"""Duyuru sayfasindan LLM ile cagri karari ve alanlari; uzatma duyurularinda tarih birlestirme."""

from __future__ import annotations

from datetime import date
import json
import re
from typing import Literal
from urllib.parse import urlparse

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from backend.llm import get_llm
from backend.matching.ilan_extract import fold, grounded_in

MAX_CHARS = 15000


class Tarih(BaseModel):
    etiket: str = Field(description="Tarihin ne olduğu, metindeki ifadeyle: ör. '1. Aşama uluslararası başvuru son "
                                    "tarihi', 'Ulusal başvuru e-imza son tarihi', 'Son başvuru'")
    tarih: str = Field(description="YYYY-MM-DD")


class Baglanti(BaseModel):
    etiket: str = Field(description="Bağlantının ne olduğu (sayfadaki link metni değil): ör. 'TÜBİTAK başvuru "
                                    "sistemi', 'Çağrı dokümanı', 'Ortaklık çağrı sayfası'")
    url: str


class CagriCikarim(BaseModel):
    tur: Literal["cagri", "guncelleme", "cagri_degil"] = Field(
        description="cagri: araştırma/Ar-Ge PROJE önerisi kabul eden, açılan ya da açılacak çağrı. "
                    "guncelleme: daha önce açılmış bir çağrının tarihini/takvimini/koşullarını değiştiren duyuru "
                    "(süre uzatma, takvim güncelleme). "
                    "cagri_degil: sonuç, burs, etkinlik, yarışma, ödül, haber, bilgi günü; bir programın kuralları "
                    "hakkında genel bilgilendirme (yeni bir başvuru dönemi/son tarih duyurmuyorsa)."
    )
    sebep: str = Field(description="Kararın tek cümlelik gerekçesi")
    hedef_kitle: Literal["akademik", "sanayi"] = Field(
        description="akademik: üniversite ya da araştırma kurumları başvuru sahibi/ortak olarak başvurabiliyor "
                    "(ARDEB programları, ikili işbirlikleri, Ufuk Avrupa ortaklık çağrıları genellikle akademiktir). "
                    "sanayi: başvuru sahibi yalnızca firma, KOBİ, girişimci ya da kamu kurumu olabiliyor; "
                    "üniversiteler en fazla alt yüklenici/danışman (TEYDEB 15xx/17xx/18xx, EUREKA, BiGG)."
    )
    program_kodu: str | None = Field(
        None, description="Program numarası; başlıkta numara varsa o (ör. '1001', '2518'), yoksa metindeki TÜBİTAK "
                          "program numarası (ör. '1071'), o da yoksa kısaltma (ör. 'SBEP', 'EUREKA'). Yalnızca sayı "
                          "ya da kısaltma, başka kelime yok."
    )
    program_adi: str | None = Field(None, description="Program/ortaklık adı, ör. 'Sürdürülebilir Mavi Ekonomi Ortaklığı'")
    ozet: str | None = Field(None, description="Çağrının konusu ve amacı, 2-3 cümle Türkçe")
    tarihler: list[Tarih] = Field(
        [], description="Metinde AÇIKÇA yazan tüm başvuru/son tarihleri; yayın tarihi ve çağrının açılış tarihi hariç"
    )
    butce: str | None = Field(None, description="Destek üst limiti / bütçe, metinde yazdığı gibi")
    sure: str | None = Field(None, description="Proje süresi, metinde yazdığı gibi")
    basvuru_kosullari: list[str] = Field([], description="Kısa maddeler: kimler başvurabilir, ortak/konsorsiyum şartı vb.")
    baglantilar: list[Baglanti] = Field(
        [], description="Yalnızca verilen bağlantı listesinden: başvuru sistemi, çağrı dokümanı, çağrı/ortaklık sayfası"
    )


_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "Sen TÜBİTAK duyurularını sınıflandıran ve proje çağrılarının bilgilerini çıkaran bir asistansın. "
     "Duyuru yayın tarihi: {yayin_tarihi}. Yılı yazmayan tarihlerde yılı bu tarihe ve metne göre belirle.\n"
     "İlanda olmayan bilgiyi KESİNLİKLE uydurma: alanları yalnızca metinde açıkça yazıyorsa doldur, "
     "yazmıyorsa null ya da boş liste bırak."),
    ("human", "{metin}\n\n## Sayfadaki bağlantılar\n{baglantilar}"),
])

cikarim_chain = _PROMPT | get_llm().with_structured_output(CagriCikarim)


class BirlesikTarihler(BaseModel):
    tarihler: list[Tarih] = Field(description="Güncellemeden sonra geçerli olan TÜM tarihler")


_MERGE_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "Bir proje çağrısının kayıtlı tarihleri ve bu çağrıyla ilgili yeni bir duyuru verilecek. Duyuruda değişen "
     "tarihleri güncelle, yeni tarihleri ekle, duyuruda geçmeyen kayıtlı tarihleri aynen koru. Tarihleri "
     "YYYY-MM-DD yaz. Duyuru yayın tarihi: {yayin_tarihi}."),
    ("human", "## Kayıtlı tarihler\n{mevcut}\n\n## Yeni duyuru\n{metin}"),
])

merge_chain = _MERGE_PROMPT | get_llm().with_structured_output(BirlesikTarihler)


