"""
Eslestirme kalitesi degerlendirmesi (Faz 5).

eval/gold.json: her ilan icin beklenen (uygun) akademisyen id'leri, elle doldurulur:
  {"I003_stemegitiminde": ["H023_Cem_Kilic", "H043_Serap_Ozturk"], ...}
Dosya yoksa tum ilanlar icin bos bir sablon olusturulur ve etiketlemeye yardimci olmak icin
tam sistemin top-10 onerisi yazdirilir.

Metrikler: Hit@5 (beklenenlerden en az biri ilk 5'te mi), Recall@5, MRR.
Karsilastirilan modlar: sadece BM25 / sadece semantik / hibrit / hibrit + profil (tam sistem).

LLM ilan cikarimi ve sorgu embedding'i eval/cache/ altinda saklanir; tekrar calistirmak ucretsizdir.

Kullanim:
  uv run python -m eval.run_eval
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from backend.api.schemas import IlanOzet
from backend.config import PROJECT_ROOT
from backend.indexing.parser import collect_pdfs, parse_pdf
from backend.llm import get_embeddings
from backend.matching.ilan_extract import extract_ilan, keyword_query
from backend.matching.scoring import score_academics
from backend.matching.search import hybrid_chunk_search, profile_ranking

EVAL_DIR = Path(__file__).parent
GOLD = EVAL_DIR / "gold.json"
CACHE = EVAL_DIR / "cache"
ILAN_DIR = PROJECT_ROOT / "data" / "raw" / "proje_ilanlari"

MODES = {
    "bm25":            dict(use_semantic=False, use_bm25=True,  use_profile=False),
    "semantik":        dict(use_semantic=True,  use_bm25=False, use_profile=False),
    "hibrit":          dict(use_semantic=True,  use_bm25=True,  use_profile=False),
    "hibrit+profil":   dict(use_semantic=True,  use_bm25=True,  use_profile=True),
}


async def load_query(pdf: Path) -> tuple[IlanOzet, list[float]]:
    CACHE.mkdir(exist_ok=True)
    cache = CACHE / f"{pdf.stem}.json"
    if cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
        return IlanOzet(**data["ilan"]), data["vector"]
    ilan = await extract_ilan(parse_pdf(pdf, use_ocr=False).markdown)
    vector = await get_embeddings().aembed_query(ilan.sorgu_metni)
    cache.write_text(json.dumps({"ilan": ilan.model_dump(), "vector": vector}, ensure_ascii=False), encoding="utf-8")
    return ilan, vector


async def rank(ilan: IlanOzet, vector: list[float], use_semantic: bool, use_bm25: bool, use_profile: bool) -> list[str]:
    hits = await hybrid_chunk_search(vector, keyword_query(ilan), use_semantic=use_semantic, use_bm25=use_bm25)
    profiles = await profile_ranking(vector)
    return [a.hoca_id for a in score_academics(hits, profiles, use_profile=use_profile, limit=len(profiles))]


async def main() -> None:
    pdfs = collect_pdfs(ILAN_DIR)
    queries = {p.stem: await load_query(p) for p in pdfs}

    if not GOLD.exists():
        GOLD.write_text(json.dumps({k: [] for k in queries}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{GOLD} olusturuldu; beklenen akademisyenleri doldurup tekrar calistirin.\n")
        for key, (ilan, vector) in queries.items():
            ranked = await rank(ilan, vector, **MODES["hibrit+profil"])
            print(f"{key}: {ilan.baslik}\n  aranan: {', '.join(ilan.aranan_uzmanliklar)}\n  top-10: {ranked[:10]}\n")
        return

    gold = {k: set(v) for k, v in json.loads(GOLD.read_text(encoding="utf-8")).items() if v}
    if not gold:
        print(f"{GOLD} bos; once beklenen akademisyenleri doldurun.")
        return

    print(f"{len(gold)} etiketli ilan\n")
    print(f"{'mod':<16}{'Hit@5':>8}{'Recall@5':>10}{'MRR':>8}")
    for mode, flags in MODES.items():
        hit = recall = mrr = 0.0
        for key, expected in gold.items():
            ranked = await rank(*queries[key], **flags)
            top5 = set(ranked[:5])
            hit += bool(top5 & expected)
            recall += len(top5 & expected) / len(expected)
            first = next((i for i, h in enumerate(ranked) if h in expected), None)
            mrr += 1 / (first + 1) if first is not None else 0
        n = len(gold)
        print(f"{mode:<16}{hit / n:>8.3f}{recall / n:>10.3f}{mrr / n:>8.3f}")


if __name__ == "__main__":
    asyncio.run(main())
