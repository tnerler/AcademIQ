import { match, validatePdf, validateMetin, getCvs, cvPdfUrl } from "../api.js";
import { CONFIG } from "../config.js";
import {
  esc, icon, chips, displayName, fullName, shortUni, shortBolum, scoreBar, notice, soonBadge,
  formatBytes, openPdfModal, downloadFile, slugify, normalize, toast,
} from "../ui.js";

export const title = "Eşleştir";

const RESULT_KEY = "academiq.lastMatch";

const LOADING_STEPS = [
  "İlan okunuyor",
  "Eşleştirmeye girecek bölümler ayrıştırılıyor",
  "Sorgu metni ve anahtar kelimeler üretiliyor",
  "Hibrit arama (BM25 + semantik) yapılıyor",
  "Gerekçeler ve kanıtlar hazırlanıyor",
];

const BOLUM_SAYI = {
  arastirma: "araştırma alanı",
  egitim: "eğitim/tez",
  yayinlar: "yayın",
  projeler: "proje",
  yonetilen_tezler: "tez",
  dersler: "ders",
};

// Durum modül seviyesinde tutulur: sayfadan çıkıp dönünce (ya da istek sürerken) kaybolmaz.
const state = {
  tab: "pdf", // pdf | metin
  file: null,
  metin: "",
  topN: 5,
  status: "idle", // idle | loading | done | error
  result: restoreResult(),
  error: null,
  startedAt: 0,
  controller: null,
  totalCvs: null,
};
if (state.result) state.status = "done";

let root = null;
let ticker = null;

function restoreResult() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(RESULT_KEY) ?? "null");
    return saved?.sonuclar ? saved : null;
  } catch {
    return null;
  }
}

function saveResult(result) {
  try {
    sessionStorage.setItem(RESULT_KEY, JSON.stringify(result));
  } catch {
    /* depolama kapalı; sadece bellekte kalır */
  }
}

export function render(el) {
  root = el;
  el.innerHTML = `
    <div class="page">
      <div class="match-layout">
        <section class="match-left" id="left"></section>
        <section class="match-right" id="right" aria-live="polite"></section>
      </div>
    </div>`;
  renderLeft();
  renderRight();
  if (state.totalCvs == null) {
    getCvs().then((cvs) => {
      state.totalCvs = cvs.length;
      if (root && state.status === "done") renderRight();
    }).catch(() => {});
  }
  return () => {
    root = null;
    clearInterval(ticker);
    ticker = null;
  };
}

const canStart = () =>
  state.status !== "loading" && (state.tab === "pdf" ? !!state.file : !validateMetin(state.metin));

