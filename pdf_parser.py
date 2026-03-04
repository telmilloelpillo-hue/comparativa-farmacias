"""
pdf_parser.py — Parser universal para PDFs de estadísticas de ventas (Farmacias)

Estructura del PDF (coordenadas X fijas para todos los laboratorios):
  Código       : x = 29–55
  Descripción  : x = 70–315  (puede contaminar zona de columnas numéricas)
  Stock        : x = 216.00  (1 dígito; 2 dígitos: 216.00, 220.25)
  S.min        : x = 244.35  (misma lógica)
  Año          : x = 255.13–267.87  (limpio solo en Patrón A)
  Total        : x = 318.05  (no usado: calculamos suma mensual)
  Meses Ene–Dic: x = [357.74, 397.42, 437.11, 476.79, 516.48, 556.16,
                       595.85, 635.53, 675.22, 714.90, 754.59, 794.27]

Patrones detectados:
  Patrón A: descripción cabe en x<255 → año legible en columna año
  Patrón B: descripción larga contamina zona año → año inferido por contexto

En ambos patrones los meses son SIEMPRE fiables.
Stock/smin: extraídos por posición exacta (±1px).
"""

import pdfplumber
import re
from collections import defaultdict

# ─── Posiciones X fijas del layout ────────────────────────────────────────────

STOCK_X  = 216.00   # x0 del primer dígito de Stock
SMIN_X   = 244.35   # x0 del primer dígito de S.min
YEAR_X0  = 255.13   # inicio del año en columna Año (solo Patrón A)
YEAR_X1  = 267.87   # fin del año
TOTAL_X  = 318.05   # Total del PDF (no usamos, calculamos por suma)

MONTH_X = [357.74, 397.42, 437.11, 476.79, 516.48, 556.16,
           595.85, 635.53, 675.22, 714.90, 754.59, 794.27]

DIGIT_W  = 4.25     # ancho de un dígito (monospace aprox.)
X_TOL    = 1.2      # tolerancia en px para leer una columna exacta


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _digits_at(row_chars, x_anchor, max_digits=3, tol=X_TOL):
    """
    Extrae un número entero right-aligned cuyo último dígito está en x_anchor.
    Busca hasta max_digits dígitos hacia la izquierda desde x_anchor.
    Tolerancia generosa para el dígito ancla, ajustada para los anteriores.
    """
    result = []
    for d in range(max_digits):
        target = x_anchor - d * DIGIT_W          # busca hacia la izquierda
        tight  = tol if d == 0 else 0.5
        found  = [c for c in row_chars
                  if c['text'].isdigit()
                  and abs(c['x0'] - target) <= tight]
        if found:
            best = min(found, key=lambda c: abs(c['x0'] - target))
            result.append(best['text'])
        else:
            break
    result.reverse()                              # reconstruir orden izq→der
    return int(''.join(result)) if result else 0


def _month_value(row_chars, target_x, window=6):
    """Suma dígitos en la zona de una columna mensual."""
    digits = [c['text'] for c in sorted(row_chars, key=lambda c: c['x0'])
              if c['text'].isdigit()
              and (target_x - window) <= c['x0'] <= (target_x + 2)]
    return int(''.join(digits)) if digits else 0


def _year_from_row(row_chars):
    """
    Detecta el año (20xx) en la zona de columna Año (x=255–270).
    Devuelve int o None si la zona está contaminada/ausente.
    """
    zone = sorted(
        [c for c in row_chars if YEAR_X0 - 1 <= c['x0'] <= YEAR_X1 + 1],
        key=lambda c: c['x0']
    )
    text = ''.join(c['text'] for c in zone)
    m = re.search(r'(20\d{2})', text)
    return int(m.group(1)) if m else None


def _detect_years_global(all_rows):
    """
    Detecta los dos años usados en el documento mirando todas las filas.
    Filtra falsos positivos (debe estar en zona YEAR_X0 ± 2).
    """
    years = set()
    for row_chars in all_rows:
        yr = _year_from_row(row_chars)
        if yr:
            years.add(yr)
    years = sorted(years)
    if len(years) >= 2:
        return years[-1], years[-2]   # actual, anterior
    elif len(years) == 1:
        return years[0], years[0] - 1
    return 2026, 2025


