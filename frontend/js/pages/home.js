import { getCvs, getCagrilar } from "../api.js";
import { icon } from "../ui.js";

export const title = "Ana Sayfa";

export function render(el) {
  el.innerHTML = `
    <div class="page">
      <h1 class="page-title xl">Proje ilanlarını doğru akademisyenlerle buluşturun</h1>
      <p class="page-sub">CV'leri yükleyin, ilanları inceleyin ve bir ilan için en uygun hocaları gerekçeleriyle listeleyin.</p>

      <div class="home-grid">
        <a class="card home-card" href="#/cvler">
          <div class="icon-box">${icon("users")}</div>
          <h2>CV'leri görüntüle</h2>
          <p>Sistemdeki hocaları alan, unvan ve üniversiteye göre filtreleyin, CV detayına bakın.</p>
          <span class="meta" id="cv-count">&nbsp;</span>
        </a>
        <a class="card home-card" href="#/cv-yukle">
          <div class="icon-box">${icon("upload")}</div>
          <h2>CV yükle</h2>
          <p>PDF CV'leri sürükleyip bırakın; metin çıkarılır, bölümlere ayrılır ve vektör veritabanına eklenir.</p>
          <span class="meta">PDF · toplu yükleme</span>
        </a>
        <a class="card home-card" href="#/ilanlar">
          <div class="icon-box">${icon("file")}</div>
          <h2>Proje ilanlarını görüntüle</h2>
          <p>TÜBİTAK duyurularından her gün toplanan çağrıları son başvuru tarihi ve programa göre inceleyin.</p>
          <span class="meta" id="cagri-count">İlan listesi</span>
        </a>
        <a class="card home-card dark" href="#/eslestir">
          <div class="icon-box">${icon("swap")}</div>
          <h2>CV'leri eşleştir</h2>
          <p>Bir ilan PDF'i yükleyin; en uygun hocalar skor, gerekçe ve CV'den kanıtlarıyla sıralansın.</p>
          <span class="meta">Eşleştirmeyi başlat ${icon("arrow")}</span>
        </a>
      </div>

      <a class="card home-banner" href="#/bana-uygun">
        <div>
          <h3>Akademisyen misiniz?</h3>
          <p>Kendi CV'nizi yükleyin, yalnızca size uygun proje ilanlarını görün.</p>
        </div>
        <span class="go">Bana uygun ilanlar →</span>
      </a>
    </div>`;

  const count = el.querySelector("#cv-count");
  getCvs()
    .then((cvs) => (count.textContent = `${cvs.length} CV kayıtlı`))
    .catch(() => (count.textContent = "CV listesine git"));

  const cagriCount = el.querySelector("#cagri-count");
  getCagrilar({ durum: "acik", limit: 1 })
    .then((r) => (cagriCount.textContent = `${r.toplam} çağrının başvurusu açık`))
    .catch(() => {});
}
