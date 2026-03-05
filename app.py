from flask import Flask, request, render_template, send_file, session, redirect, url_for
import os, tempfile
from datetime import datetime
from pdf_parser import extract_products, compare_products, detect_lab

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm

app = Flask(__name__)
app.secret_key = 'farmacias_barris_zarzuelo_2026'  # cambia esto por algo único tuyo

# ── Configuración ──────────────────────────────────────────────────────────────
PASSWORD             = "farmacias2026"       # ← cambia esta contraseña
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
    name1 = request.form.get('name1', 'Farmacia 1').strip()
    name2 = request.form.get('name2', 'Farmacia 2').strip()

    if not file1 or not file2:
        return 'Debes subir los dos PDFs', 400

    # Verificar que son PDFs reales
    for f, nombre in [(file1, name1), (file2, name2)]:
        header = f.read(4)
        f.seek(0)
        if header != b'%PDF':
            return f'El archivo de {nombre} no es un PDF válido', 400

    tmp1 = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
    tmp2 = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
    file1.save(tmp1.name)
    file2.save(tmp2.name)

    try:
        # Detectar laboratorio de cada PDF
        lab1 = detect_lab(tmp1.name)
        lab2 = detect_lab(tmp2.name)

        # Validar que son del mismo laboratorio
        if lab1 != lab2:
            return render_template('error.html', lab1=lab1, lab2=lab2), 400

        products1 = extract_products(tmp1.name)
        products2 = extract_products(tmp2.name)
        results   = compare_products(products1, products2, name1, name2)

        lab_slug = (lab1.replace(' ', '_').replace('-', '_')
                       .replace("'", '').replace('é','e')
                       .replace('à','a').replace('ó','o'))
        download_name = f'comparativa_{lab_slug}.pdf'

        output = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        generate_pdf(results, output.name, name1, name2,
                     len(products1), len(products2), lab1)

        return send_file(output.name, as_attachment=True,
                         download_name=download_name,
                         mimetype='application/pdf')
    finally:
        os.unlink(tmp1.name)
        os.unlink(tmp2.name)

@app.errorhandler(413)
def too_large(e):
    return f'El PDF es demasiado grande. Máximo {MAX_PDF_MB}MB por archivo.', 413


