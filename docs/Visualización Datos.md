---
tags: [feature, visualizacion, plotly, pandas, dashboard]
---

# Visualización de Datos

## Stack
- **pandas** — DataFrames para estadísticas de ventas
- **plotly** — gráficos interactivos HTML + PNG estático (para PDFs)
- **kaleido** — exportación PNG desde plotly (necesario para incrustar en PDF)

## Arquitectura

```
scripts/
  stats.py          ← build_dataframe(), kpis(), monthly_totals(), top_products()
  chart_builder.py  ← sales_comparison_bar(), monthly_trend(), scatter, dashboard HTML
  report_builder.py ← build_report() → PDF ejecutivo con gráficos
```

## Flujo de datos
```
pdf_parser.py → compare_products() → lista de dicts
  → build_dataframe(products, name1, name2) → pd.DataFrame
  → [plotly]  → gráficos HTML interactivos → charts/
  → [kaleido] → PNGs → incrustados en PDF por reportlab
  → [reportlab] → reports/informe_*.pdf
```

## Rutas Flask
| Ruta | Resultado |
|---|---|
| `GET /dashboard` | HTML interactivo (KPIs + 3 gráficos plotly) |
| `GET /informe` | Descarga PDF ejecutivo (portada + KPIs + gráficos + tabla) |

Ambas rutas leen el `comp_token` de la sesión Flask y cargan el JSON de resultados.

## Gráficos disponibles
1. `sales_comparison_bar(df)` — Barras agrupadas top 20 productos
2. `monthly_trend(df)` — Líneas mensuales F1 vs F2
3. `stock_coverage_scatter(df)` — Scatter cobertura vs ventas
4. `kpi_dashboard(kpis, name1, name2)` — Panel de 4 indicadores

## Paleta brand
```python
C_F1   = '#dc2626'   # rojo (Farmacia 1)
C_F2   = '#1d4ed8'   # azul (Farmacia 2)
C_TEXT = '#111827'
C_BG   = '#f9fafb'
```

## Archivos generados (no en git)
- `charts/dashboard_<token>.html` — dashboard interactivo
- `reports/informe_<token>.pdf` — PDF ejecutivo

## Relaciones
- [[Feature Comparativa]] — fuente de datos
- [[Reportes PDF]] — detalles del PDF
- [[Scripts Análisis]] — módulos Python
- [[App Flask]] — rutas /dashboard y /informe
- [[Costes Tokens]] — plotly/pandas son locales, 0 coste IA
