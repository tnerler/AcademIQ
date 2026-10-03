// CV'ler sayfasındaki "CV'ler güncel mi?" kontrolü: YÖK Akademik'i yeniden tarar ve son bilinen
// durumla farkı (yeni/ayrılan hoca, unvan-bölüm değişikliği, eklenen/silinen yayın-ders-proje) gösterir.
// Tarama backend'de yok-worker'da çalışır; burası isteği gönderir ve bitene kadar durumu izler.

import { getYokTarama, yokTara, ApiError } from "./api.js";
import { CONFIG } from "./config.js";
import { esc, icon, notice, toast, formatDateTime, displayName } from "./ui.js";

const TOKEN_KEY = "academiq.adminToken"; // Proje İlanları'ndaki "Kaynakları tara" ile ortak
const POLL_MS = 3000;

const TUR = {
  hizli: { ad: "Hızlı kontrol", sure: "~1 dk", aciklama: "Yeni gelen / ayrılan hocalar, unvan, bölüm ve anahtar kelime değişiklikleri." },
  tam: { ad: "Tam tarama", sure: "~2 saat", aciklama: "Hızlı kontrole ek olarak her hocanın yayın, proje, ders, tez ve patentlerindeki eklenen/silinen kayıtlar." },
};
const ALAN = {
  ad_soyad: "Ad soyad", unvan: "Unvan", fakulte: "Fakülte", bolum: "Bölüm", anabilim_dali_program: "Anabilim dalı / program",
  temel_alan: "Temel alan", bilim_alani: "Bilim alanı", anahtar_kelimeler: "Anahtar kelimeler", eposta: "E-posta", orcid: "ORCID",
};
const BOLUM = {
  makaleler: "Makaleler", bildiriler: "Bildiriler", kitaplar: "Kitaplar", projeler: "Projeler", dersler: "Dersler",
  yonetilen_tezler: "Yönetilen tezler", patentler: "Patentler", akademik_gorevler: "Akademik görevler", ogrenim: "Öğrenim",
};

/**
 * headEl: sayfa başlığındaki buton + durum yazısı, bodyEl: başlığın altındaki form / ilerleme / rapor alanı.
 * Dönen fonksiyon sayfadan çıkarken çağrılır.
 */
