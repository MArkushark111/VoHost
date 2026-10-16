// VoHost frontend - rebuilt. No build step.
let TOKEN = localStorage.getItem("vohost_tok") || "";
let SID = localStorage.getItem("vohost_sid") || "";
let CURSRV = null;              // current server metadata (defines loader-aware tabs)
const $ = s => document.querySelector(s);
const H = () => ({ "Content-Type": "application/json", "x-token": TOKEN });
function qs(extra) { let s = SID ? "server_id=" + encodeURIComponent(SID) : ""; if (extra) s += (s ? "&" : "") + extra; return s; }

async function api(path, opts = {}) {
  let url = path;
  if (SID && !path.startsWith("/api/servers") && !path.startsWith("/api/login") && !path.startsWith("/api/setup") && !path.startsWith("/api/me") && !path.startsWith("/api/public") && !path.includes("/public/") && !/server_id=/.test(path)) {
    url = path + (path.includes("?") ? "&" : "?") + "server_id=" + encodeURIComponent(SID);
  }
  const r = await fetch(url, { ...opts, headers: { ...H(), ...(opts.headers || {}) } });
  const ct = r.headers.get("content-type") || "";
  let body = null;
  try { body = ct.includes("json") ? await r.json() : await r.text(); } catch (e) { body = null; }
  if (!r.ok) throw Object.assign(new Error(body && body.detail ? body.detail : ("HTTP " + r.status)), { status: r.status });
  return body;
}

function esc(s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;"); }
function ansi(s) {
  return esc(s).replace(/\x1b\[(\d+)m/g, (m, c) => { const map = { 31: "red", 32: "green", 33: "goldenrod", 36: "cyan", 90: "gray", 0: "inherit" }; return `<span style="color:${map[c] || "inherit"}">`; });
}
const ok = r => r && r.ok !== false;

// ---------- Minecraft legacy formatting (&c &6 &l &k ...) ----------
const MC_COL = { 0: "#000000", 1: "#0000AA", 2: "#00AA00", 3: "#00AAAA", 4: "#AA0000", 5: "#AA00AA", 6: "#FFAA00", 7: "#AAAAAA", 8: "#555555", 9: "#5555FF", a: "#55FF55", b: "#55FFFF", c: "#FF5555", d: "#FF55FF", e: "#FFFF55", f: "#FFFFFF" };
const _MC_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789@#$!?";
function _mcRnd(t) { let o = ""; for (let i = 0; i < t.length; i++) o += t[i] === " " ? " " : _MC_CHARS[Math.floor(Math.random() * _MC_CHARS.length)]; return o; }
setInterval(() => { document.querySelectorAll(".mc-obf").forEach(el => { const t = el.getAttribute("data-t") || ""; el.textContent = _mcRnd(t); }); }, 80);
function mcFmt(str) {
  if (!str) return "";
  const s = String(str);
  const runs = [];
  let txt = "", st = { c: "", b: false, i: false, u: false, s: false, k: false };
  const push = () => { if (txt) { runs.push({ t: txt, st: Object.assign({}, st) }); txt = ""; } };
  const reset = () => ({ c: "", b: false, i: false, u: false, s: false, k: false });
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (ch === "&" || ch === "\u00A7") {
      const cd = (s[i + 1] || "").toLowerCase();
      if (/^[0-9a-f]$/.test(cd)) { push(); st = reset(); st.c = MC_COL[cd]; i++; continue; }
      if (cd === "k") { push(); st.k = true; i++; continue; }
      if (cd === "l") { push(); st.b = true; i++; continue; }
      if (cd === "m") { push(); st.s = true; i++; continue; }
      if (cd === "n") { push(); st.u = true; i++; continue; }
      if (cd === "o") { push(); st.i = true; i++; continue; }
      if (cd === "r") { push(); st = reset(); i++; continue; }
    }
    txt += ch;
  }
  push();
  return runs.map(r => {
    const css = [];
    if (r.st.c) css.push("color:" + r.st.c);
    if (r.st.b) css.push("font-weight:700");
    if (r.st.i) css.push("font-style:italic");
    const dec = []; if (r.st.u) dec.push("underline"); if (r.st.s) dec.push("line-through");
    if (dec.length) css.push("text-decoration:" + dec.join(" "));
    const style = css.length ? ` style="${css.join(";")}"` : "";
    if (r.st.k) return `<span class="mc-obf"${style} data-t="${esc(r.t)}">${_mcRnd(r.t)}</span>`;
    return `<span class="mc"${style}>${esc(r.t)}</span>`;
  }).join("");
}

// ---------- custom UI dialogs (no browser alert/confirm/prompt) ----------
function toast(msg, type) {
  let box = document.getElementById("toasts");
  if (!box) { box = document.createElement("div"); box.id = "toasts"; document.body.appendChild(box); }
  const t = document.createElement("div");
  t.className = "toast " + (type || "info");
  t.textContent = msg;
  box.appendChild(t);
  setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 300); }, type === "error" ? 6000 : 3500);
}
function ask(msg) {
  return new Promise(res => {
    const ov = document.createElement("div"); ov.className = "overlay";
    ov.innerHTML = `<div class="modal" style="max-width:430px"><p style="margin:0 0 14px">${esc(msg)}</p><div class="row"><button class="act ok" data-y="1">Yes</button><button class="act" data-y="0">Cancel</button></div></div>`;
    document.body.appendChild(ov);
    const done = v => { ov.remove(); res(v); };
    ov.querySelector("[data-y='1']").onclick = () => done(true);
    ov.querySelector("[data-y='0']").onclick = () => done(false);
    ov.addEventListener("click", e => { if (e.target === ov) done(false); });
  });
}
function askYN(msg) {
  return new Promise(res => {
    const ov = document.createElement("div"); ov.className = "overlay";
    ov.innerHTML = `<div class="modal" style="max-width:430px"><p style="margin:0 0 14px">${esc(msg)}</p><div class="row"><button class="act ok" data-y="1">Yes</button><button class="act" data-y="0">No</button></div></div>`;
    document.body.appendChild(ov);
    const done = v => { ov.remove(); res(v); };
    ov.querySelector("[data-y='1']").onclick = () => done(true);
    ov.querySelector("[data-y='0']").onclick = () => done(false);
    ov.addEventListener("click", e => { if (e.target === ov) done(false); });
  });
}
function askText(title, def, secret) {
  return new Promise(res => {
    const ov = document.createElement("div"); ov.className = "overlay";
    ov.innerHTML = `<div class="modal" style="max-width:430px"><h3 style="margin:0 0 12px">${esc(title)}</h3><input id="atIn" type="${secret ? "password" : "text"}" value="${esc(def || "")}"><div class="row"><button class="act ok" data-y="1">OK</button><button class="act" data-y="0">Cancel</button></div></div>`;
    document.body.appendChild(ov);
    const inp = ov.querySelector("#atIn"); inp.focus(); inp.select();
    const done = v => { ov.remove(); res(v); };
    ov.querySelector("[data-y='1']").onclick = () => done(inp.value);
    ov.querySelector("[data-y='0']").onclick = () => done(null);
    inp.addEventListener("keydown", e => { if (e.key === "Enter") done(inp.value); });
    ov.addEventListener("click", e => { if (e.target === ov) done(null); });
  });
}

// ---------- navigation ----------
function show(tab) {
  document.querySelectorAll("#nav button").forEach(b => b.classList.toggle("on", b.dataset.t === tab));
  document.querySelectorAll("main section").forEach(sec => sec.classList.toggle("hide", sec.dataset.s !== tab));
  ({
    servers: loadServers, server: () => { loadStatus(); loadDD(); loadSec(); }, options: loadOpts, console: nop,
    log: () => scheduleLog(true), players: loadPlayers, software: loadSw, mods: () => refreshInstBadges(), plugins: () => refreshInstBadges(), files: () => loadFiles(cur), worlds: loadWorlds,
    backups: loadBk, access: loadUsers
  }[tab] || nop)();
  if (tab !== "log") scheduleLog(false);
}
const nop = () => {};
document.querySelectorAll("#nav button").forEach(b => b.onclick = () => show(b.dataset.t));

