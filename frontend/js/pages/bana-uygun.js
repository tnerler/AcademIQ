import { banaUygun, validateCv } from "../api.js";
import { CONFIG } from "../config.js";
import {
  esc, icon, chips, scoreBar, notice, toast, formatBytes, displayName, durumBadge, tarihCell,
} from "../ui.js";

export const title = "Bana Uygun İlanlar";

// Durum modül seviyesinde: sayfadan çıkıp dönünce sonuç kaybolmaz (CV dosyası bellekte kalır, saklanmaz).
const state = {
  file: null,
  kaydet: false,
  sadeceAcik: true,
  status: "idle", // idle | loading | done | error
  result: null,
  error: null,
  controller: null,
};

let root = null;

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
  return () => {
    root = null;
  };
}

function renderLeft() {
  const left = root?.querySelector("#left");
  if (!left) return;
  const loading = state.status === "loading";
  const r = state.status === "done" ? state.result : null;

  left.innerHTML = `
    <div>
      <h1 class="page-title">Bana Uygun İlanlar</h1>
      <p class="page-sub">CV'nizi yükleyin, profilinizle eşleşen proje çağrılarını görün.</p>
    </div>
    <input type="file" id="file-input" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" hidden>
    ${state.file ? `
      <div class="card file-card">
        ${icon("pdf", "file-ico")}
        <div style="flex:1;min-width:0">
          <div class="fname">${esc(state.file.name)}</div>
          <div class="tiny muted">${formatBytes(state.file.size)}</div>
        </div>
        ${loading ? "" : `<button class="link-btn" id="change-file">Değiştir</button>`}
      </div>` : `
      <div class="dropzone" tabindex="0" role="button" aria-label="CV dosyası seç">
        ${icon("upload")}
        <div class="dz-title">CV'nizi sürükleyin veya seçin</div>
        <div class="dz-sub">PDF ya da Word (.docx) · en fazla ${CONFIG.MAX_PDF_MB} MB</div>
      </div>`}

    ${r ? `
      <div class="card card-pad stack" style="gap:12px">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:10px">
          <b>${esc(displayName(r.ad_soyad) || state.file?.name || "CV")}</b>
          <span class="badge ok">${r.hoca_id ? "Kaydedildi" : "Analiz edildi"}</span>
        </div>
        <div class="section-label">CV'nizden algılanan alanlar</div>
        ${chips(r.profil.arastirma_alanlari, { max: 8 })}
        ${r.hoca_id ? `<a class="link-btn" href="#/cvler/${encodeURIComponent(r.hoca_id)}">Kaydedilen profili gör</a>` : ""}
      </div>` : ""}

    <div class="card card-pad stack" style="gap:12px">
      <label class="check"><input type="checkbox" id="sadece-acik" ${state.sadeceAcik ? "checked" : ""} ${loading ? "disabled" : ""}>
        Yalnızca başvurusu açık ilanlar</label>
      <label class="check"><input type="checkbox" id="kaydet" ${state.kaydet ? "checked" : ""} ${loading ? "disabled" : ""}>
        CV'mi sisteme kaydet</label>
      <p class="tiny muted">İşaretlerseniz CV'niz hoca havuzuna eklenir ve proje eşleştirmelerinde önerilebilirsiniz.
        İşaretlemezseniz yalnızca bu arama için kullanılır ve saklanmaz.</p>
    </div>

    <button class="btn btn-primary btn-lg btn-block" id="start" ${state.file && !loading ? "" : "disabled"}>
      ${loading ? `<span class="spinner"></span> CV analiz ediliyor…` : "Uygun ilanları bul"}
    </button>
    ${loading ? `<button class="link-btn" id="cancel" style="align-self:center">İptal et</button>` : ""}`;

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
      if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
    });
  }
  left.querySelector("#change-file")?.addEventListener("click", () => input.click());
  left.querySelector("#sadece-acik").addEventListener("change", (e) => (state.sadeceAcik = e.target.checked));
  left.querySelector("#kaydet").addEventListener("change", (e) => (state.kaydet = e.target.checked));
  left.querySelector("#start").addEventListener("click", start);
  left.querySelector("#cancel")?.addEventListener("click", () => state.controller?.abort());
}

function setFile(file) {
  const invalid = validateCv(file);
  if (invalid) {
    toast(invalid.message);
    return;
  }
  state.file = file;
  renderLeft();
}

