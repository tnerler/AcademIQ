import { getCvs, getCv, cvPdfUrl } from "../api.js";
import {
  esc, icon, chips, displayName, fullName, shortUni, normalize, trCompare, notice, openPdfModal,
} from "../ui.js";

export const title = "CV'ler";

const UNVAN_SIRASI = ["Prof. Dr.", "Doç. Dr.", "Dr. Öğr. Üyesi", "Öğr. Gör. Dr.", "Arş. Gör. Dr."];

let root = null;
let all = [];
let selectedId = null;
let detailToken = 0;
const filters = { q: "", alan: "", unvan: "", uni: "" };

const isWide = () => window.matchMedia("(min-width: 961px)").matches;

// Sözleşmeye ana_alan eklenirse filtre ve kolon otomatik olarak onu kullanır.
const hasAnaAlan = () => all.some((h) => h.ana_alan);
const alanlarOf = (h) => (h.ana_alan ? [h.ana_alan] : h.arastirma_alanlari ?? []);

export function render(el, params) {
  root = el;
  selectedId = params[0] ?? null;
  el.innerHTML = `
    <div class="page">
      <div class="page-head">
        <div>
          <h1 class="page-title">CV'ler</h1>
          <p class="page-sub" id="cv-sub">Yükleniyor…</p>
        </div>
        <a class="btn btn-primary" href="#/cv-yukle">+ CV Yükle</a>
      </div>
      <div id="cv-body">${skeleton()}</div>
    </div>`;
  load();
  return () => {
    root = null;
  };
}

export function update(params) {
  select(params[0] ?? null, { scroll: true });
}

async function load() {
  const body = root.querySelector("#cv-body");
  try {
    all = await getCvs();
  } catch (err) {
    if (!root) return;
    root.querySelector("#cv-sub").textContent = "";
    body.innerHTML = notice("err", esc(err.message), `<button class="btn btn-outline" id="retry">Tekrar dene</button>`);
    body.querySelector("#retry").addEventListener("click", () => {
      body.innerHTML = skeleton();
      load();
    });
    return;
  }
  if (!root) return;

  const alanSet = new Set(all.flatMap(alanlarOf));
  root.querySelector("#cv-sub").textContent =
    `${all.length} hoca · ${alanSet.size} ${hasAnaAlan() ? "ana alan" : "araştırma alanı"}`;

  body.innerHTML = `
    <div class="filters">
      <label class="field"><span>Ara</span>
        <input class="input" id="f-q" type="search" placeholder="İsim, uzmanlık veya anahtar kelime" value="${esc(filters.q)}">
      </label>
      <label class="field"><span>Alan</span>
        <select class="select" id="f-alan">${options([...alanSet].sort(trCompare), filters.alan)}</select>
      </label>
      <label class="field"><span>Unvan</span>
        <select class="select" id="f-unvan">${options(sortUnvan([...new Set(all.map((h) => h.unvan).filter(Boolean))]), filters.unvan)}</select>
      </label>
      <label class="field"><span>Üniversite</span>
        <select class="select" id="f-uni">${options([...new Set(all.map((h) => h.universite).filter(Boolean))].sort(trCompare), filters.uni)}</select>
      </label>
    </div>
    <div class="split">
      <div class="card table-card">
        <div class="table-wrap">
          <table class="table">
            <thead><tr>
              <th>Hoca</th>
              <th>Üniversite</th>
              <th class="hide-sm">${hasAnaAlan() ? "Ana alan" : "Araştırma alanları"}</th>
            </tr></thead>
            <tbody id="cv-rows"></tbody>
          </table>
        </div>
      </div>
      <aside class="card detail" id="cv-detail" aria-live="polite"></aside>
    </div>`;

  const bind = (id, key, evt = "change") =>
    body.querySelector(id).addEventListener(evt, (e) => {
      filters[key] = e.target.value;
      renderRows();
    });
  bind("#f-q", "q", "input");
  bind("#f-alan", "alan");
  bind("#f-unvan", "unvan");
  bind("#f-uni", "uni");

  body.querySelector("#cv-rows").addEventListener("click", (e) => {
    const row = e.target.closest("tr[data-id]");
    if (row) location.hash = `#/cvler/${encodeURIComponent(row.dataset.id)}`;
  });
  body.querySelector("#cv-rows").addEventListener("keydown", (e) => {
    const row = e.target.closest("tr[data-id]");
    if (row && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      location.hash = `#/cvler/${encodeURIComponent(row.dataset.id)}`;
    }
  });

  renderRows();
  if (selectedId) {
    select(selectedId, { scroll: !isWide() });
    if (isWide()) root.querySelector("#cv-rows tr.selected")?.scrollIntoView({ block: "center" });
  }
  else if (isWide() && all.length) select(all[0].id);
  else renderEmptyDetail();
}

function options(values, selected) {
  return `<option value="">Tümü</option>${values
    .map((v) => `<option value="${esc(v)}" ${v === selected ? "selected" : ""}>${esc(v)}</option>`)
    .join("")}`;
}

function sortUnvan(list) {
  const rank = (u) => (UNVAN_SIRASI.indexOf(u) + 1 || 99);
  return list.sort((a, b) => rank(a) - rank(b) || trCompare(a, b));
}

function filtered() {
  const q = normalize(filters.q.trim());
  return all.filter((h) => {
    if (filters.alan && !alanlarOf(h).includes(filters.alan)) return false;
    if (filters.unvan && h.unvan !== filters.unvan) return false;
    if (filters.uni && h.universite !== filters.uni) return false;
    if (q) {
      const hay = normalize([h.ad_soyad, h.universite, h.fakulte, h.bolum, ...(h.arastirma_alanlari ?? [])].join(" "));
      return q.split(/\s+/).every((w) => hay.includes(w));
    }
    return true;
  });
}