// ---------------------------------------------------------------------------
// Sol kolon: ilan girişi, ilan detayları, ayarlar
// ---------------------------------------------------------------------------
function renderLeft() {
  const left = root?.querySelector("#left");
  if (!left) return;
  const loading = state.status === "loading";
  const ilan = state.status === "done" ? state.result?.ilan : null;

  left.innerHTML = `
    <h1 class="page-title">Eşleştir</h1>

    <div class="segmented" role="tablist" aria-label="İlan kaynağı">
      <button role="tab" disabled title="Yakında: kayıtlı ilanlardan seçim">Listeden seç</button>
      ${["pdf", "metin"].map((t) => `
        <button role="tab" data-tab="${t}" class="${state.tab === t ? "active" : ""}" aria-selected="${state.tab === t}" ${loading ? "disabled" : ""}>
          ${t === "pdf" ? "PDF yükle" : "Metin yapıştır"}
        </button>`).join("")}
    </div>

    <input type="file" id="file-input" accept=".pdf,application/pdf" hidden>
    ${state.tab === "pdf" ? (state.file ? fileCard(loading) : dropzone()) : metinBox(loading)}

    ${ilan ? ilanCard(ilan) : ""}

    <div class="card card-pad settings">
      <div class="section-label">Ayarlar</div>
      <label class="setting-row">
        <span>Gösterilecek hoca sayısı</span>
        <select class="select" id="top-n">
          ${[1, 2, 3, 4, 5].map((n) => `<option ${n === state.topN ? "selected" : ""}>${n}</option>`).join("")}
        </select>
      </label>
      <label class="setting-row" title="Yakında: backend unvan filtresini desteklediğinde aktif olacak">
        <span class="muted">Minimum unvan ${soonBadge()}</span>
        <select class="select" disabled><option>Fark etmez</option></select>
      </label>
      <label class="check disabled" title="Yakında: gerekçeler şu an her zaman üretiliyor">
        <input type="checkbox" checked disabled>
        <span>Gerekçeleri yapay zekâ ile açıkla ${soonBadge()}</span>
      </label>
    </div>

    <button class="btn btn-primary btn-lg btn-block" id="start" ${canStart() ? "" : "disabled"}>
      ${loading ? `<span class="spinner"></span> Eşleştiriliyor… <span id="elapsed">${elapsed()}</span> sn` : "Eşleştirmeyi başlat"}
    </button>
    ${loading ? `<button class="link-btn" id="cancel" style="align-self:center">İptal et</button>` : ""}
    ${!loading && !canStart() ? `<p class="tiny muted" style="text-align:center">${
      state.tab === "pdf" ? "Başlamak için bir ilan PDF'i seçin." : "Başlamak için ilan metnini yapıştırın."}</p>` : ""}
  `;

  left.querySelectorAll("[data-tab]").forEach((b) =>
    b.addEventListener("click", () => {
      if (state.tab === b.dataset.tab) return;
      state.tab = b.dataset.tab;
      renderLeft();
      if (state.tab === "metin") left.querySelector("#metin")?.focus();
    }),
  );

  // Yazarken sol kolonu yeniden çizmiyoruz (odak kaybolmasın); sadece sayaç ve buton güncellenir.
  const metinEl = left.querySelector("#metin");
  metinEl?.addEventListener("input", () => {
    state.metin = metinEl.value;
    updateMetinStatus();
  });

  const input = left.querySelector("#file-input");
  input.addEventListener("change", () => {
    if (input.files[0]) setFile(input.files[0]);
    input.value = "";
  });

  const dz = left.querySelector(".dropzone");
  if (dz) {
    dz.addEventListener("click", () => input.click());
    dz.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        input.click();
      }
    });
    dz.addEventListener("dragover", (e) => {
      e.preventDefault();
      dz.classList.add("drag");
    });
    dz.addEventListener("dragleave", () => dz.classList.remove("drag"));
    dz.addEventListener("drop", (e) => {
      e.preventDefault();
      dz.classList.remove("drag");
      const file = e.dataTransfer.files[0];
      if (file) setFile(file);
    });
  }

  left.querySelector("#change-file")?.addEventListener("click", () => input.click());
  left.querySelector("#remove-file")?.addEventListener("click", () => {
    state.file = null;
    renderLeft();
  });
  left.querySelector("#top-n").addEventListener("change", (e) => {
    state.topN = Number(e.target.value);
    if (state.status === "done") renderRight();
  });
  left.querySelector("#start").addEventListener("click", start);
  left.querySelector("#cancel")?.addEventListener("click", () => state.controller?.abort());
}

function metinBox(loading) {
  return `
    <div class="field">
      <textarea class="textarea" id="metin" rows="10" ${loading ? "disabled" : ""}
        placeholder="İlan metnini buraya yapıştırın: başlık, amaç ve kapsam, aranan uzmanlık alanları…">${esc(state.metin)}</textarea>
      <div class="tiny ${metinStatus().over ? "over" : "muted"}" id="metin-status">${metinStatus().text}</div>
    </div>`;
}

