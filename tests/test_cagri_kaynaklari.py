"""Cagri kaynagi ayristiricilari: tests/fixtures/cagrilar altindaki gercek sayfalar (scriptler ve stiller cikarildi).
Ag istegi yapilmaz; Kaynak.get / Kaynak.istek fixture dondurur. Site HTML'i degisirse bu testler bozulur."""

from datetime import date
import json
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest

from backend.cagrilar import fetch
from backend.cagrilar.extract import CagriCikarim, _basvuru_tarihi_mi, butceleri_ayir, ground, universite_uygun
from backend.cagrilar.filters import kara_liste
from backend.cagrilar.sources.ab import AbBaskanligi
from backend.cagrilar.sources.base import DuyuruOge, ana_metin, pdf_metni, tr_tarih
from backend.cagrilar.sources.kalkinma_ajanslari import KalkinmaAjanslari
from backend.cagrilar.sources.tubitak import cagri_pdfleri
from backend.cagrilar.sources.tuseb import Tuseb

FIX = Path(__file__).parent / "fixtures" / "cagrilar"


def oku(ad: str) -> str:
    return (FIX / ad).read_text(encoding="utf-8")


def _pdf(metin: str) -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), metin)
    return doc.tobytes()


@pytest.mark.parametrize("text, beklenen", [
    ("Ağustos 19, 2026", date(2026, 8, 19)),
    ("24 Temmuz, 2026", date(2026, 7, 24)),
    ("17 Eylül 2026 | 17:08", date(2026, 9, 17)),
    ("31 Şubat 2026", None),
    ("tarih yok", None),
])
def test_tr_tarih(text, beklenen):
    assert tr_tarih(text) == beklenen


def test_tuseb_liste(monkeypatch):
    k = Tuseb()
    istenen = []
    monkeypatch.setattr(k, "get", lambda url, params=None: istenen.append(url) or oku("tuseb_liste.html"))
    ogeler = k.liste(0)
    k.liste(2)
    assert istenen == ["https://proje-destek.tuseb.gov.tr/tr/haberler",
                       "https://proje-destek.tuseb.gov.tr/tr/haberler/p/3"]
    assert len(ogeler) == 8
    ilk = ogeler[0]
    assert ilk.baslik.startswith("2026 Yılı TÜSEB B Grubu II. Dönem Proje Desteklerine")
    assert ilk.url.endswith("-20260819") and ilk.yayin_tarihi == date(2026, 8, 19)
    assert all(o.yayin_tarihi for o in ogeler)


def test_tuseb_detay_pdf_ekler(monkeypatch):
    k = Tuseb()
    monkeypatch.setattr(k, "get", lambda url, params=None: oku("tuseb_detay.html"))
    pdf_istekleri = []

    def istek(url, params=None):
        pdf_istekleri.append(url)
        return SimpleNamespace(content=_pdf("On Basvuru: 01.09.2026-13.09.2026"))

    monkeypatch.setattr(k, "istek", istek)
    s = k.detay("https://proje-destek.tuseb.gov.tr/tr/haberler/x-20260819")
    assert s.metin.startswith("2026 Yılı TÜSEB B Grubu II. Dönem")
    assert "Üreten Sağlık Platformu" in s.metin  # menu/footer degil haber govdesi
    assert pdf_istekleri == ["https://files.tuseb.gov.tr/tuseb/files/tbys/2026-b2-cagri-metni.pdf"]
    assert "## Ek: 2026-b2-cagri-metni.pdf\nOn Basvuru: 01.09.2026-13.09.2026" in s.metin
    assert ("tıklayınız.", pdf_istekleri[0]) in s.baglantilar


def test_tuseb_pdf_okunamazsa_haber_metniyle_devam(monkeypatch):
    k = Tuseb()
    monkeypatch.setattr(k, "get", lambda url, params=None: oku("tuseb_detay.html"))
    monkeypatch.setattr(k, "istek", lambda url, params=None: SimpleNamespace(content=b"pdf degil"))
    s = k.detay("https://proje-destek.tuseb.gov.tr/tr/haberler/x")
    assert "## Ek:" not in s.metin and s.metin.startswith("2026 Yılı TÜSEB")


