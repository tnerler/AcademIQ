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

MAX_CHARS = 40000  # duyuru + bagli cagri metni PDF'leri (butce ust siniri cogunlukla PDF'te)


class Tarih(BaseModel):
    etiket: str = Field(description="Tarihin ne olduğu, metindeki ifadeyle: ör. '1. Aşama uluslararası başvuru son "
                                    "tarihi', 'Ulusal başvuru e-imza son tarihi', 'Son başvuru'")
    tarih: str = Field(description="YYYY-MM-DD")
    basvuru: bool = Field(True, description="Başvuru/teslim/e-imza son tarihi ya da başvuru dönemiyse true; sonuç "
                                            "açıklama, itiraz, proje başlangıcı, toplantı/bilgi günü tarihleriyse false")


class Baglanti(BaseModel):
    etiket: str = Field(description="Bağlantının ne olduğu (sayfadaki link metni değil): ör. 'TÜBİTAK başvuru "
                                    "sistemi', 'Çağrı dokümanı', 'Ortaklık çağrı sayfası'")
    url: str


class CagriCikarim(BaseModel):
    # Karardan once: model once basvuranlarin ne sundugunu yazsin (bkz. karar: proje degilse cagri_degil)
    basvurulan: Literal["proje", "egitim_etkinlik", "burs_odul_yarisma", "personel_ihale", "yok"] = Field(
        description="Başvuranların sunduğu şey. proje: proje önerisi/teklifi ya da araştırma, hibe, mali/teknik "
                    "destek, fizibilite başvurusu. egitim_etkinlik: eğitim, okul, kurs, etkinlik/toplantı katılımı. "
                    "burs_odul_yarisma: öğrenim bursu, ödül, yarışma. personel_ihale: personel alımı, sınav, ihale, "
                    "satın alma. yok: başvuru alınmıyor (haber, sonuç, anlaşma, genel bilgilendirme; daha önce "
                    "desteklenmiş/yürütülen bir projenin tanıtımı ya da açılışı)."
    )
    tur: Literal["cagri", "guncelleme", "cagri_degil"] = Field(
        description="cagri: PROJE önerisi/başvurusu kabul eden, açılan ya da açılacak çağrı ya da destek programı "
                    "(araştırma/Ar-Ge projeleri, hibe teklif çağrıları, kalkınma ajansı mali destek, fizibilite ve "
                    "teknik destek programları). "
                    "guncelleme: daha önce açılmış bir çağrının tarihini/takvimini/koşullarını değiştiren duyuru "
                    "(süre uzatma, takvim güncelleme). "
                    "cagri_degil: sonuç, burs, etkinlik, eğitim, yarışma, ödül, haber, bilgi günü, personel alımı, "
                    "sınav, ihale; anlaşma/protokol imzalanması ya da yürürlüğe girmesi; desteklenen bir projenin haberi; "
                    "bir programın kuralları "
                    "hakkında genel bilgilendirme (yeni bir başvuru dönemi/son tarih duyurmuyorsa)."
    )
    sebep: str = Field(description="Kararın tek cümlelik gerekçesi")
    program_kodu: str | None = Field(
        None, description="Program numarası ya da kısaltması: TÜBİTAK'ta başlıktaki numara (ör. '1001', '2518'), "
                          "yoksa metindeki program numarası (ör. '1071'); diğer kurumlarda metinde geçen kısaltma "
                          "(ör. 'SBEP', 'EUREKA', 'GISEP', 'TURGEP'). Yalnızca sayı ya da kısaltma, başka kelime yok; "
                          "metinde yoksa null."
    )
    program_adi: str | None = Field(None, description="Program/ortaklık adı, ör. 'Sürdürülebilir Mavi Ekonomi Ortaklığı'")
    ozet: str | None = Field(None, description="Çağrının konusu ve amacı, 2-3 cümle Türkçe")
    tarihler: list[Tarih] = Field(
        [], description="Metinde AÇIKÇA yazan çağrı takvimi tarihleri (başvuru dışı olanlar basvuru=false); "
                        "duyurunun/çağrının yayın ve açılış tarihi hariç"
    )
    # Once toplam: model programin toplam kaynagini ayirdiktan sonra proje basina tutari yazsin
    program_butcesi: str | None = Field(
        None, description="Programa/çağrıya ayrılan TOPLAM kaynak, metinde yazdığı gibi. 'Toplam bütçe', 'program "
                          "bütçesi', 'çağrı bütçesi', 'ayrılan toplam tutar/kaynak', 'toplam X TL bütçeli program' "
                          "ifadeleri buraya. Geçmiş dönemlerin istatistikleri ('bugüne kadar 61 proje 353,7 milyon TL "
                          "ile desteklendi') değil; yazmıyorsa null."
    )
    butce: str | None = Field(
        None, description="Tek bir PROJEYE verilebilecek destek/bütçe sınırı, metinde yazdığı gibi: ör. 'en fazla "
                          "10.000.000 TL', 'asgari 400.000 TL, azami 1.500.000 TL'. Yalnızca 'proje başına', "
                          "'azami/asgari destek tutarı', 'proje bütçesi üst sınırı' gibi tek projeye ait tutarlar. "
                          "program_butcesi'ne yazdığın toplam tutarı ve geçmiş istatistikleri buraya YAZMA; tek "
                          "projeye ait tutar yoksa null."
    )
    sure: str | None = Field(None, description="Proje süresi, metinde yazdığı gibi")
    basvuru_kosullari: list[str] = Field([], description="Kısa maddeler: kimler başvurabilir, ortak/konsorsiyum şartı vb.")
    # basvuru_kosullari'ndan sonra: model once kimlerin basvurabilecegini yazip sonra karar versin
    hedef_kitle: Literal["akademik", "sanayi"] = Field(
        description="akademik: üniversite ya da araştırma kurumları başvuru sahibi/ortak olarak başvurabiliyor "
                    "(TÜBİTAK ARDEB programları, ikili işbirlikleri, Ufuk Avrupa ortaklık çağrıları ve TÜSEB "
                    "akademik proje destekleri genellikle akademiktir). Uygun başvuru sahipleri listesinde "
                    "üniversiteler geçiyorsa, liste başka kurumları da içerse ve program araştırma odaklı olmasa da "
                    "(ör. kalkınma ajansı mali destek programları) akademik. "
                    "sanayi: başvuru sahibi yalnızca firma, KOBİ, girişimci ya da kamu kurumu olabiliyor; "
                    "üniversiteler en fazla alt yüklenici/danışman ya da uygun başvuru sahipleri arasında hiç "
                    "geçmiyor (TEYDEB 15xx/17xx/18xx, EUREKA, BiGG; yalnızca işletmelere, STK'lara, kooperatiflere "
                    "ya da belediyelere açık kalkınma ajansı programları)."
    )
    baglantilar: list[Baglanti] = Field(
        [], description="Yalnızca verilen bağlantı listesinden: başvuru sistemi, çağrı dokümanı, çağrı/ortaklık sayfası"
    )


