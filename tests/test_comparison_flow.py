"""Exercise upload, comparison, results and exports without network or login."""

import io
import json

import pdfplumber

import app as web
from tests.test_pdf_parser import _sales_pdf, _situation_pdf


class _InlineThread:
    def __init__(self, *, target, args, daemon):
        self.target = target
        self.args = args

    def start(self):
        self.target(*self.args)


def test_public_four_document_comparison_preserves_names_and_signed_sales(tmp_path, monkeypatch):
    monkeypatch.setattr(web.threading, "Thread", _InlineThread)
    monkeypatch.setattr(web.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(web, "_get_api_key", lambda: "")
    monkeypatch.setattr(web, "_progress_store", {})
    monkeypatch.setitem(web.app.config, "TESTING", True)

    sales1 = _sales_pdf(tmp_path / "ventas_zarzuelo.pdf", [
        {"code": "195765", "lines": ["AGUA DESTILADA INTERAPOTHEK", "1 ENVASE 1000 ML"]},
        {"code": "195766", "lines": ["AGUA DESTILADA INTERAPOTHEK", "1 ENVASE 5000 ML"],
         "current": [0, 1, 0, 1] + [0] * 8},
    ])
    sales2 = _sales_pdf(tmp_path / "ventas_barris.pdf", [
        {"code": "369884", "lines": ["INTERAPOTHEK TERMOMETRO DIGITAL"],
         "stock": 4, "smin": 2, "current": [-1, 0, 0, 5] + [0] * 8},
    ])
    situation1 = _situation_pdf(tmp_path / "situacion_zarzuelo.pdf", [[
        {"code": "208775", "lines": ["CEPILLO INTERAPOTHEK", "COLOR NARANJA"]},
        {"code": "217849", "lines": ["CONTORNO OJOS BIO-PEPTIDOS INTERAPOTHEK", "1 ENVASE 15 ML"]},
    ]])
    situation2 = _situation_pdf(tmp_path / "situacion_barris.pdf", [[
        {"code": "208296", "lines": ["INTERAPOTHEK BARRA DE LABIOS Nº5"]},
        {"code": "208297", "lines": ["INTERAPOTHEK BARRA DE LABIOS Nº6"]},
    ]])
    uploads = {key: (io.BytesIO(path.read_bytes()), path.name) for key, path in [
        ("pdf1", sales1), ("pdf2", sales2), ("sit1", situation1), ("sit2", situation2),
    ]}
    uploads.update(name1="Zarzuelo", name2="Barris")

    with web.app.test_client() as client:
        response = client.post("/comparar", data=uploads)
        assert response.status_code == 200
        job = response.get_json()["job"]
        progress = client.get(f"/progress/{job}").get_json()
        assert progress["done"] is True
        assert progress["error_msg"] is None
        assert progress["pct"] == 100

        final = client.get(f"/finalizar/{job}")
        assert final.status_code == 302
        assert final.headers["Location"].endswith("/resultado")
        page = client.get("/resultado")
        assert page.status_code == 200
        assert "COLOR NARANJA CONTORNO" not in page.get_data(as_text=True)

        with client.session_transaction() as state:
            assert "authenticated" not in state
            token = state["comp_token"]
        stored = json.loads((tmp_path / f"comp_{token}.json").read_text())
        products = {product["code"]: product for product in stored["results"]}
        assert products["195766"]["description"] == "AGUA DESTILADA INTERAPOTHEK 1 ENVASE 5000 ML"
        assert products["369884"]["total2"] == 4
        assert products["369884"]["months2_current"][0] == -1
        assert products["208296"]["description"] == "INTERAPOTHEK BARRA DE LABIOS Nº5"
        assert products["217849"]["description"].startswith("CONTORNO OJOS")
        assert products["195766"]["description_source"]["file"] == sales1.name
        assert products["369884"]["sources"][0]["file"] == sales2.name
        assert products["217849"]["description_candidates"][0]["file"] == situation1.name
        assert products["208296"]["description_source"]["file"] == situation2.name

        for route in ("/pedido", "/buscador"):
            assert client.get(route).status_code == 200
        exported = client.get("/descargar")
        assert exported.status_code == 200
        assert exported.mimetype == "application/pdf"
        with pdfplumber.open(io.BytesIO(exported.data)) as document:
            text = " ".join((page.extract_text() or "") for page in document.pages)
        assert "5000 ML" in text
        assert "1000 ML AGUA" not in text
        assert "Totales de selección" not in text
        assert all(path.exists() for path in (sales1, sales2, situation1, situation2))
