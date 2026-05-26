# Scanner de Códigos de Barras en Albaranes — Plan de Implementación

> **Para workers agénticos:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Añadir escaneo de código de barras 1D en albaranes para obtener datos directamente de los portales Hefame/BIDA, eliminando errores de OCR en esos proveedores y manteniendo OCR como fallback para labs externos.

**Architecture:** Frontend ZXing-js (CDN WebAssembly) en nueva pestaña de `facturas.html` para escaneo por cámara o foto. Backend `portal_session.py` con `PortalSession` (requests + cookie cache) que obtiene datos del portal y los devuelve en la misma estructura JSON que `/leer_factura`. Fallback automático a OCR existente para labs externos o si el portal falla. Nueva ruta `POST /fetch_albaran` en `app.py`.

**Tech Stack:** Python `requests` + `beautifulsoup4` · ZXing-js 0.1.1 (CDN, sin build step) · Flask · pytest + unittest.mock

**Spec completo:** `docs/superpowers/specs/2026-05-26-barcode-albaran-scanner-design.md`

---

## Mapa de archivos

| Archivo | Acción | Responsabilidad |
|---|---|---|
| `portal_session.py` | Crear | detect_provider, PortalConfig, PortalSession, get_session |
| `static/js/barcode_scanner.js` | Crear | Wrapper ZXing-js: cámara en tiempo real + decode desde foto |
| `tests/test_portal_session.py` | Crear | Tests unitarios con mocks para portal_session.py |
| `tests/test_fetch_albaran.py` | Crear | Tests de la ruta Flask /fetch_albaran |
| `app.py` | Modificar | Añadir ruta POST /fetch_albaran (~30 líneas) |
| `templates/facturas.html` | Modificar | Añadir tabs Escanear/Subir, visor de cámara, indicador proveedor |
| `requirements.txt` | Modificar | Añadir beautifulsoup4 |
| `.env` | Documentar | HEFAME_USER, HEFAME_PASS, BIDA_USER, BIDA_PASS (no en git) |

---

## Task 1: Dependencias

**Files:**
- Modify: `requirements.txt`

- [ ] **Añadir beautifulsoup4 a requirements.txt**

Añadir al final del archivo:
```
beautifulsoup4
```

- [ ] **Verificar instalación**

```bash
pip install beautifulsoup4
python -c "from bs4 import BeautifulSoup; print('OK')"
```
Expected: `OK`

- [ ] **Commit**

```bash
git add requirements.txt
git commit -m "feat: add beautifulsoup4 for portal HTML parsing"
```

---

## Task 2: `portal_session.py` — detect_provider [TDD]

**Files:**
- Create: `tests/test_portal_session.py`
- Create: `portal_session.py`

- [ ] **Crear directorio tests e inicializar**

```bash
mkdir -p tests
touch tests/__init__.py
```

- [ ] **Escribir tests que fallan**

Crear `tests/test_portal_session.py`:

```python
import pytest
from portal_session import detect_provider


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
```

- [ ] **Ejecutar para verificar que fallan**

```bash
cd /Users/telmobarris/Desktop/comparativa-farmacias
python -m pytest tests/test_portal_session.py -v
```
Expected: `ModuleNotFoundError: No module named 'portal_session'`

- [ ] **Implementar detect_provider**

Crear `portal_session.py`:

```python
"""
portal_session.py — Gestión de sesiones en portales de proveedores (Hefame, BIDA).

Patrón de uso:
    from portal_session import detect_provider, get_session
    provider = detect_provider(numero_albaran)   # 'hefame' | 'bida' | 'unknown'
    session = get_session(provider)              # PortalSession o None
    result = session.fetch_albaran(numero)       # dict con 'lineas', 'numero_factura', etc.
"""

from __future__ import annotations

import os
import re
import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass, field
from typing import Optional


# ── Detección de proveedor ────────────────────────────────────────────────────
# Patrones ajustados tras inspección de albaranes reales (Task 4 y 5).
# El orden importa: el primer match gana.
_PROVIDER_PATTERNS: list[tuple[str, str]] = [
    (r'(?i)^hef', 'hefame'),
    (r'(?i)^bid', 'bida'),
]


def detect_provider(numero: str) -> str:
    """Infiere el proveedor ('hefame'|'bida'|'unknown') por el prefijo del número."""
    for pattern, slug in _PROVIDER_PATTERNS:
        if re.match(pattern, numero):
            return slug
    return 'unknown'
```

- [ ] **Ejecutar tests — deben pasar**