// loader-aware tab visibility: vanilla -> none; fabric/quilt/forge/neoforge -> mods only; paper/purpur/spigot -> plugins only; arclight/modpack -> both
function setLoaderUI() {
  const l = (CURSRV && CURSRV.loader) || "";
  const mods = ["fabric", "quilt", "forge", "neoforge", "arclight", "modpack"].includes(l);
  const plgs = ["paper", "purpur", "spigot", "arclight", "hytale"].includes(l);
  $("#navMods").style.display = mods ? "" : "none";
  $("#navPlugins").style.display = plgs ? "" : "none";
}

// ---------- auth / setup ----------
async function setupState() { try { const r = await fetch("/api/setup-state"); return r.ok ? (await r.json()).needs_setup : false; } catch (e) { return false; } }

$("#btnLogin").onclick = async () => {
  if (await setupState()) {
    const u = await askText("Create admin - username", "admin"); if (!u) return;
    const p = await askText("Create admin - password (min 4 chars)", "", true); if (!p) return;
    const p2 = await askText("Repeat password", "", true);
    if (p2 === null || p !== p2) { toast("Passwords differ, try again.", "error"); return; }
    const r = await fetch("/api/setup", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: u, password: p }) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { toast("Setup failed: " + (j.detail || r.status), "error"); return; }
    TOKEN = r.headers.get("x-token") || ""; localStorage.setItem("vohost_tok", TOKEN);
    $("#btnLogin").textContent = "Logout"; toast("Admin created - welcome!", "ok"); refreshMe(); loadServers(); return;
  }
  const u = await askText("Username"); if (!u) return;
  const p = await askText("Password", "", true); if (p === null) return;
  const r = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: u, password: p }) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { toast("Login failed: " + (j.detail || r.status), "error"); return; }
  TOKEN = r.headers.get("x-token") || ""; localStorage.setItem("vohost_tok", TOKEN);
  $("#btnLogin").textContent = "Logout"; toast("Logged in as " + u, "ok"); refreshMe(); loadServers();
};
async function refreshMe() { try { const j = await api("/api/me"); const u = j.user; $("#me").textContent = u ? `${u.username} (${u.role})` : ""; $("#btnLogin").textContent = u ? "Logout" : "Login"; } catch (e) { $("#me").textContent = ""; $("#btnLogin").textContent = "Login"; } }

// ---------- servers ----------
async function loadServers() {
  try {
    const j = await api("/api/servers");
    const arr = j.servers || [];
    $("#srvCount").textContent = arr.length ? arr.length + " server(s) - click Manage to open" : "No servers yet. Add one below.";
    $("#srvList").innerHTML = arr.map(s =>
      `<div class="mod"><div><b>${mcFmt(s.name)}</b> <span class="mut">${esc(s.id)} - port ${s.port} - ${s.network_mode.toUpperCase()} - ${s.online ? "ONLINE" : "offline"}</span><br>` +
      `<button class="act" onclick="openSrv('${esc(s.id)}')">Manage</button> ` +
      `<button class="act" onclick="renameSrv('${esc(s.id)}','${esc(s.name)}')">Rename</button> ` +
      `<button class="act danger" onclick="delSrv('${esc(s.id)}')">Delete</button></div></div>`).join("");
    if (!SID && arr.length) { SID = arr[0].id; localStorage.setItem("vohost_sid", SID); }
    if (SID) {
      CURSRV = arr.find(x => x.id === SID) || null;
      $("#srvName").innerHTML = CURSRV ? mcFmt(CURSRV.name || "") : "VoHost";
      $("#srvId").textContent = CURSRV ? CURSRV.id : "select";
      setLoaderUI();
    }
    refreshMe();
  } catch (e) { $("#srvList").textContent = e.message; }
}
window.openSrv = async id => { SID = id; localStorage.setItem("vohost_sid", SID); show("server"); connectWS(); loadStatus(); };
window.renameSrv = async (id, cur) => {
  const nv = await askText("Server name - supports & codes, e.g. &l&cVo&6SM&eP", cur);
  if (nv == null || !nv.trim() || nv === cur) return;
  await api("/api/servers/" + id, { method: "PUT", body: JSON.stringify({ name: nv.trim() }) });
  toast("Server renamed.", "ok"); loadServers();
};
window.delSrv = async id => { if (!(await ask("Delete server " + id + "? (files are kept)"))) return; await api("/api/servers/" + id, { method: "DELETE" }); SID = ""; CURSRV = null; localStorage.removeItem("vohost_sid"); toast("Server deleted.", "ok"); loadServers(); };
$("#nsGo").onclick = async () => {
  try {
    const r = await api("/api/servers", { method: "POST", body: JSON.stringify({ name: $("#nsName").value || "server", network_mode: $("#nsNet").value, memory_max: $("#nsMem").value || "4G" }) });
    $("#nsOut").textContent = r.note || "created";
    SID = r.server.id; localStorage.setItem("vohost_sid", SID); loadServers();
  } catch (e) { $("#nsOut").textContent = e.message; }
};

