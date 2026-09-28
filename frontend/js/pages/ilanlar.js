import { getCagrilar, getProgramlar, getTarama, tara, ApiError } from "../api.js";
import { CONFIG } from "../config.js";
import {
  esc, icon, notice, toast, durumBadge, tarihCell, tarihList, formatDateTime, displayName, HEDEF_KITLE,
} from "../ui.js";

export const title = "Proje İlanları";

const PAGE_SIZE = 50;
const TOKEN_KEY = "academiq.adminToken";
const POLL_MS = 5000;

// Filtreler modül seviyesinde: sayfadan çıkıp dönünce korunur.
const filters = { q: "", durum: "acik", hedef_kitle: "", program: "" };

let root = null;
let cagrilar = [];
let toplam = 0;
let open = new Set();
let requestId = 0;
let pollTimer = null;
let searchTimer = null;

export function render(el) {
  root = el;
  cagrilar = [];
  taramaAktif = false;
  el.innerHTML = `
    <div class="page">
      <div class="page-head">
        <div>
          <h1 class="page-title">Proje İlanları</h1>
          <p class="page-sub" id="ilan-sub">&nbsp;</p>
        </div>
        <div style="display:flex;gap:10px;align-items:center">
          <span class="tiny muted" id="tarama-durum"></span>
          <button class="btn btn-outline" id="tara">${icon("refresh")} Kaynakları tara</button>
        </div>
      </div>
      <div id="tara-panel"></div>
      <div class="filters">
        <label class="field"><span>Ara</span>
          <input class="input" id="f-q" placeholder="Başlık, program veya konu" value="${esc(filters.q)}"></label>
        <label class="field"><span>Durum</span>
          <select class="select" id="f-durum">
            ${[["", "Tümü"], ["acik", "Başvurusu açık"], ["belirsiz", "Tarih belirsiz"], ["gecmis", "Süresi doldu"]]
              .map(([v, l]) => `<option value="${v}" ${filters.durum === v ? "selected" : ""}>${l}</option>`).join("")}
          </select></label>
        <label class="field"><span>Hedef kitle</span>
          <select class="select" id="f-hedef">
            ${[["", "Tümü"], ["akademik", "Akademik"], ["sanayi", "Sanayi"]]
              .map(([v, l]) => `<option value="${v}" ${filters.hedef_kitle === v ? "selected" : ""}>${l}</option>`).join("")}
          </select></label>
        <label class="field"><span>Program</span>
          <select class="select" id="f-program"><option value="">Tümü</option></select></label>
      </div>
      <div class="card" style="overflow:hidden">
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>Çağrı</th><th class="hide-sm">Program</th><th>Son başvuru</th><th class="hide-sm"></th></tr></thead>
            <tbody id="ilan-rows"></tbody>
          </table>
        </div>
      </div>
      <div id="more" style="text-align:center;margin-top:14px"></div>
    </div>`;

  const q = el.querySelector("#f-q");
  q.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { filters.q = q.value; load(); }, 300);
  });
  for (const [id, key] of [["#f-durum", "durum"], ["#f-hedef", "hedef_kitle"], ["#f-program", "program"]]) {
    el.querySelector(id).addEventListener("change", (e) => { filters[key] = e.target.value; load(); });
  }
  el.querySelector("#tara").addEventListener("click", showTaraPanel);
  el.querySelector("#ilan-rows").addEventListener("click", onRowClick);

  getProgramlar().then(renderProgramlar).catch(() => {});
  refreshTarama();
  load();

  return () => {
    root = null;
    clearTimeout(pollTimer);
    clearTimeout(searchTimer);
  };
}

// ---------------------------------------------------------------------------
// Liste
// ---------------------------------------------------------------------------
async function load({ append = false } = {}) {
  const id = ++requestId;
  const rows = root?.querySelector("#ilan-rows");
  if (!rows) return;
  if (!append) {
    rows.innerHTML = `<tr><td colspan="4"><div class="skel" style="height:14px"></div></td></tr>`.repeat(3);
    open = new Set();
  }
  try {
    const res = await getCagrilar({ ...filters, limit: PAGE_SIZE, offset: append ? cagrilar.length : 0 });
    if (id !== requestId || !root) return;
    cagrilar = append ? [...cagrilar, ...res.cagrilar] : res.cagrilar;
    toplam = res.toplam;
    renderRows();
  } catch (err) {
    if (id !== requestId || !root) return;
    rows.innerHTML = `<tr><td colspan="4">${notice("err", esc(err.message))}</td></tr>`;
  }
}

