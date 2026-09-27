// Sayfalar arasında paylaşılan küçük yardımcılar: kaçış, ikonlar, biçimlendirme, modal, toast.

export function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// ---------------------------------------------------------------------------
// İkonlar (lucide tarzı, 24x24 çizgi)
// ---------------------------------------------------------------------------
const ICON_PATHS = {
  home: '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/><path d="M10 21v-6h4v6"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.6-3.4 3.3-5.5 6.5-5.5s5.9 2.1 6.5 5.5"/><path d="M15.5 4.8a3.5 3.5 0 0 1 0 6.4"/><path d="M18 14.8c1.9.8 3.2 2.6 3.5 5.2"/>',
  upload: '<path d="M12 16V4"/><path d="m7 9 5-5 5 5"/><path d="M4 20h16"/>',
  file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 17h6"/>',
  "file-plus": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M12 11v6M9 14h6"/>',
  swap: '<path d="M4 8h15"/><path d="m15 4 4 4-4 4"/><path d="M20 16H5"/><path d="m9 12-4 4 4 4"/>',
  "user-check": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.6-3.4 3.3-5.5 6.5-5.5 1.5 0 2.9.5 4 1.3"/><path d="m15 18 2 2 4-4"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  "chevron-down": '<path d="m6 9 6 6 6-6"/>',
  download: '<path d="M12 4v12"/><path d="m7 11 5 5 5-5"/><path d="M4 20h16"/>',
  external: '<path d="M14 4h6v6"/><path d="M20 4 10 14"/><path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/>',
  check: '<path d="m5 12 5 5 9-10"/>',
  alert: '<path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17.5v.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.5v.01"/>',
  pdf: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
  arrow: '<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
};

export function icon(name, cls = "") {
  return `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON_PATHS[name] ?? ""}</svg>`;
}

// ---------------------------------------------------------------------------
// Biçimlendirme
// ---------------------------------------------------------------------------

/** "Zeynep YILDIZ" -> "Zeynep Yıldız" (Türkçe büyük/küçük harf kurallarıyla). */
export function displayName(adSoyad) {
  return String(adSoyad ?? "")
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toLocaleUpperCase("tr") + w.slice(1).toLocaleLowerCase("tr"))
    .join(" ");
}

export function fullName(hoca) {
  return [hoca.unvan, displayName(hoca.ad_soyad)].filter(Boolean).join(" ");
}

export function shortUni(universite) {
  return String(universite ?? "").replace(/\s*Üniversitesi$/u, " Ü.");
}

export function shortBolum(bolum) {
  return String(bolum ?? "").replace(/Mühendisliği/gu, "Müh.");
}

/** Arama için: küçük harf + Türkçe karakterleri sadeleştirme ("Işık" ve "isik" eşleşir). */
export function normalize(text) {
  return String(text ?? "")
    .toLocaleLowerCase("tr")
    .replace(/[çğıöşüâîû]/g, (c) => ({ ç: "c", ğ: "g", ı: "i", ö: "o", ş: "s", ü: "u", â: "a", î: "i", û: "u" })[c]);
}

export const trCompare = (a, b) => String(a).localeCompare(String(b), "tr");

export function formatBytes(bytes) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toLocaleString("tr-TR", { maximumFractionDigits: 1 })} MB`;
}

/** "2026-10-25" -> { text: "25.10.2026", days: 28 } */
export function deadline(isoDate) {
  const [y, m, d] = isoDate.split("-").map(Number);
  const target = new Date(y, m - 1, d);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const days = Math.round((target - today) / 86_400_000);
  const text = `${String(d).padStart(2, "0")}.${String(m).padStart(2, "0")}.${y}`;
  return { text, days };
}

// ---------------------------------------------------------------------------
// Küçük bileşenler (HTML string döner)
// ---------------------------------------------------------------------------
export function chips(list, { max = Infinity, size = "" } = {}) {
  const items = (list ?? []).filter(Boolean);
  const shown = items.slice(0, max);
  const rest = items.length - shown.length;
  return `<div class="chips">${shown.map((t) => `<span class="chip ${size}">${esc(t)}</span>`).join("")}${
    rest > 0 ? `<span class="chip more ${size}" title="${esc(items.slice(max).join(", "))}">+${rest}</span>` : ""
  }</div>`;
}

export function scoreBar(value) {
  const v = Math.max(0, Math.min(100, Number(value) || 0));
  return `<div class="score" title="Skor: ${v.toLocaleString("tr-TR", { maximumFractionDigits: 1 })} / 100">
    <div class="score-bar"><i style="width:${v}%"></i></div>
    <span class="score-val">${Math.round(v)}</span>
  </div>`;
}

export function soonBadge() {
  return `<span class="badge soon">Yakında</span>`;
}

export function notice(type, html, actions = "") {
  const ico = type === "err" || type === "warn" ? "alert" : "info";
  return `<div class="notice ${type}" role="${type === "err" ? "alert" : "status"}">${icon(ico)}<div>${html}</div>${
    actions ? `<div class="notice-actions">${actions}</div>` : ""
  }</div>`;
}

export function passiveNotice(text) {
  return notice(
    "info",
    `<b>Önizleme.</b> ${esc(text)} Bu ekran tasarımı göstermek içindir, demo aşamasında işlevsizdir.`,
  );
}

// ---------------------------------------------------------------------------
// Modal (PDF önizleme)
// ---------------------------------------------------------------------------
let closeActiveModal = null;

/** Açık modal varsa kapatır (sayfa değişiminde yönlendirici çağırır). */
export function closeModal() {
  closeActiveModal?.();
}

export function openPdfModal(title, url) {
  closeModal();
  const root = document.getElementById("modal-root");
  const previousFocus = document.activeElement;
  root.innerHTML = `
    <div class="modal-backdrop">
      <div class="modal" role="dialog" aria-modal="true" aria-label="${esc(title)}">
        <div class="modal-head">
          ${icon("pdf")}
          <h3>${esc(title)}</h3>
          <a class="btn btn-outline" style="padding:7px 14px;font-size:14px" href="${esc(url)}" target="_blank" rel="noopener">${icon("external")} Yeni sekmede aç</a>
          <button class="icon-btn" data-close aria-label="Kapat">${icon("x")}</button>
        </div>
        <div class="modal-body"><iframe src="${esc(url)}" title="CV önizleme"></iframe></div>
      </div>
    </div>`;
  const close = () => {
    closeActiveModal = null;
    root.innerHTML = "";
    document.removeEventListener("keydown", onKey);
    previousFocus?.focus?.();
  };
  const onKey = (e) => e.key === "Escape" && close();
  document.addEventListener("keydown", onKey);
  closeActiveModal = close;
  root.querySelector(".modal-backdrop").addEventListener("click", (e) => {
    if (e.target === e.currentTarget || e.target.closest("button[data-close]")) close();
  });
  root.querySelector("button[data-close]").focus();
}

// ---------------------------------------------------------------------------
// Toast ve dosya indirme
// ---------------------------------------------------------------------------
export function toast(message, ms = 3200) {
  const root = document.getElementById("toast-root");
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = message;
  root.append(el);
  setTimeout(() => el.remove(), ms);
}

export function downloadFile(filename, content, mime) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function slugify(text) {
  return normalize(text).replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 60) || "sonuc";
}
