// Echoes of Fate - browser client. All AI text is inserted with textContent (no HTML injection).
const $ = (id) => document.getElementById(id);
let game = null;
let busy = false;
let lastInventory = [];

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = text;
  return e;
}

async function api(path, body) {
  let res;
  try {
    res = await fetch(path, {
      method: body ? "POST" : "GET",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new Error("Can't reach the game server. Is `python app.py` still running?");
  }
  let data = {};
  try { data = await res.json(); } catch { /* non-JSON */ }
  if (!res.ok) throw new Error(data.error || `Server error (${res.status})`);
  return data;
}

// ---------------- narrator status badge ----------------
api("/api/status").then((s) => {
  const b = $("ai-badge");
  if (s.enabled) { b.textContent = `AI narrator: ${s.provider} · ${s.model}`; b.className = "badge live"; }
  else { b.textContent = `Offline narrator (${s.reason})`; b.className = "badge offline"; }
}).catch(() => { $("ai-badge").textContent = "server offline"; });

// ---------------- setup ----------------
document.querySelectorAll('input[name="setting"]').forEach((r) =>
  r.addEventListener("change", () => {
    const custom = document.querySelector('input[name="setting"]:checked').value === "custom";
    $("custom-setting").classList.toggle("hidden", !custom);
    if (custom) $("custom-setting").focus();
  }));

$("setup-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (busy) return;
  const hero = $("hero").value.trim();
  const setting = document.querySelector('input[name="setting"]:checked')?.value;
  const custom = $("custom-setting").value.trim();
  // quick client-side checks (server validates again)
  if (!hero) return showSetupError("Please enter a name for your hero.");
  if (setting === "custom" && custom.length < 5) return showSetupError("Describe your custom world (at least 5 characters).");
  showSetupError("");
  setBusy(true, "The narrator is imagining your world…", $("start-btn"));
  $("start-btn").textContent = "Creating your world…";
  try {
    const data = await api("/api/new", {
      hero,
      archetype: document.querySelector('input[name="archetype"]:checked')?.value,
      setting, custom_setting: custom,
    });
    startGame(data);
  } catch (err) {
    showSetupError(err.message);
  } finally {
    setBusy(false, null, $("start-btn"));
    $("start-btn").textContent = "Begin the adventure";
  }
});

function showSetupError(msg) { $("setup-error").textContent = msg; }

function startGame(data) {
  game = data;
  lastInventory = [];
  $("story").innerHTML = "";
  $("ending").classList.add("hidden");
  $("controls").classList.remove("hidden");
  $("setup").classList.remove("active");
  $("play").classList.add("active");
  render(data);
}

// ---------------- play ----------------
async function act(payload) {
  if (busy || !game) return;
  $("play-error").textContent = "";
  setBusy(true, "Rolling the dice… the narrator is writing your fate…");
  try {
    const data = await api("/api/act", { game_id: game.id, ...payload });
    game = data;
    $("custom-action").value = "";
    render(data);
  } catch (err) {
    $("play-error").textContent = err.message;
  } finally {
    setBusy(false);
  }
}

$("custom-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = $("custom-action").value.trim();
  if (text.length < 3) { $("play-error").textContent = "Type a little more - what does your hero do?"; return; }
  act({ custom_action: text });
});

$("restart").addEventListener("click", () => {
  game = null;
  $("play").classList.remove("active");
  $("setup").classList.add("active");
  window.scrollTo({ top: 0, behavior: "smooth" });
});

let diceTimer = null;
function setBusy(on, text, btn) {
  busy = on;
  document.querySelectorAll(".choice, #custom-form button, #custom-action").forEach((b) => (b.disabled = on));
  if (btn) btn.disabled = on;
  const t = $("thinking");
  if (on && game) {
    $("thinking-text").textContent = text || "The narrator is writing…";
    t.classList.remove("hidden");
    $("controls").classList.add("hidden");
    diceTimer = setInterval(() => ($("d20").textContent = 1 + Math.floor(Math.random() * 20)), 90);
    t.scrollIntoView({ behavior: "smooth", block: "center" });
  } else {
    t.classList.add("hidden");
    clearInterval(diceTimer);
    if (game && game.status === "playing") $("controls").classList.remove("hidden");
  }
}

