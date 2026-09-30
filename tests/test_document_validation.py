"""Independent checks for document totals, report scope and product sizes.

All ordinary fixtures are synthetic and contain no customer quantities. The
optional corpus checks read visually reviewed expectations from a local manifest;
neither customer PDFs nor their expected values belong in the repository.
"""

import json
import os
from pathlib import Path
import unicodedata

import pytest
from reportlab.lib import colors
from reportlab.pdfgen import canvas

import pdf_parser
from tests.test_pdf_parser import MONTHS, _document_header, _sales_pdf


def _sales_document(path, pages, *, criteria=None, criteria_page=False, criteria_extra_record=None):
    """Print cumulative footers independently of the parser's row detection."""
    width, height = 1000, 800
    pdf = canvas.Canvas(str(path), pagesize=(width, height))
    code_x, description_x = 30, 90
    numeric_x = [360, 410, 460, 530] + [590 + 34 * index for index in range(12)]
    accumulated_stock, accumulated_total = 0, 0
    accumulated_months = [0] * 12
    criteria = criteria or ["Desde: 05/2025", "Hasta: 04/2026", "Agrupar por: Producto"]

    def draw_criteria(top):
        pdf.setFillColor(colors.black)
        pdf.setFont("Helvetica", 10)
        pdf.drawString(description_x, height - top, "Criterios de selección:")
        for index, text in enumerate(["Laboratorio: 24"] + criteria):
            pdf.drawString(description_x, height - top - (index + 1) * 16, text)

    for page_index, records in enumerate(pages):
        _document_header(pdf, width, height, "ventas")
        pdf.setFillColor(colors.HexColor("#cc5555"))
        pdf.rect(20, height - 107, width - 40, 22, fill=1, stroke=0)
        pdf.setFillColor(colors.white)
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(code_x, height - 100, "Código")
        pdf.drawString(description_x, height - 100, "Descripción")
        for right, label in zip(numeric_x, ["Stock", "S.min", "Año", "Total"] + MONTHS):
            pdf.drawRightString(right, height - 100, label)

        top, leading = 124, 13
        for record_index, record in enumerate(records):
            current = record["current"]
            previous = record["previous"]
            line_count = max(2, len(record["lines"]))
            pdf.setFillColor(colors.HexColor("#dddddd" if record_index % 2 == 0 else "#ffffff"))
            pdf.rect(20, height - top - (line_count - 1) * leading - 5,
                     width - 40, line_count * leading, fill=1, stroke=0)
            pdf.setFillColor(colors.black)
            pdf.setFont("Helvetica", 10)
            for line_index, text in enumerate(record["lines"]):
                pdf.drawString(description_x, height - top - line_index * leading, text)
            if record.get("code") is not None:
                pdf.drawString(code_x, height - top, record["code"])
            for baseline, numbers in [
                (height - top, [record["stock"], record.get("smin", 1), record.get("year_current", 2026), sum(current)] + current),
                (height - top - leading, [None, None, record.get("year_prev", 2025), sum(previous)] + previous),
            ]:
                for right, number in zip(numeric_x, numbers):
                    if number is not None:
                        pdf.drawRightString(right, baseline, str(number))
            accumulated_stock += record["stock"]
            accumulated_total += sum(current) + sum(previous)
            accumulated_months = [total + first + second for total, first, second
                                  in zip(accumulated_months, current, previous)]
            top += line_count * leading + 3

        pdf.setFillColor(colors.HexColor("#cc5555"))
        pdf.rect(20, height - top - 14, width - 40, 20, fill=1, stroke=0)
        pdf.setFillColor(colors.white)
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(description_x, height - top - 7, "Totales")
        for right, number in zip(numeric_x, [accumulated_stock, None, None, accumulated_total] + accumulated_months):
            if number is not None:
                pdf.drawRightString(right, height - top - 7, str(number))
        if page_index == len(pages) - 1 and not criteria_page:
            draw_criteria(top + 40)
        pdf.showPage()

    if criteria_page:
        _document_header(pdf, width, height, "ventas")
        draw_criteria(110)
        if criteria_extra_record:
            pdf.drawString(code_x, height - 260, criteria_extra_record["code"])
            pdf.drawString(description_x, height - 260, criteria_extra_record["description"])
        pdf.showPage()
    pdf.save()
    return path


