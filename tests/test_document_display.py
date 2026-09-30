"""Document scope must survive upload, storage and the user-facing exports."""

import io
import json

import app as web
from tests.test_comparison_flow import _InlineThread
from tests.test_document_validation import _record, _sales_document
from tests.test_pdf_parser import _situation_pdf
from tests.test_public_access import _pdf_text


def test_report_periods_and_union_counts_survive_the_full_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(web.threading, 'Thread', _InlineThread)
    monkeypatch.setattr(web.tempfile, 'gettempdir', lambda: str(tmp_path))
    monkeypatch.setattr(web, '_get_api_key', lambda: '')
    monkeypatch.setattr(web, '_progress_store', {})
    monkeypatch.setitem(web.app.config, 'TESTING', True)
    sales1 = _sales_document(tmp_path / 'first.pdf', [[
        _record('123456', stock=3, current=2, previous=1)]],
        criteria=['Desde: 06/2025', 'Hasta: 05/2026'])
    sales2 = _sales_document(tmp_path / 'second.pdf', [[
        _record('123456', stock=4, current=3, previous=2)]],
        criteria=['Desde: 04/2025', 'Hasta: 04/2026', 'Mes actual: S'])
    situation = _situation_pdf(tmp_path / 'situation.pdf', [[
        {'code': '234567', 'lines': ['PRODUCTO SOLO EN SITUACION'], 'stock': 1},
        {'code': '123456', 'lines': ['PRODUCTO SINTETICO 1 ENVASE 100 ML'], 'stock': 3},
    ]])
    uploads = {key: (io.BytesIO(path.read_bytes()), filename) for key, path, filename in [
        ('pdf1', sales1, 'Ventas & uno.pdf'), ('pdf2', sales2, 'Ventas <dos>.pdf'),
        ('sit1', situation, 'Situación uno.pdf')
    ]}
    uploads.update(name1='Zarzuelo', name2='Barris')
    with web.app.test_client() as client:
        job = client.post('/comparar', data=uploads).get_json()['job']
        progress = client.get(f'/progress/{job}').get_json()
        assert progress['done'] and progress['error_msg'] is None
        client.get(f'/finalizar/{job}')
        with client.session_transaction() as session:
            token = session['comp_token']
        stored = json.loads((tmp_path / f'comp_{token}.json').read_text())
        assert stored['documents']['pdf1']['file'] == 'Ventas & uno.pdf'
        assert stored['documents']['pdf2']['period']['current_month'] is True
        assert stored['periods_differ'] is True
        assert stored['count1'] == 1  # still the number of rows in the sales PDF
        for route in ('/resultado', '/pedido'):
            text = client.get(route).get_data(as_text=True)
            assert 'id="documentWarnings"' in text
            assert 'Revisa los periodos antes de usar el pedido sugerido.' in text
            assert '06/2025 a 05/2026' in text and 'Mes actual: sí' in text
            assert 'Ventas &lt;dos&gt;.pdf' in text
            assert 'Sin movimientos desde hace 365 días' in text
        pdf_text = _pdf_text(io.BytesIO(client.get('/descargar').data))
        assert 'Zarzuelo: 2 prod. (1 en ventas)' in pdf_text
        assert 'Barris: 1 prod. (1 en ventas)' in pdf_text
        assert 'Total: 2' in pdf_text
        assert '06/2025 a 05/2026' in pdf_text
        assert 'Mes actual: sí' in pdf_text
        assert 'Los periodos o criterios de ventas son distintos' in pdf_text


def test_explicit_inactivity_dates_are_not_assumed_to_be_365_days():
    documents = {'sit2': {'file': 'Situación.pdf', 'period': {}, 'criteria': {
        'inactive_from': '01/01/2026', 'inactive_to': '30/04/2026', 'inactive_days': None}}}
    summary = web._document_summaries(documents, 'Uno', 'Dos')[0]
    assert summary['detail'] == 'Sin movimientos: 01/01/2026 a 30/04/2026'
    assert summary['label'] == 'Dos · Situación'