def _extract_description(row_chars):
    """
    Extrae la descripción del producto desde x=70 hasta donde termina texto
    antes de la zona numérica. Filtra dígitos sueltos de columnas adyacentes.
    """
    desc_chars = [c for c in sorted(row_chars, key=lambda c: c['x0'])
                  if 70 <= c['x0'] < 315]

    # Construir texto carácter a carácter; parar cuando empiecen columnas puras
    tokens = []
    for c in desc_chars:
        # Ignorar dígitos que caen exactamente en posiciones de columna
        if c['text'].isdigit():
            # Columnas numéricas: stock y smin son right-aligned (hasta 3 dígitos)
            # → filtrar desde x_anchor-2*DIGIT_W hasta x_anchor
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
    # Limpiar espacios múltiples
    desc = re.sub(r'  +', ' ', desc)
    return desc


# ─── Extracción principal ──────────────────────────────────────────────────────

def extract_products(pdf_path):
    """
    Extrae todos los productos de un PDF de estadísticas de ventas.
    Devuelve dict: { código: {...} }
    """
    products = {}

    with pdfplumber.open(pdf_path) as pdf:

        # Paso 1: recopilar todas las filas de todas las páginas para
        #         detectar años de forma global y robusta
        all_rows = []
        pages_rows = []   # lista de dicts {y: [chars]}

        for page in pdf.pages:
            rows = defaultdict(list)
            for c in page.chars:
                y = round(c['top'] / 2) * 2
                rows[y].append(c)
            pages_rows.append(rows)
            all_rows.extend(rows.values())

        year_current, year_prev = _detect_years_global(all_rows)

        # Paso 2: recorrer cada página
        for page_idx, rows in enumerate(pages_rows):
            sorted_ys = sorted(rows.keys())

            for i, y in enumerate(sorted_ys):
                row = rows[y]

                # ── Detectar código de producto ───────────────────────────
                code_chars = sorted(
                    [c for c in row if 20 <= c['x0'] < 60],
                    key=lambda c: c['x0']
                )
                code = ''.join(c['text'] for c in code_chars).strip()

                if not re.match(r'^[0-9A-Z]{6}$', code):
                    continue

                # ── Patrón A vs B (detectar año en columna Año) ──────────
                yr_this_row = _year_from_row(row)
                is_pattern_a = (yr_this_row is not None)

                # ── Descripción ───────────────────────────────────────────
                description = _extract_description(row)

                # Si descripción está vacía, buscar en fila anterior
                if not description and i > 0:
                    prev_row = rows[sorted_ys[i - 1]]
                    prev_min_x = min((c['x0'] for c in prev_row), default=999)
                    if 60 <= prev_min_x < 100:
                        description = _extract_description(prev_row)

                # ── Stock y S.min ─────────────────────────────────────────
                stock = _digits_at(row, STOCK_X)
                smin  = _digits_at(row, SMIN_X)

                # Validación: si la zona tiene letras cerca de stock/smin,
                # puede haber contaminación → marcar para revisión
                zone_letters = [c for c in row
                                if 200 <= c['x0'] < 255
                                and c['text'].isalpha()]
                stock_warning = len(zone_letters) > 0

                # ── Meses y total (SIEMPRE fiables) ──────────────────────
                months_current = [0] * 12
                months_prev    = [0] * 12

                # Patrón B: los datos de year_current están en la fila del código
                # Patrón A: la fila del código YA tiene el año → leer aquí directamente
                if not is_pattern_a:
                    # Patrón B: meses 2026 en esta misma fila
                    months_current = [_month_value(row, mx) for mx in MONTH_X]
                elif yr_this_row == year_current:
                    # Patrón A: código y datos del año actual en la misma fila
                    months_current = [_month_value(row, mx) for mx in MONTH_X]
                    stock = _digits_at(row, STOCK_X)
                    smin  = _digits_at(row, SMIN_X)

                # Buscar filas de años adicionales (principalmente year_prev,
                # pero también year_current si no se leyó arriba)
                for j in range(i + 1, min(i + 8, len(sorted_ys))):
                    y2 = sorted_ys[j]
                    row2 = rows[y2]

                    # Parar si encontramos otro código de producto
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
                        # Solo si no lo leímos ya de la fila del código
                        months_current = months2
                        stock = _digits_at(row2, STOCK_X)
                        smin  = _digits_at(row2, SMIN_X)
                    elif yr2 == year_prev:
                        months_prev = months2

                total_current = sum(months_current)
                total_prev    = sum(months_prev)

                # ── Validación cruzada ────────────────────────────────────
                warnings = []

                if stock_warning:
                    warnings.append('stock_smin_zona_contaminada')

                # Detectar valores de stock imposiblemente altos
                if stock > 9999:
                    warnings.append(f'stock_sospechoso:{stock}')
                    stock = None   # forzar revisión humana
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