_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "Sen {kaynak} duyurularını sınıflandıran ve proje çağrılarının bilgilerini çıkaran bir asistansın. "
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


TUBITAK = "TÜBİTAK"


def cikar(metin: str, baglantilar: list[tuple[str, str]], yayin_tarihi: date | None,
          baslik: str | None = None, kaynak: str = TUBITAK) -> CagriCikarim:
    text = metin[:MAX_CHARS]
    c: CagriCikarim = cikarim_chain.invoke({
        "metin": text,
        "baglantilar": "\n".join(f"- {etiket}: {url}" for etiket, url in baglantilar) or "(yok)",
        "yayin_tarihi": yayin_tarihi or "bilinmiyor",
        "kaynak": kaynak,
    })
    return ground(c, text, {url for _, url in baglantilar}, baslik, kaynak)


# Baslikta gecen TUBITAK program numarasi (1001, 2247-C, 2518 ...); 20xx yillari haric
_PROGRAM_NO = re.compile(r"(?<![\d.,])(?!20\d\d)([1-4]\d{3})(?![\d.,])")


_KISALTMA = re.compile(r"[A-Z0-9+]{2,10}")


def program_kodu(llm_kodu: str | None, baslik: str | None) -> str | None:
    """Baslikta program numarasi varsa o kullanilir (LLM bazen metindeki baska bir programi seciyor).
    Yoksa LLM'in kodunun ilk parcasi ('EUROSTARS-KOORD-DEST-2026-1' -> 'EUROSTARS', 'DUT_2026_1' -> 'DUT');
    'null' gibi bos degerler None olur."""
    if baslik and (m := _PROGRAM_NO.search(baslik)):
        return m.group(1)
    ilk = fold(re.split(r"[\s,;/_-]+", (llm_kodu or "").strip(), maxsplit=1)[0]).upper()  # GİSEP -> GISEP
    return ilk if _KISALTMA.fullmatch(ilk) and ilk not in ("NULL", "NONE", "YOK") else None


