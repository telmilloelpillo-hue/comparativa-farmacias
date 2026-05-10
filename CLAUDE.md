# comparativa-farmacias — contexto para Claude

## Qué es
App Flask para gestión de dos farmacias (Barris y Zarzuelo). Tres features principales:
- **Comparativa**: sube dos PDFs de ventas → tabla comparativa con stock, tendencias, pedidos
- **Facturas**: sube factura/albarán PDF o imagen → IA extrae líneas → calcula PVP por proveedor
- **Encargos**: reservas de pacientes (frontend JS puro, sin backend propio)

## Stack
- Python 3 · Flask · gunicorn (producción)
- pdfplumber — extracción de texto/tablas de PDF
- reportlab — generación de PDFs de pedido
- anthropic — Claude Haiku para leer facturas y responder preguntas de stock
- Deployed en **Render** (auto-deploy en `git push`). Antes en PythonAnywhere.
- Obsidian vault = este mismo directorio. obsidian-git hace backup automático.

## Archivos críticos
| Archivo | Rol |
|---|---|
| `app.py` | Flask app completa. Todas las rutas aquí. |
| `pdf_parser.py` | Extracción de productos de PDFs de ventas (pdfplumber). |
| `labs.json` | Laboratorios conocidos con nombre, slug y palabras clave. |
| `templates/facturas.html` | UI compleja: tabla editable + panel preview con zoom/pan. |
| `templates/comparativa.html` | Tabla comparativa principal. |
| `requirements.txt` | flask, pdfplumber, reportlab, gunicorn, anthropic |
| `Procfile` | `web: gunicorn app:app` |
| `.env` | `ANTHROPIC_API_KEY=sk-ant-...` (no en git) |

## Rutas Flask (`app.py`)
```
GET  /              → index.html (selector de feature)
GET  /comparar      → comparativa.html  
POST /comparar      → procesa PDFs, devuelve JSON con productos comparados
POST /detect_pdf    → detecta lab del PDF antes de subir
GET  /progress/<t>  → SSE con progreso del job
GET  /comparativa/<t> → resultado comparativa
POST /generar_pedido → genera PDF de pedido
GET  /pedido_file/<id> → descarga PDF pedido
GET  /encargos      → encargos.html
POST /pregunta      → pregunta IA sobre un producto concreto (haiku, max 350 tokens)
GET  /facturas      → facturas.html
POST /leer_factura  → sube factura → pdfplumber extrae → haiku parsea → JSON
GET/POST /login     → auth por contraseña
GET  /logout
```

## Lógica IA (`app.py` ~línea 500+)
```python
def _get_api_key()   # lee ANTHROPIC_API_KEY de env o .env directamente
def _ai_available()  # check en tiempo de request, no al importar
# leer_factura:
#   1. pdfplumber extrae tablas/texto del PDF (evita mezcla de descripciones)
#   2. Si hay texto (>80 chars) → manda texto a haiku, sin adjuntar PDF binario
#   3. Si no → fallback: adjunta PDF binario como 'document'
#   Modelo: claude-haiku-4-5-20251001, max_tokens=8192
```

## PVP por proveedor (`_CONFIG_PROVEEDORES` en app.py)
Dos proveedores: `hefame_bida` y `laboratorio`. Cada uno tiene factores PVP por tipo IVA.
Fórmula: `PVP = precio_neto_unitario × factor`
El usuario puede editar PVP manualmente en la tabla (campo `pvpManual`).

## Auth
Contraseña única: `"farmacias2026"`. Flask session con secret key hardcodeada.
`check_auth()` en `before_request` protege todas las rutas excepto `/login` y `/static`.

## Frontend facturas.html (complejo)
- Layout CSS grid: upload state vs results state
- `#tableSection` scroll independiente, `#previewPanel` collapsible/resizable
- Zoom/pan en preview: pointer events + pinch (10% de sensibilidad para precisión)
- sessionStorage persiste la factura al recargar (`SESSION_KEY = 'factura_session'`)
- CSV export incluye PVP (manual o calculado)

## Notas de desarrollo
- `docs/` contiene notas Obsidian con detalles de cada feature → leer antes de tocar algo nuevo
- No hay base de datos: todo es estado en memoria o archivos temporales
- PDFs de ventas formato: columnas Código | Descripción | Stock | S.min | Año | Total | Ene…Dic
- Pendiente: mejorar lectura de PDFs con descripciones multi-línea (pdfplumber en curso)
