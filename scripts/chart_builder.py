"""
chart_builder.py — Generación de gráficos Plotly para la comparativa de farmacias.
Produce HTML interactivo (para web/Obsidian) e imágenes PNG (para PDFs).
"""
import os
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

# Paleta brand
C_F1   = '#dc2626'   # rojo
C_F2   = '#1d4ed8'   # azul
C_BG   = '#f9fafb'
C_GRID = '#e5e7eb'
C_TEXT = '#111827'

_BASE_LAYOUT = dict(
    paper_bgcolor=C_BG,
    plot_bgcolor=C_BG,
    font=dict(family='Inter, sans-serif', color=C_TEXT, size=12),
    margin=dict(l=40, r=20, t=50, b=40),
    legend=dict(orientation='h', y=-0.15),
    xaxis=dict(gridcolor=C_GRID, linecolor=C_GRID),
    yaxis=dict(gridcolor=C_GRID, linecolor=C_GRID, zeroline=False),
)


def sales_comparison_bar(df: pd.DataFrame, top_n: int = 20) -> go.Figure:
    """Barras agrupadas: ventas año actual de los top N productos."""
    from scripts.stats import top_products
    name1 = df['_name1'].iloc[0]
    name2 = df['_name2'].iloc[0]
    sub = top_products(df, top_n)
    labels = [f"{r['code']}<br>{r['description'][:22]}…" if len(r['description']) > 22
              else f"{r['code']}<br>{r['description']}" for _, r in sub.iterrows()]

    fig = go.Figure([
        go.Bar(name=name1, x=labels, y=sub['total1'],
               marker_color=C_F1, opacity=0.85),
        go.Bar(name=name2, x=labels, y=sub['total2'],
               marker_color=C_F2, opacity=0.85),
    ])
    fig.update_layout(**_BASE_LAYOUT,
                      title=f'Top {top_n} productos — ventas año actual',
                      barmode='group',
                      height=420)
    return fig


def monthly_trend(df: pd.DataFrame) -> go.Figure:
    """Líneas mensuales de ventas totales de ambas farmacias."""
    from scripts.stats import monthly_totals
    name1 = df['_name1'].iloc[0]
    name2 = df['_name2'].iloc[0]
    mt = monthly_totals(df)

    fig = go.Figure([
        go.Scatter(name=name1, x=mt['mes'], y=mt['f1'],
                   mode='lines+markers', line=dict(color=C_F1, width=2.5),
                   marker=dict(size=7)),
        go.Scatter(name=name2, x=mt['mes'], y=mt['f2'],
                   mode='lines+markers', line=dict(color=C_F2, width=2.5),
                   marker=dict(size=7)),
    ])
    fig.update_layout(**_BASE_LAYOUT,
                      title='Evolución mensual de ventas',
                      height=360)
    return fig


def stock_coverage_scatter(df: pd.DataFrame) -> go.Figure:
    """Scatter: días de cobertura vs ventas totales, por producto."""
    name1 = df['_name1'].iloc[0]
    name2 = df['_name2'].iloc[0]
    sub = df[df['total_combined'] > 0].copy()

    fig = go.Figure([
        go.Scatter(
            name=name1,
            x=sub['total1'], y=sub['diasCobertura1'],
            mode='markers',
            marker=dict(color=C_F1, size=7, opacity=0.6),
            text=sub['description'],
            hovertemplate='%{text}<br>Ventas: %{x}<br>Cobertura: %{y}d<extra></extra>',
        ),
        go.Scatter(
            name=name2,
            x=sub['total2'], y=sub['diasCobertura2'],
            mode='markers',
            marker=dict(color=C_F2, size=7, opacity=0.6),
            text=sub['description'],
            hovertemplate='%{text}<br>Ventas: %{x}<br>Cobertura: %{y}d<extra></extra>',
        ),
    ])
    fig.update_layout(**_BASE_LAYOUT,
                      title='Cobertura de stock vs ventas',
                      xaxis_title='Ventas anuales (uds)',
                      yaxis_title='Días de cobertura',
                      height=400)
    return fig