# TEYDEB (15xx-18xx) ve firma odakli uluslararasi programlar: LLM bunlari zaman zaman akademik etiketliyor
_SANAYI_KOD = re.compile(r"1[5-8]\d\d")
_SANAYI_BASLIK = re.compile(r"\b(eureka|eurostars|ira-sme|cornet|bigg|kobi|girisim|startup|hizlandirici)")


def hedef_kitle(llm_hedef: str, kod: str | None, baslik: str | None, universite_uygun: bool = False) -> str:
    if (kod and _SANAYI_KOD.fullmatch(kod)) or _SANAYI_BASLIK.search(fold(baslik or "")):
        return "sanayi"
    return "akademik" if universite_uygun else llm_hedef


# Kalkinma ajansi / AB hibe programlarinda LLM, basvuru kosullarina "Universiteler" yazdigi halde programi
# "sanayi" etiketleyebiliyor (uygun basvuru sahipleri listesinde belediye, STK, kooperatif de var diye).
_UNIVERSITE = re.compile(r"\buniversite")
_OLUMSUZ = re.compile(r"\b(olamaz|olamayacak|haric|disinda|degil|alt yuklenici|danisman)")


def universite_uygun(kosullar: list[str]) -> bool:
    """Basvuru kosullarindan biri universiteleri olumsuzlamadan aniyor mu?"""
    return any(_UNIVERSITE.search(k) and not _OLUMSUZ.search(k) for k in map(fold, kosullar))


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

def ground(c: CagriCikarim, source: str, urls: set[str], baslik: str | None = None,
           kaynak: str = TUBITAK) -> CagriCikarim:
    ok = grounded_in(source)
    tubitak = kaynak == TUBITAK  # baslikta numara / 15xx-18xx kurallari TUBITAK program numaralarina ozgu
    kod = program_kodu(c.program_kodu, baslik if tubitak else None)
    kosullar = [k for k in c.basvuru_kosullari if ok(k)]
    tur, sebep = karar(c, f"{baslik or ''} {source}")
    return c.model_copy(update={
        "tur": tur,
        "sebep": sebep,
        "program_kodu": kod,
        "hedef_kitle": hedef_kitle(c.hedef_kitle, kod if tubitak else None, baslik,
                                   universite_uygun=not tubitak and universite_uygun(kosullar)),
        "tarihler": [Tarih(**t) for t in _tarihler(c.tarihler, source)],
        **dict(zip(("butce", "program_butcesi"),
                   butceleri_ayir(c.butce if ok(c.butce) else None,
                                  c.program_butcesi if ok(c.program_butcesi) else None, source))),
        "sure": c.sure if ok(c.sure) else None,
        "basvuru_kosullari": kosullar,
        "baglantilar": list({b.url: _etiketle(b) for b in c.baglantilar if b.url in urls}.values()),
    })


# --- Butce: proje basina ust sinir / programin toplami / gecmis istatistik ------------------
# LLM (gpt-4o-mini) iki alani karistiriyor: programin toplam butcesini proje basina yaziyor ya da tersi; 1711'de
# duyurudaki "bugune kadar 61 proje 353,7 milyon TL ile desteklenmistir" istatistigini butce sandi. Her tutar
# metinde gectigi yerin hemen onundeki ifadeye gore yeniden siniflandirilir.

# 10.000.000 TL, 353,7 milyon TL, uc milyon (3.000.000,00) TL, 1.500.000-TL, 1.500.000 (birmilyonbesyuzbin) TL
_PARA = re.compile(r"(\d[\d.,]*)\)?\s*(?:\([^)\d]{0,40}\))?\s*-?\s*(?:milyon|milyar|bin)?\s*"
                   r"(?:tl|try|turk lira|avro|euro|eur|€|\$|dolar|usd)")  # ekli olabilir: "TL'dir" -> "tldir"
