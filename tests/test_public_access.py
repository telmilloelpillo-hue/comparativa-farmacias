"""Public access and faithful PDF rendering regressions."""

import io
import json

import pdfplumber
import pytest

import app as app_module
from app import app, generate_pdf, _generate_plantilla_pdf, _generate_pedido_pdf, _generate_pedido_anotacion_pdf


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def _result(description, **overrides):
    row = {
        'code': '123456', 'description': description, 'status': 'both',
        'stock1': 2, 'stock2': -1, 'smin1': 1, 'smin2': 0,
        'total1': 4, 'total2': 4, 'total1_prev': 6, 'total2_prev': 6,
        's365_1': '—', 's365_2': '—', 'pedido1': 1, 'pedido2': 3,
        'year_current': 2026, 'year_prev': 2025,
        'parado1': False, 'parado2': False,
        'needs_review': False, 'warnings': [],
        'months1_current': [0, 0, 0, 4] + [0] * 8,
        'months2_current': [-1, 0, 0, 5] + [0] * 8,
        'months1_prev': [0] * 6 + [1] * 6,
        'months2_prev': [0] * 6 + [1] * 6,
    }
    row.update(overrides)
    return row


def _pdf_text(source):
    with pdfplumber.open(source) as pdf:
        return ' '.join(' '.join((page.extract_text() or '').split()) for page in pdf.pages)


def _assert_full_description(description, text):
    # A line-based PDF reader interleaves the code/numeric columns with a
    # wrapped description. Require every literal description token in order.
    tokens = iter(text.split())
    for expected in description.split():
        assert any(token == expected for token in tokens), expected


def test_home_and_feature_pages_open_without_password(client):
    for url in ['/', '/facturas', '/encargos']:
        response = client.get(url)
        assert response.status_code == 200
        assert b'type="password"' not in response.data
        assert b'Cerrar sesi' not in response.data
    for url in ['/resultado', '/pedido', '/buscador', '/descargar', '/plantilla_anotacion']:
        response = client.get(url)
        assert response.status_code == 302
        assert response.headers['Location'] == '/'
    with client.session_transaction() as session:
        assert 'authenticated' not in session


def test_old_login_urls_redirect_and_logout_clears_work(client):
    for response in [client.get('/login'), client.post('/login', data={'password': 'anything'})]:
        assert response.status_code == 302
        assert response.headers['Location'] == '/'
    with client.session_transaction() as session:
        session['comp_token'] = 'old-job'
        session['authenticated'] = True  # a cookie issued by an older release
    response = client.get('/logout')
    assert response.status_code == 302
    assert response.headers['Location'] == '/'
    with client.session_transaction() as session:
        assert not session


def test_public_apis_validate_input_without_login(client, monkeypatch):
    monkeypatch.setattr(app_module, '_ai_available', lambda: False)
    checks = [
        ('/detect_pdf', None, 400), ('/comparar', None, 400),
        ('/fetch_albaran', {}, 400), ('/save_pedido_pdf', {}, 400),
        ('/procesar_anotaciones', None, 400), ('/leer_factura', None, 503),
        ('/pregunta', {}, 200),
    ]
    for url, payload, expected in checks:
        response = client.post(url, json=payload) if payload is not None else client.post(url)
        assert response.status_code == expected
        assert response.is_json
    assert client.get('/pedido_file/missing').status_code == 404
    assert client.get('/buscador_pdf/00000000-0000-0000-0000-000000000000/pdf1').status_code == 404


def test_public_order_pdf_preserves_literal_and_full_description(client):
    description = 'AGUA & SOL <b>FORMULA ESPECIAL</b> INTERAPOTHEK CON UNA DESCRIPCION MUY LARGA 5000 ML COLOR CORAL FINAL'
    response = client.post('/pedido_pdf', json={
        'lab': 'Prueba & <b>Laboratorio</b>', 'name1': 'Uno & Dos', 'name2': 'Tres <b>Cuatro</b>',
        'rows': [{'code': '123456', 'desc': description, 'qz': 2, 'qb': 1, 'tot': 3}],
    })
    assert response.status_code == 200
    assert response.mimetype == 'application/pdf'
    _assert_full_description(description, _pdf_text(io.BytesIO(response.data)))


