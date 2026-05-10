---
tags: [backend, pdf, pdfplumber]
---

# PDF Processing

## Dos pipelines distintos

### 1. PDFs de ventas (Comparativa)
Procesado por `pdf_parser.py` con pdfplumber.
Columnas esperadas: `Código | Descripción | Stock | S.min | Año | Total | Ene … Dic`
Funciones: `extract_products()`, `detect_lab()`, `extract_situation()`, `detect_pdf_header()`

### 2. Facturas (leer_factura en app.py)
```python
with pdfplumber.open(io.BytesIO(data)) as pdf:
    for page in pdf.pages:
        # Intento 1: tablas con líneas dibujadas
        tables = page.extract_tables({'vertical_strategy': 'lines', 'horizontal_strategy': 'lines'})
        # Intento 2: tablas automáticas
        if not tables: tables = page.extract_tables()
        # Intento 3: texto con layout preservado
        if not tables: text = page.extract_text(layout=True) or page.extract_text()
```
Si hay tablas → filas formateadas como `col1 | col2 | col3`
Si no → texto plano con layout.
Resultado enviado a [[IA Anthropic]] como texto (no como PDF binario).

## Por qué pre-extraer con pdfplumber
Claude recibe texto estructurado en lugar de interpretar el layout visual.
Reduce mezcla de descripciones entre líneas adyacentes.
Ver problema conocido en [[Feature Facturas]].

## Fallback
Si pdfplumber falla o devuelve < 80 chars → se adjunta el PDF binario original
directamente a Claude como `type: document`.

## Librerías
- `pdfplumber` — extracción texto/tablas (ya en `requirements.txt`)
- `reportlab` — generación de PDFs de pedido (ver [[App Flask]])

## Relaciones
- [[Feature Comparativa]] — usa pdf_parser.py
- [[Feature Facturas]] — usa pipeline inline en app.py
- [[IA Anthropic]] — recibe el output de este pipeline
- [[Prompts IA]] — prompt diseñado para el formato de texto extraído