def kpi_dashboard(kpis: dict, name1: str, name2: str) -> go.Figure:
    """Panel de KPIs como indicadores (gauge + número)."""
    v1 = kpis.get(f'ventas_{name1}', 0)
    v2 = kpis.get(f'ventas_{name2}', 0)
    p1 = kpis.get(f'stock_parado_{name1}', 0)
    p2 = kpis.get(f'stock_parado_{name2}', 0)
    total = kpis.get('total_productos', 1)

    fig = make_subplots(rows=1, cols=4,
                        specs=[[{'type': 'indicator'}] * 4])
    fig.add_trace(go.Indicator(
        mode='number', value=total,
        title={'text': 'Productos'},
        number={'font': {'color': C_TEXT}}), row=1, col=1)
    fig.add_trace(go.Indicator(
        mode='number', value=v1,
        title={'text': f'Ventas {name1}'},
        number={'font': {'color': C_F1}}), row=1, col=2)
    fig.add_trace(go.Indicator(
        mode='number', value=v2,
        title={'text': f'Ventas {name2}'},
        number={'font': {'color': C_F2}}), row=1, col=3)
    fig.add_trace(go.Indicator(
        mode='number', value=kpis.get('con_pedido', 0),
        title={'text': 'Con pedido'},
        number={'font': {'color': '#166534'}}), row=1, col=4)

    fig.update_layout(paper_bgcolor=C_BG, height=200,
                      margin=dict(l=20, r=20, t=40, b=20))
    return fig


def save_html(fig: go.Figure, path: str) -> str:
    """Guarda figura como HTML interactivo. Devuelve la ruta."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fig.write_html(path, include_plotlyjs='cdn', full_html=True)
    return path


def save_png(fig: go.Figure, path: str, width: int = 900,
             height: int = 420) -> str:
    """Guarda figura como PNG estático (requiere kaleido). Devuelve la ruta."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fig.write_image(path, width=width, height=height, scale=2)
    return path


def build_dashboard_html(df: pd.DataFrame, out_path: str) -> str:
    """
    Genera un HTML con el dashboard completo: KPIs + 3 gráficos.
    Sirve directamente desde Flask o se abre en el navegador.
    """
    from scripts.stats import kpis as compute_kpis
    name1 = df['_name1'].iloc[0]
    name2 = df['_name2'].iloc[0]
    kp = compute_kpis(df)

    figs = {
        'kpis':     kpi_dashboard(kp, name1, name2),
        'barras':   sales_comparison_bar(df),
        'mensual':  monthly_trend(df),
        'scatter':  stock_coverage_scatter(df),
    }

    import plotly.io as pio
    divs = {k: pio.to_html(v, include_plotlyjs=(k == 'kpis'),
                            full_html=False, div_id=k)
            for k, v in figs.items()}

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>Dashboard — {name1} vs {name2}</title>
  <style>
    body {{ margin: 0; padding: 16px; background: #f9fafb;
           font-family: Inter, sans-serif; color: #111827; }}
    h1   {{ font-size: 1.25rem; color: #166534; margin-bottom: 4px; }}
    .sub {{ font-size: .85rem; color: #6b7280; margin-bottom: 16px; }}
    .card {{ background: #fff; border-radius: 8px; padding: 16px;
             box-shadow: 0 1px 4px rgba(0,0,0,.08); margin-bottom: 16px; }}
  </style>
</head>
<body>
  <h1>Dashboard comparativa de farmacias</h1>
  <p class="sub">{name1} vs {name2}</p>
  <div class="card">{divs['kpis']}</div>
  <div class="card">{divs['barras']}</div>
  <div class="card">{divs['mensual']}</div>
  <div class="card">{divs['scatter']}</div>
</body>
</html>"""

    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)
    return out_path
