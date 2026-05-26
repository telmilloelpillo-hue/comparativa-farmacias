"""
invoice_ocr.py — Pipeline OCR para facturas de farmacia

Flujo:
  1. preprocess_image()   → OpenCV: deskew, sombras, ruido, contraste
  2. run_paddleocr()      → texto + coordenadas (opcional, graceful fallback)
  3. extract_semantic()   → Qwen2-VL vía API (Together.ai / HuggingFace)
                            Fallback: Claude Haiku si no hay QWEN_API_KEY

PDF: pdfplumber extrae texto + renderiza primera página como imagen para Qwen.
"""

import base64
import json
import os
import re
import tempfile

import cv2
import numpy as np

# ─── PaddleOCR (opcional) ─────────────────────────────────────────────────────
try:
    from paddleocr import PaddleOCR as _PaddleOCR
    _PADDLE_OK = True
except ImportError:
    _PADDLE_OK = False

_paddle_instance = None


def _get_paddle():
    global _paddle_instance
    if _paddle_instance is None:
        _paddle_instance = _PaddleOCR(use_angle_cls=True, lang='es', show_log=False)
    return _paddle_instance


# ─── Preprocessing OpenCV ─────────────────────────────────────────────────────

def preprocess_image(image_bytes: bytes) -> bytes:
    """
    Aplica pipeline OpenCV completo a bytes de imagen.
    Devuelve JPEG bytes listos para OCR.
    """
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return image_bytes

    # 1 — Resize: max 1500 px (suficiente para OCR; 3000px hacía timeout en Render)
    h, w = img.shape[:2]
    if max(h, w) > 1500:
        scale = 1500 / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)),
                         interpolation=cv2.INTER_AREA)

    # 2 — Corrección de perspectiva (encuentra el documento en la foto)
    img = _perspective_correction(img)

    # 3 — Eliminación de sombras por canal
    img = _remove_shadows(img)

    # 4 — Deskew (corrección de inclinación de texto)
    img = _deskew(img)

    # 5 — Suavizado ligero (fastNlMeansDenoisingColored es demasiado lento en prod)
    img = cv2.GaussianBlur(img, (3, 3), 0)

    # 6 — Mejora de contraste adaptativa (CLAHE en canal L del espacio LAB)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    lab = cv2.merge((clahe.apply(l), a, b))
    img = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

    _, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return buf.tobytes()


def _perspective_correction(img: np.ndarray) -> np.ndarray:
    """
    Detecta los 4 vértices del documento en la imagen y aplica perspectiva.
    Si no detecta documento rectangular, devuelve la imagen sin cambios.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 75, 200)

    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)

    doc_cnt = None
    for cnt in contours[:5]:
        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
        # Solo aceptamos cuadriláteros que ocupen >20 % del área de la imagen
        if len(approx) == 4:
            area_ratio = cv2.contourArea(cnt) / (img.shape[0] * img.shape[1])
            if area_ratio > 0.20:
                doc_cnt = approx
                break

    if doc_cnt is None:
        return img

    pts = doc_cnt.reshape(4, 2).astype(np.float32)
    # Ordenar: top-left, top-right, bottom-right, bottom-left
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1)
    ordered = np.array([
        pts[np.argmin(s)],
        pts[np.argmin(diff)],
        pts[np.argmax(s)],
        pts[np.argmax(diff)],
    ], dtype=np.float32)

    w_top = np.linalg.norm(ordered[1] - ordered[0])
    w_bot = np.linalg.norm(ordered[2] - ordered[3])
    h_lft = np.linalg.norm(ordered[3] - ordered[0])
    h_rgt = np.linalg.norm(ordered[2] - ordered[1])
    W, H = int(max(w_top, w_bot)), int(max(h_lft, h_rgt))

    if W < 100 or H < 100:
        return img

    dst = np.array([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]],
                   dtype=np.float32)
    M = cv2.getPerspectiveTransform(ordered, dst)
    return cv2.warpPerspective(img, M, (W, H))


def _remove_shadows(img: np.ndarray) -> np.ndarray:
    """Normaliza iluminación no uniforme y elimina sombras por canal."""
    channels = cv2.split(img)
    result = []
    kernel = np.ones((21, 21), np.uint8)
    for ch in channels:
        bg = cv2.dilate(ch, kernel)
        bg = cv2.GaussianBlur(bg, (21, 21), 0)
        diff = 255 - cv2.absdiff(ch, bg)
        norm = cv2.normalize(diff, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
        result.append(norm)
    return cv2.merge(result)


def _deskew(img: np.ndarray) -> np.ndarray:
    """Detecta ángulo de inclinación y lo corrige (solo entre 0.5° y 15°)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    thresh = cv2.threshold(255 - gray, 0, 255,
                           cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(thresh > 0))
    if len(coords) < 200:
        return img
    angle = cv2.minAreaRect(coords)[-1]
    angle = -(90 + angle) if angle < -45 else -angle
    if abs(angle) < 0.5 or abs(angle) > 15:
        return img
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
    return cv2.warpAffine(img, M, (w, h),
                          flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)


