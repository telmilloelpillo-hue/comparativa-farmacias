"""Regression checks for pharmacy tables, including the visually reviewed originals.

Synthetic PDFs are generated in pytest's temporary directory and exercise the
public parser without depending on an installed PDF renderer or private files.
The four customer originals stay outside the repository. Set
PHARMACY_PDF_FIXTURE_DIR to their directory to run those optional regressions.
"""

import os
from pathlib import Path
from contextlib import nullcontext
from types import SimpleNamespace
import sys
import unicodedata

import pytest
from reportlab.lib import colors
from reportlab.pdfgen import canvas

from pdf_parser import calculate_pedido, compare_products, detect_pdf_header, extract_products, extract_situation


MONTHS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


@pytest.fixture
def mock_vision_renderer(monkeypatch):
    # Isolate response validation from optional rendering and external APIs.
    # The model call below is also mocked; no image or request leaves the test.
    pixmap = SimpleNamespace(tobytes=lambda image_type: b"mock-image")
    page = SimpleNamespace(rect=SimpleNamespace(height=800), get_pixmap=lambda **kwargs: pixmap)
    renderer = SimpleNamespace(open=lambda path: nullcontext({0: page}),
                               Rect=lambda *args: args, Matrix=lambda *args: args, csRGB="RGB")
    monkeypatch.setitem(sys.modules, "fitz", renderer)


def _number(value):
    return "" if value is None else str(value)


def _document_header(pdf, width, height, kind):
    pdf.setFillColor(colors.black)
    pdf.setFont("Helvetica", 12)
    pdf.drawString(20, height - 30, "Estadísticas de ventas" if kind == "ventas" else "Informe de situación")
    pdf.setFont("Helvetica", 10)
    pdf.drawRightString(width - 20, height - 30, "FARMACIA DE PRUEBAS")
    pdf.drawRightString(width - 20, height - 48, "lunes, 4 de mayo de 2026")


