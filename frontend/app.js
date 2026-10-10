// VoHost frontend - rebuilt. No build step.
let TOKEN = localStorage.getItem("vohost_tok") || "";
let SID = localStorage.getItem("vohost_sid") || "";
let CURSRV = null;              // current server metadata (defines loader-aware tabs)
const $ = s => document.querySelector(s);
const H = () => ({ "Content-Type": "application/json", "x-token": TOKEN });
function qs(extra) { let s = SID ? "server_id=" + encodeURIComponent(SID) : ""; if (extra) s += (s ? "&" : "") + extra; return s; }

async function api(path, opts = {}) {
  let url = path;
  if (SID && !path.startsWith("/api/servers") && !path.startsWith("/api/login") && !path.startsWith("/api/setup") && !path.startsWith("/api/me") && !/server_id=/.test(path) && !path.includes("?")) url = path + "?" + qs();
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

// ---------- navigation ----------
function show(tab) {
  document.querySelectorAll("#nav button").forEach(b => b.classList.toggle("on", b.dataset.t === tab));
  document.querySelectorAll("main section").forEach(sec => sec.classList.toggle("hide", sec.dataset.s !== tab));
  ({
    servers: loadServers, server: loadStatus, options: loadOpts, console: nop,
    log: loadLog, players: loadPlayers, software: loadSw, mods: () => loadInstalled("mod"),
    plugins: () => loadInstalled("plugin"), files: () => loadFiles(cur), worlds: loadWorlds,
    backups: loadBk, access: loadUsers
  }[tab] || nop)();
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
    const u = prompt("Create admin - username", "admin"); if (!u) return;
    const p = prompt("Create admin - password (min 4 chars)"); if (!p) return;
    if (p !== prompt("repeat password")) { alert("passwords differ"); return; }
    const r = await fetch("/api/setup", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: u, password: p }) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { alert("setup failed: " + (j.detail || r.status)); return; }
    TOKEN = r.headers.get("x-token") || ""; localStorage.setItem("vohost_tok", TOKEN);
    $("#btnLogin").textContent = "Logout"; refreshMe(); loadServers(); return;
  }
  const u = prompt("username"); if (!u) return;
  const p = prompt("password"); if (p === null) return;
  const r = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: u, password: p }) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { alert("login failed: " + (j.detail || r.status)); return; }
  TOKEN = r.headers.get("x-token") || ""; localStorage.setItem("vohost_tok", TOKEN);
  $("#btnLogin").textContent = "Logout"; refreshMe(); loadServers();
};
async function refreshMe() { try { const j = await api("/api/me"); const u = j.user; $("#me").textContent = u ? `${u.username} (${u.role})` : ""; $("#btnLogin").textContent = u ? "Logout" : "Login"; } catch (e) { $("#me").textContent = ""; $("#btnLogin").textContent = "Login"; } }