# ─── PaddleOCR ────────────────────────────────────────────────────────────────

def run_paddleocr(image_bytes: bytes) -> str:
    """
    Extrae texto con PaddleOCR. Devuelve string vacío si no está disponible.
    Filtra líneas con confianza < 0.5.
    """
    if not _PADDLE_OK:
        return ''
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
        tmp.write(image_bytes)
        tmp_path = tmp.name
    try:
        result = _get_paddle().ocr(tmp_path, cls=True)
        lines = []
        if result and result[0]:
            for box, (text, conf) in result[0]:
                if conf >= 0.5:
                    lines.append(text)
        return '\n'.join(lines)
    except Exception:
        return ''
    finally:
        os.unlink(tmp_path)


def run_paddleocr_boxes(image_bytes: bytes) -> list:
    """
    Variante de run_paddleocr que devuelve (bbox, (text, conf)) en lugar de
    texto plano. Necesario para que invoice_structure.py pueda reconstruir la
    tabla con coordenadas + texto.
    """
    if not _PADDLE_OK:
        return []
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
        tmp.write(image_bytes)
        tmp_path = tmp.name
    try:
        result = _get_paddle().ocr(tmp_path, cls=True)
        if result and result[0]:
            return [(box, (text, conf))
                    for box, (text, conf) in result[0]
                    if conf >= 0.5]
        return []
    except Exception:
        return []
    finally:
        os.unlink(tmp_path)


# ─── PDF → imagen primera página ─────────────────────────────────────────────

def pdf_first_page_image(pdf_bytes: bytes, dpi: int = 150) -> bytes:
    """
    Renderiza la primera página de un PDF como imagen JPEG.
    Usa pdfplumber (no requiere dependencias extra).
    Devuelve bytes vacíos si falla.
    """
    try:
        import pdfplumber
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name
        try:
            with pdfplumber.open(tmp_path) as pdf:
                if not pdf.pages:
                    return b''
                page_img = pdf.pages[0].to_image(resolution=dpi)
                buf = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
                buf.close()
                page_img.save(buf.name)
                with open(buf.name, 'rb') as f:
                    img_bytes = f.read()
                os.unlink(buf.name)
                return img_bytes
        finally:
            os.unlink(tmp_path)
    except Exception:
        return b''


# ─── Extracción semántica ─────────────────────────────────────────────────────