// ---------------- rendering ----------------
function render(g) {
  $("story-title").textContent = g.story_title;
  $("quest").textContent = g.quest;
  $("health-val").textContent = g.health;
  $("progress-val").textContent = g.progress;
  $("health-bar").style.width = g.health + "%";
  $("progress-bar").style.width = g.progress + "%";
  $("turn-val").textContent = `${g.turn} / ${g.max_turns}`;

  const inv = $("inventory");
  inv.innerHTML = "";
  if (!g.inventory.length) inv.appendChild(el("li", "", "empty"));
  g.inventory.forEach((it) => inv.appendChild(el("li", lastInventory.includes(it) ? "" : "new", it)));
  lastInventory = [...g.inventory];

  // story log: dim previous scenes, append the newest
  document.querySelectorAll(".scene").forEach((s) => s.classList.add("old"));
  $("story").appendChild(sceneCard(g.latest));

  // notices (AI fallback etc.)
  const n = $("notice");
  if (g.notices && g.notices.length) { n.textContent = g.notices.join(" "); n.classList.remove("hidden"); }
  else n.classList.add("hidden");

  // choices
  const box = $("choices");
  box.innerHTML = "";
  g.choices.forEach((c, i) => {
    const b = el("button", "choice");
    b.type = "button";
    b.appendChild(el("span", "", `${i + 1}. ${c.text}`));
    b.appendChild(el("span", `risk ${c.risk}`, `${c.risk} risk`));
    b.addEventListener("click", () => act({ choice: i }));
    box.appendChild(b);
  });

  renderBehindTheScenes(g);

  if (g.status === "ended") showEnding(g);
  else setTimeout(() => $("story").lastElementChild.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
}

function sceneCard(s) {
  const card = el("article", "scene");
  if (s.action) {
    const line = el("div", "action-line");
    line.appendChild(el("span", "", "You:"));
    line.appendChild(el("q", "", s.action));
    const r = s.roll;
    line.appendChild(el("span", `tag ${r.outcome}`,
      r.forced ? `${r.outcome} (rule-breaking action)` : `d20 = ${r.value} · needed ${r.needed}+ · ${r.outcome}`));
    card.appendChild(line);
  }
  card.appendChild(el("h3", "", s.chapter_title));
  card.appendChild(el("div", "narr", s.narrative));
  const d = s.applied, deltas = el("div", "deltas");
  if (d.health) deltas.appendChild(el("span", `delta ${d.health > 0 ? "pos" : "neg"}`, `${d.health > 0 ? "+" : ""}${d.health} health`));
  if (d.progress) deltas.appendChild(el("span", `delta ${d.progress > 0 ? "pos" : "neg"}`, `${d.progress > 0 ? "+" : ""}${d.progress} quest progress`));
  d.added.forEach((it) => deltas.appendChild(el("span", "delta item", `+ ${it}`)));
  d.removed.forEach((it) => deltas.appendChild(el("span", "delta neg", `- ${it}`)));
  if (deltas.childElementCount) card.appendChild(deltas);
  return card;
}

function renderBehindTheScenes(g) {
  const body = $("bts-body");
  body.innerHTML = "";
  const table = el("table");
  g.ai_calls_summary.forEach((c, i) => {
    const tr = el("tr");
    tr.appendChild(el("td", "", `#${i + 1} ${c.kind}`));
    tr.appendChild(el("td", "", c.source === "ai" ? `AI · ${c.model}` : "offline"));
    tr.appendChild(el("td", "", c.source === "ai" ? `${c.latency_ms} ms` : (c.error ? "fallback" : "")));
    table.appendChild(tr);
  });
  body.appendChild(table);
  const last = g.last_ai_call;
  if (last) {
    body.appendChild(el("p", "muted", `Latest call: ${last.kind}${last.error ? " - error: " + last.error : ""}`));
    body.appendChild(el("strong", "", "Prompt sent to the model"));
    body.appendChild(el("pre", "", last.prompt));
    body.appendChild(el("strong", "", "Raw model reply"));
    body.appendChild(el("pre", "", last.raw || "(offline narrator - no model reply)"));
  }
}

function showEnding(g) {
  $("controls").classList.add("hidden");
  const tag = $("ending-tag");
  const labels = { victory: "Victory", defeat: "Defeat", bittersweet: "Bittersweet ending", lost: "Quest failed" };
  tag.textContent = labels[g.ending_type] || g.ending_type;
  tag.className = `ending-tag ${g.ending_type}`;
  $("ending-title").textContent = g.ending.ending_title;
  $("ending-text").textContent = g.ending.epilogue;
  $("ending-legacy").textContent = g.ending.legacy ? `“${g.ending.legacy}”` : "";
  $("transcript-link").href = `/api/transcript/${g.id}`;
  $("ending").classList.remove("hidden");
  setTimeout(() => $("ending").scrollIntoView({ behavior: "smooth", block: "start" }), 60);
}

// keyboard shortcuts: 1/2/3 pick a choice when not typing
document.addEventListener("keydown", (e) => {
  if (!game || game.status !== "playing" || busy || document.activeElement.tagName === "INPUT") return;
  const n = parseInt(e.key, 10);
  if (n >= 1 && n <= game.choices.length) act({ choice: n - 1 });
});
