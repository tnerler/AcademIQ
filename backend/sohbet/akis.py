"""
Sohbet akisi: mesaj -> LLM ile niyet -> (ilan / alan) eslestirme ya da (hoca) CV'den yanit -> SohbetYaniti

  ilan   : yapistirilan proje ilani            -> match_text(mesaj)
  alan   : "computer vision calismis hoca"     -> match_text(tek basina anlasilir arama metni)
  hoca   : "Erkan Kiyak'in deneyimleri"        -> isimden akademisyen bul, CV verisiyle yanitla
  sohbet : selamlama, yardim, kapsam disi      -> niyet modelinin kisa yaniti

CLI ile deneme:
  uv run python -m backend.sohbet.akis "bilgisayarli goru alaninda calismis hocalar"
"""

from __future__ import annotations

import asyncio
import json
import sys

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from backend.api.schemas import MatchResponse, SohbetMesaji, SohbetTuru, SohbetYaniti
from backend.llm import get_llm
from backend.matching.pipeline import hoca_ozet, match_text
from backend.sohbet.hoca_bul import hoca_bul

GECMIS_MESAJ = 6  # niyet modeline giden son mesaj sayisi
GECMIS_KARAKTER = 600  # gecmisteki her mesajin kirpildigi uzunluk
NIYET_KARAKTER = 2500  # uzun ilan metinlerinin niyet icin okunan kismi
CV_KARAKTER = 20000  # hoca yanitina giden CV verisi
ONE_CIKAN = 3  # yanit metninde adi gecen ilk hoca sayisi


class Niyet(BaseModel):
    tur: SohbetTuru = Field(
        description="ilan: kullanıcı bir proje ilanı/çağrı metni yapıştırmış (başlık, amaç, kapsam ...). "
                    "alan: belirli bir alanda/konuda/yöntemde çalışan akademisyen arıyor. "
                    "hoca: adı verilen (ya da geçmişte anılan) belirli bir akademisyenin bilgilerini istiyor. "
                    "sohbet: selamlama, sistemin ne yaptığı, kapsam dışı sorular."
    )
    arama_metni: str | None = Field(
        None, description="Yalnızca tur=alan: geçmişi de hesaba katarak tek başına anlaşılır, 1-2 cümlelik arama "
                          "isteği; alan adlarının Türkçe ve İngilizce karşılıklarıyla. Ör. 'Bilgisayarlı görü "
                          "(computer vision) ve görüntü işleme alanlarında çalışmış akademisyen'."
    )
    hoca_adi: str | None = Field(
        None, description="Yalnızca tur=hoca: akademisyenin adı, kullanıcının yazdığı gibi; unvan ve ekler "
                          "olmadan (\"Ayşe Demir'in\" -> 'Ayşe Demir', 'Mehmet hocanın' -> 'Mehmet'). Yalnızca "
                          "ad ya da soyad verildiyse eksik kısmı ASLA tamamlama. Zamirle ya da sırayla anılıyorsa "
                          "('onun', 'ilk sıradaki') adı geçmişteki yanıtlardan al."
    )
    soru: str | None = Field(
        None, description="Yalnızca tur=hoca: akademisyen hakkında ne istendiği, ör. 'deneyimleri', "
                          "'yayınları', 'yürüttüğü projeler'. Genel bir istekse 'genel özet'."
    )
    yanit: str | None = Field(
        None, description="Yalnızca tur=sohbet: kısa, samimi Türkçe yanıt. Kapsam dışıysa neler "
                          "yapabildiğini hatırlat (ilan eşleştirme, alana göre hoca bulma, hoca bilgisi)."
    )


_NIYET_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "Sen AcademIQ'nun sohbet asistanısın. AcademIQ bir üniversitenin akademisyen CV havuzunda arama yapar: "
     "proje ilanlarına en uygun hocaları bulur, bir alanda çalışan hocaları listeler ve bir hocanın CV "
     "bilgilerini (deneyim, eğitim, yayın, proje, ders ...) gösterir. Kullanıcının son mesajının niyetini "
     "belirle ve ilgili alanları doldur. Geçmiş, zamirleri ve 'peki ya ...' gibi devam sorularını "
     "çözmek içindir.\n\n## Geçmiş\n{gecmis}"),
    ("human", "{mesaj}"),
])

niyet_chain = _NIYET_PROMPT | get_llm().with_structured_output(Niyet)

