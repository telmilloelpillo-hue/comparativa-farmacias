"""
report_builder.py — PDF ejecutivo con reportlab.
Incluye: portada, KPIs, tabla top productos, gráficos incrustados (PNG via kaleido).
"""
import os
import io
import tempfile
from datetime import datetime

import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, Image, KeepTogether,
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

# ── Paleta ────────────────────────────────────────────────────────────────────
GREEN   = colors.HexColor('#166534')
RED     = colors.HexColor('#dc2626')
BLUE    = colors.HexColor('#1d4ed8')
LIGHT_G = colors.HexColor('#d1fae5')
LIGHT_R = colors.HexColor('#fef2f2')
LIGHT_B = colors.HexColor('#eff6ff')
GRAY_50 = colors.HexColor('#f9fafb')
GRAY_200= colors.HexColor('#e5e7eb')
GRAY_700= colors.HexColor('#374151')
WHITE   = colors.white
BLACK   = colors.HexColor('#111827')

W, H = A4


def _styles():
    return {
        'title': ParagraphStyle('title', fontName='Helvetica-Bold',
                                fontSize=20, textColor=GREEN,
                                spaceAfter=4, leading=24),
        'subtitle': ParagraphStyle('subtitle', fontName='Helvetica',
                                   fontSize=11, textColor=GRAY_700,
                                   spaceAfter=16),
        'section': ParagraphStyle('section', fontName='Helvetica-Bold',
                                  fontSize=13, textColor=GREEN,
                                  spaceBefore=18, spaceAfter=6),
        'body': ParagraphStyle('body', fontName='Helvetica',
                               fontSize=9, textColor=BLACK,
                               leading=13),
        'kpi_label': ParagraphStyle('kpi_label', fontName='Helvetica',
                                    fontSize=8, textColor=GRAY_700,
                                    alignment=TA_CENTER),
        'kpi_value': ParagraphStyle('kpi_value', fontName='Helvetica-Bold',
                                    fontSize=20, textColor=GREEN,
                                    alignment=TA_CENTER, leading=24),
        'footer': ParagraphStyle('footer', fontName='Helvetica',
                                 fontSize=7, textColor=GRAY_700,
                                 alignment=TA_CENTER),
        'cell': ParagraphStyle('cell', fontName='Helvetica',
                               fontSize=8, textColor=BLACK, leading=10),
        'cell_bold': ParagraphStyle('cell_bold', fontName='Helvetica-Bold',
                                    fontSize=8, textColor=BLACK, leading=10),
    }


def _kpi_table(kpis: dict, name1: str, name2: str, s) -> Table:
    """Fila de tarjetas KPI."""
    items = [
        ('Productos',           str(kpis.get('total_productos', 0)),   BLACK),
        (f'Ventas {name1}',     str(kpis.get(f'ventas_{name1}', 0)),   RED),
        (f'Ventas {name2}',     str(kpis.get(f'ventas_{name2}', 0)),   BLUE),
        ('Con pedido',          str(kpis.get('con_pedido', 0)),         GREEN),
    ]
    cells = [[Paragraph(lbl, s['kpi_label']),
              Paragraph(val, ParagraphStyle('kv', fontName='Helvetica-Bold',
                                            fontSize=18, textColor=col,
                                            alignment=TA_CENTER, leading=22))]
             for lbl, val, col in items]

    col_w = (W - 4 * cm) / len(items)
    tbl = Table([cells[0][:1] + cells[1][:1] + cells[2][:1] + cells[3][:1],
                 cells[0][1:] + cells[1][1:] + cells[2][1:] + cells[3][1:]],
                colWidths=[col_w] * len(items), rowHeights=[16, 28])
    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), GRAY_50),
        ('BOX',        (0, 0), (-1, -1), 0.5, GRAY_200),
        ('INNERGRID',  (0, 0), (-1, -1), 0.5, GRAY_200),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [GRAY_50]),
        ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    return tbl


