"""
Eslestirme akisi: ilan PDF -> Markdown -> LLM ile sorgu -> embedding -> hibrit arama
-> akademisyen skorlama -> LLM gerekce -> MatchResponse

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
from backend.matching.rationale import Gerekce, explain
from backend.matching.scoring import AcademicScore, score_academics, to_percent
from backend.matching.search import hybrid_chunk_search, profile_ranking

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


def _evidence(a: AcademicScore, g: Gerekce, best_chunk: float) -> list[Kanit]:
    """LLM'in sectigi kanit satirlarini ait olduklari chunk'a gore gruplar.
    LLM'in CV'de olmayan (uydurma) satirlari atilir; hic secim yoksa chunk'in ilk satirlari gosterilir."""
    chosen = {line.strip() for line in g.kanit_maddeleri}
    kanitlar = []
    for h in a.top_chunks:
        lines = [l for l in h.icerik.splitlines()[1:] if l.strip()]  # ilk satir "[Bölüm: ...]"
        picked = [l for l in lines if l.strip() in chosen] or lines[:3]
        kanitlar.append(Kanit(
            bolum=h.bolum,
            bolum_etiketi=SECTION_LABELS.get(h.bolum, h.bolum),
            maddeler=picked,
            skor=to_percent(h.rrf, best_chunk),
        ))
    return kanitlar


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
    gerekceler = await explain(ilan, academics)

    best = academics[0].score if academics else 0.0
    best_chunk = hits[0].rrf if hits else 0.0
    return MatchResponse(
        ilan=ilan,
        sonuclar=[
            EslesmeSonucu(
                sira=i + 1,
                hoca=hoca_ozet(a.profile.metadata),
                skor=to_percent(a.score, best),
                gerekce=g.gerekce,
                kanitlar=_evidence(a, g, best_chunk),
            )
            for i, (a, g) in enumerate(zip(academics, gerekceler))
        ],
    )


if __name__ == "__main__":
    result = asyncio.run(match(Path(sys.argv[1]).read_bytes()))
    print(result.model_dump_json(indent=2))
