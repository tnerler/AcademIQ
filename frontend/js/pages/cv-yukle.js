import { uploadCv, validateCv } from "../api.js";
import { CONFIG } from "../config.js";
import { esc, icon, chips, notice, toast, formatBytes, fullName } from "../ui.js";

export const title = "CV Yükle";

// Yükleme listesi modül seviyesinde: sayfadan çıkıp dönünce kaybolmaz. Dosyalar sırayla işlenir.
const uploads = []; // { file, status: wait|run|ok|err, hoca?, error? }
let running = false;
let root = null;

const STATUS = { ok: ["ok", "İndekslendi"], run: ["warn", "İşleniyor"], wait: ["muted", "Bekliyor"], err: ["err", "Hata"] };

export function render(el) {
  root = el;
  el.innerHTML = `
    <div class="page">
      <div class="page-head"><div>
        <h1 class="page-title">CV Yükle</h1>
        <p class="page-sub">Yüklenen her CV metne çevrilir, bölümlere ayrılır, profili çıkarılır ve eşleştirme için indekslenir.
          Aynı e-posta adresiyle kayıtlı bir hoca varsa kaydı güncellenir.</p>
      </div></div>
      <div class="two-col">
        <div class="stack">
          <input type="file" id="file-input" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" multiple hidden>
          <div class="dropzone" tabindex="0" role="button" aria-label="CV dosyaları seç">
            ${icon("upload")}
            <div class="dz-title">CV dosyalarını buraya sürükleyin</div>
            <div class="dz-sub">PDF ya da Word (.docx) · birden fazla dosya seçilebilir · en fazla ${CONFIG.MAX_PDF_MB} MB</div>
          </div>
          <div id="uploads"></div>
        </div>
        <div id="detail"></div>
      </div>
    </div>`;

  const input = el.querySelector("#file-input");
  const dz = el.querySelector(".dropzone");
  input.addEventListener("change", () => {
    addFiles([...input.files]);
    input.value = "";
  });
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
    addFiles([...e.dataTransfer.files]);
  });

  renderUploads();
  return () => {
    root = null;
  };
}

function addFiles(files) {
  for (const file of files) {
    const invalid = validateCv(file);
    if (invalid) toast(`${file.name}: ${invalid.message}`);
    else uploads.push({ file, status: "wait" });
  }
  renderUploads();
  processQueue();
}

async function processQueue() {
  if (running) return;
  running = true;
  for (let u = uploads.find((x) => x.status === "wait"); u; u = uploads.find((x) => x.status === "wait")) {
    u.status = "run";
    renderUploads();
    try {
      u.hoca = await uploadCv(u.file);
      u.status = "ok";
    } catch (err) {
      Object.assign(u, { status: "err", error: err.message });
    }
    renderUploads();
  }
  running = false;
}

function renderUploads() {
  const list = root?.querySelector("#uploads");
  if (!list) return;
  list.innerHTML = uploads.length ? `
    <div class="card" style="overflow:hidden"><div class="table-wrap">
      <table class="table compact">
        <thead><tr><th>Dosya</th><th>Durum</th><th>Akademisyen</th></tr></thead>
        <tbody>${uploads.map((u, i) => `
          <tr>
            <td class="cell-title">${esc(u.file.name)}<div class="cell-sub">${formatBytes(u.file.size)}</div></td>
            <td><span class="badge ${STATUS[u.status][0]}" ${u.error ? `title="${esc(u.error)}"` : ""}>
              ${u.status === "run" ? `<span class="spinner dark"></span> ` : ""}${STATUS[u.status][1]}</span></td>
            <td>${u.hoca ? `<a class="link-btn" href="#/cvler/${encodeURIComponent(u.hoca.id)}">${esc(fullName(u.hoca))}</a>`
              : u.error ? `<span class="small" style="color:var(--err-fg)">${esc(u.error)}</span>` : "—"}</td>
          </tr>`).join("")}
        </tbody>
      </table>
    </div></div>
    <p class="tiny muted">Her CV'nin işlenmesi (metin çıkarma, yapay zekâ profili, embedding) 10–20 saniye sürer.</p>` : "";

  const last = [...uploads].reverse().find((u) => u.hoca);
  const detail = root.querySelector("#detail");
  detail.innerHTML = last ? profileCard(last.hoca) : `
    <div class="card card-pad stack">
      <h3 style="font-size:17px;font-weight:600">Nasıl çalışır?</h3>
      ${notice("info", "CV'deki araştırma alanları, yayınlar, projeler ve tezler okunur; bunlardan akademisyenin profili çıkarılır. İndekslenen CV, <b>Eşleştir</b> sonuçlarında hemen görünür.")}
    </div>`;
}

function profileCard(h) {
  const p = h.profil ?? {};
  return `
    <div class="card card-pad stack">
      <div>
        <div class="section-label">Son indekslenen</div>
        <h3 style="font-size:17px;font-weight:600">${esc(fullName(h))}</h3>
        <p class="small muted">${esc([h.universite, h.bolum].filter(Boolean).join(" · "))}</p>
      </div>
      ${p.arastirma_alanlari?.length ? `<div class="field"><span>Araştırma alanları</span>${chips(p.arastirma_alanlari)}</div>` : ""}
      ${p.yontemler?.length ? `<div class="field"><span>Yöntemler</span>${chips(p.yontemler, { size: "sm" })}</div>` : ""}
      ${p.ozet_metni ? `<p class="small muted" style="line-height:1.6">${esc(p.ozet_metni)}</p>` : ""}
      <a class="btn btn-outline" href="#/cvler/${encodeURIComponent(h.id)}">CV detayına git</a>
    </div>`;
}