window.copyIp = id => {
  const el = document.getElementById(id); if (!el) return;
  const v = (el.textContent || "").trim();
  if (!v || v === "-" || v === "fetching..." || v === "fetching WAN...") { toast("Address not available yet.", "error"); return; }
  (navigator.clipboard ? navigator.clipboard.writeText(v) : Promise.reject()).then(() => toast("Copied: " + v, "ok")).catch(() => { const t = document.createElement("textarea"); t.value = v; document.body.appendChild(t); t.select(); document.execCommand("copy"); t.remove(); toast("Copied: " + v, "ok"); });
};
function publicUrl() { return location.origin + "/public/" + SID; }
$("#pubOpen").onclick = () => { if (!SID) return toast("Select a server first.", "error"); window.open(publicUrl(), "_blank"); };
$("#pubCopy").onclick = () => {
  if (!SID) return toast("Select a server first.", "error");
  const u = publicUrl();
  (navigator.clipboard ? navigator.clipboard.writeText(u) : Promise.reject()).then(() => toast("Public link copied", "ok")).catch(() => { const t = document.createElement("textarea"); t.value = u; document.body.appendChild(t); t.select(); document.execCommand("copy"); t.remove(); toast("Public link copied", "ok"); });
  $("#pubUrl").textContent = u;
};
// ---------- server panel ----------
let histCpu = [], histRam = [];
async function loadStatus() {
  if (!SID) { document.querySelector("[data-s='servers']").classList.remove("hide"); show("servers"); return; }
  try {
    const s = await api("/api/status");
    $("#mCpu").textContent = s.cpu + " %"; $("#mRam").textContent = s.ram_pct + " %";
    $("#mOn").textContent = s.online ? "ONLINE" : "OFFLINE"; $("#mTps").textContent = s.tps;
    $("#mMc").textContent = (s.mc_rss_mb ?? "-") + " MB"; $("#mDisk").textContent = (s.disk_pct ?? "-") + " %";
    $("#mNet").textContent = (s.network_mode || "?").toUpperCase(); $("#mPort").textContent = (s.server || {}).port || "?";
    $("#motdCur").innerHTML = mcFmt((s.props || {}).motd || "");
    const soft = s.software || {};
    $("#mSoft").textContent = (soft.loader || "vanilla") + " " + (soft.mc_version || "");
    $("#netSel").value = s.network_mode || "wan";
    const ip = s.ip || {};
    $("#mLan").textContent = ip.lan || "-";
    $("#mWan").textContent = ip.wan || "fetching...";
    const mport = (s.props && s.props["server-port"]) || ((s.server || {}).port) || "25565";
    const host = s.hostname || "";
    let conn = "";
    if (s.network_mode === "lan") conn = ip.lan ? ip.lan + ":" + mport : "fetching...";
    else if (host) conn = host + ":" + mport;
    else conn = ip.wan && ip.wan !== "-" ? ip.wan + ":" + mport : "fetching WAN...";
    $("#mConn").textContent = conn;
    if (CURSRV && (!CURSRV.loader) && soft.loader) { CURSRV.loader = soft.loader; setLoaderUI(); }
    if (CURSRV && soft.mc_version && (!CURSRV.mc_version || CURSRV.mc_version === "latest")) { CURSRV.mc_version = soft.mc_version; }
    histCpu.push(s.cpu); histRam.push(s.ram_pct);
    if (histCpu.length > 60) { histCpu.shift(); histRam.shift(); }
    if (s.mc_rss_mb != null) $("#mMc").textContent = s.mc_rss_mb + " MB";
    drawGraph();
    const bk = await api("/api/backups"); $("#bkBadge").style.display = bk.needs_attention ? "" : "none";
  } catch (e) { if (e.status === 401) { $("#mOn").textContent = "login required"; } }
}
function drawGraph() {
  const c = $("#graph"); if (!c) return;
  const g = c.getContext("2d"); g.clearRect(0, 0, 900, 120);
  const line = (arr, color) => {
    g.strokeStyle = color; g.lineWidth = 2; g.beginPath();
    arr.forEach((v, i) => { const x = i * 15, y = 120 - Math.min(v, 100) * 1.2; i ? g.lineTo(x, y) : g.moveTo(x, y); });
    g.stroke();
  };
  line(histRam, "#cfd3d9"); line(histCpu, "#787e88");
  g.fillStyle = "#787e88"; g.font = "11px system-ui";
  g.fillText("CPU", 6, 14); g.fillStyle = "#cfd3d9"; g.fillText("RAM", 46, 14);
}
document.querySelectorAll("[data-a]").forEach(b => b.onclick = async () => {
  try {
    const r = await api("/api/server/" + b.dataset.a, { method: "POST", body: "{}" });
    if (r && r.crashed) {
      $("#term").innerHTML += "\n" + ansi("[crash] Server exited immediately - reason:\n" + (r.note || "")) + "\n";
      show("console");
    } else if (r && r.note) {
      $("#term").innerHTML += "\n" + ansi("[start] " + r.note) + "\n";
    }
    setTimeout(loadStatus, 1500);
  } catch (e) { toast(e.message, "error"); }
});
$("#btnEula").onclick = async () => { try { await api("/api/eula", { method: "POST", body: JSON.stringify({ accept: true }) }); toast("EULA accepted.", "ok"); } catch (e) { toast(e.message, "error"); } };
$("#netGo").onclick = async () => { await api("/api/servers/" + SID, { method: "PUT", body: JSON.stringify({ network_mode: $("#netSel").value }) }); loadStatus(); };

// ---------- subdomain (DuckDNS) ----------
async function loadDD() {
  if (!SID || !$("#ddDomain")) return;
  try {
    const j = await api("/api/subdomain");
    $("#ddDomain").value = j.domain || "";
    $("#ddToken").placeholder = j.token_set ? "token saved (paste a new one to replace)" : "paste token from duckdns.org";
    const l = j.last || {};
    $("#ddStatus").textContent = l.ts ? ((l.ok ? "OK: " : "FAIL: ") + (l.message || "") + " - " + new Date(l.ts * 1000).toLocaleString()) : "not synced yet";
    $("#ddAddr").textContent = j.hostname ? (j.hostname + ":" + (j.port || "25565")) : "-";
  } catch (e) { $("#ddStatus").textContent = e.message; }
}
const _ddSave = $("#ddSave");
if (_ddSave) _ddSave.onclick = async () => {
  try {
    const body = { domain: $("#ddDomain").value, server_id: SID };
    if ($("#ddToken").value) body.token = $("#ddToken").value;
    const r = await api("/api/subdomain", { method: "PUT", body: JSON.stringify(body) });
    $("#ddToken").value = "";
    const sy = r.sync || {};
    toast(sy.ok ? ("Subdomain live: " + (sy.message || "")) : ("Saved. Sync: " + (sy.message || "failed")), sy.ok ? "ok" : "error");
    loadDD(); loadStatus();
  } catch (e) { toast(e.message, "error"); }
};

// ---------- DDoS / flood protection ----------
async function loadSec() {
  if (!$("#secStatus")) return;
  try {
    const j = await api("/api/security");
    const parts = ["SYN defenses", "connection limits", "SSH limit", "login guard"].filter((_, i) => [j.sysctl, j.chain, j.ufw_ssh, j.login_guard][i]);
    $("#secStatus").textContent = (j.enabled ? "ENABLED" : "disabled") + (j.enabled ? " - active: " + (parts.join(", ") || "applying...") : "")
    + ((j.enabled && j.ufw_active && !j.ssh_allow) ? " - WARNING: SSH not allowed in UFW!" : "");
  } catch (e) { $("#secStatus").textContent = e.message; }
}
const _secOn = $("#secOn"), _secOff = $("#secOff");
if (_secOn) _secOn.onclick = async () => { try { await api("/api/security", { method: "PUT", body: JSON.stringify({ enabled: true }) }); toast("Flood protection enabled.", "ok"); } catch (e) { toast(e.message, "error"); } loadSec(); };
if (_secOff) _secOff.onclick = async () => { try { await api("/api/security", { method: "PUT", body: JSON.stringify({ enabled: false }) }); toast("Flood protection disabled.", "ok"); } catch (e) { toast(e.message, "error"); } loadSec(); };
setInterval(() => { if (!document.querySelector("[data-s='server']").classList.contains("hide")) loadStatus(); }, 4000);