# ─── Comparación ──────────────────────────────────────────────────────────────

def compare_products(products1, products2,
                     name1='Farmacia 1', name2='Farmacia 2'):
    """
    Compara productos de dos farmacias.
    Gestiona correctamente PDFs con años distintos:
    - Si una farmacia solo tiene datos de year_prev (PDF del año anterior),
      su columna year_current aparece como '—' en el comparativo.
    """
    all_codes = sorted(set(products1.keys()) | set(products2.keys()))
    results = []

    # ── Determinar el año de referencia global ─────────────────────────────────
    # Es el año más reciente encontrado entre ambos PDFs
    all_yr_cur = [p.get('year_current', 0)
                  for p in list(products1.values()) + list(products2.values())]
    global_yr_cur  = max(all_yr_cur) if all_yr_cur else 2026
    global_yr_prev = global_yr_cur - 1

    def _totals(p):
        """
        Devuelve (total_cur, total_prev) normalizados al año global.
        Si el PDF de la farmacia solo llega hasta global_yr_prev,
        su 'year_current' es en realidad global_yr_prev → total_cur='—'
        """
        if p is None:
            return '—', '—'
        yr = p.get('year_current', global_yr_cur)
        if yr == global_yr_cur:
            return p.get('total_current', 0), p.get('total_prev', 0)
        elif yr == global_yr_prev:
            # PDF solo tiene datos del año anterior: cur→prev, prev→vacío
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
        else:
            status = 'only2'
            description = p2['description']

        warnings = []
        if p1 and p1.get('warnings'):
            warnings += [f'{name1}:{w}' for w in p1['warnings']]
        if p2 and p2.get('warnings'):
            warnings += [f'{name2}:{w}' for w in p2['warnings']]

        t1_cur, t1_prev = _totals(p1)
        t2_cur, t2_prev = _totals(p2)

        results.append({
            'code':         code,
            'description':  description,
            'status':       status,
            'stock1':       _val(p1, 'stock'),
            'smin1':        _val(p1, 'smin'),
            'total1':       t1_cur,
            'total1_prev':  t1_prev,
            'stock2':       _val(p2, 'stock'),
            'smin2':        _val(p2, 'smin'),
            'total2':       t2_cur,
            'total2_prev':  t2_prev,
            'year_current': global_yr_cur,
            'year_prev':    global_yr_prev,
            'warnings':     warnings,
            'needs_review': bool(warnings),
        })

    return results



# ─── Detección de laboratorio ──────────────────────────────────────────────────

import json as _json
import re as _re
from collections import Counter as _Counter
from pathlib import Path as _Path

_LABS_FILE = _Path(__file__).parent / 'labs.json'

# Stopwords que no son nombres de marca
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
    'MINERAL','SOLAR','SOLAR','PROTECCION','SUNSCREEN','SENSITIVE',
}