# ── Generación del PDF ─────────────────────────────────────────────────────────
def generate_pdf(results, output_path, name1, name2, count1, count2, lab_name=''):
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

    yr_cur  = results[0]['year_current'] if results else 2026
    yr_prev = results[0]['year_prev']    if results else 2025

    today   = datetime.today().strftime('%d/%m/%Y')
    n_both  = sum(1 for r in results if r['status'] == 'both')
    n_only1 = sum(1 for r in results if r['status'] == 'only1')
    n_only2 = sum(1 for r in results if r['status'] == 'only2')

    lab_part   = f"  ·  {lab_name}" if lab_name else ""
    title_text = f"Comparativa de Stock{lab_part}  ·  {name1} vs {name2}  ·  Generado el {today}"
    stats_text = (
        f"{name1}: {count1} prod.  ·  {name2}: {count2} prod.  ·  "
        f"Total: {len(results)}  ·  Ambas: {n_both}  ·  "
        f"Solo {name1}: {n_only1}  ·  Solo {name2}: {n_only2}"
    )

    def hdr(text, size=7.5, bold=True, align=1):
        fn = 'Helvetica-Bold' if bold else 'Helvetica'
        return Paragraph(
            f'<font name="{fn}" size="{size}">{text}</font>',
            ParagraphStyle('_h', leading=size + 2,
                           alignment=align, textColor=colors.white))

    row_farmacia = [
        '', '',
        hdr(f'● {name1}', size=8), '', '', '',
        hdr(f'● {name2}', size=8), '', '', '',
    ]

    row_cols = [
        hdr('Código', size=7), hdr('Descripción', size=7),
        hdr('Stock', size=7), hdr('S.min', size=7),
        hdr(f'V.{yr_cur}', size=7), hdr(f'V.{yr_prev}', size=7),
        hdr('Stock', size=7), hdr('S.min', size=7),
        hdr(f'V.{yr_cur}', size=7), hdr(f'V.{yr_prev}', size=7),
    ]

    def _fmt(v):
        if v in ('—', '⚠️') or v is None: return str(v) if v else '⚠️'
        return str(v)

    data = [row_farmacia, row_cols]
    row_meta = []

    for r in results:
        idx = len(data)
        desc_text = r['description']
        if len(desc_text) > 52:
            desc_text = desc_text[:50] + '…'
        warn_flag = ' ⚠' if r['needs_review'] else ''
        desc_para = Paragraph(desc_text + warn_flag, cell_style)

        data.append([
            r['code'], desc_para,
            _fmt(r['stock1']),  _fmt(r['smin1']),
            _fmt(r['total1']),  _fmt(r['total1_prev']),
            _fmt(r['stock2']),  _fmt(r['smin2']),
            _fmt(r['total2']),  _fmt(r['total2_prev']),
        ])
        row_meta.append((idx, r['status'], r['needs_review']))

    col_widths = [
        1.8*cm, 6.2*cm,
        1.3*cm, 1.3*cm, 1.4*cm, 1.4*cm,
        1.3*cm, 1.3*cm, 1.4*cm, 1.4*cm,
    ]

    table = Table(data, colWidths=col_widths, repeatRows=2)

    ts = TableStyle([
        ('BACKGROUND',    (0, 0), (1, 0),  C_HEADER),
        ('BACKGROUND',    (2, 0), (5, 0),  C_Z_HDR),
        ('BACKGROUND',    (6, 0), (9, 0),  C_B_HDR),
        ('SPAN',          (2, 0), (5, 0)),
        ('SPAN',          (6, 0), (9, 0)),
        ('ALIGN',         (0, 0), (-1, 0), 'CENTER'),
        ('VALIGN',        (0, 0), (-1, 0), 'MIDDLE'),
        ('ROWHEIGHT',     (0, 0), (0, 0),  16),
        ('BACKGROUND',    (0, 1), (1, 1),  C_HEADER),
        ('BACKGROUND',    (2, 1), (5, 1),  C_Z_HDR),
        ('BACKGROUND',    (6, 1), (9, 1),  C_B_HDR),
        ('ALIGN',         (0, 1), (-1, 1), 'CENTER'),
        ('VALIGN',        (0, 1), (-1, 1), 'MIDDLE'),
        ('ROWHEIGHT',     (0, 1), (0, 1),  13),
        ('FONTNAME',      (0, 2), (-1, -1), 'Helvetica'),
        ('FONTSIZE',      (0, 2), (-1, -1), 7),
        ('ALIGN',         (0, 2), (-1, -1), 'CENTER'),
        ('ALIGN',         (1, 2), (1, -1),  'LEFT'),
        ('VALIGN',        (0, 2), (-1, -1), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING',   (0, 0), (-1, -1), 4),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 4),
        ('GRID',          (0, 0), (-1, -1), 0.25, C_GRID),
        ('LINEBELOW',     (0, 0), (-1, 0),  0.8,  colors.white),
        ('LINEBELOW',     (0, 1), (-1, 1),  0.8,  colors.white),
        ('LINEAFTER',     (1, 0), (1, -1),  0.8, C_GRID),
        ('LINEAFTER',     (5, 0), (5, -1),  1.2, C_HEADER),
    ])

    for idx, status, needs_review in row_meta:
        if needs_review:
            ts.add('BACKGROUND', (0, idx), (-1, idx), C_WARNING)
        elif status == 'only1':
            ts.add('BACKGROUND', (0, idx), (-1, idx), C_Z_BG)
            ts.add('TEXTCOLOR',  (6, idx), (9, idx),  colors.HexColor('#bbbbbb'))
        elif status == 'only2':
            ts.add('BACKGROUND', (0, idx), (-1, idx), C_B_BG)
            ts.add('TEXTCOLOR',  (2, idx), (5, idx),  colors.HexColor('#bbbbbb'))
        elif idx % 2 == 0:
            ts.add('BACKGROUND', (0, idx), (-1, idx), C_ROW_ALT)

    table.setStyle(ts)

    title_data = [[
        Paragraph(title_text, title_style),
        Paragraph(stats_text, sub_style),
    ]]
    title_table = Table(title_data, colWidths=[9.5*cm, 18.3*cm])
    title_table.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, 0), C_HEADER),
        ('VALIGN',        (0, 0), (-1, 0), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, 0), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('LEFTPADDING',   (0, 0), (-1, 0), 10),
        ('RIGHTPADDING',  (0, 0), (-1, 0), 10),
    ]))

    elements = [title_table, Spacer(1, 0.3*cm), table]
    doc.build(elements)


if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)