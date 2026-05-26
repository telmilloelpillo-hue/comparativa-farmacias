"""
portal_session.py — Gestión de sesiones en portales de proveedores (Hefame, BIDA).

Patrón de uso:
    from portal_session import detect_provider, get_session
    provider = detect_provider(numero_albaran)   # 'hefame' | 'bida' | 'unknown'
    session = get_session(provider)              # PortalSession o None
    result = session.fetch_albaran(numero)       # dict con 'lineas', 'numero_factura', etc.
"""

from __future__ import annotations

import re


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
