"""
pdf_parser.py — Parser universal para PDFs de estadísticas de ventas (Farmacias)
"""

import pdfplumber
import re
import logging
from collections import defaultdict
from datetime import date as _date

_log = logging.getLogger('pdf_parser')

# ─── Posiciones X fijas del layout ────────────────────────────────────────────

STOCK_X  = 216.00
SMIN_X   = 244.35
YEAR_X0  = 255.13
YEAR_X1  = 267.87
TOTAL_X  = 318.05

MONTH_X = [357.74, 397.42, 437.11, 476.79, 516.48, 556.16,
           595.85, 635.53, 675.22, 714.90, 754.59, 794.27]

DIGIT_W  = 4.25
X_TOL    = 1.2


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _char_clusters(row_chars, max_gap=7.0):
    """Group digit chars into word-like clusters based on X proximity."""
    digits = sorted([c for c in row_chars if c['text'].isdigit()],
                    key=lambda c: c['x0'])
    if not digits:
        return []
    groups = [[digits[0]]]
    for c in digits[1:]:
        if c['x0'] - groups[-1][-1]['x0'] <= max_gap:
            groups[-1].append(c)
        else:
            groups.append([c])
    return groups


def _digits_at(row_chars, x_anchor, max_digits=3, tol=X_TOL):
    """Read integer ending at x_anchor using cluster-based approach."""
    clusters = _char_clusters(row_chars)
    if not clusters:
        return 0
    # Find cluster whose rightmost char ends near x_anchor
    best_cluster = None
    best_dist = float('inf')
    for grp in clusters:
        right_x = grp[-1]['x0']
        dist = abs(right_x - x_anchor)
        if dist <= max(tol * 2, DIGIT_W) and dist < best_dist:
            best_dist = dist
            best_cluster = grp
    if best_cluster is None:
        return 0
    # Take at most max_digits chars from the cluster
    chars = best_cluster[-max_digits:]
    return int(''.join(c['text'] for c in chars))


def _month_value(row_chars, target_x, window=10, cutoff_x=0):
    """
    Return integer at target_x using cluster proximity.
    cutoff_x: clusters with center < cutoff_x are ignored (description zone filter).
    """
    clusters = _char_clusters(row_chars)
    if not clusters:
        return 0
    candidates = []
    for grp in clusters:
        center = (grp[0]['x0'] + grp[-1]['x0']) / 2
        if center < cutoff_x:
            continue
        dist = abs(center - target_x)
        if dist <= window:
            candidates.append((dist, grp))
    if not candidates:
        return 0
    best = min(candidates, key=lambda t: t[0])[1]
    val = int(''.join(c['text'] for c in best))
    # A year-like value (≥1900) can never be a valid monthly sale count
    return 0 if val >= 1900 else val


def _year_from_row(row_chars, yr_x0=YEAR_X0, yr_x1=YEAR_X1):
    zone = sorted(
        [c for c in row_chars if yr_x0 - 1 <= c['x0'] <= yr_x1 + 1],
        key=lambda c: c['x0']
    )
    text = ''.join(c['text'] for c in zone)
    m = re.search(r'(20\d{2})', text)
    return int(m.group(1)) if m else None


# ─── Auto-detección de columnas ───────────────────────────────────────────────

_MONTH_NAMES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
                'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']


def _detect_columns(page):
    """
    Auto-detecta posiciones X desde la fila de cabecera 'Ene Feb Mar...'.
    Devuelve dict {stock, smin, year_x0, year_x1, total, months[12]} o None.
    """
    try:
        words = page.extract_words(x_tolerance=3, y_tolerance=3)
    except Exception:
        return None

    month_hits = {}
    for w in words:
        txt = w['text'].strip().lower().rstrip('.')
        for i, m in enumerate(_MONTH_NAMES):
            if txt == m.lower():
                month_hits[i] = w
                break

    if len(month_hits) < 6:
        return None

    month_xs = [None] * 12
    for i, w in month_hits.items():
        month_xs[i] = (w['x0'] + w['x1']) / 2

    known = sorted((i, x) for i, x in enumerate(month_xs) if x is not None)
    if len(known) >= 2:
        step = (known[-1][1] - known[0][1]) / max(known[-1][0] - known[0][0], 1)
        for i in range(12):
            if month_xs[i] is None:
                month_xs[i] = known[0][1] + (i - known[0][0]) * step

    ref_top = next(iter(month_hits.values()))['top']
    header_words = [w for w in words if abs(w['top'] - ref_top) <= 5]

    cols = {
        'stock':   STOCK_X,
        'smin':    SMIN_X,
        'year_x0': YEAR_X0,
        'year_x1': YEAR_X1,
        'total':   TOTAL_X,
        'months':  month_xs,
    }
    for w in header_words:
        t, tl = w['text'].strip(), w['text'].strip().lower()
        cx = (w['x0'] + w['x1']) / 2
        if tl in ('stock', 'stk'):
            cols['stock'] = cx
        elif tl.startswith('s.m') or tl.startswith('smi'):
            cols['smin'] = cx
        elif 'ñ' in tl or tl in ('ano', 'año'):
            cols['year_x0'] = w['x0']
            cols['year_x1'] = w['x1']
        elif tl == 'total':
            cols['total'] = cx
    return cols


