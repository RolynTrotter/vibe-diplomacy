"use strict";

// Power colours (approx. the diplomacy engine map palette) for the scoreboard.
const POWER_COLORS = {
  AUSTRIA: "#c48f3f", ENGLAND: "#7b53a6", FRANCE: "#4f7fd6", GERMANY: "#6b6b6b",
  ITALY: "#4aa05a", RUSSIA: "#cfd2d8", TURKEY: "#d8b13a",
};
const POWERS = Object.keys(POWER_COLORS);

const el = (id) => document.getElementById(id);
const gameSelect = el("game-select");
const mapImg = el("map-img");
const textView = el("text-view");
const talkView = el("talk-view");
const statusEl = el("status");
const scoreboard = el("scoreboard");
const phaseBar = document.querySelector(".phase-bar");
const range = el("phase-range");
const phaseLabel = el("phase-label");
const prevBtn = el("prev");
const nextBtn = el("next");
const powerPicker = el("power-picker");
const thread = el("thread");

let meta = null;        // current game's meta.json
let index = 0;          // current phase index
let mode = "map";       // "map" | "text" | "talk"
let pair = [];          // selected powers for the talk view (max 2)
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
  meta.messages = meta.messages || [];
  preloaded.clear();
  pair = [];
  range.max = String(meta.phases.length - 1);
  index = meta.phases.length - 1; // open on the latest phase
  range.value = String(index);
  el("src-link").innerHTML =
    `· <a href="https://github.com/RolynTrotter/vibe-diplomacy/tree/game/${name}">source</a>`;
  buildPowerPicker();
  render();
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
  if (!powers.length) html += `<p class="none">No orders this phase.</p>`;
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

// ---- Talk view -----------------------------------------------------------
function buildPowerPicker() {
  powerPicker.innerHTML = "";
  for (const power of POWERS) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "power-btn";
    btn.dataset.power = power;
    btn.innerHTML =
      `<span class="dot" style="background:${POWER_COLORS[power]}"></span>` +
      `<span>${power.slice(0, 3)}</span>`;
    btn.addEventListener("click", () => togglePower(power));
    powerPicker.appendChild(btn);
  }
}

function togglePower(power) {
  const i = pair.indexOf(power);
  if (i >= 0) pair.splice(i, 1);
  else { pair.push(power); if (pair.length > 2) pair.shift(); }
  renderTalk();
}

function escapeHtml(s) {
  return s.replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function messagesForPair() {
  const [a, b] = pair;
  return meta.messages.filter((m) => {
    const cast = m.recipient === "GLOBAL";
    if (pair.length === 1) {
      return m.sender === a || m.recipient === a || (cast && m.sender === a);
    }
    const between = (m.sender === a && m.recipient === b) ||
                    (m.sender === b && m.recipient === a);
    return between || (cast && (m.sender === a || m.sender === b));
  });
}

function renderTalk() {
  // reflect selection state on buttons
  for (const btn of powerPicker.children) {
    const p = btn.dataset.power;
    btn.classList.toggle("sel", pair.includes(p));
    btn.classList.toggle("dim", pair.length === 2 && !pair.includes(p));
  }

  // Messages are revealed only once a game ends.
  if (meta.messages_locked) {
    thread.innerHTML = `<p class="none">🔒 Messages stay private while the game is in progress. They're revealed here for the post-mortem once the game ends.</p>`;
    return;
  }
  if (!pair.length) {
    thread.innerHTML = `<p class="none">Pick a power (and optionally a second) to see their messages.</p>`;
    return;
  }
  if (!meta.messages.length) {
    const msg = meta.complete
      ? "No messages were exchanged in this game."
      : "No messages yet — full-press comms aren't enabled. The buttons are ready for when they are.";
    thread.innerHTML = `<p class="none">${msg}</p>`;
    return;
  }

  const msgs = messagesForPair();
  if (!msgs.length) {
    thread.innerHTML = `<p class="none">No messages between ${pair.join(" & ")}.</p>`;
    return;
  }

  const anchor = pair[0];
  let html = "";
  let lastPhase = null;
  for (const m of msgs) {
    if (m.phase !== lastPhase) {
      html += `<div class="phase-sep">${m.phase}</div>`;
      lastPhase = m.phase;
    }
    if (m.recipient === "GLOBAL") {
      html += `<div class="bubble cast"><div class="who" style="color:${POWER_COLORS[m.sender]}">${m.sender} → all</div>${escapeHtml(m.body)}</div>`;
    } else {
      const side = m.sender === anchor ? "right" : "left";
      html += `<div class="bubble ${side}"><div class="who" style="color:${POWER_COLORS[m.sender]}">${m.sender} → ${m.recipient}</div>${escapeHtml(m.body)}</div>`;
    }
  }
  thread.innerHTML = html;
}

// ---- Render dispatch -----------------------------------------------------
function render() {
  if (!meta) return;
  index = Math.max(0, Math.min(index, meta.phases.length - 1));
  const ph = meta.phases[index];
  range.value = String(index);
  phaseLabel.textContent = ph.label;
  prevBtn.disabled = index === 0;
  nextBtn.disabled = index === meta.phases.length - 1;

  const boardMode = mode !== "talk";
  scoreboard.hidden = !boardMode;
  phaseBar.style.display = boardMode ? "" : "none";
  mapImg.hidden = mode !== "map";
  textView.hidden = mode !== "text";
  talkView.hidden = mode !== "talk";
  setStatus("");

  if (mode === "map") {
    renderScoreboard(ph);
    mapImg.src = ph.svg;
    preload(index + 1);
    preload(index - 1);
  } else if (mode === "text") {
    renderScoreboard(ph);
    renderText(ph);
  } else {
    renderTalk();
  }
}

function setMode(next) {
  mode = next;
  el("btn-map").classList.toggle("active", next === "map");
  el("btn-text").classList.toggle("active", next === "text");
  el("btn-talk").classList.toggle("active", next === "talk");
  render();
}

function step(delta) { index += delta; render(); }

gameSelect.addEventListener("change", () => loadGame(gameSelect.value));
range.addEventListener("input", () => { index = Number(range.value); render(); });
prevBtn.addEventListener("click", () => step(-1));
nextBtn.addEventListener("click", () => step(1));
el("btn-map").addEventListener("click", () => setMode("map"));
el("btn-text").addEventListener("click", () => setMode("text"));
el("btn-talk").addEventListener("click", () => setMode("talk"));
document.addEventListener("keydown", (e) => {
  if (mode === "talk") return;
  if (e.key === "ArrowLeft") step(-1);
  if (e.key === "ArrowRight") step(1);
});

loadManifest();