def _record(code, *, stock, current, previous):
    return {"code": code, "lines": ["PRODUCTO SINTETICO", "1 ENVASE 100 ML"], "stock": stock,
            "current": [current] + [0] * 11, "previous": [0] * 4 + [previous] + [0] * 7}


def _two_page_records():
    return [[_record("123456", stock=3, current=2, previous=1)],
            [_record("234567", stock=4, current=3, previous=2)]]


def _situation_document(path, pages):
    width, height = 1000, 800
    pdf = canvas.Canvas(str(path), pagesize=(width, height))
    xs = [30, 80, 150, 560, 640, 730, 840]
    cumulative_stock = 0
    for page_index, records in enumerate(pages):
        _document_header(pdf, width, height, "situacion")
        pdf.setFillColor(colors.HexColor("#cc5555"))
        pdf.rect(20, height - 107, width - 40, 22, fill=1, stroke=0)
        pdf.setFillColor(colors.white)
        pdf.setFont("Helvetica-Bold", 10)
        for x, label in zip(xs, ["Alm.", "Código", "Descripción", "Stock", "PVP", "Importe PVP", "Caducidad"]):
            pdf.drawString(x, height - 100, label)
        top = 124
        for record in records:
            pdf.setFillColor(colors.HexColor("#dddddd"))
            pdf.rect(20, height - top - 18, width - 40, 26, fill=1, stroke=0)
            pdf.setFillColor(colors.black)
            pdf.setFont("Helvetica", 10)
            values = [1, record.get("code"), "PRODUCTO SINTETICO 100 ML", record["stock"], "2,50",
                      f'{record["stock"] * 2.5:.2f}'.replace(".", ","), "07/2027"]
            for x, value in zip(xs, values):
                if value is not None:
                    pdf.drawString(x, height - top, str(value))
            cumulative_stock += record["stock"]
            top += 29
        pdf.setFillColor(colors.HexColor("#cc5555"))
        pdf.rect(20, height - top - 14, width - 40, 20, fill=1, stroke=0)
        pdf.setFillColor(colors.white)
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(xs[2], height - top - 7, "Suma y Sigue" if page_index < len(pages) - 1 else "Totales")
        pdf.drawString(xs[3], height - top - 7, str(cumulative_stock))
        if page_index == len(pages) - 1:
            pdf.setFillColor(colors.black)
            pdf.setFont("Helvetica", 10)
            for index, text in enumerate(["Criterios de selección:", "Laboratorio: 24", "Stock actual: >0",
                                          "Artículos sin movimientos desde hace: 365"]):
                pdf.drawString(xs[2], height - top - 40 - index * 16, text)
        pdf.showPage()
    pdf.save()
    return path


def _document_warning_codes(products):
    return {warning["code"] for warning in products.metadata["warnings"]}


def _footer_discrepancy(products):
    return any("discrepancia" in code and ("total" in code or "pie" in code)
               for code in _document_warning_codes(products))


def test_valid_cumulative_footers_are_checked_without_double_counting(tmp_path):
    products = pdf_parser.extract_products(_sales_document(tmp_path / "cumulative.pdf", _two_page_records()))
    assert isinstance(products, pdf_parser.DocumentProducts)
    assert set(products) == {"123456", "234567"}
    assert sum(product["stock"] for product in products.values()) == 7
    assert sum(product["total_current"] + product["total_prev"] for product in products.values()) == 8
    assert products.metadata["page_count"] == 2
    assert products.metadata["document_type"] == "ventas"
    assert len(products.metadata["pages"]) == 2
    assert all(page["footer_checks"] for page in products.metadata["pages"])
    first_footer, last_footer = [page["footer_checks"][0] for page in products.metadata["pages"]]
    assert first_footer["printed"] == {"stock": 3, "total": 3, "months": [2, 0, 0, 0, 1] + [0] * 7}
    assert last_footer["printed"] == {"stock": 7, "total": 8, "months": [5, 0, 0, 0, 3] + [0] * 7}
    assert first_footer["calculated"] == first_footer["printed"] and first_footer["matches"] is True
    assert last_footer["calculated"] == last_footer["printed"] and last_footer["matches"] is True
    assert products.metadata["totals"] == {"stock": 7, "by_year": {"2025": 3, "2026": 5}}
    assert not _footer_discrepancy(products)
    assert products.metadata["order_unsafe"] is False


