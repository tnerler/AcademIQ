"""
Akademisyen bazinda skorlama:
  skor = (en iyi N chunk'in RRF toplami / N) + profil RRF terimi (1 / (k + profil_sirasi))
N sabit oldugu icin tek bir sansli eslesme, tutarli sekilde eslesen bir profili gecemez.
UI icin skorlar en iyi adaya gore 0-100'e olceklenir.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from langchain_core.documents import Document

from backend.config import get_settings
from backend.matching.search import ChunkHit


@dataclass
class AcademicScore:
    hoca_id: str
    profile: Document
    score: float
    top_chunks: list[ChunkHit]


def score_academics(
    hits: list[ChunkHit], profiles: list[Document], use_profile: bool = True, limit: int | None = None
) -> list[AcademicScore]:
    s = get_settings()
    n = s.chunks_per_academic

    by_hoca: dict[str, list[ChunkHit]] = defaultdict(list)
    for h in hits:  # hits RRF'e gore azalan sirada
        by_hoca[h.hoca_id].append(h)

    scores = []
    for rank, profile in enumerate(profiles):
        hoca_id = profile.metadata["hoca_id"]
        top = by_hoca.get(hoca_id, [])[:n]
        chunk_score = sum(h.rrf for h in top) / n
        profile_score = 1.0 / (s.rrf_k + rank) if use_profile else 0.0
        scores.append(AcademicScore(hoca_id, profile, chunk_score + profile_score, top))

    scores.sort(key=lambda a: a.score, reverse=True)
    return scores[: limit or s.result_count]


def to_percent(value: float, best: float) -> float:
    return round(100 * value / best, 1) if best > 0 else 0.0
