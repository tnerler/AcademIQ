import { sohbet, cvPdfUrl } from "../api.js";
import { CONFIG } from "../config.js";
import { esc, icon, displayName, fullName, shortUni, shortBolum, openPdfModal, toast } from "../ui.js";
import { setSohbetResult } from "./eslestir.js";

// Asistan: ilan metni, alan araması ("computer vision çalışmış hoca") ya da bir hoca hakkında soru.
// Eşleşme dönen yanıtlar Eşleştir sayfasının sonuç listesine yazılır; hoca yanıtları balonun içinde kalır.

export const title = "Asistan";

const CHAT_KEY = "academiq.sohbet";
const CHAT_GECMIS = 6; // backend'e bağlam olarak giden son mesaj sayısı

const ORNEKLER = [
  "Bilgisayarlı görü alanında çalışmış hocaları getir",
  "Erkan Kıyak'ın deneyimlerini göster",
  "Makine öğrenmesiyle kestirimci bakım konusunda kim çalışıyor?",
];

// Durum modül seviyesinde tutulur: sayfadan çıkıp dönünce (ya da istek sürerken) kaybolmaz.
const state = {
  mesajlar: restoreChat(), // { rol, metin, tur?, hoca?, adaylar?, eslesme?: boolean, hata?: boolean }
  taslak: "",
  busy: false,
  startedAt: 0,
  controller: null,
};

let root = null;
let chatTicker = null;

function restoreChat() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(CHAT_KEY) ?? "[]");
    return Array.isArray(saved) ? saved : [];
  } catch {
    return [];
  }
}

function saveChat() {
  try {
    sessionStorage.setItem(CHAT_KEY, JSON.stringify(state.mesajlar));
  } catch {
    /* depolama kapalı; sadece bellekte kalır */
  }
}

export function render(el) {
  root = el;
  el.innerHTML = `
    <div class="page asistan-page">
      <h1 class="page-title">Asistan</h1>
      <section class="card chat asistan-chat" id="chat" aria-label="Asistan"></section>
    </div>`;
  renderChat();
  if (state.busy) startChatTicker();
  root.querySelector("#chat-text")?.focus();
  return () => {
    root = null;
    clearInterval(chatTicker);
    chatTicker = null;
  };
}

function startChatTicker() {
  clearInterval(chatTicker);
  chatTicker = setInterval(() => {
    const el = root?.querySelector("#chat-status");
    if (el) el.innerHTML = chatStatus();
  }, 500);
}

function renderChat() {
  const box = root?.querySelector("#chat");
  if (!box) return;
  const { mesajlar, busy, taslak } = state;

  box.innerHTML = `
    <header class="chat-head">
      <span class="chat-avatar">${icon("chat")}</span>
      <div style="flex:1;min-width:0">
        <b>Asistan</b>
        <div class="tiny muted">İlan yapıştırın, bir alan sorun ya da bir hocayı sorun</div>
      </div>
      ${mesajlar.length && !busy ? `<button class="icon-btn" id="chat-clear" title="Sohbeti temizle" aria-label="Sohbeti temizle">${icon("trash")}</button>` : ""}
    </header>
    <div class="chat-log" id="chat-log" aria-live="polite">
      ${mesajlar.length ? mesajlar.map(bubble).join("") : chatWelcome()}
      ${busy ? `<div class="msg bot typing"><span class="spinner dark"></span>
        <span id="chat-status">${chatStatus()}</span>
        <button class="link-btn" id="chat-cancel">İptal</button></div>` : ""}
    </div>
    <form class="chat-input" id="chat-form">
      <textarea id="chat-text" rows="1" aria-label="Mesaj" ${busy ? "disabled" : ""}
        placeholder="${busy ? "Yanıt bekleniyor…" : "Mesajınızı yazın ya da ilan metnini yapıştırın…"}">${esc(taslak)}</textarea>
      <button class="chat-send" type="submit" aria-label="Gönder" ${busy || !taslak.trim() ? "disabled" : ""}>${icon("send")}</button>
    </form>
    <div class="tiny muted chat-foot" id="chat-foot">${chatFoot()}</div>`;

  const log = box.querySelector("#chat-log");
  log.scrollTop = log.scrollHeight;

  const text = box.querySelector("#chat-text");
  autoGrow(text);
  // Yazarken kutu yeniden çizilmez (odak kaybolmasın); yalnızca gönder düğmesi ve sayaç güncellenir.
  text.addEventListener("input", () => {
    state.taslak = text.value;
    autoGrow(text);
    box.querySelector(".chat-send").disabled = !text.value.trim();
    box.querySelector("#chat-foot").innerHTML = chatFoot();
  });
  text.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      send(text.value);
    }
  });
  box.querySelector("#chat-form").addEventListener("submit", (e) => {
    e.preventDefault();
    send(text.value);
  });
  box.querySelector("#chat-clear")?.addEventListener("click", () => {
    state.mesajlar = [];
    saveChat();
    renderChat();
  });
  box.querySelector("#chat-cancel")?.addEventListener("click", () => state.controller?.abort());
  box.querySelectorAll("[data-ornek]").forEach((b) => b.addEventListener("click", () => send(b.dataset.ornek)));
  box.querySelectorAll("[data-aday]").forEach((b) => b.addEventListener("click", () => send(b.dataset.aday)));
  box.querySelectorAll("[data-cv]").forEach((b) => b.addEventListener("click", () =>
    openPdfModal(`${b.dataset.ad} · CV`, cvPdfUrl(b.dataset.cv))));
}

