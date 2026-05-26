import pytest
import json
from unittest.mock import patch, MagicMock
from app import app as flask_app


@pytest.fixture
def client():
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as c:
        with c.session_transaction() as sess:
            sess['authenticated'] = True
        yield c


def test_sin_autenticacion():
    with flask_app.test_client() as c:
        rv = c.post('/fetch_albaran', json={'numero': 'HEF-001'},
                    content_type='application/json')
    assert rv.status_code == 401


def test_sin_numero_devuelve_400(client):
    rv = client.post('/fetch_albaran', json={}, content_type='application/json')
    assert rv.status_code == 400
    data = rv.get_json()
    assert 'error' in data


def test_proveedor_desconocido_devuelve_fallback_ocr(client):
    rv = client.post('/fetch_albaran', json={'numero': 'COSMED-2024-001'},
                     content_type='application/json')
    assert rv.status_code == 200
    data = rv.get_json()
    assert data['fallback'] == 'ocr'
    assert data['numero'] == 'COSMED-2024-001'


def test_proveedor_sin_credenciales_devuelve_fallback_ocr(client):
    with patch('portal_session.get_session', return_value=None):
        rv = client.post('/fetch_albaran', json={'numero': 'HEF-001'},
                         content_type='application/json')
    data = rv.get_json()
    assert data['fallback'] == 'ocr'
    assert data.get('reason') == 'no_credentials'


def test_portal_ok_devuelve_lineas(client):
    mock_session = MagicMock()
    mock_session.fetch_albaran.return_value = {
        'lineas': [
            {'cn': '8470001', 'nombre': 'Aspirina', 'cantidad': 10,
             'precio_neto_unitario': 2.35, 'iva_porcentaje': 4,
             'recargo': False, 'sin_valor_comercial': False}
        ],
        'numero_factura': 'HEF-001',
        'fecha': '01/01/2024',
        'pdf_bytes': None,
    }
    with patch('portal_session.get_session', return_value=mock_session), \
         patch('portal_session.detect_provider', return_value='hefame'):
        rv = client.post('/fetch_albaran', json={'numero': 'HEF-001'},
                         content_type='application/json')
    assert rv.status_code == 200
    data = rv.get_json()
    assert len(data['lineas']) == 1
    assert data['lineas'][0]['cn'] == '8470001'
    assert 'proveedores' in data


def test_portal_error_devuelve_fallback_ocr(client):
    mock_session = MagicMock()
    mock_session.fetch_albaran.side_effect = Exception('timeout')
    with patch('portal_session.get_session', return_value=mock_session), \
         patch('portal_session.detect_provider', return_value='hefame'):
        rv = client.post('/fetch_albaran', json={'numero': 'HEF-001'},
                         content_type='application/json')
    data = rv.get_json()
    assert data['fallback'] == 'ocr'
    assert 'timeout' in data.get('reason', '')


def test_pdf_bytes_no_se_serializa_en_respuesta(client):
    """Si el portal devuelve pdf_bytes (bytes), la respuesta JSON no debe fallar."""
    mock_session = MagicMock()
    mock_session.fetch_albaran.return_value = {
        'lineas': [],
        'numero_factura': 'HEF-005',
        'fecha': '',
        'pdf_bytes': b'%PDF-fake-content',  # bytes que no son JSON-serializables
    }
    with patch('portal_session.get_session', return_value=mock_session), \
         patch('portal_session.detect_provider', return_value='hefame'):
        rv = client.post('/fetch_albaran', json={'numero': 'HEF-005'},
                         content_type='application/json')
    assert rv.status_code == 200
    data = rv.get_json()
    assert 'pdf_bytes' not in data
    assert data['numero_factura'] == 'HEF-005'
    assert 'proveedores' in data