def test_document_footer_detects_an_omitted_row_even_when_remaining_rows_balance(tmp_path, monkeypatch):
    pages = _two_page_records()
    pages[1].append(_record("345678", stock=2, current=4, previous=3))
    path = _sales_document(tmp_path / "omitted-row.pdf", pages)
    original_blocks = pdf_parser._product_blocks

    def omit_one_product(page, layout):
        return [block for block in original_blocks(page, layout) if block["anchor"]["code"] != "345678"]

    monkeypatch.setattr(pdf_parser, "_product_blocks", omit_one_product)
    products = pdf_parser.extract_products(path)
    assert set(products) == {"123456", "234567"}
    assert all(product["total_pdf_current"] == sum(product["months_current"])
               and product["total_pdf_prev"] == sum(product["months_prev"])
               for product in products.values())
    assert _footer_discrepancy(products)
    assert products.metadata["order_unsafe"] is True
    rows = pdf_parser.compare_products(products, {})
    assert all(row["pedido1"] is None and row["pedido_no_calculable1"] for row in rows)


def test_document_footer_detects_a_page_with_no_recognized_product_codes(tmp_path):
    pages = _two_page_records()
    pages[1][0]["code"] = None
    products = pdf_parser.extract_products(_sales_document(tmp_path / "omitted-page.pdf", pages))
    assert set(products) == {"123456"}
    assert products["123456"]["total_pdf_current"] == sum(products["123456"]["months_current"])
    assert products["123456"]["total_pdf_prev"] == sum(products["123456"]["months_prev"])
    assert _footer_discrepancy(products)
    assert products.metadata["order_unsafe"] is True


def test_recognized_empty_table_with_an_explicit_zero_footer_is_safe(tmp_path):
    products = pdf_parser.extract_products(_sales_document(tmp_path / "empty-zero-table.pdf", [[]]))
    assert isinstance(products, pdf_parser.DocumentProducts) and not products
    assert products.metadata["page_count"] == 1
    assert products.metadata["pages"][0]["kind"] == "table"
    assert products.metadata["pages"][0]["product_count"] == 0
    footer = products.metadata["pages"][0]["footer_checks"][0]
    assert footer["printed"] == {"stock": 0, "total": 0, "months": [0] * 12}
    assert footer["matches"] is True
    assert products.metadata["order_unsafe"] is False
    assert "pagina_sin_productos" not in _document_warning_codes(products)
    assert products.metadata["years"] == []


def test_zero_footer_does_not_hide_a_visible_product_without_a_recognized_code(tmp_path):
    record = _record(None, stock=0, current=0, previous=0)
    products = pdf_parser.extract_products(_sales_document(tmp_path / "unread-zero-product.pdf", [[record]]))
    assert not products
    assert products.metadata["pages"][0]["footer_checks"][0]["printed"] == {
        "stock": 0, "total": 0, "months": [0] * 12}
    assert "pagina_sin_productos" in _document_warning_codes(products)
    assert products.metadata["order_unsafe"] is True


def test_last_page_containing_only_selection_criteria_is_not_a_missing_table(tmp_path):
    products = pdf_parser.extract_products(_sales_document(
        tmp_path / "criteria-only-last-page.pdf", _two_page_records(), criteria_page=True))
    assert set(products) == {"123456", "234567"}
    assert products.metadata["page_count"] == 3
    assert len(products.metadata["pages"]) == 3
    assert products.metadata["pages"][2]["kind"] == "criteria"
    assert not any(warning.get("page") == 3 for warning in products.metadata["warnings"])
    assert not _footer_discrepancy(products)
    assert products.metadata["order_unsafe"] is False
    assert products.metadata["period"]["from"] == "05/2025"
    assert products.metadata["period"]["to"] == "04/2026"


def test_criteria_heading_does_not_hide_an_unrecognized_product_table(tmp_path):
    products = pdf_parser.extract_products(_sales_document(
        tmp_path / "unrecognized-table-after-criteria.pdf", _two_page_records(), criteria_page=True,
        criteria_extra_record={"code": "345678", "description": "PRODUCTO SINTETICO FUERA DE COLUMNAS"}))
    assert products.metadata["pages"][2]["kind"] != "criteria"
    assert any(warning.get("page") == 3 for warning in products.metadata["warnings"])
    assert products.metadata["order_unsafe"] is True


