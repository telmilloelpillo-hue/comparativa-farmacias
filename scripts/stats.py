"""
stats.py — Transformación de datos de comparativa a pandas DataFrames.
Entrada: lista de productos de compare_products() (app.py / pdf_parser.py)
Salida:  DataFrames listos para plotly y reportlab.
"""
import pandas as pd
import numpy as np

MONTHS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun',
          'jul', 'ago', 'sep', 'oct', 'nov', 'dic']


def build_dataframe(products: list, name1: str = 'Farmacia 1',
                    name2: str = 'Farmacia 2') -> pd.DataFrame:
    """Convierte la lista de productos en un DataFrame normalizado."""
    rows = []
    for p in products:
        row = {
            'code':         p.get('code', ''),
            'description':  p.get('description', ''),
            'stock1':       _to_float(p.get('stock1')),
            'stock2':       _to_float(p.get('stock2')),
            'smin1':        _to_float(p.get('smin1')),
            'smin2':        _to_float(p.get('smin2')),
            'total1':       _to_float(p.get('total1')),
            'total2':       _to_float(p.get('total2')),
            'total1_prev':  _to_float(p.get('total1_prev')),
            'total2_prev':  _to_float(p.get('total2_prev')),
            'pedido':       _to_float(p.get('pedido', 0)),
            'avgMonthly1':  _to_float(p.get('avgMonthly1', 0)),
            'avgMonthly2':  _to_float(p.get('avgMonthly2', 0)),
            'diasCobertura1': _to_float(p.get('diasCobertura1', 0)),
            'diasCobertura2': _to_float(p.get('diasCobertura2', 0)),
            'trend1':       p.get('trend1', '→'),
            'trend2':       p.get('trend2', '→'),
            's365_1':       _to_float(p.get('s365_1', 0)),
            's365_2':       _to_float(p.get('s365_2', 0)),
        }
        # Ventas mensuales
        for m in MONTHS:
            row[f'm1_{m}'] = _to_float(p.get(f'{m}1', p.get(f'{m}_1', 0)))
            row[f'm2_{m}'] = _to_float(p.get(f'{m}2', p.get(f'{m}_2', 0)))
        rows.append(row)

    df = pd.DataFrame(rows)
    df['total_combined'] = df['total1'] + df['total2']
    df['stock_parado1'] = (df['s365_1'] > 0).astype(int)
    df['stock_parado2'] = (df['s365_2'] > 0).astype(int)
    df['_name1'] = name1
    df['_name2'] = name2
    return df


def top_products(df: pd.DataFrame, n: int = 20,
                 by: str = 'total_combined') -> pd.DataFrame:
    """Top N productos por ventas combinadas (o cualquier columna)."""
    return df.nlargest(n, by).reset_index(drop=True)


def kpis(df: pd.DataFrame) -> dict:
    """KPIs globales del informe."""
    name1 = df['_name1'].iloc[0] if len(df) else 'F1'
    name2 = df['_name2'].iloc[0] if len(df) else 'F2'
    return {
        'total_productos':    len(df),
        'con_pedido':         int((df['pedido'] > 0).sum()),
        f'ventas_{name1}':    int(df['total1'].sum()),
        f'ventas_{name2}':    int(df['total2'].sum()),
        f'stock_parado_{name1}': int(df['stock_parado1'].sum()),
        f'stock_parado_{name2}': int(df['stock_parado2'].sum()),
        f'cobertura_media_{name1}': round(df.loc[df['diasCobertura1'] > 0, 'diasCobertura1'].mean(), 1),
        f'cobertura_media_{name2}': round(df.loc[df['diasCobertura2'] > 0, 'diasCobertura2'].mean(), 1),
    }


def monthly_totals(df: pd.DataFrame) -> pd.DataFrame:
    """Totales mensuales agregados para ambas farmacias."""
    rows = []
    for m in MONTHS:
        rows.append({
            'mes':  m.capitalize(),
            'f1':   df[f'm1_{m}'].sum(),
            'f2':   df[f'm2_{m}'].sum(),
        })
    return pd.DataFrame(rows)


def _to_float(v) -> float:
    try:
        return float(str(v).replace(',', '.').replace(' ', '')) if v not in (None, '', '—') else 0.0
    except (ValueError, TypeError):
        return 0.0