function renderRows() {
  const rows = root.querySelector("#ilan-rows");
  root.querySelector("#ilan-sub").textContent =
    `${toplam} çağrı${CONFIG.USE_MOCK ? " · örnek veri" : ""} · TÜBİTAK duyurularından otomatik toplanır`;

  if (!cagrilar.length) {
    rows.innerHTML = `<tr><td colspan="4"><div class="empty" style="padding:28px">
      ${icon("file")}<h3>Bu filtrelere uyan çağrı yok</h3>
      <p class="small">Filtreleri değiştirin ya da <b>Durum: Tümü</b> seçin.</p></div></td></tr>`;
  } else {
    rows.innerHTML = cagrilar.map(rowHtml).join("");
  }
  const more = root.querySelector("#more");
  more.innerHTML = cagrilar.length < toplam
    ? `<button class="btn btn-outline" id="load-more">Daha fazla göster (${toplam - cagrilar.length})</button>` : "";
  more.querySelector("#load-more")?.addEventListener("click", () => load({ append: true }));
}

function rowHtml(c) {
  const [cls, label] = HEDEF_KITLE[c.hedef_kitle] ?? ["muted", c.hedef_kitle];
  const uygun = c.uygun_hocalar?.length
    ? `<span class="badge ok" title="${esc(c.uygun_hocalar.map(displayName).join(", "))}">${icon("user-check")} ${c.uygun_hocalar.length} uygun hoca</span>` : "";
  return `
    <tr class="clickable ${open.has(c.id) ? "selected" : ""}" data-id="${esc(c.id)}" aria-expanded="${open.has(c.id)}">
      <td style="max-width:480px">
        <div class="cell-title">${esc(c.baslik)}</div>
        <div class="cell-sub" style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px">
          ${durumBadge(c.durum)}<span class="badge ${cls}">${esc(label)}</span>${uygun}
        </div>
      </td>
      <td class="hide-sm small">${esc([c.program_kodu, c.program_adi].filter(Boolean).join(" · ") || "—")}</td>
      <td>${tarihCell(c)}</td>
      <td class="hide-sm"><a class="btn btn-soft" href="#/eslestir/cagri/${encodeURIComponent(c.id)}" data-stop>Eşleştir</a></td>
    </tr>
    ${open.has(c.id) ? detailRow(c) : ""}`;
}

function detailRow(c) {
  const meta = [["Bütçe", c.butce], ["Süre", c.sure]].filter(([, v]) => v);
  return `
    <tr class="detail-row"><td colspan="4" style="background:var(--surface-2)">
      <div class="stack" style="gap:14px;max-width:900px">
        ${c.ozet ? `<p class="small" style="line-height:1.6;margin:0">${esc(c.ozet)}</p>` : ""}
        <div><div class="section-label">Tarihler</div>${tarihList(c.tarihler)}</div>
        ${meta.length ? `<dl class="meta-list">${meta.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("")}</dl>` : ""}
        ${c.basvuru_kosullari?.length ? `<div><div class="section-label">Başvuru koşulları</div>
          <ul class="kosullar">${c.basvuru_kosullari.map((k) => `<li>${esc(k)}</li>`).join("")}</ul></div>` : ""}
        ${c.uygun_hocalar?.length ? `<div><div class="section-label">Uygun hocalar (otomatik eşleştirme)</div>
          <p class="small" style="margin:0">${c.uygun_hocalar.map((h, i) => `${i + 1}. ${esc(displayName(h))}`).join(" · ")}</p></div>` : ""}
        <div style="display:flex;gap:14px;flex-wrap:wrap;align-items:center">
          <a class="btn btn-primary" href="#/eslestir/cagri/${encodeURIComponent(c.id)}">${icon("swap")} Eşleştir</a>
          <a class="link-btn" href="${esc(c.url)}" target="_blank" rel="noopener">${icon("external")} TÜBİTAK duyurusu</a>
          ${(c.baglantilar ?? []).map((b) => `<a class="link-btn" href="${esc(b.url)}" target="_blank" rel="noopener">${esc(b.etiket)}</a>`).join("")}
        </div>
        ${c.guncelleme_urller?.length ? `<p class="tiny muted" style="margin:0">Bu çağrı ${c.guncelleme_urller.length} güncelleme duyurusuyla değişti (tarihler günceldir).</p>` : ""}
      </div>
    </td></tr>`;
}