_INVOICE_PROMPT = """Analiza esta factura o albarán de farmacia española y extrae los datos de las líneas de producto.

Devuelve ÚNICAMENTE un objeto JSON con esta estructura exacta (sin texto adicional, sin markdown):
{
  "proveedor": "nombre del proveedor/laboratorio o null",
  "numero_factura": "número o null",
  "fecha": "DD/MM/YYYY o null",
  "lineas": [
    {
      "cn": "código del producto EXACTAMENTE como aparece — puede ser alfanumérico — NUNCA inventes ni normalices — null si no hay código",
      "nombre": "descripción completa del producto",
      "cantidad": número entero,
      "precio_neto_unitario": número decimal (ver REGLAS),
      "precio_neto_total": número decimal o null,
      "iva_porcentaje": 4 o 5 o 10 o 21 o 0,
      "recargo": número decimal o 0,
      "sin_valor_comercial": true si el precio aparece como "S/VALOR COMERCIAL", false en caso contrario
    }
  ],
  "total_sin_iva": número decimal o null,
  "total_con_iva": número decimal o null
}

REGLAS CRÍTICAS — LEE TODAS ANTES DE EXTRAER:

1. CÓDIGO (cn):
   - Copia EXACTAMENTE el código tal como aparece en el documento (columna "Cód.", "Cod.Mater.", "CN", "Ref.", etc.)
   - Conserva letras, puntos, guiones y prefijos (P00, KL, 221193.3, 221724.T, etc.)
   - NUNCA normalices a 7 dígitos si el documento no los tiene

2. CANTIDAD — COLUMNA UDS:
   - En albaranes con tres columnas "Cajas | UDS/Caja | UDS": la cantidad es SIEMPRE el valor de "UDS" (la tercera columna, más a la derecha)
   - Si las tres muestran "0 | 0 | N", la cantidad es N (aunque las dos primeras sean cero)
   - NUNCA uses "Cajas" ni "UDS/Caja" como cantidad cuando existe columna "UDS" separada
   - Si solo hay una columna de cantidad, usa ese valor

3. PRECIO NETO UNITARIO — REGLA MÁS IMPORTANTE:
   - Usa SIEMPRE el precio YA descontado, nunca el precio bruto:
     * Columna "Precio Neto" → usa ese valor directamente (es el precio unitario después del descuento)
     * Columna "COSTE UNITARIO" (Pierre Fabre, Almirall) → usa ese valor directamente
     * Si solo hay "Precio Fact." con descuento explícito → calcula: precio_neto = precio_fact × (1 − descuento/100)
   - NUNCA uses "Precio Fact.", "Precio Unid.", "PVP", "P.V.F." ni ningún precio BRUTO como precio_neto_unitario

4. VALIDACIÓN CRUZADA OBLIGATORIA (aplica siempre que exista columna "Importe"):
   Tras extraer cada línea verifica: precio_neto_unitario × cantidad ≈ Importe (tolerancia ±0,05 €)

   Si NO coinciden, corrige en este orden:
   a) Primero intenta corregir la CANTIDAD:
      cantidad_correcta = redondear(Importe ÷ precio_neto_unitario)
      Si precio_neto_unitario × cantidad_correcta ≈ Importe → usa cantidad_correcta
   b) Si a) no resuelve, corrige el PRECIO:
      precio_neto_unitario = Importe ÷ cantidad

   Ejemplos reales de errores que DEBES detectar y autocorregir:
   · Leíste cantidad=5, precio=4,167, importe=12,50 → 4,167×5=20,84 ≠ 12,50 → ERROR
     → cantidad_correcta = redondear(12,50÷4,167) = 3 → 4,167×3=12,50 ✓
   · Leíste cantidad=1, precio=3,898, importe=23,39 → 3,898×1=3,90 ≠ 23,39 → ERROR
     → cantidad_correcta = redondear(23,39÷3,898) = 6 → 3,898×6=23,39 ✓
   · Leíste precio=5,69, cantidad=3, importe=20,06 → 5,69×3=17,07 ≠ 20,06 → ERROR
     → precio correcto = 20,06÷3 = 6,687 ✓

5. PRECIO NETO TOTAL:
   - Usa el valor de la columna "Importe" si existe
   - Si no hay columna Importe, calcula: precio_neto_total = precio_neto_unitario × cantidad

6. LÍNEAS GRATUITAS ("S/VALOR COMERCIAL", "RAPPEL", "BONIFICACIÓN", "0,000", expositores, material promocional):
   - Inclúyelas con precio_neto_unitario = 0, sin_valor_comercial = true, iva_porcentaje = 0

7. IVA — TABLA OBLIGATORIA PARA FARMACIA ESPAÑOLA:
   Si no hay columna IVA explícita en el documento, determina el % según el tipo de producto:

   21% IVA — Cosmética e higiene (la mayoría de productos de farmacia):
   · Cremas, geles de baño, champús, aceites corporales/masaje, colonias, perfumes
   · Leches hidratantes, bálsamos, pomadas cosméticas, estrías, anticeluliticos
   · Biberones, chupetes, tetinas, portadocumentos, puericultura, accesorios bebé
   · Productos de marcas: Suavinex, Chicco, Nuk, Mustela, Weleda, SVR, Nuxe, Avène
   · Todo producto con "BABY", "BIB", "CH" (chupete), "TETINA", "COL" (colonia) en el nombre
   · Protectores solares, desodorantes, maquillaje, jabones, geles íntimos

   10% IVA — Productos sanitarios específicos:
   · Apósitos, tiritas, gasas, compresas, preservativos, termómetros
   · Dispositivos médicos con marcado CE (tensiómetros, nebulizadores, etc.)

   4% IVA — Medicamentos únicamente:
   · Solo productos con número de registro de medicamento de la AEMPS
   · Generalmente tienen CN de 7 dígitos con letra inicial (P00xxxxx, etc.) o nº registro AEMPS
   · En caso de duda entre 4% y 21%: usa 21% si el producto es cosmético/parafarmacia

   Para líneas gratuitas (precio 0): iva_porcentaje = 0

8. NÚMEROS:
   - Usa punto "." como separador decimal en el JSON
   - El documento puede usar coma "," como decimal — conviértela a punto

9. EXCLUYE siempre: subtotales de sección, filas de totales IVA, portes, líneas de cabecera de tabla

EJEMPLO SUAVINEX (columnas: Cod.Mater. | Descripción | Cajas | UDS/Caja | UDS | Precio Fact. | Dcto. | Precio Neto | Importe):
  212143 | S BABY ACEITE DE MASAJE HIDRATANTE 100ML | 0 | 0 | 3 | 7,960 | 16,00% | 6,687 | 20,06
  → cn="212143", cantidad=3, precio_neto_unitario=6.687, precio_neto_total=20.06, iva_porcentaje=21
  Validación: 6.687 × 3 = 20.061 ≈ 20.06 ✓

  217167 | S SEL PORTADOCUMENTOS WONDERLAND LIB | 0 | 0 | 1 | 0,000 | — | 0,000 | 0,00
  → cn="217167", cantidad=1, precio_neto_unitario=0, sin_valor_comercial=true, iva_porcentaje=0

EJEMPLO CINFA (columnas: Código | Descripción | Unidades | PVL | %Dto | PVL Neto | %IVA | PVP+IVA | Imp.Bruto | Fec.Caduc | Lote):
  REGLA CINFA — hay 11 columnas. Lee cada fila de izquierda a derecha sin saltar columnas:
  · precio_neto_unitario = columna "PVL Neto" (precio unitario DESPUÉS del descuento)
  · cantidad = columna "Unidades"
  · iva_porcentaje = columna "%IVA" — COPIA EL VALOR EXACTO (puede ser 21% o 10%)
  · precio_neto_total = PVL Neto × Unidades (calcula tú, NO uses Imp.Bruto que es PVL×Uds sin descuento)

  2239678 | FLS CORRECTOR JUANETE TM PIE | 1 | 14,57 | 20% | 11,66 | 21% | | 14,57 | Nov-2030 | 0251101698
  → cn="2239678", cantidad=1, precio_neto_unitario=11.66, precio_neto_total=11.66, iva_porcentaje=21

  2132832 | FLS PACK FRÍO CALOR MAX | 3 | 9,00 | 20% | 7,20 | 21% | | 27,00 | Jun-2029 | 20250625
  → cn="2132832", cantidad=3, precio_neto_unitario=7.20, precio_neto_total=21.60, iva_porcentaje=21

  2105904 | MUÑE META NEOPRENO | 3 | 9,24 | 16% | 7,76 | 10% | | 27,72 | Ene-2031 | A003
  → cn="2105904", cantidad=3, precio_neto_unitario=7.76, precio_neto_total=23.28, iva_porcentaje=10
  ¡ATENCIÓN! La columna %IVA muestra 10% → usa 10%, aunque el producto sea ortopédico

  4996166 | VENDA CO BL 4,5M X 7,5CM | 5 | 2,49 | 15% | 2,12 | 10% | 3,80 | 12,45 | Ago-2028 | 2509171
  → cn="4996166", cantidad=5, precio_neto_unitario=2.12, precio_neto_total=10.60, iva_porcentaje=10

  ARTÍCULOS PROMOCIONALES Cinfa (precio 0,00, código empieza por EX0 o 0006):
  EX023937 | EXP BE+ MED ANTIESTRIAS | 1 | 0,00 | 0% | → cn="EX023937", cantidad=1, precio_neto_unitario=0, sin_valor_comercial=true, iva_porcentaje=0
  0006275 | FLS PLANTILLA FASCITIS DISPL | 1 | 0,00 | 0% | → cn="0006275", cantidad=1, precio_neto_unitario=0, sin_valor_comercial=true, iva_porcentaje=0

REGLA GLOBAL CRÍTICA — IVA DESDE COLUMNA:
  Si el documento tiene columna "%IVA" o "% IVA" con valores explícitos por línea,
  SIEMPRE usa ese valor exactamente. NUNCA sobreescribas con 21% por defecto.
  La tabla de IVA de la regla 7 solo aplica cuando NO hay columna %IVA en el documento.
"""