def test_ab_liste_ve_detay(monkeypatch):
    k = AbBaskanligi()
    assert k.sirali is False
    monkeypatch.setattr(k, "get", lambda url, params=None: oku("ab_liste.html"))
    ogeler = k.liste(0)
    assert k.liste(1) == []
    assert len(ogeler) > 40 and all(o.yayin_tarihi for o in ogeler)
    hibe = next(o for o in ogeler if o.url.endswith("_54262.html"))
    assert hibe.url.startswith("https://www.ab.gov.tr/") and hibe.yayin_tarihi == date(2026, 7, 24)
    assert "HİBE TEKLİF ÇAĞRILARI" in hibe.baslik

    monkeypatch.setattr(k, "get", lambda url, params=None: oku("ab_detay.html"))
    s = k.detay(hibe.url)
    ilk_satir = s.metin.splitlines()[0]
    assert ilk_satir.startswith("# ") and "MEDYA" not in ilk_satir  # h1.navb yol satiri alinmaz
    assert "hibe" in s.metin.lower()


def test_ka_liste(monkeypatch):
    k = KalkinmaAjanslari()
    sayfalar = []

    def istek(url, params=None):
        sayfalar.append(params["page"])
        return SimpleNamespace(json=lambda: json.loads(oku("ka_liste.json")))

    monkeypatch.setattr(k, "istek", istek)
    ogeler = k.liste(0)
    assert sayfalar == [1]  # API sayfalari 1'den baslar
    assert len(ogeler) == 20
    assert all(o.url.startswith("https://api.ka.gov.tr/redirect/") and o.yayin_tarihi for o in ogeler)
    tarihler = [o.yayin_tarihi for o in ogeler]
    assert tarihler == sorted(tarihler, reverse=True)  # sirali=True varsayimi


def test_ka_api_hatasi(monkeypatch):
    k = KalkinmaAjanslari()
    monkeypatch.setattr(k, "istek", lambda url, params=None: SimpleNamespace(
        json=lambda: {"status": False, "message": "An error occurred please try again later"}))
    with pytest.raises(ValueError):
        k.liste(0)


def test_ana_metin_ajans_sayfasi():
    url = "https://oka.gov.tr/duyuru/2026-yili-turizm-odakli-yatirim-projeleri-fizibilite-destegi-programi-ilan-edilmistir"
    s = ana_metin(oku("ka_ajans_detay.html"), url)
    assert "Turizm Odaklı Yatırım Projeleri Fizibilite Desteği Programı" in s.metin
    assert "25.12.2026" in s.metin
    # Menu/footer baglantilari alinmaz; metinde gecen baglantilar (basvuru rehberi) alinir
    assert s.baglantilar and len(s.baglantilar) < 10
    assert all(etiket.casefold() in " ".join(s.metin.split()).casefold() for etiket, _ in s.baglantilar)


def test_ana_metin_bos_sayfa():
    with pytest.raises(ValueError):
        ana_metin("<html><body><nav>Menu</nav></body></html>", "https://ornek.gov.tr/x")


def test_pdf_metni_satir_birlestirme():
    doc = pymupdf.open()
    sayfa = doc.new_page()
    sayfa.insert_text((72, 72), "Akademisyenlerin\nve\nuzmanlarin")
    sayfa.insert_text((72, 200), "Ikinci paragraf")
    metin = pdf_metni(doc.tobytes())
    assert "Akademisyenlerin ve uzmanlarin" in metin
    assert "Ikinci paragraf" in metin


class _Sahte:
    ad = "Sahte"
    sirali = False

    def __init__(self, sayfalar):
        self.sayfalar = sayfalar

    def liste(self, sayfa):
        return self.sayfalar[sayfa] if sayfa < len(self.sayfalar) else []


def test_sirasiz_liste_bilinende_durmaz():
    bugun = date.today()
    ogeler = [DuyuruOge("u/bilinen", "b", bugun),
              DuyuruOge("u/yeni-eski", "c", date(bugun.year - 5, 1, 1)),  # backfill penceresinden eski
              DuyuruOge("u/yeni1", "a", date(bugun.year, 1, 1) if bugun.month > 1 else bugun),
              DuyuruOge("u/tarihsiz", "d", None),
              DuyuruOge("u/yeni2", "e", bugun)]
    yeni = fetch._yeni_duyurular(_Sahte([ogeler[:2], ogeler[2:]]), {"u/bilinen"}, backfill=False)
    assert [o.url for o in yeni][0] == "u/tarihsiz"  # tarihsizler en yeni sayilir, en son islenir
    assert {o.url for o in yeni} == {"u/tarihsiz", "u/yeni1", "u/yeni2"}
    tarihli = [o.yayin_tarihi for o in yeni if o.yayin_tarihi]
    assert tarihli == sorted(tarihli, reverse=True)