def _month_cutoff(row_chars, year_x1):
    """
    Devuelve la X mínima válida para leer valores de mes en una fila con año.
    Excluye texto de descripción como '400 ML' buscando el carácter alfabético
    más a la derecha después de la zona del año y añadiendo un margen.
    """
    alpha_after_year = [c['x0'] for c in row_chars
                        if c['text'].isalpha() and c['x0'] > year_x1]
    if not alpha_after_year:
        return year_x1 + 2
    return max(alpha_after_year) + 4


def _detect_columns_from_data(rows_dict):
    """
    Fallback de detección cuando la cabecera no tiene 'Ene/Feb/Mar...'.
    Escanea filas de productos (código 6 chars) buscando el cluster '20XX'
    como ancla del año, luego infiere el resto de columnas por posición relativa.

    Retorna dict con mismas claves que _detect_columns(), o None si insuficiente.
    """
    year_xs = []
    right_xs = []   # X de clusters a la derecha del año → candidatos a meses
    left_xs  = []   # X de clusters a la izquierda del año → candidatos a stock/smin

    rows_checked = 0
    for y in sorted(rows_dict.keys()):
        row = rows_dict[y]
        code_chars = sorted([c for c in row if 20 <= c['x0'] < 60],
                            key=lambda c: c['x0'])
        code = ''.join(c['text'] for c in code_chars).strip()
        if not re.match(r'^[0-9A-Z]{6}$', code):
            continue

        clusters = _char_clusters(row)
        for grp in clusters:
            txt = ''.join(c['text'] for c in grp)
            if re.match(r'^20\d{2}$', txt):
                cx = (grp[0]['x0'] + grp[-1]['x0']) / 2
                year_xs.append(cx)
                for g2 in clusters:
                    g2_cx = (g2[0]['x0'] + g2[-1]['x0']) / 2
                    if g2_cx > cx + 25:
                        right_xs.append(g2_cx)
                    elif cx - 90 < g2_cx < cx - 5:
                        left_xs.append(g2_cx)
                break

        rows_checked += 1
        if rows_checked >= 10:
            break

    if len(year_xs) < 3 or not right_xs:
        return None

    yr_center = sorted(year_xs)[len(year_xs) // 2]
    yr_x0 = yr_center - 10
    yr_x1 = yr_center + 10

    # Distribución uniforme de 12 meses entre el primer y último cluster derecho
    right_sorted = sorted(set(right_xs))
    r_min = right_sorted[0]
    r_max = right_sorted[-1]
    if r_max - r_min < 50:
        return None   # zona demasiado estrecha para 12 meses
    step = (r_max - r_min) / 11
    month_xs = [r_min + i * step for i in range(12)]

    left_sorted = sorted(set(left_xs))
    stock_x = left_sorted[-2] if len(left_sorted) >= 2 else yr_x0 - 40
    smin_x  = left_sorted[-1] if len(left_sorted) >= 1 else yr_x0 - 20

    return {
        'stock':   stock_x,
        'smin':    smin_x,
        'year_x0': yr_x0,
        'year_x1': yr_x1,
        'total':   yr_x1 + 30,
        'months':  month_xs,
    }


def _detect_years_global(all_rows):
    years = set()
    for row_chars in all_rows:
        yr = _year_from_row(row_chars)
        if yr:
            years.add(yr)
    years = sorted(years)
    if len(years) >= 2:
        return years[-1], years[-2]
    elif len(years) == 1:
        return years[0], years[0] - 1
    _cur = _date.today().year
    return _cur, _cur - 1


def _extract_description(row_chars):
    desc_chars = [c for c in sorted(row_chars, key=lambda c: c['x0'])
                  if 63 <= c['x0'] < 315]
    tokens = []
    for c in desc_chars:
        if c['text'].isdigit():
            stock_xs = [STOCK_X + d * DIGIT_W for d in range(-2, 3)]
            smin_xs  = [SMIN_X  + d * DIGIT_W for d in range(-2, 3)]
            year_xs  = [YEAR_X0 + d * DIGIT_W for d in range(4)]
            total_xs = [TOTAL_X + d * DIGIT_W for d in range(-2, 3)]
            all_col_xs = stock_xs + smin_xs + year_xs + total_xs
            is_col = (
                any(abs(c['x0'] - cx) <= X_TOL for cx in all_col_xs) or
                any(abs(c['x0'] - mx) <= 6 for mx in MONTH_X)
            )
            if is_col:
                continue
        tokens.append(c['text'])
    desc = ''.join(tokens).strip()
    desc = re.sub(r'  +', ' ', desc)
    return desc


# ─── Extracción principal ──────────────────────────────────────────────────────

def extract_products(pdf_path, on_page=None):
    products = {}

    with pdfplumber.open(pdf_path) as pdf:
        all_rows = []
        pages_data = []  # list of (page_object, rows_dict)

        for page in pdf.pages:
            rows = defaultdict(list)
            for c in page.chars:
                y = round(c['top'] / 2) * 2
                rows[y].append(c)
            pages_data.append((page, rows))
            all_rows.extend(rows.values())

        year_current, year_prev = _detect_years_global(all_rows)
        total_pages = len(pages_data)

        for page_idx, (page, rows) in enumerate(pages_data):
            if on_page:
                on_page(page_idx + 1, total_pages)

            # Detectar posiciones de columnas en 3 niveles:
            # 1) cabecera de página (más fiable), 2) inferencia desde datos (robusto),
            # 3) posiciones hardcoded (último recurso, puede fallar en formatos nuevos).
            _cols = (_detect_columns(page)
                     or _detect_columns_from_data(rows)
                     or {
                         'stock': STOCK_X, 'smin': SMIN_X,
                         'year_x0': YEAR_X0, 'year_x1': YEAR_X1,
                         'total': TOTAL_X, 'months': MONTH_X,
                     })
            p_stock_x  = _cols['stock']
            p_smin_x   = _cols['smin']
            p_yr_x0    = _cols['year_x0']
            p_yr_x1    = _cols['year_x1']
            p_months   = _cols['months']

            sorted_ys = sorted(rows.keys())

            for i, y in enumerate(sorted_ys):
                row = rows[y]

                code_chars = sorted(
                    [c for c in row if 20 <= c['x0'] < 60],
                    key=lambda c: c['x0']
                )
                code = ''.join(c['text'] for c in code_chars).strip()

                if not re.match(r'^[0-9A-Z]{6}$', code):
                    continue

                yr_this_row = _year_from_row(row, p_yr_x0, p_yr_x1)
                is_pattern_a = (yr_this_row is not None)

                description = _extract_description(row)

                # Forward: añadir filas de continuación hasta llegar a una fila con
                # datos de año. Se para en la primera fila que tenga año detectado
                # (independientemente del contenido textual de la continuación).
                j = i + 1
                while j < len(sorted_ys):
                    next_row = rows[sorted_ys[j]]
                    next_code_chars = [c for c in next_row if 20 <= c['x0'] < 60]
                    next_code = ''.join(
                        c['text'] for c in sorted(next_code_chars, key=lambda c: c['x0'])
                    ).strip()
                    if re.match(r'^[0-9A-Z]{6}$', next_code):
                        break
                    next_yr = _year_from_row(next_row, p_yr_x0, p_yr_x1)
                    if next_yr is not None:
                        # Primera fila de datos: puede tener texto de descripción
                        # en la misma línea (p.ej. "0,12% 250 ML" + "2026 1 0...")
                        tail = _extract_description(next_row)
                        if tail and not re.search(r'[a-z]', tail):
                            description = re.sub(r'  +', ' ',
                                                 (description + ' ' + tail).strip())
                        break
                    continuation = _extract_description(next_row)
                    if not continuation:
                        break
                    description = re.sub(r'  +', ' ',
                                         (description + ' ' + continuation).strip())
                    j += 1

                # Backward: subir hasta 5 filas antes del código buscando líneas de
                # descripción. Cada farmacia imprime el código al lado de la ÚLTIMA
                # línea de descripción, por lo que las líneas anteriores quedan sin
                # código y deben recogerse hacia atrás.
                back_descs = []
                k = i - 1
                while k >= 0 and len(back_descs) < 5:
                    prev_row = rows[sorted_ys[k]]
                    prev_code_chars = [c for c in prev_row if 20 <= c['x0'] < 60]
                    prev_code = ''.join(
                        c['text'] for c in sorted(prev_code_chars, key=lambda c: c['x0'])
                    ).strip()
                    if re.match(r'^[0-9A-Z]{6}$', prev_code):
                        break  # Código de otro producto
                    if _year_from_row(prev_row, p_yr_x0, p_yr_x1) is not None:
                        break  # Fila de datos del año del producto anterior
                    prev_desc = _extract_description(prev_row)
                    # Excluir cabeceras de página (contienen minúsculas: fecha, "Pág.")
                    if prev_desc and not re.search(r'[a-z]', prev_desc):
                        back_descs.insert(0, prev_desc)
                        k -= 1
                    else:
                        break
                if back_descs:
                    description = re.sub(r'  +', ' ',
                                         (' '.join(back_descs) + ' ' + description).strip())

                stock = _digits_at(row, p_stock_x)
                smin  = _digits_at(row, p_smin_x)

                zone_letters = [c for c in row
                                if 200 <= c['x0'] < 255
                                and c['text'].isalpha()]
                stock_warning = len(zone_letters) > 0

                months_current = [0] * 12
                months_prev    = [0] * 12

                if not is_pattern_a:
                    months_current = [_month_value(row, mx) for mx in p_months]
                elif yr_this_row == year_current:
                    cutoff = _month_cutoff(row, p_yr_x1)
                    months_current = [_month_value(row, mx, cutoff_x=cutoff)
                                      for mx in p_months]
                    stock = _digits_at(row, p_stock_x)
                    smin  = _digits_at(row, p_smin_x)

                for j in range(i + 1, min(i + 8, len(sorted_ys))):
                    y2 = sorted_ys[j]
                    row2 = rows[y2]

                    code2_chars = [c for c in row2 if 20 <= c['x0'] < 60]
                    code2 = ''.join(c['text'] for c in
                                    sorted(code2_chars, key=lambda c: c['x0'])).strip()
                    if re.match(r'^[0-9A-Z]{6}$', code2) and code2 != code:
                        break

                    yr2 = _year_from_row(row2, p_yr_x0, p_yr_x1)
                    if yr2 is None:
                        continue

                    cutoff2 = _month_cutoff(row2, p_yr_x1)
                    months2 = [_month_value(row2, mx, cutoff_x=cutoff2)
                               for mx in p_months]

                    if yr2 == year_current and yr_this_row != year_current:
                        months_current = months2
                        stock = _digits_at(row2, p_stock_x)
                        smin  = _digits_at(row2, p_smin_x)
                    elif yr2 == year_prev:
                        months_prev = months2

                total_current = sum(months_current)
                total_prev    = sum(months_prev)

                # Capa 3: si el total parece un año, algún mes fue mal leído.
                # Eliminar valores ≥ 500 en meses individuales (ninguna farmacia
                # pequeña vende 500 uds de un producto en un solo mes).
                if total_current >= 1500:
                    months_current = [m if m < 500 else 0 for m in months_current]
                    total_current  = sum(months_current)
                if total_prev >= 1500:
                    months_prev = [m if m < 500 else 0 for m in months_prev]
                    total_prev  = sum(months_prev)

                last_month_idx = max(
                    (idx for idx, v in enumerate(months_current) if v > 0), default=-1
                )
                close_month = last_month_idx + 1  # 1-12; 0 = sin datos

                warnings = []
                if stock_warning:
                    warnings.append('stock_smin_zona_contaminada')
                if stock > 9999:
                    warnings.append(f'stock_sospechoso:{stock}')
                    stock = None
                if smin > 9999:
                    warnings.append(f'smin_sospechoso:{smin}')
                    smin = None

                products[code] = {
                    'code':           code,
                    'description':    description,
                    'stock':          stock,
                    'smin':           smin,
                    'year_current':   year_current,
                    'year_prev':      year_prev,
                    'total_current':  total_current,
                    'total_prev':     total_prev,
                    'months_current': months_current,
                    'months_prev':    months_prev,
                    'close_month':    close_month,
                    'pattern':        'A' if is_pattern_a else 'B',
                    'warnings':       warnings,
                    'needs_review':   len(warnings) > 0,
                }

    return products


# ─── Informe de situación (stock parado) ───────────────────────────────────────

def _detect_situation_columns(words):  # kept for potential future use
    """
    Detecta posiciones X de columnas del Informe de Situación buscando
    palabras de cabecera ('Código', 'Stock', 'Caducidad').
    Devuelve dict con rangos x0/x1 por columna, o None si no encuentra cabecera.
    """
    _HEADER_KEYS = {
        'código': 'code', 'codigo': 'code',
        'descripción': 'desc', 'descripcion': 'desc',
        'stock': 'stock',
        'caducidad': 'caducidad',
    }

    # Encontrar la fila de cabecera buscando 'Código'/'codigo'
    header_y = None
    for w in words:
        norm = w['text'].lower().strip().rstrip(':')
        if norm in ('código', 'codigo'):
            header_y = w['top']
            break

    if header_y is None:
        return None

    # Recoger todas las palabras en esa fila (±6px)
    header_row = [w for w in words if abs(w['top'] - header_y) <= 6]
    cols = {}
    for w in header_row:
        norm = w['text'].lower().strip().rstrip(':')
        if norm in _HEADER_KEYS:
            cols[_HEADER_KEYS[norm]] = w['x0']

    if 'code' not in cols:
        return None

    code_x   = cols['code']
    desc_x   = cols.get('desc',      code_x + 40)
    stock_x  = cols.get('stock',     code_x + 350)
    cad_x    = cols.get('caducidad', code_x + 470)

    return {
        'code_x0':      code_x - 5,
        'code_x1':      code_x + 38,
        'desc_x0':      desc_x,
        'desc_x1':      stock_x - 5,
        'stock_x0':     stock_x - 10,
        'stock_x1':     stock_x + 40,
        'caducidad_x0': cad_x - 10,
        'caducidad_x1': cad_x + 90,
    }


def extract_situation(pdf_path):
    """
    Extrae productos del "Informe de situación" (stock parado).
    Devuelve dict: { código: { 'stock': int, 'caducidad': str, 'description': str } }
    """
    STOCK_X0,     STOCK_X1     = 410, 445
    CADUCIDAD_X0, CADUCIDAD_X1 = 535, 600

    products = {}

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            words    = page.extract_words(x_tolerance=4, y_tolerance=4)
            raw_text = page.extract_text() or ''
            if not words:
                continue

            rows_dict = defaultdict(list)
            for w in words:
                y = round(w['top'] / 2) * 2
                rows_dict[y].append(w)

            sorted_ys = sorted(rows_dict.keys())
            i = 0
            while i < len(sorted_ys):
                y   = sorted_ys[i]
                row = sorted(rows_dict[y], key=lambda w: w['x0'])

                # Código: 6 chars alfanuméricos en x ≈ 30–110
                code = None
                for w in row:
                    if re.match(r'^[0-9A-Z]{6}$', w['text']) and 30 <= w['x0'] <= 110:
                        code = w['text']
                        break
                if not code:
                    i += 1
                    continue

                # Stock: entero < 1900 en x ≈ 410–445
                stock = 0
                for w in row:
                    if STOCK_X0 <= w['x0'] <= STOCK_X1:
                        if re.match(r'^\d+$', w['text']):
                            v = int(w['text'])
                            if v < 1900:
                                stock = v
                        break

                # Caducidad: MM/YYYY en x ≈ 535–600
                caducidad = ''
                for w in row:
                    if CADUCIDAD_X0 <= w['x0'] <= CADUCIDAD_X1:
                        if re.match(r'^\d{2}/\d{4}$', w['text']):
                            caducidad = w['text']
                        break

                # Descripción: palabras entre x=70 y STOCK_X0, sin el código
                description = ' '.join(
                    w['text'] for w in row
                    if 70 <= w['x0'] < STOCK_X0 and w['text'] != code
                )

                # Look-ahead: líneas de continuación hasta el siguiente código
                j = i + 1
                while j < len(sorted_ys):
                    next_row = sorted(rows_dict[sorted_ys[j]], key=lambda w: w['x0'])
                    if any(re.match(r'^[0-9A-Z]{6}$', w['text']) and 30 <= w['x0'] <= 110
                           for w in next_row):
                        break
                    cont = ' '.join(
                        w['text'] for w in next_row
                        if 70 <= w['x0'] < STOCK_X0
                    ).strip()
                    if not cont:
                        break
                    description = re.sub(r'  +', ' ', (description + ' ' + cont).strip())
                    j += 1

                description = re.sub(r'  +', ' ', description).strip()

                # Fallback: texto plano si la descripción quedó vacía
                if not description:
                    description = _desc_from_raw_text(raw_text, code)

                products[code] = {
                    'stock':       stock,
                    'caducidad':   caducidad,
                    'description': description,
                }
                i = j

    return products


def _desc_from_raw_text(page_text, code):
    """
    Extrae descripción de un código usando el texto plano de la página
    (extract_text), sin depender de posiciones X. Útil cuando extract_words
    falla en agrupar caracteres del PDF de Pierre Fabre u otros labs.
    """
    for line in page_text.splitlines():
        # Buscar línea que contenga el código como token aislado
        if not re.search(r'(?<!\w)' + re.escape(code) + r'(?!\w)', line):
            continue
        idx = line.find(code)
        after = line[idx + len(code):].strip()
        parts = after.split()
        desc_parts = []
        for k, part in enumerate(parts):
            if re.match(r'^\d+$', part):
                v = int(part)
                if v < 1900:
                    # Stock: seguido de precio decimal
                    remaining = ' '.join(parts[k:])
                    if re.search(r'\d+[,\.]\d{2}', remaining[len(part):]):
                        break
            desc_parts.append(part)
        result = ' '.join(desc_parts).strip()
        if result:
            return result
    return ''


# ─── Diagnóstico de formato PDF ───────────────────────────────────────────────

def diagnose_pdf(pdf_path, max_products=5):
    """
    Imprime la estructura interna de un PDF de estadísticas para depurar
    formatos nuevos. Muestra posiciones X de cabeceras, año detectado y
    primeros productos con sus clusters de dígitos.

    Uso: python3 -c "from pdf_parser import diagnose_pdf; diagnose_pdf('ruta.pdf')"
    """
    import sys
    out = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            out.append(f'\n=== PÁGINA {page_idx + 1} ===')

            # Detección de columnas por cabecera
            cols = _detect_columns(page)
            if cols:
                out.append(f'  _detect_columns → OK')
                out.append(f'    stock={cols["stock"]:.1f}  smin={cols["smin"]:.1f}'
                           f'  year=[{cols["year_x0"]:.1f}-{cols["year_x1"]:.1f}]'
                           f'  total={cols["total"]:.1f}')
                out.append(f'    months (12): {[f"{x:.0f}" for x in cols["months"]]}')
            else:
                out.append(f'  _detect_columns → None (no header found)')

            # Cabecera bruta: palabras en las primeras 5 líneas
            words = page.extract_words(x_tolerance=3, y_tolerance=3) or []
            if words:
                top_y = min(w['top'] for w in words)
                header_words = [w for w in words if w['top'] < top_y + 40]
                out.append(f'  Header words: {[(w["text"], round(w["x0"])) for w in header_words[:20]]}')

            # Primeros productos con clusters
            rows = defaultdict(list)
            for c in page.chars:
                y = round(c['top'] / 2) * 2
                rows[y].append(c)

            found = 0
            for y in sorted(rows.keys()):
                row = rows[y]
                code_chars = sorted([c for c in row if 20 <= c['x0'] < 60],
                                    key=lambda c: c['x0'])
                code = ''.join(c['text'] for c in code_chars).strip()
                if not re.match(r'^[0-9A-Z]{6}$', code):
                    continue

                clusters = _char_clusters(row)
                cluster_info = [(int(''.join(c['text'] for c in g)),
                                 round((g[0]['x0'] + g[-1]['x0']) / 2))
                                for g in clusters]
                yr = _year_from_row(row)
                out.append(f'  {code}  yr={yr}  clusters={cluster_info}')
                found += 1
                if found >= max_products:
                    break

            if found == 0:
                out.append('  (sin productos en esta página)')

            # Inferencia desde datos
            data_cols = _detect_columns_from_data(rows)
            if data_cols:
                out.append(f'  _detect_columns_from_data → OK')
                out.append(f'    year=[{data_cols["year_x0"]:.1f}-{data_cols["year_x1"]:.1f}]'
                           f'  months: {[f"{x:.0f}" for x in data_cols["months"]]}')
            else:
                out.append(f'  _detect_columns_from_data → None')

    print('\n'.join(out))
    return '\n'.join(out)



# ─── Cálculo de pedido sugerido ───────────────────────────────────────────────

import math as _math

def calculate_pedido(product):
    """
    Pedido sugerido = max(0, ceil(ventas_12m / 4) - stock)
    Ventas_12m = total_current + total_prev (los totales del PDF ya cubren 12 meses).
    """
    if product is None:
        return 0
    ventas_12m = product.get('total_current', 0) + product.get('total_prev', 0)
    stock = product.get('stock') or 0
    return max(0, _math.ceil(ventas_12m / 4) - stock)


# ─── Comparación ──────────────────────────────────────────────────────────────

def compare_products(products1, products2,
                     name1='Farmacia 1', name2='Farmacia 2',
                     situation1=None, situation2=None):
    """
    Compara productos de dos farmacias.
    Solo incluye productos que aparecen en ventas (products1 o products2).
    El informe de situación solo se usa para marcar parados y S.365.
    """
    sit1 = situation1 or {}
    sit2 = situation2 or {}

    # Códigos de ventas + informe de situación (productos sin ventas también visibles)
    all_codes = (set(products1.keys()) | set(products2.keys())
                 | set(sit1.keys()) | set(sit2.keys()))
    results = []

    all_yr_cur = [p.get('year_current', 0)
                  for p in list(products1.values()) + list(products2.values())]
    global_yr_cur  = max(all_yr_cur) if all_yr_cur else _date.today().year
    global_yr_prev = global_yr_cur - 1

    def _totals(p):
        if p is None:
            return '—', '—'
        yr = p.get('year_current', global_yr_cur)
        if yr == global_yr_cur:
            return p.get('total_current', 0), p.get('total_prev', 0)
        elif yr == global_yr_prev:
            return '—', p.get('total_current', 0)
        else:
            return p.get('total_current', 0), p.get('total_prev', 0)

    def _val(p, key, fallback='—'):
        if p is None:
            return fallback
        v = p.get(key)
        if v is None:
            return '⚠️'
        return v

    for code in all_codes:
        p1 = products1.get(code)
        p2 = products2.get(code)

        if p1 and p2:
            status = 'both'
            description = p1['description'] or p2['description']
        elif p1:
            status = 'only1'
            description = p1['description']
        elif p2:
            status = 'only2'
            description = p2['description']
        elif code in sit1 and code in sit2:
            status = 'both'
            description = (sit1[code].get('description', '')
                           or sit2[code].get('description', ''))
        elif code in sit1:
            status = 'only1'
            description = sit1[code].get('description', '')
        elif code in sit2:
            status = 'only2'
            description = sit2[code].get('description', '')
        else:
            continue

        # Use situation-report description as fallback for empty ventas descriptions
        if not description:
            description = (sit1.get(code, {}).get('description', '')
                           or sit2.get(code, {}).get('description', ''))

        warnings = []
        if p1 and p1.get('warnings'):
            warnings += [f'{name1}:{w}' for w in p1['warnings']]
        if p2 and p2.get('warnings'):
            warnings += [f'{name2}:{w}' for w in p2['warnings']]

        t1_cur, t1_prev = _totals(p1)
        t2_cur, t2_prev = _totals(p2)

        # S.365: stock del informe (solo si el código está en el informe)
        s365_1 = sit1[code]['stock'] if code in sit1 else '—'
        s365_2 = sit2[code]['stock'] if code in sit2 else '—'

        # Para productos sin ventas, usar el stock del informe de situación
        stock1 = (_val(p1, 'stock') if p1
                  else (sit1[code]['stock'] if code in sit1 else '—'))
        stock2 = (_val(p2, 'stock') if p2
                  else (sit2[code]['stock'] if code in sit2 else '—'))
        smin1  = _val(p1, 'smin') if p1 else '—'
        smin2  = _val(p2, 'smin') if p2 else '—'

        results.append({
            'code':         code,
            'description':  description,
            'status':       status,
            'stock1':       stock1,
            'smin1':        smin1,
            'total1':       t1_cur,
            'total1_prev':  t1_prev,
            's365_1':       s365_1,
            'pedido1':      calculate_pedido(p1),
            'stock2':       stock2,
            'smin2':        smin2,
            'total2':       t2_cur,
            'total2_prev':  t2_prev,
            's365_2':       s365_2,
            'pedido2':      calculate_pedido(p2),
            'year_current': global_yr_cur,
            'year_prev':    global_yr_prev,
            'warnings':     warnings,
            'needs_review': bool(warnings),
            'parado1':      code in sit1,
            'parado2':      code in sit2,
            'caducidad1':   sit1.get(code, {}).get('caducidad', ''),
            'caducidad2':   sit2.get(code, {}).get('caducidad', ''),
            # Datos mensuales para KPIs del Motor de Decisión
            'months1_current': p1.get('months_current', [0]*12) if p1 else [0]*12,
            'months1_prev':    p1.get('months_prev',    [0]*12) if p1 else [0]*12,
            'months2_current': p2.get('months_current', [0]*12) if p2 else [0]*12,
            'months2_prev':    p2.get('months_prev',    [0]*12) if p2 else [0]*12,
        })

    # Ordenar alfabéticamente por descripción
    results.sort(key=lambda r: r['description'].upper())
    return results


# ─── Detección de laboratorio ──────────────────────────────────────────────────

import json as _json
import re as _re
from collections import Counter as _Counter
from pathlib import Path as _Path

_LABS_FILE = _Path(__file__).parent / 'labs.json'

_STOP = {
    'ENVASE','TUBO','BOTE','FRASCO','UNIDAD','CAPSULAS','CAPS',
    'COMPRIMIDOS','COMP','AMPOLLA','SPRAY','CREMA','GEL','LOCION',
    'SERUM','FLUIDO','ACEITE','LECHE','AGUA','MOUSSE','ESPUMA',
    'BAUME','STICK','PACK','DUPLO','COLOR','PIEL','ROSTRO','NORMAL',
    'SECA','GRASA','MIXTA','PARA','CON','SIN','MUY','ALTA','BAJA',
    'MEDIA','GRANDE','REPARADOR','HIDRATANTE','LIMPIADOR','EXTRACTO',
    'JARABE','TABLETAS','SPF','ANTI','ULTRA','FORTE','BIO','PLUS',
    'TOTAL','PURE','LIGHT','RICH','MAX','PRO','ONE','AIR','ACTIVE',
    'REPAIR','CARE','SKIN','FACE','BODY','MANOS','PIES','OJOS',
    'LABIOS','CUELLO','CONTORNO','ZONA','ZONAS','INVISIBLE',
    'MINERAL','SOLAR','PROTECCION','SUNSCREEN','SENSITIVE',
}

_NORMALIZE = {
    'ABOCA': 'Aboca', 'GRINTUSS': 'Aboca', 'NEOBIANACID': 'Aboca',
    'MELILAX': 'Aboca', 'LENODIAR': 'Aboca', 'ALIVIOLAS': 'Aboca',
    'COLIGAS': 'Aboca', 'COLILEN': 'Aboca', 'FITONASAL': 'Aboca',
    'FITOSTILL': 'Aboca', 'FISIOVEN': 'Aboca', 'GOLAMIR': 'Aboca',
    'IMMUNOMIX': 'Aboca', 'LIBRAMED': 'Aboca', 'LYNFASE': 'Aboca',
    'METARECOD': 'Aboca', 'NEOFITOROID': 'Aboca', 'OROBEN': 'Aboca',
    'SEDIVITAX': 'Aboca', 'PROPOL': 'Aboca',
    'ARKOPHARMA': 'Arkopharma', 'ARKO': 'Arkopharma', 'ARKOFLEX': 'Arkopharma',
    'ARKOREAL': 'Arkopharma', 'ARKOVOX': 'Arkopharma', 'ARKOCAPS': 'Arkopharma',
    'ARKOVITAL': 'Arkopharma',
    'BIODERMA': 'Bioderma', 'SENSIBIO': 'Bioderma', 'SEBIUM': 'Bioderma',
    'ATODERM': 'Bioderma', 'PHOTODERM': 'Bioderma', 'PIGMENTBIO': 'Bioderma',
    'CICABIO': 'Bioderma',
    'BIPOLE': 'Bipole', 'INTEGRALIA': 'Bipole',
    'BEPANTHOL': 'Bepanthol',
    'CAUDALIE': 'Caudalie', 'VINOPERFECT': 'Caudalie', 'VINOSOURCE': 'Caudalie',
    'VINOCLEAN': 'Caudalie', 'VINERGETIC': 'Caudalie',
    'CERAVE': 'CeraVe',
    'CINFA': 'Cinfa',
    'COLNATUR': 'Colnatur / Ordesa', 'BLEVIT': 'Colnatur / Ordesa',
    'BLEMIL': 'Colnatur / Ordesa', 'SANUTRI': 'Colnatur / Ordesa',
    'CUMLAUDE': 'Cumlaude', 'DAYLONG': 'Cumlaude',
    'DEMEMORY': 'Dememory',
    'EPAPLUS': 'Epaplus',
    'EUCERIN': 'Eucerin', 'UREAREPAIR': 'Eucerin', 'AQUAPHOR': 'Eucerin',
    'HELIOCARE': 'Heliocare',
    'ISDIN': 'ISDIN', 'UREADIN': 'ISDIN', 'ERYFOTONA': 'ISDIN',
    'NUTRADEICA': 'ISDIN', 'LAMBDAPIL': 'ISDIN',
    'JUANOLA': 'Juanola / Angelini', 'ANGELINI': 'Juanola / Angelini',
    'KINERASE': 'Kin',
    'POSAY': 'La Roche-Posay', 'ANTHELIOS': 'La Roche-Posay',
    'CICAPLAST': 'La Roche-Posay', 'EFFACLAR': 'La Roche-Posay',
    'LIPIKAR': 'La Roche-Posay', 'TOLERIANE': 'La Roche-Posay',
    'HYDRAPHASE': 'La Roche-Posay', 'SUBSTIANE': 'La Roche-Posay',
    'PIGMENTCLAR': 'La Roche-Posay', 'SPOTSCAN': 'La Roche-Posay',
    'LOREAL': "L'Oreal", 'REVITALIFT': "L'Oreal",
    'MARTIDERM': 'Martiderm',
    'MESOESTETIC': 'Mesoestetic',
    'MUSTELA': 'Mustela', 'VARISAN': 'Varisan',
    'STELATOPIA': 'Mustela', 'STELATRIA': 'Mustela',
    'CICASTELA': 'Mustela',
    'NEOSTRATA': 'Neostrata',
    'NEUTROGENA': 'Neutrogena',
    'NIVEA': 'Nivea',
    'NUTRALIE': 'Nutralie',
    'NUXE': 'Nuxe', 'HUILE': 'Nuxe',
    'NUROFEN': 'Reckitt', 'STREPSILS': 'Reckitt', 'GAVISCON': 'Reckitt',
    'DUREX': 'Reckitt', 'MUCINEX': 'Reckitt',
    'RILASTIL': 'Rilastil',
    'SENSILIS': 'Sensilis / Pierre Fabre', 'FABRE': 'Sensilis / Pierre Fabre',
    'KLORANE': 'Sensilis / Pierre Fabre', 'AVENE': 'Sensilis / Pierre Fabre',
    'DUCRAY': 'Sensilis / Pierre Fabre', 'KERTYOL': 'Sensilis / Pierre Fabre',
    'ANACAPS': 'Sensilis / Pierre Fabre', 'ICTYANE': 'Sensilis / Pierre Fabre',
    'SESDERMA': 'Sesderma', 'ENDOCARE': 'Sesderma', 'RETISES': 'Sesderma',
    'SVRGEL': 'SVR', 'CICAVIT': 'SVR', 'SEBIACLEAR': 'SVR', 'CLAIRIAL': 'SVR',
    'URIAGE': 'Uriage', 'XEMOSE': 'Uriage', 'BARIEDERM': 'Uriage',
    'PRURICED': 'Uriage', 'ROSELIANE': 'Uriage',
    'VICHY': 'Vichy', 'LIFTACTIV': 'Vichy', 'NORMADERM': 'Vichy',
    'DERMABLEND': 'Vichy', 'AQUALIA': 'Vichy',
    'ESI': 'ESI', 'MELATONIN': 'ESI', 'NORMOLIP': 'ESI',
    'PROPOLAID': 'ESI', 'SERENESI': 'ESI',
}


def _load_labs():
    if _LABS_FILE.exists():
        with open(_LABS_FILE, 'r', encoding='utf-8') as f:
            data = _json.load(f)
        return {k: v for k, v in data.items() if not k.startswith('_')}
    return {}


def _save_lab(code, name):
    labs = {}
    if _LABS_FILE.exists():
        with open(_LABS_FILE, 'r', encoding='utf-8') as f:
            labs = _json.load(f)
    labs[code] = name
    with open(_LABS_FILE, 'w', encoding='utf-8') as f:
        _json.dump(labs, f, ensure_ascii=False, indent=2)


def _guess_from_descriptions(pdf_path):
    word_count = _Counter()
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages[:-1]:
            words = page.extract_words(x_tolerance=4, y_tolerance=4)
            for w in words:
                if 60 <= w['x0'] <= 210:
                    tok = w['text'].upper()
                    if len(tok) >= 4 and tok.isalpha() and tok not in _STOP:
                        word_count[tok] += 1

    for word, _ in word_count.most_common(15):
        if word in _NORMALIZE:
            return _NORMALIZE[word]

    if word_count:
        top = word_count.most_common(1)[0][0]
        return top.capitalize()
    return None


def detect_lab(pdf_path):
    labs = _load_labs()

    with pdfplumber.open(pdf_path) as pdf:
        last_text = pdf.pages[-1].extract_text() or ''

    m = _re.search(r'Laboratorio[:\s]+(\w+)', last_text)
    code = m.group(1).strip() if m else None

    if code and code in labs:
        return labs[code]

    guessed = _guess_from_descriptions(pdf_path)
    if guessed:
        if code:
            _save_lab(code, guessed)
        return guessed

    return f'Lab {code}' if code else 'Laboratorio desconocido'


_DATE_LINE_RE = re.compile(
    r'^(lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo|\d{1,2}[\/\-])',
    re.IGNORECASE,
)

def detect_pdf_header(pdf_path):
    """Lee SOLO la cabecera de la página 1 para detectar tipo de documento y farmacia.

    Usa crop + extract_text en lugar de chars crudos para evitar interleaving
    entre líneas distintas (ej: nombre farmacia vs línea de fecha).

    Returns:
        {'type': 'ventas'|'situacion', 'pharmacy': str}
    """
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        w = float(page.width)
        mid = w * 0.45

        left_text  = (page.crop((0,   0, mid, 65)).extract_text() or '').strip()
        right_text = (page.crop((mid, 0, w,   65)).extract_text() or '').strip()

    # Tipo de documento: buscar clave en líneas del lado izquierdo
    doc_type = 'ventas'
    for line in left_text.splitlines():
        ll = line.lower()
        if 'situaci' in ll or 'informe' in ll:
            doc_type = 'situacion'
            break
        if 'estad' in ll or 'ventas' in ll:
            doc_type = 'ventas'
            break

    # Farmacia: primera línea del lado derecho que no sea una fecha
    pharmacy = ''
    for line in right_text.splitlines():
        line = line.strip()
        if line and not _DATE_LINE_RE.match(line):
            pharmacy = line
            break

    return {'type': doc_type, 'pharmacy': pharmacy}