// ---------- servers ----------
async function loadServers() {
  try {
    const j = await api("/api/servers");
    const arr = j.servers || [];
    $("#srvCount").textContent = arr.length ? arr.length + " server(s) - click Manage to open" : "No servers yet. Add one below.";
    $("#srvList").innerHTML = arr.map(s =>
      `<div class="mod"><div><b>${esc(s.name)}</b> <span class="mut">${esc(s.id)} - port ${s.port} - ${s.network_mode.toUpperCase()} - ${s.online ? "ONLINE" : "offline"}</span><br>` +
      `<button class="act" onclick="openSrv('${esc(s.id)}')">Manage</button> ` +
      `<button class="act danger" onclick="delSrv('${esc(s.id)}')">Delete</button></div></div>`).join("");
    if (!SID && arr.length) { SID = arr[0].id; localStorage.setItem("vohost_sid", SID); }
    if (SID) {
      CURSRV = arr.find(x => x.id === SID) || null;
      $("#srvName").textContent = CURSRV ? CURSRV.name : "VoHost";
      $("#srvId").textContent = CURSRV ? CURSRV.id : "select";
      setLoaderUI();
    }
    refreshMe();
  } catch (e) { $("#srvList").textContent = e.message; }
}
window.openSrv = async id => { SID = id; localStorage.setItem("vohost_sid", SID); show("server"); connectWS(); loadStatus(); };
window.delSrv = async id => { if (!confirm("Delete " + id + "? (files are kept)") ) return; await api("/api/servers/" + id, { method: "DELETE" }); SID = ""; CURSRV = null; localStorage.removeItem("vohost_sid"); loadServers(); };
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
  if (!v || v === "-" || v === "fetching..." || v === "fetching WAN...") { alert("Address not available yet."); return; }
  (navigator.clipboard ? navigator.clipboard.writeText(v) : Promise.reject()).then(() => alert("Copied: " + v)).catch(() => { const t = document.createElement("textarea"); t.value = v; document.body.appendChild(t); t.select(); document.execCommand("copy"); t.remove(); alert("Copied: " + v); });
};
// ---------- server panel ----------
let hist = [];
async function loadStatus() {
  if (!SID) { document.querySelector("[data-s='servers']").classList.remove("hide"); show("servers"); return; }
  try {
    const s = await api("/api/status");
    $("#mCpu").textContent = s.cpu + " %"; $("#mRam").textContent = s.ram_pct + " %";
    $("#mOn").textContent = s.online ? "ONLINE" : "OFFLINE"; $("#mTps").textContent = s.tps;
    $("#mNet").textContent = (s.network_mode || "?").toUpperCase(); $("#mPort").textContent = (s.server || {}).port || "?";
    $("#motdCur").textContent = (s.props || {}).motd || "";
    const soft = s.software || {};
    $("#mSoft").textContent = (soft.loader || "vanilla") + " " + (soft.mc_version || "");
    $("#netSel").value = s.network_mode || "wan";
    const ip = s.ip || {};
    $("#mLan").textContent = ip.lan || "-";
    $("#mWan").textContent = ip.wan || "fetching...";
    const mport = (s.props && s.props["server-port"]) || ((s.server || {}).port) || "25565";
    let conn = "";
    if (s.network_mode === "lan") conn = ip.lan ? ip.lan + ":" + mport : "fetching...";
    else conn = ip.wan && ip.wan !== "-" ? ip.wan + ":" + mport : "fetching WAN...";
    $("#mConn").textContent = conn;
    if (CURSRV && (!CURSRV.loader) && soft.loader) { CURSRV.loader = soft.loader; setLoaderUI(); }
    if (CURSRV && soft.mc_version && (!CURSRV.mc_version || CURSRV.mc_version === "latest")) { CURSRV.mc_version = soft.mc_version; }
    hist.push(s.cpu); if (hist.length > 60) hist.shift(); drawGraph();
    const bk = await api("/api/backups"); $("#bkBadge").style.display = bk.needs_attention ? "" : "none";
  } catch (e) { if (e.status === 401) { $("#mOn").textContent = "login required"; } }
}
function drawGraph() { const c = $("#graph"); if (!c) return; const g = c.getContext("2d"); g.clearRect(0, 0, 900, 120); g.strokeStyle = "#3fa7ff"; g.beginPath(); hist.forEach((v, i) => { const x = i * 15, y = 120 - v * 1.2; i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.stroke(); }
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
  } catch (e) { alert(e.message); }
});
$("#btnEula").onclick = async () => { await api("/api/eula", { method: "POST", body: JSON.stringify({ accept: true }) }); alert("EULA accepted"); };
$("#netGo").onclick = async () => { await api("/api/servers/" + SID, { method: "PUT", body: JSON.stringify({ network_mode: $("#netSel").value }) }); loadStatus(); };
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
$("#cmd").addEventListener("keydown", e => { if (e.key === "Enter") sendCmd(); });
async function sendCmd() {
  const c = $("#cmd").value; if (!c) return;
  try {
    if (ws && ws.readyState === 1) ws.send(JSON.stringify({ command: c }));
    else { const r = await api("/api/server/command", { method: "POST", body: JSON.stringify({ command: c, server_id: SID }) }); $("#term").innerHTML += "\n" + ansi(r.out || r.error || ""); }
  } catch (e) { $("#term").innerHTML += "\n" + ansi("[error] " + e.message); }
  $("#cmd").value = "";
}
async function loadLog() { try { $("#term2").innerHTML = ansi((await api("/api/logs?lines=400")).log || ""); } catch (e) { $("#term2").textContent = e.message; } }
$("#btnLog").onclick = loadLog;

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
    const toggles = ["white-list", "allow-flight", "force-gamemode", "pvp", "enable-rcon", "require-resource-pack"];
    toggles.forEach(k => {
      const on = (o.props[k] || "false") === "true";
      f.innerHTML += `<div class="tgl"><span>${esc(k)}</span><input type="checkbox" data-k="${k}" style="width:auto" ${on ? "checked" : ""}></div>`;
    });
    const cracked = (o.props["online-mode"] || "true") === "false";
    f.innerHTML += `<div class="tgl" style="border:1px solid var(--warn,#c9a227);border-radius:8px;padding:8px"><span><b>Cracked mode</b> (allow TLauncher / unofficial clients) <span class="mut">- sets online-mode=false + enforce-secure-profile=false so cracked and official (Minecraft) clients join the same server</span></span><input type="checkbox" data-k="cracked-mode" style="width:auto" ${cracked ? "checked" : ""}></div>`;
    f.innerHTML += `<label>Network (WAN public / LAN only)</label><select data-k="_network_mode"><option value="wan" ${o.network_mode === "wan" ? "selected" : ""}>WAN - public</option><option value="lan" ${o.network_mode === "lan" ? "selected" : ""}>LAN - home only</option></select>`;
    $("#optTz").value = o.timezone || "UTC"; $("#optEnv").value = o.env || "";
    window._iconB64 = "";
    $("#optIconPrev").style.display = o.icon ? "" : "none";
    if (o.icon) $("#optIconPrev").src = "data:image/png;base64," + o.icon;
    $("#optIconMsg").textContent = o.icon ? "Current icon shown above (64x64). Pick a new one below or upload." : "No icon yet - upload a 64x64 PNG.";
  } catch (e) { $("#optForm").textContent = e.message; }
}
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
    await api("/api/options", { method: "PUT", body: JSON.stringify({ props, server_id: SID, timezone: $("#optTz").value, env: $("#optEnv").value, icon_b64: window._iconB64 || undefined, curseforge_api_key: $("#optCF").value || undefined, discord_webhook: $("#optDiscord").value || undefined }) });
    alert("Saved. Restart the server to apply.");
  } catch (e) { alert(e.message); }
};