// ---------- console / log ----------
let ws = null;
function connectWS() {
  if (ws) { try { ws.close(); } catch (e) {} }
  if (!TOKEN || !SID) return;
  ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/console?token=" + encodeURIComponent(TOKEN) + "&server_id=" + encodeURIComponent(SID));
  ws.onmessage = ev => { const t = $("#term"); t.innerHTML += ansi(ev.data) + "\n"; t.scrollTop = t.scrollHeight; };
  ws.onclose = () => { ws = null; setTimeout(() => { if (!document.querySelector("[data-s='console']").classList.contains("hide")) connectWS(); }, 3000); };
}
connectWS();
$("#sendCmd").onclick = sendCmd;
$("#testRcon").onclick = async () => {
  const t = $("#term");
  t.innerHTML += ansi("[rcon] testing...") + "\n"; t.scrollTop = t.scrollHeight;
  try {
    const j = await api("/api/rcon/diag");
    const L = [
      "target: " + j.target.host + ":" + j.target.port + " (password from " + j.target.password_source + ")",
      "server.properties: enable-rcon=" + (j.props["enable-rcon"] || "?") + " rcon.port=" + (j.props["rcon.port"] || "?") + " game-port=" + (j.props["server-port"] || "?"),
      "tcp rcon-port: " + (j.tcp_rcon.open ? "OPEN" : "CLOSED (" + (j.tcp_rcon.error || "?") + ")"),
      "tcp game-port: " + (j.tcp_game.open ? "OPEN" : "CLOSED"),
      "auth test: " + (j.auth.ok ? "OK (" + (j.auth.out || "").slice(0, 120) + ")" : "FAILED: " + (j.auth.error || "?")),
      "fix: " + j.suggestion,
    ];
    t.innerHTML += ansi(L.join("\n")) + "\n";
  } catch (e) { t.innerHTML += ansi("[rcon] " + e.message) + "\n"; }
  t.scrollTop = t.scrollHeight;
};
$("#cmd").addEventListener("keydown", e => { if (e.key === "Enter") sendCmd(); });
async function sendCmd() {
  const c = $("#cmd").value; if (!c) return;
  try {
    if (ws && ws.readyState === 1) ws.send(JSON.stringify({ command: c }));
    else { const r = await api("/api/server/command", { method: "POST", body: JSON.stringify({ command: c, server_id: SID }) }); $("#term").innerHTML += "\n" + ansi(r.out || r.error || ""); }
  } catch (e) { $("#term").innerHTML += "\n" + ansi("[error] " + e.message); }
  $("#cmd").value = "";
}
// live log: polls while the Log tab is visible and appends new lines without a refresh click
let logTimer = null, logCur = "";
async function loadLog(append) {
  try {
    const txt = ((await api("/api/logs?lines=2000")).log) || "";
    const t = $("#term2"); if (!t) return;
    const appendable = append && logCur && txt.startsWith(logCur);
    if (appendable) {
      const delta = txt.slice(logCur.length);
      if (delta) {
        const nearBottom = t.scrollTop + t.clientHeight >= t.scrollHeight - 50;
        const oldH = t.scrollHeight;
        t.innerHTML += ansi(delta);
        if (nearBottom) t.scrollTop = t.scrollHeight;
        else t.scrollTop += (t.scrollHeight - oldH);
      }
    } else {
      t.innerHTML = ansi(txt);
      t.scrollTop = t.scrollHeight;
    }
    logCur = txt;
  } catch (e) { /* server polling errors are transient */ }
}
function scheduleLog(active) {
  if (active) {
    if (!logTimer) logTimer = setInterval(() => loadLog(true), 2500);
    loadLog(false);
  } else if (logTimer) {
    clearInterval(logTimer); logTimer = null;
  }
}
$("#btnLog").onclick = () => { logCur = ""; loadLog(false); };
$("#btnCrash").onclick = openCrash;
async function openCrash() {
  try {
    const j = await api("/api/crash-reports");
    const reports = j.reports || [];
    const sel = $("#crashPick");
    sel.innerHTML = reports.map(f => `<option value="${esc(f)}">${esc(f)}</option>`).join("");
    if (!reports.length) { $("#crashTitle").textContent = "Crash reports"; $("#crashBody").textContent = "No crash reports found (the server never got far enough to write one, or it started fine)."; return; }
    $("#crashModal").classList.remove("hide");
    await showCrash(reports[0]);
  } catch (e) { toast(e.message, "error"); }
}
async function showCrash(f) {
  try {
    const j = await api("/api/crash-reports?file=" + encodeURIComponent(f));
    $("#crashTitle").textContent = "Crash report - " + j.file;
    $("#crashBody").textContent = j.text;
    $("#crashModal").classList.remove("hide");
  } catch (e) { toast(e.message, "error"); }
}
$("#crashPick").onchange = () => { const f = $("#crashPick").value; if (f) showCrash(f); };
$("#crashClose").onclick = () => $("#crashModal").classList.add("hide");
$("#crashModal").onclick = e => { if (e.target.id === "crashModal") $("#crashModal").classList.add("hide"); };

// ---------- options ----------
async function loadOpts() {
  try {
    const o = await api("/api/options");
    const f = $("#optForm"); f.innerHTML = "";
    const inputs = [["server-name", "text", ""], ["motd", "text", ""], ["max-players", "number", ""],
      ["spawn-protection", "number", ""],
      ["server-port", "number", ""], ["resource-pack", "text", "https://...zip"], ["resource-pack-prompt", "text", "optional text"]];
    inputs.forEach(([k, type, ph]) => {
      f.innerHTML += `<label>${esc(k)}</label><input type="${type}" data-k="${k}" placeholder="${esc(ph)}" value="${esc(o.props[k] || "")}">`;
    });
    const drops = {
      gamemode: [["survival", "Survival"], ["creative", "Creative"], ["adventure", "Adventure"], ["spectator", "Spectator"]],
      difficulty: [["peaceful", "Peaceful"], ["easy", "Easy"], ["normal", "Normal"], ["hard", "Hard"]]
    };
    Object.keys(drops).forEach(k => {
      const cur = o.props[k] || drops[k][0][0];
      f.innerHTML += `<label>${esc(k)}</label><select data-k="${k}">` + drops[k].map(([v, l]) => `<option value="${v}" ${cur === v ? "selected" : ""}>${l}</option>`).join("") + `</select>`;
    });
    const toggles = ["white-list", "allow-flight", "force-gamemode", "pvp", "enable-rcon", "require-resource-pack",
      "keepInventory", "hardcore", "enable-command-block", "spawnMonsters", "spawnAnimals"];
    toggles.forEach(k => {
      const on = (o.props[k] || "false") === "true";
      f.innerHTML += `<div class="tgl"><span>${esc(k)}</span><input type="checkbox" data-k="${k}" style="width:auto" ${on ? "checked" : ""}></div>`;
    });
    const cracked = (o.props["online-mode"] || "true") === "false";
    f.innerHTML += `<div class="tgl" style="border:1px solid var(--warn,#c9a227);border-radius:8px;padding:8px"><span><b>Cracked mode</b> (allow TLauncher / unofficial clients) <span class="mut">- sets online-mode=false + enforce-secure-profile=false so cracked and official (Minecraft) clients join the same server and play together. Note: everyone gets an offline identity (premium players start a fresh inventory), and anyone can join under any name - restart the server after saving.</span></span><input type="checkbox" data-k="cracked-mode" style="width:auto" ${cracked ? "checked" : ""}></div>`;
    f.innerHTML += `<label>Network (WAN public / LAN only)</label><select data-k="_network_mode"><option value="wan" ${o.network_mode === "wan" ? "selected" : ""}>WAN - public</option><option value="lan" ${o.network_mode === "lan" ? "selected" : ""}>LAN - home only</option></select>`;
    $("#optTz").value = o.timezone || "UTC"; $("#optEnv").value = o.env || "";
    window._iconB64 = "";
    $("#optIconPrev").style.display = o.icon ? "" : "none";
    if (o.icon) $("#optIconPrev").src = "data:image/png;base64," + o.icon;
    $("#optIconMsg").textContent = o.icon ? "Current icon shown above (64x64). Pick a new one below or upload." : "No icon yet - upload a 64x64 PNG.";
    $("#optMemMin").value = (o.memory || {}).min || "1G";
    $("#optMemMax").value = (o.memory || {}).max || "4G";
    $("#optCpu").value = o.cpu_cores || 4;
    $("#optPub").checked = !!o.public_page;
    $("#optRestartOn").checked = !!((o.restart || {}).enabled);
    // legacy single-time restarts show in both fields (= stop+start that minute)
    $("#optRestartDown").value = (o.restart || {}).shutdown_at || (o.restart || {}).at || "";
    $("#optRestartUp").value = (o.restart || {}).startup_at || (o.restart || {}).at || "";
    const rl = o.restart_last || {};
    const fmt1 = e => (e.ok ? "ok" : "FAILED") + " (" + (e.note || "") + ")";
    const bits = [];
    if (rl.shutdown) bits.push("shutdown: " + fmt1(rl.shutdown));
    if (rl.startup) bits.push("startup: " + fmt1(rl.startup));
    if (rl.restart) bits.push("restart: " + fmt1(rl.restart));
    $("#optRestartLast").textContent = bits.length ? ("Last scheduled: " + bits.join(" - ")) : "Nothing scheduled has run yet.";
    $("#optServerTime").textContent = "Server time now: " + (o.server_time || "?") + " - schedule must match this clock.";
    loadPush();
  } catch (e) { $("#optForm").textContent = e.message; }
}

