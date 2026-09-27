import { esc, icon, chips, scoreBar, passiveNotice } from "../ui.js";

export const title = "Bana Uygun İlanlar";

// Tasarımdaki örnek sonuçlar; bu ekran demo aşamasında işlevsiz.
const SAMPLE = [
  {
    baslik: "Türkçe Büyük Dil Modelleri ile Açıklanabilir Karar Destek Sistemleri",
    alt: "TÜBİTAK 1001 · Son başvuru 25.10.2026",
    skor: 81,
    neden: "Büyük dil modelleri ve Türkçe metin madenciliği üzerine yayın ve proje geçmişiniz ilanın ana konusuyla örtüşüyor.",
    eksik: "Açıklanabilir yapay zekâ alanında doğrudan yayınınız görünmüyor.",
  },
  {
    baslik: "STEM Eğitiminde Yapay Zekâ Destekli Kişiselleştirilmiş Öğrenme Platformu",
    alt: "Milli Eğitim Bakanlığı · Son başvuru 20.10.2026",
    skor: 76,
    neden: "Yapay zekâ uzmanlığınız ve eğitim teknolojileri alanındaki çalışmalarınız ilanın disiplinlerarası yapısına uyuyor.",
    eksik: "Oyunlaştırma ve öğrenme analitiği deneyimi olan bir ekip üyesi faydalı olur.",
  },
  {
    baslik: "Tarımda Yapay Zekâ Destekli Uzaktan Algılama ile Hassas Tarım Uygulamaları",
    alt: "TÜBİTAK 1001 · Son başvuru 12.11.2026",
    skor: 61,
    neden: "Derin öğrenme yöntemleri ilanın modelleme kısmında doğrudan kullanılabilir.",
    eksik: "Tarım ve uzaktan algılama alanı dışındasınız; araştırmacı olarak katılmanız daha uygun.",
  },
];

export function render(el) {
  el.innerHTML = `
    <div class="page">
      ${passiveNotice("Akademisyenlerin kendi CV'leriyle ilan araması ileriki aşamada eklenecek.")}
      <div class="match-layout" inert>
        <section class="match-left">
          <div>
            <h1 class="page-title">Bana Uygun İlanlar</h1>
            <p class="page-sub">CV'nizi yükleyin, yalnızca profilinizle eşleşen proje ilanlarını görün.</p>
          </div>
          <div class="dropzone disabled">
            ${icon("upload")}
            <div class="dz-title">CV'nizi sürükleyin veya seçin</div>
            <div class="dz-sub">Yalnızca PDF · tek dosya</div>
          </div>
          <div class="card card-pad stack" style="gap:12px">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:10px">
              <b>Hasan_Tunc_CV.pdf</b><span class="badge ok">Analiz edildi</span>
            </div>
            <div class="section-label">CV'nizden algılanan alanlar</div>
            ${chips(["Büyük dil modelleri", "Derin öğrenme", "Türkçe metin madenciliği", "Eğitim teknolojileri"])}
          </div>
          <div class="card card-pad stack" style="gap:12px">
            <label class="check disabled"><input type="checkbox" disabled> Yalnızca başvurusu açık ilanlar</label>
            <label class="check disabled"><input type="checkbox" disabled> CV'mi sisteme kaydet ve yeni ilanlarda bana haber ver</label>
            <p class="tiny muted">İşaretlemezseniz CV'niz yalnızca bu eşleştirme için kullanılır ve saklanmaz.</p>
          </div>
        </section>

        <section class="match-right">
          <div class="results-head"><div>
            <h2>Size uygun 3 ilan</h2>
            <p class="small muted">Örnek sonuç · skorlar gösterim amaçlı</p>
          </div></div>
          <div class="results">
            ${SAMPLE.map((s) => `
              <article class="card result">
                <div style="display:grid;grid-template-columns:minmax(0,1fr) 180px;gap:16px">
                  <div>
                    <div style="font-weight:600;font-size:17px">${esc(s.baslik)}</div>
                    <div class="small muted">${esc(s.alt)}</div>
                  </div>
                  <div><div class="tiny muted" style="text-align:right">Uyum skoru</div>${scoreBar(s.skor)}</div>
                </div>
                <div class="fit-grid">
                  <div><h4 class="ok">Neden uygun?</h4><p class="small muted">${esc(s.neden)}</p></div>
                  <div><h4 class="warn">Eksik kalan</h4><p class="small muted">${esc(s.eksik)}</p></div>
                </div>
                <div class="result-foot"><span class="link-btn">İlan detayı</span><span class="link-btn">Kaynağa git</span></div>
              </article>`).join("")}
          </div>
          <div class="dashed-note" style="margin-top:14px">Diğer 15 ilan profilinizle yeterince örtüşmüyor.</div>
        </section>
      </div>
    </div>`;
}
