"""Ilk N akademisyen icin, en yuksek skorlu chunk'lari kanit olarak kullanan LLM gerekcesi."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from backend.api.schemas import IlanOzet
from backend.llm import get_llm
from backend.matching.scoring import AcademicScore


class Gerekce(BaseModel):
    gerekce: str = Field(
        description="Akademisyenin bu ilan için neden uygun olduğunu açıklayan 2-4 cümlelik Türkçe gerekçe. "
                    "Yalnızca verilen kanıtlara dayan; eksik kaldığı noktalar varsa belirt."
    )
    kanit_maddeleri: list[str] = Field(
        description="Gerekçeyi destekleyen, kanıt listesinden AYNEN kopyalanmış 2-6 satır"
    )


_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "Sen bir proje-akademisyen eşleştirme sisteminin açıklama modülüsün. Verilen ilan özeti ve "
     "akademisyenin CV'sinden alınan kanıt satırlarına bakarak akademisyenin neden önerildiğini açıkla. "
     "Kanıtlarda olmayan bir bilgi uydurma."),
    ("human",
     "## İlan\nBaşlık: {baslik}\nKonu: {konu}\nAmaç ve kapsam: {amac}\nAranan uzmanlıklar: {uzmanliklar}\n\n"
     "## Akademisyen\n{hoca}\nAraştırma alanları: {alanlar}\n\n## Kanıtlar (CV'den)\n{kanitlar}"),
])

rationale_chain = _PROMPT | get_llm().with_structured_output(Gerekce)


def _inputs(ilan: IlanOzet, a: AcademicScore) -> dict:
    meta = a.profile.metadata
    return {
        "baslik": ilan.baslik,
        "konu": ilan.konu,
        "amac": ilan.amac_kapsam,
        "uzmanliklar": ", ".join(ilan.aranan_uzmanliklar),
        "hoca": f"{meta.get('unvan') or ''} {meta['ad_soyad']} - {meta.get('bolum') or ''}".strip(),
        "alanlar": ", ".join(meta.get("profil", {}).get("arastirma_alanlari", [])),
        "kanitlar": "\n\n".join(h.icerik for h in a.top_chunks) or "(eşleşen CV parçası yok)",
    }


async def explain(ilan: IlanOzet, academics: list[AcademicScore]) -> list[Gerekce]:
    return await rationale_chain.abatch([_inputs(ilan, a) for a in academics])
