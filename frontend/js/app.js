// Hash tabanlı basit yönlendirici: #/cvler, #/cvler/H036_Ebru_Isik, #/eslestir ...
// Her sayfa modülü { title, render(el, params) -> cleanup?, update?(params) } dışa aktarır.

import { CONFIG, setUseMock } from "./config.js";
import { icon, esc, closeModal } from "./ui.js";
import * as home from "./pages/home.js";
import * as cvler from "./pages/cvler.js";
import * as eslestir from "./pages/eslestir.js";
import * as asistan from "./pages/asistan.js";
import * as cvYukle from "./pages/cv-yukle.js";
import * as ilanlar from "./pages/ilanlar.js";
import * as ilanEkle from "./pages/ilan-ekle.js";
import * as banaUygun from "./pages/bana-uygun.js";

const routes = {
  home,
  cvler,
  eslestir,
  asistan,
  "cv-yukle": cvYukle,
  ilanlar,
  "ilan-ekle": ilanEkle,
  "bana-uygun": banaUygun,
};

const app = document.getElementById("app");
const sidebar = document.getElementById("sidebar");
const menuToggle = document.getElementById("menu-toggle");

let current = { name: null, cleanup: null };

function parseHash() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  const name = parts[0] || "home";
  return { name, params: parts.slice(1) };
}

async function navigate() {
  const { name, params } = parseHash();
  const page = routes[name];

  closeModal();
  sidebar.classList.remove("open");
  menuToggle.setAttribute("aria-expanded", "false");

  if (!page) {
    location.replace("#/");
    return;
  }

  // Aynı sayfada sadece parametre değiştiyse (ör. CV seçimi) yeniden çizmeden güncelle.
  if (current.name === name && page.update) {
    page.update(params);
    return;
  }

  current.cleanup?.();
  current = { name, cleanup: null };

  document.querySelectorAll(".nav-link").forEach((a) => {
    a.classList.toggle("active", a.dataset.route === name);
    if (a.dataset.route === name) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  document.title = page.title ? `${page.title} · AcademIQ` : "AcademIQ";

  app.innerHTML = "";
  window.scrollTo(0, 0);
  const cleanup = await page.render(app, params);
  if (current.name === name) current.cleanup = typeof cleanup === "function" ? cleanup : null;
}

function initSidebar() {
  document.querySelectorAll(".nav-link").forEach((a) => {
    a.insertAdjacentHTML("afterbegin", icon(a.dataset.icon));
    if (a.hasAttribute("data-passive")) {
      a.insertAdjacentHTML("beforeend", `<span class="soon">Yakında</span>`);
      a.title = "Önizleme: bu modül demo aşamasında işlevsiz";
    }
  });

  menuToggle.addEventListener("click", () => {
    const open = sidebar.classList.toggle("open");
    menuToggle.setAttribute("aria-expanded", String(open));
  });

  const badge = document.getElementById("mode-badge");
  const label = CONFIG.USE_MOCK ? "Mock veri" : "Canlı API";
  const other = CONFIG.USE_MOCK ? "canlı API'ye" : "mock veriye";
  badge.innerHTML = `<button class="mode-pill ${CONFIG.USE_MOCK ? "" : "real"}" title="Tıklayınca ${other} geçer">
    <i></i>${esc(label)}</button>`;
  badge.querySelector("button").addEventListener("click", () => setUseMock(!CONFIG.USE_MOCK));
}

// Tema: index.html'deki script ilk temayı uygular; burada düğme ve değişiklikler yönetilir.
const TEMA_KEY = "academiq-tema";
const themeToggle = document.getElementById("theme-toggle");
const sistemKaranlik = matchMedia("(prefers-color-scheme: dark)");

function kayitliTema() {
  try { return localStorage.getItem(TEMA_KEY); } catch { return null; }
}

function temaUygula(tema, animasyon = true) {
  const root = document.documentElement;
  if (animasyon) {
    root.classList.add("theme-anim");
    clearTimeout(temaUygula.t);
    temaUygula.t = setTimeout(() => root.classList.remove("theme-anim"), 250);
  }
  root.dataset.theme = tema;
  const karanlik = tema === "dark";
  const label = karanlik ? "Aydınlık moda geç" : "Karanlık moda geç";
  themeToggle.innerHTML = icon(karanlik ? "sun" : "moon");
  themeToggle.setAttribute("aria-label", label);
  themeToggle.title = label;
}

function initTheme() {
  temaUygula(document.documentElement.dataset.theme === "dark" ? "dark" : "light", false);
  themeToggle.addEventListener("click", () => {
    const yeni = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    try { localStorage.setItem(TEMA_KEY, yeni); } catch { /* gizli pencere: yalnızca bu oturum */ }
    temaUygula(yeni);
  });
  // Kullanıcı seçim yapmadıysa sistem tercihini izlemeye devam et
  sistemKaranlik.addEventListener("change", (e) => {
    if (!["light", "dark"].includes(kayitliTema())) temaUygula(e.matches ? "dark" : "light");
  });
}

initTheme();
initSidebar();
window.addEventListener("hashchange", navigate);
navigate();
