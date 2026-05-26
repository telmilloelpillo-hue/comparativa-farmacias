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
from dataclasses import dataclass
from typing import Optional

from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup


# ── Detección de proveedor ────────────────────────────────────────────────────
# Patrones ajustados tras inspección de albaranes reales (Task 4 y 5).
# El orden importa: el primer match gana.
_PROVIDER_PATTERNS: list[tuple[str, str]] = [
    (r'(?i)^hef', 'hefame'),
    (r'(?i)^bid', 'bida'),
    # Descomenta y ajusta si el código de barras usa prefijos numéricos:
    # (r'^\d{10}$', 'hefame'),   # ej: Hefame usa números de 10 dígitos
    # (r'^\d{9}$', 'bida'),      # ej: BIDA usa números de 9 dígitos
]


def detect_provider(numero: str) -> str:
    """Infiere el proveedor ('hefame'|'bida'|'unknown') por el prefijo del número."""
    for pattern, slug in _PROVIDER_PATTERNS:
        if re.match(pattern, numero):
            return slug
    return 'unknown'


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
        if resp.status_code in (401, 403) or urlparse(resp.url).path == urlparse(self.config.login_url).path:
            self._session = None
            self._login()
            resp = self._session.get(
                self.config.search_url,
                params={self.config.albaran_param: numero},
                timeout=15,
            )
            if resp.status_code in (401, 403) or urlparse(resp.url).path == urlparse(self.config.login_url).path:
                raise RuntimeError(
                    f'Re-login failed for {self.config.login_url!r} — verifica credenciales'
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
                pdf_url = urljoin(resp.url, link['href'])
                pdf_resp = self._session.get(pdf_url, timeout=20)
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
        cleaned = re.sub(r'[^\d,.]', '', s)
        if ',' in cleaned:
            cleaned = cleaned.replace('.', '').replace(',', '.')
        return float(cleaned)
    except ValueError:
        return 0.0


def _to_iva(s: str) -> int:
    m = re.search(r'\d+', s)
    return int(m.group()) if m else 21


# ── Configuraciones de portal (rellenar con valores reales tras inspección de Tasks 4 y 5) ──

HEFAME_CONFIG = PortalConfig(
    login_url    = 'HEFAME_LOGIN_URL',
    search_url   = 'HEFAME_SEARCH_URL',
    user_field   = 'HEFAME_USER_FIELD',
    pass_field   = 'HEFAME_PASS_FIELD',
    albaran_param= 'HEFAME_ALBARAN_PARAM',
    row_selector = 'HEFAME_ROW_SELECTOR',
    cols         = {'cn': 0, 'desc': 1, 'qty': 2, 'price': 3, 'iva': 4},
    pdf_selector = '',
)

BIDA_CONFIG = PortalConfig(
    login_url    = 'BIDA_LOGIN_URL',
    search_url   = 'BIDA_SEARCH_URL',
    user_field   = 'BIDA_USER_FIELD',
    pass_field   = 'BIDA_PASS_FIELD',
    albaran_param= 'BIDA_ALBARAN_PARAM',
    row_selector = 'BIDA_ROW_SELECTOR',
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