@pytest.mark.parametrize('format', ['comparison', 'ipad', 'order', 'annotation'])
def test_all_pdf_exports_preserve_long_names_and_xml_characters(tmp_path, format):
    description = 'AGUA & SOL <b>FORMULA ESPECIAL</b> INTERAPOTHEK CON UNA DESCRIPCION MUY LARGA 5000 ML COLOR CORAL FINAL'
    path = tmp_path / (format + '.pdf')
    row = _result(description)
    if format == 'comparison':
        generate_pdf([row], str(path), 'Uno & Dos', 'Tres <b>Cuatro</b>', 1, 1, 'LAB <b>A&B</b>')
    elif format == 'ipad':
        _generate_plantilla_pdf([row], str(path), 'Uno & Dos', 'Tres <b>Cuatro</b>', 'LAB <b>A&B</b>')
    elif format == 'order':
        _generate_pedido_pdf([{'code': row['code'], 'desc': description, 'qz': 2, 'qb': 1, 'tot': 3}], str(path), 'LAB <b>A&B</b>', 'Uno & Dos', 'Tres <b>Cuatro</b>')
    else:
        _generate_pedido_anotacion_pdf([{'code': row['code'], 'description': description, 'qty': 3}], str(path), 'LAB <b>A&B</b>')
    _assert_full_description(description, _pdf_text(path))


def test_ipad_rows_expand_to_fit_complete_descriptions(tmp_path):
    description = 'PRODUCTO ' + 'PRESENTACION COMPLETA PARA USO EN FARMACIA ' * 8 + 'FINAL'
    path = tmp_path / 'wrapping.pdf'
    _generate_plantilla_pdf([_result(description), _result('SEGUNDO PRODUCTO', code='654321')], str(path), 'Uno', 'Dos', 'Laboratorio')
    with pdfplumber.open(path) as pdf:
        words = pdf.pages[0].extract_words()
    final = next(word for word in words if word['text'] == 'FINAL')
    second_code = next(word for word in words if word['text'] == '654321')
    assert final['bottom'] < second_code['top']


@pytest.mark.parametrize('format', ['comparison', 'ipad'])
def test_unknown_numbers_are_reviewed_and_do_not_crash_pdf(tmp_path, format):
    path = tmp_path / (format + '.pdf')
    row = _result('DATOS PENDIENTES', stock1=None, smin1=None, total1=None,
                  total1_prev=None, s365_1=None, pedido1=None,
                  needs_review=True, warnings=['campo_ausente:stock'])
    if format == 'comparison':
        generate_pdf([row], str(path), 'Uno', 'Dos', 1, 1, 'Laboratorio', has_situation1=True)
    else:
        _generate_plantilla_pdf([row], str(path), 'Uno', 'Dos', 'Laboratorio', has_sit1=True)
    text = _pdf_text(path)
    assert 'Revisar' in text
    assert 'None' not in text


def test_result_renders_unknowns_and_untrusted_source_text_safely(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.tempfile, 'gettempdir', lambda: str(tmp_path))
    token = '00000000-0000-0000-0000-000000000000'
    unsafe = '<script>alert("source")</script>'
    row = _result(unsafe, stock1=None, smin1=None, total1=None, total1_prev=None, pedido1=None,
                  needs_review=True, warnings=[unsafe],
                  sources=[{'file': unsafe, 'page': 1, 'bbox': [10, 20, 200, 40],
                            'document_type': 'sales', 'description': unsafe,
                            'pharmacy_index': 1, 'pharmacy': 'Uno'}])
    row['description_source'] = row['sources'][0]
    payload = {'results': [row], 'name1': 'Uno', 'name2': 'Dos', 'lab': 'Prueba',
               'lab_slug': 'Prueba', 'count1': 1, 'count2': 1, 'has_sit1': False,
               'has_sit2': False, 'current_year': 2026}
    (tmp_path / ('comp_' + token + '.json')).write_text(json.dumps(payload))
    with client.session_transaction() as session:
        session['comp_token'] = token
    response = client.get('/resultado')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert unsafe not in html
    assert '\\u003cscript\\u003e' in html
    assert 'Revisar' in html
    assert 'const PRODUCTS' in html and '"stock1": null' in html
    pedido = client.get('/pedido')
    assert pedido.status_code == 200
    assert 'id="reviewNotice"' in pedido.get_data(as_text=True)