_PROJE_BASINA = re.compile(r"proje basina|her bir proje|projeye|proje(?:nin)? (?:destek )?butce|destek (?:miktar|tutar|butce)"
                           r"|azami|asgari|en fazla|en az|ust sinir|ust limit|alt sinir|maksimum|minimum|basina")
_TOPLAM = re.compile(r"toplam|program(?:in)? butce|cagri(?:nin)? butce|ayrilan|tahsis edilen|butceli")
# Butceye eklenen odemeler (PTI, kurum hissesi): "PTI miktari ise 100.000 TL", "en fazla 100.000-TL PTI odemesi".
# "PTI ve Kurum Hissesi haric/dahil en fazla 10.000.000 TL" ise butcenin kendisi.
_EK = re.compile(r"\bpti\b|tesvik ikramiye|kurum hisse|genel gider")
_CUMLE = re.compile(r"\n|[.!?;]\s")
_GECMIS = re.compile(r"bugune kadar|simdiye kadar|desteklenmis|desteklendi|destek verilmis|destek saglanmis")


def _sayi(m: re.Match) -> str:
    """'10.000.000,00' ve '10.000.000' ayni tutar."""
    return re.sub(r"[.,]0{1,2}$", "", m.group(1).rstrip(".,"))


def _tutar_turu(sayi: str, kaynak: str) -> str | None:
    """'proje', 'toplam', 'gecmis' ya da None (metinde bulunamadi / ifade yok)."""
    for m in _PARA.finditer(kaynak):
        if _sayi(m) != sayi:
            continue
        # Ayni cumlede, bir onceki tutardan sonrasi ve tutardan sonraki kisim
        onceki = _CUMLE.split(_PARA.split(kaynak[max(0, m.start() - 160):m.start()])[-1])[-1]
        sonraki = _CUMLE.split(kaynak[m.end():m.end() + 60])[0]
        if _GECMIS.search(onceki + sonraki):
            return "gecmis"
        yakin = onceki[-50:] + sonraki[:25]
        if _EK.search(yakin) and not re.search(r"haric|dahil", yakin):
            return "ek"
        p = [x.start() for x in _PROJE_BASINA.finditer(onceki)]
        t = [x.start() for x in _TOPLAM.finditer(onceki)]
        if p or t:  # ikisi de varsa tutara en yakin olan
            return "proje" if max(p, default=-1) > max(t, default=-1) else "toplam"
    return None


def _tutarlar(deger: str) -> set[str]:
    return {_sayi(m) for m in _PARA.finditer(fold(deger))}


def _turu(deger: str | None, kaynak: str) -> str | None:
    """Degerdeki tutarlarin ortak turu; tutar yoksa 'yok', turler karisiksa ya da belirsizse None."""
    if not deger:
        return None
    sayilar = _tutarlar(deger)
    if not sayilar:
        return "yok"
    turler = {_tutar_turu(s, kaynak) for s in sayilar}
    if turler & {"gecmis", "ek"}:
        return "gecmis"
    return turler.pop() if len(turler) == 1 else None


def butceleri_ayir(butce: str | None, program: str | None, kaynak: str) -> tuple[str | None, str | None]:
    """(proje basina, program toplami). Tutarsiz ya da gecmis istatistik olan degerler atilir, yanlis alana
    yazilanlar tasinir; turu belirlenemeyen deger LLM'in sectigi alanda kalir."""
    kaynak = fold(kaynak)
    if butce and program and _tutarlar(butce) == _tutarlar(program) and _turu(program, kaynak) != "toplam":
        program = None  # ayni tutar iki alanda (LLM emin olamayinca ikisine de yaziyor)
    adaylar = [(tur or alan, alan, deger) for deger, alan in ((butce, "proje"), (program, "toplam"))
               if deger and (tur := _turu(deger, kaynak)) not in ("yok", "gecmis")]
    sonuc: dict[str, str | None] = {"proje": None, "toplam": None}
    for hedef, _, deger in sorted(adaylar, key=lambda a: a[0] != a[1]):  # ayni ture iki deger: yerinde olan kalir
        sonuc[hedef] = sonuc[hedef] or _ifadeyi_duzelt(deger, hedef)
    return sonuc["proje"], sonuc["toplam"]


_PARA_METNI = re.compile(r"\d[\d.,]*\s*(?:milyon|milyar|bin)?\s*(?:TL|TRY|Türk Lirası|avro|euro|EUR|€|\$|dolar|USD)",
                         re.IGNORECASE)