// Uzun metni sessizce kırpmamak için textarea'ya maxlength verilmiyor; sayaç uyarıyor.
function metinStatus() {
  const len = state.metin.trim().length;
  const { MAX_METIN_LENGTH: max } = CONFIG;
  const count = `${len.toLocaleString("tr-TR")} / ${max.toLocaleString("tr-TR")} karakter`;
  if (len > max) return { text: `${count} · ${(len - max).toLocaleString("tr-TR")} karakter fazla`, over: true };
  return { text: count, over: false };
}

function updateMetinStatus() {
  const left = root?.querySelector("#left");
  if (!left) return;
  const status = metinStatus();
  const el = left.querySelector("#metin-status");
  el.textContent = status.text;
  el.classList.toggle("over", status.over);
  el.classList.toggle("muted", !status.over);
  left.querySelector("#start").disabled = !canStart();
  const hint = left.querySelector("#start + p");
  if (hint) hint.hidden = canStart();
}

function dropzone() {
  return `
    <div class="dropzone" tabindex="0" role="button" aria-label="İlan PDF'i seç">
      ${icon("upload")}
      <div class="dz-title">İlan PDF'ini buraya sürükleyin</div>
      <div class="dz-sub">veya bilgisayarınızdan seçin · en fazla ${CONFIG.MAX_PDF_MB} MB</div>
    </div>`;
}

function fileCard(loading) {
  const f = state.file;
  return `
    <div class="card file-card">
      ${icon("pdf", "file-ico")}
      <div style="flex:1;min-width:0">
        <div class="fname">${esc(f.name)}</div>
        <div class="tiny muted">${formatBytes(f.size)} · PDF</div>
      </div>
      ${loading ? "" : `
        <button class="link-btn" id="change-file">Değiştir</button>
        <button class="icon-btn" id="remove-file" aria-label="Dosyayı kaldır">${icon("x")}</button>`}
    </div>`;
}

function ilanCard(ilan) {
  const m = ilan.meta ?? {};
  const metaRows = [
    ["Son başvuru", m.son_basvuru],
    ["Bütçe", m.butce],
    ["Süre", m.sure],
    ["Yer", m.yer],
  ].filter(([, v]) => v);
  const kosullar = m.basvuru_kosullari ?? [];

  return `
    <div class="card card-pad ilan-card">
      <div class="section-label">Eşleştirilen ilan</div>
      <h3>${esc(ilan.baslik)}</h3>
      ${ilan.kurum ? `<div class="small muted">${esc(ilan.kurum)}</div>` : ""}
      ${ilan.aranan_uzmanliklar?.length ? chips(ilan.aranan_uzmanliklar, { size: "sm" }) : ""}
      ${metaRows.length ? `<dl class="meta-list">${metaRows.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("")}</dl>` : ""}
      ${ilan.amac_kapsam ? `
        <details class="more"><summary>Amaç ve kapsam</summary>
          <p class="small muted" style="line-height:1.6">${esc(ilan.amac_kapsam)}</p>
        </details>` : ""}
      ${kosullar.length ? `
        <details class="more"><summary>Başvuru koşulları (${kosullar.length})</summary>
          <ul class="kosullar">${kosullar.map((k) => `<li>${esc(k)}</li>`).join("")}</ul>
        </details>` : ""}
      ${ilan.sorgu_metni ? `
        <details class="more"><summary>Sistemin arama sorgusu</summary>
          <p class="small muted" style="line-height:1.6">${esc(ilan.sorgu_metni)}</p>
          ${ilan.anahtar_kelimeler?.length ? chips(ilan.anahtar_kelimeler, { size: "sm" }) : ""}
        </details>` : ""}
      <p class="tiny muted">Tarih, bütçe ve başvuru koşulları eşleştirme skoruna dahil edilmez.</p>
    </div>`;
}

function setFile(file) {
  const invalid = validatePdf(file);
  if (invalid) {
    toast(invalid.message);
    return;
  }
  state.file = file;
  renderLeft();
}

