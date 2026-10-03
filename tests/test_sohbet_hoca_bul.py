from backend.sohbet.hoca_bul import sirala

HOCALAR = [
    {"hoca_id": "1", "ad_soyad": "Erkan Kıyak"},
    {"hoca_id": "2", "ad_soyad": "Erkan Aydın"},
    {"hoca_id": "3", "ad_soyad": "Gizem Dilara Açan Yıldız"},
]


def test_tam_ad_turkce_karaktersiz_bulunur():
    bulunan, adaylar = sirala("erkan kiyak", HOCALAR)
    assert bulunan["hoca_id"] == "1" and adaylar == []


def test_yazim_hatasi_tolere_edilir():
    bulunan, _ = sirala("Erkan Kıyac", HOCALAR)
    assert bulunan["hoca_id"] == "1"


def test_yalnizca_soyad_yeter():
    bulunan, _ = sirala("Yıldız", HOCALAR)
    assert bulunan["hoca_id"] == "3"


def test_belirsiz_ad_adaylari_dondurur():
    bulunan, adaylar = sirala("Erkan", HOCALAR)
    assert bulunan is None
    assert {m["hoca_id"] for m in adaylar} == {"1", "2"}


def test_bulunamayan_ad():
    bulunan, adaylar = sirala("Mehmet Öztürk", HOCALAR)
    assert bulunan is None and adaylar == []