@pytest.mark.parametrize("missing_last_code", [False, True])
def test_situation_cumulative_stock_and_inactive_scope_are_checked(tmp_path, missing_last_code):
    pages = [[{"code": "123456", "stock": 3}],
             [{"code": None if missing_last_code else "234567", "stock": 4}]]
    products = pdf_parser.extract_situation(_situation_document(tmp_path / "inactive-stock.pdf", pages))
    assert products.metadata["document_type"] == "situacion"
    assert products.metadata["criteria"]["inactive_days"] == 365
    assert products.metadata["criteria"]["stock_filter"] == ">0"
    assert products.metadata["pages"][0]["footer_checks"][0]["printed"]["stock"] == 3
    assert products.metadata["pages"][1]["footer_checks"][0]["printed"]["stock"] == 7
    assert _footer_discrepancy(products) is missing_last_code
    assert products.metadata["order_unsafe"] is missing_last_code
    if not missing_last_code:
        assert products.metadata["totals"]["stock"] == 7
        assert set(products) == {"123456", "234567"}
    assert all("smin" not in product and "total_current" not in product for product in products.values())


def test_comparison_preserves_different_declared_periods_and_current_month_flag(tmp_path):
    first = pdf_parser.extract_products(_sales_document(
        tmp_path / "period-one.pdf", _two_page_records(),
        criteria=["Desde: 05/2025", "Hasta: 04/2026", "Mes actual: N"]))
    second = pdf_parser.extract_products(_sales_document(
        tmp_path / "period-two.pdf", _two_page_records(),
        criteria=["Desde: 03/2025", "Hasta: 03/2026", "Mes actual: S"]))
    comparison = pdf_parser.compare_document_metadata(first, second, None, None)
    assert comparison["periods_differ"] is True
    assert comparison["documents"]["pdf1"]["period"] == {"from": "05/2025", "to": "04/2026", "current_month": False}
    assert comparison["documents"]["pdf2"]["period"] == {"from": "03/2025", "to": "03/2026", "current_month": True}
    assert comparison["document_warnings"]
    assert any("period" in warning.lower() or "períod" in warning.lower()
               for warning in comparison["document_warnings"])


def test_current_month_alone_changes_the_compared_report_scope(tmp_path):
    documents = []
    for flag in ("N", "S"):
        documents.append(pdf_parser.extract_products(_sales_document(
            tmp_path / f"current-month-{flag}.pdf", _two_page_records(),
            criteria=["Desde: 05/2025", "Hasta: 04/2026", f"Mes actual: {flag}"])))
    comparison = pdf_parser.compare_document_metadata(*documents)
    assert comparison["periods_differ"] is True
    assert comparison["documents"]["pdf1"]["period"]["current_month"] is False
    assert comparison["documents"]["pdf2"]["period"]["current_month"] is True


def _known_product(description):
    return {"description": description, "stock": 1, "smin": 1,
            "year_current": 2026, "year_prev": 2025,
            "months_current": [4] + [0] * 11, "months_prev": [4] + [0] * 11,
            "total_current": 4, "total_prev": 4, "warnings": [], "needs_review": False}


@pytest.mark.parametrize("unsafe_pharmacy", [1, 2])
def test_empty_unreadable_situation_blocks_only_its_pharmacy_order(unsafe_pharmacy):
    sales1 = {"123456": _known_product("PRODUCTO SINTETICO 100ML")}
    sales2 = {"123456": _known_product("PRODUCTO SINTETICO 100ML")}
    unreadable_situation = pdf_parser.DocumentProducts(metadata={"order_unsafe": True})
    assert not unreadable_situation
    safe_pharmacy = 2 if unsafe_pharmacy == 1 else 1
    row = pdf_parser.compare_products(
        sales1, sales2,
        situation1=unreadable_situation if unsafe_pharmacy == 1 else None,
        situation2=unreadable_situation if unsafe_pharmacy == 2 else None)[0]
    assert row[f"pedido{unsafe_pharmacy}"] is None
    assert row[f"pedido_no_calculable{unsafe_pharmacy}"] is True
    assert row[f"pedido{safe_pharmacy}"] == 1
    assert row[f"pedido_no_calculable{safe_pharmacy}"] is False
    assert row["total1"] == 4 and row["total2"] == 4
    assert row["stock1"] == 1 and row["stock2"] == 1


