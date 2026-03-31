from flask import Flask, request, render_template, send_file, session, redirect, url_for
import os, tempfile
from datetime import datetime
from pdf_parser import extract_products, compare_products, detect_lab, extract_situation

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm

app = Flask(__name__)
app.secret_key = 'farmacias_barris_zarzuelo_2026'

# ── Configuración ──────────────────────────────────────────────────────────────
PASSWORD             = "farmacias2026"
MAX_PDF_MB           = 20
app.config['MAX_CONTENT_LENGTH'] = MAX_PDF_MB * 1024 * 1024

# ── Colores ────────────────────────────────────────────────────────────────────
C_HEADER    = colors.HexColor('#2c3e50')
C_Z_BG      = colors.HexColor('#fdecea')
C_B_BG      = colors.HexColor('#e8f3fb')
C_Z_HDR     = colors.HexColor('#c0392b')
C_B_HDR     = colors.HexColor('#1a6fa8')
C_ROW_ALT   = colors.HexColor('#f7f5f0')
C_GRID      = colors.HexColor('#d0cdc8')
C_WARNING   = colors.HexColor('#fff3cd')
C_PARADO    = colors.HexColor('#ffe0b2')   # naranja suave → stock parado
C_PEDIDO    = colors.HexColor('#d4edda')   # verde suave → pedido > 0

# ── Login ──────────────────────────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form.get('password') == PASSWORD:
            session['authenticated'] = True
            return redirect(url_for('index'))
        error = 'Contraseña incorrecta'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.before_request
def check_auth():
    if request.endpoint in ('login', 'static'):
        return
    if not session.get('authenticated'):
        return redirect(url_for('login'))

# ── Rutas ──────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/comparar', methods=['POST'])
def comparar():
    file1 = request.files.get('pdf1')
    file2 = request.files.get('pdf2')
    sit1  = request.files.get('sit1')   # opcional
    sit2  = request.files.get('sit2')   # opcional
    name1 = request.form.get('name1', 'Farmacia 1').strip()
    name2 = request.form.get('name2', 'Farmacia 2').strip()

    if not file1 or not file2:
        return 'Debes subir los dos PDFs de ventas', 400

    # Verificar que los PDFs obligatorios son reales
    for f, nombre in [(file1, name1), (file2, name2)]:
        header = f.read(4)
        f.seek(0)
        if header != b'%PDF':
            return f'El archivo de {nombre} no es un PDF válido', 400

    # Verificar PDFs opcionales si se subieron (y no están vacíos)
    def _is_valid_pdf(f):
        if not f or f.filename == '':
            return False
        header = f.read(4)
        f.seek(0)
        return header == b'%PDF'

    has_sit1 = _is_valid_pdf(sit1)
    has_sit2 = _is_valid_pdf(sit2)

    # Guardar archivos temporales
    tmp1  = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
    tmp2  = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
    file1.save(tmp1.name)
    file2.save(tmp2.name)

    tmp_sit1 = tmp_sit2 = None
    if has_sit1:
        tmp_sit1 = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        sit1.save(tmp_sit1.name)
    if has_sit2:
        tmp_sit2 = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        sit2.save(tmp_sit2.name)

    try:
        # Detectar laboratorio de los PDFs de ventas
        lab1 = detect_lab(tmp1.name)
        lab2 = detect_lab(tmp2.name)

        if lab1 != lab2:
            return render_template('error.html', lab1=lab1, lab2=lab2), 400

        products1 = extract_products(tmp1.name)
        products2 = extract_products(tmp2.name)

        # Parsear informes de situación si se han subido
        situation1 = extract_situation(tmp_sit1.name) if has_sit1 else None
        situation2 = extract_situation(tmp_sit2.name) if has_sit2 else None

        results = compare_products(
            products1, products2, name1, name2,
            situation1=situation1, situation2=situation2
        )

        lab_slug = (lab1.replace(' ', '_').replace('-', '_')
                       .replace("'", '').replace('é','e')
                       .replace('à','a').replace('ó','o'))
        download_name = f'comparativa_{lab_slug}.pdf'

        output = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        generate_pdf(
            results, output.name, name1, name2,
            len(products1), len(products2), lab1,
            has_situation1=has_sit1, has_situation2=has_sit2
        )

        return send_file(output.name, as_attachment=True,
                         download_name=download_name,
                         mimetype='application/pdf')
    finally:
        os.unlink(tmp1.name)
        os.unlink(tmp2.name)
        if tmp_sit1: os.unlink(tmp_sit1.name)
        if tmp_sit2: os.unlink(tmp_sit2.name)

