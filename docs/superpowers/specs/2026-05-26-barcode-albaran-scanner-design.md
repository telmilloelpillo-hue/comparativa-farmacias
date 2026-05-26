# Diseño: Scanner de códigos de barras en albaranes

## Contexto

El sistema actual de lectura de facturas/albaranes (invoice_ocr.py) usa OCR + visión IA para extraer líneas de producto. El OCR comete errores frecuentes en albaranes de distribuidores (Hefame, BIDA) con tablas densas o texto pequeño. Los programas oficiales de farmacia evitan este problema conectando directamente con los portales de los distribuidores mediante el número de albarán, que viene codificado en el código de barras 1D del documento. El objetivo es replicar ese flujo: escanear el código → obtener datos oficiales → sin OCR para albaranes de Hefame/BIDA.

## Enfoque elegido: Híbrido inteligente (3 niveles de fallback)

Se construye una nueva capa de captura encima del sistema OCR existente. El OCR no se toca; sigue siendo el fallback para labs externos.

---

## Arquitectura

### Capa 1 — Frontend (browser)

**ZXing-js** (WebAssembly, carga desde CDN, sin instalación en servidor):
- Tab "Escanear albarán" como pestaña principal en `facturas.html`
- `getUserMedia` abre cámara; ZXing decodifica frames cada 300ms
- Al detectar código: beep + vibración, cámara se detiene
- Muestra número detectado + proveedor inferido (Hefame / BIDA / Lab externo)
- Input manual siempre visible como fallback si la cámara no lee bien
- Tab "Subir archivo" preserva el comportamiento actual intacto
- Subir foto también pasa por detección de barcode antes de enviar a OCR

### Capa 2 — Backend (Python, portal session)

**`portal_session.py`** — módulo nuevo con dos clases:

`PortalSessionManager`:
- Singleton por proveedor (una instancia Hefame, una BIDA)
- Credenciales desde `.env`: `HEFAME_USER`, `HEFAME_PASS`, `BIDA_USER`, `BIDA_PASS`
- Cookie de sesión cacheada en memoria del proceso → <1s si válida
- Auto re-login transparente si la respuesta es 401 o redirect a login
- Si el proveedor no tiene credenciales configuradas → lanza `ProviderNotConfigured`

`AlbaranFetcher`:
- Recibe número de albarán y proveedor
- Intenta primero descarga de PDF directo desde el portal
- Si no hay PDF disponible → parsea HTML con BeautifulSoup para extraer líneas
- Devuelve el mismo JSON que `leer_factura` (`lineas`, `numero_factura`, `fecha`, etc.)
- Si el portal no responde → lanza excepción → `app.py` hace fallback a OCR

`detect_provider(numero)`:
- Función pura que infiere proveedor por prefijo/formato del número
- Devuelve `"hefame"` | `"bida"` | `"unknown"`
- Los prefijos exactos se mapean durante implementación inspeccionando albaranes reales

### Capa 3 — Fallback OCR

`invoice_ocr.py` no se modifica. Se invoca exactamente igual que ahora cuando:
- El proveedor es `"unknown"` (lab externo)
- El portal no responde o devuelve error
- El usuario viene por el tab "Subir archivo" con un lab externo

---

## Nueva ruta Flask

```
POST /fetch_albaran
Body: { "numero": "HEF-2024-001234" }

Flujo:
  1. detect_provider(numero)
  2. Si hefame/bida → AlbaranFetcher.fetch(numero, proveedor)
       → devuelve JSON con lineas[] (misma estructura que /leer_factura)
  3. Si unknown → { "fallback": "ocr", "numero": numero }
       → el frontend llama a /leer_factura con la foto ya adjunta
```

La respuesta comparte estructura con `/leer_factura` para que el frontend no necesite lógica diferente según la fuente.

---

## Cambios por archivo

| Archivo | Cambio |
|---|---|
| `portal_session.py` | Nuevo. PortalSessionManager + AlbaranFetcher + detect_provider |
| `static/js/barcode_scanner.js` | Nuevo. Wrapper ZXing-js: cámara, decode, eventos |
| `app.py` | Añadir ruta `POST /fetch_albaran` (~30 líneas) |
| `templates/facturas.html` | Tabs Escanear/Subir, visor de cámara, indicador proveedor |
| `requirements.txt` | Añadir `beautifulsoup4` |
| `.env` | Añadir `HEFAME_USER`, `HEFAME_PASS`, `BIDA_USER`, `BIDA_PASS` |

---

## UX del scanner

```
[Escanear albarán]  [Subir archivo]     ← tabs principales

┌─────────────────────────────────────┐
│  🎥  vista cámara en tiempo real    │
│      ┌─────────────────────┐        │
│      │   apunta aquí       │  ←guía │
│      └─────────────────────┘        │
└─────────────────────────────────────┘
  ✅ Hefame detectado · Nº HEF-0012345

  [Número manual: ____________] [Buscar]

  → al confirmar: misma tabla de resultados de siempre
```

Estados del indicador de proveedor:
- Gris: esperando escaneo
- Azul parpadeante: procesando
- Verde: Hefame/BIDA → datos del portal
- Naranja: lab externo → OCR automático
- Rojo: error → mensaje descriptivo

---

## Notas de implementación

- **Inspección de portales**: durante implementación hay que mapear el HTML real de Hefame y BIDA (rutas de login, formulario de búsqueda, estructura de tabla de albarán, URL de descarga PDF). Esto se hace una vez con las credenciales reales.
- **Render free tier**: el proceso se reinicia periódicamente; la cookie de sesión se pierde y se regenera en el primer escaneo tras el reinicio (~3s extra, transparente para el usuario).
- **ZXing-js**: carga desde CDN `unpkg.com` o `cdn.jsdelivr.net`. No añade dependencias Python.
- **Número de albarán en CSV**: el campo `numero_factura` ya existe en la exportación; se rellena automáticamente desde el escaneo.

---

## Verificación end-to-end

1. Abrir `/facturas` → verificar tabs "Escanear" y "Subir archivo"
2. Escanear albarán Hefame real con cámara → tabla se rellena sin OCR, PDF descargable
3. Introducir número Hefame manualmente → mismo resultado
4. Subir foto de albarán lab externo → OCR funciona igual que antes (sin regresión)
5. Simular cookie expirada (reinicio Render) → re-login automático transparente
6. Albarán BIDA → mismo flujo que Hefame si `BIDA_USER`/`BIDA_PASS` configurados
7. Exportar CSV → columna `numero_factura` contiene el número escaneado