@pytest.mark.parametrize("baslik", [
    "2026 Yılı TÜSEB B Grubu II. Dönem Proje Desteklerine İlişkin Çağrı Ayrıntıları Yayımlandı!",
    "TÜSEB Bcg Aşısının Yerli Üretimi ve Üretim Alt Yapısının Kurulmasına Yönelik Proje Çağrısı Açıldı!",
    "KUDAKA 2026 Yılı Anadoludakiler Coğrafi İşaretli Ürünlerin Üretimi ve Tanıtımı MDP İlan Edildi",
    "Zafer Kalkınma Ajansı Girişimci ve Güçlü Sivil Toplum Mali Destek Programı (GİSEP) İlan Edildi",
    "OKA Kadın Mühendis Okulu 4. Dönem Başvuru Süresi Uzatıldı",
    "\"TÜRKİYE'DE SİVİL TOPLUMUN SOSYAL GİRİŞİMCİLİK YOLUYLA DESTEKLENMESİ\" PROJESİ HİBE TEKLİF ÇAĞRILARI YAYIMLANDI",
    "PACE Projesi Hibe Duyurusu Yayımlandı",
    "Tek Sağlık Antimikrobiyal Dirençle Mücadele (OHAMR) Avrupa Ortaklığının 2026 Yılı \"Tedaviler ve Tedavi "
    "Protokollerine Uyum- OH-TREAT\" Başlıklı Çağrısı Açıldı",
])
def test_kara_liste_cagrilari_gecirir(baslik):
    assert kara_liste(baslik) is None


@pytest.mark.parametrize("baslik", [
    "TÜSEB Heyetinden Kütahya Sağlık Bilimleri Üniversitesi’ne Ziyaret",
    "TÜSEB Hakem Havuzuna Katılın",
    "TÜSEB B Grubu I. Dönem Ön Başvuruları Tamamlandı!",
    "ANKARAKA Sosyal Girişim İş Modeli Kanvası Hazırlama Eğitimi Düzenlenecektir",
    "Sosyal Girişimcilik Mali Destek Programı Başvuru Mentörlüğü",
    "2025 Yılı Teknik Destek Programı Beşinci Dönem 2. Satın Alma Duyurusu",
    "Rekabetçi Sanayi İşletmeleri Alternatif Destek Programı Bilgilendirme Toplantısı",
    "Siber Vatan Programı Kapsamında BANÜ ve GMKA Protokol İmzaladı",
    "2026/1 KPSS Yerleştirmesi hk.",
    "AVRUPA BİRLİĞİ İŞLERİ UZMAN YARDIMCISI ALIM İLANI",
    "PACE Projesi Hibe Duyurusuna İlişkin Sıkça Sorulan Sorular Dokümanı Yayımlandı",
    "Türkiye için Katılım Öncesi Mali Yardım (IPA) 2024 Yılı Eylem Programına Ait Finansman Anlaşması Yürürlüğe Girdi",
])
def test_kara_liste_yeni_kaynak_gurultusu(baslik):
    assert kara_liste(baslik)


def test_tuseb_haber_sayfasi_olmayan_kart(monkeypatch):
    """TBYS'ye giden kartlar ayni adresi paylasiyor: kimlik basliktan uretilir, metin kart ozetidir."""
    k = Tuseb()
    monkeypatch.setattr(k, "get", lambda url, params=None: oku("tuseb_liste.html"))
    ogeler = k.liste(0)
    assert len({o.url for o in ogeler}) == len(ogeler)
    kart = next(o for o in ogeler if "tbys" not in o.url and "#" in o.url)
    assert kart.url.startswith("https://proje-destek.tuseb.gov.tr/tr/haberler#tuseb-koah")

    yeni = Tuseb()  # aktif cagri kontrolu: bu surecte liste gezilmemis
    monkeypatch.setattr(yeni, "get", lambda url, params=None: oku("tuseb_liste.html"))
    s = yeni.detay(kart.url)
    assert s.metin.startswith(kart.baslik)
    assert s.baglantilar == [("TÜSEB Bilgi Yönetim Sistemi (TBYS)", "https://tbys.tuseb.gov.tr/#/aktifcagrilistesidispanel")]