// ---------- players ----------
$("#plGo").onclick = async () => {
  try {
    const r = await api("/api/players/action", { method: "POST", body: JSON.stringify({ name: $("#plName").value, action: $("#plAct").value, duration: $("#plDur").value, reason: $("#plReason").value, server_id: SID }) });
    $("#plOut").textContent = JSON.stringify(r).slice(0, 200);
  } catch (e) { $("#plOut").textContent = e.message; }
};
async function loadPlayers() {
  loadOnline(); loadSeen();
}
async function loadOnline() {
  try {
    const j = await api("/api/players/online");
    if (j.error) { $("#plOnline").textContent = j.error; return; }
    $("#plOnline").textContent = (j.online || []).length
      ? "Online: " + j.online.join(", ")
      : "0 players online";
  } catch (e) { $("#plOnline").textContent = "server offline or RCON disabled"; }
}
async function loadSeen() {
  try {
    const j = await api("/api/players/seen");
    const ps = j.players || [];
    if (!ps.length) { $("#plSeen").textContent = "No players seen yet (join once to appear here)."; return; }
    $("#plSeen").innerHTML = ps.slice(0, 40).map(p => {
      const label = p.name || p.uuid || "?";
      const uuid = p.uuid || "";
      return `<button class="act" onclick="plData('${esc(uuid)}')">${esc(label)} (inventory)</button> `;
    }).join("");
  } catch (e) { $("#plSeen").textContent = e.message; }
}
window.plData = async uuid => {
  if (!uuid) { alert("Player needs a UUID (join the server once)"); return; }
  try { const j = await api("/api/players/data?uuid=" + encodeURIComponent(uuid)); $("#plData").innerHTML = "<pre>" + esc(JSON.stringify(j, null, 1).slice(0, 4000)) + "</pre>"; }
  catch (e) { $("#plData").textContent = e.message; }
};

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
    const r = await api("/api/software/install", { method: "POST", body: JSON.stringify({ loader: $("#swLoader").value, mc_version: $("#swMc").value, loader_version: $("#swBuild").value, accept_eula: $("#swEula").checked, server_id: SID }) });
    $("#swOut").textContent = r.note;
    if (CURSRV) { CURSRV.loader = $("#swLoader").value; CURSRV.mc_version = $("#swMc").value; setLoaderUI(); }
    loadStatus();
  } catch (e) { $("#swOut").textContent = e.message; }
};

