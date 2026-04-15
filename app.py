from flask import Flask, request, render_template, send_file, session, redirect, url_for, jsonify
import os, tempfile, uuid, json, threading
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
except ImportError:
    pass
from pdf_parser import extract_products, compare_products, detect_lab, extract_situation, detect_pdf_header

try:
    import anthropic as _anthropic
    _AI_AVAILABLE = bool(os.environ.get('ANTHROPIC_API_KEY'))
except ImportError:
    _AI_AVAILABLE = False

# ── Facturas: factores PVP por proveedor ──────────────────────────────────────
_CONFIG_PROVEEDORES = {
    'hefame_bida': {
        'nombre': 'Hefame / BIDA',
        'factores': {
            'iva21':        {'etiqueta': 'IVA 21%',            'factor': 1.68},
            'iva10_diet':   {'etiqueta': 'IVA 10% Dietético',  'factor': 1.3585},
            'iva10_nodiet': {'etiqueta': 'IVA 10% No Diet.',   'factor': 1.48},
            'iva5':         {'etiqueta': 'IVA 5%',             'factor': 1.3063},
            'veterinaria':  {'etiqueta': 'VET',                'factor': 1.48},
        },
    },
    'laboratorio': {
        'nombre': 'Laboratorio (directo)',
        'factores': {
            'iva21':        {'etiqueta': 'IVA 21%',            'factor': 1.8},
            'iva10_diet':   {'etiqueta': 'IVA 10% Dietético',  'factor': 1.3925},
            'iva10_nodiet': {'etiqueta': 'IVA 10% No Diet.',   'factor': 1.59},
            'iva4':         {'etiqueta': 'IVA 4%',             'factor': 1.3933},
            'veterinaria':  {'etiqueta': 'VET',                'factor': 0},
        },
    },
}

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm

app = Flask(__name__)
app.secret_key = 'farmacias_barris_zarzuelo_2026'

# Progreso de trabajos en curso: { job_token: {pct, step, done, error_msg, comp_token, lab_slug} }
_progress_store = {}

# ── Configuración ──────────────────────────────────────────────────────────────
PASSWORD             = "farmacias2026"
PEDIDOS_DIR          = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pedidos')
os.makedirs(PEDIDOS_DIR, exist_ok=True)
MAX_PDF_MB           = 20
app.config['MAX_CONTENT_LENGTH'] = MAX_PDF_MB * 1024 * 1024

# ── Colores ────────────────────────────────────────────────────────────────────
C_HEADER    = colors.HexColor('#166534')   # verde acento web
C_Z_BG      = colors.HexColor('#fef2f2')   # rojo muy suave
C_B_BG      = colors.HexColor('#eff6ff')   # azul muy suave
C_Z_HDR     = colors.HexColor('#dc2626')   # rojo farmacia 1
C_B_HDR     = colors.HexColor('#1d4ed8')   # azul farmacia 2
C_ROW_ALT   = colors.HexColor('#f3f4f6')   # gris muy suave (fila par)
C_GRID      = colors.HexColor('#d1fae5')   # borde verde suave
C_WARNING   = colors.HexColor('#fef9c3')
C_PARADO    = colors.HexColor('#ffe0b2')   # naranja suave → stock parado
C_PEDIDO    = colors.HexColor('#dcfce7')   # verde suave → pedido > 0

# ── Login ──────────────────────────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form.get('password') == PASSWORD:
            session['authenticated'] = True
            return redirect(url_for('index'))
        error = 'Contraseña incorrecta'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.before_request
def check_auth():
    if request.endpoint in ('login', 'static'):
        return
    if not session.get('authenticated'):
        return redirect(url_for('login'))

# ── Rutas ──────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/detect_pdf', methods=['POST'])
def detect_pdf_route():
    f = request.files.get('file')
    if not f:
        return jsonify({'error': 'No file'}), 400
    header = f.read(4)
    f.seek(0)
    if header != b'%PDF':
        return jsonify({'error': 'Not a PDF'}), 400
    tmp = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
    try:
        f.save(tmp.name)
        tmp.close()
        result = detect_pdf_header(tmp.name)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    return jsonify(result)

@app.route('/comparar', methods=['POST'])
def comparar():
    file1 = request.files.get('pdf1')
    file2 = request.files.get('pdf2')
    sit1  = request.files.get('sit1')
    sit2  = request.files.get('sit2')
    name1 = request.form.get('name1', 'Farmacia 1').strip()
    name2 = request.form.get('name2', 'Farmacia 2').strip()

    if not file1 or not file2:
        return jsonify({'error': 'Debes subir los dos PDFs de ventas'}), 400

    for f, nombre in [(file1, name1), (file2, name2)]:
        header = f.read(4)
        f.seek(0)
        if header != b'%PDF':
            return jsonify({'error': f'El archivo de {nombre} no es un PDF válido'}), 400

    def _is_valid_pdf(f):
        if not f or f.filename == '':
            return False
        header = f.read(4)
        f.seek(0)
        return header == b'%PDF'

    has_sit1 = _is_valid_pdf(sit1)
    has_sit2 = _is_valid_pdf(sit2)

    tmp1 = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
    tmp2 = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
    file1.save(tmp1.name)
    file2.save(tmp2.name)

    tmp_sit1 = tmp_sit2 = None
    if has_sit1:
        tmp_sit1 = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        sit1.save(tmp_sit1.name)
    if has_sit2:
        tmp_sit2 = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        sit2.save(tmp_sit2.name)

    # Limpiar trabajo anterior de la sesión
    old_token = session.get('comp_token')
    if old_token:
        for ext in ['json', 'pdf']:
            p = os.path.join(tempfile.gettempdir(), f'comp_{old_token}.{ext}')
            if os.path.exists(p):
                try: os.unlink(p)
                except OSError: pass

    job_token = str(uuid.uuid4())
    _progress_store[job_token] = {
        'pct': 0, 'step': 'Iniciando análisis…',
        'done': False, 'error_msg': None,
        'comp_token': None, 'lab_slug': None,
    }

    t = threading.Thread(
        target=_run_comparison,
        args=(job_token, tmp1.name, tmp2.name,
              tmp_sit1.name if tmp_sit1 else None,
              tmp_sit2.name if tmp_sit2 else None,
              name1, name2, has_sit1, has_sit2),
        daemon=True,
    )
    t.start()

    return jsonify({'job': job_token})