@pytest.mark.parametrize("kosullar, beklenen", [
    (["Kamu kurum ve kuruluşları", "Mahalli idareler", "Üniversiteler"], True),
    (["Kamu üniversiteleri ve vakıf üniversiteleri"], True),
    (["Üniversiteler başvuru sahibi olamaz"], False),
    (["Üniversiteler alt yüklenici olarak yer alabilir"], False),
    (["Sivil toplum kuruluşları", "Kooperatifler"], False),
])
def test_universite_uygun(kosullar, beklenen):
    assert universite_uygun(kosullar) is beklenen


def _cikarim(**alanlar):
    varsayilan = {"tur": "cagri", "sebep": "-", "hedef_kitle": "sanayi", "basvurulan": "proje"}
    return CagriCikarim(**{**varsayilan, **alanlar})


def test_tubitak_cagri_pdfleri():
    F = "https://tubitak.gov.tr/sites/default/files/2026-09/"
    linkler = [
        ("Başvuru Kılavuzu", F + "ardeb_1001_basvuru_rehberi.pdf"),
        ("E-imza süreci yardım dokümanı", F + "ardeb_e-imza_yardim_dokumani.pdf"),
        ("Öncelikli konu başlıkları", F + "TUBITAK_24-25_Ar-Ge_ve_Yenilik_Konu_Basliklari.pdf"),
        ("Uluslararası Çağrı Metni", F + "RAMP_JTC_2026_Call_Text.pdf"),
        ("Ulusal Başvuru Kuralları", F + "RAMP_Ulusal_Basvuru_Kurallari.pdf"),
        ("Süreç dokümanı", F + "DUT%202026_%C4%B0ki%20a%C5%9Famal%C4%B1_S%C3%BCre%C3%A7%20Dok%C3%BCman%C4%B1.pdf"),
        ("Çağrı Metni", "https://icgeb.org/CRP-Cagri.pdf"),  # baska alan adi
        ("Çağrı sayfası", "https://tubitak.gov.tr/tr/duyuru/x"),
    ]
    # Ulusal (Turkce) dokumanlar uluslararasi cagri metninden once; en fazla 2
    assert cagri_pdfleri(linkler) == [F + "RAMP_Ulusal_Basvuru_Kurallari.pdf", F + linkler[5][1].rsplit("/", 1)[1]]
    assert cagri_pdfleri(linkler[:4]) == [F + "RAMP_JTC_2026_Call_Text.pdf"]


# Kayitli cagrilardan (kisaltilmis) metinler
KUDAKA = ("Toplam bütçesi 75.000.000 TL olan program kapsamında proje başına asgari 2.000.000 TL, azami "
          "10.000.000 TL mali destek sağlanacaktır.")
YZE = ("Bugüne kadar her yıl açılan periyodik çağrılarda 61 proje 353,7 milyon TL ile desteklenmiştir.\n"
       "## Ek: cagri_metni.pdf\nBaşvurulan projelerin bütçesi Genel Gider, Proje Teşvik İkramiyesi ve Kurum Hissesi "
       "hariç en fazla 10.000.000 TL (on milyon Türk Lirası) olacaktır.")
TUSEB = ("Proje destek miktarı, Proje Teşvik İkramiyesi (PTİ) dahil en fazla üç milyon (3.000.000,00) TL olabilir.")
KUTUP = ('"Bilimsel Araştırma Bütçesi" 1.500.000 TL ve proje kapsamında ödenebilecek Proje Teşvik İkramiyesi (PTİ) '
         "miktarı ise 100.000 TL olarak güncellenmiştir. Bu çağrı için belirlenen bütçe üst limiti 1.500.000-TL olup, "
         "en fazla 100.000-TL PTİ ödemesi planlanmıştır.")
