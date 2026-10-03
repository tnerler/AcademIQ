"""YOK verisi -> arama bolumleri ve CV semasi (LLM cagrisi yok)."""

from backend.indexing.chunker import build_chunks
from backend.yok.index import arama_bolumleri, cv_cikarim, icerik_hash, kisa_unvan, tr_baslik


def hoca(**kw):
    k = {
        "author_id": "ABC123", "arastirmaci_id": "42", "ad_soyad": "AYŞE IŞIK", "unvan": "DOKTOR ÖĞRETİM ÜYESİ",
        "universite": "PİRİ REİS ÜNİVERSİTESİ", "fakulte": "MÜHENDİSLİK FAKÜLTESİ",
        "bolum": "GEMİ İNŞAATI VE GEMİ MAKİNELERİ MÜHENDİSLİĞİ BÖLÜMÜ", "anabilim_dali_program": "",
        "temel_alan": "Mühendislik Temel Alanı", "bilim_alani": "Deniz ve Gemi Mühendisliği",
        "anahtar_kelimeler": ["Gemi Hidrodinamiği"], "eposta": "aisik@pirireis.edu.tr", "orcid": "",
        "profil_url": "https://akademik.yok.gov.tr/x?authorId=ABC123",
        "akademik_gorevler": [{"unvan": "DOKTOR ÖĞRETİM ÜYESİ", "yil": "2020", "kurum": "PİRİ REİS ÜNİVERSİTESİ", "birim": ""}],
        "ogrenim": [{"derece": "Doktora", "yil": "2014-2019", "kurum": "İTÜ", "birim": "", "tez_adi": "Pervane kavitasyonu"}],
        "makaleler": [{"baslik": "Ship resistance", "yil": "2023", "yayin_yeri": "Ocean Engineering", "etiketler": []}],
        "bildiriler": [{"baslik": "Hull form", "yil": "", "yayin_yeri": "", "etiketler": []}],
        "kitaplar": [{"baslik": "Denizcilik Yazıları", "bolum_adi": "Liman Yönetimi", "yil": "2022", "yayin_yeri": "Springer"}],
        "projeler": [{"baslik": "Otonom tekne", "baslangic": "01.03.2022", "bitis": "01.03.2024", "tur": "ARAŞTIRMA PROJESİ",
                      "rol": "Yürütücü", "proje_konusu": "x " * 1000}],
        "dersler": [{"ders_adi": "Statik", "duzey": "Lisans"}, {"ders_adi": "Statik", "duzey": "Yüksek Lisans"}],
        "yonetilen_tezler": [{"tez_adi": "Dümen tasarımı", "duzey": "Yüksek Lisans", "yil": "2024", "hazirlayan": "ALİ VELİ"}],
        "patentler": [{"baslik": "Pervane", "basvuru_no": "2021/0042", "ozet": "Yeni pervane."}],
    }
    k.update(kw)
    return k


def test_arama_bolumleri():
    s = arama_bolumleri(hoca())
    assert s["arastirma"] == [
        "Gemi Hidrodinamiği", "Bilim alanı: Deniz ve Gemi Mühendisliği", "Temel alan: Mühendislik Temel Alanı",
        "Birim: Mühendislik Fakültesi / Gemi İnşaatı ve Gemi Makineleri Mühendisliği Bölümü",
    ]
    assert s["egitim"] == ["Doktora tezi: Pervane kavitasyonu"]
    assert s["yayinlar"] == ["Ship resistance (2023) — Ocean Engineering", "Hull form",
                             "Liman Yönetimi (Kitap: Denizcilik Yazıları) (2022)"]
    assert s["projeler"][0].startswith("Otonom tekne (2022–2024): x x")
    assert len(s["projeler"][0]) < 900  # uzun proje konusu kisaltilir
    assert s["patentler"] == ["Pervane: Yeni pervane."]
    assert s["dersler"] == ["Statik"]  # duzeyler arasi tekillestirilir
    assert s["yonetilen_tezler"] == ["Yüksek Lisans: Dümen tasarımı"]


def test_bos_profil_birimle_aranabilir():
    s = arama_bolumleri(hoca(anahtar_kelimeler=[], bilim_alani="", temel_alan="", makaleler=[], bildiriler=[],
                             kitaplar=[], projeler=[], dersler=[], yonetilen_tezler=[], patentler=[], ogrenim=[]))
    assert [c.metadata["bolum"] for c in build_chunks("YOK_ABC123", s)] == ["arastirma"]


def test_kisa_unvan_ve_devam_eden_doktora():
    assert kisa_unvan(hoca()) == "Dr. Öğr. Üyesi"
    assert kisa_unvan(hoca(unvan="DOKTOR ÖĞRETİM ÜYESİ (Unvan:Doçent)")) == "Doç. Dr."
    devam = [{"derece": "Doktora", "yil": "2024", "kurum": "İTÜ", "birim": "", "tez_adi": ""}]
    assert kisa_unvan(hoca(unvan="ARAŞTIRMA GÖREVLİSİ", ogrenim=devam)) == "Arş. Gör."
    assert kisa_unvan(hoca(unvan="ARAŞTIRMA GÖREVLİSİ")) == "Arş. Gör. Dr."
    cv = cv_cikarim(hoca(ogrenim=devam))
    assert cv.egitim[0].derece == "Doktora (devam ediyor)" and cv.egitim[0].yil is None


def test_cv_semasi():
    cv = cv_cikarim(hoca())
    assert (cv.kimlik.ad_soyad, cv.kimlik.universite) == ("Ayşe Işık", "Piri Reis Üniversitesi")
    assert cv.iletisim.web.startswith("https://akademik.yok.gov.tr")
    assert [y.tur for y in cv.yayinlar] == ["makale", "bildiri", "kitap_bolumu", "diger"]
    assert cv.projeler[0].gorev == "Yürütücü" and cv.yonetilen_tezler[0].seviye == "yuksek_lisans"
    assert cv.dersler == ["Statik"]


def test_tr_baslik():
    assert tr_baslik("İKTİSADİ VE İDARİ BİLİMLER FAKÜLTESİ") == "İktisadi ve İdari Bilimler Fakültesi"
    assert tr_baslik("Zaten Düzgün") == "Zaten Düzgün"


def test_icerik_hash_degisiklikte_degisir():
    assert icerik_hash(hoca()) == icerik_hash(hoca())
    assert icerik_hash(hoca()) != icerik_hash(hoca(anahtar_kelimeler=["Başka"]))