// ---------- push limits mode ----------
async function loadPush() {
  if (!SID || !$("#pushStatus")) return;
  try {
    const j = await api("/api/push-limits");
    const t = j.target || {}, m = j.machine || {}, c = j.current || {};
    $("#pushStatus").textContent = j.enabled
      ? `ON - using ${c.max} RAM + ${c.cores} cores (this PC: ${m.ram_total_gb}G RAM, ${m.cores} cores)`
      : `off - now ${c.min}/${c.max} RAM, ${c.cores} cores (would set ${t.memory} RAM + ${t.cores} cores)`;
    $("#pushToggle").textContent = j.enabled ? "Disable push limits" : "Enable push limits";
    window._pushOn = !!j.enabled;
  } catch (e) { $("#pushStatus").textContent = e.message; }
}
const _pushToggle = $("#pushToggle");
if (_pushToggle) _pushToggle.onclick = async () => {
  try {
    const r = await api("/api/push-limits", { method: "POST", body: JSON.stringify({ enabled: !window._pushOn, server_id: SID }) });
    toast(r.note || "done", "ok"); loadOpts();
  } catch (e) { toast(e.message, "error"); }
};
async function restartTest(action) {
  try {
    if (action === "shutdown" && !(await ask("Test shutdown will STOP the server now. Continue?"))) return;
    const r = await api("/api/restart/test", { method: "POST", body: JSON.stringify({ action, server_id: SID }) });
    toast(r.note || "done", r.ok === false ? "error" : "ok"); loadStatus();
  } catch (e) { toast(e.message, "error"); }
}
const _rtDown = $("#optRestartTestDown"), _rtUp = $("#optRestartTestUp");
if (_rtDown) _rtDown.onclick = () => restartTest("shutdown");
if (_rtUp) _rtUp.onclick = () => restartTest("startup");
$("#optIcon").onchange = e => {
  const f = e.target.files[0]; if (!f) return;
  const r = new FileReader();
  r.onload = () => { window._iconB64 = r.result.split(",")[1]; $("#optIconPrev").src = r.result; $("#optIconPrev").style.display = ""; $("#optIconMsg").textContent = "Selected: " + f.name + " - click Upload icon to save it to the server."; };
  r.readAsDataURL(f);
};
$("#optIconUp").onclick = async () => {
  if (!window._iconB64) { $("#optIconMsg").textContent = "Pick a PNG first (64x64)."; return; }
  try { await api("/api/options", { method: "PUT", body: JSON.stringify({ server_id: SID, icon_b64: window._iconB64 }) }); $("#optIconMsg").textContent = "Icon uploaded. Restart the server (or new players will see it on next join)."; }
  catch (e) { $("#optIconMsg").textContent = e.message; }
};
$("#optSave").onclick = async () => {
  const props = {};
  document.querySelectorAll("#optForm [data-k]").forEach(el => { props[el.dataset.k] = el.type === "checkbox" ? String(el.checked) : el.value; });
  const cracked = props["cracked-mode"] === "true";
  delete props["cracked-mode"];
  if ("online-mode" in props) delete props["online-mode"];
  props["online-mode"] = cracked ? "false" : "true";
  props["enforce-secure-profile"] = cracked ? "false" : "true";
  try {
    await api("/api/options", { method: "PUT", body: JSON.stringify({ props, server_id: SID, timezone: $("#optTz").value, env: $("#optEnv").value, icon_b64: window._iconB64 || undefined, curseforge_api_key: $("#optCF").value || undefined, discord_webhook: $("#optDiscord").value || undefined, memory_min: $("#optMemMin").value, memory_max: $("#optMemMax").value, cpu_cores: parseInt($("#optCpu").value || "4", 10), public_page: $("#optPub").checked, restart: { enabled: $("#optRestartOn").checked, shutdown_at: $("#optRestartDown").value, startup_at: $("#optRestartUp").value } }) });
    toast("Saved. Restart the server to apply.", "ok");
  } catch (e) { toast(e.message, "error"); }
};