def _clean_json(raw: str) -> dict:
    """Elimina fences de markdown y parsea JSON."""
    raw = raw.strip()
    if raw.startswith('```'):
        lines = raw.split('\n')
        end = -1 if lines[-1].strip() == '```' else len(lines)
        raw = '\n'.join(lines[1:end])
    return json.loads(raw)


def extract_with_qwen(image_bytes: bytes, ocr_text: str, api_key: str,
                      endpoint: str | None = None) -> dict:
    """
    Envía imagen + texto OCR a Qwen2-VL vía API compatible OpenAI.

    endpoint: URL base del proveedor.
      - Together.ai:   https://api.together.xyz/v1  (modelo: Qwen/Qwen2-VL-72B-Instruct)
      - HuggingFace:   https://api-inference.huggingface.co/v1  (modelo: Qwen/Qwen2-VL-7B-Instruct)
      Por defecto usa Together.ai.
    """
    import requests

    base = (endpoint or 'https://api.together.xyz/v1').rstrip('/')
    model = ('Qwen/Qwen2-VL-7B-Instruct'
             if 'huggingface' in base
             else 'Qwen/Qwen2-VL-72B-Instruct')

    b64 = base64.b64encode(image_bytes).decode()
    full_prompt = _INVOICE_PROMPT
    if ocr_text:
        full_prompt += f'\n\nTexto extraído por OCR (usa como referencia):\n"""\n{ocr_text}\n"""'

    payload = {
        'model': model,
        'max_tokens': 4096,
        'temperature': 0.05,
        'messages': [{
            'role': 'user',
            'content': [
                {'type': 'image_url',
                 'image_url': {'url': f'data:image/jpeg;base64,{b64}'}},
                {'type': 'text', 'text': full_prompt},
            ],
        }],
    }
    resp = requests.post(
        f'{base}/chat/completions',
        headers={'Authorization': f'Bearer {api_key}',
                 'Content-Type': 'application/json'},
        json=payload,
        timeout=90,
    )
    resp.raise_for_status()
    raw = resp.json()['choices'][0]['message']['content']
    return _clean_json(raw)