def _run_comparison(job_token, path1, path2, path_sit1, path_sit2,
                    name1, name2, has_sit1, has_sit2):
    store = _progress_store[job_token]

    def upd(pct, step):
        store['pct']  = min(int(pct), 99)
        store['step'] = step

    try:
        with app.app_context():
            # Rangos dinámicos según si hay situación
            n_extra = (1 if has_sit1 else 0) + (1 if has_sit2 else 0)
            pct_pdf1_end  = 42 if n_extra == 0 else (35 if n_extra == 1 else 28)
            pct_pdf2_end  = 72 if n_extra == 0 else (58 if n_extra == 1 else 52)

            upd(2, 'Detectando laboratorio…')
            lab1 = detect_lab(path1)
            lab2 = detect_lab(path2)

            if lab1 != lab2:
                store['done']      = True
                store['error_msg'] = (f'Los PDFs pertenecen a laboratorios distintos: '
                                      f'{lab1} y {lab2}. Sube PDFs del mismo laboratorio.')
                return

            # PDF 1
            upd(5, f'Leyendo ventas — {name1} (página 1…)')
            def cb1(pg, total):
                upd(5 + (pct_pdf1_end - 5) * pg / total,
                    f'Leyendo ventas — {name1} ({pg}/{total} páginas)')
            products1 = extract_products(path1, on_page=cb1)

            # PDF 2
            upd(pct_pdf1_end + 1, f'Leyendo ventas — {name2} (página 1…)')
            def cb2(pg, total):
                upd(pct_pdf1_end + (pct_pdf2_end - pct_pdf1_end) * pg / total,
                    f'Leyendo ventas — {name2} ({pg}/{total} páginas)')
            products2 = extract_products(path2, on_page=cb2)

            # Situaciones (opcionales)
            situation1 = situation2 = None
            pct_now = pct_pdf2_end
            if has_sit1:
                upd(pct_now + 1, f'Leyendo situación — {name1}…')
                situation1 = extract_situation(path_sit1)
                pct_now += 10
            if has_sit2:
                upd(pct_now + 1, f'Leyendo situación — {name2}…')
                situation2 = extract_situation(path_sit2)
                pct_now += 10

            upd(pct_now + 2, 'Comparando productos…')
            results = compare_products(
                products1, products2, name1, name2,
                situation1=situation1, situation2=situation2,
            )

            upd(82, 'Generando informe PDF…')
            comp_token = str(uuid.uuid4())
            pdf_path   = os.path.join(tempfile.gettempdir(), f'comp_{comp_token}.pdf')
            json_path  = os.path.join(tempfile.gettempdir(), f'comp_{comp_token}.json')

            generate_pdf(
                results, pdf_path, name1, name2,
                len(products1), len(products2), lab1,
                has_situation1=has_sit1, has_situation2=has_sit2,
            )

            upd(93, 'Guardando datos…')

            def _jsonable(v):
                if v is None or v == '—' or v == '⚠️':
                    return str(v)
                return v

            safe_results = [{k: _jsonable(v) for k, v in r.items()} for r in results]
            lab_slug = (lab1.replace(' ', '_').replace('-', '_')
                            .replace("'", '').replace('é', 'e')
                            .replace('à', 'a').replace('ó', 'o'))

            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump({
                    'results':      safe_results,
                    'name1':        name1,
                    'name2':        name2,
                    'lab':          lab1,
                    'lab_slug':     lab_slug,
                    'count1':       len(products1),
                    'count2':       len(products2),
                    'has_sit1':     has_sit1,
                    'has_sit2':     has_sit2,
                    'current_year': datetime.now().year,
                }, f, ensure_ascii=False)

            store['comp_token'] = comp_token
            store['lab_slug']   = lab_slug
            store['pct']        = 100
            store['step']       = '¡Análisis completado!'
            store['done']       = True

    except Exception as e:
        store['done']      = True
        store['error_msg'] = f'Error durante el análisis: {e}'

    finally:
        for p in [path1, path2, path_sit1, path_sit2]:
            if p and os.path.exists(p):
                try: os.unlink(p)
                except OSError: pass


@app.route('/progress/<job_token>')
def progress(job_token):
    store = _progress_store.get(job_token)
    if not store:
        return jsonify({'error': 'not_found'}), 404
    return jsonify({
        'pct':       store['pct'],
        'step':      store['step'],
        'done':      store['done'],
        'error_msg': store.get('error_msg'),
    })


@app.route('/finalizar/<job_token>')
def finalizar(job_token):
    store = _progress_store.pop(job_token, None)
    if not store or not store.get('done') or store.get('error_msg'):
        return redirect(url_for('index'))
    session['comp_token'] = store['comp_token']
    session['lab_slug']   = store['lab_slug']
    return redirect(url_for('resultado'))

@app.route('/resultado')
def resultado():
    token = session.get('comp_token')
    if not token:
        return redirect(url_for('index'))
    json_path = os.path.join(tempfile.gettempdir(), f'comp_{token}.json')
    if not os.path.exists(json_path):
        return redirect(url_for('index'))
    with open(json_path, encoding='utf-8') as f:
        data = json.load(f)
    return render_template('comparativa.html', **data)


