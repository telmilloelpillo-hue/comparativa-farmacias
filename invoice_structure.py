"""
invoice_structure.py — Reconstrucción estructural geométrica de facturas

Detecta automáticamente el tipo de factura (A/B/C/D) según presencia de
líneas visibles y reconstruye filas/columnas mediante análisis geométrico.
Genera un bloque de contexto estructural que se inyecta al prompt de
Claude/Qwen SIN modificar la extracción semántica existente.

Tipos de documento:
  A — líneas verticales visibles
  B — líneas horizontales visibles
  C — ambas (tabla completa)
  D — sin líneas visibles (estructura implícita, más común en fotos)

Uso:
    from invoice_structure import analyze_document
    struct = analyze_document(image_bytes, paddle_boxes_or_None)
    ocr_text = struct.prompt_context + "\\n\\n" + ocr_text
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np

# ─── Constantes ───────────────────────────────────────────────────────────────

_DOC_TYPE_LABELS = {
    'A': 'Con líneas verticales',
    'B': 'Con líneas horizontales',
    'C': 'Con tabla completa (V+H)',
    'D': 'Sin líneas visibles — estructura inferida',
}

# Número mínimo de líneas "significativas" para clasificar como A/B/C
_MIN_H_LINES = 2
_MIN_V_LINES = 1


# ─── Data structures ──────────────────────────────────────────────────────────

@dataclass
class TextBox:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str = ''
    confidence: float = 1.0

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def w(self) -> float:
        return self.x1 - self.x0

    @property
    def h(self) -> float:
        return self.y1 - self.y0


@dataclass
class StructuralAnalysis:
    doc_type: str = 'D'
    img_w: int = 0
    img_h: int = 0
    h_lines_count: int = 0
    v_lines_count: int = 0
    text_boxes: List[TextBox] = field(default_factory=list)
    rows: List[List[TextBox]] = field(default_factory=list)
    col_boundaries: List[float] = field(default_factory=list)
    col_labels: List[str] = field(default_factory=list)
    table_rows: List[dict] = field(default_factory=list)
    confidence: dict = field(default_factory=lambda: {
        'geometric': 0.0, 'rows': 0.0, 'columns': 0.0, 'overall': 0.0
    })
    prompt_context: str = ''


# ─── FASE 1 — Detección de líneas ─────────────────────────────────────────────

def _detect_table_lines(gray: np.ndarray) -> Tuple[List, List]:
    """
    Detecta líneas horizontales y verticales de tabla con dos métodos:
    1. Canny + HoughLinesP  → bueno en documentos impresos
    2. Operaciones morfológicas → bueno en fotos con ruido

    Retorna (h_lines, v_lines) como listas de (x1, y1, x2, y2).
    """
    img_h, img_w = gray.shape
    h_lines: List = []
    v_lines: List = []

    # — Método 1: Hough —
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(blurred, 50, 150, apertureSize=3)
    min_h_len = img_w * 0.18
    min_v_len = img_h * 0.10

    raw = cv2.HoughLinesP(
        edges, 1, np.pi / 180,
        threshold=55,
        minLineLength=max(int(min(min_h_len, min_v_len)), 20),
        maxLineGap=30,
    )
    if raw is not None:
        for ln in raw:
            x1, y1, x2, y2 = ln[0]
            dx, dy = abs(x2 - x1), abs(y2 - y1)
            if dx == 0 and dy == 0:
                continue
            angle = np.degrees(np.arctan2(dy, dx + 1e-9))
            length = np.hypot(dx, dy)
            if angle < 15 and length >= min_h_len:
                h_lines.append((x1, y1, x2, y2))
            elif angle > 75 and length >= min_v_len:
                v_lines.append((x1, y1, x2, y2))

    # — Método 2: morfológico (complementa Hough) —
    fg = 255 - gray if float(gray.mean()) > 128 else gray.copy()

    # Líneas horizontales
    kh = cv2.getStructuringElement(cv2.MORPH_RECT, (max(int(img_w * 0.18), 25), 1))
    hm = cv2.morphologyEx(fg, cv2.MORPH_OPEN, kh)
    cnts_h, _ = cv2.findContours(hm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in cnts_h:
        x, y, cw, ch = cv2.boundingRect(cnt)
        if cw >= img_w * 0.18 and ch <= max(4, int(img_h * 0.005)):
            h_lines.append((x, y + ch // 2, x + cw, y + ch // 2))

    # Líneas verticales
    kv = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(int(img_h * 0.10), 20)))
    vm = cv2.morphologyEx(fg, cv2.MORPH_OPEN, kv)
    cnts_v, _ = cv2.findContours(vm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in cnts_v:
        x, y, cw, ch = cv2.boundingRect(cnt)
        if ch >= img_h * 0.10 and cw <= max(4, int(img_w * 0.005)):
            v_lines.append((x + cw // 2, y, x + cw // 2, y + ch))

    h_lines = _dedup_lines(h_lines, axis='h', tol=6)
    v_lines = _dedup_lines(v_lines, axis='v', tol=6)
    return h_lines, v_lines


def _dedup_lines(lines: List, axis: str, tol: int = 6) -> List:
    """Elimina líneas duplicadas que están a < tol píxeles entre sí."""
    if not lines:
        return []
    if axis == 'h':
        key = lambda l: (l[1] + l[3]) / 2
    else:
        key = lambda l: (l[0] + l[2]) / 2
    lines_s = sorted(lines, key=key)
    result = [lines_s[0]]
    for ln in lines_s[1:]:
        if abs(key(ln) - key(result[-1])) > tol:
            result.append(ln)
    return result


# ─── FASE 2 — Clasificación del tipo de documento ─────────────────────────────

def _classify_doc_type(h_lines: List, v_lines: List,
                       img_h: int, img_w: int) -> str:
    """Clasifica como A/B/C/D según líneas significativas detectadas."""
    sig_h = [l for l in h_lines if abs(l[2] - l[0]) >= img_w * 0.22]
    sig_v = [l for l in v_lines if abs(l[3] - l[1]) >= img_h * 0.12]
    has_h = len(sig_h) >= _MIN_H_LINES
    has_v = len(sig_v) >= _MIN_V_LINES
    if has_h and has_v:
        return 'C'
    if has_v:
        return 'A'
    if has_h:
        return 'B'
    return 'D'


# ─── FASE 3 — Detección de regiones de texto desde imagen ─────────────────────

def _detect_text_boxes(gray: np.ndarray) -> List[TextBox]:
    """
    Detecta bounding boxes de regiones de texto mediante threshold adaptativo
    y morfología. No requiere OCR — devuelve geometría sin contenido textual.
    Robusto a sombras, blur e inclinaciones.
    """
    img_h, img_w = gray.shape

    # Normalizar iluminación antes de umbralizar
    normalized = cv2.equalizeHist(gray)

    thresh = cv2.adaptiveThreshold(
        normalized, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        15, 8,
    )

    # Cerrar caracteres en palabras (kernel horizontal)
    word_k = cv2.getStructuringElement(cv2.MORPH_RECT, (18, 2))
    word_blobs = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, word_k)

    contours, _ = cv2.findContours(word_blobs, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    boxes: List[TextBox] = []
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        # Filtrar ruido (<8px ancho, <4px alto) y bloques grandes (logotipos, bordes)
        if cw < 8 or ch < 4:
            continue
        if ch > img_h * 0.08 or cw > img_w * 0.88:
            continue
        ar = cw / (ch + 1e-6)
        if ar < 0.25 or ar > 130:
            continue
        boxes.append(TextBox(x0=float(x), y0=float(y),
                             x1=float(x + cw), y1=float(y + ch)))
    return boxes


# ─── FASE 4 — Clustering de filas por Y ───────────────────────────────────────

def _cluster_rows(boxes: List[TextBox], img_h: int) -> List[List[TextBox]]:
    """
    Agrupa TextBoxes en filas usando distancia adaptativa en el eje Y.
    El epsilon se adapta a la altura mediana de los boxes detectados.
    Tolerante a perspectiva imperfecta y skew.
    """
    if not boxes:
        return []

    heights = [b.h for b in boxes]
    median_h = float(np.median(heights)) if heights else img_h * 0.018
    eps = max(median_h * 0.80, img_h * 0.009, 4.0)

    sorted_boxes = sorted(boxes, key=lambda b: b.cy)
    rows: List[List[TextBox]] = []
    current: List[TextBox] = [sorted_boxes[0]]
    row_y = sorted_boxes[0].cy

    for box in sorted_boxes[1:]:
        if abs(box.cy - row_y) <= eps:
            current.append(box)
            row_y = float(np.mean([b.cy for b in current]))
        else:
            rows.append(sorted(current, key=lambda b: b.cx))
            current = [box]
            row_y = box.cy

    if current:
        rows.append(sorted(current, key=lambda b: b.cx))

    return rows


# ─── FASE 5 — Detección de columnas por distribución X ────────────────────────

def _detect_col_boundaries(rows: List[List[TextBox]], img_w: int) -> List[float]:
    """
    Infiere los límites de columna a partir de la distribución X de los boxes.
    Busca gaps significativos (>2.5% del ancho) en los bordes izquierdos de texto.
    Solo conserva gaps que aparecen en al menos el 15% de las filas.
    """
    if len(rows) < 2:
        return []

    x_starts = [b.x0 for row in rows for b in row]
    if len(x_starts) < 5:
        return []

    x_sorted = sorted(x_starts)
    min_gap = img_w * 0.025
    raw_gaps: List[float] = []
    for i in range(1, len(x_sorted)):
        if x_sorted[i] - x_sorted[i - 1] > min_gap:
            raw_gaps.append((x_sorted[i - 1] + x_sorted[i]) / 2)

    # Fusionar gaps cercanos (< 2% de ancho)
    merged: List[float] = []
    for g in raw_gaps:
        if not merged or g - merged[-1] > img_w * 0.02:
            merged.append(g)
        else:
            merged[-1] = (merged[-1] + g) / 2

    # Filtrar: solo gaps con soporte en ≥15% de las filas
    n_rows = len(rows)
    strong: List[float] = []
    for g in merged:
        support = sum(
            1 for row in rows
            if any(abs(b.x0 - g) < img_w * 0.018 for b in row)
        )
        if support >= max(2, int(n_rows * 0.15)):
            strong.append(g)

    return sorted(strong)


# ─── Etiquetado semántico de columnas ─────────────────────────────────────────

def _label_columns(boundaries: List[float], img_w: int) -> List[str]:
    """
    Asigna etiquetas semánticas a las columnas detectadas basándose en su
    posición relativa dentro del documento (patrón típico de facturas farmacia).
    """
    n = len(boundaries) + 1
    if n <= 1:
        return ['contenido']

    # Anchos de cada columna
    b_full = [0.0] + list(boundaries) + [float(img_w)]
    widths = [b_full[i + 1] - b_full[i] for i in range(n)]
    max_w = max(widths)

    labels: List[str] = []
    for i, w in enumerate(widths):
        if i == 0:
            labels.append('codigo')
        elif w == max_w:
            labels.append('descripcion')
        else:
            # Columnas derechas: precio / descuento / total / coste
            right_pos = n - 1 - i
            right_map = {0: 'coste_unitario', 1: 'total',
                         2: 'importe_venta', 3: 'descuento', 4: 'cantidad'}
            labels.append(right_map.get(right_pos, f'col{i}'))

    return labels


# ─── FASE 6 — Reconstrucción de tabla con texto ────────────────────────────────

def _assign_to_columns(row: List[TextBox],
                       col_boundaries: List[float]) -> dict:
    """Asigna cada TextBox al índice de columna que le corresponde por X."""
    n_cols = len(col_boundaries) + 1
    cells: dict = {i: [] for i in range(n_cols)}

    for box in row:
        col_idx = 0
        for gx in col_boundaries:
            if box.cx > gx:
                col_idx += 1
            else:
                break
        cells[min(col_idx, n_cols - 1)].append(box)

    result: dict = {}
    for idx, bxs in cells.items():
        if bxs:
            bxs.sort(key=lambda b: b.cx)
            txt = ' '.join(b.text for b in bxs if b.text).strip()
            if txt:
                result[idx] = txt
    return result


def _build_table_rows(rows: List[List[TextBox]],
                      col_boundaries: List[float],
                      col_labels: List[str]) -> List[dict]:
    """Construye filas estructuradas asignando texto a etiquetas de columna."""
    table: List[dict] = []
    for row_idx, row in enumerate(rows):
        cells_by_idx = _assign_to_columns(row, col_boundaries)

        labeled: dict = {}
        for idx, text in cells_by_idx.items():
            label = col_labels[idx] if idx < len(col_labels) else f'col{idx}'
            labeled[label] = text

        key_present = sum(1 for k in ('codigo', 'descripcion')
                          if labeled.get(k, ''))
        conf = round(key_present / 2, 2)
        raw = ' | '.join(t for t in cells_by_idx.values() if t)

        table.append({
            'row': row_idx + 1,
            'cells': labeled,
            'raw_text': raw,
            'confidence': conf,
        })
    return table


# ─── FASE 7 — Confidence scoring ──────────────────────────────────────────────

def _compute_confidence(doc_type: str, h_lines: List, v_lines: List,
                        rows: List, col_boundaries: List) -> dict:
    if doc_type == 'C':
        geo = 0.95
    elif doc_type in ('A', 'B'):
        geo = 0.82
    else:
        geo = 0.52   # Tipo D: estructura inferida

    # Confianza de filas: regularidad en el espaciado
    if len(rows) >= 3:
        ys = sorted(float(np.mean([b.cy for b in r])) for r in rows)
        diffs = np.diff(ys)
        mean_d = float(np.mean(diffs)) if len(diffs) else 1
        std_d = float(np.std(diffs)) if len(diffs) else 0
        row_conf = min(0.95, 0.5 + 0.45 * max(0, 1 - std_d / (mean_d + 1e-6)))
    else:
        row_conf = 0.35

    # Confianza de columnas: número de límites detectados
    col_conf = min(0.90, 0.25 + 0.13 * len(col_boundaries))

    overall = round(0.35 * geo + 0.35 * row_conf + 0.30 * col_conf, 3)
    return {
        'geometric': round(geo, 3),
        'rows': round(row_conf, 3),
        'columns': round(col_conf, 3),
        'overall': overall,
    }


# ─── FASE 8 — Generación de contexto para el prompt ──────────────────────────

def _build_prompt_context(analysis: 'StructuralAnalysis') -> str:
    c = analysis.confidence
    doc_desc = _DOC_TYPE_LABELS.get(analysis.doc_type, analysis.doc_type)
    lines: List[str] = [
        '=== ANÁLISIS ESTRUCTURAL DEL DOCUMENTO ===',
        f'Tipo {analysis.doc_type}: {doc_desc}',
        (f'Imagen: {analysis.img_w}×{analysis.img_h}px  '
         f'| Líneas H detectadas: {analysis.h_lines_count}  '
         f'| Líneas V detectadas: {analysis.v_lines_count}'),
        (f'Confianza — geométrica: {c["geometric"]:.0%}  '
         f'| filas: {c["rows"]:.0%}  '
         f'| columnas: {c["columns"]:.0%}  '
         f'| global: {c["overall"]:.0%}'),
        (f'Filas geométricas detectadas: {len(analysis.rows)}  '
         f'| Columnas inferidas: {len(analysis.col_labels)}'),
    ]

    if analysis.col_labels:
        lines.append('Columnas (izq→der): ' + ' | '.join(analysis.col_labels))

    if analysis.table_rows:
        lines += [
            '',
            '=== TABLA RECONSTRUIDA ===',
            ('INSTRUCCIÓN: usa esta estructura para asociar correctamente cada '
             'código con su descripción y sus valores. Si hay celdas vacías, '
             'el artículo puede ser promocional o sin valor comercial.'),
            '',
        ]
        for row in analysis.table_rows:
            flag = ' [low_conf]' if row['confidence'] < 0.5 else ''
            parts = [f'{lbl}: «{txt}»'
                     for lbl, txt in row['cells'].items() if txt]
            if parts:
                lines.append(f'Fila {row["row"]}{flag}: ' + ' | '.join(parts))
        lines.append('')

    if analysis.doc_type == 'D':
        lines.append(
            '⚠ Sin líneas visibles: estructura inferida geométricamente. '
            'Si no coincide con la imagen, prevalece lo visual.'
        )

    lines.append('=== FIN ANÁLISIS ESTRUCTURAL ===')
    return '\n'.join(lines)


# ─── Punto de entrada principal ───────────────────────────────────────────────

def analyze_document(image_bytes: bytes,
                     paddle_boxes: Optional[list] = None) -> StructuralAnalysis:
    """
    Analiza la estructura geométrica del documento a partir de bytes de imagen.

    Args:
        image_bytes  : JPEG/PNG ya preprocesados por preprocess_image().
        paddle_boxes : Lista opcional de (bbox, (text, conf)) de PaddleOCR.
                       Si se proveen, la reconstrucción de tabla incluye texto.
                       Sin ellos se detectan posiciones pero sin contenido.

    Returns:
        StructuralAnalysis con .prompt_context listo para inyectar al prompt.
        Si falla cualquier paso, devuelve análisis parcial sin romper el pipeline.
    """
    analysis = StructuralAnalysis()
    try:
        arr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return analysis

        img_h, img_w = img.shape[:2]
        analysis.img_h, analysis.img_w = img_h, img_w
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Fase 1: líneas
        h_lines, v_lines = _detect_table_lines(gray)
        analysis.h_lines_count = len(h_lines)
        analysis.v_lines_count = len(v_lines)

        # Fase 2: tipo de documento
        analysis.doc_type = _classify_doc_type(h_lines, v_lines, img_h, img_w)

        # Fase 3: boxes de texto
        if paddle_boxes:
            boxes = []
            for bbox, (text, conf) in paddle_boxes:
                xs = [p[0] for p in bbox]
                ys = [p[1] for p in bbox]
                boxes.append(TextBox(
                    x0=float(min(xs)), y0=float(min(ys)),
                    x1=float(max(xs)), y1=float(max(ys)),
                    text=str(text), confidence=float(conf),
                ))
        else:
            boxes = _detect_text_boxes(gray)
        analysis.text_boxes = boxes

        # Fase 4: agrupación en filas
        analysis.rows = _cluster_rows(boxes, img_h)

        # Fase 5: límites de columna
        if analysis.doc_type == 'A' and v_lines:
            # Tipo A: usar posiciones X de las líneas verticales como límites
            v_xs = sorted({(l[0] + l[2]) / 2 for l in v_lines})
            analysis.col_boundaries = v_xs[1:]  # saltar borde izquierdo
        else:
            analysis.col_boundaries = _detect_col_boundaries(analysis.rows, img_w)

        # Fase 5b: etiquetas semánticas
        analysis.col_labels = _label_columns(analysis.col_boundaries, img_w)

        # Fase 6: reconstrucción de tabla (solo si hay texto de PaddleOCR)
        if paddle_boxes and analysis.rows and analysis.col_boundaries:
            analysis.table_rows = _build_table_rows(
                analysis.rows, analysis.col_boundaries, analysis.col_labels
            )

        # Fase 7: confianza
        analysis.confidence = _compute_confidence(
            analysis.doc_type, h_lines, v_lines,
            analysis.rows, analysis.col_boundaries,
        )

        # Fase 8: contexto para el prompt
        analysis.prompt_context = _build_prompt_context(analysis)

    except Exception:
        # Fallback silencioso: el análisis es siempre opcional
        analysis.prompt_context = ''

    return analysis
