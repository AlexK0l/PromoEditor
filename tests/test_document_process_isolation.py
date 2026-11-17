"""Untrusted document parsers run in resource-bounded subprocesses."""
import io
import json
import subprocess

import pytest

from app import document_worker
from app.documents import extract_text, pdf_first_page_png


def test_real_docx_and_xlsx_are_parsed_in_subprocess():
    from docx import Document
    from openpyxl import Workbook

    doc = Document()
    doc.add_paragraph("Тормозная система: ABS")
    data = io.BytesIO()
    doc.save(data)
    text, warnings = extract_text("brochure.docx", data.getvalue())
    assert "Тормозная система: ABS" in text
    assert isinstance(warnings, list)

    book = Workbook()
    book.active.append(["Грузоподъёмность", "44 т"])
    data = io.BytesIO()
    book.save(data)
    text, _ = extract_text("specifications.xlsx", data.getvalue())
    assert "44 т" in text


def test_pdf_drawing_is_rasterized_in_bounded_subprocess():
    import fitz
    pdf = fitz.open()
    page = pdf.new_page(width=330, height=240)
    page.insert_text((20, 30), "PDF technical drawing")
    content = pdf.tobytes()
    pdf.close()
    text, warnings = extract_text("drawing.pdf", content)
    assert "PDF technical drawing" in text
    image = pdf_first_page_png(content)
    assert image.startswith(b"\x89PNG\r\n\x1a\n")


def test_child_environment_excludes_credentials(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-child")
    monkeypatch.setenv("PROMO_SESSION_SECRET", "must-not-reach-child")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps({
                "ok": True, "text": "good", "warnings": [],
            }).encode("utf-8"),
        )

    monkeypatch.setattr(document_worker.subprocess, "run", fake_run)
    result = document_worker.run_document_worker("extract", "source.docx", b"x")
    assert result == ("good", [])
    command, kwargs = calls[0]
    assert command[1:3] == ["-m", "app.document_worker"]
    assert kwargs["cwd"] == str(document_worker._ROOT)
    assert kwargs["input"] == b"x"
    assert "OPENAI_API_KEY" not in kwargs["env"]
    assert "PROMO_SESSION_SECRET" not in kwargs["env"]
    assert kwargs["timeout"] > 0


def test_timeout_is_reported_as_bounded_failure(monkeypatch):
    def timed_out(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(document_worker.subprocess, "run", timed_out)
    with pytest.raises(ValueError, match="лимит времени"):
        document_worker.run_document_worker("extract", "bad.pdf", b"payload")


def test_crashed_worker_and_invalid_configuration_fail_closed(monkeypatch):
    monkeypatch.setattr(
        document_worker.subprocess, "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, -9, stdout=b""),
    )
    with pytest.raises(ValueError, match="ресурсы"):
        document_worker.run_document_worker("extract", "bad.xlsx", b"payload")

    monkeypatch.setenv("PROMO_DOCUMENT_MEMORY_MB", "16")
    with pytest.raises(ValueError, match="памяти"):
        document_worker.run_document_worker("extract", "bad.xlsx", b"payload")

    monkeypatch.delenv("PROMO_DOCUMENT_MEMORY_MB", raising=False)
    with pytest.raises(ValueError, match="превышает 20 МБ"):
        document_worker.run_document_worker("extract", "huge.xlsx", b"x" * (20*1024*1024+1))
