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

_INVOICE_PROMPT = (
    "Analiza esta factura o albarán de farmacia española y extrae los datos de las líneas de producto.\n\n"
    "Devuelve ÚNICAMENTE un objeto JSON con esta estructura exacta (sin texto adicional, sin markdown):\n"
    "{\n"
    '  "proveedor": "nombre del proveedor/laboratorio o null",\n'
    '  "numero_factura": "número o null",\n'
    '  "fecha": "DD/MM/YYYY o null",\n'
    '  "lineas": [\n'
    "    {\n"
    '      "cn": "código del producto EXACTAMENTE como aparece en el documento — puede ser alfanumérico: P0018200, 221193.3, 221724.T, 221194, etc. — NUNCA inventes ni normalices el código — null si no hay código",\n'
    '      "nombre": "descripción completa del producto",\n'
    '      "cantidad": número entero,\n'
    '      "precio_neto_unitario": número decimal (ver REGLAS),\n'
    '      "precio_neto_total": número decimal o null,\n'
    '      "iva_porcentaje": 4 o 5 o 10 o 21 o 0,\n'
    '      "recargo": número decimal o 0,\n'
    '      "sin_valor_comercial": true si el precio aparece como "S/VALOR COMERCIAL", false en caso contrario\n'
    "    }\n"
    "  ],\n"
    '  "total_sin_iva": número decimal o null,\n'
    '  "total_con_iva": número decimal o null\n'
    "}\n\n"
    "REGLAS CRÍTICAS:\n"
    "- cn: copia el código EXACTAMENTE como aparece en el documento. Si tiene letras, puntos o prefijos (P00, KL...) consérvelos tal cual. NUNCA inventes un formato de 7 dígitos si no es lo que aparece\n"
    "- Incluye TODAS las líneas de producto, incluyendo gratuitas ('S/VALOR COMERCIAL', material promocional, expositores, displays)\n"
    "- Para líneas con 'S/VALOR COMERCIAL': precio_neto_unitario = 0, sin_valor_comercial = true, iva_porcentaje = 0\n"
    "- precio_neto_unitario: usa el COSTE UNITARIO (precio tras todos los descuentos aplicados). "
    "En albaranes Pierre Fabre, Almirall y similares existe columna 'COSTE UNITARIO' — usa ESE valor, NO el 'PRECIO UNID' bruto previo al descuento. "
    "Si solo aparece un precio y hay descuento explícito, calcula: precio_neto = precio_bruto × (1 - descuento/100)\n"
    "- precio_neto_total = precio_neto_unitario × cantidad\n"
    "- iva_porcentaje: % real de IVA de la línea (4, 5, 10 o 21). Para artículos sin valor comercial: 0\n"
    "- cantidad mínima 1 si no se especifica\n"
    "- Números con punto como separador decimal, sin puntos de miles\n"
    "- NO incluyas: subtotales de sección, líneas de IVA, portes, cabeceras de tabla"
)


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
                    qwen_endpoint: str | None = None) -> dict:
    """
    Pipeline completo:
      1. OpenCV preprocessing (imágenes) / extracción texto (PDFs)
      2. PaddleOCR (si disponible)
      3. Qwen2-VL API  →  fallback Claude Haiku

    Devuelve dict con campos de factura + 'pipeline_used' para debug.
    """
    ocr_text = ''
    is_pdf = (mime == 'application/pdf')

    if is_pdf:
        # Extrae texto nativo con pdfplumber
        import pdfplumber, io
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            pages_text = []
            for page in pdf.pages[:3]:   # primeras 3 páginas
                t = page.extract_text()
                if t:
                    pages_text.append(t)
            ocr_text = '\n\n'.join(pages_text)
        # Renderiza primera página para visión
        image_bytes = pdf_first_page_image(file_bytes)
        if not image_bytes:
            image_bytes = file_bytes   # fallback: mandar PDF directamente
            preprocessed = False
        else:
            image_bytes = preprocess_image(image_bytes)
            preprocessed = True
    else:
        # Imagen: preprocessing completo
        image_bytes = preprocess_image(file_bytes)
        preprocessed = True
        # PaddleOCR sobre imagen preprocesada
        ocr_text = run_paddleocr(image_bytes)

    # Análisis estructural (FASES 1–8 de invoice_structure) — siempre opcional
    try:
        from invoice_structure import analyze_document as _analyze_struct
        _paddle_boxes = (run_paddleocr_boxes(image_bytes)
                         if _PADDLE_OK and not is_pdf else [])
        _struct = _analyze_struct(image_bytes, _paddle_boxes or None)
        if _struct.prompt_context:
            ocr_text = (_struct.prompt_context
                        + ('\n\n' + ocr_text if ocr_text else ''))
    except Exception:
        pass  # nunca bloquea el pipeline principal

    # Semántica: Qwen2-VL o Claude
    if qwen_key and image_bytes and not (is_pdf and not preprocessed):
        result = extract_with_qwen(image_bytes, ocr_text, qwen_key, qwen_endpoint)
        result['pipeline_used'] = (
            f"opencv+{'paddleocr+' if _PADDLE_OK and not is_pdf else ''}qwen2-vl"
        )
    elif is_pdf and not preprocessed:
        # PDF sin imagen: mandar PDF binario a Claude (ruta original)
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
        result['pipeline_used'] = (
            f"opencv+{'paddleocr+' if _PADDLE_OK and not is_pdf else ''}claude-haiku"
        )

    return result