@pytest.mark.parametrize("first_size,second_size", [("100 ML", "200ML"), ("100mL", "200 ML"), ("75 G", "100G")])
@pytest.mark.parametrize("second_source", ["sales", "situation"])
def test_same_code_with_different_presentations_requires_review(first_size, second_size, second_source):
    first = {"123456": _known_product(f"PRODUCTO SINTETICO 1 ENVASE {first_size}")}
    second = {"123456": _known_product(f"PRODUCTO SINTETICO 1 ENVASE {second_size}")}
    if second_source == "sales":
        row = pdf_parser.compare_products(first, second)[0]
    else:
        row = pdf_parser.compare_products(first, {}, situation1=second)[0]
    assert any(warning.startswith("presentacion_inconsistente") for warning in row["warnings"])
    assert row["needs_review"] is True
    descriptions = {candidate["description"] for candidate in row["description_candidates"]}
    assert descriptions == {first["123456"]["description"], second["123456"]["description"]}


@pytest.mark.parametrize("first_size,second_size", [("100 ML", "100ML"), ("100mL", "100 ML"),
                                                     ("0.1 L", "100ML"), ("0,1L", "100 mL"), ("75G", "75 G")])
def test_equivalent_presentations_do_not_raise_a_size_conflict(first_size, second_size):
    first = {"123456": _known_product(f"PRODUCTO SINTETICO 1 ENVASE {first_size}")}
    second = {"123456": _known_product(f"PRODUCTO SINTETICO 1 ENVASE {second_size}")}
    row = pdf_parser.compare_products(first, second)[0]
    assert not any(warning.startswith("presentacion_inconsistente") for warning in row["warnings"])


@pytest.mark.parametrize("first_description,second_description", [
    ("PRODUCTO1 ENVASE100ML", "PRODUCTO1 ENVASE200ML"),
    ("PRODUCTO SINTETICO 75ML", "PRODUCTO SINTETICO ENVASE100ML"),
    ("PRODUCTO1 ENVASE75G", "PRODUCTO1 ENVASE100ML"),
    ("PRODUCTO SINTETICO SPF15 ENVASE100ML", "PRODUCTO SINTETICO FPS20 ENVASE100ML"),
])
@pytest.mark.parametrize("second_source", ["sales", "situation"])
def test_joined_quantities_and_sun_protection_differences_are_preserved_and_flagged(
        first_description, second_description, second_source):
    first = {"123456": _known_product(first_description)}
    second = {"123456": _known_product(second_description)}
    if second_source == "sales":
        row = pdf_parser.compare_products(first, second)[0]
    else:
        row = pdf_parser.compare_products(first, {}, situation1=second)[0]
    assert any(warning.startswith("presentacion_inconsistente") for warning in row["warnings"])
    assert row["needs_review"] is True
    assert {candidate["description"] for candidate in row["description_candidates"]} == {
        first_description, second_description}


@pytest.mark.parametrize("first_description,second_description", [
    ("PRODUCTO1 ENVASE100ML", "PRODUCTO1 ENVASE 100 mL"),
    ("PRODUCTO1 ENVASE0.1L", "PRODUCTO1 ENVASE100ML"),
    ("PRODUCTO SINTETICO SPF15 ENVASE100ML", "PRODUCTO SINTETICO FPS15 ENVASE100ML"),
])
def test_equivalent_joined_quantities_and_sun_protection_aliases_do_not_conflict(
        first_description, second_description):
    first = {"123456": _known_product(first_description)}
    second = {"123456": _known_product(second_description)}
    row = pdf_parser.compare_products(first, second)[0]
    assert not any(warning.startswith("presentacion_inconsistente") for warning in row["warnings"])


@pytest.mark.parametrize("older_pharmacy", [1, 2])
def test_comparison_aligns_both_totals_and_months_to_the_observed_years(older_pharmacy):
    latest = _known_product("PRODUCTO SINTETICO 100ML")
    latest.update(total_current=2, total_prev=7, months_current=[2] + [0] * 11,
                  months_prev=[0, 7] + [0] * 10)
    older = _known_product("PRODUCTO SINTETICO 100ML")
    older.update(year_current=2025, year_prev=2024, total_current=3, total_prev=9,
                 months_current=[0, 0, 3] + [0] * 9, months_prev=[0, 0, 0, 9] + [0] * 8)
    first, second = (older, latest) if older_pharmacy == 1 else (latest, older)
    row = pdf_parser.compare_products({"123456": first}, {"123456": second})[0]
    latest_pharmacy = 2 if older_pharmacy == 1 else 1
    assert row["year_current"] == 2026 and row["year_prev"] == 2025
    assert row[f"total{older_pharmacy}"] in (None, "—")
    assert row[f"total{older_pharmacy}_prev"] == 3
    assert row[f"months{older_pharmacy}_current"] == [None] * 12
    assert row[f"months{older_pharmacy}_prev"] == [0, 0, 3] + [0] * 9
    assert row[f"total{latest_pharmacy}"] == 2
    assert row[f"total{latest_pharmacy}_prev"] == 7
    assert row[f"months{latest_pharmacy}_current"] == [2] + [0] * 11
    assert row[f"months{latest_pharmacy}_prev"] == [0, 7] + [0] * 10
    assert older["year_prev"] == 2024 and older["total_prev"] == 9


