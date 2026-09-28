// Backend ile tüm iletişim bu dosyadan geçer. Sayfalar fetch'i doğrudan çağırmaz.
// Şekiller API sözleşmesiyle birebir aynıdır (HocaOzet, HocaDetay, MatchResponse ...).
// CONFIG.USE_MOCK açıkken aynı şekillerde veri frontend/mock/*.json'dan gelir.

import { CONFIG } from "./config.js";

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const FALLBACK_MESSAGES = {
  0: `Sunucuya ulaşılamadı. Backend çalışıyor mu? (${CONFIG.API_URL})`,
  404: "Kayıt bulunamadı.",
  408: "İstek zaman aşımına uğradı. Lütfen tekrar deneyin.",
  413: `PDF ${CONFIG.MAX_PDF_MB} MB'tan büyük olamaz.`,
  415: "Yüklenen dosya PDF değil.",
  422: "Dosya gönderilemedi. Lütfen bir PDF seçin.",
  500: "Sunucu ya da yapay zekâ hatası oluştu. Lütfen tekrar deneyin.",
  501: "Bu özellik henüz aktif değil.",
};

function messageFor(status, detail) {
  // Sözleşme: detail doğrudan kullanıcıya gösterilebilir. 422'de FastAPI dizi dönebilir.
  if (typeof detail === "string" && detail.trim()) return detail;
  return FALLBACK_MESSAGES[status] ?? `Beklenmeyen bir hata oluştu (HTTP ${status}).`;
}

async function request(path, options = {}) {
  let res;
  try {
    res = await fetch(CONFIG.API_URL + path, options);
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new ApiError(0, messageFor(0));
  }
  if (!res.ok) {
    let detail;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* gövde JSON değil */
    }
    throw new ApiError(res.status, messageFor(res.status, detail));
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Mock yardımcıları
// ---------------------------------------------------------------------------
const mockCache = new Map();

function loadMock(name) {
  if (!mockCache.has(name)) {
    const url = new URL(`../mock/${name}.json`, import.meta.url);
    const promise = fetch(url).then((r) => {
      if (!r.ok) throw new ApiError(r.status, `Mock veri yüklenemedi: ${name}.json`);
      return r.json();
    });
    promise.catch(() => mockCache.delete(name));
    mockCache.set(name, promise);
  }
  return mockCache.get(name);
}

function sleep(ms, signal) {
  return new Promise((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(t);
      reject(new DOMException("İptal edildi", "AbortError"));
    }, { once: true });
  });
}

const OZET_KEYS = ["id", "unvan", "ad_soyad", "universite", "fakulte", "bolum", "ana_alan", "arastirma_alanlari"];
const toOzet = (h) => Object.fromEntries(OZET_KEYS.map((k) => [k, h[k]]));

function hashString(s) {
  let h = 0;
  for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return h;
}

// Mock modda yüklenen PDF'in hangi ilana ait olduğunu dosya adından tahmin eder
// (data/ altındaki ilan PDF'leri "I007_..." gibi başlar).
async function pickMockIlan(fileName) {
  const matches = await loadMock("matches");
  const ids = Object.keys(matches);
  const byId = fileName.match(/I\d{3}/i)?.[0].toUpperCase();
  if (byId && matches[byId]) return matches[byId];

  const ilanlar = await loadMock("ilanlar");
  const stem = fileName.toLocaleLowerCase("tr").replace(/\.pdf$/, "");
  const byName = ilanlar.find((i) => i.dosya.toLocaleLowerCase("tr").includes(stem) || stem.includes(i.dosya.slice(5, 15)));
  if (byName) return matches[byName.id];

  return matches[ids[hashString(fileName) % ids.length]];
}

// Mock modda yapıştırılan metni, başlık ve uzmanlık alanlarıyla en çok kelime paylaşan ilana eşler.
async function pickMockIlanByText(metin) {
  const [matches, ilanlar] = await Promise.all([loadMock("matches"), loadMock("ilanlar")]);
  const words = (t) => new Set((normalizeText(t).match(/[a-z0-9]{4,}/g) ?? []).map((w) => w.slice(0, 5)));
  const query = words(metin);
  let best = null;
  let bestScore = 0;
  for (const ilan of ilanlar) {
    const own = words([ilan.baslik, ilan.alan, ...ilan.gerekli_uzmanlik].join(" "));
    const score = [...own].filter((w) => query.has(w)).length;
    if (score > bestScore) [best, bestScore] = [ilan, score];
  }
  if (best) return matches[best.id];
  const ids = Object.keys(matches);
  return matches[ids[hashString(metin) % ids.length]];
}

function normalizeText(text) {
  return text
    .toLocaleLowerCase("tr")
    .replace(/[çğıöşüâîû]/g, (c) => ({ ç: "c", ğ: "g", ı: "i", ö: "o", ş: "s", ü: "u", â: "a", î: "i", û: "u" })[c]);
}