// ---------- players ----------
$("#plGo").onclick = async () => {
  try {
    const r = await api("/api/players/action", { method: "POST", body: JSON.stringify({ name: $("#plName").value, action: $("#plAct").value, duration: $("#plDur").value, reason: $("#plReason").value, server_id: SID }) });
    $("#plOut").textContent = JSON.stringify(r).slice(0, 200);
  } catch (e) { $("#plOut").textContent = e.message; }
};
async function loadPlayers() {
  loadOnline(); loadSeen(); loadLists();
}
async function loadLists() {
  try {
    const j = await api("/api/players/lists");
    $("#wlToggle").textContent = "Whitelist: " + (j.whitelist_enabled ? "ON" : "off");
    $("#wlList").innerHTML = (j.whitelist || []).length
      ? j.whitelist.map(e => `${esc(e.name || e.uuid || "?")} <button class="act mini danger" onclick="wlRm('${esc(e.name || e.uuid)}')">Remove</button>`).join("<br>")
      : "Whitelist is empty (whitelist " + (j.whitelist_enabled ? "ON - only these can join" : "off - anyone can join") + ").";
    const bans = (j.bans || []).map(e => `${esc(e.name || "?")}${e.reason ? " - " + esc(e.reason) : ""} <button class="act mini danger" onclick="wlUnban('${esc(e.name || e.uuid)}')">Unban</button>`).join("<br>");
    const ips = (j.ban_ips || []).map(e => `${esc(e.ip || "?")} <button class="act mini danger" onclick="wlUnip('${esc(e.ip || "")}')">Unban IP</button>`).join("<br>");
    $("#banList").innerHTML = [bans, ips].filter(Boolean).join("<br>") || "No bans.";
  } catch (e) { $("#wlList").textContent = e.message; }
}
window.wlRm = async n => { try { await api("/api/players/lists", { method: "POST", body: JSON.stringify({ op: "whitelist-remove", name: n, server_id: SID }) }); toast("Removed from whitelist.", "ok"); } catch (e) { toast(e.message, "error"); } loadLists(); loadSeen(); };
window.wlUnban = async n => { try { await api("/api/players/lists", { method: "POST", body: JSON.stringify({ op: "ban-remove", name: n, server_id: SID }) }); toast("Unbanned.", "ok"); } catch (e) { toast(e.message, "error"); } loadLists(); };
window.wlUnip = async n => { try { await api("/api/players/lists", { method: "POST", body: JSON.stringify({ op: "banip-remove", name: n, server_id: SID }) }); toast("IP unbanned.", "ok"); } catch (e) { toast(e.message, "error"); } loadLists(); };
$("#wlAdd").onclick = async () => {
  const n = $("#wlName").value.trim(); if (!n) return toast("Enter a player name.", "error");
  try { const r = await api("/api/players/lists", { method: "POST", body: JSON.stringify({ op: "whitelist-add", name: n, server_id: SID }) }); toast(r.note || "Added to whitelist.", "ok"); }
  catch (e) { toast(e.message, "error"); }
  $("#wlName").value = ""; loadLists();
};
$("#wlRm").onclick = async () => { const n = $("#wlName").value.trim(); if (n) { await wlRm(n); $("#wlName").value = ""; } };
$("#wlToggle").onclick = async () => {
  try {
    const r = await api("/api/players/lists", { method: "POST", body: JSON.stringify({ op: "toggle-whitelist", server_id: SID }) });
    $("#wlToggle").textContent = "Whitelist: " + (r.enabled ? "ON" : "off");
    toast("Whitelist " + (r.enabled ? "enabled" : "disabled") + " (apply takes effect when players re-join or after restart).", "ok");
    loadLists();
  } catch (e) { toast(e.message, "error"); }
};
$("#banGo").onclick = async () => {
  const n = $("#banName").value.trim(); if (!n) return toast("Enter a player or IP.", "error");
  try {
    const r = await api("/api/players/lists", { method: "POST", body: JSON.stringify({ op: $("#banAct").value, name: n, reason: $("#banReason").value, server_id: SID }) });
    if (r.ok) toast(r.note || "Done.", "ok"); else toast(r.error || "Failed.", "error");
  } catch (e) { toast(e.message, "error"); }
  $("#banName").value = ""; loadLists();
};
async function loadOnline() {
  try {
    const j = await api("/api/players/online");
    if (j.error) { $("#plOnline").textContent = j.error; return; }
    $("#plOnline").textContent = (j.online || []).length
      ? "Online: " + j.online.join(", ")
      : "0 players online";
  } catch (e) { $("#plOnline").textContent = "couldn't reach the server (is it online?)"; }
}
async function loadSeen() {
  try {
    const j = await api("/api/players/seen");
    const ps = j.players || [];
    if (!ps.length) { $("#plSeen").textContent = "No players seen yet (join once to appear here)."; return; }
    $("#plSeen").innerHTML = ps.slice(0, 40).map(p => {
      const label = p.name || p.uuid || "?";
      const uuid = p.uuid || "";
      const tag = p["ops.json"] ? " OP" : (p["whitelist.json"] ? " whitelisted" : "");
      return `<button class="act" onclick="plProfile('${esc(label)}','${esc(uuid)}')">${esc(label)}${tag ? `<span class="badge">${tag.trim()}</span>` : ""} - view</button> `;
    }).join("");
  } catch (e) { $("#plSeen").textContent = e.message; }
}
window._plCur = { name: "", uuid: "" };
window.plProfile = async (name, uuid) => {
  if (!uuid) { toast("Player needs a UUID (join the server once)", "error"); return; }
  window._plCur = { name: name || "", uuid };
  $("#plModal").classList.remove("hide");
  $("#plH").textContent = name || uuid;
  $("#plU").textContent = "UUID: " + uuid + " - name from the saved player file.";
  await plRefreshInv();
};
async function plRefreshInv() {
  const { uuid } = window._plCur;
  try {
    const j = await api("/api/players/data?uuid=" + encodeURIComponent(uuid));
    if (!j.uuid) { $("#plInv").textContent = j.error || "no data"; $("#plEnd").innerHTML = ""; return; }
    if (j.name && !window._plCur.name) { window._plCur.name = j.name; $("#plH").textContent = j.name; }
    const row = (it, lst) => `${esc(it.id)} <span class="mut">x${it.Count} slot ${it.Slot}</span> <button class="act mini danger" onclick="plDelItem(${it.Slot},'${lst}')">Delete</button>`;
    $("#plInv").innerHTML = (j.Inventory && j.Inventory.length)
      ? j.Inventory.map(it => row(it, "Inventory")).join("<br>") : '<span class="mut">empty</span>';
    $("#plEnd").innerHTML = (j.EnderItems && j.EnderItems.length)
      ? j.EnderItems.map(it => row(it, "EnderItems")).join("<br>") : '<span class="mut">empty</span>';
  } catch (e) { $("#plInv").textContent = e.message; }
}
window.plDelItem = async (slot, lst) => {
  if (!(await ask("Delete the item in slot " + slot + (lst === "EnderItems" ? " (ender chest)" : "") + "?"))) return;
  const u = window._plCur.uuid;
  try { const r = await api("/api/players/item/delete", { method: "POST", body: JSON.stringify({ uuid: u, slot, list: lst, server_id: SID }) }); toast(r.note || "Deleted.", "ok"); }
  catch (e) { toast(e.message, "error"); }
  plRefreshInv();
};
const plActs = [
  ["op", "OP"], ["deop", "De-OP"], ["kick", "Kick"], ["ban", "Ban"],
  ["tempban", "Temp ban"], ["pardon", "Unban"], ["kill", "Kill"], ["feed", "Feed"]
];
$("#plActs").innerHTML = plActs.map(([a, l]) => `<button class="act" data-a="${a}">${l}</button>`).join("");
document.querySelectorAll("#plActs [data-a]").forEach(b => b.onclick = async () => {
  const { name } = window._plCur;
  if (!name) return toast("Unknown player name - cannot run commands.", "error");
  const body = { name, action: b.dataset.a, server_id: SID };
  if (b.dataset.a === "kick") { const r = await askText("Kick reason", "kicked by VoHost"); if (r === null) return; body.reason = r; }
  if (b.dataset.a === "ban" || b.dataset.a === "tempban") { const r = await askText("Ban reason", "banned by VoHost"); if (r === null) return; body.reason = r; }
  if (b.dataset.a === "tempban") { const d = await askText("Duration (e.g. 7d / 2h / forever)", "7d"); if (!d) return; body.duration = d; }
  try {
    const r = await api("/api/players/action", { method: "POST", body: JSON.stringify(body) });
    if (r.ok) toast(r.out ? (b.dataset.a.toUpperCase() + ": " + r.out) : (b.dataset.a + " done"), "ok");
    else toast(r.error || (b.dataset.a + " failed"), "error");
  } catch (e) { toast(e.message, "error"); }
});
$("#plClearInv").onclick = async () => {
  if (!(await ask("Clear the entire saved inventory of " + (window._plCur.name || window._plCur.uuid) + "?"))) return;
  try { const r = await api("/api/players/item/clear", { method: "POST", body: JSON.stringify({ uuid: window._plCur.uuid, ender: false, server_id: SID }) }); toast(r.note || "Cleared.", "ok"); }
  catch (e) { toast(e.message, "error"); }
  plRefreshInv();
};
$("#plClearEnd").onclick = async () => {
  if (!(await ask("Clear the entire saved ender chest?"))) return;
  try { const r = await api("/api/players/item/clear", { method: "POST", body: JSON.stringify({ uuid: window._plCur.uuid, ender: true, server_id: SID }) }); toast(r.note || "Cleared.", "ok"); }
  catch (e) { toast(e.message, "error"); }
  plRefreshInv();
};
$("#plCl").onclick = () => $("#plModal").classList.add("hide");
$("#plModal").onclick = e => { if (e.target.id === "plModal") $("#plModal").classList.add("hide"); };
document.addEventListener("keydown", e => { if (e.key === "Escape") $("#plModal").classList.add("hide"); });

// ---------- software ----------
async function loadSw() {
  try {
    const l = await api("/api/software/loaders");
    $("#swLoader").innerHTML = l.loaders.map(x => `<option value="${esc(x.id)}">${esc(x.name)}</option>`).join("");
    const mc = await api("/api/software/mc?kind=release");
    $("#swMc").innerHTML = mc.versions.slice(0, 50).map(v => `<option>${esc(v)}</option>`).join("");
    if (CURSRV && CURSRV.loader) $("#swLoader").value = CURSRV.loader;
    if (CURSRV && CURSRV.mc_version) $("#swMc").value = CURSRV.mc_version;
    await loadBuilds();
  } catch (e) { $("#swOut").textContent = e.message; }
}
async function loadBuilds() {
  try {
    const j = await api("/api/software/loader-versions?loader=" + encodeURIComponent($("#swLoader").value) + "&mc=" + encodeURIComponent($("#swMc").value || ""));
    $("#swBuild").innerHTML = (j.versions && j.versions.length ? j.versions : ["latest"]).map(v => `<option>${esc(v)}</option>`).join("");
    $("#swOut").textContent = j.note || "";
  } catch (e) { $("#swOut").textContent = "versions: " + e.message; }
}
$("#swLoader").onchange = loadBuilds; $("#swMc").onchange = loadBuilds;
$("#swInstall").onclick = async () => {
  try {
    const loader = $("#swLoader").value, mc = $("#swMc").value;
    const changed = CURSRV && (CURSRV.loader !== loader || String(CURSRV.mc_version) !== String(mc));
    let wipe = false;
    if (changed) {
      if (await askYN("Back up the world before switching software?")) {
        $("#swOut").textContent = "Backing up the world...";
        const b = await api("/api/backups", { method: "POST", body: JSON.stringify({ label: "pre-switch", server_id: SID }) });
        window.open("/api/backups/download?file=" + encodeURIComponent(b.file) + "&" + qs(), "_blank");
        toast("Backup saved + downloading: " + b.file, "ok");
      }
      if (!(await ask("Switching software will WIPE the server folder (world, mods, jar). Continue?"))) return;
      wipe = true;
      $("#swOut").textContent = "Wiping + installing...";
    }
    const r = await api("/api/software/install", { method: "POST", body: JSON.stringify({ loader, mc_version: mc, loader_version: $("#swBuild").value, accept_eula: $("#swEula").checked, wipe, server_id: SID }) });
    $("#swOut").textContent = r.note;
    if (CURSRV) { CURSRV.loader = loader; CURSRV.mc_version = mc; setLoaderUI(); }
    loadStatus();
  } catch (e) { $("#swOut").textContent = e.message; }
};

