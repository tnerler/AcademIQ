"""
Sablondan bagimsiz CV cikarimi: CV metni -> LLM (structured output) -> ortak sema.

  - Arama alanlari   : arastirma alanlari + ozet, yayinlar, projeler, yonetilen tezler, kendi tez basliklari.
                       arama_bolumleri() bunlari chunk'lanacak bolum maddelerine cevirir.
  - Gosterim alanlari: iletisim, egitim, gorevler, oduller, uyelikler, bibliyometri, dersler ...
                       aramaya girmez; cikarimin tamami profil metadata'sinda ('cv') saklanir (UI, HocaDetay.cv).
LLM'in metinde dayanagi olmayan maddeleri (uydurma) ground_cv ile atilir.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import logging
import re
import unicodedata

from langchain_core.prompts import ChatPromptTemplate
from openai import LengthFinishReasonError
from pydantic import BaseModel, ValidationError

from backend.api.schemas import Bibliyometri, CVBilgileri, CVCikarim, Iletisim, Yayin, YayinListesi
from backend.llm import get_llm
from backend.matching.ilan_extract import fold, grounded_in

logger = logging.getLogger("index_cvs")

MAX_CHARS = 40000


_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "Sen akademik özgeçmişleri (CV) yapılandırılmış veriye dönüştüren bir asistansın. CV'ler farklı "
     "şablonlarda olabilir: başlıklar farklı adlandırılmış, bilgiler tablo satırlarına ('a | b | c'), yan "
     "panellere ya da tek satıra sıkıştırılmış olabilir. Her bilgiyi anlamına göre doğru alana yerleştir.\n"
     "Kurallar:\n"
     "- Yalnızca CV'de yazan bilgiyi kullan; olmayanı uydurma, boş bırak.\n"
     "- Listelerdeki maddeleri eksiksiz çıkar (yayınların ve tezlerin hepsi).\n"
     "- Başlıkları CV'deki yazımıyla aynen aktar, çevirme ve kısaltma.\n"
     "- Kendi yüksek lisans/doktora tezleri 'egitim' altına, öğrencilerinin tezleri 'yonetilen_tezler' altına.\n"
     "- Yayınları çıkarma; onlar ayrıca işlenecek."),
    ("human", "{cv}"),
])

_YAYIN_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "Sana bir akademik CV'nin bir parçası verilecek. Parçadaki her yayını (makale, bildiri, kitap, kitap bölümü) "
     "ayrı kayıt olarak çıkar; numaralı ya da numarasız her kaynak satırı bir yayındır, hiçbirini atlama. "
     "Yayın yoksa boş liste döndür. Proje, tez ve ders başlıkları yayın değildir."),
    ("human", "{parca}"),
])

# gpt-4o-mini katı JSON (json_schema) modunda bazı Türkçe ifadelerde ('Dokuz Eylül Üniversitesi') karakterleri
# \u0000 olarak bozuyor ya da cikti token sinirina kadar donguye giriyor (100 CV'nin 9'u). Bu durumda ayni
# istek function calling moduyla yeniden denenir; yazim sonunda kaynak metinden duzeltilir (_yazimi_duzelt).
_LLM = get_llm().bind(max_tokens=8000)
_ZINCIRLER = {
    schema: (prompt | _LLM.with_structured_output(schema),
             prompt | _LLM.with_structured_output(schema, method="function_calling"))
    for prompt, schema in ((_PROMPT, CVBilgileri), (_YAYIN_PROMPT, YayinListesi))
}

YAYIN_PARCA_CHARS = 5000  # gpt-4o-mini uzun listeleri yarida kesiyor (27 yayinin 12'si); kisa parcalarda eksiksiz


def _yapilandir(schema: type[BaseModel], girdi: dict) -> BaseModel:
    katı, yedek = _ZINCIRLER[schema]
    try:
        sonuc = katı.invoke(girdi)
        if "\\u0000" not in sonuc.model_dump_json():
            return sonuc
        logger.info("LLM ciktisinda bozuk karakter; function calling ile yeniden deneniyor")
    except (LengthFinishReasonError, ValidationError) as exc:
        logger.info("LLM ciktisi gecersiz (%s); function calling ile yeniden deneniyor", type(exc).__name__)
    return yedek.invoke(girdi)


def cikar(metin: str) -> CVCikarim:
    text = metin[:MAX_CHARS]
    parcalar = _parcalar(text, YAYIN_PARCA_CHARS)
    with ThreadPoolExecutor(len(parcalar) + 1) as ex:
        c = ex.submit(_yapilandir, CVBilgileri, {"cv": text})
        listeler = list(ex.map(lambda p: _yapilandir(YayinListesi, {"parca": p}), parcalar))
        c = c.result()
    # Parcalar ortusmedigi icin yalnizca LLM'in ayni yayini iki kez dondurmesi elenir; ayni baslikla farkli
    # yil/turde yayimlanmis eserler (makale + bildiri) ayri kalir
    yayinlar = {(fold(y.baslik), y.yil, y.tur): y for liste in listeler for y in liste.yayinlar}
    ham = CVCikarim(**c.model_dump(), yayinlar=list(yayinlar.values()))
    return ground_cv(CVCikarim(**_yazimi_duzelt(ham.model_dump(), text)), text)


# --- Yazim duzeltme ---------------------------------------------------------------

def _harf(ch: str) -> str:
    """Tek karakter -> tek karakter sadelestirme (hizalama bozulmasin diye uzunluk korunur)."""
    if ch in "İIı":
        return "i"
    return (unicodedata.normalize("NFKD", ch.lower()).encode("ascii", "ignore").decode() or ch.lower())[:1] or ch


_SABIT_ALANLAR = {"tur", "seviye"}


def _yazimi_duzelt(obj, source: str, _sade_kaynak: list[str] | None = None):
    """LLM'in dondurdugu metinleri CV'deki yazimla degistirir: aksansiz/kucuk harf eslesmesi bulunursa
    kaynaktaki orijinal dizi alinir ('Dokuz Eylul Universitesi' / 'Eyl\\x00l' -> 'Dokuz Eylül Üniversitesi')."""
    sade = _sade_kaynak if _sade_kaynak is not None else "".join(_harf(ch) for ch in source)
    if isinstance(obj, dict):  # sabit degerli alanlar (tur, seviye) serbest metin degil
        return {k: v if k in _SABIT_ALANLAR else _yazimi_duzelt(v, source, sade) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_yazimi_duzelt(v, source, sade) for v in obj]
    if not isinstance(obj, str) or not obj or obj in source:
        return obj
    desen = "".join("." if ch == "\x00" else re.escape(_harf(ch)) for ch in obj)
    m = re.search(desen, sade)
    return source[m.start():m.end()] if m else obj.replace("\x00", "")


def _parcalar(text: str, size: int) -> list[str]:
    """Satir sinirlarinda bolunmus, en fazla size karakterlik parcalar."""
    parcalar, simdiki = [], ""
    for line in text.splitlines():
        if simdiki and len(simdiki) + len(line) > size:
            parcalar.append(simdiki)
            simdiki = ""
        simdiki += line + "\n"
    return parcalar + ([simdiki] if simdiki else [])


# --- Uydurma bilgi filtresi ----------------------------------------------------

def ground_cv(c: CVCikarim, source: str) -> CVCikarim:
    ok = grounded_in(source)
    birebir = lambda v: v if v and _sade(v) in _sade(source) else None  # noqa: E731  e-posta, ORCID gibi kimlikler

    def liste(items, alan: str):
        return [i for i in items if ok(getattr(i, alan) if alan else i)]

    return c.model_copy(update={
        "kimlik": c.kimlik.model_copy(update={"unvan": kisa_unvan(c.kimlik.unvan)}),
        "iletisim": Iletisim(**{k: birebir(v) for k, v in c.iletisim.model_dump().items()}),
        "arastirma_alanlari": liste(c.arastirma_alanlari, ""),
        "egitim": [e.model_copy(update={"tez_basligi": _danismansiz(e.tez_basligi) if ok(e.tez_basligi) else None})
                   for e in c.egitim if ok(e.universite)],
        "akademik_gorevler": liste(c.akademik_gorevler, "gorev"),
        "yonetim_gorevleri": liste(c.yonetim_gorevleri, "gorev"),
        "yayinlar": [y.model_copy(update={"baslik": _yalin_baslik(y)}) for y in liste(c.yayinlar, "baslik")],
        "projeler": liste(c.projeler, "ad"),
        "yonetilen_tezler": liste(c.yonetilen_tezler, "baslik"),
        "dersler": liste(c.dersler, ""),
        "oduller": liste(c.oduller, ""),
        "uyelikler": liste(c.uyelikler, ""),
        "hakemlik_editorluk": liste(c.hakemlik_editorluk, ""),
        "yabanci_diller": liste(c.yabanci_diller, ""),
        # LLM CV'de olmayan sayilari 0 olarak doldurabiliyor; 0 bilgi tasimaz
        "bibliyometri": Bibliyometri(**{k: v if v and ok(str(v)) else None
                                        for k, v in c.bibliyometri.model_dump().items()}),
    })


_UNVANLAR = [  # (sadelestirilmis yazim kalibi, kisa unvan); ozelden genele
    (r"ogr(etim)?\.? ?gor(evlisi)?\.? ?d(okto)?r", "Öğr. Gör. Dr."),
    (r"ar(a)?s(tirma)?\.? ?gor(evlisi)?\.? ?d(okto)?r", "Arş. Gör. Dr."),
    (r"(dr\.? ?ogr(etim)?\.? ?uye(si)?|doktor ogretim uyesi|yardimci docent|yrd\.? ?doc)", "Dr. Öğr. Üyesi"),
    (r"(prof|profesor)", "Prof. Dr."),
    (r"(doc|docent)", "Doç. Dr."),
    (r"ogr(etim)?\.? ?gor", "Öğr. Gör."),
    (r"ar(a)?s(tirma)?\.? ?gor", "Arş. Gör."),
]


def kisa_unvan(unvan: str | None) -> str | None:
    """'Doçent', 'Doktor Öğretim Üyesi' gibi yazimlari CV'ler listesindeki kisa bicime cevirir."""
    if not unvan:
        return None
    f = fold(unvan)
    return next((kisa for kalip, kisa in _UNVANLAR if re.search(rf"\b{kalip}", f)), unvan)


