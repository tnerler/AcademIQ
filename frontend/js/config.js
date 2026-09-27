// Uygulama ayarları. Build adımı olmadığı için ortam değişkeni yerine burası kullanılır.
//
// Mock / gerçek API seçimi:
//   - Varsayılan: USE_MOCK_DEFAULT
//   - Adres çubuğunda ?mock=0 (gerçek API) ya da ?mock=1 (mock) verilirse
//     seçim tarayıcıda saklanır; sidebar'daki rozetten de değiştirilebilir.

const USE_MOCK_DEFAULT = true;
const STORAGE_KEY = "academiq.useMock";

function readUseMock() {
  const param = new URLSearchParams(location.search).get("mock");
  try {
    if (param === "0" || param === "1") localStorage.setItem(STORAGE_KEY, param);
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "0" || stored === "1") return stored === "1";
  } catch {
    if (param === "0" || param === "1") return param === "1";
  }
  return USE_MOCK_DEFAULT;
}

export const CONFIG = {
  API_URL: "http://localhost:8000",
  USE_MOCK: readUseMock(),
  // Sözleşme: eşleştirme 10–15 sn sürer, istemci timeout'u en az 60 sn olmalı.
  MATCH_TIMEOUT_MS: 90_000,
  MATCH_EXPECTED_MS: 13_000,
  MOCK_MATCH_DELAY_MS: 4_500,
  MAX_PDF_MB: 20,
  MIN_METIN_LENGTH: 100,
  MAX_METIN_LENGTH: 3000,
};

export function setUseMock(value) {
  try {
    localStorage.setItem(STORAGE_KEY, value ? "1" : "0");
  } catch {
    /* depolama kapalıysa sadece bu oturum için geçerli olur */
  }
  const url = new URL(location.href);
  url.searchParams.delete("mock");
  location.replace(url);
}