@app.errorhandler(413)
def too_large(e):
    return f'El PDF es demasiado grande. Máximo {MAX_PDF_MB}MB por archivo.', 413


# ── Generación del PDF ─────────────────────────────────────────────────────────
def generate_pdf(results, output_path, name1, name2, count1, count2,
                 lab_name='', has_situation1=False, has_situation2=False):

    from datetime import datetime as _dt

    doc = SimpleDocTemplate(
        output_path,
        pagesize=landscape(A4),
        leftMargin=1*cm, rightMargin=1*cm,
        topMargin=1.2*cm, bottomMargin=1.2*cm
    )

    title_style = ParagraphStyle('title',
        fontName='Helvetica-Bold', fontSize=11, leading=13,
        textColor=colors.white)
    sub_style = ParagraphStyle('sub',
        fontName='Helvetica', fontSize=7.5, leading=9,
        textColor=colors.HexColor('#a0aab4'))
    cell_style = ParagraphStyle('cell',
        fontName='Helvetica', fontSize=7, leading=8.5,
        textColor=colors.HexColor('#1c1a17'))

    show_s365 = has_situation1 or has_situation2

    yr_cur  = results[0]['year_current'] if results else 2026
    yr_prev = results[0]['year_prev']    if results else 2025

    today   = _dt.today().strftime('%d/%m/%Y')
    n_both  = sum(1 for r in results if r['status'] == 'both')
    n_only1 = sum(1 for r in results if r['status'] == 'only1')
    n_only2 = sum(1 for r in results if r['status'] == 'only2')
    n_par1  = sum(1 for r in results if r.get('parado1'))
    n_par2  = sum(1 for r in results if r.get('parado2'))

    lab_part   = f"  ·  {lab_name}" if lab_name else ""
    title_text = f"Comparativa de Stock{lab_part}  ·  {name1} vs {name2}  ·  {today}"
    stats_parts = [
        f"{name1}: {count1} prod.", f"{name2}: {count2} prod.",
        f"Total: {len(results)}", f"Ambas: {n_both}",
        f"Solo {name1}: {n_only1}", f"Solo {name2}: {n_only2}",
    ]
    if has_situation1: stats_parts.append(f"Parados {name1}: {n_par1}")
    if has_situation2: stats_parts.append(f"Parados {name2}: {n_par2}")
    stats_text = "  ·  ".join(stats_parts)

    def hdr(text, size=7.5, bold=True):
        fn = 'Helvetica-Bold' if bold else 'Helvetica'
        return Paragraph(
            f'<font name="{fn}" size="{size}">{text}</font>',
            ParagraphStyle('_h', leading=size+2, alignment=1, textColor=colors.white))

    # ── Cabeceras ─────────────────────────────────────────────────────────────
    # Con S.365: 14 cols (2 + 6 farm1 + 6 farm2); sin S.365: 12 cols (2+5+5)

    if show_s365:
        # Cols 0-1: Cód/Desc | 2-7: Farm1 | 8-13: Farm2
        row_farmacia = ['', '',
            hdr(f'● {name1}', size=8), '', '', '', '', '',
            hdr(f'● {name2}', size=8), '', '', '', '', '']
        row_cols = [
            hdr('Cód', size=7), hdr('Descripción', size=7),
            hdr('Stock',size=7), hdr('S.min',size=7),
            hdr(f'V.{yr_cur}',size=7), hdr(f'V.{yr_prev}',size=7),
            hdr('S.365',size=7), hdr('Pedido',size=7),
            hdr('Stock',size=7), hdr('S.min',size=7),
            hdr(f'V.{yr_cur}',size=7), hdr(f'V.{yr_prev}',size=7),
            hdr('S.365',size=7), hdr('Pedido',size=7),
        ]
        span1_end = 7; span2_start = 8; span2_end = 13
        divider_col = 7
        s365_1_col = 6; s365_2_col = 12
        pedido1_col = 7; pedido2_col = 13
        col_widths = [
            1.6*cm, 5.5*cm,
            1.1*cm, 1.1*cm, 1.2*cm, 1.2*cm, 1.1*cm, 1.2*cm,
            1.1*cm, 1.1*cm, 1.2*cm, 1.2*cm, 1.1*cm, 1.2*cm,
        ]
    else:
        # Cols 0-1: Cód/Desc | 2-6: Farm1 | 7-11: Farm2
        row_farmacia = ['', '',
            hdr(f'● {name1}', size=8), '', '', '', '',
            hdr(f'● {name2}', size=8), '', '', '', '']
        row_cols = [
            hdr('Código',size=7), hdr('Descripción',size=7),
            hdr('Stock',size=7), hdr('S.min',size=7),
            hdr(f'V.{yr_cur}',size=7), hdr(f'V.{yr_prev}',size=7), hdr('Pedido',size=7),
            hdr('Stock',size=7), hdr('S.min',size=7),
            hdr(f'V.{yr_cur}',size=7), hdr(f'V.{yr_prev}',size=7), hdr('Pedido',size=7),
        ]
        span1_end = 6; span2_start = 7; span2_end = 11
        divider_col = 6
        s365_1_col = None; s365_2_col = None
        pedido1_col = 6; pedido2_col = 11
        col_widths = [
            1.8*cm, 6.0*cm,
            1.2*cm, 1.2*cm, 1.3*cm, 1.3*cm, 1.2*cm,
            1.2*cm, 1.2*cm, 1.3*cm, 1.3*cm, 1.2*cm,
        ]

    def _fmt(v):
        if v in ('—', '⚠️') or v is None: return str(v) if v else '⚠️'
        return str(v)

    data = [row_farmacia, row_cols]
    row_meta = []

    for r in results:
        idx = len(data)
        desc_text = r['description']
        max_desc = 48 if show_s365 else 52
        if len(desc_text) > max_desc:
            desc_text = desc_text[:max_desc-2] + '…'
        warn_flag = ' ⚠' if r['needs_review'] else ''
        desc_para = Paragraph(desc_text + warn_flag, cell_style)

        if show_s365:
            row = [
                r['code'], desc_para,
                _fmt(r['stock1']), _fmt(r['smin1']),
                _fmt(r['total1']), _fmt(r['total1_prev']), _fmt(r.get('s365_1','—')),
                str(r.get('pedido1', 0)),
                _fmt(r['stock2']), _fmt(r['smin2']),
                _fmt(r['total2']), _fmt(r['total2_prev']), _fmt(r.get('s365_2','—')),
                str(r.get('pedido2', 0)),
            ]
        else:
            row = [
                r['code'], desc_para,
                _fmt(r['stock1']), _fmt(r['smin1']),
                _fmt(r['total1']), _fmt(r['total1_prev']),
                str(r.get('pedido1', 0)),
                _fmt(r['stock2']), _fmt(r['smin2']),
                _fmt(r['total2']), _fmt(r['total2_prev']),
                str(r.get('pedido2', 0)),
            ]
        data.append(row)
        row_meta.append((idx, r['status'], r['needs_review'],
                         r.get('parado1',False), r.get('parado2',False),
                         r.get('pedido1', 0), r.get('pedido2', 0)))

    table = Table(data, colWidths=col_widths, repeatRows=2)

    ts = TableStyle([
        ('BACKGROUND',    (0,0), (1,0),           C_HEADER),
        ('BACKGROUND',    (2,0), (span1_end,0),   C_Z_HDR),
        ('BACKGROUND',    (span2_start,0), (-1,0),C_B_HDR),
        ('SPAN',          (2,0), (span1_end,0)),
        ('SPAN',          (span2_start,0), (-1,0)),
        ('ALIGN',         (0,0), (-1,0),  'CENTER'),
        ('VALIGN',        (0,0), (-1,0),  'MIDDLE'),
        ('ROWHEIGHT',     (0,0), (0,0),   16),
        ('BACKGROUND',    (0,1), (1,1),           C_HEADER),
        ('BACKGROUND',    (2,1), (span1_end,1),   C_Z_HDR),
        ('BACKGROUND',    (span2_start,1), (-1,1),C_B_HDR),
        ('ALIGN',         (0,1), (-1,1),  'CENTER'),
        ('VALIGN',        (0,1), (-1,1),  'MIDDLE'),
        ('ROWHEIGHT',     (0,1), (0,1),   13),
        ('FONTNAME',      (0,2), (-1,-1), 'Helvetica'),
        ('FONTSIZE',      (0,2), (-1,-1), 7),
        ('ALIGN',         (0,2), (-1,-1), 'CENTER'),
        ('ALIGN',         (1,2), (1,-1),  'LEFT'),
        ('VALIGN',        (0,2), (-1,-1), 'MIDDLE'),
        ('TOPPADDING',    (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('LEFTPADDING',   (0,0), (-1,-1), 4),
        ('RIGHTPADDING',  (0,0), (-1,-1), 4),
        ('GRID',          (0,0), (-1,-1), 0.25, C_GRID),
        ('LINEBELOW',     (0,0), (-1,0),  0.8,  colors.white),
        ('LINEBELOW',     (0,1), (-1,1),  0.8,  colors.white),
        ('LINEAFTER',     (1,0), (1,-1),  0.8,  C_GRID),
        ('LINEAFTER',     (divider_col,0),(divider_col,-1), 1.2, C_HEADER),
    ])

    for idx, status, needs_review, parado1, parado2, pedido1, pedido2 in row_meta:
        if needs_review:
            ts.add('BACKGROUND', (0,idx), (-1,idx), C_WARNING)
        elif status == 'only1':
            ts.add('BACKGROUND', (0,idx), (-1,idx), C_Z_BG)
            ts.add('TEXTCOLOR',  (span2_start,idx), (-1,idx), colors.HexColor('#bbbbbb'))
        elif status == 'only2':
            ts.add('BACKGROUND', (0,idx), (-1,idx), C_B_BG)
            ts.add('TEXTCOLOR',  (2,idx), (span1_end,idx), colors.HexColor('#bbbbbb'))
        elif idx % 2 == 0:
            ts.add('BACKGROUND', (0,idx), (-1,idx), C_ROW_ALT)

        if parado1:
            ts.add('BACKGROUND', (2,idx), (2,idx), C_PARADO)
            if show_s365:
                ts.add('BACKGROUND', (s365_1_col,idx), (s365_1_col,idx), C_PARADO)
        if parado2:
            ts.add('BACKGROUND', (span2_start,idx), (span2_start,idx), C_PARADO)
            if show_s365:
                ts.add('BACKGROUND', (s365_2_col,idx), (s365_2_col,idx), C_PARADO)

        if pedido1 > 0:
            ts.add('BACKGROUND', (pedido1_col,idx), (pedido1_col,idx), C_PEDIDO)
        if pedido2 > 0:
            ts.add('BACKGROUND', (pedido2_col,idx), (pedido2_col,idx), C_PEDIDO)

    table.setStyle(ts)

    # ── Leyenda ───────────────────────────────────────────────────────────────
    legend_items = [
        (C_Z_BG,    C_Z_HDR,                    f'Solo en {name1}'),
        (C_B_BG,    C_B_HDR,                    f'Solo en {name2}'),
        (C_WARNING, colors.HexColor('#b8860b'),  'Revisar'),
        (C_PEDIDO,  colors.HexColor('#2e7d32'),  'Pedido sugerido'),
    ]
    if show_s365:
        legend_items.append((C_PARADO, colors.HexColor('#e65100'),
                             'Stock parado (+365d) · celda naranja = S.365'))

    legend_data = [[]]
    for bg, fg, label in legend_items:
        sw = Table([['']], colWidths=[0.35*cm], rowHeights=[0.25*cm])
        sw.setStyle(TableStyle([('BACKGROUND',(0,0),(0,0),bg),('BOX',(0,0),(0,0),0.5,fg)]))
        legend_data[0].append(sw)
        legend_data[0].append(Paragraph(
            f'<font name="Helvetica" size="6.5" color="#555555">{label}</font>',
            ParagraphStyle('leg', leading=8)))

    legend_cw = []
    for _ in legend_items:
        legend_cw += [0.45*cm, 3.8*cm]
    legend_table = Table(legend_data, colWidths=legend_cw)
    legend_table.setStyle(TableStyle([
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('LEFTPADDING',(0,0),(-1,-1),2),
        ('RIGHTPADDING',(0,0),(-1,-1),4),
    ]))

    # ── Título ────────────────────────────────────────────────────────────────
    title_data = [[Paragraph(title_text, title_style), Paragraph(stats_text, sub_style)]]
    title_table = Table(title_data, colWidths=[9.5*cm, 18.3*cm])
    title_table.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),C_HEADER),
        ('VALIGN',(0,0),(-1,0),'MIDDLE'),
        ('TOPPADDING',(0,0),(-1,0),8),('BOTTOMPADDING',(0,0),(-1,0),8),
        ('LEFTPADDING',(0,0),(-1,0),10),('RIGHTPADDING',(0,0),(-1,0),10),
    ]))

    elements = [title_table, Spacer(1,0.2*cm), legend_table, Spacer(1,0.15*cm), table]

    # ── Tabla logística (solo si hay informe de situación) ────────────────────
    if show_s365:
        log_elements = _build_logistics_table(
            results, name1, name2, has_situation1, has_situation2, cell_style)
        if log_elements:
            elements += log_elements

    doc.build(elements)


