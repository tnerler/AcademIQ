"""
YOK akademisyenlerini eslestirme havuzuna indeksler: yok_akademisyenler -> arama bolumleri -> LLM profil ozeti
-> PGVectorStore (CV'lerle ayni cv_chunks / hoca_profilleri tablolari, kimlik YOK_<authorId>).

Aramaya giren alanlar (bkz. arama_bolumleri): anahtar kelimeler, bilim/temel alan ve birim; doktora ve yuksek
lisans tezleri; makale/bildiri basliklari + yayin yeri, kitap (bolum) basliklari; proje basligi + konusu;
yonetilen tezler; patent basligi + ozeti; verdigi dersler. Diger alanlar metadata'da ("yok") saklanir.

Yalnizca icerigi degisen hocalar yeniden islenir (kaynak_hash); havuzdan cikan (aktif olmayan) hocalar silinir.
YOK taramasindan sonra yok-worker bunu kendisi calistirir.

  uv run python -m backend.yok.index            # degisenleri indeksle
  uv run python -m backend.yok.index --hepsi    # hepsini yeniden indeksle
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import logging
import re

from langchain_core.documents import Document
from sqlalchemy import select

from backend.api.schemas import CVCikarim, Egitim, Gorev, Iletisim, Kimlik, Proje, Tez, Yayin
from backend.cagrilar.db import get_engine
from backend.config import get_settings
from backend.indexing.chunker import build_chunks
from backend.indexing.index_cvs import delete_cv, kayitli_hocalar
from backend.indexing.profile import AkademikProfil, format_sections, profile_chain, profile_text
from backend.vectorstore import apply_indexes, doc_id, get_chunk_store, get_profile_store, init_tables
from backend.yok import YOK_ID_ONEKI
from backend.yok.db import yok_akademisyenler

logger = logging.getLogger("yok")

SURUM = 1  # metin bicimi degisirse artirin: tum hocalar yeniden indekslenir
KONU_MAX = 800  # proje konusu / patent ozeti: chunk'i tek bir uzun metne bogmamak icin


def hoca_id(author_id: str) -> str:
    return f"{YOK_ID_ONEKI}{author_id}"


# --- Metin yardimcilari ----------------------------------------------------------

_BAGLACLAR = {"ve", "ile", "için", "veya", "ya", "da", "de"}


def _kucuk(metin: str) -> str:
    return metin.replace("I", "ı").replace("İ", "i").lower()


def tr_baslik(metin: str) -> str:
    """'GEMİ İNŞAATI VE GEMİ MAKİNELERİ BÖLÜMÜ' -> 'Gemi İnşaatı ve Gemi Makineleri Bölümü' (yalnizca tamami buyukse)."""
    if not metin.isupper():
        return metin
    kelimeler = []
    for i, w in enumerate(metin.split(" ")):
        k = _kucuk(w)
        kelimeler.append(k if i and k in _BAGLACLAR else w[:1] + k[1:])
    return " ".join(kelimeler)


def _kisalt(metin: str, n: int = KONU_MAX) -> str:
    metin = re.sub(r"\s+", " ", metin or "").strip()
    return metin if len(metin) <= n else metin[:n].rsplit(" ", 1)[0] + "…"


def _yil(metin: str | None) -> int | None:
    yillar = re.findall(r"(?:19|20)\d{2}", metin or "")
    return int(yillar[-1]) if yillar else None


def _yayin_satiri(baslik: str, yil: str, yer: str) -> str:
    return f"{baslik}{f' ({yil})' if yil else ''}{f' — {yer}' if yer else ''}"


def _bitti(o: dict) -> bool:
    """YOK tamamlanan ogrenimi yil araligiyla ('2018-2025') verir; tek yil devam edenin baslangici."""
    return bool(re.search(r"\d{4}\s*-\s*\d{4}", o.get("yil") or ""))


def doktorali(k: dict) -> bool:
    return any("doktora" in (o.get("derece") or "").lower() and _bitti(o) for o in k.get("ogrenim", []))


def kisa_unvan(k: dict) -> str:
    """YOK unvani -> CV'lerdeki kisa bicim ('DOKTOR ÖĞRETİM ÜYESİ (Unvan:Doçent)' -> 'Doç. Dr.')."""
    u = k.get("unvan", "").upper()
    if "PROFESÖR" in u:
        return "Prof. Dr."
    if "DOÇENT" in u:
        return "Doç. Dr."
    if "DOKTOR ÖĞRETİM ÜYESİ" in u:
        return "Dr. Öğr. Üyesi"
    dr = " Dr." if doktorali(k) else ""
    if "ÖĞRETİM GÖREVLİSİ" in u:
        return f"Öğr. Gör.{dr}"
    if "ARAŞTIRMA GÖREVLİSİ" in u:
        return f"Arş. Gör.{dr}"
    return tr_baslik(k.get("unvan", ""))


# --- Aramaya giren bolumler --------------------------------------------------------