// ---------------------------------------------------------------------------
// Doğrulama (sözleşmedeki 413/415 kontrollerini istek atmadan yapar)
// ---------------------------------------------------------------------------
export function validatePdf(file) {
  if (!file) return new ApiError(422, FALLBACK_MESSAGES[422]);
  const isPdf = file.type === "application/pdf" || /\.pdf$/i.test(file.name);
  if (!isPdf) return new ApiError(415, FALLBACK_MESSAGES[415]);
  if (file.size > CONFIG.MAX_PDF_MB * 1024 * 1024) return new ApiError(413, FALLBACK_MESSAGES[413]);
  return null;
}

/** CV: PDF ya da Word (.docx). */
export function validateCv(file) {
  if (!file) return new ApiError(422, "Lütfen bir CV dosyası seçin.");
  if (!/\.(pdf|docx)$/i.test(file.name)) return new ApiError(415, "CV yalnızca PDF ya da Word (.docx) olabilir.");
  if (file.size > CONFIG.MAX_PDF_MB * 1024 * 1024) return new ApiError(413, `Dosya ${CONFIG.MAX_PDF_MB} MB'tan büyük olamaz.`);
  return null;
}

export function validateMetin(metin) {
  const len = (metin ?? "").trim().length;
  if (len === 0) return new ApiError(422, "İlan metni boş olamaz.");
  if (len > CONFIG.MAX_METIN_LENGTH) {
    return new ApiError(422, `İlan metni çok uzun. En fazla ${CONFIG.MAX_METIN_LENGTH} karakter girin.`);
  }
  return null;
}

// ---------------------------------------------------------------------------
// Endpoint'ler
// ---------------------------------------------------------------------------

/** GET /api/cvs -> HocaOzet[] */
export async function getCvs() {
  if (CONFIG.USE_MOCK) {
    const cvs = await loadMock("cvs");
    await sleep(250);
    return cvs.map(toOzet);
  }
  return request("/api/cvs");
}

/** GET /api/cvs/{id} -> HocaDetay */
export async function getCv(id) {
  if (CONFIG.USE_MOCK) {
    const cvs = await loadMock("cvs");
    await sleep(200);
    const hoca = cvs.find((h) => h.id === id);
    if (!hoca) throw new ApiError(404, "Akademisyen bulunamadı.");
    return hoca;
  }
  return request(`/api/cvs/${encodeURIComponent(id)}`);
}

/** GET /api/cvs/{id}/pdf için iframe'de kullanılacak adres */
export function cvPdfUrl(id) {
  if (CONFIG.USE_MOCK) return `/mock-pdf/${encodeURIComponent(id)}.pdf`;
  return `${CONFIG.API_URL}/api/cvs/${encodeURIComponent(id)}/pdf`;
}

/**
 * POST /api/match (multipart/form-data) -> MatchResponse
 * İlan PDF ("file"), düz metin ("metin") ya da toplanan bir çağrı ("cagri") olarak gönderilir.
 * Çağrıda kayıtlı sonuç varsa hemen döner (olusturuldu dolu); yenile=true yeniden hesaplatır.
 * signal ile iptal edilebilir; CONFIG.MATCH_TIMEOUT_MS sonunda 408 fırlatır.
 */