function chatWelcome() {
  return `
    <div class="msg bot">
      <p>Merhaba! Size şunlarda yardımcı olabilirim:</p>
      <ul>
        <li>Bir <b>proje ilanı metnini</b> yapıştırın, en uygun hocaları bulayım.</li>
        <li>Bir <b>alan</b> sorun, o alanda çalışmış hocaları listeleyeyim.</li>
        <li>Bir <b>hocanın adını</b> verin, deneyim, yayın ve projelerini göstereyim.</li>
      </ul>
    </div>
    <div class="chat-ornekler">
      ${ORNEKLER.map((o) => `<button class="chip sm" data-ornek="${esc(o)}">${esc(o)}</button>`).join("")}
    </div>`;
}

function bubble(m) {
  if (m.rol === "kullanici") {
    // Uzun yapıştırılmış ilanlar balonda kısaltılır
    const kisa = m.metin.length > 280 ? `${m.metin.slice(0, 280)}…` : m.metin;
    return `<div class="msg user">${esc(kisa).replace(/\n/g, "<br>")}</div>`;
  }
  const h = m.hoca;
  return `
    <div class="msg bot ${m.hata ? "err" : ""}">
      ${md(m.metin)}
      ${h ? `
        <div class="chat-hoca">
          <div style="min-width:0">
            <a href="#/cvler/${encodeURIComponent(h.id)}">${esc(fullName(h))}</a>
            <div class="tiny muted">${esc([shortUni(h.universite), shortBolum(h.bolum)].filter(Boolean).join(" · "))}</div>
          </div>
          <button class="link-btn" data-cv="${esc(h.id)}" data-ad="${esc(fullName(h))}">CV'yi aç</button>
        </div>` : ""}
      ${m.adaylar?.length ? `<div class="chips" style="margin-top:8px">${m.adaylar.map((a) =>
        `<button class="chip sm" data-aday="${esc(displayName(a.ad_soyad))}" title="${esc(shortBolum(a.bolum))}">${esc(fullName(a))}</button>`).join("")}</div>` : ""}
      ${m.eslesme ? `<a class="link-btn chat-go" href="#/eslestir">Sonuçları Eşleştir sayfasında gör ${icon("arrow")}</a>` : ""}
    </div>`;
}

// Asistan yanıtı için sade Markdown: paragraflar, "- " maddeleri (girintili alt maddeler) ve **kalın**.
function md(text) {
  const inline = (t) => esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
  const out = [];
  let list = null;
  for (const raw of String(text ?? "").split("\n")) {
    const item = raw.match(/^(\s*)[-*•]\s+(.*)$/);
    if (item) {
      if (!list) out.push((list = []));
      list.push(`<li${item[1].length >= 2 ? ' class="sub"' : ""}>${inline(item[2])}</li>`);
    } else if (raw.trim()) {
      list = null;
      out.push(`<p>${inline(raw.trim())}</p>`);
    } else {
      list = null;
    }
  }
  return out.map((x) => (Array.isArray(x) ? `<ul>${x.join("")}</ul>` : x)).join("");
}

function chatStatus() {
  const sn = Math.floor((Date.now() - state.startedAt) / 1000);
  return sn < 4 ? "Düşünüyor…" : `Aranıyor… ${sn} sn <span class="muted">(eşleştirme 10–15 sn sürebilir)</span>`;
}

function chatFoot() {
  const len = state.taslak.trim().length;
  const max = CONFIG.MAX_METIN_LENGTH;
  if (len > max) return `<span class="over">${len.toLocaleString("tr-TR")} / ${max.toLocaleString("tr-TR")} karakter · ${(len - max).toLocaleString("tr-TR")} fazla</span>`;
  if (len > 200) return `${len.toLocaleString("tr-TR")} / ${max.toLocaleString("tr-TR")} karakter`;
  return "Enter: gönder · Shift+Enter: yeni satır";
}

function autoGrow(el) {
  el.style.height = "auto";
  const h = el.scrollHeight + el.offsetHeight - el.clientHeight; // kenarlıklar dahil
  el.style.height = `${Math.min(h, 180)}px`;
  el.style.overflowY = h > 180 ? "auto" : "hidden";
}

async function send(raw) {
  const mesaj = String(raw ?? "").trim();
  if (!mesaj || state.busy) return;
  if (mesaj.length > CONFIG.MAX_METIN_LENGTH) {
    toast(`Mesaj en fazla ${CONFIG.MAX_METIN_LENGTH.toLocaleString("tr-TR")} karakter olabilir.`);
    return;
  }
  const chat = state;
  const gecmis = chat.mesajlar.filter((m) => !m.hata).slice(-CHAT_GECMIS).map(({ rol, metin }) => ({ rol, metin }));
  chat.mesajlar.push({ rol: "kullanici", metin: mesaj });
  Object.assign(chat, { taslak: "", busy: true, startedAt: Date.now(), controller: new AbortController() });
  renderChat();
  startChatTicker();

  try {
    const y = await sohbet(mesaj, gecmis, { signal: chat.controller.signal });
    chat.mesajlar.push({ rol: "asistan", metin: y.metin, tur: y.tur, hoca: y.hoca, adaylar: y.adaylar, eslesme: !!y.eslesme });
    if (y.eslesme) setSohbetResult(y.eslesme, mesaj);
  } catch (err) {
    chat.mesajlar.push({
      rol: "asistan", hata: true,
      metin: err.name === "AbortError" ? "İstek iptal edildi." : `Yanıt alınamadı. ${err.message ?? ""}`,
    });
  } finally {
    Object.assign(chat, { busy: false, controller: null });
    clearInterval(chatTicker);
    chatTicker = null;
    saveChat();
    renderChat();
    root?.querySelector("#chat-text")?.focus();
  }
}