@app.route('/descargar')
def descargar():
    token = session.get('comp_token')
    if not token:
        return redirect(url_for('index'))
    pdf_path = os.path.join(tempfile.gettempdir(), f'comp_{token}.pdf')
    if not os.path.exists(pdf_path):
        return redirect(url_for('resultado'))
    lab_slug = session.get('lab_slug', 'comparativa')
    return send_file(pdf_path, as_attachment=True,
                     download_name=f'comparativa_{lab_slug}.pdf',
                     mimetype='application/pdf')


@app.route('/pedido')
def pedido():
    token = session.get('comp_token')
    if not token:
        return redirect(url_for('index'))
    json_path = os.path.join(tempfile.gettempdir(), f'comp_{token}.json')
    if not os.path.exists(json_path):
        return redirect(url_for('index'))
    with open(json_path, encoding='utf-8') as f:
        data = json.load(f)
    return render_template('pedido.html', **data)


@app.route('/pedido_pdf', methods=['POST'])
def pedido_pdf():
    if not session.get('authenticated'):
        return jsonify({'error': 'no auth'}), 401
    data  = request.get_json(force=True)
    lab   = data.get('lab',   'Farmacia')
    name1 = data.get('name1', 'Farmacia 1')
    name2 = data.get('name2', 'Farmacia 2')
    rows  = data.get('rows',  [])

    tmp = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
    tmp.close()
    _generate_pedido_pdf(rows, tmp.name, lab, name1, name2)

    from datetime import date as _date
    slug  = ''.join(c if c.isalnum() else '_' for c in lab.lower())
    fecha = _date.today().strftime('%Y%m%d')
    return send_file(tmp.name, as_attachment=True,
                     download_name=f'pedido_{slug}_{fecha}.pdf',
                     mimetype='application/pdf')


@app.route('/save_pedido_pdf', methods=['POST'])
def save_pedido_pdf():
    if not session.get('authenticated'):
        return jsonify({'error': 'no auth'}), 401
    data     = request.get_json(force=True)
    order_id = data.get('order_id', '')
    lab      = data.get('lab',      'Farmacia')
    name1    = data.get('name1',    'Farmacia 1')
    name2    = data.get('name2',    'Farmacia 2')
    rows     = data.get('rows',     [])
    if not order_id:
        return jsonify({'error': 'order_id required'}), 400
    safe_id  = ''.join(c if c.isalnum() or c in '-_' else '_' for c in order_id)
    pdf_path = os.path.join(PEDIDOS_DIR, f'{safe_id}.pdf')
    _generate_pedido_pdf(rows, pdf_path, lab, name1, name2)
    return jsonify({'pdf_id': safe_id})


@app.route('/pedido_file/<pdf_id>')
def pedido_file(pdf_id):
    if not session.get('authenticated'):
        return redirect(url_for('login'))
    safe_id  = ''.join(c if c.isalnum() or c in '-_' else '_' for c in pdf_id)
    pdf_path = os.path.join(PEDIDOS_DIR, f'{safe_id}.pdf')
    if not os.path.exists(pdf_path):
        return 'PDF no encontrado', 404
    return send_file(pdf_path, mimetype='application/pdf',
                     as_attachment=False,
                     download_name=f'pedido_{safe_id}.pdf')


@app.route('/encargos')
def encargos():
    return render_template('encargos.html')


@app.route('/pregunta', methods=['POST'])
def pregunta():
    if not session.get('authenticated'):
        return jsonify({'error': 'no auth'}), 401

    if not _AI_AVAILABLE:
        return jsonify({'answer': 'IA no configurada. Añade ANTHROPIC_API_KEY como variable de entorno.'})

    body = request.get_json(silent=True) or {}
    question = body.get('question', '').strip()
    if not question:
        return jsonify({'error': 'pregunta vacía'}), 400

    p = body.get('product', {})
    name1 = body.get('name1', 'Farmacia 1')
    name2 = body.get('name2', 'Farmacia 2')

    ctx = f"""Producto: {p.get('code')} — {p.get('description')}

{name1}:
  Stock actual: {p.get('stock1')}  |  Stock mínimo: {p.get('smin1')}
  Ventas {p.get('year_current')}: {p.get('total1')}  |  Ventas {p.get('year_prev')}: {p.get('total1_prev')}
  Consumo medio mensual (últ. 3 meses): {p.get('avgMonthly1', '—')} uds
  Tendencia: {p.get('trend1', '—')}  |  Días de cobertura: {p.get('diasCobertura1', '—')}
  Stock parado 365d: {p.get('s365_1')}

{name2}:
  Stock actual: {p.get('stock2')}  |  Stock mínimo: {p.get('smin2')}
  Ventas {p.get('year_current')}: {p.get('total2')}  |  Ventas {p.get('year_prev')}: {p.get('total2_prev')}
  Consumo medio mensual (últ. 3 meses): {p.get('avgMonthly2', '—')} uds
  Tendencia: {p.get('trend2', '—')}  |  Días de cobertura: {p.get('diasCobertura2', '—')}
  Stock parado 365d: {p.get('s365_2')}"""

    prompt = (
        "Eres un experto en gestión de stock de farmacia. Responde de forma concisa y directa "
        "(máximo 4 frases) basándote únicamente en los datos facilitados.\n\n"
        f"Datos del producto:\n{ctx}\n\n"
        f"Pregunta: {question}"
    )

    try:
        client = _anthropic.Anthropic()
        msg = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=350,
            messages=[{'role': 'user', 'content': prompt}]
        )
        return jsonify({'answer': msg.content[0].text})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/facturas')
def facturas():
    if not session.get('authenticated'):
        return redirect(url_for('login'))
    return render_template('facturas.html')