// ---------- mods / plugins ----------
let instKind = "mod";
async function refreshInstBadges() {
  if (!SID) return;
  try {
    const m = await api("/api/catalog/installed?kind=mod");
    const p = await api("/api/catalog/installed?kind=plugin");
    $("#modInstBtn").textContent = "Installed mods (" + (m.installed || []).length + ")";
    $("#plgInstBtn").textContent = "Installed plugins (" + (p.installed || []).length + ")";
    window._instFiles = { mod: (m.installed || []).map(x => x.file), plugin: (p.installed || []).map(x => x.file) };
  } catch (e) { /* server not selected yet */ }
}
async function loadInstModal() {
  try {
    const j = await api("/api/catalog/installed?kind=" + instKind);
    const list = j.installed || [];
    $("#instCount").textContent = list.length + " installed in the " + (instKind === "mod" ? "mods" : "plugins") + " folder";
    const f = ($("#instFilter").value || "").toLowerCase();
    const rows = list.filter(m => !f || m.file.toLowerCase().includes(f));
    $("#instList").innerHTML = rows.length
      ? rows.map(m => `<div class="mod"><div><b>${esc(m.file)}</b> <span class="mut">${(m.size / 1048576).toFixed(2)} MB</span>${m.update ? ` <span class="badge" style="cursor:default" title="a newer version exists for your MC version">update: ${esc(m.latest)}</span>` : ""}</div><div>${m.update ? `<button class="act" onclick="updMod('${instKind}','${esc(m.file)}')">Update</button>` : ""}<button class="act danger" onclick="uninst('${instKind}','${esc(m.file)}')">Uninstall</button></div></div>`).join("")
      : (f ? "No installed " + (instKind === "mod" ? "mods" : "plugins") + " match that filter." : "Nothing installed yet.");
  } catch (e) { $("#instList").textContent = e.message; }
}
window.updMod = async (kind, file) => {
  if (!(await ask("Update " + file + " to the newest version compatible with your MC version?"))) return;
  try {
    const r = await api("/api/catalog/update", { method: "POST", body: JSON.stringify({ kind, file, server_id: SID }) });
    toast("Updated - " + (r.note || r.file), "ok");
  } catch (e) { toast(e.message, "error"); }
  loadInstModal(); refreshInstBadges();
};
window.uninst = async (kind, file) => {
  if (!(await ask("Uninstall " + file + "?"))) return;
  try { await api("/api/catalog/uninstall", { method: "POST", body: JSON.stringify({ kind, file, server_id: SID }) }); loadInstModal(); refreshInstBadges(); toast("Removed " + file, "ok"); } catch (e) { toast(e.message, "error"); }
};

function isInstalled(src, id, kind, slug) {
  const just = (window._justInstalled || {})[src + "/" + id];
  if (just) return true;
  const files = ((window._instFiles || {})[kind] || []).map(f => f.toLowerCase());
  if (slug && files.some(f => f.includes(slug.toLowerCase()))) return true;
  return false;
}
function instBtn(src, id, kind, slug) {
  return isInstalled(src, id, kind, slug)
    ? `<button class="act ok" id="ib-${kind}-${id}" disabled style="opacity:.55;cursor:default">Installed</button>`
    : `<button class="act" id="ib-${kind}-${id}" onclick="inst('${esc(src)}','${esc(id)}','${kind}')">Install</button>`;
}
function openInstModal(kind) {
  instKind = kind;
  $("#instModalTitle").textContent = "Installed " + (kind === "mod" ? "Mods" : "Plugins");
  $("#instFilter").value = "";
  $("#instModal").classList.remove("hide");
  loadInstModal();
}
$("#modInstBtn").onclick = () => openInstModal("mod");
$("#plgInstBtn").onclick = () => openInstModal("plugin");
$("#instClose").onclick = () => $("#instModal").classList.add("hide");
$("#instRef").onclick = loadInstModal;
$("#instFilter").oninput = loadInstModal;
$("#instModal").onclick = e => { if (e.target.id === "instModal") $("#instModal").classList.add("hide"); };
document.addEventListener("keydown", e => { if (e.key === "Escape") $("#instModal").classList.add("hide"); });

async function search(into, src, q, kind) {
  try {
    const loader = (CURSRV && CURSRV.loader) || "";
    const mc = (CURSRV && CURSRV.mc_version) || "";
    const j = await api("/api/catalog/search?source=" + encodeURIComponent(src) + "&q=" + encodeURIComponent(q) + "&kind=" + kind + "&mc=" + encodeURIComponent(mc) + "&loader=" + encodeURIComponent(loader));
    const res = j.results || [];
    document.querySelector(into).innerHTML = res.length
      ? res.map(r => `<div class="mod">${r.icon ? `<img src="${esc(r.icon)}">` : `<div class="mut" style="width:48px;height:48px;display:flex;align-items:center;justify-content:center">NA</div>`}<div><b>${esc(r.title)}</b><br><span class="mut">${esc((r.description || "").slice(0, 140))}</span><br>${instBtn(src, r.id, kind, r.slug || "")}</div></div>`).join("")
      : "No results.";
  } catch (e) { document.querySelector(into).textContent = e.message; }
}
window.inst = async (src, id, kind) => {
  try {
    if (!CURSRV || !CURSRV.mc_version) { toast("Open the Server page first so the MC version is known.", "error"); return; }
    toast("Installing latest for MC " + CURSRV.mc_version + "...", "info");
    const r = await api("/api/catalog/install", { method: "POST", body: JSON.stringify({ source: src, kind, project: id, mc: (CURSRV.mc_version || "").toString(), loader: (CURSRV.loader || "").toString(), server_id: SID }) });
    window._justInstalled = window._justInstalled || {};
    window._justInstalled[src + "/" + id] = true;
    const b = document.getElementById("ib-" + kind + "-" + id);
    if (b) b.outerHTML = `<button class="act ok" id="ib-${kind}-${id}" disabled style="opacity:.55;cursor:default">Installed</button>`;
    toast("Installed - " + (r.note || r.file) + ". Restart the server to load it.", "ok");
    refreshInstBadges();
  } catch (e) { toast(e.message, "error"); }
};
$("#modGo").onclick = () => search("#modList", $("#modSrc").value, $("#modQ").value, "mod");
$("#plgGo").onclick = () => search("#plgList", $("#plgSrc").value, $("#plgQ").value, "plugin");
const _vcInstall = $("#vcInstall");
if (_vcInstall) _vcInstall.onclick = async () => {
  try {
    if (!SID) { toast("Select a server first.", "error"); return; }
    $("#vcStatus").textContent = "installing...";
    const r = await api("/api/voicechat/install", { method: "POST", body: JSON.stringify({ server_id: SID }) });
    $("#vcStatus").textContent = r.file || "installed";
    toast(r.note || "Installed.", "ok");
    refreshInstBadges();
  } catch (e) { $("#vcStatus").textContent = e.message; toast(e.message, "error"); }
};

