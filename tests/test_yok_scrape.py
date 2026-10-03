"""YOK sayfa parser'lari: tests/fixtures/yok altindaki gercek sayfalar (fotograflar ve scriptler cikarildi).
Site HTML'i degisirse bu testler bozulur."""

from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from backend.yok import scrape

FIX = Path(__file__).parent / "fixtures" / "yok"


def sayfa(ad: str) -> BeautifulSoup:
    return BeautifulSoup((FIX / ad).read_text(encoding="utf-8"), "html.parser")


def test_liste_satiri_ve_sayfalama():
    s = sayfa("liste.html")
    satirlar = s.select('tr[id^="authorInfo_"]')
    assert len(satirlar) == 20
    k = scrape.satir_ayristir(satirlar[0])
    assert k["author_id"] == "57A6856663E8E116"
    assert k["ad_soyad"] == "AHMET TAŞDEMİR" and k["unvan"] == "PROFESÖR"
    assert k["fakulte"] == "DENİZCİLİK FAKÜLTESİ"
    assert k["anahtar_kelimeler"] == ["Gemi İnşaatı", "Gemi Hidromekaniği", "Deniz Araçları Yapısal Tasarımı"]
    assert k["orcid"] == "0000-0002-7414-2525" and k["eposta"] == "atasdemir@pirireis.edu.tr"
    assert scrape.sonraki_sayfa(s).startswith("/AkademikArama/AramaFiltrele?islem=")


def test_profil():
    p = scrape.profil_ayristir(sayfa("profil.html"))
    assert p["akademik_gorevler"][0] == {"unvan": "PROFESÖR", "yil": "2016", "kurum": "PİRİ REİS ÜNİVERSİTESİ",
                                         "birim": "DENİZCİLİK FAKÜLTESİ GEMİ MAKİNELERİ İŞLETME MÜHENDİSLİĞİ BÖLÜMÜ"}
    assert p["ogrenim"][0]["derece"] == "Doktora"
    assert p["ogrenim"][0]["tez_adi"].startswith("Experimentelle und numerische")


def test_kisi_sayfasi_kontrolu():
    assert scrape._kisi_sayfasi_mi(sayfa("profil.html"), "AHMET TAŞDEMİR")
    assert scrape._kisi_sayfasi_mi(sayfa("makaleler.html"), "AHMET TAŞDEMİR")
    assert not scrape._kisi_sayfasi_mi(sayfa("makaleler.html"), "AYKUT ARSLAN")


def test_makaleler():
    m = scrape.yayinlar_ayristir(sayfa("makaleler.html"))
    assert len(m) == 31
    assert m[0]["baslik"] == "Assessment of the shipbuilding industry with a value-oriented approach"
    assert m[0]["yil"] == "2025" and m[0]["yayin_yeri"] == "Journal of Ocean Engineering and Marine Energy"
    assert "SSCI" in m[0]["etiketler"] and m[0]["doi"].startswith("https://dx.doi.org/")
    assert all(x["baslik"] and x["yil"] for x in m)


def test_bildiriler_tarihten_yil():
    b = scrape.yayinlar_ayristir(sayfa("bildiriler.html"))
    assert len(b) == 13
    assert b[0]["tarih"] == "11.11.2020" and b[0]["yil"] == "2020"
    assert b[0]["yayin_yeri"] == "İstanbul Barosu (Çevrimiçi)"


def test_kitaplar_ve_bolum_adi():
    k = scrape.kitaplar_ayristir(sayfa("kitaplar.html"))
    assert len(k) == 44
    assert k[0]["bolum_adi"] == "" and k[0]["yil"] == "2021" and k[0]["tur"] == ["Bilimsel Kitap"]
    assert k[1]["bolum_adi"] == "Birden Çok Sigortaya İlişkin Bazı Sorunlar"


def test_projeler():
    [p, *_] = scrape.projeler_ayristir(sayfa("projeler.html"), "BE2CD8C7C095F14D")
    assert p["baslik"].startswith("İstanbul'da Deprem Sonrası")
    assert (p["durum"], p["baslangic"], p["bitis"]) == ("Tamamlandı", "01.06.2024", "31.12.2025")
    assert p["butce"] == "60000 TÜRK LİRASI" and p["rol"] == "Yürütücü"
    assert p["proje_konusu"].startswith("Depremler")


def test_dersler_tekillestirilir():
    d = scrape.dersler_ayristir(sayfa("dersler.html"))
    assert len(d) == 22
    ns = next(x for x in d if x["ders_adi"] == "Naval Architecture and Ship Stability")
    assert ns["duzey"] == "Lisans" and len(ns["donemler"]) > 1


def test_tezler():
    t = scrape.tezler_ayristir(sayfa("tezler.html"))
    assert len(t) == 5 and t[0]["duzey"] == "Doktora" and t[0]["hazirlayan"] == "SEVGİ CAN AYDIN"


@pytest.mark.parametrize("i,no", [(0, "2022/003283"), (1, "2020/02642")])
def test_patentler(i, no):
    p = scrape.patentler_ayristir(sayfa("patentler.html"))[i]
    assert p["basvuru_no"] == no and p["basvuru_sahipleri"] == "Piri Reis Üniversitesi" and p["ozet"]
