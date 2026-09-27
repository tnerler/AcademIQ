import { icon, passiveNotice } from "../ui.js";

export const title = "İlan Ekle";

export function render(el) {
  el.innerHTML = `
    <div class="page">
      <div class="page-head">
        <div>
          <h1 class="page-title">İlan Ekle</h1>
          <p class="page-sub">Bilgiler otomatik çıkarılır; kaydetmeden önce kontrol edin.</p>
        </div>
      </div>
      ${passiveNotice("İlan kaydetme, ilanlar indekslenene kadar devre dışı.")}

      <div class="two-col" inert>
        <div class="stack">
          <div class="segmented">
            <button class="active">PDF yükle</button><button>Bağlantıdan çek</button><button>Elle gir</button>
          </div>
          <div class="dropzone disabled" style="display:flex;align-items:center;gap:14px;text-align:left;padding:18px 22px">
            ${icon("pdf")}
            <div style="flex:1">
              <div style="font-weight:600">cagri_ilani.pdf</div>
              <div class="tiny muted">Tablo formatı algılandı · 1 sayfa</div>
            </div>
            <span class="link-btn">Başka dosya seç</span>
          </div>

          <div class="card card-pad form-grid">
            <label class="field full"><span>Başlık</span>
              <input class="input" value="İklim Değişikliğinin Yenilenebilir Enerji Altyapısına Etkilerinin Değerlendirilmesi" disabled></label>
            <label class="field"><span>Kurum</span><input class="input" value="TÜBİTAK" disabled></label>
            <label class="field"><span>Destek programı</span><input class="input" value="1003 - Öncelikli Alanlar Ar-Ge Projeleri" disabled></label>
            <label class="field"><span>Son başvuru</span><input class="input" type="date" value="2026-10-30" disabled></label>
            <label class="field"><span>Kaynak</span><select class="select" disabled><option>Elle yüklendi</option></select></label>
            <label class="field full"><span>Açıklama</span>
              <textarea class="textarea" disabled>Değişen iklim koşullarının rüzgâr ve güneş enerjisi santrallerinin verimliliği ve dayanıklılığı üzerindeki etkileri incelenecektir.</textarea></label>
            <div class="field full"><span>Aranan uzmanlık alanları</span>
              <div class="chips"><span class="chip">İklim değişikliği etkileri</span><span class="chip">Güneş enerjisi sistemleri</span>
              <span class="chip">Rüzgâr enerjisi</span><span class="chip add">+ ekle</span></div>
            </div>
          </div>

          <div class="notice warn" style="margin:0">
            ${icon("alert")}<div><b>Benzer bir ilan zaten kayıtlı olabilir:</b> aynı başlık ve son başvuru tarihi.</div>
            <span class="notice-actions link-btn" style="color:inherit">Mevcut ilanı gör</span>
          </div>
          <div class="row-actions">
            <button class="btn btn-outline" disabled>Kaydet</button>
            <button class="btn btn-primary" disabled>Kaydet ve eşleştir</button>
          </div>
        </div>

        <div class="stack">
          <div class="card card-pad">
            <div style="display:flex;align-items:center;justify-content:space-between;gap:10px">
              <h3 style="font-size:17px;font-weight:600">Otomatik taramalar</h3>
              <button class="btn btn-outline" style="padding:7px 14px;font-size:14px" disabled>Şimdi tara</button>
            </div>
            <div class="scan-item" style="margin-top:14px">
              <div><div style="font-weight:600">TÜBİTAK çağrıları</div><div class="tiny muted">Her gün 06:00<br>Son tarama: [tarih] · 2 yeni</div></div>
              <label class="check disabled"><input type="checkbox" checked disabled> Açık</label>
            </div>
            <div class="scan-item">
              <div><div style="font-weight:600">[Diğer kaynak sitesi]</div><div class="tiny muted">Haftalık, pazartesi<br>Henüz taranmadı</div></div>
              <label class="check disabled"><input type="checkbox" disabled> Açık</label>
            </div>
            <span class="link-btn">+ Kaynak ekle</span>
          </div>

          <div class="card card-pad">
            <h3 style="font-size:17px;font-weight:600">Onay bekleyenler (2)</h3>
            <p class="small muted">Taramada bulunan yeni ilanlar</p>
            ${[
              ["Sürdürülebilir Kimyasal Süreçler için Yeni Nesil Kataliz Yöntemleri", "TÜBİTAK 1003 · Son başvuru 20.11.2026"],
              ["Tarımda Yapay Zekâ Destekli Uzaktan Algılama ile Hassas Tarım", "TÜBİTAK 1001 · Son başvuru 12.11.2026"],
            ].map(([t, s]) => `
              <div class="scan-item" style="flex-direction:column;gap:10px">
                <div><div style="font-weight:600">${t}</div><div class="tiny muted">${s}</div></div>
                <div style="display:flex;gap:10px;width:100%">
                  <button class="btn btn-primary" style="flex:1" disabled>Onayla</button>
                  <button class="btn btn-outline" style="flex:1" disabled>Düzenle</button>
                </div>
              </div>`).join("")}
          </div>
        </div>
      </div>
    </div>`;
}