```bash
python -m pytest tests/test_portal_session.py::test_detect_hefame_uppercase \
  tests/test_portal_session.py::test_detect_hefame_lowercase \
  tests/test_portal_session.py::test_detect_bida_uppercase \
  tests/test_portal_session.py::test_detect_bida_lowercase \
  tests/test_portal_session.py::test_detect_unknown_lab \
  tests/test_portal_session.py::test_detect_empty_string \
  tests/test_portal_session.py::test_detect_pure_digits_unknown -v
```
Expected: 7 passed

- [ ] **Commit**

```bash
git add portal_session.py tests/test_portal_session.py tests/__init__.py
git commit -m "feat: detect_provider para inferir proveedor por prefijo de albarán"
```

---

## Task 3: `portal_session.py` — PortalConfig + PortalSession [TDD]

**Files:**
- Modify: `tests/test_portal_session.py`
- Modify: `portal_session.py`

- [ ] **Añadir tests de PortalSession al final de `tests/test_portal_session.py`**

```python
from unittest.mock import MagicMock, patch
from portal_session import PortalConfig, PortalSession


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

    with patch.object(session, '_login', side_effect=lambda: setattr(session, '_session', MagicMock(get=MagicMock(return_value=resp_ok)))):
        result = session.fetch_albaran('HEF-001')

    assert session._login.call_count == 1
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
```

- [ ] **Ejecutar para verificar que fallan**

```bash
python -m pytest tests/test_portal_session.py -k "parse_html or numero_factura or relogin or skip_filas" -v
```
Expected: `ImportError` o `AttributeError` — PortalConfig/PortalSession no existen aún

- [ ] **Añadir PortalConfig y PortalSession a `portal_session.py`**

Añadir después de `detect_provider` (antes del final del archivo):

```python
# ── Configuración del portal ──────────────────────────────────────────────────

@dataclass
class PortalConfig:
    login_url: str        # URL del formulario de login
    search_url: str       # URL de búsqueda de albarán
    user_field: str       # name del input de usuario en el form de login
    pass_field: str       # name del input de contraseña en el form de login
    albaran_param: str    # nombre del query param para el número de albarán
    row_selector: str     # CSS selector para filas de producto en el resultado
    cols: dict            # {'cn': idx, 'desc': idx, 'qty': idx, 'price': idx, 'iva': idx}
    pdf_selector: str = '' # CSS selector del enlace PDF; '' = sin descarga directa


# ── Sesión de portal ──────────────────────────────────────────────────────────

class PortalSession:
    def __init__(self, config: PortalConfig, username: str, password: str):
        self.config = config
        self.username = username
        self.password = password
        self._session: Optional[requests.Session] = None

    def _login(self) -> None:
        s = requests.Session()
        s.headers.update({'User-Agent': 'Mozilla/5.0 (compatible; FarmaciaApp/1.0)'})
        resp = s.post(
            self.config.login_url,
            data={self.config.user_field: self.username, self.config.pass_field: self.password},
            timeout=15,
            allow_redirects=True,
        )
        resp.raise_for_status()
        self._session = s

    def _get_albaran_page(self, numero: str) -> requests.Response:
        resp = self._session.get(
            self.config.search_url,
            params={self.config.albaran_param: numero},
            timeout=15,
        )
        # Sesión expirada → redirect a login o código 401/403
        if resp.status_code in (401, 403) or 'login' in resp.url.lower():
            self._session = None
            self._login()
            resp = self._session.get(
                self.config.search_url,
                params={self.config.albaran_param: numero},
                timeout=15,
            )
        resp.raise_for_status()
        return resp

    def fetch_albaran(self, numero: str) -> dict:
        """Devuelve dict con 'lineas', 'numero_factura', 'pdf_bytes' (o None)."""
        if self._session is None:
            self._login()
        resp = self._get_albaran_page(numero)
        return self._parse(resp, numero)

    def _parse(self, resp: requests.Response, numero: str) -> dict:
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Intento 1: descarga PDF directa
        if self.config.pdf_selector:
            link = soup.select_one(self.config.pdf_selector)
            if link and link.get('href'):
                pdf_resp = self._session.get(link['href'], timeout=20)
                ct = pdf_resp.headers.get('content-type', '')
                if pdf_resp.ok and 'pdf' in ct:
                    return {'pdf_bytes': pdf_resp.content, 'lineas': [],
                            'numero_factura': numero, 'fecha': ''}

        # Intento 2: parsear tabla HTML
        cols = self.config.cols
        needed = max(cols.values()) + 1
        lineas = []
        for row in soup.select(self.config.row_selector):
            cells = [td.get_text(strip=True) for td in row.select('td')]
            if len(cells) < needed:
                continue
            lineas.append({
                'cn':                   cells[cols['cn']],
                'nombre':               cells[cols['desc']],
                'cantidad':             _to_int(cells[cols['qty']]),
                'precio_neto_unitario': _to_float(cells[cols['price']]),
                'iva_porcentaje':       _to_iva(cells[cols['iva']]),
                'recargo':              False,
                'sin_valor_comercial':  False,
            })
        return {'lineas': lineas, 'numero_factura': numero, 'fecha': '', 'pdf_bytes': None}


# ── Helpers de parseo ─────────────────────────────────────────────────────────

def _to_int(s: str) -> int:
    try:
        return int(re.sub(r'[^\d]', '', s))
    except ValueError:
        return 0


def _to_float(s: str) -> float:
    try:
        return float(re.sub(r'[^\d,.]', '', s).replace(',', '.'))
    except ValueError:
        return 0.0


def _to_iva(s: str) -> int:
    m = re.search(r'\d+', s)
    return int(m.group()) if m else 21
```

