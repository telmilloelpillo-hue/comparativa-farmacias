import pytest
from unittest.mock import MagicMock, patch
from portal_session import detect_provider, PortalConfig, PortalSession


def test_detect_hefame_uppercase():
    assert detect_provider("HEF-2024-001234") == "hefame"


def test_detect_hefame_lowercase():
    assert detect_provider("hef001234") == "hefame"


def test_detect_bida_uppercase():
    assert detect_provider("BID-001234") == "bida"


def test_detect_bida_lowercase():
    assert detect_provider("bid12345") == "bida"


def test_detect_unknown_lab():
    assert detect_provider("COSMED-2024-001") == "unknown"


def test_detect_empty_string():
    assert detect_provider("") == "unknown"


def test_detect_pure_digits_unknown():
    # Dígitos puros sin prefijo reconocido → unknown hasta inspección real
    assert detect_provider("123456789") == "unknown"


HTML_DOS_LINEAS = """
<html><body>
<table id="productos">
  <tr class="linea">
    <td>8470001234567</td>
    <td>Aspirina 500mg 20 comp</td>
    <td>10</td>
    <td>2,35</td>
    <td>4%</td>
  </tr>
  <tr class="linea">
    <td>8470007654321</td>
    <td>Ibuprofeno 600mg 40 comp</td>
    <td>5</td>
    <td>3,80</td>
    <td>21%</td>
  </tr>
</table>
</body></html>
"""


@pytest.fixture
def config():
    return PortalConfig(
        login_url='http://portal.test/login',
        search_url='http://portal.test/albaran',
        user_field='usuario',
        pass_field='clave',
        albaran_param='num',
        row_selector='table#productos tr.linea',
        cols={'cn': 0, 'desc': 1, 'qty': 2, 'price': 3, 'iva': 4},
        pdf_selector='',
    )


def _make_response(text, url='http://portal.test/albaran', status=200):
    r = MagicMock()
    r.status_code = status
    r.url = url
    r.text = text
    r.ok = (status == 200)
    r.raise_for_status = MagicMock()
    return r


def test_parse_html_extracts_two_lines(config):
    session = PortalSession(config, 'user', 'pass')
    session._session = MagicMock()
    session._session.get.return_value = _make_response(HTML_DOS_LINEAS)

    result = session.fetch_albaran('HEF-001')

    assert len(result['lineas']) == 2
    l0 = result['lineas'][0]
    assert l0['cn'] == '8470001234567'
    assert l0['nombre'] == 'Aspirina 500mg 20 comp'
    assert l0['cantidad'] == 10
    assert l0['precio_neto_unitario'] == 2.35
    assert l0['iva_porcentaje'] == 4

    l1 = result['lineas'][1]
    assert l1['cantidad'] == 5
    assert l1['precio_neto_unitario'] == 3.80
    assert l1['iva_porcentaje'] == 21


def test_numero_factura_en_resultado(config):
    session = PortalSession(config, 'user', 'pass')
    session._session = MagicMock()
    session._session.get.return_value = _make_response(HTML_DOS_LINEAS)

    result = session.fetch_albaran('HEF-2024-999')
    assert result['numero_factura'] == 'HEF-2024-999'


def test_relogin_cuando_redirige_a_login(config):
    """Si el GET retorna URL de login → re-login automático y reintento."""
    session = PortalSession(config, 'user', 'pass')

    resp_expired = _make_response('', url='http://portal.test/login')
    resp_ok = _make_response(HTML_DOS_LINEAS)

    call_n = {'n': 0}
    def fake_get(url, **kw):
        call_n['n'] += 1
        return resp_expired if call_n['n'] == 1 else resp_ok

    session._session = MagicMock()
    session._session.get.side_effect = fake_get

    with patch.object(session, '_login', side_effect=lambda: setattr(session, '_session', MagicMock(get=MagicMock(return_value=resp_ok)))) as mock_login:
        result = session.fetch_albaran('HEF-001')
        assert mock_login.call_count == 1

    assert len(result['lineas']) == 2


def test_skip_filas_sin_suficientes_celdas(config):
    html = """<html><body><table id="productos">
      <tr class="linea"><td>solo-dos</td><td>columnas</td></tr>
      <tr class="linea"><td>8470001</td><td>Producto</td><td>3</td><td>1,00</td><td>21%</td></tr>
    </table></body></html>"""
    session = PortalSession(config, 'user', 'pass')
    session._session = MagicMock()
    session._session.get.return_value = _make_response(html)

    result = session.fetch_albaran('HEF-002')
    assert len(result['lineas']) == 1  # Solo la fila con 5 celdas


def test_to_float_spanish_thousands_separator(config):
    """Precio como '1.234,56' (separador de miles español) debe parsearse correctamente."""
    html = """<html><body><table id="productos">
      <tr class="linea"><td>1234567</td><td>Producto</td><td>2</td><td>1.234,56</td><td>21%</td></tr>
    </table></body></html>"""
    session = PortalSession(config, 'user', 'pass')
    session._session = MagicMock()
    session._session.get.return_value = _make_response(html)

    result = session.fetch_albaran('HEF-003')
    assert result['lineas'][0]['precio_neto_unitario'] == 1234.56


def test_parse_descarga_pdf_si_selector_presente():
    """Si hay pdf_selector y el enlace devuelve content-type PDF → pdf_bytes en resultado."""
    config_pdf = PortalConfig(
        login_url='http://portal.test/login',
        search_url='http://portal.test/albaran',
        user_field='usuario',
        pass_field='clave',
        albaran_param='num',
        row_selector='table tr',
        cols={'cn': 0, 'desc': 1, 'qty': 2, 'price': 3, 'iva': 4},
        pdf_selector='a.pdf-download',
    )
    html_with_link = """<html><body>
      <a class="pdf-download" href="/descargar/albaran.pdf">Descargar PDF</a>
    </body></html>"""

    pdf_bytes = b'%PDF-fake'
    pdf_response = MagicMock()
    pdf_response.ok = True
    pdf_response.content = pdf_bytes
    pdf_response.headers = {'content-type': 'application/pdf'}

    main_response = _make_response(html_with_link, url='http://portal.test/albaran?num=HEF-004')

    mock_s = MagicMock()
    mock_s.get.side_effect = [main_response, pdf_response]

    session = PortalSession(config_pdf, 'user', 'pass')
    session._session = mock_s

    result = session.fetch_albaran('HEF-004')
    assert result['pdf_bytes'] == pdf_bytes
    assert result['lineas'] == []
    assert result['numero_factura'] == 'HEF-004'