@app.route('/leer_factura', methods=['POST'])
def leer_factura():
    if not session.get('authenticated'):
        return jsonify({'error': 'no auth'}), 401

    if not _AI_AVAILABLE:
        return jsonify({'error': 'IA no configurada. Añade ANTHROPIC_API_KEY como variable de entorno.'}), 503

    f = request.files.get('file')
    if not f:
        return jsonify({'error': 'No se recibió ningún archivo'}), 400

    mime = (f.mimetype or '').split(';')[0].strip()
    allowed = {'application/pdf', 'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
    if mime not in allowed:
        return jsonify({'error': f'Tipo de archivo no soportado: {mime}'}), 400

    data = f.read()
    if len(data) > MAX_PDF_MB * 1024 * 1024:
        return jsonify({'error': f'Archivo demasiado grande (máx {MAX_PDF_MB} MB)'}), 413

    import base64 as _b64
    b64 = _b64.b64encode(data).decode('utf-8')

    prompt = (
        "Analiza esta factura o albarán de farmacia española y extrae los datos de las líneas de producto.\n\n"
        "Devuelve ÚNICAMENTE un objeto JSON con esta estructura exacta (sin texto adicional, sin markdown):\n"
        "{\n"
        '  "proveedor": "nombre del proveedor/laboratorio o null",\n'
        '  "numero_factura": "número o null",\n'
        '  "fecha": "DD/MM/YYYY o null",\n'
        '  "lineas": [\n'
        "    {\n"
        '      "cn": "código nacional 6-7 dígitos o null",\n'
        '      "nombre": "descripción del producto",\n'
        '      "cantidad": número entero,\n'
        '      "precio_neto_unitario": número decimal,\n'
        '      "precio_neto_total": número decimal,\n'
        '      "iva_porcentaje": 4 o 5 o 10 o 21,\n'
        '      "recargo": número decimal o 0\n'
        "    }\n"
        "  ],\n"
        '  "total_sin_iva": número decimal o null,\n'
        '  "total_con_iva": número decimal o null\n'
        "}\n\n"
        "REGLAS:\n"
        "- Incluye SOLO líneas que sean productos vendibles con precio unitario > 0\n"
        "- NO incluyas: subtotales, descuentos globales, portes, cuotas IVA, líneas sin precio\n"
        "- precio_neto_unitario: precio unitario ya con descuentos aplicados, SIN IVA\n"
        "- iva_porcentaje: el % real de IVA de esa línea (4, 5, 10 o 21)\n"
        "- cantidad mínima 1 si no se especifica\n"
        "- Números con punto como separador decimal, sin puntos de miles\n"
        "- Si una línea es ambigua, exclúyela"
    )

    try:
        client = _anthropic.Anthropic()
        if mime == 'application/pdf':
            content = [
                {'type': 'document', 'source': {'type': 'base64', 'media_type': 'application/pdf', 'data': b64}},
                {'type': 'text', 'text': prompt},
            ]
        else:
            content = [
                {'type': 'image', 'source': {'type': 'base64', 'media_type': mime, 'data': b64}},
                {'type': 'text', 'text': prompt},
            ]

        msg = client.messages.create(
            model='claude-opus-4-6',
            max_tokens=8192,
            messages=[{'role': 'user', 'content': content}],
        )

        raw = msg.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith('```'):
            lines = raw.split('\n')
            raw = '\n'.join(lines[1:-1] if lines[-1].strip() == '```' else lines[1:])
        result = json.loads(raw)
        result['proveedores'] = _CONFIG_PROVEEDORES
        return jsonify(result)

    except json.JSONDecodeError as e:
        return jsonify({'error': f'No se pudo parsear la respuesta de la IA: {e}'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.errorhandler(413)
def too_large(e):
    return f'El PDF es demasiado grande. Máximo {MAX_PDF_MB}MB por archivo.', 413


# ── Generación del PDF ─────────────────────────────────────────────────────────
def generate_pdf(results, output_path, name1, name2, count1, count2,
                 lab_name='', has_situation1=False, has_situation2=False):

    from datetime import datetime as _dt

    doc = SimpleDocTemplate(
        output_path,
        pagesize=landscape(A4),
        leftMargin=1*cm, rightMargin=1*cm,
        topMargin=1.2*cm, bottomMargin=1.2*cm
    )

    title_style = ParagraphStyle('title',
        fontName='Helvetica-Bold', fontSize=11, leading=13,
        textColor=colors.white)
    sub_style = ParagraphStyle('sub',
        fontName='Helvetica', fontSize=7.5, leading=9,
        textColor=colors.HexColor('#d1fae5'))
    cell_style = ParagraphStyle('cell',
        fontName='Helvetica', fontSize=7, leading=8.5,
        textColor=colors.HexColor('#1c1a17'))

    show_s365 = has_situation1 or has_situation2

    yr_cur  = results[0]['year_current'] if results else datetime.now().year
    yr_prev = results[0]['year_prev']    if results else datetime.now().year - 1

    today   = _dt.today().strftime('%d/%m/%Y')
    n_both  = sum(1 for r in results if r['status'] == 'both')
    n_only1 = sum(1 for r in results if r['status'] == 'only1')
    n_only2 = sum(1 for r in results if r['status'] == 'only2')
    n_par1  = sum(1 for r in results if r.get('parado1'))
    n_par2  = sum(1 for r in results if r.get('parado2'))

    lab_part   = f"  ·  {lab_name}" if lab_name else ""
    title_text = f"Comparativa de Stock{lab_part}  ·  {name1} vs {name2}  ·  {today}"
    stats_parts = [
        f"{name1}: {count1} prod.", f"{name2}: {count2} prod.",
        f"Total: {len(results)}", f"Ambas: {n_both}",
        f"Solo {name1}: {n_only1}", f"Solo {name2}: {n_only2}",
    ]
    if has_situation1: stats_parts.append(f"Parados {name1}: {n_par1}")
    if has_situation2: stats_parts.append(f"Parados {name2}: {n_par2}")
    stats_text = "  ·  ".join(stats_parts)

    def hdr(text, size=7.5, bold=True):
        fn = 'Helvetica-Bold' if bold else 'Helvetica'
        return Paragraph(
            f'<font name="{fn}" size="{size}">{text}</font>',
            ParagraphStyle('_h', leading=size+2, alignment=1, textColor=colors.white))

    # ── Cabeceras ─────────────────────────────────────────────────────────────
    # Con S.365: 14 cols (2 + 6 farm1 + 6 farm2); sin S.365: 12 cols (2+5+5)

    if show_s365:
        # Cols 0-1: Cód/Desc | 2-7: Farm1 | 8-13: Farm2
        row_farmacia = ['', '',
            hdr(f'● {name1}', size=8), '', '', '', '', '',
            hdr(f'● {name2}', size=8), '', '', '', '', '']
        row_cols = [
            hdr('Cód', size=7), hdr('Descripción', size=7),
            hdr('Stock',size=7), hdr('S.min',size=7),
            hdr(f'V.{yr_cur}',size=7), hdr(f'V.{yr_prev}',size=7),
            hdr('S.365',size=7), hdr('Pedido',size=7),
            hdr('Stock',size=7), hdr('S.min',size=7),
            hdr(f'V.{yr_cur}',size=7), hdr(f'V.{yr_prev}',size=7),
            hdr('S.365',size=7), hdr('Pedido',size=7),
        ]
        span1_end = 7; span2_start = 8; span2_end = 13
        divider_col = 7
        s365_1_col = 6; s365_2_col = 12
        pedido1_col = 7; pedido2_col = 13
        col_widths = [
            1.6*cm, 5.5*cm,
            1.1*cm, 1.1*cm, 1.2*cm, 1.2*cm, 1.1*cm, 1.2*cm,
            1.1*cm, 1.1*cm, 1.2*cm, 1.2*cm, 1.1*cm, 1.2*cm,
        ]
    else:
        # Cols 0-1: Cód/Desc | 2-6: Farm1 | 7-11: Farm2
        row_farmacia = ['', '',
            hdr(f'● {name1}', size=8), '', '', '', '',
            hdr(f'● {name2}', size=8), '', '', '', '']
        row_cols = [
            hdr('Código',size=7), hdr('Descripción',size=7),
            hdr('Stock',size=7), hdr('S.min',size=7),
            hdr(f'V.{yr_cur}',size=7), hdr(f'V.{yr_prev}',size=7), hdr('Pedido',size=7),
            hdr('Stock',size=7), hdr('S.min',size=7),
            hdr(f'V.{yr_cur}',size=7), hdr(f'V.{yr_prev}',size=7), hdr('Pedido',size=7),
        ]
        span1_end = 6; span2_start = 7; span2_end = 11
        divider_col = 6
        s365_1_col = None; s365_2_col = None
        pedido1_col = 6; pedido2_col = 11
        col_widths = [
            1.8*cm, 6.0*cm,
            1.2*cm, 1.2*cm, 1.3*cm, 1.3*cm, 1.2*cm,
            1.2*cm, 1.2*cm, 1.3*cm, 1.3*cm, 1.2*cm,
        ]

    def _fmt(v):
        if v in ('—', '⚠️') or v is None: return str(v) if v else '⚠️'
        return str(v)

    data = [row_farmacia, row_cols]
    row_meta = []

    for r in results:
        idx = len(data)
        desc_text = r['description']
        # strip characters unsupported by Helvetica (e.g. ■ → black square in PDF)
        desc_text = desc_text.replace('\u25a0', '').replace('\u25cf', '').replace('\u25aa', '').strip()
        max_desc = 48 if show_s365 else 52
        if len(desc_text) > max_desc:
            desc_text = desc_text[:max_desc-2] + '…'
        warn_flag = ' ⚠' if r['needs_review'] else ''
        desc_para = Paragraph(desc_text + warn_flag, cell_style)

        if show_s365:
            row = [
                r['code'], desc_para,
                _fmt(r['stock1']), _fmt(r['smin1']),
                _fmt(r['total1']), _fmt(r['total1_prev']), _fmt(r.get('s365_1','—')),
                str(r.get('pedido1', 0)),
                _fmt(r['stock2']), _fmt(r['smin2']),
                _fmt(r['total2']), _fmt(r['total2_prev']), _fmt(r.get('s365_2','—')),
                str(r.get('pedido2', 0)),
            ]
        else:
            row = [
                r['code'], desc_para,
                _fmt(r['stock1']), _fmt(r['smin1']),
                _fmt(r['total1']), _fmt(r['total1_prev']),
                str(r.get('pedido1', 0)),
                _fmt(r['stock2']), _fmt(r['smin2']),
                _fmt(r['total2']), _fmt(r['total2_prev']),
                str(r.get('pedido2', 0)),
            ]
        data.append(row)
        row_meta.append((idx, r['status'], r['needs_review'],
                         r.get('parado1',False), r.get('parado2',False),
                         r.get('pedido1', 0), r.get('pedido2', 0)))

    table = Table(data, colWidths=col_widths, repeatRows=2)

    ts = TableStyle([
        ('BACKGROUND',    (0,0), (1,0),           C_HEADER),
        ('BACKGROUND',    (2,0), (span1_end,0),   C_Z_HDR),
        ('BACKGROUND',    (span2_start,0), (-1,0),C_B_HDR),
        ('SPAN',          (2,0), (span1_end,0)),
        ('SPAN',          (span2_start,0), (-1,0)),
        ('ALIGN',         (0,0), (-1,0),  'CENTER'),
        ('VALIGN',        (0,0), (-1,0),  'MIDDLE'),
        ('ROWHEIGHT',     (0,0), (0,0),   16),
        ('BACKGROUND',    (0,1), (1,1),           C_HEADER),
        ('BACKGROUND',    (2,1), (span1_end,1),   C_Z_HDR),
        ('BACKGROUND',    (span2_start,1), (-1,1),C_B_HDR),
        ('ALIGN',         (0,1), (-1,1),  'CENTER'),
        ('VALIGN',        (0,1), (-1,1),  'MIDDLE'),
        ('ROWHEIGHT',     (0,1), (0,1),   13),
        ('FONTNAME',      (0,2), (-1,-1), 'Helvetica'),
        ('FONTSIZE',      (0,2), (-1,-1), 7),
        ('ALIGN',         (0,2), (-1,-1), 'CENTER'),
        ('ALIGN',         (1,2), (1,-1),  'LEFT'),
        ('VALIGN',        (0,2), (-1,-1), 'MIDDLE'),
        ('TOPPADDING',    (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('LEFTPADDING',   (0,0), (-1,-1), 4),
        ('RIGHTPADDING',  (0,0), (-1,-1), 4),
        ('GRID',          (0,0), (-1,-1), 0.25, C_GRID),
        ('LINEBELOW',     (0,0), (-1,0),  0.8,  colors.white),
        ('LINEBELOW',     (0,1), (-1,1),  0.8,  colors.white),
        ('LINEAFTER',     (1,0), (1,-1),  0.8,  C_GRID),
        ('LINEAFTER',     (divider_col,0),(divider_col,-1), 1.2, C_HEADER),
    ])

    for idx, status, needs_review, parado1, parado2, pedido1, pedido2 in row_meta:
        # alternating white / light-gray rows for all data rows
        if idx % 2 == 0:
            ts.add('BACKGROUND', (0,idx), (-1,idx), C_ROW_ALT)
        # gray text for columns that don't apply to this pharmacy
        if status == 'only1':
            ts.add('TEXTCOLOR', (span2_start,idx), (-1,idx), colors.HexColor('#bbbbbb'))
        elif status == 'only2':
            ts.add('TEXTCOLOR', (2,idx), (span1_end,idx), colors.HexColor('#bbbbbb'))

        if parado1:
            ts.add('BACKGROUND', (2,idx), (2,idx), C_PARADO)
            if show_s365:
                ts.add('BACKGROUND', (s365_1_col,idx), (s365_1_col,idx), C_PARADO)
        if parado2:
            ts.add('BACKGROUND', (span2_start,idx), (span2_start,idx), C_PARADO)
            if show_s365:
                ts.add('BACKGROUND', (s365_2_col,idx), (s365_2_col,idx), C_PARADO)

        if pedido1 > 0:
            ts.add('BACKGROUND', (pedido1_col,idx), (pedido1_col,idx), C_PEDIDO)
        if pedido2 > 0:
            ts.add('BACKGROUND', (pedido2_col,idx), (pedido2_col,idx), C_PEDIDO)

    table.setStyle(ts)

    # ── Leyenda ───────────────────────────────────────────────────────────────
    legend_items = [
        (C_PEDIDO,  colors.HexColor('#2e7d32'),  'Pedido sugerido'),
    ]
    if show_s365:
        legend_items.append((C_PARADO, colors.HexColor('#e65100'),
                             'Stock parado (+365d) · celda naranja = S.365'))

    legend_data = [[]]
    for bg, fg, label in legend_items:
        sw = Table([['']], colWidths=[0.35*cm], rowHeights=[0.25*cm])
        sw.setStyle(TableStyle([('BACKGROUND',(0,0),(0,0),bg),('BOX',(0,0),(0,0),0.5,fg)]))
        legend_data[0].append(sw)
        legend_data[0].append(Paragraph(
            f'<font name="Helvetica" size="6.5" color="#555555">{label}</font>',
            ParagraphStyle('leg', leading=8)))

    legend_cw = []
    for _ in legend_items:
        legend_cw += [0.45*cm, 3.8*cm]
    legend_table = Table(legend_data, colWidths=legend_cw)
    legend_table.setStyle(TableStyle([
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('LEFTPADDING',(0,0),(-1,-1),2),
        ('RIGHTPADDING',(0,0),(-1,-1),4),
    ]))

    # ── Título ────────────────────────────────────────────────────────────────
    title_data = [[Paragraph(title_text, title_style), Paragraph(stats_text, sub_style)]]
    title_table = Table(title_data, colWidths=[9.5*cm, 18.3*cm])
    title_table.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),C_HEADER),
        ('VALIGN',(0,0),(-1,0),'MIDDLE'),
        ('TOPPADDING',(0,0),(-1,0),8),('BOTTOMPADDING',(0,0),(-1,0),8),
        ('LEFTPADDING',(0,0),(-1,0),10),('RIGHTPADDING',(0,0),(-1,0),10),
    ]))

    elements = [title_table, Spacer(1,0.2*cm), legend_table, Spacer(1,0.15*cm), table]

    # ── Tabla logística (solo si hay informe de situación) ────────────────────
    if show_s365:
        log_elements = _build_logistics_table(
            results, name1, name2, has_situation1, has_situation2, cell_style)
        if log_elements:
            elements += log_elements

    doc.build(elements)