# Normalizaciones: palabra frecuente en nombres de producto → laboratorio
_NORMALIZE = {
    # Aboca
    'ABOCA': 'Aboca', 'GRINTUSS': 'Aboca', 'NEOBIANACID': 'Aboca',
    'MELILAX': 'Aboca', 'LENODIAR': 'Aboca', 'ALIVIOLAS': 'Aboca',
    'COLIGAS': 'Aboca', 'COLILEN': 'Aboca', 'FITONASAL': 'Aboca',
    'FITOSTILL': 'Aboca', 'FISIOVEN': 'Aboca', 'GOLAMIR': 'Aboca',
    'IMMUNOMIX': 'Aboca', 'LIBRAMED': 'Aboca', 'LYNFASE': 'Aboca',
    'METARECOD': 'Aboca', 'NEOFITOROID': 'Aboca', 'OROBEN': 'Aboca',
    'SEDIVITAX': 'Aboca', 'PROPOL': 'Aboca',
    # Arkopharma
    'ARKOPHARMA': 'Arkopharma', 'ARKO': 'Arkopharma', 'ARKOFLEX': 'Arkopharma',
    'ARKOREAL': 'Arkopharma', 'ARKOVOX': 'Arkopharma', 'ARKOCAPS': 'Arkopharma',
    'ARKOVITAL': 'Arkopharma',
    # Bioderma
    'BIODERMA': 'Bioderma', 'SENSIBIO': 'Bioderma', 'SEBIUM': 'Bioderma',
    'ATODERM': 'Bioderma', 'PHOTODERM': 'Bioderma', 'PIGMENTBIO': 'Bioderma',
    'CICABIO': 'Bioderma',
    # Bipole / Viñas
    'BIPOLE': 'Bipole', 'INTEGRALIA': 'Bipole',
    # Bepanthol
    'BEPANTHOL': 'Bepanthol',
    # Caudalie
    'CAUDALIE': 'Caudalie', 'VINOPERFECT': 'Caudalie', 'VINOSOURCE': 'Caudalie',
    'VINOCLEAN': 'Caudalie', 'VINERGETIC': 'Caudalie',
    # CeraVe
    'CERAVE': 'CeraVe',
    # Cinfa
    'CINFA': 'Cinfa',
    # Colnatur
    'COLNATUR': 'Colnatur / Ordesa', 'BLEVIT': 'Colnatur / Ordesa',
    'BLEMIL': 'Colnatur / Ordesa', 'SANUTRI': 'Colnatur / Ordesa',
    # Cumlaude
    'CUMLAUDE': 'Cumlaude', 'DAYLONG': 'Cumlaude',
    # Dememory
    'DEMEMORY': 'Dememory',
    # Epaplus
    'EPAPLUS': 'Epaplus',
    # Eucerin
    'EUCERIN': 'Eucerin', 'UREAREPAIR': 'Eucerin', 'AQUAPHOR': 'Eucerin',
    # Heliocare
    'HELIOCARE': 'Heliocare',
    # ISDIN
    'ISDIN': 'ISDIN', 'UREADIN': 'ISDIN', 'ERYFOTONA': 'ISDIN',
    'NUTRADEICA': 'ISDIN', 'LAMBDAPIL': 'ISDIN',
    # Juanola
    'JUANOLA': 'Juanola / Angelini', 'ANGELINI': 'Juanola / Angelini',
    # Kin
    'KINERASE': 'Kin',
    # La Roche-Posay
    'POSAY': 'La Roche-Posay', 'ANTHELIOS': 'La Roche-Posay',
    'CICAPLAST': 'La Roche-Posay', 'EFFACLAR': 'La Roche-Posay',
    'LIPIKAR': 'La Roche-Posay', 'TOLERIANE': 'La Roche-Posay',
    'HYDRAPHASE': 'La Roche-Posay', 'SUBSTIANE': 'La Roche-Posay',
    'PIGMENTCLAR': 'La Roche-Posay', 'SPOTSCAN': 'La Roche-Posay',
    # L'Oreal
    'LOREAL': "L'Oreal", 'REVITALIFT': "L'Oreal",
    # Martiderm
    'MARTIDERM': 'Martiderm',
    # Mesoestetic
    'MESOESTETIC': 'Mesoestetic',
    # Mustela / Varisan
    'MUSTELA': 'Mustela', 'VARISAN': 'Varisan',
    'STELATOPIA': 'Mustela', 'STELATRIA': 'Mustela',
    'CICASTELA': 'Mustela',
    # Neostrata
    'NEOSTRATA': 'Neostrata',
    # Neutrogena
    'NEUTROGENA': 'Neutrogena',
    # Nivea
    'NIVEA': 'Nivea',
    # Nutralie
    'NUTRALIE': 'Nutralie',
    # Nuxe
    'NUXE': 'Nuxe', 'HUILE': 'Nuxe',
    # Reckitt
    'NUROFEN': 'Reckitt', 'STREPSILS': 'Reckitt', 'GAVISCON': 'Reckitt',
    'DUREX': 'Reckitt', 'MUCINEX': 'Reckitt',
    # Rilastil (Cumlaude Lab)
    'RILASTIL': 'Rilastil',
    # Sensilis / Pierre Fabre
    'SENSILIS': 'Sensilis / Pierre Fabre', 'FABRE': 'Sensilis / Pierre Fabre',
    'KLORANE': 'Sensilis / Pierre Fabre', 'AVENE': 'Sensilis / Pierre Fabre',
    'DUCRAY': 'Sensilis / Pierre Fabre', 'KERTYOL': 'Sensilis / Pierre Fabre',
    'ANACAPS': 'Sensilis / Pierre Fabre', 'ICTYANE': 'Sensilis / Pierre Fabre',
    # Sesderma
    'SESDERMA': 'Sesderma', 'ENDOCARE': 'Sesderma', 'RETISES': 'Sesderma',
    # SVR
    'SVRGEL': 'SVR', 'CICAVIT': 'SVR', 'SEBIACLEAR': 'SVR', 'CLAIRIAL': 'SVR',
    # Uriage
    'URIAGE': 'Uriage', 'XEMOSE': 'Uriage', 'BARIEDERM': 'Uriage',
    'PRURICED': 'Uriage', 'ROSELIANE': 'Uriage',
    # Vichy
    'VICHY': 'Vichy', 'LIFTACTIV': 'Vichy', 'NORMADERM': 'Vichy',
    'DERMABLEND': 'Vichy', 'AQUALIA': 'Vichy',
}