def arama_bolumleri(k: dict) -> dict[str, list[str]]:
    """SECTION_LABELS anahtari -> madde listesi (chunk'lanan ve LLM profiline giden metin)."""
    birim = " / ".join(tr_baslik(x) for x in (k.get("fakulte"), k.get("bolum"), k.get("anabilim_dali_program")) if x)
    arastirma = [*k.get("anahtar_kelimeler", [])]
    arastirma += [f"{e}: {v}" for e, v in (("Bilim alanı", k.get("bilim_alani")), ("Temel alan", k.get("temel_alan"))) if v]
    if birim:
        arastirma.append(f"Birim: {birim}")

    kitaplar = [
        _yayin_satiri(f"{b['bolum_adi']} (Kitap: {b['baslik']})" if b.get("bolum_adi") else b["baslik"], b.get("yil", ""), "")
        for b in k.get("kitaplar", [])
    ]
    projeler = []
    for p in k.get("projeler", []):
        donem = "–".join(str(y) for y in dict.fromkeys(filter(None, (_yil(p.get("baslangic")), _yil(p.get("bitis"))))))
        satir = f"{p['baslik']}{f' ({donem})' if donem else ''}"
        if p.get("proje_konusu"):
            satir += f": {_kisalt(p['proje_konusu'])}"
        projeler.append(satir)

    return {
        "arastirma": arastirma,
        "egitim": [f"{o['derece']} tezi: {o['tez_adi']}" for o in k.get("ogrenim", []) if o.get("tez_adi")],
        "yayinlar": [_yayin_satiri(y["baslik"], y.get("yil", ""), y.get("yayin_yeri", ""))
                     for y in (*k.get("makaleler", []), *k.get("bildiriler", []))] + kitaplar,
        "projeler": projeler,
        "yonetilen_tezler": [f"{t['duzey']}: {t['tez_adi']}" for t in k.get("yonetilen_tezler", [])],
        "patentler": [f"{p['baslik']}{f': {_kisalt(p['ozet'])}' if p.get('ozet') else ''}" for p in k.get("patentler", [])],
        "dersler": list(dict.fromkeys(d["ders_adi"] for d in k.get("dersler", []))),
    }


# --- UI detay paneli icin CV semasi --------------------------------------------------

def cv_cikarim(k: dict) -> CVCikarim:
    """YOK verisini CV'lerle ayni sekle cevirir (CV'ler sayfasindaki detay paneli bunu gosterir)."""
    yayinlar = [Yayin(baslik=y["baslik"], yil=_yil(y.get("yil")), tur="makale", yayin_yeri=y.get("yayin_yeri") or None)
                for y in k.get("makaleler", [])]
    yayinlar += [Yayin(baslik=y["baslik"], yil=_yil(y.get("yil")), tur="bildiri", yayin_yeri=y.get("yayin_yeri") or None)
                 for y in k.get("bildiriler", [])]
    yayinlar += [Yayin(baslik=b.get("bolum_adi") or b["baslik"], yil=_yil(b.get("yil")),
                       tur="kitap_bolumu" if b.get("bolum_adi") else "kitap",
                       yayin_yeri=(b["baslik"] if b.get("bolum_adi") else b.get("yayin_yeri")) or None)
                 for b in k.get("kitaplar", [])]
    yayinlar += [Yayin(baslik=p["baslik"], yil=_yil(p.get("basvuru_no")), tur="diger",
                       yayin_yeri=f"Patent {p['basvuru_no']}".strip())
                 for p in k.get("patentler", [])]
    return CVCikarim(
        kimlik=Kimlik(unvan=kisa_unvan(k), ad_soyad=tr_baslik(k["ad_soyad"]), universite=tr_baslik(k.get("universite", "")),
                      fakulte=tr_baslik(k.get("fakulte", "")) or None, bolum=tr_baslik(k.get("bolum", "")) or None),
        iletisim=Iletisim(email=k.get("eposta") or None, orcid=k.get("orcid") or None, web=k.get("profil_url"),
                          yoksis=k.get("arastirmaci_id") or None),
        arastirma_alanlari=k.get("anahtar_kelimeler", []),
        egitim=[Egitim(derece=o["derece"] if _bitti(o) else f"{o['derece']} (devam ediyor)", universite=o["kurum"] or "—",
                       birim=o.get("birim") or None, yil=_yil(o.get("yil")) if _bitti(o) else None,
                       tez_basligi=o.get("tez_adi") or None) for o in k.get("ogrenim", [])],
        akademik_gorevler=[Gorev(gorev=tr_baslik(g["unvan"]), kurum=" · ".join(filter(None, (g["kurum"], tr_baslik(g.get("birim", ""))))),
                                 donem=g.get("yil") or None) for g in k.get("akademik_gorevler", [])],
        projeler=[Proje(ad=p["baslik"], program=tr_baslik(p.get("tur", "")) or None, gorev=p.get("rol") or None,
                        donem=" – ".join(filter(None, (p.get("baslangic"), p.get("bitis")))) or None)
                  for p in k.get("projeler", [])],
        yonetilen_tezler=[Tez(baslik=t["tez_adi"], seviye=t["duzey"], ogrenci=tr_baslik(t.get("hazirlayan", "")) or None,
                              yil=t.get("yil") or None) for t in k.get("yonetilen_tezler", [])],
        dersler=list(dict.fromkeys(d["ders_adi"] for d in k.get("dersler", []))),
        yayinlar=yayinlar,
    )