def extract_with_openai(image_bytes: bytes, ocr_text: str,
                        api_key: str) -> dict:
    """Extracción semántica con GPT-4o (imagen original sin preprocessing)."""
    try:
        import openai as _openai
    except ImportError:
        raise RuntimeError('openai package not installed')

    client = _openai.OpenAI(api_key=api_key)
    prompt = _INVOICE_PROMPT
    if ocr_text:
        prompt += f'\n\nTexto nativo del PDF (referencia exacta):\n"""\n{ocr_text}\n"""'

    # Construir content: imagen si hay bytes, texto siempre
    content = []
    if image_bytes:
        b64 = base64.b64encode(image_bytes).decode()
        content.append({
            'type': 'image_url',
            'image_url': {'url': f'data:image/jpeg;base64,{b64}', 'detail': 'high'},
        })
    content.append({'type': 'text', 'text': prompt})

    response = client.chat.completions.create(
        model='gpt-4o',
        max_tokens=4096,
        temperature=0.05,
        messages=[{'role': 'user', 'content': content}],
    )
    return _clean_json(response.choices[0].message.content)


def extract_with_claude(image_bytes: bytes, ocr_text: str,
                        api_key: str, mime: str = 'image/jpeg') -> dict:
    """Fallback: extracción semántica con Claude Haiku."""
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    b64 = base64.b64encode(image_bytes).decode()
    prompt = _INVOICE_PROMPT
    if ocr_text:
        prompt += f'\n\nTexto extraído por OCR:\n"""\n{ocr_text}\n"""'
    msg = client.messages.create(
        model='claude-haiku-4-5-20251001',
        max_tokens=8192,
        messages=[{'role': 'user', 'content': [
            {'type': 'image', 'source': {'type': 'base64',
                                         'media_type': mime, 'data': b64}},
            {'type': 'text', 'text': prompt},
        ]}],
    )
    return _clean_json(msg.content[0].text)


# ─── Pipeline principal ───────────────────────────────────────────────────────

