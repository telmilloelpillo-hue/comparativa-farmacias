---
tags: [ia, anthropic, backend]
---

# IA Anthropic

## Modelo en uso
`claude-haiku-4-5-20251001` — elegido por coste (ver [[Costes Tokens]]).
Antes se usó `claude-opus-4-6` (más caro, no compensa para facturas).

## Inicialización lazy
```python
try:
    import anthropic as _anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _anthropic = None
    _ANTHROPIC_AVAILABLE = False

def _get_api_key():      # lee de os.environ o .env directamente
def _ai_available():     # check en tiempo de request, no al importar
```
Crítico: si `_AI_AVAILABLE` se evaluaba al importar (antes de que dotenv cargara),
devolvía `False` aunque la clave existiera. La función runtime lo soluciona.

## Usos
| Endpoint | Prompt | Max tokens |
|---|---|---|
| `POST /leer_factura` | Extracción JSON de líneas | 8192 |
| `POST /pregunta` | Respuesta sobre stock de un producto | 350 |

## Flujo leer_factura
1. pdfplumber extrae texto (ver [[PDF Processing]])
2. Si texto > 80 chars → `content = [{"type": "text", ...}]` (sin adjuntar PDF)
3. Si no → `content = [{"type": "document", ...}, {"type": "text", ...}]`
4. Response → `json.loads()` → devuelve a frontend

## Flujo /pregunta
Recibe contexto de producto (stock, ventas, tendencia de ambas farmacias) +
pregunta del usuario. Responde en máx 4 frases.

## Config
- API key en [[Config y Deploy]]
- Prompts detallados en [[Prompts IA]]