_HOCA_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "Sen bir üniversitenin akademisyen bilgi asistanısın. Soruyu YALNIZCA verilen CV verisine dayanarak "
     "Türkçe yanıtla ve yalnızca sorulan konuya odaklan (ör. 'deneyim' için görevler ve projeler; eğitim ya "
     "da yayın istenmediyse listeleme). Bir giriş cümlesiyle başla, ardından '- ' ile başlayan maddeler yaz; önemli adları "
     "**kalın** yaz. Varsa dönem, kurum ve programı belirt. Veride olmayan bilgiyi KESİNLİKLE uydurma; "
     "istenen bilgi CV'de yoksa bunu açıkça söyle. Başlık (#) ya da tablo kullanma."),
    ("human", "## Akademisyen\n{hoca}\n\n## Soru\n{soru}\n\n## CV verisi (JSON)\n{cv}"),
])

hoca_chain = _HOCA_PROMPT | get_llm() | StrOutputParser()


def _gecmis(gecmis: list[SohbetMesaji]) -> str:
    satirlar = [f"{'Kullanıcı' if m.rol == 'kullanici' else 'Asistan'}: {m.metin[:GECMIS_KARAKTER]}"
                for m in gecmis[-GECMIS_MESAJ:]]
    return "\n".join(satirlar) or "(yok)"


async def yanitla(mesaj: str, gecmis: list[SohbetMesaji] | None = None) -> SohbetYaniti:
    niyet: Niyet = await niyet_chain.ainvoke({"mesaj": mesaj[:NIYET_KARAKTER], "gecmis": _gecmis(gecmis or [])})

    if niyet.tur == "ilan":
        return _eslesme_yaniti("ilan", await match_text(mesaj))
    if niyet.tur == "alan":
        return _eslesme_yaniti("alan", await match_text(niyet.arama_metni or mesaj))
    if niyet.tur == "hoca" and niyet.hoca_adi:
        return await _hoca_yaniti(niyet.hoca_adi, niyet.soru or "genel özet")
    return SohbetYaniti(tur="sohbet", metin=niyet.yanit or (
        "Size şu konularda yardımcı olabilirim: bir proje ilanını yapıştırırsanız en uygun hocaları bulurum, "
        "bir alan yazarsanız o alanda çalışan hocaları listelerim, bir hocanın adını verirseniz CV'sindeki "
        "bilgileri gösteririm."))


def _eslesme_yaniti(tur: SohbetTuru, sonuc: MatchResponse) -> SohbetYaniti:
    baslik = sonuc.ilan.baslik
    if not sonuc.sonuclar:
        return SohbetYaniti(tur=tur, eslesme=sonuc,
                            metin=f"**{baslik}** için yeterli benzerlikte bir hoca bulamadım.")
    one_cikan = ", ".join(f"**{s.hoca.ad_soyad}**" for s in sonuc.sonuclar[:ONE_CIKAN])
    n = len(sonuc.sonuclar)
    if tur == "ilan":
        giris = f"İlanı analiz ettim: **{baslik}**. En uygun {n} hocayı"
    else:
        alanlar = ", ".join(sonuc.ilan.aranan_uzmanliklar[:3]) or baslik
        alanlar = alanlar[:1].replace("i", "İ").upper() + alanlar[1:]
        giris = f"**{alanlar}** alanında çalışmış {n} hocayı"
    return SohbetYaniti(
        tur=tur, eslesme=sonuc,
        metin=f"{giris} gerekçe ve kanıtlarıyla Eşleştir sayfasında listeledim. İlk sıralarda {one_cikan} var.",
    )


async def _hoca_yaniti(ad: str, soru: str) -> SohbetYaniti:
    meta, adaylar = await asyncio.to_thread(hoca_bul, ad)
    if meta is None:
        if adaylar:
            return SohbetYaniti(tur="hoca", adaylar=[hoca_ozet(m) for m in adaylar],
                                metin=f"\"{ad}\" ile birden fazla ya da benzer isimli hoca var. Hangisini kastettiniz?")
        return SohbetYaniti(tur="hoca", metin=f"\"{ad}\" adında bir akademisyeni havuzda bulamadım. "
                                              "Adı ve soyadı kontrol edip tekrar dener misiniz?")

    hoca = hoca_ozet(meta)
    cv = {"profil": meta.get("profil"), **(meta.get("cv") or {})}
    metin = await hoca_chain.ainvoke({
        "hoca": " · ".join(filter(None, [f"{hoca.unvan or ''} {hoca.ad_soyad}".strip(), hoca.bolum, hoca.universite])),
        "soru": soru,
        "cv": json.dumps(cv, ensure_ascii=False)[:CV_KARAKTER],
    })
    return SohbetYaniti(tur="hoca", hoca=hoca, metin=metin.strip())


if __name__ == "__main__":
    print(asyncio.run(yanitla(" ".join(sys.argv[1:]))).model_dump_json(indent=2))