async function start() {
  if (!state.file || state.status === "loading") return;
  const controller = new AbortController();
  Object.assign(state, { status: "loading", error: null, controller });
  renderLeft();
  renderRight();
  try {
    const result = await banaUygun(state.file, { kaydet: state.kaydet, sadeceAcik: state.sadeceAcik },
      { signal: controller.signal });
    Object.assign(state, { status: "done", result });
    if (result.hoca_id) toast("CV'niz sisteme kaydedildi.");
  } catch (err) {
    if (err.name === "AbortError") {
      state.status = state.result ? "done" : "idle";
    } else {
      Object.assign(state, { status: "error", error: err });
    }
  } finally {
    state.controller = null;
    renderLeft();
    renderRight();
  }
}

function renderRight() {
  const right = root?.querySelector("#right");
  if (!right) return;

  if (state.status === "loading") {
    right.innerHTML = `
      <div class="results-head"><div><h2>Size uygun ilanlar</h2>
        <p class="small muted">CV'niz okunuyor, profiliniz çıkarılıyor ve çağrılarla karşılaştırılıyor · genelde 15–30 saniye</p></div></div>
      <div class="results">${`<div class="card result"><div class="skel" style="height:16px;width:60%"></div>
        <div class="skel" style="height:12px;margin-top:12px"></div><div class="skel" style="height:12px;width:80%;margin-top:8px"></div></div>`.repeat(3)}</div>`;
    return;
  }

  if (state.status === "error") {
    right.innerHTML = `
      <div class="results-head"><div><h2>Size uygun ilanlar</h2></div></div>
      ${notice("err", `<b>Arama tamamlanamadı.</b> ${esc(state.error?.message ?? "")}`,
        `<button class="btn btn-outline" id="retry">${icon("refresh")} Tekrar dene</button>`)}`;
    right.querySelector("#retry").addEventListener("click", start);
    return;
  }

  if (state.status === "done" && state.result) {
    const list = state.result.sonuclar;
    right.innerHTML = `
      <div class="results-head"><div>
        <h2>Size uygun ${list.length} ilan</h2>
        <p class="small muted">${CONFIG.USE_MOCK ? "Örnek sonuç (mock veri) · " : ""}${state.sadeceAcik ? "Başvurusu açık" : "Tüm"} akademik çağrılar arasından</p>
      </div></div>
      ${list.length ? `<div class="results">${list.map(resultCard).join("")}</div>
        <div class="dashed-note" style="margin-top:14px">Skorlar çağrıları profilinize göre birbirine göre sıralamak içindir; mutlak bir uygunluk yüzdesi değildir.</div>`
      : `<div class="card empty">${icon("file")}<h3>Uygun çağrı bulunamadı</h3>
          <p class="small">Şu an ${state.sadeceAcik ? "başvurusu açık " : ""}akademik çağrı yok ya da profilinizle örtüşmüyor.</p></div>`}`;
    return;
  }

  right.innerHTML = `
    <div class="results-head"><div><h2>Size uygun ilanlar</h2></div></div>
    <div class="card empty">
      ${icon("user-check")}
      <h3>Henüz arama yapılmadı</h3>
      <p class="small" style="max-width:440px;margin:0 auto">Soldan CV'nizi yükleyip <b>Uygun ilanları bul</b>'a basın.
      Profilinizle örtüşen TÜBİTAK çağrıları, neden uygun olduklarıyla birlikte burada listelenir.</p>
    </div>`;
}

function resultCard(s) {
  const c = s.cagri;
  return `
    <article class="card result">
      <div style="display:grid;grid-template-columns:minmax(0,1fr) 180px;gap:16px">
        <div>
          <div style="font-weight:600;font-size:17px">${esc(c.baslik)}</div>
          <div class="small muted" style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-top:6px">
            ${durumBadge(c.durum)}${esc([c.program_kodu, c.program_adi].filter(Boolean).join(" · "))}
          </div>
        </div>
        <div><div class="tiny muted" style="text-align:right">Uyum skoru</div>${scoreBar(s.skor)}</div>
      </div>
      <div class="fit-grid">
        <div><h4 class="ok">Neden uygun?</h4><p class="small muted">${esc(s.neden)}</p></div>
        <div><h4 class="warn">Eksik kalan</h4><p class="small muted">${esc(s.eksik ?? "Belirgin bir eksik görünmüyor.")}</p></div>
      </div>
      <div class="result-foot" style="align-items:flex-start">
        <div>${tarihCell(c)}</div>
        <span class="spacer"></span>
        <a class="link-btn" href="${esc(c.url)}" target="_blank" rel="noopener">${icon("external")} Kaynağa git</a>
      </div>
    </article>`;
}
