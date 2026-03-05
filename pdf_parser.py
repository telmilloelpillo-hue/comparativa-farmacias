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
                    'pattern':        'A' if is_pattern_a else 'B',
                    'warnings':       warnings,
                    'needs_review':   len(warnings) > 0,
                }

    return products


# ─── Informe de situación (stock parado) ───────────────────────────────────────

def extract_situation(pdf_path):
    """
    Extrae productos del "Informe de situación".
    Devuelve dict: { código: { 'stock': int, 'caducidad': str } }
    """
    products = {}

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            table = page.extract_table(
                table_settings={
                    'vertical_strategy':   'lines_strict',
                    'horizontal_strategy': 'lines_strict',
                }
            )

            if not table:
                table = _situation_from_words(page)

            if not table:
                continue

            for row in table:
                if not row:
                    continue
                for i, cell in enumerate(row):
                    cell_str = str(cell or '').strip()
                    if re.match(r'^[0-9A-Z]{6}$', cell_str):
                        code = cell_str
                        stock     = 0
                        caducidad = ''

                        for j in range(i + 2, len(row)):
                            val = str(row[j] or '').strip()
                            if re.match(r'^\d+$', val):
                                stock = int(val)
                                break

                        for j in range(i + 1, len(row)):
                            val = str(row[j] or '').strip()
                            if re.match(r'^\d{2}/\d{4}$', val):
                                caducidad = val
                                break

                        products[code] = {
                            'stock':     stock,
                            'caducidad': caducidad,
                        }
                        break

    return products


def _situation_from_words(page):
    words = page.extract_words(x_tolerance=4, y_tolerance=4)
    if not words:
        return []

    rows_dict = defaultdict(list)
    for w in words:
        y = round(w['top'] / 2) * 2
        rows_dict[y].append(w)

    table = []
    for y in sorted(rows_dict.keys()):
        row_words = sorted(rows_dict[y], key=lambda w: w['x0'])
        table.append([w['text'] for w in row_words])

    return table


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

    # SOLO códigos de ventas — el informe NO añade filas a la tabla
    all_codes = set(products1.keys()) | set(products2.keys())
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

        results.append({
            'code':         code,
            'description':  description,
            'status':       status,
            'stock1':       _val(p1, 'stock'),
            'smin1':        _val(p1, 'smin'),
            'total1':       t1_cur,
            'total1_prev':  t1_prev,
            's365_1':       s365_1,
            'stock2':       _val(p2, 'stock'),
            'smin2':        _val(p2, 'smin'),
            'total2':       t2_cur,
            'total2_prev':  t2_prev,
            's365_2':       s365_2,
            'year_current': global_yr_cur,
            'year_prev':    global_yr_prev,
            'warnings':     warnings,
            'needs_review': bool(warnings),
            'parado1':      code in sit1,
            'parado2':      code in sit2,
            'caducidad1':   sit1.get(code, {}).get('caducidad', ''),
            'caducidad2':   sit2.get(code, {}).get('caducidad', ''),
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