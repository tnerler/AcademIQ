"""
Eslestirme akisi: ilan PDF -> Markdown -> LLM ile sorgu -> embedding -> hibrit arama
-> akademisyen skorlama -> hoca bazinda kanit secimi -> LLM gerekce -> MatchResponse

CLI ile deneme:
  uv run python -m backend.matching.pipeline data/raw/proje_ilanlari/duz_metin/I003_stemegitiminde.pdf
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import threading
from pathlib import Path

from backend.api.schemas import EslesmeSonucu, HocaOzet, IlanOzet, Kanit, MatchResponse
from backend.indexing.parser import parse_pdf
from backend.indexing.sections import SECTION_LABELS
from backend.llm import get_embeddings
from backend.matching.ilan_extract import extract_ilan, keyword_query
from backend.matching.rationale import (
    Gerekce, KanitSatiri, dayanilan_satirlar, eksik_konular, explain, gerekce_metni, kanit_satirlari, sade,
)
from backend.matching.scoring import AcademicScore, score_academics, to_percent
from backend.matching.search import ChunkHit, hoca_kanitlari, hybrid_chunk_search, profile_ranking

# PyMuPDF thread-safe degil: eszamanli isteklerde parse islemleri siraya alinir
PARSE_LOCK = threading.Lock()


def _parse(pdf_bytes: bytes) -> str:
    with PARSE_LOCK, tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(pdf_bytes)
        tmp.flush()
        return parse_pdf(Path(tmp.name), use_ocr=False).markdown


def hoca_ozet(meta: dict) -> HocaOzet:
    return HocaOzet(
        id=meta["hoca_id"],
        unvan=meta.get("unvan"),
        ad_soyad=meta["ad_soyad"],
        universite=meta.get("universite"),
        fakulte=meta.get("fakulte"),
        bolum=meta.get("bolum"),
        arastirma_alanlari=meta.get("profil", {}).get("arastirma_alanlari", []),
    )


def _evidence(satirlar: list[KanitSatiri], dayanilan: list[KanitSatiri], best_sim: float) -> list[Kanit]:
    """Kanit olarak modelin dayandigi satirlar bolume gore gruplanip gosterilir (ayni yayin birden fazla chunk'ta
    olabildigi icin tekillestirilir). Model hic satir gostermediyse en benzer iki chunk'in ilk satirlari."""
    if not dayanilan:
        en_iyi = sorted({id(s.chunk): s.chunk for s in satirlar}.values(), key=lambda h: -h.benzerlik)[:2]
        dayanilan = [s for h in en_iyi for s in [x for x in satirlar if x.chunk is h][:3]]

    gruplar: dict[str, Kanit] = {}
    gorulen = set()
    for s in dayanilan:
        if (anahtar := sade(s.metin)) in gorulen:
            continue
        gorulen.add(anahtar)
        h = s.chunk
        k = gruplar.setdefault(h.bolum, Kanit(bolum=h.bolum, bolum_etiketi=SECTION_LABELS.get(h.bolum, h.bolum),
                                              maddeler=[], skor=0.0))
        k.maddeler.append(s.metin)
        k.skor = max(k.skor, to_percent(h.benzerlik, best_sim))
    return sorted(gruplar.values(), key=lambda k: k.skor, reverse=True)


def _sonuc(
    i: int, a: AcademicScore, g: Gerekce, ilan: IlanOzet, kanitlar: list[ChunkHit], best: float, best_sim: float,
) -> EslesmeSonucu:
    satirlar = kanit_satirlari(kanitlar)
    return EslesmeSonucu(
        sira=i + 1,
        hoca=hoca_ozet(a.profile.metadata),
        skor=to_percent(a.score, best),
        gerekce=gerekce_metni(g, eksik_konular(g, ilan, satirlar)),
        kanitlar=_evidence(satirlar, dayanilan_satirlar(g, satirlar), best_sim),
    )


async def match(pdf_bytes: bytes) -> MatchResponse:
    return await match_text(await asyncio.to_thread(_parse, pdf_bytes))


async def match_text(ilan_metni: str) -> MatchResponse:
    """Ilan metni (PDF'ten cikarilmis Markdown ya da kullanicinin yapistirdigi duz metin) ile eslestirme."""
    ilan: IlanOzet = await extract_ilan(ilan_metni)

    query_vector = await get_embeddings().aembed_query(ilan.sorgu_metni)
    hits, profiles = await asyncio.gather(
        hybrid_chunk_search(query_vector, keyword_query(ilan)),
        profile_ranking(query_vector),
    )
    academics = score_academics(hits, profiles)
    kanitlar = await hoca_kanitlari(query_vector, keyword_query(ilan), [a.hoca_id for a in academics])
    gerekceler = await explain(ilan, academics, kanitlar)

    best = academics[0].score if academics else 0.0
    best_sim = max((h.benzerlik for hs in kanitlar.values() for h in hs), default=0.0)
    return MatchResponse(
        ilan=ilan,
        sonuclar=[_sonuc(i, a, g, ilan, kanitlar.get(a.hoca_id, []), best, best_sim)
                  for i, (a, g) in enumerate(zip(academics, gerekceler))],
    )


if __name__ == "__main__":
    result = asyncio.run(match(Path(sys.argv[1]).read_bytes()))
    print(result.model_dump_json(indent=2))