- [ ] **Ejecutar tests — deben pasar**

```bash
python -m pytest tests/test_portal_session.py -v
```
Expected: todos los tests del archivo pasan

- [ ] **Commit**

```bash
git add portal_session.py tests/test_portal_session.py
git commit -m "feat: PortalConfig y PortalSession con auto-relogin y parsing HTML"
```

---

## Task 4: Inspección manual del portal Hefame

> **Tarea humana** — requiere acceso al portal con las credenciales reales.
> Output: valores concretos para `HEFAME_CONFIG` en Task 6.

**Files:**
- No modifica código — produce los valores para Task 6.

- [ ] **Abrir el portal de Hefame en el navegador**

Ir a la URL de login del portal de clientes de Hefame (suele ser `portal.hefame.es` o `clientes.hefame.es`). Si no se recuerda la URL, buscar en el email de bienvenida de Hefame o preguntar al representante.

- [ ] **Abrir DevTools (F12) → pestaña Network → marcar "Preserve log"**

- [ ] **Hacer login y observar la petición POST**

Al pulsar "Entrar", en Network aparece la petición POST al formulario. Hacer clic en ella y anotar:
- **URL del login** (campo "Request URL"): `_____________`
- **Nombre del campo usuario** (en payload): `_____________`
- **Nombre del campo contraseña** (en payload): `_____________`

- [ ] **Buscar un albarán real por número y observar la petición**

Después de login, usar el buscador de albaranes del portal. En Network, al hacer la búsqueda, anotar:
- **URL de búsqueda** (puede ser GET o POST): `_____________`
- **Nombre del parámetro para el número de albarán**: `_____________`
- **¿La URL de búsqueda cambia con el número?** (ej. `.../albaran/HEF-001` vs `.../albaran?num=HEF-001`): `_____________`

- [ ] **Inspeccionar el HTML de la tabla de resultados (pestaña Elements)**

En la tabla de productos del albarán, botón derecho → Inspeccionar en la fila de un producto y anotar:
- **Selector CSS de la tabla o filas de producto** (ej. `table.albaran-lines tr.item`): `_____________`
- **Índice de columna para CN** (0=primera): `_____________`
- **Índice para descripción**: `_____________`
- **Índice para cantidad**: `_____________`
- **Índice para precio neto unitario**: `_____________`
- **Índice para IVA%**: `_____________`

- [ ] **Buscar si hay enlace de descarga PDF**

Si hay botón "Descargar PDF" o similar, inspeccionar su `<a href="...">` y anotar:
- **CSS selector del enlace PDF** (ej. `a.btn-pdf`, `a[href*=".pdf"]`): `_____________`
- Si no hay PDF directo: dejar vacío (`''`)

- [ ] **Anotar el formato del número de albarán en el código de barras**

Escanear el código de barras de un albarán físico de Hefame con la app de cámara del móvil (cualquier app de lectura QR/barcode). El número que aparece tiene un prefijo:
- **Prefijo o patrón del número** (ej. `HEF`, `8`, `94`): `_____________`
- **Longitud aproximada del número total**: `_____________`

> Estos valores se usarán en Task 6 para `HEFAME_CONFIG` y para actualizar `_PROVIDER_PATTERNS`.

---

## Task 5: Inspección manual del portal BIDA

> **Tarea humana** — mismo proceso que Task 4 pero para BIDA.

**Files:**
- No modifica código — produce los valores para Task 6.