def _parse_caducidad(cad_str):
    """Convierte 'MM/YYYY' a datetime. Devuelve None si no puede."""
    if not cad_str:
        return None
    try:
        from datetime import datetime as _dt
        return _dt.strptime(cad_str, '%m/%Y')
    except ValueError:
        return None


def _build_logistics_table(results, name1, name2,
                            has_sit1, has_sit2, cell_style):
    """
    Genera la sección de análisis logístico al final del PDF.
    Detecta 3 casos:
      - Traspaso: parado en A (stock>0) y stock=0 en B
      - Exceso compartido: parado en ambas
      - Caducidad próxima: parado + caduca en ≤6 meses
    """
    from datetime import datetime as _dt
    from reportlab.platypus import KeepTogether

    now = _dt.today()
    C_LOG_HDR   = colors.HexColor('#166534')
    C_TRASPASO  = colors.HexColor('#e8f5e9')   # verde suave
    C_EXCESO    = colors.HexColor('#fff3e0')   # naranja suave
    C_CADUCIDAD = colors.HexColor('#fce4ec')   # rojo suave

    casos_traspaso  = []
    casos_exceso    = []
    casos_caducidad = []

    for r in results:
        p1 = r.get('parado1', False)
        p2 = r.get('parado2', False)
        s1 = r.get('stock1', '—')
        s2 = r.get('stock2', '—')
        cad1 = _parse_caducidad(r.get('caducidad1',''))
        cad2 = _parse_caducidad(r.get('caducidad2',''))

        # ── Caducidad próxima (≤6 meses) ─────────────────────────────────
        for parado, cad, farm, stock_val, s365_key in [
            (p1, cad1, name1, s1, 's365_1'),
            (p2, cad2, name2, s2, 's365_2'),
        ]:
            if parado and cad:
                diff_months = (cad.year - now.year)*12 + (cad.month - now.month)
                if 0 <= diff_months <= 6:
                    casos_caducidad.append({
                        'code': r['code'], 'description': r['description'],
                        'farmacia': farm, 'stock': r.get(s365_key, stock_val),
                        'caducidad': cad.strftime('%m/%Y'),
                        'meses': diff_months,
                    })

        # ── Exceso compartido ─────────────────────────────────────────────
        if p1 and p2:
            casos_exceso.append({
                'code': r['code'], 'description': r['description'],
                'stock1': r.get('s365_1', s1), 'stock2': r.get('s365_2', s2),
            })
            continue  # no añadir también a traspaso

        # ── Traspaso ──────────────────────────────────────────────────────
        def _stock_zero(v):
            try:
                return int(str(v)) == 0
            except (ValueError, TypeError):
                return v == '—'

        if p1 and _stock_zero(s2):
            casos_traspaso.append({
                'code': r['code'], 'description': r['description'],
                'origen': name1, 'destino': name2,
                'stock_origen': r.get('s365_1', s1),
            })
        elif p2 and _stock_zero(s1):
            casos_traspaso.append({
                'code': r['code'], 'description': r['description'],
                'origen': name2, 'destino': name1,
                'stock_origen': r.get('s365_2', s2),
            })

    if not casos_traspaso and not casos_exceso and not casos_caducidad:
        return []

    def log_hdr(text, color=colors.white, size=7, bg=None):
        return Paragraph(
            f'<font name="Helvetica-Bold" size="{size}" color="{"white" if color==colors.white else "#1c1a17"}">{text}</font>',
            ParagraphStyle('lh', leading=size+2, alignment=1))

    def log_cell(text, size=6.5):
        return Paragraph(
            f'<font name="Helvetica" size="{size}">{text}</font>',
            ParagraphStyle('lc', leading=size+1.5, textColor=colors.HexColor('#1c1a17')))

    section_title_style = ParagraphStyle('sct',
        fontName='Helvetica-Bold', fontSize=9, leading=11,
        textColor=colors.HexColor('#2c3e50'), spaceBefore=12, spaceAfter=4)

    elements = [
        Spacer(1, 0.5*cm),
        Paragraph('Análisis logístico · Stock parado', section_title_style),
    ]

    # ── Tabla Traspaso ────────────────────────────────────────────────────────
    if casos_traspaso:
        elements.append(Paragraph(
            '<font name="Helvetica-Bold" size="7.5" color="#2e7d32">🔄 Posible traspaso — stock parado en origen, sin stock en destino</font>',
            ParagraphStyle('sh', leading=10, spaceBefore=6, spaceAfter=2)))

        t_data = [[
            log_hdr('Código'), log_hdr('Descripción'),
            log_hdr('Origen'), log_hdr('Destino'), log_hdr('Stock parado'),
        ]]
        for c in casos_traspaso:
            t_data.append([
                log_cell(c['code']), log_cell(c['description']),
                log_cell(c['origen']), log_cell(c['destino']),
                log_cell(str(c['stock_origen'])),
            ])
        t = Table(t_data, colWidths=[1.8*cm, 9*cm, 3*cm, 3*cm, 2.5*cm])
        t.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0), colors.HexColor('#2e7d32')),
            ('FONTSIZE',(0,0),(-1,0), 7),
            ('ALIGN',(0,0),(-1,-1),'CENTER'),
            ('ALIGN',(1,1),(1,-1),'LEFT'),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[C_TRASPASO, colors.white]),
            ('GRID',(0,0),(-1,-1), 0.25, colors.HexColor('#c8e6c9')),
            ('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3),
            ('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4),
        ]))
        elements.append(t)

    # ── Tabla Exceso compartido ───────────────────────────────────────────────
    if casos_exceso:
        elements.append(Paragraph(
            f'<font name="Helvetica-Bold" size="7.5" color="#e65100">⚠️ Exceso compartido — stock parado en ambas farmacias</font>',
            ParagraphStyle('sh', leading=10, spaceBefore=8, spaceAfter=2)))

        e_data = [[
            log_hdr('Código'), log_hdr('Descripción'),
            log_hdr(f'S.365 {name1}'), log_hdr(f'S.365 {name2}'),
        ]]
        for c in casos_exceso:
            e_data.append([
                log_cell(c['code']), log_cell(c['description']),
                log_cell(str(c['stock1'])), log_cell(str(c['stock2'])),
            ])
        t = Table(e_data, colWidths=[1.8*cm, 10*cm, 3*cm, 3*cm])
        t.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0), colors.HexColor('#e65100')),
            ('FONTSIZE',(0,0),(-1,0), 7),
            ('ALIGN',(0,0),(-1,-1),'CENTER'),
            ('ALIGN',(1,1),(1,-1),'LEFT'),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[C_EXCESO, colors.white]),
            ('GRID',(0,0),(-1,-1), 0.25, colors.HexColor('#ffe0b2')),
            ('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3),
            ('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4),
        ]))
        elements.append(t)

    # ── Tabla Caducidad próxima ───────────────────────────────────────────────
    if casos_caducidad:
        casos_caducidad.sort(key=lambda x: x['meses'])
        elements.append(Paragraph(
            '<font name="Helvetica-Bold" size="7.5" color="#c62828">🕐 Caducidad próxima — stock parado con caducidad en ≤6 meses</font>',
            ParagraphStyle('sh', leading=10, spaceBefore=8, spaceAfter=2)))

        c_data = [[
            log_hdr('Código'), log_hdr('Descripción'),
            log_hdr('Farmacia'), log_hdr('S.365'), log_hdr('Caduca'), log_hdr('Meses restantes'),
        ]]
        for c in casos_caducidad:
            c_data.append([
                log_cell(c['code']), log_cell(c['description']),
                log_cell(c['farmacia']), log_cell(str(c['stock'])),
                log_cell(c['caducidad']),
                log_cell(str(c['meses']) if c['meses'] > 0 else '¡Este mes!'),
            ])
        t = Table(c_data, colWidths=[1.8*cm, 8.5*cm, 2.5*cm, 1.8*cm, 2*cm, 2.7*cm])
        t.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0), colors.HexColor('#c62828')),
            ('FONTSIZE',(0,0),(-1,0), 7),
            ('ALIGN',(0,0),(-1,-1),'CENTER'),
            ('ALIGN',(1,1),(1,-1),'LEFT'),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[C_CADUCIDAD, colors.white]),
            ('GRID',(0,0),(-1,-1), 0.25, colors.HexColor('#f8bbd0')),
            ('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3),
            ('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4),
        ]))
        elements.append(t)

    return elements


