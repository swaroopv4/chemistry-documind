from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import tiktoken
from pypdf import PdfReader


def ingest_file(path: str | Path, chunk_size: int = 400,
                chunk_overlap: int = 50) -> list[Chunk]:
    from core.formats import extract_sections
    path = Path(path)
    sections = extract_sections(path)
    if not sections:
        raise ValueError(f"No searchable text in {path.name}. Image-only documents need OCR.")
    return chunk_sections(sections, path.name, path.suffix.lower().lstrip("."),
                          chunk_size, chunk_overlap)


def chunk_sections(sections, doc_name, file_type, chunk_size=400, chunk_overlap=50):
    if chunk_size <= 0 or not 0 <= chunk_overlap < chunk_size:
        raise ValueError("Require chunk_size > 0 and 0 <= chunk_overlap < chunk_size")
    if chunk_size > 800:
        raise ValueError("Chunk size must be at most 800 tokens for hosted embeddings")
    chunks = []
    for section in sections:
        prefix = section.prefix + "\n" if section.prefix else ""
        capacity = chunk_size - count_tokens(prefix)
        if capacity <= chunk_overlap:
            raise ValueError(f"Increase chunk size or reduce overlap for {section.locator}")
        metadata = {"locator": section.locator, "file_type": file_type}
        if getattr(section,'ocr',False):
            metadata.update(ocr=True,ocr_confidence=section.ocr_confidence)
        if section.prefix:
            # Chemical rows are indivisible: repeat identifiers on each chunk and
            # do not cut atom records, quoted CIF values, or their tag assignments.
            buffer = []
            for line in section.text.splitlines():
                if count_tokens(prefix + line) > chunk_size:
                    raise ValueError(f"A record in {section.locator} exceeds chunk size; increase it")
                if buffer and count_tokens(prefix + "\n".join(buffer + [line])) > chunk_size:
                    text = prefix + "\n".join(buffer)
                    chunks.append(Chunk(text, doc_name, section.number, len(chunks), count_tokens(text), metadata.copy()))
                    buffer = []
                buffer.append(line)
            if buffer:
                text = prefix + "\n".join(buffer)
                chunks.append(Chunk(text, doc_name, section.number, len(chunks), count_tokens(text), metadata.copy()))
        else:
            tokens = _ENCODER.encode(section.text)
            start = 0
            while start < len(tokens):
                end = min(start + capacity, len(tokens))
                text = _ENCODER.decode(tokens[start:end])
                chunks.append(Chunk(text, doc_name, section.number, len(chunks), count_tokens(text), metadata.copy()))
                if end == len(tokens):
                    break
                start = end - chunk_overlap
    return chunks


def ingest_pdf(
    pdf_path: str | Path,
    chunk_size: int = 400,
    chunk_overlap: int = 50,
) -> list[Chunk]:
    pdf_path = Path(pdf_path)
    doc_name = pdf_path.stem
    pages = extract_text_from_pdf(pdf_path)
    if not pages:
        raise ValueError(f"No text found {pdf_path.name}")
    chunks = chunk_pages(pages, doc_name, chunk_size, chunk_overlap)
    return chunks


def extract_text_from_pdf(pdf_path: str | Path,ocr_results=None) -> list[tuple[int, str]]:
    from core.settings import get_settings
    settings = get_settings()
    reader = PdfReader(str(pdf_path))
    pages,ocr_pages = [],0
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        text = _clean_text(text)
        if not text.strip() and settings['ocr_enabled']:
            ocr_pages += 1
            if ocr_pages>settings['ocr_max_pages']:
                raise ValueError('This PDF exceeded the OCR page limit; split it into smaller documents.')
            from core.ocr import pdf_page
            text,confidence = pdf_page(pdf_path,i)
            text = _clean_text(text)
            if ocr_results is not None:
                ocr_results[i] = confidence
        if text.strip():
            pages.append((i, text))
    return pages


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)  # dehyphenate
    return text.strip()


_ENCODER = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_ENCODER.encode(text))


def chunk_pages(
    pages: list[tuple[int, str]],
    doc_name: str,
    chunk_size: int = 400,
    chunk_overlap: int = 50,
) -> list[Chunk]:
    # Added validation: the video's slider can otherwise produce an infinite loop.
    if chunk_size <= 0 or not 0 <= chunk_overlap < chunk_size:
        raise ValueError("Require chunk_size > 0 and 0 <= chunk_overlap < chunk_size")

    all_tokens: list[int] = []
    token_page_map: list[int] = []
    for page_num, text in pages:
        tokens = _ENCODER.encode(text)
        all_tokens.extend(tokens)
        token_page_map.extend([page_num] * len(tokens))

    chunks: list[Chunk] = []
    start = 0
    chunk_idx = 0
    while start < len(all_tokens):
        end = min(start + chunk_size, len(all_tokens))
        token_slice = all_tokens[start:end]
        text = _ENCODER.decode(token_slice)
        page_num = token_page_map[start]
        chunks.append(Chunk(
            text=text,
            doc_name=doc_name,
            page_num=page_num,
            chunk_index=chunk_idx,
            token_count=len(token_slice),
        ))
        chunk_idx += 1
        start += chunk_size - chunk_overlap
    return chunks


@dataclass
class Chunk:
    text: str
    doc_name: str
    page_num: int
    chunk_index: int
    token_count: int
    metadata: dict = field(default_factory=dict)

    def to_pinecone_metadata(self) -> dict:
        return {
            "text": self.text,
            "doc_name": self.doc_name,
            "page_num": self.page_num,
            "chunk_index": self.chunk_index,
            "token_count": self.token_count,
            **self.metadata,
        }