def cikar(metin: str, baglantilar: list[tuple[str, str]], yayin_tarihi: date | None,
          baslik: str | None = None) -> CagriCikarim:
    text = metin[:MAX_CHARS]
    c: CagriCikarim = cikarim_chain.invoke({
        "metin": text,
        "baglantilar": "\n".join(f"- {etiket}: {url}" for etiket, url in baglantilar) or "(yok)",
        "yayin_tarihi": yayin_tarihi or "bilinmiyor",
    })
    return ground(c, text, {url for _, url in baglantilar}, baslik)


# Baslikta gecen TUBITAK program numarasi (1001, 2247-C, 2518 ...); 20xx yillari haric
_PROGRAM_NO = re.compile(r"(?<![\d.,])(?!20\d\d)([1-4]\d{3})(?![\d.,])")


_KISALTMA = re.compile(r"[A-Z0-9+]{2,10}")


def program_kodu(llm_kodu: str | None, baslik: str | None) -> str | None:
    """Baslikta program numarasi varsa o kullanilir (LLM bazen metindeki baska bir programi seciyor).
    Yoksa LLM'in kodunun ilk parcasi ('EUROSTARS-KOORD-DEST-2026-1' -> 'EUROSTARS', 'DUT_2026_1' -> 'DUT');
    'null' gibi bos degerler None olur."""
    if baslik and (m := _PROGRAM_NO.search(baslik)):
        return m.group(1)
    ilk = re.split(r"[\s,;/_-]+", (llm_kodu or "").strip().upper(), maxsplit=1)[0]
    return ilk if _KISALTMA.fullmatch(ilk) and ilk not in ("NULL", "NONE", "YOK") else None


# TEYDEB (15xx-18xx) ve firma odakli uluslararasi programlar: LLM bunlari zaman zaman akademik etiketliyor
_SANAYI_KOD = re.compile(r"1[5-8]\d\d")
_SANAYI_BASLIK = re.compile(r"\b(eureka|eurostars|ira-sme|cornet|bigg|kobi|girisim|startup|hizlandirici)")


def hedef_kitle(llm_hedef: str, kod: str | None, baslik: str | None) -> str:
    if (kod and _SANAYI_KOD.fullmatch(kod)) or _SANAYI_BASLIK.search(fold(baslik or "")):
        return "sanayi"
    return llm_hedef


def tarihleri_birlestir(mevcut: list[dict], metin: str, yayin_tarihi: date | None) -> list[dict]:
    """Uzatma/guncelleme duyurusunu kayitli tarihlere uygular; sonuc [{etiket, tarih}] (ISO)."""
    text = metin[:MAX_CHARS]
    r: BirlesikTarihler = merge_chain.invoke({
        "mevcut": json.dumps(mevcut, ensure_ascii=False) if mevcut else "(yok)",
        "metin": text,
        "yayin_tarihi": yayin_tarihi or "bilinmiyor",
    })
    # Yeni tarihler duyuruda, korunanlar kayitli listede gecmeli
    return en_gec_etiketler(_tarihler(r.tarihler, text + "\n" + json.dumps(mevcut, ensure_ascii=False)))


def en_gec_etiketler(tarihler: list[dict]) -> list[dict]:
    """Ayni etiketli tarihlerden yalnizca en geci kalir: uzatma tarihi ileri atar, LLM ise birlestirirken
    eski tarihi de tutabiliyor ('son basvuru: 21 Eylul' + 'son basvuru: 30 Eylul')."""
    son: dict[str, dict] = {}
    for t in tarihler:
        key = fold(t["etiket"])
        if key not in son or t["tarih"] > son[key]["tarih"]:
            son[key] = t
    return sorted(son.values(), key=lambda t: t["tarih"])


# --- Uydurma bilgi filtresi (ilan_extract.ground_ilan ile ayni mantik) -------

def ground(c: CagriCikarim, source: str, urls: set[str], baslik: str | None = None) -> CagriCikarim:
    ok = grounded_in(source)
    kod = program_kodu(c.program_kodu, baslik)
    return c.model_copy(update={
        "program_kodu": kod,
        "hedef_kitle": hedef_kitle(c.hedef_kitle, kod, baslik),
        "tarihler": [Tarih(**t) for t in _tarihler(c.tarihler, source)],
        "butce": c.butce if ok(c.butce) else None,
        "sure": c.sure if ok(c.sure) else None,
        "basvuru_kosullari": [k for k in c.basvuru_kosullari if ok(k)],
        "baglantilar": list({b.url: _etiketle(b) for b in c.baglantilar if b.url in urls}.values()),
    })


_GENEL_ETIKET = re.compile(r"^(tikla\w*|buraya?|buradan|link|baglanti|detay\w*|devami\w*)\W*$")


def _etiketle(b: Baglanti) -> Baglanti:
    """'tiklayiniz' gibi anlamsiz link metinlerini alan adiyla degistirir."""
    if _GENEL_ETIKET.match(fold(b.etiket.strip())):
        return b.model_copy(update={"etiket": urlparse(b.url).netloc.removeprefix("www.")})
    return b


def _tarihler(tarihler: list[Tarih], source: str) -> list[dict]:
    """Gecerli ISO tarih olan ve gun/ay/yili metinde gecen tarihler; ayni tarih+etiket tekrarlari atilir."""
    ok = grounded_in(source)
    out: dict[tuple[str, str], dict] = {}
    for t in tarihler:
        try:
            d = date.fromisoformat(t.tarih)
        except ValueError:
            continue
        if ok(d.isoformat()):
            out[(t.etiket.strip(), d.isoformat())] = {"etiket": t.etiket.strip(), "tarih": d.isoformat()}
    return sorted(out.values(), key=lambda t: t["tarih"])
