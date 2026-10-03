"""
"Bana Uygun": CV profili -> acik akademik cagrilar.
  - Semantik : profil ozeti embedding'i ile cagri_vektorleri aramasi
  - BM25     : profil anahtar kelimeleri/alanlari ile cagri metinleri (aday kume kucuk, istek aninda kurulur)
  - Fuzyon   : RRF (CV -> ilan eslestirmesiyle ayni); ilk N icin LLM neden/eksik aciklamasi
"""

from __future__ import annotations

from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_postgres.v2.hybrid_search_config import reciprocal_rank_fusion
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from backend.api.schemas import BanaUygunCagri, CagriOzet
from backend.cagrilar.db import cagrilar, durum, get_engine
from backend.cagrilar.index import cagri_metni
from backend.config import get_settings
from backend.indexing.profile import AkademikProfil, profile_text
from backend.llm import get_embeddings, get_llm
from backend.matching.ilan_extract import fold
from backend.matching.scoring import to_percent
from backend.matching.search import tokenize
from backend.vectorstore import get_cagri_store, init_cagri_table


class Uygunluk(BaseModel):
    neden: str = Field(description="Çağrının bu akademisyene neden uygun olduğu, 1-2 cümle, ikinci tekil şahıs "
                                   "('... çalışmalarınız ...'). Yalnızca verilen profile dayan.")
    eksik: str | None = Field(None, description="Profilin çağrı için zayıf kaldığı nokta, 1 cümle; yoksa null")


_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "Bir akademisyene proje çağrısı öneriyorsun. Akademisyenin profiline ve çağrının konusuna bakarak neden "
     "uygun olduğunu ve varsa eksik kaldığı noktayı kısaca yaz. Profilde olmayan bir bilgi uydurma."),
    ("human", "## Çağrı\n{baslik}\nProgram: {program}\n{ozet}\n\n## Akademisyen profili\n{profil}"),
])

uygunluk_chain = _PROMPT | get_llm().with_structured_output(Uygunluk)


def _adaylar(sadece_acik: bool) -> dict[str, dict]:
    q = select(*[c for c in cagrilar.c if c.name in CagriOzet.model_fields or c.name == "metin"], durum).where(
        cagrilar.c.hedef_kitle == "akademik")
    if sadece_acik:
        q = q.where(or_(cagrilar.c.son_tarih.is_(None), cagrilar.c.son_tarih >= func.current_date()))
    with get_engine().connect() as conn:
        rows = conn.execute(q.order_by(cagrilar.c.yayin_tarihi.desc().nulls_last())).mappings().all()
    # Ayni basligi tekrar yayimlanan hatirlatmalar ("... Basvurular Devam Ediyor"): yalnizca en yenisi
    tekil = {}
    for r in rows:
        tekil.setdefault(fold(r["baslik"]), dict(r))
    return {r["id"]: r for r in tekil.values()}


async def bana_uygun(profile: AkademikProfil, sadece_acik: bool = True) -> list[BanaUygunCagri]:
    adaylar = _adaylar(sadece_acik)
    if not adaylar:
        return []
    s = get_settings()

    init_cagri_table()
    vector = await get_embeddings().aembed_query(profile_text(profile))
    semantic = await get_cagri_store().asimilarity_search_with_score_by_vector(vector, k=1000)
    semantic = [(d, dist) for d, dist in semantic if d.id in adaylar]

    bm25 = BM25Retriever.from_documents(
        [Document(id=i, page_content=cagri_metni(r)) for i, r in adaylar.items()],
        k=len(adaylar), preprocess_func=tokenize,
    ).invoke(" ".join(profile.anahtar_kelimeler + profile.arastirma_alanlari + profile.yontemler))

    fused = reciprocal_rank_fusion(
        [{"id": d.id, "distance": dist} for d, dist in semantic],
        [{"id": d.id, "distance": len(bm25) - r} for r, d in enumerate(bm25)],
        rrf_k=s.rrf_k, fetch_top_k=s.bana_uygun_sonuc,
    )
    if not fused:
        return []

    secilen = [adaylar[row["id"]] for row in fused]
    profil = profile_text(profile)
    aciklamalar = await uygunluk_chain.abatch([{
        "baslik": c["baslik"],
        "program": " ".join(filter(None, [c["program_kodu"], c["program_adi"]])) or "-",
        "ozet": c["ozet"] or c["metin"][:1500],
        "profil": profil,
    } for c in secilen])

    best = fused[0]["distance"]
    return [
        BanaUygunCagri(
            sira=i + 1,
            cagri=CagriOzet(**{k: v for k, v in c.items() if k != "metin"}),
            skor=to_percent(row["distance"], best),
            neden=a.neden,
            eksik=a.eksik,
        )
        for i, (row, c, a) in enumerate(zip(fused, secilen, aciklamalar))
    ]