def _products_table(df: pd.DataFrame, name1: str, name2: str, s,
                    top_n: int = 30) -> Table:
    from scripts.stats import top_products
    sub = top_products(df, top_n)

    header = ['Código', 'Descripción', f'Stock\n{name1}', f'Stock\n{name2}',
              f'Ventas\n{name1}', f'Ventas\n{name2}', 'Pedido']
    rows = [header]
    for _, r in sub.iterrows():
        rows.append([
            Paragraph(str(r['code']), s['cell']),
            Paragraph(str(r['description'])[:40], s['cell']),
            Paragraph(str(int(r['stock1'])), s['cell']),
            Paragraph(str(int(r['stock2'])), s['cell']),
            Paragraph(str(int(r['total1'])), s['cell']),
            Paragraph(str(int(r['total2'])), s['cell']),
            Paragraph(str(int(r['pedido'])) if r['pedido'] > 0 else '—', s['cell']),
        ])

    col_ws = [2.2 * cm, 7.2 * cm, 1.5 * cm, 1.5 * cm,
              1.8 * cm, 1.8 * cm, 1.5 * cm]
    tbl = Table(rows, colWidths=col_ws, repeatRows=1)
    style = [
        ('BACKGROUND',   (0, 0), (-1, 0),  GREEN),
        ('TEXTCOLOR',    (0, 0), (-1, 0),  WHITE),
        ('FONTNAME',     (0, 0), (-1, 0),  'Helvetica-Bold'),
        ('FONTSIZE',     (0, 0), (-1, 0),  7),
        ('FONTSIZE',     (0, 1), (-1, -1), 8),
        ('ALIGN',        (2, 0), (-1, -1), 'CENTER'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, GRAY_50]),
        ('GRID',         (0, 0), (-1, -1), 0.3, GRAY_200),
        ('VALIGN',       (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',   (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 4),
    ]
    # Colorear pedido > 0
    for i, (_, r) in enumerate(sub.iterrows(), start=1):
        if r['pedido'] > 0:
            style.append(('BACKGROUND', (6, i), (6, i), LIGHT_G))
        if r['stock_parado1'] > 0:
            style.append(('BACKGROUND', (2, i), (2, i), colors.HexColor('#ffe0b2')))
        if r['stock_parado2'] > 0:
            style.append(('BACKGROUND', (3, i), (3, i), colors.HexColor('#ffe0b2')))
    tbl.setStyle(TableStyle(style))
    return tbl


def _embed_chart(fig, width_cm: float = 16, height_cm: float = 7) -> Image | None:
    """Renderiza figura plotly como PNG y devuelve un flowable Image."""
    try:
        buf = io.BytesIO()
        fig.write_image(buf, format='png',
                        width=int(width_cm * 37.8),
                        height=int(height_cm * 37.8), scale=2)
        buf.seek(0)
        return Image(buf, width=width_cm * cm, height=height_cm * cm)
    except Exception:
        return None


def build_report(df: pd.DataFrame, output_path: str,
                 include_charts: bool = True) -> str:
    """
    Genera el PDF ejecutivo completo.
    include_charts=True requiere kaleido instalado.
    Devuelve la ruta del PDF generado.
    """
    from scripts.stats import kpis as compute_kpis
    from scripts import chart_builder as cb

    name1 = df['_name1'].iloc[0]
    name2 = df['_name2'].iloc[0]
    kp    = compute_kpis(df)
    s     = _styles()
    fecha = datetime.now().strftime('%d/%m/%Y %H:%M')

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
        title=f'Informe comparativa — {name1} vs {name2}',
        author='comparativa-farmacias',
    )

    story = []

    # ── Portada ───────────────────────────────────────────────────────────────
    story += [
        Spacer(1, 1 * cm),
        Paragraph('Informe de Comparativa', s['title']),
        Paragraph(f'{name1}  ·  {name2}  ·  {fecha}', s['subtitle']),
        HRFlowable(width='100%', thickness=1, color=GREEN, spaceAfter=16),
    ]

    # ── KPIs ──────────────────────────────────────────────────────────────────
    story += [
        Paragraph('KPIs generales', s['section']),
        _kpi_table(kp, name1, name2, s),
        Spacer(1, 0.5 * cm),
    ]

    # ── Gráficos ──────────────────────────────────────────────────────────────
    if include_charts:
        story.append(Paragraph('Ventas anuales — top 20 productos', s['section']))
        img = _embed_chart(cb.sales_comparison_bar(df), width_cm=16, height_cm=7)
        if img:
            story += [img, Spacer(1, 0.4 * cm)]

        story.append(Paragraph('Evolución mensual', s['section']))
        img = _embed_chart(cb.monthly_trend(df), width_cm=16, height_cm=6)
        if img:
            story += [img, Spacer(1, 0.4 * cm)]

    # ── Tabla productos ───────────────────────────────────────────────────────
    story += [
        Paragraph('Top 30 productos por ventas combinadas', s['section']),
        _products_table(df, name1, name2, s),
        Spacer(1, 0.3 * cm),
    ]

    # ── Footer ────────────────────────────────────────────────────────────────
    story += [
        HRFlowable(width='100%', thickness=0.5, color=GRAY_200),
        Spacer(1, 0.2 * cm),
        Paragraph(f'Generado el {fecha} · comparativa-farmacias · Uso interno',
                  s['footer']),
    ]

    doc.build(story)
    return output_path
