---
tags: [frontend, jinja2, js, ux]
---

# Frontend Templates

## Estructura
```
templates/
  login.html
  index.html          ← selector de feature (3 cards)
  comparativa.html    ← tabla comparativa principal
  facturas.html       ← UI más compleja del proyecto
  encargos.html       ← JS puro, sin backend
```

## facturas.html (complejo)
Dos layouts CSS:
- `#uploadLayout` — estado inicial (grid 420px/1fr, scroll vertical)
- `#resultsLayout` — tras análisis (flex column, 100vh, overflow hidden)

Componentes JS relevantes:
```js
// Zoom/pan en preview
let _zoom = 1, _panX = 0, _panY = 0
function setTransform() { ... }
// Pinch zoom con damping al 10%
const damped = 1 + (raw - 1) * 0.1

// Persistencia en sessionStorage
const SESSION_KEY = 'factura_session'
function saveFileToSession()   // FileReader → base64 dataURL
function restoreSession()      // IIFE al cargar página

// PVP editable
let pvpManual = null           // null = calculado, number = manual (celda azul)
function onPvpChange(i, val)
function resetPvp(i)
function persistLineas()       // sincroniza con sessionStorage
```

## comparativa.html
Tabla grande con:
- Filtros por laboratorio, búsqueda libre
- Ordenación por columna
- Colores por estado (stock parado, pedido sugerido)
- Botón "Preguntar a la IA" por producto → modal con [[IA Anthropic]]
- Export PDF → `POST /generar_pedido`

## Patrones CSS reutilizados
```css
body { height: 100vh; overflow: hidden }   /* viewport fijo sin scroll global */
overscroll-behavior: contain               /* scroll isolation por panel */
touch-action: none                         /* control manual del pinch */
```

## Colores brand
- Verde header: `#166534`
- Rojo (Zarzuelo/Farmacia 1): `#dc2626`
- Azul (Barris/Farmacia 2): `#1d4ed8`

## Relaciones
- [[Feature Facturas]] — `facturas.html` es su UI
- [[Feature Comparativa]] — `comparativa.html`
- [[Feature Encargos]] — `encargos.html`
- [[IA Anthropic]] — llamadas AJAX desde comparativa y facturas