- [ ] **Repetir el proceso de Task 4 para el portal de BIDA/Bidafarma**

Anotar los mismos valores:
- Login URL: `_____________`
- User field: `_____________`
- Pass field: `_____________`
- Search URL: `_____________`
- Albaran param: `_____________`
- Row selector: `_____________`
- cols (cn/desc/qty/price/iva): `_____________`
- PDF selector: `_____________`
- Prefijo número de albarán BIDA: `_____________`

> Si no se tiene acceso a BIDA, saltar esta tarea y configurar solo Hefame. La app funciona con cualquier subconjunto de proveedores.

---

## Task 6: Configs + singletons en `portal_session.py`

**Files:**
- Modify: `portal_session.py` (añadir al final)
- Modify: `portal_session.py` (actualizar `_PROVIDER_PATTERNS` con los prefijos reales)

> Usa los valores anotados en Task 4 y Task 5.

- [ ] **Actualizar `_PROVIDER_PATTERNS` con los prefijos reales**

Reemplazar la sección `_PROVIDER_PATTERNS` con los prefijos reales observados en Task 4/5. Ejemplo si Hefame usa prefijo `94` y BIDA usa `84`:

```python
_PROVIDER_PATTERNS: list[tuple[str, str]] = [
    (r'(?i)^hef', 'hefame'),   # Ajustar si el prefijo real es diferente
    (r'(?i)^bid', 'bida'),     # Ajustar si el prefijo real es diferente
    # Añadir más patrones si se descubren durante la inspección:
    # (r'^94\d{8}$', 'hefame'),
    # (r'^84\d{8}$', 'bida'),
]
```

- [ ] **Añadir HEFAME_CONFIG, BIDA_CONFIG y get_session() al final de `portal_session.py`**

```python
# ── Configuraciones de portal (rellenar con valores de Task 4 y Task 5) ───────

HEFAME_CONFIG = PortalConfig(
    login_url    = 'REEMPLAZAR_CON_URL_DE_LOGIN_HEFAME',
    search_url   = 'REEMPLAZAR_CON_URL_BUSQUEDA_ALBARAN',
    user_field   = 'REEMPLAZAR_CON_NOMBRE_CAMPO_USUARIO',
    pass_field   = 'REEMPLAZAR_CON_NOMBRE_CAMPO_CONTRASEÑA',
    albaran_param= 'REEMPLAZAR_CON_NOMBRE_PARAM_ALBARAN',
    row_selector = 'REEMPLAZAR_CON_CSS_SELECTOR_FILAS',
    cols         = {'cn': 0, 'desc': 1, 'qty': 2, 'price': 3, 'iva': 4},  # ajustar índices
    pdf_selector = '',   # '' si no hay descarga directa
)

BIDA_CONFIG = PortalConfig(
    login_url    = 'REEMPLAZAR_CON_URL_DE_LOGIN_BIDA',
    search_url   = 'REEMPLAZAR_CON_URL_BUSQUEDA_ALBARAN',
    user_field   = 'REEMPLAZAR_CON_NOMBRE_CAMPO_USUARIO',
    pass_field   = 'REEMPLAZAR_CON_NOMBRE_CAMPO_CONTRASEÑA',
    albaran_param= 'REEMPLAZAR_CON_NOMBRE_PARAM_ALBARAN',
    row_selector = 'REEMPLAZAR_CON_CSS_SELECTOR_FILAS',
    cols         = {'cn': 0, 'desc': 1, 'qty': 2, 'price': 3, 'iva': 4},
    pdf_selector = '',
)

_REGISTRY: dict[str, tuple[PortalConfig, str, str]] = {
    'hefame': (HEFAME_CONFIG, 'HEFAME_USER', 'HEFAME_PASS'),
    'bida':   (BIDA_CONFIG,   'BIDA_USER',   'BIDA_PASS'),
}

_sessions: dict[str, PortalSession] = {}


def get_session(provider: str) -> Optional[PortalSession]:
    """Devuelve PortalSession singleton para el proveedor, o None si sin credenciales."""
    if provider in _sessions:
        return _sessions[provider]
    entry = _REGISTRY.get(provider)
    if entry is None:
        return None
    config, user_env, pass_env = entry
    user   = os.environ.get(user_env, '').strip()
    passwd = os.environ.get(pass_env, '').strip()
    if not user or not passwd:
        return None
    session = PortalSession(config, user, passwd)
    _sessions[provider] = session
    return session
```

- [ ] **Añadir variables al `.env`** (no al git)

