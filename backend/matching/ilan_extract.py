"""Proje ilani Markdown'indan LLM ile arama sorgusu ve arayuz bilgilerini cikarir."""

from __future__ import annotations

import re
import unicodedata

from langchain_core.prompts import ChatPromptTemplate

from backend.api.schemas import IlanMeta, IlanOzet
from backend.llm import get_llm

MAX_CHARS = 15000
MIN_WORD_OVERLAP = 0.5  # bir meta degerinin kelimelerinin en az yarisi ilan metninde gecmeli

_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "Sen proje çağrılarını analiz eden bir asistansın. Verilen proje ilanından, ilana uygun akademisyeni "
     "bulmak için gereken akademik gereksinimleri (konu, amaç, kapsam, aranan uzmanlıklar) çıkar ve arama "
     "sorgusunu üret. Tarih, bütçe, süre, yer ve başvuru koşullarını yalnızca 'meta' alanına yaz; bunlar "
     "aramaya dahil edilmeyecek. 'sorgu_metni' ve 'anahtar_kelimeler' yalnızca bilimsel alan, konu ve "
     "yöntemleri içermeli; unvan şartı, proje yürütücülüğü deneyimi, yıl sayısı gibi başvuru koşullarını "
     "bu alanlara yazma.\n"
     "İlanda olmayan bilgiyi KESİNLİKLE uydurma: 'kurum' ve 'meta' alanlarını (son başvuru, bütçe, süre, yer, "
     "başvuru koşulları) yalnızca metinde açıkça yazıyorsa, metindeki ifadeyle aynen doldur; yazmıyorsa null "
     "ya da boş liste bırak. Metin kısa veya belirsizse bu alanları tahmin etme, tipik ilan değerleriyle "
     "doldurma. 'aranan_uzmanliklar' yalnızca metinde geçen alanları içersin."),
    ("human", "{ilan}"),
])

ilan_chain = _PROMPT | get_llm().with_structured_output(IlanOzet)


async def extract_ilan(markdown: str) -> IlanOzet:
    text = markdown[:MAX_CHARS]
    ilan: IlanOzet = await ilan_chain.ainvoke({"ilan": text})
    return ground_ilan(ilan, text)


def keyword_query(ilan: IlanOzet) -> str:
    """BM25 sorgusu: anahtar kelimeler + aranan uzmanliklar."""
    return " ".join(ilan.anahtar_kelimeler + ilan.aranan_uzmanliklar)


# --- Uydurma meta bilgi filtresi ---------------------------------------------
# LLM prompt'a ragmen kisa/belirsiz metinlerde kurum, butce, sure gibi alanlari
# tipik ilan degerleriyle doldurabiliyor. Bu alanlar ilan metninde gecmiyorsa silinir.

def ground_ilan(ilan: IlanOzet, source: str) -> IlanOzet:
    """kurum, meta ve aranan_uzmanliklar alanlarindan ilan metninde dayanagi olmayan degerleri temizler.
    Arama genislemesi (es anlamli / Ingilizce terimler) anahtar_kelimeler'de kalir."""
    src_words, src_numbers = _words(source), _numbers(source)

    def ok(value: str | None) -> bool:
        return bool(value) and _grounded(value, src_words, src_numbers)

    m = ilan.meta
    return ilan.model_copy(update={
        "kurum": ilan.kurum if ok(ilan.kurum) else None,
        # Hicbiri dogrulanamazsa (ör. yalnizca "NLP" gibi bir kisaltma) LLM'in yorumu korunur
        "aranan_uzmanliklar": [u for u in ilan.aranan_uzmanliklar if ok(u)] or ilan.aranan_uzmanliklar,
        "meta": IlanMeta(
            son_basvuru=m.son_basvuru if ok(m.son_basvuru) else None,
            butce=m.butce if ok(m.butce) else None,
            sure=m.sure if ok(m.sure) else None,
            yer=m.yer if ok(m.yer) else None,
            basvuru_kosullari=[k for k in m.basvuru_kosullari if ok(k)],
        ),
    })


def _grounded(value: str, src_words: set[str], src_numbers: set[str]) -> bool:
    # Degerdeki her sayi metinde gecmeli (500.000 TL, 24 ay, 2025 ...)
    if not _numbers(value) <= src_numbers:
        return False
    words = _words(value)
    if not words:
        return bool(_numbers(value))
    return len(words & src_words) / len(words) >= MIN_WORD_OVERLAP


def _fold(text: str) -> str:
    """Kucuk harf + Turkce karakter/aksan sadelestirme (Görüntü -> goruntu)."""
    text = text.replace("İ", "i").replace("I", "ı").lower().replace("ı", "i")
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def _words(text: str) -> set[str]:
    # Ilk 5 harf: Turkce eklerden bagimsiz karsilastirma (vakfi/vakfinca, doktora/doktorasi)
    return {w[:5] for w in re.findall(r"[a-z]{3,}", _fold(text))}


_MONTHS = ["ocak", "subat", "mart", "nisan", "mayis", "haziran",
           "temmuz", "agustos", "eylul", "ekim", "kasim", "aralik"]


def _numbers(text: str) -> set[str]:
    folded = _fold(text)
    # "31 Aralik 2025" metni, LLM'in "2025-12-31" yazdigi tarihi de dogrulayabilsin
    months = {str(i) for i, ay in enumerate(_MONTHS, 1) if re.search(rf"\b{ay}", folded)}
    text = re.sub(r"(?<=\d)[.,\s](?=\d{3}\b)", "", text)  # binlik ayraclari: 1.500.000 -> 1500000
    return {n.lstrip("0") or "0" for n in re.findall(r"\d+", text)} | months