// ---------- files ----------
let cur = "";
async function loadFiles(p) {
  cur = p; $("#fPath").value = p;
  try {
    const j = await api("/api/files?path=" + encodeURIComponent(p));
    const items = j.items || [];
    if (!items.length) { $("#fTable").innerHTML = "<tr><td class='mut'>empty folder</td></tr>"; return; }
    $("#fTable").innerHTML = items.map(i => i.dir
      ? `<tr><td><a href="#" onclick="openFolder('${esc(i.name)}');return false">${esc(i.name)}/</a></td><td>-</td><td><button class="act" onclick="openFolder('${esc(i.name)}')">Open</button> <button class="act danger" onclick="delP('${esc(i.name)}',1)">Delete</button></td></tr>`
      : `<tr><td>${esc(i.name)}</td><td>${(i.size / 1024).toFixed(1)} KB</td><td>${canEdit(i) ? `<button class="act" onclick="editFile('${esc(i.name)}')">Edit</button> ` : ""}<button class="act" onclick="dlFile('${esc(i.name)}')">Download</button> <button class="act danger" onclick="delP('${esc(i.name)}')">Delete</button></td></tr>`).join("");
  } catch (e) { $("#fTable").innerHTML = "<tr><td>" + esc(e.message) + "</td></tr>"; }
}
window.openFolder = n => loadFiles(cur ? cur + "/" + n : n);
window.dlFile = async n => { window.open("/api/files?path=" + encodeURIComponent(cur ? cur + "/" + n : n) + "&" + qs(), "_blank"); };
window.delP = async (n, isDir) => { if (!(await ask(isDir ? "Delete folder " + n + " and EVERYTHING inside it?" : "Delete " + n + "?"))) return; await api("/api/files/delete", { method: "POST", body: JSON.stringify({ path: cur ? cur + "/" + n : n, server_id: SID }) }); loadFiles(cur); };
const EDIT_EXT = /\.(txt|properties|json|yml|yaml|toml|cfg|conf|sh|xml|md|log|env|ini|list)$/i;
function canEdit(i) { return !i.dir && EDIT_EXT.test(i.name) && i.size < 512 * 1024; }
let editPath = "";
window.editFile = async n => {
  editPath = cur ? cur + "/" + n : n;
  try {
    const j = await api("/api/files/content?path=" + encodeURIComponent(editPath));
    $("#editTitle").textContent = "Edit " + j.name;
    $("#editBody").value = j.text;
    $("#editMsg").textContent = "";
    $("#editModal").classList.remove("hide");
  } catch (e) { toast(e.message, "error"); }
};
$("#editSave").onclick = async () => {
  try {
    await api("/api/files/content", { method: "POST", body: JSON.stringify({ server_id: SID, path: editPath, text: $("#editBody").value }) });
    toast("Saved " + editPath, "ok");
    $("#editModal").classList.add("hide");
  } catch (e) { toast(e.message, "error"); }
};
$("#editClose").onclick = () => $("#editModal").classList.add("hide");
$("#editModal").onclick = e => { if (e.target.id === "editModal") $("#editModal").classList.add("hide"); };
document.addEventListener("keydown", e => { if (e.key === "Escape") $("#editModal").classList.add("hide"); });
$("#fUp").onclick = () => loadFiles(cur.split("/").slice(0, -1).join("/"));
$("#fMk").onclick = async () => { const n = await askText("New folder name"); if (n) { await api("/api/files/mkdir", { method: "POST", body: JSON.stringify({ path: cur ? cur + "/" + n : n, server_id: SID }) }); loadFiles(cur); } };
$("#fFile").onchange = async e => { for (const f of e.target.files) { const fd = new FormData(); fd.append("file", f); await fetch("/api/files/upload?path=" + encodeURIComponent(cur) + "&" + qs(), { method: "POST", headers: { "x-token": TOKEN }, body: fd }); } loadFiles(cur); };

// ---------- worlds ----------
async function loadWorlds() {
  try {
    const j = await api("/api/worlds");
    $("#wList").innerHTML = (j.worlds || []).map(w => `<div class="mod"><div>${esc(w.name)} (${(w.size / 1048576).toFixed(1)} MB)</div><div><button class="act mini" onclick="dlWorld('${esc(w.name)}')">Download zip</button></div></div>`).join("") || "No world yet.";
  } catch (e) { $("#wList").textContent = e.message; }
}
window.dlWorld = n => window.open("/api/worlds/download?name=" + encodeURIComponent(n) + "&" + qs(), "_blank");
$("#wDl").onclick = () => window.open("/api/worlds/download?name=" + encodeURIComponent($("#wName").value) + "&" + qs(), "_blank");
$("#wUp").onchange = async e => { if (!(await ask("Replace the current world with this zip?"))) return; const fd = new FormData(); fd.append("file", e.target.files[0]); try { await fetch("/api/worlds/upload?" + qs(), { method: "POST", headers: { "x-token": TOKEN }, body: fd }); toast("World replaced.", "ok"); } catch (err) { toast(err.message, "error"); } loadWorlds(); };

// ---------- backups / access ----------
async function loadBk() {
  try {
    const j = await api("/api/backups");
    const list = j.backups || [];
    $("#bkList").innerHTML = list.length ? list.map(b => `${esc(b.file)} (${(b.size / 1048576).toFixed(1)} MB) <button class="act" onclick="dlBackup('${esc(b.file)}')">Download</button> <button class="act" onclick="restore('${esc(b.file)}')">Restore</button>`).join("<br>") : "No backups yet.";
  } catch (e) { $("#bkList").textContent = e.message; }
  loadBkSched();
}
async function loadBkSched() {
  try {
    const j = await api("/api/backups/settings");
    const sc = j.schedule || {};
    $("#bkEnabled").checked = !!sc.enabled;
    $("#bkMode").value = sc.mode || "daily";
    $("#bkHour").value = sc.hour != null ? sc.hour : 4;
    $("#bkMin").value = sc.minute != null ? sc.minute : 0;
    $("#bkKeep").value = sc.keep || 5;
    $("#bkSchedOut").textContent = sc.enabled
      ? `Scheduled ${sc.mode} at ${String(sc.hour).padStart(2, "0")}:${String(sc.minute).padStart(2, "0")}, keeping the newest ${sc.keep}.`
      : "Scheduled backups are off.";
  } catch (e) { $("#bkSchedOut").textContent = ""; }
}
window.dlBackup = f => window.open("/api/backups/download?file=" + encodeURIComponent(f) + "&" + qs(), "_blank");
window.restore = async f => { if (!(await ask("Restore backup " + f + "? The current files are overwritten."))) return; try { await api("/api/backups/restore", { method: "POST", body: JSON.stringify({ file: f }) }); toast("Restore done.", "ok"); } catch (e) { toast(e.message, "error"); } };
$("#bkGo").onclick = async () => { try { await api("/api/backups", { method: "POST", body: "{}" }); toast("Backup created.", "ok"); } catch (e) { toast(e.message, "error"); } loadBk(); };
$("#bkRef").onclick = loadBk;
$("#bkSave").onclick = async () => {
  try {
    const r = await api("/api/backups/settings", { method: "PUT", body: JSON.stringify({ server_id: SID, enabled: $("#bkEnabled").checked, mode: $("#bkMode").value, hour: parseInt($("#bkHour").value || "4", 10), minute: parseInt($("#bkMin").value || "0", 10), keep: parseInt($("#bkKeep").value || "5", 10) }) });
    toast("Schedule saved (" + (r.schedule.enabled ? r.schedule.mode + " at " + r.schedule.hour + ":" + r.schedule.minute : "off") + ").", "ok");
    loadBkSched();
  } catch (e) { toast(e.message, "error"); }
};
async function loadUsers() { try { const j = await api("/api/users"); $("#uList").innerHTML = (j.users || []).map(u => `${esc(u.username)} (${esc(u.role)}) <button class="act danger" onclick="delU('${esc(u.username)}')">Delete</button>`).join("<br>"); } catch (e) { $("#uList").textContent = e.message; } }
window.delU = async n => { await api("/api/users/" + n, { method: "DELETE" }); loadUsers(); };
$("#uAdd").onclick = async () => { try { await api("/api/users", { method: "POST", body: JSON.stringify({ username: $("#uName").value, password: $("#uPass").value, role: $("#uRole").value }) }); toast("User saved.", "ok"); loadUsers(); } catch (e) { toast(e.message, "error"); } };

// ---------- boot ----------
(async () => {
  const needs = await setupState();
  if (needs) { $("#btnLogin").textContent = "Create admin"; $("#me").textContent = "no users yet - create the first account"; }
  loadServers();
})();