Abrir `.env` y añadir:
```
HEFAME_USER=tu_usuario_hefame
HEFAME_PASS=tu_contraseña_hefame
BIDA_USER=tu_usuario_bida
BIDA_PASS=tu_contraseña_bida
```

- [ ] **Verificar que get_session funciona con env vars**

```bash
HEFAME_USER=test HEFAME_PASS=test python -c "
from portal_session import get_session
s = get_session('hefame')
print('hefame session:', s is not None)
s2 = get_session('unknown')
print('unknown session:', s2 is None)
"
```
Expected:
```
hefame session: True
unknown session: True
```

- [ ] **Commit**

```bash
git add portal_session.py
git commit -m "feat: HEFAME_CONFIG, BIDA_CONFIG y get_session singleton"
```

---

## Task 7: Ruta `/fetch_albaran` en `app.py` [TDD]

**Files:**
- Create: `tests/test_fetch_albaran.py`
- Modify: `app.py`

- [ ] **Escribir tests que fallan**

Crear `tests/test_fetch_albaran.py`:

```python
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
    assert 'proveedores' in data  # _CONFIG_PROVEEDORES incluido


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
```

- [ ] **Ejecutar para verificar que fallan**

```bash
python -m pytest tests/test_fetch_albaran.py -v
```
Expected: `404 NOT FOUND` en los tests de ruta (la ruta aún no existe)

- [ ] **Añadir la ruta a `app.py`**

Localizar en `app.py` la zona donde están las otras rutas POST (cerca de `/leer_factura`) y añadir justo antes de `if __name__ == '__main__':` o al final del bloque de rutas:

```python
@app.route('/fetch_albaran', methods=['POST'])
def fetch_albaran():
    if not session.get('authenticated'):
        return jsonify({'error': 'no auth'}), 401

    data = request.get_json(silent=True) or {}
    numero = (data.get('numero') or '').strip()
    if not numero:
        return jsonify({'error': 'Número de albarán requerido'}), 400

    from portal_session import detect_provider, get_session

    provider = detect_provider(numero)
    if provider == 'unknown':
        return jsonify({'fallback': 'ocr', 'numero': numero})

    portal = get_session(provider)
    if portal is None:
        return jsonify({'fallback': 'ocr', 'numero': numero, 'reason': 'no_credentials'})

    try:
        result = portal.fetch_albaran(numero)
        result['proveedores'] = _CONFIG_PROVEEDORES
        return jsonify(result)
    except Exception as exc:
        app.logger.warning('Portal %s error para %s: %s', provider, numero, exc)
        return jsonify({'fallback': 'ocr', 'numero': numero, 'reason': str(exc)})
```

- [ ] **Ejecutar tests — deben pasar**

```bash
python -m pytest tests/test_fetch_albaran.py -v
```
Expected: 6 passed

- [ ] **Ejecutar todos los tests para detectar regresiones**

```bash
python -m pytest tests/ -v
```
Expected: todos los tests anteriores siguen pasando

- [ ] **Commit**

```bash
git add app.py tests/test_fetch_albaran.py
git commit -m "feat: ruta POST /fetch_albaran con fallback OCR para labs externos"
```

---

## Task 8: `static/js/barcode_scanner.js`

**Files:**
- Create: `static/js/barcode_scanner.js`

> No hay tests unitarios para JS en este proyecto. La verificación es manual en Task 10.

- [ ] **Crear `static/js/barcode_scanner.js`**