export function mountYokKontrol(headEl, bodyEl) {
  let pollTimer = null;
  let oncekiAktif = null; // izlenen taramanın id'si: bitince bildirim gösterilir
  let raporAcik = false;
  let durum = null;
  let alive = true;

  headEl.innerHTML = `
    <span class="tiny muted" id="yk-durum"></span>
    <button class="btn btn-outline" id="yk-ac" ${CONFIG.USE_MOCK ? "disabled title=\"Mock modda kullanılamaz\"" : ""}>
      ${icon("refresh")} CV'ler güncel mi?</button>`;
  bodyEl.innerHTML = `<div id="yk-form"></div><div id="yk-panel"></div>`;
  headEl.querySelector("#yk-ac").addEventListener("click", toggleForm);
  bodyEl.querySelector("#yk-panel").addEventListener("click", (e) => {
    if (e.target.closest("#yk-rapor-ac")) {
      raporAcik = !raporAcik;
      renderPanel();
    }
  });

  refresh();
  return () => {
    alive = false;
    clearTimeout(pollTimer);
  };

  // -------------------------------------------------------------------------
  async function refresh() {
    clearTimeout(pollTimer);
    try {
      durum = await getYokTarama();
    } catch {
      if (!alive) return;
      headEl.querySelector("#yk-durum").textContent = "";
      headEl.querySelector("#yk-ac").title = "YÖK durumu alınamadı (backend güncel mi?)";
      return;
    }
    if (!alive) return;

    const aktif = durum.aktif;
    if (oncekiAktif && !aktif && durum.son_biten?.id === oncekiAktif) bittiBildir(durum.son_biten);
    oncekiAktif = aktif?.id ?? null;

    headEl.querySelector("#yk-ac").disabled = !!aktif || CONFIG.USE_MOCK;
    const son = durum.son_biten;
    headEl.querySelector("#yk-durum").textContent = aktif ? ""
      : son ? `YÖK son kontrol: ${formatDateTime(son.bitti)}` : "YÖK henüz kontrol edilmedi";
    renderPanel();
    if (aktif) pollTimer = setTimeout(refresh, POLL_MS);
  }

  function bittiBildir(t) {
    if (t.durum === "hata") return toast("YÖK kontrolü tamamlanamadı.");
    const o = t.ozet ?? {};
    toast(o.eklenen || o.ayrilan || o.degisen ? `YÖK kontrolü bitti: ${ozetMetni(o)}.` : "YÖK kontrolü bitti: değişiklik yok.");
    raporAcik = true;
  }

  // -------------------------------------------------------------------------
  // Başlatma formu (yönetici anahtarı + tarama türü)
  // -------------------------------------------------------------------------
  function toggleForm() {
    const form = bodyEl.querySelector("#yk-form");
    if (form.innerHTML) {
      form.innerHTML = "";
      return;
    }
    let tur = "hizli";
    form.innerHTML = `
      <form class="card card-pad yok-form">
        <div class="field"><span>Tarama türü</span>
          <div class="segmented" role="radiogroup" aria-label="Tarama türü">
            ${Object.entries(TUR).map(([k, t]) => `<button type="button" role="radio" data-tur="${k}"
              class="${k === tur ? "active" : ""}" aria-checked="${k === tur}">${esc(t.ad)} <span class="tiny muted">${t.sure}</span></button>`).join("")}
          </div>
          <p class="tiny muted" id="yk-tur-aciklama" style="margin:6px 0 0">${esc(TUR[tur].aciklama)}</p>
        </div>
        <div style="display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap">
          <label class="field" style="flex:1;min-width:220px"><span>Yönetici anahtarı</span>
            <input class="input" type="password" id="yk-token" value="${esc(readToken())}" autocomplete="off" required></label>
          <button class="btn btn-cta" type="submit">Kontrolü başlat</button>
        </div>
        <p class="tiny muted" style="margin:0">Tam tarama her hafta otomatik çalışır. Tarama arka planda sürer, bu sayfadan ayrılabilirsiniz.</p>
      </form>`;
    const formEl = form.querySelector("form");
    formEl.querySelector(".segmented").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-tur]");
      if (!b) return;
      tur = b.dataset.tur;
      formEl.querySelectorAll("button[data-tur]").forEach((x) => {
        x.classList.toggle("active", x === b);
        x.setAttribute("aria-checked", String(x === b));
      });
      formEl.querySelector("#yk-tur-aciklama").textContent = TUR[tur].aciklama;
    });
    const input = formEl.querySelector("#yk-token");
    input.focus();
    formEl.addEventListener("submit", async (e) => {
      e.preventDefault();
      const token = input.value.trim();
      try {
        await yokTara(token, tur);
        saveToken(token);
        form.innerHTML = "";
        raporAcik = false;
        toast(`${TUR[tur].ad} başlatıldı.`);
      } catch (err) {
        toast(err.message, 5000);
        if (!(err instanceof ApiError && err.status === 409)) return;
        form.innerHTML = "";
      }
      refresh();
    });
  }

  // -------------------------------------------------------------------------
  // Durum paneli: süren tarama ya da son raporun özeti ve detayı
  // -------------------------------------------------------------------------
  function renderPanel() {
    const panel = bodyEl.querySelector("#yk-panel");
    if (!durum) return;
    if (durum.aktif) {
      panel.innerHTML = aktifHtml(durum.aktif);
      return;
    }
    const t = durum.son_biten;
    if (!t) {
      panel.innerHTML = "";
      return;
    }
    if (t.durum === "hata") {
      panel.innerHTML = notice("warn", `<b>Son YÖK kontrolü tamamlanamadı</b> (${esc(formatDateTime(t.bitti))}). ${esc(t.hata ?? "")}
        ${t.ozet && (t.ozet.eklenen || t.ozet.ayrilan || t.ozet.degisen) ? `<br>Yarıda kalmadan önce bulunanlar: ${esc(ozetMetni(t.ozet))}.` : ""}`);
      return;
    }
    const o = t.ozet ?? {};
    const degisiklikVar = o.eklenen || o.ayrilan || o.degisen;
    if (!degisiklikVar) {
      panel.innerHTML = `<div class="yok-strip ok">${icon("check")}<span><b>Veriler güncel.</b> ${esc(TUR[t.tur].ad)}
        (${esc(formatDateTime(t.bitti))}): ${durum.akademisyen_sayisi} hocada değişiklik yok.${t.tur === "hizli" ? tamNotu() : ""}</span></div>`;
      return;
    }
    panel.innerHTML = `
      <div class="card yok-rapor">
        <div class="yok-strip">
          ${icon("info")}
          <span><b>YÖK'te değişiklik var:</b> ${esc(ozetMetni(o))}
            <span class="tiny muted">· ${esc(TUR[t.tur].ad)}, ${esc(formatDateTime(t.bitti))}</span></span>
          <button class="link-btn" id="yk-rapor-ac" aria-expanded="${raporAcik}">${raporAcik ? "Raporu gizle" : "Raporu göster"}</button>
        </div>
        ${raporAcik ? `<div class="yok-detay">${raporHtml(t.rapor)}${t.tur === "hizli" ? `<p class="tiny muted" style="margin:0">${tamNotu().trim()}</p>` : ""}</div>` : ""}
      </div>`;
  }
}

