import { getSampleIlanlar } from "../api.js";
import { esc, deadline, notice, passiveNotice } from "../ui.js";

export const title = "Proje İlanları";

const KAYNAK_BADGE = { "TÜBİTAK": "primary", "Elle yüklendi": "warn", "Diğer site": "muted" };

export function render(el) {
  el.innerHTML = `
    <div class="page">
      <div class="page-head">
        <div>
          <h1 class="page-title">Proje İlanları</h1>
          <p class="page-sub" id="ilan-sub">&nbsp;</p>
        </div>
        <div style="display:flex;gap:10px">
          <button class="btn btn-outline" disabled>Kaynakları tara</button>
          <button class="btn btn-primary" disabled>+ İlan ekle</button>
        </div>
      </div>
      ${passiveNotice("İlanlar henüz indekslenmediği için liste aşağıda örnek veriyle gösteriliyor.")}
      <div inert>
        <div class="filters" style="grid-template-columns:2.4fr 1fr 1fr">
          <label class="field"><span>Ara</span><input class="input" placeholder="Başlık, kurum veya uzmanlık alanı" disabled></label>
          <label class="field"><span>Kaynak</span><select class="select" disabled><option>Tümü</option></select></label>
          <label class="field"><span>Durum</span><select class="select" disabled><option>Başvurusu açık</option></select></label>
        </div>
        <div class="card" style="overflow:hidden">
          <div class="table-wrap">
            <table class="table">
              <thead><tr><th>İlan</th><th class="hide-sm">Kurum / Program</th><th>Kaynak</th><th>Son başvuru</th><th class="hide-sm"></th></tr></thead>
              <tbody id="ilan-rows"><tr><td colspan="5"><div class="skel" style="height:14px"></div></td></tr></tbody>
            </table>
          </div>
        </div>
      </div>
    </div>`;

  getSampleIlanlar()
    .then((ilanlar) => {
      const rows = el.querySelector("#ilan-rows");
      if (!rows) return;
      el.querySelector("#ilan-sub").textContent = `${ilanlar.length} ilan · örnek veri`;
      rows.innerHTML = [...ilanlar]
        .sort((a, b) => a.son_basvuru.localeCompare(b.son_basvuru))
        .map((i) => {
          const d = deadline(i.son_basvuru);
          const left = d.days < 0 ? "Süresi doldu" : d.days === 0 ? "Bugün son gün" : `${d.days} gün kaldı`;
          return `<tr>
            <td style="max-width:420px">
              <div class="cell-title">${esc(i.baslik)}</div>
              <div class="cell-sub">${esc(i.gerekli_uzmanlik.slice(0, 3).join(" · "))}</div>
            </td>
            <td class="hide-sm small">${esc(i.kurum)}</td>
            <td><span class="badge ${KAYNAK_BADGE[i.kaynak] ?? "muted"}">${esc(i.kaynak)}</span></td>
            <td><div style="font-weight:600">${d.text}</div><div class="days-left ${d.days < 7 ? "urgent" : ""}">${left}</div></td>
            <td class="hide-sm"><button class="btn btn-soft" disabled>Eşleştir</button></td>
          </tr>`;
        })
        .join("");
    })
    .catch((err) => {
      const rows = el.querySelector("#ilan-rows");
      if (rows) rows.innerHTML = `<tr><td colspan="5">${notice("err", esc(err.message))}</td></tr>`;
    });
}
