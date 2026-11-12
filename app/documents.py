"""Bounded text extraction from office files; documents are untrusted data."""
from __future__ import annotations

import csv
import io
from pathlib import Path

from docx import Document
from openpyxl import load_workbook
from pypdf import PdfReader

ALLOWED_DOCS={'.txt','.md','.csv','.pdf','.docx','.xlsx'}
MAX_PAGES=15
MAX_CHARACTERS=36000


def _decode(raw: bytes):
    for enc in ('utf-8-sig','utf-16','cp1251','latin1'):
        try:return raw.decode(enc)
        except UnicodeDecodeError:pass
    return raw.decode('utf-8',errors='replace')


def extract_text(name:str,raw:bytes):
    ext=Path(name).suffix.lower()
    if ext not in ALLOWED_DOCS: raise ValueError(f'Неподдерживаемый тип документа: {ext or "без расширения"}')
    out=[];warnings=[]
    if ext in {'.txt','.md'}:
        out.append(_decode(raw))
    elif ext=='.csv':
        text=_decode(raw)
        try:
            dialect=csv.Sniffer().sniff(text[:2000],delimiters=',;\t|')
            rows=csv.reader(io.StringIO(text),dialect)
        except csv.Error:
            rows=csv.reader(io.StringIO(text),delimiter=';')
        for i,row in enumerate(rows):
            if i>=250:break
            out.append(' | '.join(str(x) for x in row[:16]))
    elif ext=='.pdf':
        try:
            reader=PdfReader(io.BytesIO(raw),strict=False)
            if reader.is_encrypted:
                raise ValueError('PDF защищён паролем')
            for page in reader.pages[:MAX_PAGES]:
                out.append(page.extract_text(extraction_mode='plain') or '')
            if not any(s.strip() for s in out):warnings.append('В PDF нет извлекаемого текста. Для сканов перенесите характеристики вручную.')
            if len(reader.pages)>MAX_PAGES:warnings.append('Обработаны только первые 15 страниц PDF.')
        except ValueError:raise
        except Exception as exc:raise ValueError('Не удалось прочитать PDF: '+str(exc)[:120]) from exc
    elif ext=='.docx':
        try:
            doc=Document(io.BytesIO(raw))
            out.extend([x.text for x in doc.paragraphs[:450]])
            for table in doc.tables[:15]:
                for row in table.rows[:100]:out.append(' | '.join(cell.text.replace('\n',' ') for cell in row.cells[:14]))
        except Exception as exc:raise ValueError('Не удалось прочитать DOCX') from exc
    elif ext=='.xlsx':
        try:
            wb=load_workbook(io.BytesIO(raw),read_only=True,data_only=True)
            for ws in wb.worksheets[:6]:
                out.append('Лист: '+ws.title)
                for i,row in enumerate(ws.iter_rows(max_row=200,max_col=14,values_only=True)):
                    if i>=200:break
                    txt=' | '.join(str(v) if v is not None else '' for v in row)
                    if txt.strip(' |'):out.append(txt)
            wb.close()
        except Exception as exc:raise ValueError('Не удалось прочитать XLSX') from exc
    text='\n'.join(out)
    if len(text)>MAX_CHARACTERS:
        warnings.append('Текст ограничен 36 000 символами; проверьте обрезанный конец.')
        text=text[:MAX_CHARACTERS]
    return text,warnings


def heuristics(text:str):
    """Human-reviewed suggestions; no automatic trust or calculation."""
    results=[]
    for line in text.splitlines():
        line=line.strip().replace('\t',' | ')
        if 2<=len(line)<=160 and (' | ' in line or ': ' in line):
            sep=' | ' if ' | ' in line else ': '
            a,b=line.split(sep,1)
            a=a.strip(' :-|');b=b.strip(' :-|')
            if 2<=len(a)<=52 and 1<=len(b)<=90 and b and a.lower() not in {'лист','sheet'}:
                results.append([a,b])
    return results[:24]


def pdf_first_page_png(raw:bytes)->bytes:
    """Convert only the first page of a user-supplied PDF drawing to pixels."""
    try:
        import fitz  # PyMuPDF, sandbox-free direct rasterization: no shell execution
        with fitz.open(stream=raw,filetype='pdf') as document:
            if document.needs_pass:raise ValueError('PDF-чертёж защищён паролем')
            if not document.page_count:raise ValueError('PDF-чертёж не содержит страниц')
            page=document.load_page(0)
            pix=page.get_pixmap(matrix=fitz.Matrix(1.5,1.5),alpha=False)
            if pix.width*pix.height>26_000_000:raise ValueError('PDF-чертёж слишком крупный')
            return pix.tobytes('png')
    except ValueError:raise
    except Exception as exc:raise ValueError('Не удалось прочитать первую страницу PDF-чертежа') from exc