// ---------------------------------------------------------------------------
// Eşleştirme akışı
// ---------------------------------------------------------------------------
async function start() {
  if (!canStart()) return;
  const input = state.tab === "pdf" ? { file: state.file } : { metin: state.metin };
  const controller = new AbortController();
  Object.assign(state, { status: "loading", error: null, startedAt: Date.now(), controller });
  renderLeft();
  renderRight();
  startTicker();

  try {
    const result = await match(input, { signal: controller.signal });
    Object.assign(state, { status: "done", result });
    saveResult(result);
  } catch (err) {
    if (err.name === "AbortError") {
      state.status = state.result ? "done" : "idle";
      toast("Eşleştirme iptal edildi.");
    } else {
      Object.assign(state, { status: "error", error: err });
    }
  } finally {
    state.controller = null;
    clearInterval(ticker);
    ticker = null;
    renderLeft();
    renderRight();
  }
}

function elapsed() {
  return Math.floor((Date.now() - state.startedAt) / 1000);
}

function startTicker() {
  clearInterval(ticker);
  ticker = setInterval(() => {
    if (!root) return;
    const el = root.querySelector("#elapsed");
    if (el) el.textContent = elapsed();
    updateSteps();
  }, 500);
}

// ---------------------------------------------------------------------------
// Sağ kolon: boş durum, yükleniyor, hata, sonuçlar
// ---------------------------------------------------------------------------
function renderRight() {
  const right = root?.querySelector("#right");
  if (!right) return;

  if (state.status === "loading" && !ticker) startTicker();

  if (state.status === "loading") {
    right.innerHTML = `
      <div class="results-head"><div>
        <h2>En uygun hocalar</h2>
        <p class="small muted">İlan analiz ediliyor · bu işlem genelde 10–15 saniye sürer</p>
      </div></div>
      <div class="card loading-steps" id="steps">${LOADING_STEPS.map((s) => `<div class="step"><span class="dot"></span>${esc(s)}</div>`).join("")}</div>
      <div class="results" style="margin-top:14px">${resultSkeleton().repeat(3)}</div>`;
    updateSteps();
    return;
  }

  if (state.status === "error") {
    right.innerHTML = `
      <div class="results-head"><div><h2>En uygun hocalar</h2></div></div>
      ${notice("err", `<b>Eşleştirme tamamlanamadı.</b> ${esc(state.error?.message ?? "")}`,
        canStart() ? `<button class="btn btn-outline" id="retry">${icon("refresh")} Tekrar dene</button>` : "")}
      ${state.result ? `<p class="small muted">Önceki sonuç aşağıda gösteriliyor.</p>${resultsList()}` : ""}`;
    right.querySelector("#retry")?.addEventListener("click", start);
    bindResults(right);
    return;
  }

  if (state.status === "done" && state.result) {
    const shown = state.result.sonuclar.slice(0, state.topN).length;
    right.innerHTML = `
      <div class="results-head">
        <div>
          <h2>En uygun hocalar</h2>
          <p class="small muted">${[
            CONFIG.USE_MOCK ? "Örnek sonuç (mock veri)" : null,
            state.totalCvs ? `${state.totalCvs} CV tarandı` : null,
            `en uygun ${shown} hoca`,
          ].filter(Boolean).join(" · ")}</p>
        </div>
        <button class="btn btn-outline" id="download" ${shown ? "" : "disabled"}>${icon("download")} Sonuçları indir</button>
      </div>
      ${resultsList()}`;
    right.querySelector("#download").addEventListener("click", downloadCsv);
    bindResults(right);
    return;
  }

  right.innerHTML = `
    <div class="results-head"><div><h2>En uygun hocalar</h2></div></div>
    <div class="card empty">
      ${icon("swap")}
      <h3>Henüz eşleştirme yapılmadı</h3>
      <p class="small" style="max-width:440px;margin:0 auto">Soldan bir proje ilanı PDF'i yükleyip <b>Eşleştirmeyi başlat</b>'a basın.
      En uygun hocalar skor, gerekçe ve CV'den kanıtlarıyla burada listelenir.</p>
      ${CONFIG.USE_MOCK ? `<p class="tiny muted" style="margin-top:12px">Mock mod: <code>data/duz_metin</code> ya da <code>data/tablo_formatli</code> klasöründen bir ilan PDF'i seçin.</p>` : ""}
    </div>`;
}

function updateSteps() {
  const steps = root?.querySelectorAll("#steps .step");
  if (!steps?.length) return;
  const expected = CONFIG.USE_MOCK ? CONFIG.MOCK_MATCH_DELAY_MS : CONFIG.MATCH_EXPECTED_MS;
  const progress = (Date.now() - state.startedAt) / expected;
  // Son adım, yanıt gelene kadar "sürüyor" durumunda kalır.
  const currentIdx = Math.min(steps.length - 1, Math.floor(progress * steps.length));
  steps.forEach((s, i) => {
    s.classList.toggle("done", i < currentIdx);
    s.classList.toggle("current", i === currentIdx);
    const dot = s.querySelector(".dot");
    const want = i < currentIdx ? "done" : i === currentIdx ? "current" : "todo";
    if (dot.dataset.state !== want) {
      dot.dataset.state = want;
      dot.innerHTML = want === "done" ? icon("check") : want === "current" ? `<span class="spinner dark"></span>` : "";
    }
  });
}

function resultsList() {
  const { ilan, sonuclar } = state.result;
  const list = [...sonuclar].sort((a, b) => a.sira - b.sira).slice(0, state.topN);
  if (!list.length) {
    return `<div class="card empty">${icon("users")}<h3>Uygun hoca bulunamadı</h3>
      <p class="small">Bu ilan için yeterli benzerlikte bir CV bulunamadı.</p></div>`;
  }
  const terms = highlightTerms(ilan);
  return `
    <div class="results">${list.map((s) => resultCard(s, terms)).join("")}</div>
    <div class="dashed-note" style="margin-top:14px">
      Skorlar 1–100 arasıdır ve adayları bu ilan için birbirine göre sıralamak içindir; mutlak bir uygunluk yüzdesi değildir.
    </div>`;
}

function resultCard(s, terms) {
  const h = s.hoca;
  const kanitlar = s.kanitlar ?? [];
  return `
    <article class="card result" data-id="${esc(h.id)}">
      <div class="result-top">
        <div class="rank" aria-label="${s.sira}. sıra">${s.sira}</div>
        <div style="min-width:0">
          <a class="result-name" href="#/cvler/${encodeURIComponent(h.id)}">${esc(fullName(h))}</a>
          <div class="result-org">${esc([shortUni(h.universite), shortBolum(h.bolum)].filter(Boolean).join(" · "))}</div>
        </div>
        ${scoreBar(s.skor)}
      </div>
      <div class="result-body">
        <p class="gerekce">${esc(s.gerekce)}</p>
        <div class="result-foot">
          <span class="evid-sum">${esc(evidenceSummary(kanitlar))}</span>
          <span class="spacer"></span>
          ${kanitlar.length ? `<button class="toggle-evid" aria-expanded="false">Kanıtları göster ${icon("chevron-down")}</button>` : ""}
          <button class="link-btn" data-pdf>CV'yi aç</button>
        </div>
      </div>
      <div class="evidence">
        ${kanitlar.map((k) => `
          <div class="evid-group">
            <div class="evid-head">
              <b>${esc(k.bolum_etiketi || k.bolum)}</b>
              <span class="evid-score" title="Kanıtın ilanla ilgililik skoru">
                <span class="mini-bar"><i style="width:${Math.max(0, Math.min(100, k.skor))}%"></i></span>${Math.round(k.skor)}
              </span>
            </div>
            <ul>${(k.maddeler ?? []).map((m) => `<li>${highlight(m, terms)}</li>`).join("")}</ul>
          </div>`).join("")}
      </div>
    </article>`;
}

function bindResults(container) {
  container.querySelectorAll(".result").forEach((card) => {
    const toggle = card.querySelector(".toggle-evid");
    toggle?.addEventListener("click", () => {
      const open = card.classList.toggle("open");
      toggle.setAttribute("aria-expanded", String(open));
      toggle.firstChild.textContent = open ? "Kanıtları gizle " : "Kanıtları göster ";
    });
    card.querySelector("[data-pdf]").addEventListener("click", () => {
      const s = state.result.sonuclar.find((x) => x.hoca.id === card.dataset.id);
      openPdfModal(`${fullName(s.hoca)} · CV`, cvPdfUrl(s.hoca.id));
    });
  });
}

function evidenceSummary(kanitlar) {
  const parts = kanitlar
    .filter((k) => k.bolum !== "arastirma" && k.maddeler?.length)
    .map((k) => `${k.maddeler.length} ${BOLUM_SAYI[k.bolum] ?? (k.bolum_etiketi || k.bolum).toLocaleLowerCase("tr")}`);
  return parts.length ? `Eşleşen kanıt: ${parts.join(" · ")}` : "CV'de doğrudan eşleşen kanıt bulunamadı";
}

// İlandaki aranan uzmanlık ve anahtar kelimelerle örtüşen kelimeleri kanıt maddelerinde vurgular.
function highlightTerms(ilan) {
  const words = [...(ilan.aranan_uzmanliklar ?? []), ...(ilan.anahtar_kelimeler ?? [])]
    .join(" ")
    .split(/\s+/)
    .map((w) => normalize(w).replace(/[^a-z0-9]/g, ""))
    .filter((w) => w.length > 3);
  return new Set(words.map((w) => w.slice(0, 5)));
}

function highlight(text, terms) {
  return String(text)
    .split(/(\s+)/)
    .map((part) => {
      const key = normalize(part).replace(/[^a-z0-9]/g, "");
      return key.length > 3 && terms.has(key.slice(0, 5)) ? `<mark>${esc(part)}</mark>` : esc(part);
    })
    .join("");
}

function resultSkeleton() {
  return `<div class="card result">
    <div class="result-top">
      <div class="skel" style="width:40px;height:40px;border-radius:50%"></div>
      <div><div class="skel" style="height:16px;width:55%"></div><div class="skel" style="height:11px;width:35%;margin-top:7px"></div></div>
      <div class="skel" style="height:10px;margin-top:8px"></div>
    </div>
    <div class="result-body"><div class="skel" style="height:12px"></div><div class="skel" style="height:12px;width:80%;margin-top:8px"></div></div>
  </div>`;
}

// ---------------------------------------------------------------------------
// Sonuçları CSV olarak indir (Excel için ; ayraçlı ve BOM'lu)
// ---------------------------------------------------------------------------
function downloadCsv() {
  const { ilan, sonuclar } = state.result;
  const cell = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const rows = [
    ["Sıra", "Unvan", "Ad Soyad", "Üniversite", "Bölüm", "Skor (1–100)", "Gerekçe", "Kanıtlar"],
    ...sonuclar.slice(0, state.topN).map((s) => [
      s.sira,
      s.hoca.unvan,
      displayName(s.hoca.ad_soyad),
      s.hoca.universite,
      s.hoca.bolum,
      Math.round(s.skor),
      s.gerekce,
      (s.kanitlar ?? []).map((k) => `${k.bolum_etiketi}: ${(k.maddeler ?? []).join("; ")}`).join(" | "),
    ]),
  ];
  const header = [`İlan;${cell(ilan.baslik)}`, `Kurum;${cell(ilan.kurum)}`, ""];
  const csv = "﻿" + [...header, ...rows.map((r) => r.map(cell).join(";"))].join("\r\n");
  downloadFile(`eslestirme_${slugify(ilan.baslik)}.csv`, csv, "text/csv;charset=utf-8");
}