def _danismansiz(baslik: str | None) -> str | None:
    """'Tez basligi — Doç. Dr. X' / 'Tez basligi (Danışman: ...)' -> 'Tez basligi'."""
    if not baslik:
        return None
    return re.split(r"\s+[—–-]\s+(?=(Prof|Doç|Doc|Dr|Assoc|Asst)\b)|\s*\(Danışman", baslik)[0].strip()


# ". Journal of X, 12(3), 45-67" / ". Kılıç, A. (Ed.), ..." gibi baslik sonrasi kaynak bilgisi
_KAYNAK_KUYRUGU = re.compile(
    r"\.\s+(?=[^.]*(\(Ed\.\)|\d+\s*\(\d+\)|\d+\s*[–-]\s*\d+|: [A-Z])|[A-ZÇĞİÖŞÜ]\w+, [A-ZÇĞİÖŞÜ]\.)")


def _yalin_baslik(y: Yayin) -> str:
    """LLM bazen dergi/kitap bilgisini de basliga katiyor; yayin yeri ya da cilt/sayfa kuyrugundan keser."""
    baslik = y.baslik
    if y.yayin_yeri and (i := baslik.find(y.yayin_yeri)) > 10:
        baslik = baslik[:i]
    if m := _KAYNAK_KUYRUGU.search(baslik):
        baslik = baslik[:m.start()]
    return baslik.strip(" .,;")


def _sade(text: str) -> str:
    return re.sub(r"[\s()+\-]", "", text).lower()


# --- Arama bolumleri ve gosterim metadata'si ------------------------------------

_SEVIYE = {"yuksek_lisans": "Yüksek Lisans", "doktora": "Doktora"}


def arama_bolumleri(c: CVCikarim) -> dict[str, list[str]]:
    """Chunk'lanacak bolum maddeleri (SECTION_LABELS anahtarlari). Yazar/dergi gibi ayrintilar alinmaz."""
    yil = lambda y: f" ({y})" if y else ""  # noqa: E731
    return {
        "arastirma": c.arastirma_alanlari + ([c.ozet] if c.ozet else []),
        "egitim": [f"{e.derece} tezi: {e.tez_basligi}" for e in c.egitim if e.tez_basligi],
        "yayinlar": [f"{y.baslik}{yil(y.yil)}" for y in c.yayinlar],
        "projeler": [f"{p.ad}{yil(p.donem)}" for p in c.projeler],
        "yonetilen_tezler": [f"{_SEVIYE[t.seviye]}: {t.baslik}" for t in c.yonetilen_tezler],
    }
