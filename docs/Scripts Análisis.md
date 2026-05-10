---
tags: [backend, scripts, pandas, plotly, reportlab]
---

# Scripts de Análisis

## Estructura
```
scripts/
  __init__.py
  stats.py          ← capa de datos (pandas)
  chart_builder.py  ← capa de visualización (plotly)
  report_builder.py ← capa de exportación (reportlab)
```

## stats.py — Funciones principales
```python
build_dataframe(products, name1, name2) → pd.DataFrame
# Convierte lista de dicts de compare_products() en DataFrame normalizado.
# Columnas: code, description, stock1/2, smin1/2, total1/2, pedido,
#           avgMonthly1/2, diasCobertura1/2, trend1/2, s365_1/2,
#           m1_ene…m1_dic, m2_ene…m2_dic, total_combined, _name1, _name2

top_products(df, n=20, by='total_combined') → pd.DataFrame
# Top N productos por ventas combinadas (o cualquier columna numérica).

kpis(df) → dict
# KPIs globales: total_productos, con_pedido, ventas_F1/F2,
#               stock_parado_F1/F2, cobertura_media_F1/F2

monthly_totals(df) → pd.DataFrame
# Totales mensuales agregados. Columnas: mes, f1, f2
```

## chart_builder.py — Funciones principales
```python
sales_comparison_bar(df, top_n=20)  → go.Figure
monthly_trend(df)                   → go.Figure
stock_coverage_scatter(df)          → go.Figure
kpi_dashboard(kpis, name1, name2)   → go.Figure
save_html(fig, path)                → str  # HTML interactivo
save_png(fig, path, width, height)  → str  # PNG estático (kaleido)
build_dashboard_html(df, out_path)  → str  # Dashboard HTML completo
```

## report_builder.py — Funciones principales
```python
build_report(df, output_path, include_charts=True) → str
# Genera PDF ejecutivo completo. include_charts=True requiere kaleido.
```

## Uso desde CLI
```bash
# Generar dashboard y PDF desde consola
venv/bin/python3 - <<'EOF'
from scripts.stats import build_dataframe
from scripts.chart_builder import build_dashboard_html
from scripts.report_builder import build_report
import json, sys

with open(sys.argv[1]) as f:
    data = json.load(f)

df = build_dataframe(data['results'], data['name1'], data['name2'])
build_dashboard_html(df, 'charts/dashboard.html')
build_report(df, 'reports/informe.pdf')
EOF
```

## Relaciones
- [[Visualización Datos]] — flujo completo y rutas Flask
- [[Reportes PDF]] — detalles de report_builder
- [[Feature Comparativa]] — produce los datos de entrada
- [[Config y Deploy]] — no requieren variables de entorno (local puro)