function aktifHtml(t) {
  const il = t.ilerleme;
  const bekliyor = t.durum === "bekliyor";
  const detay = il?.asama === "detay" && il.toplam;
  const yuzde = detay ? Math.round((il.yapilan / il.toplam) * 100) : null;
  const adim = bekliyor ? "Sırada, birazdan başlayacak"
    : !il || il.asama === "liste" ? "YÖK'teki hoca listesi taranıyor"
      : detay ? `Hocaların yayın ve dersleri karşılaştırılıyor: ${il.yapilan}/${il.toplam}` : "Tamamlanıyor";
  const kalanDk = detay && il.yapilan < il.toplam ? Math.max(1, Math.round(((il.toplam - il.yapilan) * 28) / 60)) : null;
  return `
    <div class="card card-pad yok-aktif">
      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
        <span class="spinner dark"></span>
        <b>${esc(TUR[t.tur].ad)} sürüyor</b>
        <span class="small muted">${esc(adim)}${kalanDk ? ` · yaklaşık ${kalanDk} dk kaldı` : ""}</span>
      </div>
      ${yuzde != null ? `<div class="score-bar" style="margin-top:12px"><i style="width:${yuzde}%"></i></div>` : ""}
      ${t.ozet && (t.ozet.eklenen || t.ozet.ayrilan || t.ozet.degisen)
        ? `<p class="tiny muted" style="margin:10px 0 0">Şu ana kadar: ${esc(ozetMetni(t.ozet))}</p>` : ""}
    </div>`;
}

function raporHtml(r) {
  if (!r) return "";
  const kisi = (k) => `<div><b>${esc(displayName(k.ad_soyad))}</b> <span class="muted">· ${esc([displayName(k.unvan), displayName(k.bolum)].filter(Boolean).join(" · "))}</span></div>`;
  const bolumler = [];
  if (r.eklenen.length) bolumler.push(grup(`Yeni gelen hocalar (${r.eklenen.length})`, r.eklenen.map((k) => `<li>${kisi(k)}</li>`)));
  if (r.ayrilan.length) bolumler.push(grup(`Listeden ayrılan hocalar (${r.ayrilan.length})`, r.ayrilan.map((k) => `<li>${kisi(k)}</li>`)));
  if (r.degisen.length) {
    bolumler.push(grup(`Bilgisi değişen hocalar (${r.degisen.length})`, r.degisen.map((d) => `
      <li class="yok-kisi">${kisi(d)}
        ${d.alanlar.map(alanHtml).join("")}
        ${Object.entries(d.bolumler).map(([b, f]) => bolumHtml(b, f)).join("")}
      </li>`)));
  }
  return bolumler.join("");
}

function alanHtml(a) {
  const ad = ALAN[a.alan] ?? a.alan;
  if (Array.isArray(a.eski) || Array.isArray(a.yeni)) {
    const eski = a.eski ?? [];
    const yeni = a.yeni ?? [];
    const eklenen = yeni.filter((x) => !eski.includes(x));
    const silinen = eski.filter((x) => !yeni.includes(x));
    return `<div class="small">${esc(ad)}: ${eklenen.map((x) => `<span class="diff-add">+ ${esc(x)}</span>`).join(" ")}
      ${silinen.map((x) => `<span class="diff-del">− ${esc(x)}</span>`).join(" ")}</div>`;
  }
  return `<div class="small">${esc(ad)}: <span class="diff-del">${esc(a.eski || "—")}</span> → <span class="diff-add">${esc(a.yeni || "—")}</span></div>`;
}

function bolumHtml(bolum, f) {
  const sayi = [f.eklenen.length && `<span class="diff-add">+${f.eklenen.length}</span>`,
    f.silinen.length && `<span class="diff-del">−${f.silinen.length}</span>`].filter(Boolean).join(" ");
  return `<details class="more yok-bolum"><summary>${esc(BOLUM[bolum] ?? bolum)} ${sayi}</summary>
    <ul class="kosullar">
      ${f.eklenen.map((x) => `<li><span class="diff-add">+</span> ${esc(x)}</li>`).join("")}
      ${f.silinen.map((x) => `<li><span class="diff-del">−</span> ${esc(x)}</li>`).join("")}
    </ul></details>`;
}

const grup = (baslik, items) => `<div><div class="section-label">${esc(baslik)}</div><ul class="yok-liste">${items.join("")}</ul></div>`;

function ozetMetni(o) {
  return [o.eklenen && `${o.eklenen} yeni hoca`, o.ayrilan && `${o.ayrilan} ayrılan`, o.degisen && `${o.degisen} hocada değişiklik`]
    .filter(Boolean).join(" · ");
}

const tamNotu = () => " Yayın, ders ve proje farkları yalnızca tam taramada kontrol edilir.";

function readToken() {
  try { return localStorage.getItem(TOKEN_KEY) ?? ""; } catch { return ""; }
}

function saveToken(token) {
  try { localStorage.setItem(TOKEN_KEY, token); } catch { /* sadece bu istek için kullanılır */ }
}
