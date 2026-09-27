"""LLM (LangChain structured output) ile CV'den yapilandirilmis akademik profil ozeti cikarir."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from backend.indexing.sections import SECTION_LABELS
from backend.llm import get_llm


class AkademikProfil(BaseModel):
    arastirma_alanlari: list[str] = Field(description="3-8 ana araştırma alanı, Türkçe")
    yontemler: list[str] = Field(description="Kullandığı yöntem/teknikler (ör. panel veri, derin öğrenme, CRISPR), 3-10 adet")
    anahtar_kelimeler: list[str] = Field(
        description="Aramada kullanılacak 10-20 anahtar kelime; Türkçe ve varsa İngilizce karşılıklarıyla"
    )
    ozet_metni: str = Field(description="Akademisyenin uzmanlığını anlatan 3-5 cümlelik Türkçe özet")


_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "Sen akademik CV'leri analiz eden bir asistansın. Sana bir akademisyenin CV'sinden yalnızca "
     "akademik bölümler (araştırma alanları, eğitim, yayın/proje/tez başlıkları, dersler) verilecek. "
     "Bu içeriğe dayanarak akademisyenin araştırma profilini çıkar. Sadece verilen içerikte geçen "
     "veya doğrudan ondan çıkarılabilen bilgileri kullan; uydurma."),
    ("human", "{cv}"),
])

profile_chain = _PROMPT | get_llm().with_structured_output(AkademikProfil)


def format_sections(sections: dict[str, list[str]]) -> str:
    return "\n\n".join(
        f"## {SECTION_LABELS[key]}\n" + "\n".join(f"- {item}" for item in items)
        for key, items in sections.items()
        if items
    )


def profile_text(profile: AkademikProfil) -> str:
    """Profil embedding'i icin kullanilan metin."""
    return (
        f"{profile.ozet_metni}\n"
        f"Araştırma alanları: {', '.join(profile.arastirma_alanlari)}\n"
        f"Yöntemler: {', '.join(profile.yontemler)}\n"
        f"Anahtar kelimeler: {', '.join(profile.anahtar_kelimeler)}"
    )