def _parse_caducidad(cad_str):
    """Convierte 'MM/YYYY' a datetime. Devuelve None si no puede."""
    if not cad_str:
        return None
    try:
        from datetime import datetime as _dt
        return _dt.strptime(cad_str, '%m/%Y')
    except ValueError:
        return None


def _build_logistics_table(results, name1, name2,
                            has_sit1, has_sit2, cell_style):
    """
    Genera la sección de análisis logístico al final del PDF.
    Detecta 3 casos:
      - Traspaso: parado en A (stock>0) y stock=0 en B
      - Exceso compartido: parado en ambas
      - Caducidad próxima: parado + caduca en ≤6 meses
    """
    from datetime import datetime as _dt
    from reportlab.platypus import KeepTogether

    now = _dt.today()
    C_LOG_HDR   = colors.HexColor('#2c3e50')
    C_TRASPASO  = colors.HexColor('#e8f5e9')   # verde suave
    C_EXCESO    = colors.HexColor('#fff3e0')   # naranja suave
    C_CADUCIDAD = colors.HexColor('#fce4ec')   # rojo suave

    casos_traspaso  = []
    casos_exceso    = []
    casos_caducidad = []

    for r in results:
        p1 = r.get('parado1', False)
        p2 = r.get('parado2', False)
        s1 = r.get('stock1', '—')
        s2 = r.get('stock2', '—')
        cad1 = _parse_caducidad(r.get('caducidad1',''))
        cad2 = _parse_caducidad(r.get('caducidad2',''))

        # ── Caducidad próxima (≤6 meses) ─────────────────────────────────
        for parado, cad, farm, stock_val, s365_key in [
            (p1, cad1, name1, s1, 's365_1'),
            (p2, cad2, name2, s2, 's365_2'),
        ]:
            if parado and cad:
                diff_months = (cad.year - now.year)*12 + (cad.month - now.month)
                if 0 <= diff_months <= 6:
                    casos_caducidad.append({
                        'code': r['code'], 'description': r['description'],
                        'farmacia': farm, 'stock': r.get(s365_key, stock_val),
                        'caducidad': cad.strftime('%m/%Y'),
                        'meses': diff_months,
                    })

        # ── Exceso compartido ─────────────────────────────────────────────
        if p1 and p2:
            casos_exceso.append({
                'code': r['code'], 'description': r['description'],
                'stock1': r.get('s365_1', s1), 'stock2': r.get('s365_2', s2),
            })
            continue  # no añadir también a traspaso

        # ── Traspaso ──────────────────────────────────────────────────────
        def _stock_zero(v):
            try:
                return int(str(v)) == 0
            except (ValueError, TypeError):
                return v == '—'

        if p1 and _stock_zero(s2):
            casos_traspaso.append({
                'code': r['code'], 'description': r['description'],
                'origen': name1, 'destino': name2,
                'stock_origen': r.get('s365_1', s1),
            })
        elif p2 and _stock_zero(s1):
            casos_traspaso.append({
                'code': r['code'], 'description': r['description'],
                'origen': name2, 'destino': name1,
                'stock_origen': r.get('s365_2', s2),
            })

    if not casos_traspaso and not casos_exceso and not casos_caducidad:
        return []

    def log_hdr(text, color=colors.white, size=7, bg=None):
        return Paragraph(
            f'<font name="Helvetica-Bold" size="{size}" color="{"white" if color==colors.white else "#1c1a17"}">{text}</font>',
            ParagraphStyle('lh', leading=size+2, alignment=1))

    def log_cell(text, size=6.5):
        return Paragraph(
            f'<font name="Helvetica" size="{size}">{text}</font>',
            ParagraphStyle('lc', leading=size+1.5, textColor=colors.HexColor('#1c1a17')))

    section_title_style = ParagraphStyle('sct',
        fontName='Helvetica-Bold', fontSize=9, leading=11,
        textColor=colors.HexColor('#2c3e50'), spaceBefore=12, spaceAfter=4)

    elements = [
        Spacer(1, 0.5*cm),
        Paragraph('Análisis logístico · Stock parado', section_title_style),
    ]

    # ── Tabla Traspaso ────────────────────────────────────────────────────────
    if casos_traspaso:
        elements.append(Paragraph(
            '<font name="Helvetica-Bold" size="7.5" color="#2e7d32">🔄 Posible traspaso — stock parado en origen, sin stock en destino</font>',
            ParagraphStyle('sh', leading=10, spaceBefore=6, spaceAfter=2)))

        t_data = [[
            log_hdr('Código'), log_hdr('Descripción'),
            log_hdr('Origen'), log_hdr('Destino'), log_hdr('Stock parado'),
        ]]
        for c in casos_traspaso:
            t_data.append([
                log_cell(c['code']), log_cell(c['description']),
                log_cell(c['origen']), log_cell(c['destino']),
                log_cell(str(c['stock_origen'])),
            ])
        t = Table(t_data, colWidths=[1.8*cm, 9*cm, 3*cm, 3*cm, 2.5*cm])
        t.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0), colors.HexColor('#2e7d32')),
            ('FONTSIZE',(0,0),(-1,0), 7),
            ('ALIGN',(0,0),(-1,-1),'CENTER'),
            ('ALIGN',(1,1),(1,-1),'LEFT'),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[C_TRASPASO, colors.white]),
            ('GRID',(0,0),(-1,-1), 0.25, colors.HexColor('#c8e6c9')),
            ('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3),
            ('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4),
        ]))
        elements.append(t)

    # ── Tabla Exceso compartido ───────────────────────────────────────────────
    if casos_exceso:
        elements.append(Paragraph(
            f'<font name="Helvetica-Bold" size="7.5" color="#e65100">⚠️ Exceso compartido — stock parado en ambas farmacias</font>',
            ParagraphStyle('sh', leading=10, spaceBefore=8, spaceAfter=2)))

        e_data = [[
            log_hdr('Código'), log_hdr('Descripción'),
            log_hdr(f'S.365 {name1}'), log_hdr(f'S.365 {name2}'),
        ]]
        for c in casos_exceso:
            e_data.append([
                log_cell(c['code']), log_cell(c['description']),
                log_cell(str(c['stock1'])), log_cell(str(c['stock2'])),
            ])
        t = Table(e_data, colWidths=[1.8*cm, 10*cm, 3*cm, 3*cm])
        t.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0), colors.HexColor('#e65100')),
            ('FONTSIZE',(0,0),(-1,0), 7),
            ('ALIGN',(0,0),(-1,-1),'CENTER'),
            ('ALIGN',(1,1),(1,-1),'LEFT'),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[C_EXCESO, colors.white]),
            ('GRID',(0,0),(-1,-1), 0.25, colors.HexColor('#ffe0b2')),
            ('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3),
            ('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4),
        ]))
        elements.append(t)

    # ── Tabla Caducidad próxima ───────────────────────────────────────────────
    if casos_caducidad:
        casos_caducidad.sort(key=lambda x: x['meses'])
        elements.append(Paragraph(
            '<font name="Helvetica-Bold" size="7.5" color="#c62828">🕐 Caducidad próxima — stock parado con caducidad en ≤6 meses</font>',
            ParagraphStyle('sh', leading=10, spaceBefore=8, spaceAfter=2)))

        c_data = [[
            log_hdr('Código'), log_hdr('Descripción'),
            log_hdr('Farmacia'), log_hdr('S.365'), log_hdr('Caduca'), log_hdr('Meses restantes'),
        ]]
        for c in casos_caducidad:
            c_data.append([
                log_cell(c['code']), log_cell(c['description']),
                log_cell(c['farmacia']), log_cell(str(c['stock'])),
                log_cell(c['caducidad']),
                log_cell(str(c['meses']) if c['meses'] > 0 else '¡Este mes!'),
            ])
        t = Table(c_data, colWidths=[1.8*cm, 8.5*cm, 2.5*cm, 1.8*cm, 2*cm, 2.7*cm])
        t.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0), colors.HexColor('#c62828')),
            ('FONTSIZE',(0,0),(-1,0), 7),
            ('ALIGN',(0,0),(-1,-1),'CENTER'),
            ('ALIGN',(1,1),(1,-1),'LEFT'),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[C_CADUCIDAD, colors.white]),
            ('GRID',(0,0),(-1,-1), 0.25, colors.HexColor('#f8bbd0')),
            ('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3),
            ('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4),
        ]))
        elements.append(t)

    return elements


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)