def test_missing_printed_years_do_not_use_the_execution_year(tmp_path):
    record = _record("123456", stock=3, current=2, previous=1)
    record.update(year_current=None, year_prev=None)
    products = pdf_parser.extract_products(_sales_document(tmp_path / "missing-years.pdf", [[record]]))
    assert products["123456"]["year_current"] is None
    assert products["123456"]["year_prev"] is None
    assert products.metadata["years"] == []
    row = pdf_parser.compare_products(products, {})[0]
    assert row["year_current"] is None and row["year_prev"] is None
    assert row["total1"] in (None, "—") and row["total1_prev"] in (None, "—")
    assert row["months1_current"] == [None] * 12
    assert row["months1_prev"] == [None] * 12
    assert row["pedido1"] is None and row["pedido_no_calculable1"] is True


def test_unknown_values_and_an_absent_pharmacy_are_not_reported_as_zero(tmp_path):
    record = {"code": "123456", "lines": ["PRODUCTO SINTETICO CON CELDAS VACIAS"],
              "stock": None, "smin": None, "current": [None] + [0] * 11,
              "current_total": None, "previous": [0] * 12}
    products = pdf_parser.extract_products(_sales_pdf(tmp_path / "unknown-values.pdf", [record]))
    product = products["123456"]
    assert product["stock"] is None and product["smin"] is None
    assert product["total_current"] is None
    assert product["months_current"][0] is None
    assert product["months_current"][1] == 0
    assert products.metadata["period"] == {"from": None, "to": None, "current_month": None}
    row = pdf_parser.compare_products(products, {})[0]
    assert row["stock1"] is None and row["smin1"] is None
    assert row["total1"] is None
    assert row["total2"] in (None, "—")
    assert row["months2_current"] == [None] * 12
    assert row["months2_prev"] == [None] * 12
    assert row["pedido1"] is None and row["pedido_no_calculable1"] is True


def test_optional_visually_reviewed_private_corpus():
    manifest_path = os.environ.get("PHARMACY_CORPUS_MANIFEST")
    if not manifest_path:
        pytest.skip("Set PHARMACY_CORPUS_MANIFEST to a private manifest with visually reviewed expectations.")
    manifest = json.loads(Path(manifest_path).read_text())
    documents = manifest.get("documents", []) if isinstance(manifest, dict) else manifest
    assert documents, "The private corpus manifest has no documents."
    for document in documents:
        expected = document.get("expected")
        assert expected, f"No visually reviewed expectations for corpus document {document.get('id', '?')}."
        kind = document.get("document_type", document.get("kind_hint"))
        reader = pdf_parser.extract_situation if kind in ("situacion", "situation") else pdf_parser.extract_products
        products = reader(document["path"])
        assert len(products) == expected["count"], document.get("id")
        for field in ("stock", "total_current", "total_prev"):
            if field in expected:
                values = [product.get(field) for product in products.values()]
                assert all(value is not None for value in values), (document.get("id"), field, "unknown value")
                assert sum(values) == expected[field], (document.get("id"), field)
        for code, fields in expected.get("rows", {}).items():
            assert code in products, (document.get("id"), code)
            for field, value in fields.items():
                actual = products[code].get(field)
                if field == "description":
                    # A manual visual transcription may join a word wrapped
                    # across lines differently. Keep every letter, digit and
                    # punctuation mark; only NFC and whitespace may differ.
                    assert isinstance(actual, str) and isinstance(value, str)
                    actual = "".join(unicodedata.normalize("NFC", actual).split())
                    value = "".join(unicodedata.normalize("NFC", value).split())
                assert actual == value, (document.get("id"), code, field)