// ---------- mods / plugins ----------
async function loadInstalled(kind) {
  const into = kind === "mod" ? "#modInst" : "#plgInst";
  try {
    const j = await api("/api/catalog/installed?kind=" + kind);
    const list = j.installed || [];
    document.querySelector(into).innerHTML = list.length
      ? list.map(m => `<div class="mod"><div><b>${esc(m.file)}</b> <span class="mut">${(m.size / 1024).toFixed(0)} KB</span> <button class="act danger" onclick="uninst('${kind}','${esc(m.file)}')">Uninstall</button></div></div>`).join("")
      : "Nothing installed yet.";
  } catch (e) { document.querySelector(into).textContent = e.message; }
}
window.uninst = async (kind, file) => {
  if (!confirm("Uninstall " + file + "?")) return;
  try { await api("/api/catalog/uninstall", { method: "POST", body: JSON.stringify({ kind, file, server_id: SID }) }); loadInstalled(kind); } catch (e) { alert(e.message); }
};
$("#modRef").onclick = () => loadInstalled("mod");
$("#plgRef").onclick = () => loadInstalled("plugin");

const AF = (env, q) => {
  // helper for catalog search
};
async function search(into, src, q, kind) {
  try {
    const loader = (CURSRV && CURSRV.loader) || "";
    const mc = (CURSRV && CURSRV.mc_version) || "";
    const j = await api("/api/catalog/search?source=" + encodeURIComponent(src) + "&q=" + encodeURIComponent(q) + "&kind=" + kind + "&mc=" + encodeURIComponent(mc) + "&loader=" + encodeURIComponent(loader));
    const res = j.results || [];
    document.querySelector(into).innerHTML = res.length
      ? res.map(r => `<div class="mod">${r.icon ? `<img src="${esc(r.icon)}">` : `<div class="mut" style="width:48px;height:48px;display:flex;align-items:center;justify-content:center">NA</div>`}<div><b>${esc(r.title)}</b><br><span class="mut">${esc((r.description || "").slice(0, 140))}</span><br><button class="act" onclick="inst('${esc(src)}','${esc(r.id)}','${kind}')">Install</button></div></div>`).join("")
      : "No results.";
  } catch (e) { document.querySelector(into).textContent = e.message; }
}
window.inst = async (src, id, kind) => {
  try {
    if (!CURSRV || !CURSRV.mc_version) { alert("Open the Server page first so we know the Minecraft version."); return; }
    const r = await api("/api/catalog/install", { method: "POST", body: JSON.stringify({ source: src, kind, project: id, mc: (CURSRV.mc_version || "").toString(), loader: (CURSRV.loader || "").toString(), server_id: SID }) });
    alert("Installed - " + (r.note || r.file) + "\nRestart the server to load it.");
    loadInstalled(kind);
  } catch (e) { alert(e.message); }
};
$("#modGo").onclick = () => search("#modList", $("#modSrc").value, $("#modQ").value, "mod");
$("#plgGo").onclick = () => search("#plgList", $("#plgSrc").value, $("#plgQ").value, "plugin");

