import { esc, icon, passiveNotice } from "../ui.js";

export const title = "CV Yükle";

const STATUS = { ok: ["ok", "Tamam"], run: ["warn", "Sürüyor"], wait: ["muted", "Bekliyor"], err: ["err", "Hata"] };

const SAMPLE_ROWS = [
  ["H008_Hasan_Tunc.pdf", ["ok", "ok", "ok", "ok", "ok"]],
  ["H034_Burcu_Kurt.pdf", ["ok", "ok", "ok", "run", "wait"]],
  ["H036_Ebru_Isik.pdf", ["ok", "ok", "run", "wait", "wait"]],
  ["taranmis_cv_scan.pdf", ["ok", "err", "wait", "wait", "wait"]],
];

export function render(el) {
  el.innerHTML = `
    <div class="page">
      <div class="page-head"><div>
        <h1 class="page-title">CV Yükle</h1>
        <p class="page-sub">Yüklenen her CV metne çevrilir, bölümlere ayrılır ve eşleştirme için indekslenir.</p>
      </div></div>
      ${passiveNotice("Tüm CV'ler bu aşamada arka planda önceden indekslendi; kullanıcıdan CV yüklemesi alınmıyor.")}

      <div class="two-col" inert>
        <div class="stack">
          <div class="dropzone disabled">
            ${icon("upload")}
            <div class="dz-title">PDF dosyalarını buraya sürükleyin</div>
            <div class="dz-sub">veya bilgisayarınızdan seçin · birden fazla dosya seçilebilir</div>
          </div>
          <div class="card" style="overflow:hidden">
            <div class="table-wrap">
              <table class="table compact">
                <thead><tr><th>Dosya</th><th>Yüklendi</th><th>Metin</th><th>Bölümler</th><th>Embedding</th><th>Vektör DB</th></tr></thead>
                <tbody>${SAMPLE_ROWS.map(([name, steps]) => `
                  <tr><td class="cell-title">${esc(name)}</td>${steps
                    .map((s) => `<td><span class="badge ${STATUS[s][0]}">${STATUS[s][1]}</span></td>`)
                    .join("")}</tr>`).join("")}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div class="card card-pad stack">
          <div>
            <h3 style="font-size:17px;font-weight:600">Algılanan bilgiler</h3>
            <p class="small muted">CV'den otomatik çıkarıldı. Kaydetmeden önce kontrol edin.</p>
          </div>
          <label class="field"><span>Ad Soyad</span><input class="input" value="Hasan Tunç" disabled></label>
          <label class="field"><span>Unvan</span><input class="input" value="Doç. Dr." disabled></label>
          <label class="field"><span>Üniversite / Bölüm</span><input class="input" value="Hacettepe Üniversitesi · Bilgisayar Müh." disabled></label>
          <div class="field"><span>Uzmanlık alanları</span>
            <div class="chips">
              <span class="chip">Büyük dil modelleri</span><span class="chip">Derin öğrenme</span>
              <span class="chip">Pekiştirmeli öğrenme</span><span class="chip add">+ ekle</span>
            </div>
          </div>
          <p class="small muted">Bölümler: Eğitim · Yayınlar · Projeler · Tezler</p>
          <button class="btn btn-primary btn-block" disabled>Onayla ve indeksle</button>
        </div>
      </div>
    </div>`;
}
