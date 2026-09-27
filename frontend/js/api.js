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

export function validateMetin(metin) {
  const len = (metin ?? "").trim().length;
  if (len < CONFIG.MIN_METIN_LENGTH) {
    return new ApiError(422, `İlan metni çok kısa. En az ${CONFIG.MIN_METIN_LENGTH} karakter girin.`);
  }
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
 * İlan ya PDF olarak ("file") ya da düz metin olarak ("metin") gönderilir.
 * signal ile iptal edilebilir; CONFIG.MATCH_TIMEOUT_MS sonunda 408 fırlatır.
 */
export async function match({ file = null, metin = null }, { signal } = {}) {
  const invalid = file ? validatePdf(file) : validateMetin(metin);
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
      if (/hata/i.test(file ? file.name : metin)) throw new ApiError(500, FALLBACK_MESSAGES[500]);
      return structuredClone(await (file ? pickMockIlan(file.name) : pickMockIlanByText(metin)));
    }
    const form = new FormData();
    if (file) form.append("file", file);
    else form.append("metin", metin.trim());
    return await request("/api/match", { method: "POST", body: form, signal: controller.signal });
  } catch (err) {
    if (err.name === "AbortError" && timedOut) throw new ApiError(408, FALLBACK_MESSAGES[408]);
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

/** Pasif ekranlardaki örnek ilan listesi (backend'de GET /api/ilanlar şu an 501). */
export function getSampleIlanlar() {
  return loadMock("ilanlar");
}
