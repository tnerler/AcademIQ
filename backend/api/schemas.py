"""API yanit modelleri: UI ile backend arasindaki kontrat (Swagger: /docs).

IlanOzet ayni zamanda LLM'in ilan PDF'inden doldurdugu structured output semasidir;
alan aciklamalari (description) LLM'e talimat olarak gider.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class HocaOzet(BaseModel):
    id: str
    unvan: str | None = None
    ad_soyad: str
    universite: str | None = None
    fakulte: str | None = None
    bolum: str | None = None
    arastirma_alanlari: list[str] = []


class ProfilOzeti(BaseModel):
    arastirma_alanlari: list[str] = []
    yontemler: list[str] = []
    anahtar_kelimeler: list[str] = []
    ozet_metni: str = ""


class HocaDetay(HocaOzet):
    email: str | None = None
    profil: ProfilOzeti | None = None
    pdf_url: str


class IlanMeta(BaseModel):
    """Aramaya girmeyen, yalnizca arayuzde gosterilen ilan bilgileri."""
    son_basvuru: str | None = Field(None, description="Son başvuru tarihi (ilanda yazdığı gibi), yoksa null")
    butce: str | None = Field(None, description="Destek üst limiti / bütçe, yoksa null")
    sure: str | None = Field(None, description="Proje süresi, yoksa null")
    yer: str | None = Field(None, description="Projenin yürütüleceği yer, yoksa null")
    basvuru_kosullari: list[str] = Field([], description="Unvan, deneyim, ekip büyüklüğü gibi başvuru koşulları")


class IlanOzet(BaseModel):
    baslik: str = Field(description="Proje/çağrı başlığı")
    kurum: str | None = Field(None, description="İlanı yayımlayan kurum")
    konu: str = Field(description="Projenin konusu, 1 cümle")
    amac_kapsam: str = Field(description="Amaç ve kapsamın 2-4 cümlelik özeti")
    aranan_uzmanliklar: list[str] = Field(description="İlanda aranan uzmanlık alanları")
    anahtar_kelimeler: list[str] = Field(
        description="Akademik CV'lerde aranacak 8-15 anahtar kelime/terim; Türkçe ve İngilizce karşılıklarıyla "
                    "(ör. 'derin öğrenme', 'deep learning', 'LSTM'). Tarih, bütçe, kurum adı gibi terimler olmasın."
    )
    sorgu_metni: str = Field(
        description="İlanın akademik gereksinimlerini özetleyen 3-5 cümlelik arama metni: hangi alanlarda, hangi "
                    "yöntemlerde uzman ve hangi konularda yayın/proje deneyimi olan bir akademisyen aranıyor. "
                    "Tarih, bütçe, süre, unvan şartı, deneyim yılı gibi başvuru koşullarını KESİNLİKLE içermesin."
    )
    meta: IlanMeta = Field(default_factory=IlanMeta)


class Kanit(BaseModel):
    bolum: str = Field(description="Bölüm anahtarı: arastirma, egitim, yayinlar, projeler, yonetilen_tezler, dersler")
    bolum_etiketi: str
    maddeler: list[str] = Field(description="CV'den alınan, eşleşmeyi destekleyen başlıklar")
    skor: float = Field(description="Chunk'ın RRF skoru (0-100, en iyi chunk'a göre)")


class EslesmeSonucu(BaseModel):
    sira: int
    hoca: HocaOzet
    skor: float = Field(description="0-100, en uygun adaya göre normalize")
    gerekce: str
    kanitlar: list[Kanit]


class MatchResponse(BaseModel):
    ilan: IlanOzet
    sonuclar: list[EslesmeSonucu]