function renderRows() {
  const tbody = root?.querySelector("#cv-rows");
  if (!tbody) return;
  const list = filtered();
  if (!list.length) {
    tbody.innerHTML = `<tr><td colspan="3"><div class="empty">
      ${icon("search")}<h3>Filtrelere uyan hoca bulunamadı</h3>
      <button class="link-btn" id="clear-filters">Filtreleri temizle</button></div></td></tr>`;
    tbody.querySelector("#clear-filters").addEventListener("click", clearFilters);
    return;
  }
  tbody.innerHTML = list
    .map((h) => `
      <tr class="clickable ${h.id === selectedId ? "selected" : ""}" data-id="${esc(h.id)}" tabindex="0" aria-selected="${h.id === selectedId}">
        <td><div class="cell-title">${esc(displayName(h.ad_soyad))}</div><div class="cell-sub">${esc(h.unvan ?? "")}</div></td>
        <td>${esc(shortUni(h.universite))}</td>
        <td class="hide-sm">${h.ana_alan ? esc(h.ana_alan) : chips(h.arastirma_alanlari, { max: 2, size: "sm" })}</td>
      </tr>`)
    .join("");
}

function clearFilters() {
  Object.assign(filters, { q: "", alan: "", unvan: "", uni: "" });
  ["#f-q", "#f-alan", "#f-unvan", "#f-uni"].forEach((s) => (root.querySelector(s).value = ""));
  renderRows();
}

function renderEmptyDetail() {
  const panel = root?.querySelector("#cv-detail");
  if (!panel) return;
  panel.innerHTML = `<div class="empty">${icon("users")}<h3>Bir hoca seçin</h3><p class="small">Detayları görmek için listeden bir satıra tıklayın.</p></div>`;
}

async function select(id, { scroll = false } = {}) {
  if (!root || !all.length) {
    selectedId = id;
    return;
  }
  selectedId = id;
  root.querySelectorAll("#cv-rows tr[data-id]").forEach((tr) => {
    const on = tr.dataset.id === id;
    tr.classList.toggle("selected", on);
    tr.setAttribute("aria-selected", String(on));
  });
  if (!id) return renderEmptyDetail();

  const panel = root.querySelector("#cv-detail");
  const token = ++detailToken;
  panel.innerHTML = detailSkeleton();
  if (scroll && !isWide()) panel.scrollIntoView({ behavior: "smooth", block: "start" });

  let h;
  try {
    h = await getCv(id);
  } catch (err) {
    if (token !== detailToken || !root) return;
    panel.innerHTML = notice("err", esc(err.message));
    return;
  }
  if (token !== detailToken || !root) return;

  const p = h.profil;
  panel.innerHTML = `
    <div>
      <div class="muted small">${esc(h.unvan ?? "")}</div>
      <h2 class="detail-name">${esc(displayName(h.ad_soyad))}</h2>
      <div class="muted small" style="margin-top:4px">${esc([h.universite, h.bolum].filter(Boolean).join(" · "))}</div>
      ${h.fakulte ? `<div class="tiny muted">${esc(h.fakulte)}</div>` : ""}
      ${h.email ? `<a class="small" style="color:var(--primary)" href="mailto:${esc(h.email)}">${esc(h.email)}</a>` : ""}
    </div>
    ${h.ana_alan ? `
      <div class="detail-block">
        <div class="section-label">Ana alan</div>
        <div><span class="badge primary">${esc(h.ana_alan)}</span></div>
      </div>` : ""}
    <div class="detail-block">
      <div class="section-label">Uzmanlık alanları</div>
      ${chips(h.arastirma_alanlari)}
    </div>
    ${p?.ozet_metni ? `
      <div class="detail-block">
        <div class="section-label">Profil özeti</div>
        <p class="ozet">${esc(p.ozet_metni)}</p>
      </div>` : ""}
    ${p?.yontemler?.length ? `
      <div class="detail-block">
        <div class="section-label">Yöntemler</div>
        ${chips(p.yontemler, { size: "sm" })}
      </div>` : ""}
    ${p?.anahtar_kelimeler?.length ? `
      <div class="detail-block">
        <div class="section-label">Anahtar kelimeler</div>
        ${chips(p.anahtar_kelimeler, { size: "sm" })}
      </div>` : ""}
    <div class="detail-actions">
      <button class="btn btn-outline" id="open-pdf">${icon("pdf")} PDF'i aç</button>
      <button class="btn btn-primary" disabled title="Yakında: bu hocaya uygun ilanlar">Uygun ilanlar</button>
    </div>`;

  panel.querySelector("#open-pdf").addEventListener("click", () =>
    openPdfModal(`${fullName(h)} · CV`, cvPdfUrl(h.id)),
  );
}

function skeleton() {
  const row = `<tr><td><div class="skel" style="height:14px;width:60%"></div><div class="skel" style="height:11px;width:35%;margin-top:6px"></div></td>
    <td><div class="skel" style="height:12px;width:70%"></div></td><td class="hide-sm"><div class="skel" style="height:20px;width:80%"></div></td></tr>`;
  return `<div class="split"><div class="card table-card"><table class="table"><thead><tr><th>Hoca</th><th>Üniversite</th><th class="hide-sm">Ana alan</th></tr></thead>
    <tbody>${row.repeat(7)}</tbody></table></div><aside class="card detail">${detailSkeleton()}</aside></div>`;
}

function detailSkeleton() {
  return `<div class="skel" style="height:12px;width:30%"></div>
    <div class="skel" style="height:26px;width:70%"></div>
    <div class="skel" style="height:12px;width:85%"></div>
    <div class="skel" style="height:64px"></div>
    <div class="skel" style="height:90px"></div>`;
}
