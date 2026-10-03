"""Ilk N akademisyen icin LLM gerekcesi.

Kanitlar her hocanin kendi chunk'larindan gelir (search.hoca_kanitlari). Ilanin aradiklari ile hocanin kanitlari
prompt'ta ayri tutulur. CV satirlari ve aranan uzmanliklar NUMARALI verilir; model, aranan her uzmanlik icin
karsilayan CV satirinin numarasini dondurur (metin kopyalatmak alintinin bozulmasina yol aciyordu).
Kaniti olmayan konular "eksik" sayilir ve gerekcenin sonuna eklenir; boylece aranan konular hocaya mal edilemez.
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from backend.api.schemas import IlanOzet
from backend.config import get_settings
from backend.llm import get_llm
from backend.matching.scoring import AcademicScore
from backend.matching.search import ChunkHit

EKSIK_GOSTERIM = 4  # gerekcede en fazla bu kadar eksik konu adi yazilir, fazlasi "+N" olur


class KonuKarsiligi(BaseModel):
    konu_no: int = Field(description="Aranan uzmanlığın numarası (U1, U2 ... -> 1, 2 ...)")
    satir_no: int | None = Field(
        description="Bu konuyu doğrudan ya da açıkça ilişkili biçimde karşılayan CV satırının numarası "
                    "(S12 -> 12). Karşılığı yoksa null."
    )


class Gerekce(BaseModel):
    konu_karsiliklari: list[KonuKarsiligi] = Field(description="Aranan uzmanlıkların HER BİRİ için bir kayıt")
    gerekce: str = Field(
        description="Akademisyenin neden önerildiğini açıklayan EN FAZLA 4 cümlelik Türkçe gerekçe. En güçlü "
                    "2-3 kanıtı somut olarak anar; konuları tek tek saymaz, eksik konuları yazmaz (sistem ekler)."
    )
    kanit_satirlari: list[int] = Field(description="Gerekçede dayanılan CV satırlarının numaraları (2-6 tane)")


_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "Sen bir proje-akademisyen eşleştirme sisteminin açıklama modülüsün. Akademisyenin neden önerildiğini "
     "YALNIZCA numaralı CV satırlarına dayanarak açıkla. Kurallar:\n"
     "1. Önce aranan her uzmanlık (U1, U2 ...) için CV'de karşılığı olan satırın numarasını (S..) bul; yoksa "
     "null bırak. Yöntem/teknik eşdeğerlerini de say (ör. 'Laser Powder Bed Fusion' katmanlı imalattır; "
     "alüminyum ve magnezyum kompozitleri hafif malzemelerdir). Ama yalnızca gerçek teknik eşdeğerleri say; "
     "benzer kelime ya da uzak çağrışım yetmez (ör. biyobozunur implant malzemesi 'geri dönüşüm' değildir, "
     "bir dersin adı tek başına 'akıllı tasarım' değildir). Emin değilsen null bırak.\n"
     "2. İlanın aradığı konular ve hedefleri (ör. enerji verimliliği) akademisyenin özelliği DEĞİLDİR. "
     "Karşılığı null olan bir konuyu gerekçede akademisyene atfetme.\n"
     "3. Gerekçeye somut bir kanıtla başla: hangi yayın, proje, tez, ders ya da anahtar kelime olduğunu an "
     "(ör. 'Al/SiC ve Mg/B4C metal matrisli kompozitler üzerine makaleleri var'). Gerekçe metninde S/U "
     "numaralarını ASLA yazma; numaralar yalnızca alanlarda kullanılır.\n"
     "4. 'X alanında önemli bir uzmanlığa sahiptir', 'büyük avantaj sunar', 'önemli katkı sağlayabilir' gibi "
     "kanıtla gösterilmeyen genel övgüler YASAK. İlişki dolaylıysa dolaylı olduğunu söyle.\n"
     "5. Gerekçe en fazla 4 cümle olsun; karşılanmayan konuları gerekçeye yazma, sistem ayrıca listeler."),
    ("human",
     "## İlan (akademisyenin özelliği değil, aranan şeyler)\nBaşlık: {baslik}\nKonu: {konu}\n"
     "Amaç ve kapsam: {amac}\nAranan uzmanlıklar:\n{uzmanliklar}\n\n"
     "## Akademisyen\n{hoca}\n\n"
     "## CV satırları (gerekçe yalnızca bunlara dayanır)\n{kanitlar}"),
])

rationale_chain = _PROMPT | get_llm(get_settings().gerekce_model).with_structured_output(Gerekce)


@dataclass
class KanitSatiri:
    no: int  # prompt'taki S<no>
    chunk: ChunkHit
    metin: str


def kanit_satirlari(kanitlar: list[ChunkHit]) -> list[KanitSatiri]:
    """Chunk'larin icerik satirlari, 1'den numaralanmis (ilk satir "[Bölüm: ...]" basligidir, numaralanmaz)."""
    satirlar = []
    for h in kanitlar:
        for l in h.icerik.splitlines()[1:]:
            if l.strip():
                satirlar.append(KanitSatiri(len(satirlar) + 1, h, l))
    return satirlar


def _numarali_cv(kanitlar: list[ChunkHit]) -> str:
    satirlar = kanit_satirlari(kanitlar)
    return "\n\n".join(
        "\n".join([h.icerik.splitlines()[0], *(f"S{s.no}: {s.metin}" for s in satirlar if s.chunk is h)])
        for h in kanitlar if h.icerik
    )


def _inputs(ilan: IlanOzet, a: AcademicScore, kanitlar: list[ChunkHit]) -> dict:
    meta = a.profile.metadata
    return {
        "baslik": ilan.baslik,
        "konu": ilan.konu,
        "amac": ilan.amac_kapsam,
        "uzmanliklar": "\n".join(f"U{i}: {u}" for i, u in enumerate(ilan.aranan_uzmanliklar, 1))
                       or "(belirtilmemiş)",
        "hoca": f"{meta.get('unvan') or ''} {meta['ad_soyad']} - {meta.get('bolum') or ''}".strip(),
        "kanitlar": _numarali_cv(kanitlar) or "(eşleşen CV parçası yok)",
    }


async def explain(
    ilan: IlanOzet, academics: list[AcademicScore], kanitlar: dict[str, list[ChunkHit]]
) -> list[Gerekce]:
    return await rationale_chain.abatch([_inputs(ilan, a, kanitlar.get(a.hoca_id, [])) for a in academics])


# --- Dogrulama ---------------------------------------------------------------------

_NOKTALAMA = re.compile(r"[^\w]+", re.UNICODE)


def sade(metin: str) -> str:
    """Karsilastirma bicimi: kucuk harf, noktalama ve sapka/aksan yok, HTML varliklari cozulmus.
    Ayni yayin birden fazla chunk'ta tekrarlandiginda kanit listesini tekillestirmek icin."""
    metin = unicodedata.normalize("NFKD", html.unescape(metin).casefold())
    return _NOKTALAMA.sub(" ", "".join(c for c in metin if not unicodedata.combining(c))).strip()