def _generate_pedido_pdf(rows, output_path, lab, name1, name2):
    """Genera un PDF limpio con el resumen del pedido manual."""
    from datetime import date as _date

    MESES = ['enero','febrero','marzo','abril','mayo','junio',
             'julio','agosto','septiembre','octubre','noviembre','diciembre']
    hoy = _date.today()
    fecha_str = f'{hoy.day} de {MESES[hoy.month-1]} de {hoy.year}'

    C_GREEN_DARK  = colors.HexColor('#14532d')
    C_GREEN_LIGHT = colors.HexColor('#f0fdf4')
    C_BORDER      = colors.HexColor('#d1fae5')
    C_MUTED       = colors.HexColor('#4b7c5e')

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm,
    )
    styles = getSampleStyleSheet()

    title_st = ParagraphStyle('pt', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=14,
        textColor=C_GREEN_DARK, spaceAfter=2)
    sub_st = ParagraphStyle('ps', parent=styles['Normal'],
        fontName='Helvetica', fontSize=9,
        textColor=C_MUTED, spaceAfter=14)
    desc_st = ParagraphStyle('pd', parent=styles['Normal'],
        fontName='Helvetica', fontSize=8, leading=10)
    hdr_st = ParagraphStyle('ph', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=7,
        textColor=colors.white, alignment=1)
    hdr_left_st = ParagraphStyle('phl', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=7,
        textColor=colors.white)
    tot_st = ParagraphStyle('ptot', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=8)

    story = [
        Paragraph(f'PEDIDO — {lab.upper()}', title_st),
        Paragraph(f'Generado el {fecha_str}', sub_st),
    ]

    # Cabecera tabla
    col_widths = [2.0*cm, 9.5*cm, 2.2*cm, 2.2*cm, 2.1*cm]
    table_data = [[
        Paragraph('Código',  hdr_left_st),
        Paragraph('Descripción', hdr_left_st),
        Paragraph(name1, hdr_st),
        Paragraph(name2, hdr_st),
        Paragraph('Total',  hdr_st),
    ]]

    for r in rows:
        qz  = r.get('qz', 0) or 0
        qb  = r.get('qb', 0) or 0
        tot = r.get('tot', 0) or 0
        table_data.append([
            r.get('code', ''),
            Paragraph(r.get('desc', ''), desc_st),
            str(qz) if qz > 0 else '—',
            str(qb) if qb > 0 else '—',
            str(tot),
        ])

    total_uds = sum(r.get('tot', 0) or 0 for r in rows)
    table_data.append([
        '', Paragraph('TOTAL', tot_st), '', '', str(total_uds),
    ])

    n = len(table_data)  # total rows incl. header
    ts = TableStyle([
        # Header row
        ('BACKGROUND',     (0, 0), (-1, 0),  C_GREEN_DARK),
        ('TEXTCOLOR',      (0, 0), (-1, 0),  colors.white),
        # Alternating body rows
        ('ROWBACKGROUNDS', (0, 1), (-1, n-2), [colors.white, C_GREEN_LIGHT]),
        # Total row
        ('BACKGROUND',     (0, n-1), (-1, n-1), C_GREEN_LIGHT),
        ('LINEABOVE',      (0, n-1), (-1, n-1), 1, C_BORDER),
        ('FONTNAME',       (0, n-1), (-1, n-1), 'Helvetica-Bold'),
        # Grid
        ('GRID',           (0, 0), (-1, -1), 0.4, C_BORDER),
        # Alignment
        ('ALIGN',          (2, 0), (-1, -1), 'CENTER'),
        ('VALIGN',         (0, 0), (-1, -1), 'MIDDLE'),
        # Padding
        ('TOPPADDING',     (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING',  (0, 0), (-1, -1), 4),
        ('LEFTPADDING',    (0, 0), (-1, -1), 6),
        ('RIGHTPADDING',   (0, 0), (-1, -1), 6),
        # Code column monospace
        ('FONTNAME',       (0, 1), (0, n-1), 'Courier'),
        ('FONTSIZE',       (0, 1), (0, n-1), 7),
        ('TEXTCOLOR',      (0, 1), (0, n-1), C_MUTED),
    ])

    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(ts)
    story.append(table)

    doc.build(story)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)