def _load_labs():
    """Carga el mapa código→nombre desde labs.json."""
    if _LABS_FILE.exists():
        with open(_LABS_FILE, 'r', encoding='utf-8') as f:
            data = _json.load(f)
        return {k: v for k, v in data.items() if not k.startswith('_')}
    return {}


def _save_lab(code, name):
    """Guarda un código nuevo en labs.json para futuras referencias."""
    labs = {}
    if _LABS_FILE.exists():
        with open(_LABS_FILE, 'r', encoding='utf-8') as f:
            labs = _json.load(f)
    labs[code] = name
    with open(_LABS_FILE, 'w', encoding='utf-8') as f:
        _json.dump(labs, f, ensure_ascii=False, indent=2)


def _guess_from_descriptions(pdf_path):
    """
    Intenta deducir el nombre del lab analizando las palabras más frecuentes
    en la zona de descripciones de producto. Devuelve un nombre legible o None.
    """
    word_count = _Counter()
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages[:-1]:  # ignorar última página (criterios)
            # Usar extract_words para tener palabras limpias
            words = page.extract_words(x_tolerance=4, y_tolerance=4)
            for w in words:
                # Solo zona de descripción (x aprox 60-210)
                if 60 <= w['x0'] <= 210:
                    tok = w['text'].upper()
                    # Solo palabras de 4+ letras, solo letras
                    if len(tok) >= 4 and tok.isalpha() and tok not in _STOP:
                        word_count[tok] += 1

    # Buscar la primera coincidencia en _NORMALIZE
    for word, _ in word_count.most_common(15):
        if word in _NORMALIZE:
            return _NORMALIZE[word]

    # Fallback: devolver la palabra más frecuente capitalizada
    if word_count:
        top = word_count.most_common(1)[0][0]
        return top.capitalize()
    return None


def detect_lab(pdf_path):
    """
    Detecta el nombre del laboratorio de un PDF de estadísticas.
    
    Estrategia:
      1. Extrae el código del PDF (última página: 'Laboratorio: XXXX')
      2. Busca el código en labs.json
      3. Si no está, intenta deducirlo de las descripciones de producto
      4. Si lo deduce, lo guarda en labs.json para el futuro
      5. Fallback: devuelve 'Lab XXXX'
    """
    labs = _load_labs()

    with pdfplumber.open(pdf_path) as pdf:
        last_text = pdf.pages[-1].extract_text() or ''
    
    m = _re.search(r'Laboratorio[:\s]+(\w+)', last_text)
    code = m.group(1).strip() if m else None

    # Código conocido en labs.json
    if code and code in labs:
        return labs[code]

    # Auto-detección desde descripciones
    guessed = _guess_from_descriptions(pdf_path)
    if guessed:
        if code:
            _save_lab(code, guessed)  # aprender para el futuro
        return guessed

    # Último recurso
    return f'Lab {code}' if code else 'Laboratorio desconocido'