def dayanilan_satirlar(g: Gerekce, satirlar: list[KanitSatiri]) -> list[KanitSatiri]:
    """Modelin gerekcede ve konu karsiliklarinda gosterdigi, gercekten var olan satirlar (prompt sirasiyla).
    Var olmayan numaralar duser."""
    nolar = set(g.kanit_satirlari) | {k.satir_no for k in g.konu_karsiliklari if k.satir_no is not None}
    return [s for s in satirlar if s.no in nolar]


def eksik_konular(g: Gerekce, ilan: IlanOzet, satirlar: list[KanitSatiri]) -> list[str]:
    """Aranan uzmanliklardan, model tarafindan var olan bir CV satiriyla karsilanmayanlar (ilandaki sirayla).
    Modelin hic kayit acmadigi konular da eksik sayilir."""
    gecerli = {s.no for s in satirlar}
    karsilanan = {k.konu_no for k in g.konu_karsiliklari if k.satir_no in gecerli}
    return [u for i, u in enumerate(ilan.aranan_uzmanliklar, 1) if i not in karsilanan]


# Talimata ragmen metne sizan satir/konu numaralari: "(S7)", "(S10, S12)", "tezleri S1 ve S2 ile"
_NUMARA_PARANTEZ = re.compile(r"\s*\((?:\s*[SU]\d+\s*(?:,|ve|-|–)?)+\s*\)")
_NUMARA = re.compile(r"\s*\b[SU]\d+(?:\s*(?:,|ve|-|–)\s*[SU]?\d+)*\b")


def _numarasiz(metin: str) -> str:
    return _NUMARA.sub("", _NUMARA_PARANTEZ.sub("", metin)).replace(" ,", ",").replace(" .", ".")


def gerekce_metni(g: Gerekce, eksikler: list[str]) -> str:
    """Gosterilen gerekce: LLM metni (satir numaralari temizlenmis) + kanitlarda karsiligi olmayan aranan
    konular (sabit bicimde)."""
    metin = _numarasiz(g.gerekce).rstrip()
    if not eksikler:
        return metin
    adlar = ", ".join(eksikler[:EKSIK_GOSTERIM])
    fazla = f" (+{len(eksikler) - EKSIK_GOSTERIM})" if len(eksikler) > EKSIK_GOSTERIM else ""
    return f"{metin} CV'de karşılığı bulunamayan aranan konular: {adlar}{fazla}."
