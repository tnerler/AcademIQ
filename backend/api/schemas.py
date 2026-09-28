"""API yanit modelleri: UI ile backend arasindaki kontrat (Swagger: /docs).

IlanOzet ayni zamanda LLM'in ilan PDF'inden doldurdugu structured output semasidir;
alan aciklamalari (description) LLM'e talimat olarak gider.
"""

from __future__ import annotations

from datetime import date, datetime
import re
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field


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
    cv: CVCikarim | None = Field(None, description="CV'den çıkarılan tüm bilgiler (iletişim, eğitim, yayınlar ...)")
    pdf_url: str | None = Field(None, description="CV önizlemesi (PDF); yoksa null")


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
    olusturuldu: datetime | None = Field(None, description="Kayıtlı çağrı eşleştirmesiyse hesaplandığı zaman")


# --- Proje cagrilari (otomatik toplanan, docs/cagri-toplama-plan.md) ---------

class CagriTarihi(BaseModel):
    etiket: str = Field(description="Tarihin ne oldugu, ör. '1. Aşama uluslararası başvuru'")
    tarih: date


class Baglanti(BaseModel):
    etiket: str
    url: str


class CagriOzet(BaseModel):
    id: str
    kaynak: str
    url: str
    baslik: str
    program_kodu: str | None = None
    program_adi: str | None = None
    hedef_kitle: Literal["akademik", "sanayi"]
    ozet: str | None = None
    tarihler: list[CagriTarihi] = []
    son_tarih: date | None = Field(None, description="En geç tarih; durum buna göre hesaplanır")
    durum: Literal["acik", "gecmis", "belirsiz"]
    yayin_tarihi: date | None = None
    uygun_hocalar: list[str] = Field([], description="Kayıtlı eşleştirmedeki akademisyenler (sırayla); yoksa boş")


class CagriDetay(CagriOzet):
    butce: str | None = None
    sure: str | None = None
    basvuru_kosullari: list[str] = []
    baglantilar: list[Baglanti] = []
    guncelleme_urller: list[str] = Field([], description="Çağrıyı güncelleyen sonraki duyurular")


class CagriListe(BaseModel):
    toplam: int = Field(description="Filtreye uyan toplam çağrı sayısı (sayfalamadan bağımsız)")
    cagrilar: list[CagriDetay]


class ProgramOzet(BaseModel):
    kod: str
    ad: str | None = None
    sayi: int


class CekmeCalismasi(BaseModel):
    id: int
    tur: Literal["zamanli", "elle", "backfill"]
    durum: Literal["bekliyor", "calisiyor", "bitti", "hata"]
    istendi: datetime
    basladi: datetime | None = None
    bitti: datetime | None = None
    sayilar: dict[str, int] | None = None
    hata: str | None = None


class TaramaDurumu(BaseModel):
    son: CekmeCalismasi | None = Field(None, description="En son istenen çalışma")
    son_basarili: datetime | None = Field(None, description="En son başarıyla biten çalışmanın bitiş zamanı")


class BanaUygunCagri(BaseModel):
    sira: int
    cagri: CagriOzet
    skor: float = Field(description="0-100, en uygun çağrıya göre normalize")
    neden: str = Field(description="Çağrının bu profile neden uygun olduğu")
    eksik: str | None = Field(None, description="Profilin çağrı için zayıf kaldığı nokta, yoksa null")


class BanaUygunResponse(BaseModel):
    ad_soyad: str | None = None
    profil: ProfilOzeti
    hoca_id: str | None = Field(None, description="'CV'mi kaydet' seçildiyse kaydedilen akademisyen")
    sonuclar: list[BanaUygunCagri]


# --- CV cikarimi (LLM structured output; alan aciklamalari LLM'e talimat olarak gider) ----
# Arama alanlari cv_extract.arama_bolumleri ile chunk'lanir; gerisi profil metadata'sinda (HocaDetay.cv)

class Kimlik(BaseModel):
    unvan: str | None = Field(None, description="Kısaltılmış akademik unvan: 'Prof. Dr.', 'Doç. Dr.', "
                                                "'Dr. Öğr. Üyesi', 'Öğr. Gör. Dr.', 'Arş. Gör. Dr.' ...")
    ad_soyad: str = Field(description="Ad Soyad, unvansız")
    universite: str | None = None
    fakulte: str | None = None
    bolum: str | None = None