AHIKA = ("ilan edilen toplam 10.000.000,00 TL bütçeli Teknik Destek Programında, işletme başına azami destek "
         "tutarı 750.000,00 TL'dir.")


@pytest.mark.parametrize("butce, program, metin, beklenen", [
    ("asgari 2.000.000 TL, azami 10.000.000 TL", "75.000.000 TL", KUDAKA,
     ("asgari 2.000.000 TL, azami 10.000.000 TL", "75.000.000 TL")),
    ("75.000.000 TL", None, KUDAKA, (None, "75.000.000 TL")),            # toplam proje basina yazilmis: tasinir
    ("353,7 milyon TL", None, YZE, (None, None)),                       # gecmis istatistik
    ("10.000.000 TL", "Toplam bütçe 10.000.000 TL", YZE, ("10.000.000 TL", None)),  # ayni tutar iki alanda
    ("Toplam bütçe 10.000.000 TL", None, YZE, ("10.000.000 TL", None)),  # ifade alana ters: yalnizca tutar
    ("100.000 TL", "1.500.000 TL", KUTUP, ("1.500.000 TL", None)),     # PTI butce degil; ust limit proje basina
    ("8 milyon TL", "8 milyon TL", "Yatırım tutarı üst sınırı 8 milyon TL’dir.", ("8 milyon TL", None)),  # TL'dir
    (None, "en fazla 3.000.000,00 TL", TUSEB, ("en fazla 3.000.000,00 TL", None)),
    ("10.000.000,00 TL", None, AHIKA, (None, "10.000.000,00 TL")),
    ("750.000,00 TL", "10.000.000,00 TL", AHIKA, ("750.000,00 TL", "10.000.000,00 TL")),
    (None, "Toplam bütçe 40 proje için ayrılmıştır.", KUDAKA, (None, None)),  # tutar yok
    ("1.500.000 TL", None, '"Bilimsel Araştırma Bütçesi" 1.500.000 TL', ("1.500.000 TL", None)),  # belirsiz: yerinde
])
def test_butceleri_ayir(butce, program, metin, beklenen):
    assert butceleri_ayir(butce, program, metin) == beklenen


def test_ground_butce_metinde_yoksa_atilir():
    g = ground(_cikarim(butce="5.000.000 TL", program_butcesi="75.000.000 TL"), KUDAKA, set())
    assert (g.butce, g.program_butcesi) == (None, "75.000.000 TL")


def test_ground_kaynaga_gore():
    metin = ("Başvuru sahipleri: belediyeler, Üniversiteler. 1001 numaralı program değil. "
             "Başvurular 9 Kasım 2026 tarihine kadar alınacaktır.")
    c = _cikarim(basvuru_kosullari=["Üniversiteler"], program_kodu="GİSEP")
    ka = ground(c, metin, set(), "KUDAKA 2026 Yılı 1001 Mali Destek Programı İlan Edildi", "Kalkınma Ajansları")
    assert ka.hedef_kitle == "akademik"
    assert ka.program_kodu == "GISEP"  # baslikta numara kurali yalnizca TUBITAK icin
    tb = ground(c, metin, set(), "1001 Çağrısı", "TÜBİTAK")
    assert tb.hedef_kitle == "sanayi" and tb.program_kodu == "1001"


METIN = ("KUDAKA Mali Destek Programı ilan edildi. Programın ilan tarihi 17 Eylül 2026. Başvurular 9 Kasım 2026 "
         "saat 23.59'a kadar KAYS üzerinden alınacaktır. Sonuçlar 15 Aralık 2026 tarihinde açıklanacaktır.")


@pytest.mark.parametrize("alanlar, tur", [
    ({}, "cagri"),
    ({"tur": "guncelleme"}, "guncelleme"),
    ({"basvurulan": "egitim_etkinlik"}, "cagri_degil"),         # Kadin Muhendis Okulu
    ({"basvurulan": "yok"}, "cagri_degil"),                     # haber / anlasma yururluge girdi
    ({"tur": "cagri_degil", "basvurulan": "proje"}, "cagri_degil"),
])
def test_karar_basvurulan(alanlar, tur):
    c = ground(_cikarim(**alanlar), METIN, set(), "KUDAKA Mali Destek Programı", "Kalkınma Ajansları")
    assert c.tur == tur
    if tur == "cagri_degil" and alanlar.get("tur") != "cagri_degil":
        assert c.sebep != "-"  # neden elendigi duyurular tablosunda gorunsun