def test_browser_calculations_keep_returns_visible_and_block_unknown_orders():
    """Execute the shipped chart/order functions without requiring a browser."""
    import re
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which('node')
    if not node:
        pytest.skip('Node is only used for this optional browser-function regression')
    root = Path(app_module.__file__).parent
    comparison = (root / 'templates' / 'comparativa.html').read_text()
    order = (root / 'templates' / 'pedido.html').read_text()

    def function(source, name):
        return re.search(r'function ' + name + r'\([^\n]*\) \{.*?\n\}', source, re.S).group(0)

    script = '\n'.join([
        "const assert = require('node:assert/strict');",
        "const MONTH_LABELS = Array(18).fill('M');",
        function(comparison, 'numericValue'),
        function(comparison, 'renderSparkline'),
        function(comparison, 'calcPedidoSugerido'),
        function(order, 'computeKPIs'),
        """
const chart = {innerHTML: '', textContent: ''};
renderSparkline(chart, [-1,0,0,5,0,0,0,0,0,0,0,0], [], '#c0392b');
const points = chart.innerHTML.match(/<polyline points="([^"]+)"/)[1]
  .split(' ').map(point => point.split(',').map(Number));
assert(points.every(([, y]) => y >= 0 && y <= 52));
assert(points[0][1] > points[1][1] && points[1][1] > points[3][1]);
assert(chart.innerHTML.includes('<line x1="3"'));
assert.equal((chart.innerHTML.match(/<circle /g) || []).length, 2);
renderSparkline(chart, [0,0,0,5,0,0,0,0,0,0,0,0], [], '#c0392b');
assert(!chart.innerHTML.includes('<line x1="3"'));
assert(chart.innerHTML.includes('3.0,48.0'));
renderSparkline(chart, [null,0,0,5,0,0,0,0,0,0,0,0], [], '#c0392b');
assert(chart.textContent.includes('Revisar'));
assert.equal(calcPedidoSugerido({total1:4,total1_prev:6,stock1:null}, 'z', 3), null);
assert.equal(calcPedidoSugerido({total1:4,total1_prev:6,stock1:2,pedido_no_calculable1:true}, 'z', 3), null);
assert.equal(calcPedidoSugerido({total1:4,total1_prev:6,stock1:-1}, 'z', 3), 4);
assert.equal(computeKPIs(Array(12).fill(1), null, 15, 0, 2), null);
assert.equal(computeKPIs([null, ...Array(11).fill(1)], 0, 15, 0, 2), null);
""",
    ])
    result = subprocess.run([node, '-e', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('empty_pharmacy', ['Zarzuelo', 'Barris'])
def test_unreadable_sales_pdf_fails_job_before_export(client, tmp_path, monkeypatch, empty_pharmacy):
    from reportlab.pdfgen import canvas
    from tests.test_pdf_parser import _sales_pdf

    class InlineThread:
        def __init__(self, *, target, args, daemon):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    # A real PDF containing text but no product table must not become an empty
    # "successful" comparison, regardless of which pharmacy uploaded it.
    unreadable = tmp_path / 'ventas_sin_tabla.pdf'
    pdf = canvas.Canvas(str(unreadable))
    pdf.drawString(40, 800, 'Estadisticas de ventas sin tabla de productos')
    pdf.save()
    readable = _sales_pdf(tmp_path / 'ventas_legibles.pdf', [
        {'code': '123456', 'lines': ['PRODUCTO INTERAPOTHEK 5000 ML']},
    ])
    monkeypatch.setattr(app_module.threading, 'Thread', InlineThread)
    monkeypatch.setattr(app_module.tempfile, 'gettempdir', lambda: str(tmp_path))
    monkeypatch.setattr(app_module, '_get_api_key', lambda: '')
    monkeypatch.setattr(app_module, 'detect_lab', lambda path: 'Interapothek')
    monkeypatch.setattr(app_module, '_progress_store', {})

    def should_not_run(*args, **kwargs):
        pytest.fail('An unreadable sales PDF must stop before comparison/export')

    monkeypatch.setattr(app_module, 'compare_products', should_not_run)
    monkeypatch.setattr(app_module, 'generate_pdf', should_not_run)
    first = unreadable if empty_pharmacy == 'Zarzuelo' else readable
    second = unreadable if empty_pharmacy == 'Barris' else readable
    response = client.post('/comparar', data={
        'name1': 'Zarzuelo', 'name2': 'Barris',
        'pdf1': (io.BytesIO(first.read_bytes()), first.name),
        'pdf2': (io.BytesIO(second.read_bytes()), second.name),
    })
    assert response.status_code == 200
    job = response.get_json()['job']
    progress = client.get('/progress/' + job).get_json()
    assert progress['done'] is True
    assert progress['pct'] < 100
    assert ('PDF de ventas de ' + empty_pharmacy) in progress['error_msg']
    assert 'tabla de productos con texto legible' in progress['error_msg']
    assert app_module._progress_store[job]['comp_token'] is None
    assert not list(tmp_path.glob('comp_*.pdf'))
    assert not list(tmp_path.glob('comp_*.json'))
    assert client.get('/finalizar/' + job).headers['Location'] == '/'


def test_source_panel_keeps_original_and_selected_visual_description():
    import re
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which('node')
    if not node:
        pytest.skip('Node is only used for this optional source-panel regression')
    template = (Path(app_module.__file__).parent / 'templates' / 'comparativa.html').read_text()
    render = re.search(r'function renderSourceReview\([^\n]*\) \{.*?\n\}', template, re.S).group(0)
    script = '\n'.join([
        "const assert = require('node:assert/strict');",
        "const COMP_TOKEN = '00000000-0000-0000-0000-000000000000';",
        """
class Element {
  constructor() { this.children = []; this.textContent = ''; }
  appendChild(child) { this.children.push(child); }
  replaceChildren() { this.children = []; }
}
const elements = {sourceReview: new Element(), sourceReviewList: new Element(), sourceReviewSummary: new Element()};
const document = {getElementById: id => elements[id], createElement: () => new Element()};
""",
        render,
        """
const original = {file:'ventas <script>PDF</script>.pdf', page:2, bbox:[0,10,200,30],
  document_type:'sales', pharmacy_index:1, pharmacy:'Zarzuelo', description:'8'};
const corrected = {...original, description:'MASCARILLA INTERAPOTHEK 250 ML', method:'vision'};
renderSourceReview({sources:[original], description_candidates:[original,corrected,corrected],
  description_source:corrected, warnings:[]});
assert.equal(elements.sourceReview.hidden, false);
const items = elements.sourceReviewList.children;
assert.equal(items.length, 2);  // one original, one correction, no duplicate candidates
assert(items[0].children.some(child => child.textContent === '8'));
assert(items[1].children.some(child => child.textContent === corrected.description));
assert(items[1].children[0].textContent.includes('Descripción elegida'));
assert(items[1].children[0].textContent.includes('Lectura visual con IA'));
assert(!items[0].children[0].textContent.includes('Descripción elegida'));
assert.equal(items[1].children.at(-1).href, '/buscador_pdf/' + COMP_TOKEN + '/pdf1#page=2');
assert.equal(items[0].children[1].textContent, original.file); // source data is text, never HTML
renderSourceReview({description_source:corrected});
assert.equal(elements.sourceReview.hidden, false);
assert.equal(elements.sourceReviewList.children.length, 1);
""",
    ])
    result = subprocess.run([node, '-e', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