```javascript
/**
 * barcode_scanner.js — Wrapper sobre @zxing/browser para escaneo de códigos de barras.
 *
 * Requiere en el HTML (antes de este script):
 *   <script src="https://unpkg.com/@zxing/browser@0.1.1/umd/index.min.js"></script>
 *
 * API:
 *   BarcodeScanner.startCamera(videoEl, onDetected)  → Promise<void>
 *   BarcodeScanner.stopCamera()
 *   BarcodeScanner.decodeFromFile(file)              → Promise<string>
 */

const BarcodeScanner = (() => {
    const codeReader = new ZXingBrowser.BrowserMultiFormatReader();
    let activeControls = null;

    /**
     * Inicia el stream de cámara y llama onDetected(texto) al leer un código.
     * La cámara se para automáticamente tras el primer resultado.
     */
    async function startCamera(videoEl, onDetected) {
        if (activeControls) {
            activeControls.stop();
            activeControls = null;
        }
        try {
            activeControls = await codeReader.decodeFromVideoDevice(
                null,      // null = cámara trasera en móvil, predeterminada en PC
                videoEl,
                (result, err) => {
                    if (result) {
                        activeControls.stop();
                        activeControls = null;
                        _beep();
                        onDetected(result.getText());
                    }
                }
            );
        } catch (err) {
            throw new Error('No se pudo acceder a la cámara: ' + err.message);
        }
    }

    /** Para el stream de cámara si está activo. */
    function stopCamera() {
        if (activeControls) {
            activeControls.stop();
            activeControls = null;
        }
    }

    /**
     * Decodifica el primer código de barras encontrado en un File (foto subida).
     * Lanza Error si no hay código de barras.
     */
    async function decodeFromFile(file) {
        const url = URL.createObjectURL(file);
        try {
            const img = document.createElement('img');
            img.src = url;
            await new Promise((resolve, reject) => {
                img.onload = resolve;
                img.onerror = () => reject(new Error('No se pudo cargar la imagen'));
            });
            const result = await codeReader.decodeFromImageElement(img);
            return result.getText();
        } catch (err) {
            if (err.name === 'NotFoundException') {
                throw new Error('No se detectó ningún código de barras en la imagen');
            }
            throw err;
        } finally {
            URL.revokeObjectURL(url);
        }
    }

    /** Beep corto al escanear con éxito (contexto de audio del navegador). */
    function _beep() {
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.frequency.value = 880;
            gain.gain.setValueAtTime(0.3, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.15);
            osc.start(ctx.currentTime);
            osc.stop(ctx.currentTime + 0.15);
        } catch (_) {}  // Silencioso si el navegador bloquea AudioContext
    }

    return { startCamera, stopCamera, decodeFromFile };
})();
```

- [ ] **Verificar que el archivo existe**

```bash
ls -la /Users/telmobarris/Desktop/comparativa-farmacias/static/js/barcode_scanner.js
```
Expected: archivo listado con tamaño > 0

- [ ] **Commit**

```bash
git add static/js/barcode_scanner.js
git commit -m "feat: barcode_scanner.js con ZXing-js para cámara y foto"
```

---

## Task 9: `templates/facturas.html` — Tabs + Scanner UI

**Files:**
- Modify: `templates/facturas.html`

> Leer el archivo completo antes de editar para entender la estructura actual.

- [ ] **Leer facturas.html para localizar los puntos de inserción**

```bash
grep -n "uploadSection\|fileInput\|drag-drop\|proveedor\|redondeo\|<head\|</head\|<script" \
  templates/facturas.html | head -40
```

Anotar:
- Línea donde está `<head>` para insertar el `<script>` de ZXing-js
- Línea donde empieza la sección de upload (`#uploadSection` o similar)
- Línea donde está el `<input type="file" id="fileInput">`

- [ ] **Añadir ZXing-js CDN y barcode_scanner.js en `<head>`**

Localizar el cierre `</head>` en `facturas.html` y añadir antes:

```html
    <!-- Barcode scanner: ZXing-js (WebAssembly) -->
    <script src="https://unpkg.com/@zxing/browser@0.1.1/umd/index.min.js"></script>
    <script src="{{ url_for('static', filename='js/barcode_scanner.js') }}" defer></script>
```

- [ ] **Añadir estilos CSS del scanner en `<head>` (antes de `</head>`)**

```html
    <style>
      /* Tabs escanear/subir */
      .scan-tabs { display: flex; border-bottom: 2px solid #e0e0e0; margin-bottom: 16px; }
      .scan-tab  { padding: 8px 18px; cursor: pointer; border-radius: 4px 4px 0 0;
                   font-size: 13px; color: #666; border: none; background: none; }
      .scan-tab.active { background: #4a90d9; color: #fff; font-weight: 600; }

      /* Visor de cámara */
      #scannerPanel { display: none; }
      #scannerPanel.visible { display: block; }
      #cameraView { width: 100%; max-height: 220px; border-radius: 8px;
                    background: #111; object-fit: cover; }
      .camera-guide { text-align: center; font-size: 11px; color: #888; margin: 4px 0 8px; }

      /* Indicador de proveedor */
      #providerBadge { display: none; padding: 6px 12px; border-radius: 4px;
                       font-size: 12px; margin-top: 8px; }
      #providerBadge.hefame { background: #e8f4fd; border: 1px solid #4a90d9; color: #1a5fa8; display: block; }
      #providerBadge.bida   { background: #e8fde8; border: 1px solid #2ecc71; color: #1a7a3a; display: block; }
      #providerBadge.unknown{ background: #fff8e6; border: 1px solid #f0c040; color: #856404; display: block; }
      #providerBadge.error  { background: #fdeaea; border: 1px solid #e74c3c; color: #a61c00; display: block; }
    </style>
```

