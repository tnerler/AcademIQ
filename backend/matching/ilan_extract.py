"""Proje ilani Markdown'indan LLM ile arama sorgusu ve arayuz bilgilerini cikarir."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from backend.api.schemas import IlanOzet
from backend.llm import get_llm

MAX_CHARS = 15000

_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "Sen proje çağrılarını analiz eden bir asistansın. Verilen proje ilanından, ilana uygun akademisyeni "
     "bulmak için gereken akademik gereksinimleri (konu, amaç, kapsam, aranan uzmanlıklar) çıkar ve arama "
     "sorgusunu üret. Tarih, bütçe, süre, yer ve başvuru koşullarını yalnızca 'meta' alanına yaz; bunlar "
     "aramaya dahil edilmeyecek. 'sorgu_metni' ve 'anahtar_kelimeler' yalnızca bilimsel alan, konu ve "
     "yöntemleri içermeli; unvan şartı, proje yürütücülüğü deneyimi, yıl sayısı gibi başvuru koşullarını "
     "bu alanlara yazma. İlanda olmayan bilgiyi uydurma."),
    ("human", "{ilan}"),
])

ilan_chain = _PROMPT | get_llm().with_structured_output(IlanOzet)


async def extract_ilan(markdown: str) -> IlanOzet:
    return await ilan_chain.ainvoke({"ilan": markdown[:MAX_CHARS]})


def keyword_query(ilan: IlanOzet) -> str:
    """BM25 sorgusu: anahtar kelimeler + aranan uzmanliklar."""
    return " ".join(ilan.anahtar_kelimeler + ilan.aranan_uzmanliklar)