def test_karar_basvuru_ifadesi_yoksa_cagri_degil():
    haber = ("Sosyal Gelişmeyi Destekleme Programı kapsamında desteklenen Usta Ellerde Yaşayan Miras projesi için "
             "imzalar atıldı. Proje ile sepetçilik mesleğinin yaşatılması hedefleniyor.")
    c = ground(_cikarim(), haber, set(), "GMKA Desteğiyle Çanakkale'de Sepetçilik Yeniden Canlandırılacak",
               "Kalkınma Ajansları")
    assert c.tur == "cagri_degil" and "ifadesi yok" in c.sebep
    # Baslikta gecmesi yeter (TUSEB kartlari: metin = baslik + kisa ozet)
    kart = ground(_cikarim(), "TÜSEB Bcg Aşısının Yerli Üretimi", set(), "TÜSEB Bcg Aşısı Proje Çağrısı Açıldı!", "TÜSEB")
    assert kart.tur == "cagri"


def test_tarih_basvuru_bayragi():
    c = ground(_cikarim(tarihler=[
        {"etiket": "Programın ilan tarihi", "tarih": "2026-09-17"},             # basvuru=True dese de yayin
        {"etiket": "Son başvuru", "tarih": "2026-11-09"},
        {"etiket": "Sonuçların açıklanması", "tarih": "2026-12-15", "basvuru": False},
        {"etiket": "Uydurma", "tarih": "2027-03-01"},                           # metinde yok
    ]), METIN, set(), "KUDAKA", "Kalkınma Ajansları")
    assert [(t.etiket, t.basvuru) for t in c.tarihler] == [
        ("Programın ilan tarihi", False), ("Son başvuru", True), ("Sonuçların açıklanması", False)]


@pytest.mark.parametrize("a, b, ayni", [
    ("1833-SAYEM Yeşil Dönüşüm 2026-1 Çağrı Takvimi Belli Oldu", "1833-SAYEM Yeşil Dönüşüm 2026 Yılı 1. Çağrısı Açıldı", True),
    ("EMBO Bilimsel Değişim Hibelerine Başvurular Devam Ediyor", "EMBO Bilimsel Değişim Hibelerine Başvurular Devam Ediyor", True),
    ("1707 Sipariş Ar-Ge 2026-2 Çağrısı Açıldı", "1707 Sipariş Ar-Ge 2026 Yılı 3. Çağrısı Açıldı", False),
    ("1833-SAYEM Yeşil Dönüşüm 2026-1 Çağrısı 2. Aşaması Başvuruya Açıldı", "1833-SAYEM Yeşil Dönüşüm 2026 Yılı 1. Çağrısı Açıldı", False),
    ("KUDAKA 2026 Yılı Teknik Destek Programı İlan Edildi", "DAKA 2026 Yılı Teknik Destek Programı İlan Edildi", False),
    ("Çağrı Takvimi Belli Oldu", "Çağrı Takvimi Belli Oldu", False),  # anlamli kelime yok
])
def test_ayni_baslik(a, b, ayni):
    assert fetch.ayni_baslik(a, b) is ayni


@pytest.mark.parametrize("etiket, llm, beklenen", [
    ("E-imzaların tamamlanması için son tarih", False, True),   # LLM tutarsiz; e-imza basvuru tarihidir
    ("Ulusal başvuru e-imza son tarihi", False, True),
    ("Aşama 2 başvurularının TÜBİTAK’a sunulması", False, True),
    ("Şirket kurulumu ve sözleşme imzalanması için son tarih", True, False),
    ("Ön başvuru değerlendirme sonuçlarının bildirilmesi (tam başvuru daveti)", True, False),
    ("Hibe teklif çağrıları yayımlanma tarihi", True, False),
    ("Beklenen proje başlangıcı", False, False),
    ("1833 SAYEM Yeşil Dönüşüm 2026-1. Çağrısı başvurularının açılması", True, False),
    ("Son tarih", True, True),
])
def test_basvuru_tarihi_mi(etiket, llm, beklenen):
    assert _basvuru_tarihi_mi(etiket, llm) is beklenen
