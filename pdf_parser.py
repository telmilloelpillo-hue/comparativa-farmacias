"""
pdf_parser.py — Parser universal para PDFs de estadísticas de ventas (Farmacias)
"""

import pdfplumber
import re
from collections import defaultdict

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

def _digits_at(row_chars, x_anchor, max_digits=3, tol=X_TOL):
    result = []
    for d in range(max_digits):
        target = x_anchor - d * DIGIT_W
        tight  = tol if d == 0 else 0.5
        found  = [c for c in row_chars
                  if c['text'].isdigit()
                  and abs(c['x0'] - target) <= tight]
        if found:
            best = min(found, key=lambda c: abs(c['x0'] - target))
            result.append(best['text'])
        else:
            break
    result.reverse()
    return int(''.join(result)) if result else 0


def _month_value(row_chars, target_x, window=6):
    digits = [c['text'] for c in sorted(row_chars, key=lambda c: c['x0'])
              if c['text'].isdigit()
              and (target_x - window) <= c['x0'] <= (target_x + 2)]
    return int(''.join(digits)) if digits else 0


def _year_from_row(row_chars):
    zone = sorted(
        [c for c in row_chars if YEAR_X0 - 1 <= c['x0'] <= YEAR_X1 + 1],
        key=lambda c: c['x0']
    )
    text = ''.join(c['text'] for c in zone)
    m = re.search(r'(20\d{2})', text)
    return int(m.group(1)) if m else None


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
    return 2026, 2025


def _extract_description(row_chars):
    desc_chars = [c for c in sorted(row_chars, key=lambda c: c['x0'])
                  if 70 <= c['x0'] < 315]
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

def extract_products(pdf_path):
    products = {}

    with pdfplumber.open(pdf_path) as pdf:
        all_rows = []
        pages_rows = []

        for page in pdf.pages:
            rows = defaultdict(list)
            for c in page.chars:
                y = round(c['top'] / 2) * 2
                rows[y].append(c)
            pages_rows.append(rows)
            all_rows.extend(rows.values())

        year_current, year_prev = _detect_years_global(all_rows)

        for page_idx, rows in enumerate(pages_rows):
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

                yr_this_row = _year_from_row(row)
                is_pattern_a = (yr_this_row is not None)

                description = _extract_description(row)

                # Continuar descripción en filas siguientes si no tienen código propio
                j = i + 1
                while j < len(sorted_ys):
                    next_row = rows[sorted_ys[j]]
                    next_code_chars = [c for c in next_row if 20 <= c['x0'] < 60]
                    next_code = ''.join(
                        c['text'] for c in sorted(next_code_chars, key=lambda c: c['x0'])
                    ).strip()
                    if re.match(r'^[0-9A-Z]{6}$', next_code):
                        break
                    continuation = _extract_description(next_row)
                    if not continuation:
                        break
                    description = re.sub(r'  +', ' ',
                                         (description + ' ' + continuation).strip())
                    j += 1

                if not description and i > 0:
                    prev_row = rows[sorted_ys[i - 1]]
                    prev_min_x = min((c['x0'] for c in prev_row), default=999)
                    if 60 <= prev_min_x < 100:
                        description = _extract_description(prev_row)

                stock = _digits_at(row, STOCK_X)
                smin  = _digits_at(row, SMIN_X)

                zone_letters = [c for c in row
                                if 200 <= c['x0'] < 255
                                and c['text'].isalpha()]
                stock_warning = len(zone_letters) > 0

                months_current = [0] * 12
                months_prev    = [0] * 12

                if not is_pattern_a:
                    months_current = [_month_value(row, mx) for mx in MONTH_X]
                elif yr_this_row == year_current:
                    months_current = [_month_value(row, mx) for mx in MONTH_X]
                    stock = _digits_at(row, STOCK_X)
                    smin  = _digits_at(row, SMIN_X)

                for j in range(i + 1, min(i + 8, len(sorted_ys))):
                    y2 = sorted_ys[j]
                    row2 = rows[y2]

                    code2_chars = [c for c in row2 if 20 <= c['x0'] < 60]
                    code2 = ''.join(c['text'] for c in
                                    sorted(code2_chars, key=lambda c: c['x0'])).strip()
                    if re.match(r'^[0-9A-Z]{6}$', code2) and code2 != code:
                        break

                    yr2 = _year_from_row(row2)
                    if yr2 is None:
                        continue

                    months2 = [_month_value(row2, mx) for mx in MONTH_X]

                    if yr2 == year_current and yr_this_row != year_current:
                        months_current = months2
                        stock = _digits_at(row2, STOCK_X)
                        smin  = _digits_at(row2, SMIN_X)
                    elif yr2 == year_prev:
                        months_prev = months2

                total_current = sum(months_current)
                total_prev    = sum(months_prev)

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