def _sales_pdf(path, records, *, width=1000, font_size=10, alignment="first", backgrounds=True, header_labels=None):
    height = 800
    pdf = canvas.Canvas(str(path), pagesize=(width, height))
    _document_header(pdf, width, height, "ventas")
    code_x, desc_x = width * .03, width * .09
    numeric_x = [width * .36, width * .41, width * .46, width * .53]
    numeric_x += [width * (.59 + .034 * i) for i in range(12)]
    pdf.setFillColor(colors.HexColor("#cc5555"))
    pdf.rect(20, height - 107, width - 40, 22, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont("Helvetica-Bold", font_size)
    pdf.drawString(code_x, height - 100, "Código")
    pdf.drawString(desc_x, height - 100, "Descripción")
    for right, label in zip(numeric_x, header_labels or ["Stock", "S.min", "Año", "Total"] + MONTHS):
        pdf.drawRightString(right, height - 100, label)

    top, leading = 124, font_size + 3
    for index, record in enumerate(records):
        lines = record["lines"]
        code_index = 0 if alignment == "first" else len(lines) - 1
        previous_index = code_index + 1
        line_count = max(len(lines), previous_index + 1)
        if backgrounds:
            pdf.setFillColor(colors.HexColor("#dddddd" if index % 2 == 0 else "#ffffff"))
            pdf.rect(20, height - top - (line_count - 1) * leading - 5, width - 40, line_count * leading, fill=1, stroke=0)
        pdf.setFillColor(colors.black)
        pdf.setFont("Helvetica", font_size)
        for line_index, line in enumerate(lines):
            pdf.drawString(desc_x, height - top - line_index * leading, line)
        code_y = height - top - code_index * leading
        pdf.drawString(code_x, code_y, record["code"])
        current = record.get("current", [0] * 12)
        previous = record.get("previous", [0] * 12)
        current_total = record.get("current_total", sum(current) if None not in current else None)
        previous_total = record.get("previous_total", sum(previous) if None not in previous else None)
        for baseline, numbers in [
            (code_y, [record.get("stock", 2), record.get("smin", 1), 2026, current_total] + current),
            (height - top - previous_index * leading, [None, None, 2025, previous_total] + previous),
        ]:
            for right, number in zip(numeric_x, numbers):
                pdf.drawRightString(right, baseline, _number(number))
        top += line_count * leading + 3

    pdf.setFillColor(colors.HexColor("#cc5555"))
    pdf.rect(20, height - top - 14, width - 40, 20, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.drawString(desc_x, height - top - 7, "Totales")
    pdf.setFillColor(colors.black)
    pdf.drawString(desc_x, height - top - 40, "Criterios de selección:")
    pdf.drawString(desc_x, height - top - 56, "Laboratorio: 24")
    pdf.drawString(desc_x, height - top - 72, "Agrupar por: Producto")
    pdf.save()
    return path


def _situation_pdf(path, pages, *, width=1000, font_size=10, alignment="first", backgrounds=True):
    height = 800
    pdf = canvas.Canvas(str(path), pagesize=(width, height))
    xs = [width * ratio for ratio in (.03, .08, .15, .56, .64, .73, .84)]
    for records in pages:
        _document_header(pdf, width, height, "situacion")
        pdf.setFillColor(colors.HexColor("#cc5555"))
        pdf.rect(20, height - 107, width - 40, 22, fill=1, stroke=0)
        pdf.setFillColor(colors.white)
        pdf.setFont("Helvetica-Bold", font_size)
        for x, label in zip(xs, ["Alm.", "Código", "Descripción", "Stock", "PVP", "Importe PVP", "Caducidad"]):
            pdf.drawString(x, height - 100, label)
        top, leading = 124, font_size + 3
        for index, record in enumerate(records):
            lines = record["lines"]
            if backgrounds:
                pdf.setFillColor(colors.HexColor("#dddddd" if index % 2 == 0 else "#ffffff"))
                pdf.rect(20, height - top - (len(lines) - 1) * leading - 5, width - 40, len(lines) * leading, fill=1, stroke=0)
            pdf.setFillColor(colors.black)
            pdf.setFont("Helvetica", font_size)
            for line_index, line in enumerate(lines):
                pdf.drawString(xs[2], height - top - line_index * leading, line)
            baseline = height - top - (len(lines) - 1 if alignment == "last" else 0) * leading
            for x, value in zip(xs, ["1", record["code"], None, record.get("stock", 2), "2,50", "5,00", record.get("expiry", "07/2027")]):
                if value is not None:
                    pdf.drawString(x, baseline, str(value))
            top += len(lines) * leading + 3
        pdf.setFillColor(colors.HexColor("#cc5555"))
        pdf.rect(20, height - top - 14, width - 40, 20, fill=1, stroke=0)
        pdf.setFillColor(colors.white)
        pdf.drawString(xs[2], height - top - 7, "Totales")
        pdf.setFillColor(colors.black)
        pdf.drawString(xs[2], height - top - 40, "Criterios de selección:")
        pdf.drawString(xs[2], height - top - 56, "Stock actual: >0")
        pdf.drawString(xs[2], height - top - 72, "Artículos sin movimientos desde hace: 365")
        pdf.showPage()
    pdf.save()
    return path


@pytest.mark.parametrize("width,font_size", [(842, 8), (1000, 10), (1200, 12)])
@pytest.mark.parametrize("alignment", ["first", "last"])
@pytest.mark.parametrize("backgrounds", [True, False])
def test_sales_description_stays_with_its_product_across_layouts(tmp_path, width, font_size, alignment, backgrounds):
    records = [
        {"code": "195765", "lines": ["AGUA DESTILADA INTERAPOTHEK", "1 ENVASE 1000 ML"], "stock": 0, "smin": 0, "current": [0, 0, 1] + [0] * 9},
        {"code": "195766", "lines": ["AGUA DESTILADA INTERAPOTHEK", "1 ENVASE 5000 ML"], "stock": 1, "smin": 1, "current": [0, 1, 0, 1] + [0] * 8, "previous": [0] * 6 + [3, 6, 0, 1, 0, 0]},
        {"code": "185913", "lines": ["ALCACHOFA INTERAPOTHEK IA", "60 CAPSULAS"]},
        {"code": "215220", "lines": ["CEPILLO MINI BIODEGRADABLE", "INTERAPOTHEK 1 UNIDAD", "COLOR CORAL"]},
    ]
    products = extract_products(_sales_pdf(tmp_path / "sales.pdf", records, width=width, font_size=font_size, alignment=alignment, backgrounds=backgrounds))
    assert set(products) == {record["code"] for record in records}
    for record in records:
        product = products[record["code"]]
        assert product["description"] == " ".join(record["lines"])
        assert product["stock"] == record.get("stock", 2)
        assert product["smin"] == record.get("smin", 1)
    assert products["195766"]["total_current"] == 2
    assert products["195766"]["total_prev"] == 10


@pytest.mark.parametrize("width,font_size", [(842, 8), (1000, 10), (1200, 12)])
@pytest.mark.parametrize("alignment", ["first", "last"])
@pytest.mark.parametrize("backgrounds", [True, False])
def test_situation_description_excludes_neighbor_header_and_footer(tmp_path, width, font_size, alignment, backgrounds):
    pages = [
        [
            {"code": "208775", "lines": ["CEPILLO DESENREDANTE BIODEGRADABLE", "INTERAPOTHEK 1 UNIDAD", "COLOR NARANJA"], "stock": 6},
            {"code": "217849", "lines": ["CONTORNO OJOS BIO-PEPTIDOS", "INTERAPOTHEK 1 ENVASE 15 ML"], "stock": 2},
        ],
        [{"code": "212736", "lines": ["PROTECTOR LABIAL MANTECA DE KARITE", "SPF 50+ 1 ENVASE 5 G"], "stock": 2}],
    ]
    products = extract_situation(_situation_pdf(tmp_path / "situation.pdf", pages, width=width, font_size=font_size, alignment=alignment, backgrounds=backgrounds))
    assert set(products) == {"208775", "217849", "212736"}
    for page in pages:
        for record in page:
            assert products[record["code"]]["description"] == " ".join(record["lines"])
            assert products[record["code"]]["stock"] == record["stock"]
            assert products[record["code"]]["caducidad"] == "07/2027"


def test_sales_preserves_returns_and_legitimate_large_quantities(tmp_path):
    records = [
        {"code": "215037", "lines": ["LEVADURA ROJA DE ARROZ", "30 CAPSULAS"], "stock": -1, "current": [-1, 0, 0, 5] + [0] * 8},
        {"code": "123456", "lines": ["PRODUCTO CON VENTAS DE MIL UNIDADES"], "stock": 12345, "smin": 1000, "current": [1200, 0, 0, 0] + [0] * 8, "previous": [0, 1001] + [0] * 10},
    ]
    products = extract_products(_sales_pdf(tmp_path / "numbers.pdf", records))
    assert products["215037"]["stock"] == -1
    assert products["215037"]["months_current"] == [-1, 0, 0, 5] + [0] * 8
    assert products["215037"]["total_current"] == 4
    assert products["123456"]["stock"] == 12345
    assert products["123456"]["smin"] == 1000
    assert products["123456"]["total_current"] == 1200
    assert products["123456"]["total_prev"] == 1001


def test_even_two_unit_total_difference_requires_review_and_keeps_source_total(tmp_path):
    record = {"code": "369884", "lines": ["PRODUCTO CON TOTAL A REVISAR"], "current": [0, 0, 0, 6] + [0] * 8, "current_total": 4}
    product = extract_products(_sales_pdf(tmp_path / "totals.pdf", [record]))["369884"]
    assert product["months_current"][3] == 6
    assert product["total_pdf_current"] == 4
    assert product["total_current"] == 4
    assert product["needs_review"] is True
    assert any(warning.startswith("total_discrepancia:") for warning in product["warnings"])


def test_missing_values_remain_unknown_instead_of_becoming_zero(tmp_path):
    record = {"code": "123456", "lines": ["PRODUCTO CON CELDAS VACIAS"], "stock": None, "smin": None, "current": [None] + [0] * 11, "current_total": None}
    product = extract_products(_sales_pdf(tmp_path / "missing.pdf", [record]))["123456"]
    assert product["stock"] is None
    assert product["smin"] is None
    assert product["months_current"][0] is None
    assert product["total_current"] is None
    assert product["needs_review"] is True
    assert any(warning.startswith("campo_ausente:") for warning in product["warnings"])


def test_unrecognized_column_layout_requires_review(tmp_path):
    record = {"code": "123456", "lines": ["PRODUCTO DE FORMATO DESCONOCIDO"]}
    path = _sales_pdf(tmp_path / "unknown-layout.pdf", [record],
                      header_labels=["Disponible", "Reserva", "Ejercicio", "Acumulado"] + [f"M{i}" for i in range(1, 13)])
    product = extract_products(path)["123456"]
    assert product["needs_review"] is True
    assert any(warning.startswith("columnas_no_reconocidas") for warning in product["warnings"])


@pytest.mark.parametrize("kind", ["ventas", "situacion"])
def test_extracted_products_keep_document_page_and_bounding_box(tmp_path, kind):
    record = {"code": "123456", "lines": ["PRODUCTO CON ORIGEN VERIFICABLE"]}
    path = tmp_path / f"provenance-{kind}.pdf"
    if kind == "ventas":
        product = extract_products(_sales_pdf(path, [record]))["123456"]
    else:
        product = extract_situation(_situation_pdf(path, [[record]]))["123456"]
    sources = product["sources"]
    assert sources
    assert product["description_source"] in sources
    source = product["description_source"]
    assert Path(source["file"]).name == path.name
    assert source["page"] == 1
    assert source["document_type"] == ("sales" if kind == "ventas" else "situation")
    assert source["description"] == product["description"]
    x0, top, x1, bottom = source["bbox"]
    assert 0 <= x0 < x1 <= 1000
    assert 0 <= top < bottom <= 800


def test_duplicate_code_does_not_overwrite_a_trusted_description(tmp_path):
    records = [
        {"code": "208627", "lines": ["CHAMPU INTERAPOTHEK", "ACEITE DE ARGÁN 500 ML"], "stock": 2},
        {"code": "208627", "lines": ["8"], "stock": 2},
    ]
    product = extract_products(_sales_pdf(tmp_path / "duplicate.pdf", records))["208627"]
    assert product["description"] == "CHAMPU INTERAPOTHEK ACEITE DE ARGÁN 500 ML"
    assert product["needs_review"] is True
    assert any(warning.startswith("codigo_duplicado:") for warning in product["warnings"])


def test_comparison_prefers_a_trusted_description_over_a_longer_ambiguous_one():
    fields = {"stock": 2, "smin": 1, "year_current": 2026, "year_prev": 2025,
              "total_current": 1, "total_prev": 1,
              "months_current": [1] + [0] * 11, "months_prev": [1] + [0] * 11}
    ambiguous = {**fields, "description": "PRODUCTO CORRECTO DESCRIPCION DEL PRODUCTO VECINO",
                 "warnings": ["limites_fila_inciertos"], "needs_review": True}
    trusted = {**fields, "description": "PRODUCTO CORRECTO", "warnings": [], "needs_review": False}
    row = compare_products({"123456": ambiguous}, {"123456": trusted})[0]
    assert row["description"] == "PRODUCTO CORRECTO"
    assert row["needs_review"] is True


def test_comparison_keeps_review_warning_for_a_situation_only_product(tmp_path):
    record = {"code": "211836", "lines": ["07/2026"]}
    situation = extract_situation(_situation_pdf(tmp_path / "source-error.pdf", [[record]]))
    row = compare_products({}, {}, situation1=situation)[0]
    assert row["description"] == "07/2026"
    assert row["needs_review"] is True
    assert any("descripcion_sospechosa" in warning for warning in row["warnings"])


def test_name_review_keeps_verified_order_but_numerical_or_geometry_review_blocks_it(tmp_path):
    record = {"code": "123456", "lines": ["8"], "stock": 1,
              "current": [4] + [0] * 11, "previous": [4] + [0] * 11}
    products = extract_products(_sales_pdf(tmp_path / "verified-numbers.pdf", [record]))
    product = products["123456"]
    assert product["needs_review"] is True
    assert "descripcion_sospechosa" in product["warnings"]
    assert calculate_pedido(product) == 1
    row = compare_products(products, {})[0]
    assert row["needs_review"] is True
    assert row["pedido1"] == 1
    assert row["pedido_no_calculable1"] is False

    # The same known values become unsafe once their row or totals are disputed.
    for uncertainty in ("total_discrepancia:pdf=4,calc=6", "limites_fila_inciertos"):
        disputed = {**product, "warnings": product["warnings"] + [uncertainty]}
        assert calculate_pedido(disputed) is None
        disputed_row = compare_products({"123456": disputed}, {})[0]
        assert disputed_row["pedido1"] is None
        assert disputed_row["pedido_no_calculable1"] is True


@pytest.mark.parametrize("pharmacy_index", [1, 2])
def test_unknown_situation_stock_blocks_an_otherwise_verified_sales_order(tmp_path, pharmacy_index):
    record = {"code": "123456", "lines": ["PRODUCTO VERIFICADO"], "stock": 1,
              "current": [4] + [0] * 11, "previous": [4] + [0] * 11}
    sales = extract_products(_sales_pdf(tmp_path / "valid-sales.pdf", [record]))
    situation = extract_situation(_situation_pdf(tmp_path / "missing-situation-stock.pdf", [[{**record, "stock": None}]]))
    assert calculate_pedido(sales["123456"]) == 1
    assert situation["123456"]["stock"] is None
    assert "campo_ausente:stock" in situation["123456"]["warnings"]

    if pharmacy_index == 1:
        row = compare_products(sales, {}, situation1=situation)[0]
    else:
        row = compare_products({}, sales, situation2=situation)[0]
    assert row[f"stock{pharmacy_index}"] == 1
    assert row[f"s365_{pharmacy_index}"] is None
    assert row[f"pedido_no_calculable{pharmacy_index}"] is True
    assert row[f"pedido{pharmacy_index}"] is None
    assert row["needs_review"] is True


def test_product_starting_with_total_is_preserved_before_the_real_totals_footer(tmp_path):
    records = [
        {"code": "123456", "lines": ["TOTAL CARE INTERAPOTHEK", "CEPILLO DENTAL 1 UNIDAD"], "stock": 3},
        {"code": "234567", "lines": ["PRODUCTO POSTERIOR AL TOTAL CARE"], "stock": 2},
    ]
    paths = [tmp_path / "total-name-sales.pdf", tmp_path / "total-name-situation.pdf"]
    extracted = [extract_products(_sales_pdf(paths[0], records, alignment="last")),
                 extract_situation(_situation_pdf(paths[1], [records], alignment="last"))]
    for products in extracted:
        assert set(products) == {"123456", "234567"}
        assert products["123456"]["description"] == "TOTAL CARE INTERAPOTHEK CEPILLO DENTAL 1 UNIDAD"
        assert "descripcion_sospechosa" not in products["123456"]["warnings"]
        assert products["234567"]["description"] == "PRODUCTO POSTERIOR AL TOTAL CARE"
        assert products["123456"]["stock"] == 3
        assert all("Criterios" not in product["description"] and "Totales" not in product["description"]
                   for product in products.values())


@pytest.mark.parametrize("kind,original_description", [("ventas", "8"), ("situacion", "07/2026")])
def test_vision_cannot_invent_a_name_missing_from_the_original(tmp_path, monkeypatch, mock_vision_renderer, kind, original_description):
    code = "123456"
    calls = []

    def invented_name(*args, **kwargs):
        calls.append(True)
        return {code: {"code": code, "description": "NOMBRE INVENTADO", "stock": 999, "smin": 999,
                       "months_current": [0] * 12, "months_prev": [0] * 12,
                       "total_current": 0, "total_prev": 0, "caducidad": "07/2027"}}

    monkeypatch.setattr("pdf_parser._extract_page_vision", invented_name)
    record = {"code": code, "lines": [original_description], "stock": 2}
    if kind == "ventas":
        products = extract_products(_sales_pdf(tmp_path / "source-error-sales.pdf", [record]), anthropic_key="mock-key")
    else:
        products = extract_situation(_situation_pdf(tmp_path / "source-error-situation.pdf", [[record]]), anthropic_key="mock-key")
    product = products[code]
    assert calls
    assert product["description"] == original_description
    assert product["stock"] == 2
    assert product["needs_review"] is True
    assert "vision_rechazada:nombre_ausente_en_original" in product["warnings"]


def test_invalid_vision_months_cannot_overwrite_signed_source_values(tmp_path, monkeypatch, mock_vision_renderer):
    code = "123456"

    def invalid_months(*args, **kwargs):
        return {code: {"code": code, "description": "PRODUCTO CON DEVOLUCIONES", "stock": 999, "smin": 999,
                       "months_current": [6], "months_prev": [0] * 12,
                       "total_current": 6, "total_prev": 0}}

    monkeypatch.setattr("pdf_parser._extract_page_vision", invalid_months)
    months = [-1, 0, 0, 5] + [0] * 8
    record = {"code": code, "lines": ["PRODUCTO CON DEVOLUCIONES"], "stock": -1, "smin": 1,
              "current": months, "current_total": 6}
    product = extract_products(_sales_pdf(tmp_path / "invalid-vision.pdf", [record]), anthropic_key="mock-key")[code]
    assert product["stock"] == -1
    assert product["smin"] == 1
    assert product["months_current"] == months
    assert product["total_current"] == 6
    assert product["needs_review"] is True
    assert "vision_rechazada:months_current_invalidos" in product["warnings"]


@pytest.mark.parametrize("kind", ["ventas", "situacion"])
def test_document_header_detection_still_identifies_type_and_pharmacy(tmp_path, kind):
    path = tmp_path / "header.pdf"
    record = {"code": "123456", "lines": ["PRODUCTO DE PRUEBA"]}
    if kind == "ventas":
        _sales_pdf(path, [record])
    else:
        _situation_pdf(path, [[record]])
    assert detect_pdf_header(path) == {"type": kind, "pharmacy": "FARMACIA DE PRUEBAS"}


def _customer_pdf(prefix):
    fixture_location = os.environ.get("PHARMACY_PDF_FIXTURE_DIR")
    if not fixture_location:
        pytest.skip("Set PHARMACY_PDF_FIXTURE_DIR to run the private, visually reviewed originals. Originals are intentionally not committed.")
    fixture_dir = Path(fixture_location)
    if fixture_dir.is_dir():
        for path in fixture_dir.glob("*.pdf"):
            if unicodedata.normalize("NFC", path.name).startswith(prefix):
                return path
    pytest.skip(f"Private, visually reviewed PDF not available: {prefix}; set PHARMACY_PDF_FIXTURE_DIR. Originals are intentionally not committed.")


@pytest.mark.parametrize("prefix,kind,pharmacy", [
    ("Estadísticas de interapotek", "ventas", "LDA. CARMEN R. ZARZUELO"),
    ("Informe de interapotek", "situacion", "LDA. CARMEN R. ZARZUELO"),
    ("Estadísticas de ventas de IA", "ventas", "BARRIS"),
    ("Informe de situación de IA", "situacion", "BARRIS"),
])
def test_customer_documents_keep_working_header_detection(prefix, kind, pharmacy):
    header = detect_pdf_header(_customer_pdf(prefix))
    assert header["type"] == kind
    assert pharmacy in header["pharmacy"].upper()


@pytest.fixture(scope="module")
def zarzuelo_sales():
    return extract_products(_customer_pdf("Estadísticas de interapotek"))


@pytest.fixture(scope="module")
def barris_sales():
    return extract_products(_customer_pdf("Estadísticas de ventas de IA"))


def test_customer_zarzuelo_descriptions_match_visual_originals(zarzuelo_sales):
    expected = {
        "195766": "AGUA DESTILADA INTERAPOTHEK 1 ENVASE 5000 ML",
        "197836": "ALGODON ZIG-ZAG INTERAPOTHEK 1 PAQUETE 50 G",
        "215220": "CEPILLO MINI BIODEGRADABLE INTERAPOTHEK 1 UNIDAD COLOR CORAL",
        "006113": "IA CEPILLO BIO VERDE",
        "134766": "IA DUPLO CHAMPU CERO 2º 50%",
    }
    for code, description in expected.items():
        assert zarzuelo_sales[code]["description"] == description
    assert zarzuelo_sales["195766"]["stock"] == 1
    assert zarzuelo_sales["195766"]["smin"] == 1
    assert zarzuelo_sales["195766"]["total_current"] == 2
    assert zarzuelo_sales["195766"]["total_prev"] == 10


def test_customer_zarzuelo_situation_does_not_absorb_headers_or_selection_criteria():
    products = extract_situation(_customer_pdf("Informe de interapotek"))
    assert products["217849"]["description"] == "CONTORNO OJOS BIO-PEPTIDOS INTERAPOTHEK 1 ENVASE 15 ML"
    assert products["165950"]["description"] == "INTERAPOTHEK CHAMPU PEDICULICIDA USO HUMANO ANTIPIOJOS 1 ENVASE 150 ML"
    assert products["211836"]["description"] == "07/2026"
    assert products["211836"]["needs_review"] is True
    assert "Totales" not in products["211836"]["description"]
    assert all(not product["description"].startswith("Descripción") for product in products.values())


def test_customer_barris_names_and_negative_stock_match_visual_originals(barris_sales):
    assert "MICROFIBRA" not in barris_sales["208315"]["description"]
    assert "IRRIGADOR" not in barris_sales["214681"]["description"]
    assert barris_sales["215037"]["stock"] == -1
    assert barris_sales["195766"]["stock"] == 1
    assert barris_sales["195766"]["smin"] == 0


def test_customer_barris_keeps_signed_months_and_original_stock(barris_sales):
    product = barris_sales["369884"]
    assert product["total_current"] == 4
    assert product["months_current"][0] == -1
    assert product["months_current"][3] == 5
    assert product["stock"] == 4
    assert product["smin"] == 2
    assert not any(warning.startswith("total_discrepancia:") for warning in product["warnings"])


def test_customer_barris_situation_keeps_each_product_separate():
    products = extract_situation(_customer_pdf("Informe de situación de IA"))
    expected = {
        "208296": "INTERAPOTHEK BARRA DE LABIOS 1 ENVASE 4,2 G Nº5",
        "208308": "INTERAPOTHEK ESMALTE DE UÑAS 1 ENVASE 10 ML Nº20",
        "257072": "INTERAPOTHEK LECHE CORPORAL ALOE VERA 1 ENVASE 200 ML",
        "208313": "INTERAPOTHEK LIPGLOSS BRILLO DE LABIOS 1 ENVASE 3 ML Nº2",
        "213664": "ORINAL MASCULINO INTERAPOTHEK 1 UNIDAD",
    }
    for code, description in expected.items():
        assert products[code]["description"] == description
    assert all("Criterios" not in product["description"] and "Totales" not in product["description"] for product in products.values())


def test_customer_sales_totals_match_the_visually_reviewed_final_pages(zarzuelo_sales, barris_sales):
    assert sum(product["total_current"] for product in zarzuelo_sales.values()) == 539
    assert sum(product["total_prev"] for product in zarzuelo_sales.values()) == 1034
    assert sum(product["total_current"] for product in barris_sales.values()) == 700
    assert sum(product["total_prev"] for product in barris_sales.values()) == 1863


def test_customer_comparison_uses_a_trusted_name_when_one_original_contains_only_a_digit(zarzuelo_sales, barris_sales):
    assert zarzuelo_sales["208627"]["description"] == "8"
    assert zarzuelo_sales["208627"]["needs_review"] is True
    row = next(product for product in compare_products(zarzuelo_sales, barris_sales, name1="Zarzuelo", name2="Barris")
               if product["code"] == "208627")
    assert row["description"] == "INTERAPOTHEK MASCARILLA ACEITE DE ARGAN 1 ENVASE 250 ML"
    assert row["description_source"]["pharmacy_index"] == 2
    assert row["description_source"]["pharmacy"] == "Barris"
    assert row["description_source"]["file"] in {source["file"] for source in row["sources"]}