def icerik_hash(k: dict) -> str:
    """Bolumler ve CV semasi YOK verisinden turetildigi icin veri + SURUM yeter (metadata da guncel kalir)."""
    return hashlib.sha256(json.dumps([SURUM, k], ensure_ascii=False, sort_keys=True).encode()).hexdigest()


# --- DB ------------------------------------------------------------------------

def _yaz(k: dict, sections: dict, cv: CVCikarim, profil: AkademikProfil, kaynak_hash: str) -> None:
    hid = hoca_id(k["author_id"])
    get_profile_store().add_documents([Document(
        page_content=profile_text(profil),
        metadata={
            "hoca_id": hid, "unvan": cv.kimlik.unvan, "ad_soyad": cv.kimlik.ad_soyad, "universite": cv.kimlik.universite,
            "fakulte": cv.kimlik.fakulte, "bolum": cv.kimlik.bolum, "email": cv.iletisim.email,
            "kaynak_pdf": k["profil_url"],  # PDF yok; kaynak YOK profil sayfasi
            "profil": profil.model_dump(),
            "cv": cv.model_dump(),
            "kaynak_hash": kaynak_hash,
            "kaynak": "yok",
            "yok": k,  # tum YOK verisi: filtre/skor icin (unvan, doktora yili, proje rolu, yayin etiketleri ...)
        },
    )], ids=[doc_id(hid)])

    chunk_store = get_chunk_store()
    eski = chunk_store.get(where={"hoca_id": hid}, include=[])["ids"]
    if eski:
        chunk_store.delete(ids=eski)
    chunks = build_chunks(hid, sections)
    if chunks:
        chunk_store.add_documents(chunks, ids=[doc_id(hid, c.metadata["sira"]) for c in chunks])


def _profil(sections: dict, cv: CVCikarim) -> AkademikProfil:
    girdi = f"Akademisyen: {cv.kimlik.unvan} {cv.kimlik.ad_soyad}\n\n{format_sections(sections)}"
    return profile_chain.invoke({"cv": girdi})


def senkronize(hepsi: bool = False, concurrency: int = 6) -> dict[str, int]:
    """Aktif ve detayi cekilmis YOK hocalarini havuza yazar; degismeyenleri atlar, cikanlari siler."""
    init_tables()
    with get_engine().connect() as conn:
        kisiler = [r.veri for r in conn.execute(
            select(yok_akademisyenler.c.veri).where(yok_akademisyenler.c.aktif, yok_akademisyenler.c.detay_var,
                                                    yok_akademisyenler.c.universite == get_settings().yok_universite))]
    kayitli = {h: m for h, m in kayitli_hocalar().items() if h.startswith(YOK_ID_ONEKI)}
    hedefler = {}
    for k in kisiler:
        h = icerik_hash(k)
        if hepsi or kayitli.get(hoca_id(k["author_id"]), {}).get("kaynak_hash") != h:
            hedefler[k["author_id"]] = (k, arama_bolumleri(k), cv_cikarim(k), h)
    silinecek = set(kayitli) - {hoca_id(k["author_id"]) for k in kisiler}
    logger.info("YOK indeks: %d hoca, %d islenecek, %d silinecek", len(kisiler), len(hedefler), len(silinecek))

    for hid in silinecek:
        delete_cv(hid)
    sayac = {"islenen": 0, "hatali": 0, "silinen": len(silinecek)}
    # LLM profil cagrilari paralel, DB yazimi sirali
    with ThreadPoolExecutor(concurrency) as ex:
        futures = {aid: ex.submit(_profil, sections, cv) for aid, (_, sections, cv, _) in hedefler.items()}
        for aid, fut in futures.items():
            k, sections, cv, h = hedefler[aid]
            try:
                _yaz(k, sections, cv, fut.result(), h)
                sayac["islenen"] += 1
                logger.info("OK    %s %s (%d chunk bolumu)", hoca_id(aid), k["ad_soyad"], sum(bool(v) for v in sections.values()))
            except Exception as exc:  # tek hocanin hatasi tum indekslemeyi durdurmasin
                logger.error("HATA  %s %s: %s", hoca_id(aid), k["ad_soyad"], exc)
                sayac["hatali"] += 1
    if sayac["islenen"] or sayac["silinen"]:
        apply_indexes()
    return sayac


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hepsi", action="store_true", help="degismeyenleri de yeniden indeksle")
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--eslesme-atla", action="store_true", help="kayitli cagri eslestirmelerini yenileme")
    args = ap.parse_args()
    sayac = senkronize(args.hepsi, args.concurrency)
    if (sayac["islenen"] or sayac["silinen"]) and not args.eslesme_atla:
        from backend.indexing.index_cvs import eslesmeleri_yenile
        eslesmeleri_yenile()
    logger.info("Tamamlandi: %s", sayac)
    return 0 if not sayac["hatali"] else 2


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    raise SystemExit(main())
