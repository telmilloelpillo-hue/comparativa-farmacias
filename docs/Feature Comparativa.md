---
tags: [feature, comparativa]
---

# Feature: Comparativa

## Qué hace
Sube dos PDFs de estadísticas de ventas (uno por farmacia) y genera una tabla comparativa
con stock, ventas anuales, tendencia y cantidad de pedido sugerida.

## Flujo
```
Usuario sube pdf1 + pdf2 (+ opcional sit1, sit2)
  → POST /comparar
  → detect_lab() identifica laboratorio
  → Thread async: extract_products() × 2 + compare_products()
  → SSE /progress/<token> con % avance
  → GET /comparativa/<token> → comparativa.html con datos JSON
```

## Módulos implicados
- [[PDF Processing]] — `extract_products()`, `detect_lab()`, `extract_situation()`
- [[App Flask]] — rutas `/comparar`, `/progress`, `/comparativa`, `/generar_pedido`
- [[Datos Proveedores]] — filtrado por laboratorio (`labs.json`)
- [[Frontend Templates]] — `comparativa.html`, tabla interactiva JS
- [[IA Anthropic]] — `/pregunta` permite preguntar por producto concreto

## Formato PDF de entrada
Columnas esperadas: `Código | Descripción | Stock | S.min | Año | Total | Ene … Dic`
Ver [[PDF Processing]] para detalles de parsing.

## Métricas calculadas
- `avgMonthly`: media de últimos 3 meses con ventas > 0
- `trend`: ↑ ↓ → según comparación año actual vs anterior
- `diasCobertura`: `stock / avgMonthly × 30`
- `pedido`: sugerido según stock mínimo y cobertura

## Exportación
Botón "Exportar PDF" → `POST /generar_pedido` → reportlab → descarga.
Sólo filas con pedido > 0 o marcadas manualmente.