class Iletisim(BaseModel):
    email: str | None = None
    telefon: str | None = None
    web: str | None = Field(None, description="Kişisel/AVESİS sayfası")
    orcid: str | None = Field(None, description="0000-0000-0000-0000 biçiminde")
    yoksis: str | None = None


class Egitim(BaseModel):
    derece: str = Field(description="Lisans, Yüksek Lisans, Doktora ...")
    universite: str
    birim: str | None = Field(None, description="Enstitü / fakülte / anabilim dalı")
    yil: int | None = None
    tez_basligi: str | None = Field(None, description="Kendi tezinin başlığı (varsa), danışman adı hariç")


class Gorev(BaseModel):
    gorev: str = Field(description="Unvan ya da görev adı")
    kurum: str | None = None
    donem: str | None = Field(None, description="ör. '2014 – 2019', '2020 – Halen'")


class Yayin(BaseModel):
    baslik: str = Field(description="Yalnızca eserin başlığı (yazarlar, dergi, cilt, sayfa HARİÇ)")
    yil: int | None = None
    tur: Literal["makale", "bildiri", "kitap", "kitap_bolumu", "diger"] = "makale"
    yayin_yeri: str | None = Field(None, description="Dergi / konferans / yayınevi adı")


class Proje(BaseModel):
    ad: str = Field(description="Projenin adı")
    program: str | None = Field(None, description="Destekleyen program, ör. 'TÜBİTAK 1001', 'Horizon Europe', 'BAP'")
    gorev: str | None = Field(None, description="Yürütücü, araştırmacı, danışman ...")
    donem: str | None = None


def _seviye(v: object) -> object:
    """Serbest yazimlari ('Yüksek Lisans', 'PhD') sabit degerlere cevirir (function calling modu icin)."""
    if isinstance(v, str) and v not in ("yuksek_lisans", "doktora"):
        return "doktora" if re.search(r"(?i)dokt|ph\.?d|sanatta yeterlik", v) else "yuksek_lisans"
    return v


class Tez(BaseModel):
    baslik: str
    seviye: Annotated[Literal["yuksek_lisans", "doktora"], BeforeValidator(_seviye)]
    ogrenci: str | None = None
    yil: int | str | None = Field(None, description="Yıl ya da 'Devam ediyor'")


class Bibliyometri(BaseModel):
    toplam_yayin: int | None = None
    atif: int | None = None
    h_indeksi: int | None = None
    i10_indeksi: int | None = None


class YayinListesi(BaseModel):
    yayinlar: list[Yayin] = Field(description="Metin parçasındaki TÜM makale, bildiri, kitap ve kitap bölümleri")


class CVBilgileri(BaseModel):
    """LLM'e tek seferde sorulan alanlar (yayinlar haric)."""
    kimlik: Kimlik
    iletisim: Iletisim = Field(default_factory=Iletisim)
    ozet: str | None = Field(None, description="'Özet', 'Hakkında', 'Profil' paragrafı aynen")
    arastirma_alanlari: list[str] = Field([], description="Çalışma / araştırma / uzmanlık alanları, her biri ayrı")
    egitim: list[Egitim] = []
    akademik_gorevler: list[Gorev] = Field([], description="Akademik deneyim / unvanlar (Araş. Gör., Doçent ...)")
    yonetim_gorevleri: list[Gorev] = Field([], description="İdari görevler (bölüm başkanı, kurul üyeliği ...)")
    projeler: list[Proje] = []
    yonetilen_tezler: list[Tez] = Field([], description="Danışmanlığını yaptığı öğrenci tezleri")
    dersler: list[str] = Field([], description="Verdiği dersler, yalnızca ders adı")
    oduller: list[str] = Field([], description="Ödüller, burslar, teşvikler")
    uyelikler: list[str] = Field([], description="Bilimsel/mesleki kuruluş üyelikleri")
    hakemlik_editorluk: list[str] = Field([], description="Hakemlik, editörlük, yayın kurulu görevleri")
    yabanci_diller: list[str] = Field([], description="ör. 'İngilizce — YÖKDİL: 83'")
    bibliyometri: Bibliyometri = Field(default_factory=Bibliyometri)


class CVCikarim(CVBilgileri):
    yayinlar: list[Yayin] = []  # CV parca parca ayri cikarilir (bkz. cikar)


HocaDetay.model_rebuild()  # cv alani dosyanin sonunda tanimlanan CVCikarim'a bagli
