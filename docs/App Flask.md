---
tags: [backend, arquitectura]
---

# App Flask

## Estructura general
`app.py` contiene toda la aplicación: rutas, lógica de negocio, generación de PDFs.
No hay blueprints; todo en un único fichero por simplicidad.

## Dependencias externas
- [[PDF Processing]] — `pdf_parser.py` importado como módulo
- [[IA Anthropic]] — anthropic SDK, lazy-init via `_get_api_key()`
- [[Datos Proveedores]] — `labs.json` y `_CONFIG_PROVEEDORES` dict en app.py
- [[Config y Deploy]] — `ANTHROPIC_API_KEY`, `SECRET_KEY`, `PORT`

## Rutas principales
| Ruta | Feature |
|---|---|
| `GET /` | index |
| `POST /comparar` | [[Feature Comparativa]] |
| `POST /leer_factura` | [[Feature Facturas]] |
| `POST /pregunta` | IA sobre producto individual |
| `GET /encargos` | [[Feature Encargos]] |
| `GET/POST /login` | [[Sesion y Auth]] |

## Jobs asíncronos
`/comparar` lanza un thread con `_progress_store[token]`.
El cliente hace polling a `/progress/<token>` via SSE hasta `done=True`,
luego redirige a `/comparativa/<token>`.

## Generación de PDF pedido
`generate_pdf()` y `_generate_pedido_pdf()` usan reportlab.
PDFs guardados en `PEDIDOS_DIR = ./pedidos/`.

## Colores brand
```python
C_HEADER  = '#166534'  # verde
C_Z_HDR   = '#dc2626'  # rojo Zarzuelo
C_B_HDR   = '#1d4ed8'  # azul Barris
```

Ver [[Frontend Templates]] para el CSS equivalente en HTML.
