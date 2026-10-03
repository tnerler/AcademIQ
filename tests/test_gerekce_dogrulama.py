"""Gerekce dogrulamasi: model kanitlari numarali CV satirlariyla gosterir; var olmayan numaralar duser, kaniti
olmayan aranan konular eksik sayilir. Ornekler gercek eslestirmelerde gorulen hatalardan alindi."""

from backend.api.schemas import IlanOzet
from backend.matching.pipeline import _evidence
from backend.matching.rationale import (
    Gerekce, KonuKarsiligi, _numarali_cv, dayanilan_satirlar, eksik_konular, gerekce_metni, kanit_satirlari, sade,
)
from backend.matching.search import ChunkHit

PROJELER = ChunkHit("c1", "H1", "projeler", "[Bölüm: Projeler]\n"
                    "Bor Katkılı metal matrix kompozit (2003)\n"
                    "Toz metalurjisinde elektrik alan sinterleme tekniğinin modellenmesi", 0.0, 0.50)
YAYINLAR = ChunkHit("c2", "H1", "yayinlar", "[Bölüm: Yayınlar]\n"
                    "Residual Stress Using Wire Arc Additive Manufacturing (2024) — Mechanics &amp; Fabrication\n"
                    "Bor Katkılı metal matrix kompozit (2003)", 0.0, 0.40)  # ayni kayit iki bolumde
SATIRLAR = kanit_satirlari([PROJELER, YAYINLAR])


def ilan(*aranan):
    return IlanOzet(baslik="Çağrı", konu="Konu", amac_kapsam="", aranan_uzmanliklar=list(aranan),
                    anahtar_kelimeler=[], sorgu_metni="")


def gerekce(*konu_satir, satirlar=()):
    return Gerekce(konu_karsiliklari=[KonuKarsiligi(konu_no=k, satir_no=s) for k, s in konu_satir],
                   gerekce="Gerekçe.", kanit_satirlari=list(satirlar))


def test_satirlar_bolum_basligi_haric_numaralanir():
    assert [(s.no, s.chunk.bolum) for s in SATIRLAR] == [(1, "projeler"), (2, "projeler"), (3, "yayinlar"),
                                                        (4, "yayinlar")]
    metin = _numarali_cv([PROJELER, YAYINLAR])
    assert "[Bölüm: Projeler]\nS1: Bor Katkılı" in metin and "S3: Residual Stress" in metin


def test_var_olmayan_satir_numarasi_duser():
    g = gerekce((1, 99), satirlar=[2, 42])
    assert [s.no for s in dayanilan_satirlar(g, SATIRLAR)] == [2]


def test_kaniti_null_ya_da_gecersiz_olan_ve_atlanan_konular_eksiktir():
    g = gerekce((1, 3), (2, None), (3, 99))  # 4. konu icin kayit yok
    eksik = eksik_konular(g, ilan("Katmanlı imalat", "Geri dönüşüm", "Hafif tasarım", "Dijital modelleme"), SATIRLAR)
    assert eksik == ["Geri dönüşüm", "Hafif tasarım", "Dijital modelleme"]


def test_kanitlar_bolume_gore_gruplanir_ve_tekrar_eden_kayit_bir_kez_gosterilir():
    kanitlar = _evidence(SATIRLAR, dayanilan_satirlar(gerekce(satirlar=[1, 3, 4]), SATIRLAR), best_sim=0.5)
    assert [(k.bolum, k.maddeler, k.skor) for k in kanitlar] == [
        ("projeler", ["Bor Katkılı metal matrix kompozit (2003)"], 100.0),
        ("yayinlar", ["Residual Stress Using Wire Arc Additive Manufacturing (2024) — Mechanics &amp; Fabrication"],
         80.0),
    ]


def test_model_satir_gostermezse_en_benzer_chunklarin_ilk_satirlari():
    kanitlar = _evidence(SATIRLAR, [], best_sim=0.5)
    assert kanitlar[0].bolum == "projeler" and len(kanitlar[0].maddeler) == 2


def test_sade_html_aksan_ve_noktalamayi_yok_sayar():
    assert sade("Mechanics &amp; Fabrication") == sade("mechanics & fabrication")
    assert sade("Yapay Zekâ") == sade("Yapay Zeka")


def test_gerekce_metni_eksikleri_sinirli_sayida_ekler():
    g = gerekce()
    assert gerekce_metni(g, []) == "Gerekçe."
    metin = gerekce_metni(g, ["A", "B", "C", "D", "E", "F"])
    assert metin == "Gerekçe. CV'de karşılığı bulunamayan aranan konular: A, B, C, D (+2)."


def test_gerekceye_sizan_satir_numaralari_temizlenir():
    g = gerekce()
    g.gerekce = ("Balık tankı projesi (S7) hafif tasarımı içerir. Sinterleme çalışmaları (S10, S12) var. "
                 "Uzmanlığı S3, sinir ağları tezleri S1 ve S2 ile desteklenir. SiC ve B4C kompozitleri var.")
    assert gerekce_metni(g, []) == ("Balık tankı projesi hafif tasarımı içerir. Sinterleme çalışmaları var. "
                                    "Uzmanlığı, sinir ağları tezleri ile desteklenir. SiC ve B4C kompozitleri var.")