def extract_situation(pdf_path):
    """
    Extrae productos del "Informe de situación" usando posiciones X fijas.

    Estructura del informe (x fijas detectadas empíricamente):
      Alm.      : x ≈ 29
      Código    : x ≈ 58
      Descripción: x ≈ 109–420
      Stock     : x ≈ 420–440  ← entero en esta franja
      PVP       : x ≈ 450–480  ← decimal con coma (12,95)
      Caducidad : x ≈ 540–570  ← patrón MM/YYYY

    Devuelve dict: { código: { 'stock': int, 'caducidad': str } }
    """
    # Rangos X para cada columna
    STOCK_X0, STOCK_X1    = 410, 445
    CADUCIDAD_X0, CADUCIDAD_X1 = 535, 600

    products = {}

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            words = page.extract_words(x_tolerance=4, y_tolerance=4)
            if not words:
                continue

            # Agrupar palabras por fila (Y)
            rows_dict = defaultdict(list)
            for w in words:
                y = round(w['top'] / 2) * 2
                rows_dict[y].append(w)

            sorted_ys = sorted(rows_dict.keys())
            i = 0
            while i < len(sorted_ys):
                y = sorted_ys[i]
                row = sorted(rows_dict[y], key=lambda w: w['x0'])

                # Buscar código de 6 caracteres alfanumérico
                code = None
                for w in row:
                    if re.match(r'^[0-9A-Z]{6}$', w['text']) and 50 <= w['x0'] <= 80:
                        code = w['text']
                        break

                if not code:
                    i += 1
                    continue

                # Stock: entero en la franja x ≈ 410–445
                stock = 0
                for w in row:
                    if STOCK_X0 <= w['x0'] <= STOCK_X1:
                        if re.match(r'^\d+$', w['text']):
                            stock = int(w['text'])
                            break

                # Caducidad: patrón MM/YYYY en x ≈ 535–600
                caducidad = ''
                for w in row:
                    if CADUCIDAD_X0 <= w['x0'] <= CADUCIDAD_X1:
                        if re.match(r'^\d{2}/\d{4}$', w['text']):
                            caducidad = w['text']
                            break

                # Descripción: texto entre el código (x≈80) y el stock (x≈410)
                description = ' '.join(
                    w['text'] for w in row
                    if 80 <= w['x0'] < STOCK_X0 and w['text'] != code
                )

                # Look-ahead: concatenar líneas de continuación sin código propio
                j = i + 1
                while j < len(sorted_ys):
                    next_row = sorted(rows_dict[sorted_ys[j]], key=lambda w: w['x0'])
                    has_code = any(
                        re.match(r'^[0-9A-Z]{6}$', w['text']) and 50 <= w['x0'] <= 80
                        for w in next_row
                    )
                    if has_code:
                        break
                    continuation = ' '.join(
                        w['text'] for w in next_row
                        if 80 <= w['x0'] < STOCK_X0
                    ).strip()
                    if not continuation:
                        break
                    description = re.sub(r'  +', ' ', (description + ' ' + continuation).strip())
                    j += 1

                description = re.sub(r'  +', ' ', description).strip()

                products[code] = {
                    'stock':       stock,
                    'caducidad':   caducidad,
                    'description': description,
                }
                i = j

    return products





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
    global_yr_cur  = max(all_yr_cur) if all_yr_cur else 2026
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