// ---------- files ----------
let cur = "";
async function loadFiles(p) {
  cur = p; $("#fPath").value = p;
  try {
    const j = await api("/api/files?path=" + encodeURIComponent(p));
    const items = j.items || [];
    if (!items.length) { $("#fTable").innerHTML = "<tr><td class='mut'>empty folder</td></tr>"; return; }
    $("#fTable").innerHTML = items.map(i => i.dir
      ? `<tr><td><a href="#" onclick="openFolder('${esc(i.name)}');return false">${esc(i.name)}/</a></td><td>-</td><td><button class="act" onclick="openFolder('${esc(i.name)}')">Open</button></td></tr>`
      : `<tr><td>${esc(i.name)}</td><td>${(i.size / 1024).toFixed(1)} KB</td><td><button class="act" onclick="dlFile('${esc(i.name)}')">Download</button> <button class="act danger" onclick="delP('${esc(i.name)}')">Delete</button></td></tr>`).join("");
  } catch (e) { $("#fTable").innerHTML = "<tr><td>" + esc(e.message) + "</td></tr>"; }
}
window.openFolder = n => loadFiles(cur ? cur + "/" + n : n);
window.dlFile = async n => { window.open("/api/files?path=" + encodeURIComponent(cur ? cur + "/" + n : n) + "&" + qs(), "_blank"); };
window.delP = async n => { if (!confirm("Delete " + n + "?")) return; await api("/api/files/delete", { method: "POST", body: JSON.stringify({ path: cur ? cur + "/" + n : n, server_id: SID }) }); loadFiles(cur); };
$("#fUp").onclick = () => loadFiles(cur.split("/").slice(0, -1).join("/"));
$("#fMk").onclick = async () => { const n = prompt("folder name"); if (n) { await api("/api/files/mkdir", { method: "POST", body: JSON.stringify({ path: cur ? cur + "/" + n : n, server_id: SID }) }); loadFiles(cur); } };
$("#fFile").onchange = async e => { for (const f of e.target.files) { const fd = new FormData(); fd.append("file", f); await fetch("/api/files/upload?path=" + encodeURIComponent(cur) + "&" + qs(), { method: "POST", headers: { "x-token": TOKEN }, body: fd }); } loadFiles(cur); };

// ---------- worlds ----------
async function loadWorlds() { try { const j = await api("/api/worlds"); $("#wList").innerHTML = (j.worlds || []).map(w => `${esc(w.name)} (${(w.size / 1048576).toFixed(1)} MB)`).join("<br>") || "No world yet."; } catch (e) { $("#wList").textContent = e.message; } }
$("#wDl").onclick = () => window.open("/api/worlds/download?name=" + encodeURIComponent($("#wName").value) + "&" + qs(), "_blank");
$("#wUp").onchange = async e => { if (!confirm("Replace the old world with this zip?")) return; const fd = new FormData(); fd.append("file", e.target.files[0]); await fetch("/api/worlds/upload?" + qs(), { method: "POST", headers: { "x-token": TOKEN }, body: fd }); loadWorlds(); };

// ---------- backups / access ----------
async function loadBk() { try { const j = await api("/api/backups"); const list = j.backups || []; $("#bkList").innerHTML = list.length ? list.map(b => `${esc(b.file)} <button class="act" onclick="restore('${esc(b.file)}')">Restore</button>`).join("<br>") : "No backups yet."; } catch (e) { $("#bkList").textContent = e.message; } }
window.restore = async f => { if (confirm("Restore " + f + "?")) { await api("/api/backups/restore", { method: "POST", body: JSON.stringify({ file: f }) }); } };
$("#bkGo").onclick = async () => { await api("/api/backups", { method: "POST", body: "{}" }); loadBk(); };
$("#bkRef").onclick = loadBk;
async function loadUsers() { try { const j = await api("/api/users"); $("#uList").innerHTML = (j.users || []).map(u => `${esc(u.username)} (${esc(u.role)}) <button class="act danger" onclick="delU('${esc(u.username)}')">Delete</button>`).join("<br>"); } catch (e) { $("#uList").textContent = e.message; } }
window.delU = async n => { await api("/api/users/" + n, { method: "DELETE" }); loadUsers(); };
$("#uAdd").onclick = async () => { try { await api("/api/users", { method: "POST", body: JSON.stringify({ username: $("#uName").value, password: $("#uPass").value, role: $("#uRole").value }) }); loadUsers(); } catch (e) { alert(e.message); } };

// ---------- boot ----------
(async () => {
  const needs = await setupState();
  if (needs) { $("#btnLogin").textContent = "Create admin"; $("#me").textContent = "no users yet - create the first account"; }
  loadServers();
})();