- [ ] **Envolver la sección de upload existente en tabs**

Localizar el div principal de la sección de upload (el que contiene el `<input type="file" id="fileInput">`). Envolverlo añadiendo los tabs ANTES del upload existente, dentro de la misma columna izquierda:

Estructura a añadir (insertar justo antes del bloque de drag-drop/file input existente):

```html
        <!-- Tabs: Escanear / Subir -->
        <div class="scan-tabs">
          <button class="scan-tab active" id="tabScan" onclick="switchTab('scan')">
            📷 Escanear albarán
          </button>
          <button class="scan-tab" id="tabUpload" onclick="switchTab('upload')">
            📄 Subir factura
          </button>
        </div>

        <!-- Panel: Escanear -->
        <div id="scannerPanel" class="visible">
          <video id="cameraView" autoplay muted playsinline></video>
          <p class="camera-guide">Apunta al código de barras del albarán</p>

          <div id="providerBadge"></div>

          <div style="display:flex; gap:8px; margin-top:10px; align-items:center">
            <input type="text" id="manualBarcode" placeholder="Nº albarán manual..."
                   style="flex:1; padding:7px 10px; border:1px solid #ccc; border-radius:5px; font-size:13px">
            <button id="btnFetchManual"
                    style="padding:7px 14px; background:#4a90d9; color:#fff; border:none;
                           border-radius:5px; cursor:pointer; font-size:13px">
              Buscar
            </button>
          </div>
          <p style="font-size:11px;color:#aaa;margin:6px 0 0;">
            Si la cámara no lee el código, introdúcelo manualmente.
          </p>
        </div>

        <!-- Panel: Subir (contiene el upload existente) -->
        <div id="uploadPanel">
          <!-- AQUÍ VA EL CONTENIDO ACTUAL DEL UPLOAD (drag-drop, fileInput, etc.) SIN CAMBIOS -->
```

Y añadir la etiqueta de cierre `</div>` del `#uploadPanel` al final del bloque de upload original.

- [ ] **Añadir el JS del scanner al final de `facturas.html`, antes de `</body>`**

```html
<script>
// ── Tab switcher ──────────────────────────────────────────────────────────────
function switchTab(tab) {
  document.getElementById('tabScan').classList.toggle('active', tab === 'scan');
  document.getElementById('tabUpload').classList.toggle('active', tab === 'upload');
  document.getElementById('scannerPanel').classList.toggle('visible', tab === 'scan');
  document.getElementById('uploadPanel').style.display = tab === 'upload' ? '' : 'none';
  if (tab === 'scan') {
    _startScanner();
  } else {
    BarcodeScanner.stopCamera();
  }
}

// ── Cámara ────────────────────────────────────────────────────────────────────
function _startScanner() {
  const video = document.getElementById('cameraView');
  BarcodeScanner.startCamera(video, _onBarcodeDetected).catch(err => {
    _setBadge('error', '⚠ ' + err.message);
  });
}

// Al detectar código desde cámara
function _onBarcodeDetected(numero) {
  document.getElementById('manualBarcode').value = numero;
  _fetchAlbaran(numero);
}

// ── Fetch albarán ─────────────────────────────────────────────────────────────
document.getElementById('btnFetchManual').addEventListener('click', () => {
  const numero = document.getElementById('manualBarcode').value.trim();
  if (numero) _fetchAlbaran(numero);
});

async function _fetchAlbaran(numero) {
  _setBadge('', '⏳ Buscando ' + numero + '...');

  try {
    const resp = await fetch('/fetch_albaran', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ numero }),
    });
    const data = await resp.json();

    if (data.error) {
      _setBadge('error', '✗ ' + data.error);
      return;
    }

    if (data.fallback === 'ocr') {
      _setBadge('unknown', '⚠ Lab externo — sube la foto para procesar con OCR');
      return;
    }

    // Datos obtenidos del portal → rellenar tabla (usa la función existente de facturas.html)
    _setBadge(data.proveedor || 'hefame', '✓ Albarán ' + numero + ' cargado desde portal');
    // Llamar a la función existente que muestra resultados en la tabla
    if (typeof mostrarResultados === 'function') {
      mostrarResultados(data);
    } else if (typeof renderTable === 'function') {
      renderTable(data);
    } else {
      // Fallback: disparar el mismo evento que usa el upload existente
      document.dispatchEvent(new CustomEvent('albaran-loaded', { detail: data }));
    }

  } catch (err) {
    _setBadge('error', '✗ Error de red: ' + err.message);
  }
}

// ── Badge de proveedor ────────────────────────────────────────────────────────
function _setBadge(cls, text) {
  const badge = document.getElementById('providerBadge');
  badge.className = '';
  badge.textContent = text;
  if (cls) badge.classList.add(cls);
}

// Arrancar cámara al cargar si el tab de escaneo está activo
window.addEventListener('DOMContentLoaded', () => {
  if (document.getElementById('tabScan').classList.contains('active')) {
    _startScanner();
  }
});

// También intentar decodificar barcode cuando se sube foto en tab Upload
const origFileInput = document.getElementById('fileInput');
if (origFileInput) {
  origFileInput.addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      const numero = await BarcodeScanner.decodeFromFile(file);
      document.getElementById('manualBarcode').value = numero;
      // No fetch automático — el usuario puede revisar el número primero
    } catch (_) {
      // Ningún código de barras → continuar con OCR normal, sin interrumpir
    }
  });
}
</script>
```