function onRowClick(e) {
  if (e.target.closest("a, button")) return;
  const tr = e.target.closest("tr[data-id]");
  if (!tr) return;
  const id = tr.dataset.id;
  if (open.has(id)) open.delete(id);
  else open.add(id);
  renderRows();
}

function renderProgramlar(programlar) {
  const select = root?.querySelector("#f-program");
  if (!select) return;
  select.innerHTML = `<option value="">Tümü</option>${programlar.map((p) =>
    `<option value="${esc(p.kod)}" ${filters.program === p.kod ? "selected" : ""}>${esc(p.kod)}${p.ad ? ` · ${esc(p.ad)}` : ""} (${p.sayi})</option>`).join("")}`;
}

// ---------------------------------------------------------------------------
// Kaynakları tara: yönetici anahtarı ile istek, bitene kadar durum takibi
// ---------------------------------------------------------------------------
function readToken() {
  try { return localStorage.getItem(TOKEN_KEY) ?? ""; } catch { return ""; }
}

function saveToken(token) {
  try { localStorage.setItem(TOKEN_KEY, token); } catch { /* sadece bu istek için kullanılır */ }
}

function showTaraPanel() {
  const panel = root.querySelector("#tara-panel");
  if (panel.innerHTML) {
    panel.innerHTML = "";
    return;
  }
  panel.innerHTML = `
    <form class="card card-pad" id="tara-form" style="display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap;margin-bottom:20px">
      <label class="field" style="flex:1;min-width:220px"><span>Yönetici anahtarı</span>
        <input class="input" type="password" id="tara-token" value="${esc(readToken())}" autocomplete="off" required></label>
      <button class="btn btn-primary" type="submit">Taramayı başlat</button>
      <p class="tiny muted" style="flex-basis:100%;margin:0">Kaynaklar her gün otomatik taranır. Elle tarama yeni duyuruları hemen işler (birkaç dakika sürebilir).</p>
    </form>`;
  const input = panel.querySelector("#tara-token");
  input.focus();
  panel.querySelector("#tara-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const token = input.value.trim();
    try {
      await tara(token);
      saveToken(token);
      panel.innerHTML = "";
      toast("Tarama başlatıldı.");
      refreshTarama();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        panel.innerHTML = "";
        toast(err.message);
        refreshTarama();
      } else toast(err.message);
    }
  });
}

let taramaAktif = false;

async function refreshTarama() {
  clearTimeout(pollTimer);
  let t;
  try {
    t = await getTarama();
  } catch {
    return;
  }
  const el = root?.querySelector("#tarama-durum");
  if (!el) return;
  const aktif = !!t.son && ["bekliyor", "calisiyor"].includes(t.son.durum);
  if (taramaAktif && !aktif) { // tarama az önce bitti: listeyi yenile
    load();
    getProgramlar().then(renderProgramlar).catch(() => {});
  }
  taramaAktif = aktif;
  root.querySelector("#tara").disabled = aktif || CONFIG.USE_MOCK;
  if (aktif) {
    el.innerHTML = `<span class="spinner dark"></span> ${t.son.durum === "bekliyor" ? "Tarama sırada" : "Taranıyor"}…`;
    pollTimer = setTimeout(refreshTarama, POLL_MS);
    return;
  }
  const hata = t.son?.durum === "hata" ? ` · son tarama hatalı` : "";
  el.textContent = t.son_basarili ? `Son güncelleme: ${formatDateTime(t.son_basarili)}${hata}` : hata.slice(3);
  if (t.son?.durum === "hata") el.title = t.son.hata ?? "";
}
