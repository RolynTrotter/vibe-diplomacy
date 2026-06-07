"use strict";

// Power colours (approx. the diplomacy engine map palette) for the scoreboard.
const POWER_COLORS = {
  AUSTRIA: "#c48f3f", ENGLAND: "#7b53a6", FRANCE: "#4f7fd6", GERMANY: "#6b6b6b",
  ITALY: "#4aa05a", RUSSIA: "#cfd2d8", TURKEY: "#d8b13a",
};

const el = (id) => document.getElementById(id);
const gameSelect = el("game-select");
const mapImg = el("map-img");
const textView = el("text-view");
const statusEl = el("status");
const scoreboard = el("scoreboard");
const range = el("phase-range");
const phaseLabel = el("phase-label");
const prevBtn = el("prev");
const nextBtn = el("next");

let meta = null;        // current game's meta.json
let index = 0;          // current phase index
let mode = "map";       // "map" | "text"
const preloaded = new Set();

function setStatus(msg) {
  statusEl.textContent = msg || "";
  statusEl.hidden = !msg;
}

async function loadManifest() {
  setStatus("Loading games…");
  let games;
  try {
    games = await (await fetch("games.json", { cache: "no-cache" })).json();
  } catch (e) {
    setStatus("Could not load games.json");
    return;
  }
  if (!games.length) { setStatus("No games published yet."); return; }

  gameSelect.innerHTML = "";
  for (const g of games) {
    const opt = document.createElement("option");
    opt.value = g.name;
    opt.textContent = `${g.title} (${g.current_phase})`;
    gameSelect.appendChild(opt);
  }
  await loadGame(games[0].name);
}

async function loadGame(name) {
  setStatus("Loading game…");
  try {
    meta = await (await fetch(`games/${name}/meta.json`, { cache: "no-cache" })).json();
  } catch (e) {
    setStatus("Could not load game data."); return;
  }
  preloaded.clear();
  range.max = String(meta.phases.length - 1);
  index = meta.phases.length - 1; // open on the latest phase
  range.value = String(index);
  el("src-link").innerHTML =
    `· <a href="https://github.com/RolynTrotter/vibe-diplomacy/tree/game/${name}">source</a>`;
  showPhase(index);
}

function preload(i) {
  const ph = meta.phases[i];
  if (!ph || preloaded.has(ph.svg)) return;
  preloaded.add(ph.svg);
  const img = new Image();
  img.src = ph.svg;
}

function renderScoreboard(ph) {
  const entries = Object.entries(ph.centers)
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1]);
  scoreboard.innerHTML = "";
  for (const [power, n] of entries) {
    const chip = document.createElement("div");
    chip.className = "sc-chip";
    chip.innerHTML =
      `<span class="dot" style="background:${POWER_COLORS[power] || "#888"}"></span>` +
      `<span>${power.slice(0, 3)}</span><span class="n">${n}</span>`;
    scoreboard.appendChild(chip);
  }
}

function renderText(ph) {
  const powers = Object.keys(ph.orders).sort();
  let html = `<h2>${ph.label}</h2>`;
  if (!powers.length) {
    html += `<p class="none">No orders this phase.</p>`;
  }
  for (const power of powers) {
    const orders = ph.orders[power];
    html += `<div class="power"><h3 style="color:${POWER_COLORS[power] || "#fff"}">${power}</h3>`;
    html += orders.length
      ? "<ul>" + orders.map((o) => `<li>${o}</li>`).join("") + "</ul>"
      : `<p class="none">(none)</p>`;
    html += `</div>`;
  }
  textView.innerHTML = html;
}

function showPhase(i) {
  if (!meta) return;
  index = Math.max(0, Math.min(i, meta.phases.length - 1));
  const ph = meta.phases[index];
  range.value = String(index);
  phaseLabel.textContent = ph.label;
  prevBtn.disabled = index === 0;
  nextBtn.disabled = index === meta.phases.length - 1;

  renderScoreboard(ph);
  if (mode === "map") {
    setStatus("");
    mapImg.hidden = false;
    textView.hidden = true;
    mapImg.src = ph.svg;
  } else {
    mapImg.hidden = true;
    textView.hidden = false;
    setStatus("");
    renderText(ph);
  }
  // Preload neighbours for smooth scrubbing.
  preload(index + 1);
  preload(index - 1);
}

function setMode(next) {
  mode = next;
  el("btn-map").classList.toggle("active", next === "map");
  el("btn-text").classList.toggle("active", next === "text");
  showPhase(index);
}

gameSelect.addEventListener("change", () => loadGame(gameSelect.value));
range.addEventListener("input", () => showPhase(Number(range.value)));
prevBtn.addEventListener("click", () => showPhase(index - 1));
nextBtn.addEventListener("click", () => showPhase(index + 1));
el("btn-map").addEventListener("click", () => setMode("map"));
el("btn-text").addEventListener("click", () => setMode("text"));
document.addEventListener("keydown", (e) => {
  if (e.key === "ArrowLeft") showPhase(index - 1);
  if (e.key === "ArrowRight") showPhase(index + 1);
});

loadManifest();
