"""YOK fark hesabi: son bilinen durum bilerek bozulur, raporun tam olarak bu degisiklikleri gostermesi beklenir."""

import copy

from backend.yok.fark import Rapor, alan_farki, bolum_farki, detay_farki, liste_farki


def kisi(aid, ad, **kw):
    k = {
        "author_id": aid, "ad_soyad": ad, "unvan": "PROFESÖR", "fakulte": "MÜHENDİSLİK FAKÜLTESİ",
        "bolum": "BİLGİSAYAR MÜHENDİSLİĞİ BÖLÜMÜ", "anabilim_dali_program": "", "temel_alan": "Mühendislik Temel Alanı",
        "bilim_alani": "Bilgisayar Bilimleri", "anahtar_kelimeler": ["Yapay Zeka", "Veri Madenciliği"],
        "eposta": f"{aid.lower()}@pirireis.edu.tr", "orcid": "",
        "makaleler": [{"baslik": "Deep Learning for Ship Detection"}, {"baslik": "Port Logistics Optimization"}],
        "bildiriler": [], "kitaplar": [], "projeler": [{"baslik": "Otonom Gemi"}],
        "dersler": [{"ders_adi": "Algoritmalar", "duzey": "Lisans"}], "yonetilen_tezler": [], "patentler": [],
        "akademik_gorevler": [{"yil": "2015", "unvan": "DOÇENT", "kurum": "PİRİ REİS ÜNİVERSİTESİ"}], "ogrenim": [],
    }
    k.update(kw)
    return k


def test_liste_farki_eklenen_ayrilan_degisen():
    eski = {k["author_id"]: k for k in [kisi("A1", "AHMET YILMAZ"), kisi("B2", "AYŞE KAYA"), kisi("C3", "CAN DEMİR")]}
    yeni = [copy.deepcopy(eski["A1"]), copy.deepcopy(eski["B2"]), kisi("D4", "DENİZ ÖZ")]  # C3 ayrildi, D4 geldi
    yeni[1]["unvan"] = "DOÇENT"

    eklenen, ayrilan, degisen = liste_farki(eski, yeni)

    assert [k["author_id"] for k in eklenen] == ["D4"]
    assert [k["author_id"] for k in ayrilan] == ["C3"]
    assert degisen == {"B2": [{"alan": "unvan", "eski": "PROFESÖR", "yeni": "DOÇENT"}]}


def test_degismeyen_liste_fark_vermez():
    eski = {"A1": kisi("A1", "AHMET YILMAZ")}
    assert liste_farki(eski, [copy.deepcopy(eski["A1"])]) == ([], [], {})


def test_alan_farki_bicim_degisikligini_saymaz():
    eski = kisi("A1", "AHMET YILMAZ")
    yeni = {**eski, "bolum": "Bilgisayar  Mühendisliği Bölümü",  # buyuk/kucuk harf + bosluk
            "anahtar_kelimeler": ["Veri Madenciliği", "Yapay Zeka"]}  # sira
    assert alan_farki(eski, yeni) == []


def test_anahtar_kelime_eklenmesi_fark_verir():
    eski = kisi("A1", "AHMET YILMAZ")
    yeni = {**eski, "anahtar_kelimeler": [*eski["anahtar_kelimeler"], "Denizcilik"]}
    [f] = alan_farki(eski, yeni)
    assert f["alan"] == "anahtar_kelimeler"


def test_detay_farki_kalem_bazinda():
    eski = kisi("A1", "AHMET YILMAZ")
    yeni = copy.deepcopy(eski)
    yeni["makaleler"].append({"baslik": "Maritime Cybersecurity"})
    yeni["makaleler"] = [m for m in yeni["makaleler"] if m["baslik"] != "Port Logistics Optimization"]
    yeni["dersler"].append({"ders_adi": "Makine Öğrenmesi", "duzey": "Yüksek Lisans"})
    yeni["akademik_gorevler"].insert(0, {"yil": "2021", "unvan": "PROFESÖR", "kurum": "PİRİ REİS ÜNİVERSİTESİ"})

    f = detay_farki(eski, yeni)

    assert f == {
        "makaleler": {"eklenen": ["Maritime Cybersecurity"], "silinen": ["Port Logistics Optimization"]},
        "dersler": {"eklenen": ["Makine Öğrenmesi (Yüksek Lisans)"], "silinen": []},
        "akademik_gorevler": {"eklenen": ["2021 · PROFESÖR · PİRİ REİS ÜNİVERSİTESİ"], "silinen": []},
    }


def test_detay_farki_baslik_bicimi_ve_sira_degisince_bos():
    eski = kisi("A1", "AHMET YILMAZ")
    yeni = copy.deepcopy(eski)
    yeni["makaleler"] = [{"baslik": "PORT LOGISTICS OPTIMIZATION."}, {"baslik": "deep learning for ship detection"}]
    assert detay_farki(eski, yeni) == {}


def test_ayni_baslik_iki_kez_coklu_kume():
    goster = lambda y: y["baslik"]  # noqa: E731
    eski = [{"baslik": "Kitap Bölümü"}, {"baslik": "Kitap Bölümü"}]
    assert bolum_farki(eski, eski[:1], goster) == {"eklenen": [], "silinen": ["Kitap Bölümü"]}
    assert bolum_farki(eski[:1], eski, goster) == {"eklenen": ["Kitap Bölümü"], "silinen": []}


def test_kitap_bolumleri_ayni_kitapta_ayri_kalem():
    eski = kisi("A1", "X", kitaplar=[{"baslik": "Denizcilik Yazıları", "bolum_adi": "Liman Yönetimi"}])
    yeni = kisi("A1", "X", kitaplar=[*eski["kitaplar"], {"baslik": "Denizcilik Yazıları", "bolum_adi": "Gemi Enerjisi"}])
    assert detay_farki(eski, yeni)["kitaplar"]["eklenen"] == ["Gemi Enerjisi (Denizcilik Yazıları)"]


def test_rapor_alan_ve_bolum_farkini_ayni_kiside_birlestirir():
    r = Rapor()
    k = kisi("B2", "AYŞE KAYA")
    r.degisen_ekle(k, alanlar=[{"alan": "unvan", "eski": "DOÇENT", "yeni": "PROFESÖR"}])
    r.degisen_ekle(k, bolumler={"makaleler": {"eklenen": ["Yeni"], "silinen": []}})
    r.degisen_ekle(kisi("C3", "CAN"), alanlar=[], bolumler={})  # bos fark raporu kirletmez

    assert r.ozet() == {"eklenen": 0, "ayrilan": 0, "degisen": 1}
    [d] = r.json()["degisen"]
    assert d["author_id"] == "B2" and len(d["alanlar"]) == 1 and "makaleler" in d["bolumler"]
