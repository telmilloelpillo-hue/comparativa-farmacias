---
tags: [feature, reportlab, pdf, reportes]
---

# Reportes PDF

## Dos tipos de PDF en el proyecto

| Tipo | Generado por | Ruta | Contenido |
|---|---|---|---|
| Pedido (tabla) | `generate_pdf()` en app.py | `GET /descargar` | Tabla de pedido por laboratorio |
| Informe ejecutivo | `report_builder.build_report()` | `GET /informe` | Portada + KPIs + gráficos + top 30 |

## report_builder.py — Estructura del informe

```
Portada
  → Título "Informe de Comparativa"
  → Subtítulo: Farmacia1 · Farmacia2 · Fecha
  → Línea verde divisoria

KPIs (4 tarjetas)
  → Total productos | Ventas F1 | Ventas F2 | Con pedido

Gráficos (PNGs incrustados via kaleido)
  → Barras top 20 productos
  → Evolución mensual

Tabla top 30 productos
  → Código | Descripción | Stock F1/F2 | Ventas F1/F2 | Pedido
  → Celda verde si pedido > 0
  → Celda naranja si stock parado
```

## Paleta reportlab
```python
GREEN   = '#166534'   # headers, títulos
RED     = '#dc2626'   # farmacia 1
BLUE    = '#1d4ed8'   # farmacia 2
GRAY_50 = '#f9fafb'   # fondo filas alternas
```

## Agregar una nueva sección
1. Añadir flowable a `story[]` en `build_report()`
2. Usar `Paragraph(texto, s['section'])` para cabecera de sección
3. Usar `_products_table()` como referencia para tablas con estilo

## Tipografía
Helvetica / Helvetica-Bold (disponible sin instalación en reportlab).
Para tipografía custom: registrar TTF con `pdfmetrics.registerFont()`.

## Relaciones
- [[Visualización Datos]] — los gráficos incrustados vienen de chart_builder.py
- [[Scripts Análisis]] — report_builder.py
- [[Feature Comparativa]] — datos de entrada
- [[App Flask]] — ruta /informe