> **Nota:** El nombre exacto de la función que renderiza resultados en la tabla (`mostrarResultados`, `renderTable`, etc.) depende del JS existente en `facturas.html`. Buscar con `grep -n "function.*result\|function.*tabla\|function.*render" templates/facturas.html` antes de editar y ajustar la llamada en `_fetchAlbaran`.

- [ ] **Verificar que facturas.html no tiene errores de sintaxis básicos**

```bash
python -c "
from flask import Flask
app = Flask(__name__, template_folder='templates')
with app.app_context():
    from flask import render_template_string
    with open('templates/facturas.html') as f:
        content = f.read()
    print('HTML leído OK, longitud:', len(content))
"
```
Expected: `HTML leído OK, longitud: XXXXX`

- [ ] **Commit**

```bash
git add templates/facturas.html
git commit -m "feat: tabs Escanear/Subir en facturas.html con ZXing-js y badge de proveedor"
```

---

## Task 10: Verificación E2E

> Checklist manual — ejecutar con la app corriendo localmente.

- [ ] **Arrancar la app**

```bash
flask run --port 5000
```
O si usa gunicorn localmente:
```bash
gunicorn app:app --bind 0.0.0.0:5000
```

- [ ] **Test 1: Tabs visibles**

Abrir `http://localhost:5000/facturas`. Verificar:
- [ ] Hay dos pestañas: "📷 Escanear albarán" y "📄 Subir factura"
- [ ] Por defecto el tab activo es "Escanear albarán"
- [ ] Al pulsar "Subir factura" → aparece la UI de upload original sin cambios

- [ ] **Test 2: Cámara**

En el tab "Escanear albarán":
- [ ] El navegador pide permiso de cámara al cargar la pestaña
- [ ] Al conceder permiso → aparece el video stream
- [ ] Apuntar al código de barras de un albarán real → se detecta y el número aparece en el input manual
- [ ] Aparece el badge de proveedor (Hefame/BIDA en azul/verde, o naranja si lab externo)

- [ ] **Test 3: Número manual Hefame**

Con credenciales configuradas en `.env`:
- [ ] Introducir un número de albarán de Hefame → pulsar "Buscar"
- [ ] Badge muestra "✓ Albarán X cargado desde portal"
- [ ] La tabla se rellena con las líneas del portal (sin OCR)
- [ ] El campo `numero_factura` tiene el número del albarán

- [ ] **Test 4: Lab externo → fallback OCR**

- [ ] Introducir un número de un lab externo (no Hefame/BIDA) → pulsar "Buscar"
- [ ] Badge muestra naranja "⚠ Lab externo — sube la foto para procesar con OCR"
- [ ] Cambiar al tab "Subir factura" → subir la foto → OCR funciona igual que antes

- [ ] **Test 5: Foto con código de barras en tab Subir**

- [ ] En tab "Subir factura" → subir una foto que contiene un código de barras
- [ ] El campo manual en el tab Escanear muestra el número detectado (sin interrumpir el OCR)

- [ ] **Test 6: Exportar CSV**

Después de cargar un albarán de Hefame:
- [ ] Pulsar "Exportar CSV" → verificar que la columna `numero_factura` contiene el número del albarán

- [ ] **Test 7: Sin credenciales (simular Render restart)**

```bash
# Arrancar sin HEFAME_USER
flask run --port 5000
```
- [ ] Buscar número Hefame → badge "⚠ Lab externo" con reason `no_credentials`
- [ ] No hay error 500 — la app sigue funcionando

- [ ] **Test 8: Ejecutar suite de tests**

```bash
python -m pytest tests/ -v
```
Expected: todos los tests pasan
