"""
Temizlenmis bolum maddelerini LangChain Document chunk'larina boler.

Her bolum tek chunk olur; token siniri asilirsa RecursiveCharacterTextSplitter
madde sinirlarinda (satir sonu) boler ve chunk_overlap_tokens kadar ortusme birakir.
Her chunk'in basina bolum etiketi eklenir, boylece embedding bolum baglamini da tasir.
"""

from __future__ import annotations

from functools import lru_cache

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from backend.config import get_settings
from backend.indexing.sections import SECTION_LABELS


@lru_cache
def _splitter() -> RecursiveCharacterTextSplitter:
    s = get_settings()
    return RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name="o200k_base",
        chunk_size=s.chunk_max_tokens - 15,  # bolum etiketi icin pay
        chunk_overlap=s.chunk_overlap_tokens,
        separators=["\n", "; ", " "],  # once madde sinirlari
    )


def build_chunks(hoca_id: str, sections: dict[str, list[str]]) -> list[Document]:
    """sections: bolum anahtari (SECTION_LABELS) -> madde listesi (cv_extract.arama_bolumleri)."""
    docs: list[Document] = []
    for bolum, items in sections.items():
        if not items:
            continue
        prefix = f"[Bölüm: {SECTION_LABELS[bolum]}]\n"
        for text in _splitter().split_text("\n".join(items)):
            docs.append(Document(
                page_content=prefix + text,
                metadata={"hoca_id": hoca_id, "bolum": bolum, "sira": len(docs)},
            ))
    return docs