export async function match({ file = null, metin = null, cagri = null, yenile = false }, { signal } = {}) {
  const invalid = cagri ? null : file ? validatePdf(file) : validateMetin(metin);
  if (invalid) throw invalid;

  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, CONFIG.MATCH_TIMEOUT_MS);
  signal?.addEventListener("abort", () => controller.abort(), { once: true });

  try {
    if (CONFIG.USE_MOCK) {
      await sleep(CONFIG.MOCK_MATCH_DELAY_MS, controller.signal);
      // Hata ekranını denemek için: adında "hata" geçen bir PDF yükleyin ya da metne "hata" yazın.
      if (/hata/i.test(file ? file.name : metin ?? "")) throw new ApiError(500, FALLBACK_MESSAGES[500]);
      if (cagri) return structuredClone(await pickMockIlanByText(cagri.baslik));
      return structuredClone(await (file ? pickMockIlan(file.name) : pickMockIlanByText(metin)));
    }
    const form = new FormData();
    if (file) form.append("file", file);
    else if (cagri) {
      form.append("cagri_id", cagri.id);
      if (yenile) form.append("yenile", "true");
    } else form.append("metin", metin.trim());
    return await request("/api/match", { method: "POST", body: form, signal: controller.signal });
  } catch (err) {
    if (err.name === "AbortError" && timedOut) throw new ApiError(408, FALLBACK_MESSAGES[408]);
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

/** Pasif İlan Ekle ekranındaki örnek ilan listesi. */
export function getSampleIlanlar() {
  return loadMock("ilanlar");
}

// ---------------------------------------------------------------------------
// Proje çağrıları (otomatik toplanan). Mock modda örnek ilanlar çağrı şekline çevrilir.
// ---------------------------------------------------------------------------
function todayIso() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

async function mockCagrilar() {
  const ilanlar = await loadMock("ilanlar");
  const today = todayIso();
  return ilanlar.map((i) => ({
    id: i.id,
    kaynak: i.kaynak,
    url: "#",
    baslik: i.baslik,
    program_kodu: i.kurum.match(/\d{4}/)?.[0] ?? null,
    program_adi: i.program,
    hedef_kitle: "akademik",
    ozet: `Aranan uzmanlıklar: ${i.gerekli_uzmanlik.join(", ")}.`,
    tarihler: [{ etiket: "Son başvuru", tarih: i.son_basvuru }],
    son_tarih: i.son_basvuru,
    durum: i.son_basvuru >= today ? "acik" : "gecmis",
    yayin_tarihi: null,
    uygun_hocalar: [],
    butce: null, sure: null, basvuru_kosullari: [], baglantilar: [], guncelleme_urller: [],
  }));
}

/** GET /api/cagrilar -> { toplam, cagrilar: CagriOzet[] } */
export async function getCagrilar({ durum = "", hedef_kitle = "", program = "", q = "", limit = 50, offset = 0 } = {}) {
  if (CONFIG.USE_MOCK) {
    await sleep(250);
    const ara = normalizeText(q);
    const list = (await mockCagrilar()).filter((c) =>
      (!durum || c.durum === durum) && (!hedef_kitle || c.hedef_kitle === hedef_kitle)
      && (!program || c.program_kodu === program) && (!ara || normalizeText(c.baslik + " " + c.ozet).includes(ara)));
    return { toplam: list.length, cagrilar: list.slice(offset, offset + limit) };
  }
  const params = new URLSearchParams(
    Object.entries({ durum, hedef_kitle, program, q, limit, offset }).filter(([, v]) => v !== "" && v != null),
  );
  return request(`/api/cagrilar?${params}`);
}

/** GET /api/cagrilar/{id} -> CagriDetay */
export async function getCagri(id) {
  if (CONFIG.USE_MOCK) {
    const cagri = (await mockCagrilar()).find((c) => c.id === id);
    if (!cagri) throw new ApiError(404, "Çağrı bulunamadı.");
    return cagri;
  }
  return request(`/api/cagrilar/${encodeURIComponent(id)}`);
}

/** GET /api/cagrilar/programlar -> ProgramOzet[] */
export async function getProgramlar() {
  if (CONFIG.USE_MOCK) {
    const counts = new Map();
    for (const c of await mockCagrilar()) if (c.program_kodu) counts.set(c.program_kodu, (counts.get(c.program_kodu) ?? 0) + 1);
    return [...counts].map(([kod, sayi]) => ({ kod, ad: null, sayi }));
  }
  return request("/api/cagrilar/programlar");
}

/** GET /api/cagrilar/tarama -> TaramaDurumu */
export async function getTarama() {
  if (CONFIG.USE_MOCK) return { son: null, son_basarili: null };
  return request("/api/cagrilar/tarama");
}

/** POST /api/cagrilar/tara (X-Admin-Token) -> CekmeCalismasi */
export async function tara(token) {
  if (CONFIG.USE_MOCK) throw new ApiError(501, "Mock modda kaynak taraması yapılamaz.");
  return request("/api/cagrilar/tara", { method: "POST", headers: { "X-Admin-Token": token } });
}

// ---------------------------------------------------------------------------
// CV yükleme ve Bana Uygun
// ---------------------------------------------------------------------------

/** POST /api/cvs (multipart) -> HocaDetay */
export async function uploadCv(file, { signal } = {}) {
  const invalid = validateCv(file);
  if (invalid) throw invalid;
  if (CONFIG.USE_MOCK) {
    await sleep(2000, signal);
    return structuredClone((await loadMock("cvs"))[hashString(file.name) % 10]);
  }
  const form = new FormData();
  form.append("file", file);
  return request("/api/cvs", { method: "POST", body: form, signal });
}

/** POST /api/bana-uygun (multipart) -> BanaUygunResponse */
export async function banaUygun(file, { kaydet = false, sadeceAcik = true } = {}, { signal } = {}) {
  const invalid = validateCv(file);
  if (invalid) throw invalid;
  if (CONFIG.USE_MOCK) {
    await sleep(CONFIG.MOCK_MATCH_DELAY_MS, signal);
    const cv = (await loadMock("cvs"))[hashString(file.name) % 10];
    const cagrilar = (await mockCagrilar()).filter((c) => !sadeceAcik || c.durum !== "gecmis").slice(0, 3);
    return {
      ad_soyad: cv.ad_soyad,
      profil: cv.profil ?? { arastirma_alanlari: cv.arastirma_alanlari ?? [], yontemler: [], anahtar_kelimeler: [], ozet_metni: "" },
      hoca_id: kaydet ? cv.id : null,
      sonuclar: cagrilar.map((c, i) => ({
        sira: i + 1, cagri: c, skor: 100 - i * 14,
        neden: "Örnek sonuç: araştırma alanlarınız çağrının konusu ile örtüşüyor.",
        eksik: i ? "Örnek sonuç: çağrının yöntem tarafında doğrudan yayınınız görünmüyor." : null,
      })),
    };
  }
  const form = new FormData();
  form.append("file", file);
  form.append("kaydet", String(kaydet));
  form.append("sadece_acik", String(sadeceAcik));
  return request("/api/bana-uygun", { method: "POST", body: form, signal });
}