def _ifadeyi_duzelt(deger: str, tur: str) -> str:
    """Degerin kendi ifadesi alanina ters dusuyorsa (proje basina alanda 'Toplam butce 10.000.000 TL') yalnizca
    tutarlar kalir."""
    f = fold(deger)
    ters = _TOPLAM.search(f) and not _PROJE_BASINA.search(f) if tur == "proje" else _PROJE_BASINA.search(f)
    return ", ".join(_PARA_METNI.findall(deger)) or deger if ters else deger


# Kayitli 113 cagrinin hepsinde geciyor; desteklenmis bir projenin haberinde (ör. "GMKA Destegiyle ...
# Sepetcilik Yeniden Canlandirilacak") hic gecmiyor ama LLM onu da 'proje' sayiyor.
_BASVURU_IFADESI = re.compile(r"basvur|cagri|teklif")


def karar(c: CagriCikarim, metin: str) -> tuple[str, str]:
    """LLM 'cagri'/'guncelleme' dese de basvuranlar proje sunmuyorsa ya da metinde basvuru/cagri/teklif hic
    gecmiyorsa cagri_degil (haber, egitim programi, anlasma duyurulari). Metinden alinti isteyip dogrulamak
    da denendi: model alintiyi rastgele bos biraktigi icin gercek cagrilarin ~%35'ini eliyordu."""
    if c.tur == "cagri_degil":
        return c.tur, c.sebep
    if c.basvurulan != "proje":
        return "cagri_degil", f"başvurulan: {c.basvurulan} ({c.sebep})"
    if not _BASVURU_IFADESI.search(fold(metin)):
        return "cagri_degil", f"metinde başvuru/çağrı ifadesi yok ({c.sebep})"
    return c.tur, c.sebep


_GENEL_ETIKET = re.compile(r"^(tikla\w*|buraya?|buradan|link|baglanti|detay\w*|devami\w*)\W*$")


def _etiketle(b: Baglanti) -> Baglanti:
    """'tiklayiniz' gibi anlamsiz link metinlerini alan adiyla degistirir."""
    if _GENEL_ETIKET.match(fold(b.etiket.strip())):
        return b.model_copy(update={"etiket": urlparse(b.url).netloc.removeprefix("www.")})
    return b


# Yayin/acilis tarihi basvuru son tarihi sayilmasin (LLM zaman zaman "yayimlanma tarihi"ni basvuru=true yaziyor)
_YAYIN_ETIKETI = re.compile(r"\b(yayim|yayin|ilan|acilis|acilma|acildig)")
# E-imza / teslim / basvuru tarihleri basvuru tarihidir: LLM ayni "E-imza son tarihi"ni bir cagrida true, digerinde
# false yaziyor. Basvuru sonrasi adimlar (degerlendirme, sonuc, sozlesme imzasi, baslangic) haric.
_BASVURU_ETIKETI = re.compile(r"(\be-?imza|basvur|teslim)")
_BASVURU_SONRASI = re.compile(r"(sonuc|degerlendir|sozlesme|baslang|duyur|itiraz|hak kazan)")


def _basvuru_tarihi_mi(etiket: str, llm: bool) -> bool:
    e = fold(etiket)
    if _YAYIN_ETIKETI.search(e) or _BASVURU_SONRASI.search(e):
        return False
    return True if _BASVURU_ETIKETI.search(e) else llm


def _tarihler(tarihler: list[Tarih], source: str) -> list[dict]:
    """Gecerli ISO tarih olan ve gun/ay/yili metinde gecen tarihler; ayni tarih+etiket tekrarlari atilir.
    basvuru=false tarihler gosterilir ama son_tarih'e (db: cagri_son_tarih) katilmaz."""
    ok = grounded_in(source)
    out: dict[tuple[str, str], dict] = {}
    for t in tarihler:
        try:
            d = date.fromisoformat(t.tarih)
        except ValueError:
            continue
        if ok(d.isoformat()):
            etiket = t.etiket.strip()
            out[(etiket, d.isoformat())] = {"etiket": etiket, "tarih": d.isoformat(),
                                             "basvuru": _basvuru_tarihi_mi(etiket, t.basvuru)}
    return sorted(out.values(), key=lambda t: t["tarih"])