def process_invoice(file_bytes: bytes, mime: str,
                    anthropic_key: str,
                    qwen_key: str | None = None,
                    qwen_endpoint: str | None = None,
                    openai_key: str | None = None) -> dict:
    """
    Pipeline completo con dos rutas según el modelo disponible:

    RUTA A — GPT-4o (si hay openai_key):
      · Imagen original sin ningún preprocesado → GPT-4o la lee nativamente
      · PDF: pdfplumber extrae texto limpio + imagen renderizada a 200 DPI sin OpenCV
      · NO se pasa texto PaddleOCR (evita contaminar con OCR erróneo)

    RUTA B — Fallback (Qwen / Claude Haiku):
      · OpenCV preprocessing + PaddleOCR como texto auxiliar (modelos débiles lo necesitan)
    """
    is_pdf = (mime == 'application/pdf')

    # ── RUTA A: GPT-4o — imagen original, sin preprocessing ───────────────────
    if openai_key:
        if is_pdf:
            import pdfplumber, io
            # Texto nativo pdfplumber (limpio, sin OCR) como contexto adicional
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                pages_text = [p.extract_text() for p in pdf.pages[:3] if p.extract_text()]
            pdf_text = '\n\n'.join(pages_text)
            # Imagen a 200 DPI sin OpenCV
            image_bytes = pdf_first_page_image(file_bytes, dpi=200)
            if not image_bytes:
                # PDF sin imagen renderizable: mandar texto solo
                result = extract_with_openai(b'', pdf_text, openai_key)
                result['pipeline_used'] = 'pdfplumber+gpt-4o'
                return result
            result = extract_with_openai(image_bytes, pdf_text, openai_key)
            result['pipeline_used'] = 'pdfplumber+gpt-4o'
        else:
            # Foto: mandar bytes originales directamente, sin OpenCV, sin PaddleOCR
            result = extract_with_openai(file_bytes, '', openai_key)
            result['pipeline_used'] = 'gpt-4o-direct'
        return result

    # ── RUTA B: Fallback con OpenCV + PaddleOCR ───────────────────────────────
    ocr_text = ''
    if is_pdf:
        import pdfplumber, io
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            pages_text = [p.extract_text() for p in pdf.pages[:3] if p.extract_text()]
            ocr_text = '\n\n'.join(pages_text)
        image_bytes = pdf_first_page_image(file_bytes)
        if not image_bytes:
            image_bytes = file_bytes
            preprocessed = False
        else:
            image_bytes = preprocess_image(image_bytes)
            preprocessed = True
    else:
        image_bytes = preprocess_image(file_bytes)
        preprocessed = True
        ocr_text = run_paddleocr(image_bytes)

    try:
        from invoice_structure import analyze_document as _analyze_struct
        _paddle_boxes = run_paddleocr_boxes(image_bytes) if _PADDLE_OK and not is_pdf else []
        _struct = _analyze_struct(image_bytes, _paddle_boxes or None)
        if _struct.prompt_context:
            ocr_text = _struct.prompt_context + ('\n\n' + ocr_text if ocr_text else '')
    except Exception:
        pass

    ocr_prefix = 'opencv+' + ('paddleocr+' if _PADDLE_OK and not is_pdf else '')

    if qwen_key and image_bytes and not (is_pdf and not preprocessed):
        result = extract_with_qwen(image_bytes, ocr_text, qwen_key, qwen_endpoint)
        result['pipeline_used'] = ocr_prefix + 'qwen2-vl'
    elif is_pdf and not preprocessed:
        import anthropic
        client = anthropic.Anthropic(api_key=anthropic_key)
        b64 = base64.b64encode(file_bytes).decode()
        prompt = _INVOICE_PROMPT
        if ocr_text:
            prompt += f'\n\nTexto extraído:\n"""\n{ocr_text}\n"""'
        msg = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=8192,
            messages=[{'role': 'user', 'content': [
                {'type': 'document',
                 'source': {'type': 'base64', 'media_type': 'application/pdf', 'data': b64}},
                {'type': 'text', 'text': prompt},
            ]}],
        )
        result = _clean_json(msg.content[0].text)
        result['pipeline_used'] = 'pdfplumber+claude'
    else:
        result = extract_with_claude(image_bytes or file_bytes, ocr_text,
                                     anthropic_key, mime)
        result['pipeline_used'] = ocr_prefix + 'claude-haiku'

    return result
