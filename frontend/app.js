// VoHost frontend — multi-server + WAN/LAN + installed mods.
let TOKEN = localStorage.getItem("vohost_tok") || "";
let SID = localStorage.getItem("vohost_sid") || "";
const H = () => ({ "Content-Type": "application/json", "x-token": TOKEN });
const Q = (extra = "") => { const s = SID ? `server_id=${encodeURIComponent(SID)}` : ""; return s + (extra ? (s ? "&" : "") + extra : ""); };
async function api(p, o = {}) {
  const sep = p.includes("?") ? "&" : "?";
  const withSid = SID && !p.includes("server_id") && !p.startsWith("/api/servers") && !p.startsWith("/api/login") ? p + sep + Q() : p;
  const r = await fetch(withSid, { ...o, headers: { ...H(), ...(o.headers || {}) } });
  if (!r.ok) throw new Error(await r.text());
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r.text();
}
function ansi(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/\x1b\[(\d+)m/g, (m, c) => { const map = { 31: "red", 32: "green", 33: "goldenrod", 36: "cyan", 0: "inherit" }; return `<span style="color:${map[c] || "inherit"}">`; });
}
const $ = (s) => document.querySelector(s);
function show(t) {
  document.querySelectorAll("#nav button").forEach(x => x.classList.toggle("on", x.dataset.t === t));
  document.querySelectorAll("main section").forEach(s => s.classList.toggle("hide", s.dataset.s !== t));
  if (t === "servers") loadServers(); if (t === "server") loadStatus(); if (t === "log") loadLog();
  if (t === "files") loadFiles(""); if (t === "worlds") loadWorlds(); if (t === "backups") loadBk();
  if (t === "access") loadUsers(); if (t === "options") loadOpts(); if (t === "software") loadSw();
  if (t === "players") loadSeen(); if (t === "mods") loadInstalled("mod"); if (t === "plugins") loadInstalled("plugin");
}
document.querySelectorAll("#nav button").forEach(b => b.onclick = () => show(b.dataset.t));
async function checkSetup() {
  try {
    const r = await fetch("/api/setup-state"); const j = await r.json();
    if (j.needs_setup) {
      $("#btnLogin").textContent = "Create admin";
      $("#me").textContent = "no users yet — create the first account";
    } else {
      $("#btnLogin").textContent = "Login";
    }
  } catch (e) { /* logged out state */ }
}
checkSetup();
$("#btnLogin").onclick = async () => {
  // first-run: create admin when no users exist
  let j;
  try { j = await (await fetch("/api/setup-state")).json(); } catch (e) { j = { needs_setup: false }; }
  if (j.needs_setup) {
    const u = prompt("Create admin — username", "admin"); if (!u) return;
    const p = prompt("Create admin — password (min 4 chars)"); if (!p) return;
    const c = prompt("repeat password"); if (c !== p) { alert("passwords differ"); return; }
    const r = await fetch("/api/setup", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: u, password: p }) });
    const jj = await r.json().catch(() => ({}));
    if (!r.ok) { alert("setup failed: " + (jj.detail || r.status)); return; }
    TOKEN = r.headers.get("x-token") || ""; localStorage.setItem("vohost_tok", TOKEN);
    $("#btnLogin").textContent = "Login"; loadServers(); return;
  }
  const u = prompt("username", ""); if (!u) return;
  const p = prompt("password"); if (p === null) return;
  try {
    const r = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: u, password: p }) });
    const jj = await r.json().catch(() => ({}));
    if (!r.ok) { alert("login failed: " + (jj.detail || r.status)); return; }
    TOKEN = r.headers.get("x-token") || ""; localStorage.setItem("vohost_tok", TOKEN);
    $("#me").textContent = (jj.user || {}).username + " (" + (jj.user || {}).role + ")"; loadServers();
  } catch (e) { alert("login error: " + e.message); }
};
// servers
async function loadServers() {
  try {
    const j = await api("/api/servers");
    const arr = j.servers || [];
    $("#srvCount").textContent = arr.length ? `${arr.length} server(s) — click Open to manage` : "No servers yet — add your first below.";
    $("#srvList").innerHTML = arr.map(s => `<div class="mod"><div><b>${s.name}</b> <span class="mut">${s.id} · :${s.port} · ${s.network_mode.toUpperCase()} · ${s.online ? "ONLINE" : "offline"}</span><br><button class="act" onclick="openSrv('${s.id}','${s.name}')">Open dashboard</button> <button class="act danger" onclick="delSrv('${s.id}')">Delete</button></div></div>`).join("");
    if (!SID && arr.length) { SID = arr[0].id; localStorage.setItem("vohost_sid", SID); }
    if (SID) { const cur = arr.find(x => x.id === SID); $("#srvName").textContent = cur ? cur.name : "VoHost"; $("#srvId").textContent = SID; $("#curSrv").textContent = "— " + (cur ? cur.name : SID); }
  } catch (e) { $("#srvList").textContent = "login required"; }
}
window.openSrv = (id, name) => { SID = id; localStorage.setItem("vohost_sid", SID); $("#srvName").textContent = name; show("server"); connectWS(); };
window.delSrv = async (id) => { if (!confirm("delete " + id + "? (files kept unless wiped)")) return; await api("/api/servers/" + id, { method: "DELETE" }); SID = ""; localStorage.removeItem("vohost_sid"); loadServers(); };
$("#nsGo").onclick = async () => { try { const r = await api("/api/servers", { method: "POST", body: JSON.stringify({ name: $("#nsName").value || "server", network_mode: $("#nsNet").value, memory_max: $("#nsMem").value || "4G" }) }); $("#nsOut").textContent = r.note; SID = r.server.id; localStorage.setItem("vohost_sid", SID); loadServers(); } catch (e) { $("#nsOut").textContent = e.message; } };
// server tab
let hist = [];
async function loadStatus() {
  if (!SID) { show("servers"); return; }
  try {
    const s = await api("/api/status");
    $("#mCpu").textContent = s.cpu + " %"; $("#mRam").textContent = s.ram_pct + " %";
    $("#mOn").textContent = s.online ? "ONLINE" : "OFFLINE";
    $("#mNet").textContent = (s.network_mode || "?").toUpperCase(); $("#mPort").textContent = (s.server || {}).port || "?";
    $("#netSel").value = s.network_mode || "wan";
    $("#softCur").textContent = JSON.stringify(s.software || {}); $("#motdCur").textContent = (s.props || {}).motd || "";
    hist.push(s.cpu); if (hist.length > 60) hist.shift(); draw();
    const bk = await api("/api/backups"); $("#bkBadge").style.display = bk.needs_attention ? "" : "none";
  } catch (e) { $("#mOn").textContent = "login required"; }
}
function draw() { const c = $("#graph").getContext("2d"); c.clearRect(0, 0, 900, 120); c.strokeStyle = "#3fa7ff"; c.beginPath(); hist.forEach((v, i) => { const x = i * 15, y = 120 - v * 1.2; i ? c.lineTo(x, y) : c.moveTo(x, y); }); c.stroke(); }
document.querySelectorAll("[data-a]").forEach(b => b.onclick = async () => { await api("/api/server/" + b.dataset.a, { method: "POST", body: "{}" }); setTimeout(loadStatus, 1500); });
$("#btnStop").onclick = async () => { await api("/api/server/stop", { method: "POST", body: "{}" }); loadStatus(); };
$("#btnEula").onclick = async () => { await api("/api/eula", { method: "POST", body: JSON.stringify({ accept: true }) }); alert("EULA accepted"); };
$("#netGo").onclick = async () => { await api("/api/servers/" + SID, { method: "PUT", body: JSON.stringify({ network_mode: $("#netSel").value }) }); loadStatus(); };
setInterval(() => { if (!document.querySelector('[data-s="server"]').classList.contains("hide")) loadStatus(); }, 4000);
// console
let ws;
function connectWS() {
  try { ws && ws.close(); } catch (e) {}
  ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/console?token=" + encodeURIComponent(TOKEN) + "&server_id=" + encodeURIComponent(SID));
  ws.onmessage = (e) => { const t = $("#term"); t.innerHTML += ansi(e.data) + "\n"; t.scrollTop = t.scrollHeight; };
  ws.onclose = () => setTimeout(() => { if (!document.querySelector('[data-s="console"]').classList.contains("hide")) connectWS(); }, 3000);
}
connectWS();
async function sendCmd() { const c = $("#cmd").value; if (!c) return; if (ws && ws.readyState === 1) ws.send(JSON.stringify({ command: c })); else await api("/api/server/command", { method: "POST", body: JSON.stringify({ command: c }) }).then(r => { $("#term").innerHTML += "\n" + ansi(r.out || ""); }); $("#cmd").value = ""; }
$("#sendCmd").onclick = sendCmd; $("#cmd").onkeydown = (e) => { if (e.key === "Enter") sendCmd(); };
async function loadLog() { try { $("#term2").innerHTML = ansi(await api("/api/logs?lines=400").then(j => j.log)); } catch (e) { } }
$("#btnLog").onclick = loadLog;
// options
async function loadOpts() {
  const o = await api("/api/options");
  const f = $("#optForm"); f.innerHTML = "";
  ["server-name", "motd", "max-players", "gamemode", "difficulty", "spawn-protection", "server-port", "resource-pack", "resource-pack-prompt"].forEach(k => { f.innerHTML += `<label>${k}</label><input data-k="${k}" value="${(o.props[k] || "").replace(/"/g, "&quot;")}">`; });
  ["white-list", "allow-flight", "force-gamemode", "pvp", "online-mode", "enable-rcon", "require-resource-pack"].forEach(k => {
    const on = (o.props[k] || "false") === "true";
    f.innerHTML += `<div class="tgl"><span>${k}</span><input type="checkbox" data-k="${k}" style="width:auto" ${on ? "checked" : ""}></div>`;
  });
  f.innerHTML += `<label>network (WAN public / LAN only)</label><select data-k="_network_mode"><option value="wan" ${o.network_mode === "wan" ? "selected" : ""}>WAN public</option><option value="lan" ${o.network_mode === "lan" ? "selected" : ""}>LAN only</option></select>`;
  $("#optTz").value = o.timezone || "UTC"; $("#optEnv").value = o.env || "";
  window._iconB64 = "";
  if (o.icon) f.innerHTML += `<p>Current icon:</p><img src="data:image/png;base64,${o.icon}" width=64 height=64>`;
}
$("#optIcon").onchange = (e) => { const r = new FileReader(); r.onload = () => window._iconB64 = r.result.split(",")[1]; r.readAsDataURL(e.target.files[0]); };
$("#optSave").onclick = async () => {
  const props = {};
  document.querySelectorAll("#optForm [data-k]").forEach(el => { props[el.dataset.k] = el.type === "checkbox" ? String(el.checked) : el.value; });
  await api("/api/options", { method: "PUT", body: JSON.stringify({ props, server_id: SID, timezone: $("#optTz").value, env: $("#optEnv").value, icon_b64: window._iconB64 || undefined, curseforge_api_key: $("#optCF").value || undefined, discord_webhook: $("#optDiscord").value || undefined }) });
  alert("saved — restart to apply");
};
// players
$("#plGo").onclick = async () => { const r = await api("/api/players/action", { method: "POST", body: JSON.stringify({ name: $("#plName").value, action: $("#plAct").value, duration: $("#plDur").value, reason: $("#plReason").value, server_id: SID }) }); $("#plOut").textContent = JSON.stringify(r).slice(0, 300); };
async function loadSeen() { try { const j = await api("/api/players/seen"); $("#plSeen").innerHTML = j.players.slice(0, 50).map(p => `<button class="act" onclick="plData('${p.uuid || ""}')">${p.name || p.uuid || "?"}</button>`).join(" "); } catch (e) { } }
window.plData = async (uuid) => { if (!uuid) return alert("need uuid"); const j = await api("/api/players/data?uuid=" + uuid + "&" + Q()); $("#plData").innerHTML = "<pre>" + JSON.stringify(j, null, 1).slice(0, 4000) + "</pre>"; };
// software
async function loadSw() {
  const l = await api("/api/software/loaders");
  $("#swLoader").innerHTML = l.loaders.map(x => `<option value="${x.id}">${x.name}</option>`).join("");
  const mc = await api("/api/software/mc?kind=release");
  $("#swMc").innerHTML = mc.versions.slice(0, 40).map(v => `<option>${v}</option>`).join("");
  await loadBuilds();
}
async function loadBuilds() {
  const j = await api(`/api/software/loader-versions?loader=${$("#swLoader").value}&mc=${$("#swMc").value}`);
  $("#swBuild").innerHTML = (j.versions || []).map(v => `<option>${v}</option>`).join("") || `<option>latest</option>`;
  $("#swOut").textContent = j.note || "";
}
$("#swLoader").onchange = loadBuilds; $("#swMc").onchange = loadBuilds;
$("#swInstall").onclick = async () => { const r = await api("/api/software/install", { method: "POST", body: JSON.stringify({ loader: $("#swLoader").value, mc_version: $("#swMc").value, loader_version: $("#swBuild").value, accept_eula: $("#swEula").checked, server_id: SID }) }); $("#swOut").textContent = r.note; };
// catalog + installed
async function loadInstalled(kind) {
  const into = kind === "mod" ? "#modInst" : "#plgInst";
  try {
    const j = await api(`/api/catalog/installed?kind=${kind}&` + Q());
    document.querySelector(into).innerHTML = j.installed.map(m => `<div class="mod"><div><b>${m.file}</b> <span class="mut">${(m.size / 1024).toFixed(0)} KB</span> <button class="act danger" onclick="uninst('${kind}','${m.file}')">Uninstall</button></div></div>`).join("") || "nothing installed";
  } catch (e) { document.querySelector(into).textContent = e.message; }
}
window.uninst = async (kind, file) => { if (!confirm("uninstall " + file + "?")) return; await api("/api/catalog/uninstall", { method: "POST", body: JSON.stringify({ kind, file, server_id: SID }) }); loadInstalled(kind); };
$("#modRef").onclick = () => loadInstalled("mod"); $("#plgRef").onclick = () => loadInstalled("plugin");
async function search(into, src, q, kind, mc) {
  const j = await api(`/api/catalog/search?source=${src}&q=${encodeURIComponent(q)}&kind=${kind}&mc=${mc || ""}&loader=${$("#swLoader")?.value || ""}`);
  document.querySelector(into).innerHTML = j.results.map(r => `<div class="mod">${r.icon ? `<img src="${r.icon}">` : ""}<div><b>${r.title}</b><br><span class="mut">${(r.description || "").slice(0, 140)}</span><br><button class="act" onclick="inst('${src}','${r.id}','${kind}')">Install (pick version)</button></div></div>`).join("") || "no results";
}
window.inst = async (src, id, kind) => {
  const mc = prompt("MC version:", $("#swMc")?.value || "1.21"); if (mc === null) return;
  if (src === "modrinth") { const j = await api(`/api/catalog/versions?source=modrinth&project=${id}&mc=${mc}`); const ver = prompt("version_id:\n" + j.versions.map(v => v.id + " = " + v.number).join("\n")); if (!ver) return; await api("/api/catalog/install", { method: "POST", body: JSON.stringify({ source: src, kind, project: id, version_id: ver, mc, server_id: SID }) }); }
  else { const url = prompt("paste CurseForge file URL:"); if (!url) return; await api("/api/catalog/install", { method: "POST", body: JSON.stringify({ source: src, kind, project: id, file_url: url, server_id: SID }) }); }
  alert("installed"); loadInstalled(kind);
};
$("#modGo").onclick = () => search("#modList", $("#modSrc").value, $("#modQ").value, $("#modKind").value, $("#swMc")?.value);
$("#plgGo").onclick = () => search("#plgList", $("#plgSrc").value, $("#plgQ").value, "plugin", $("#swMc")?.value);
// files
let cur = "";
async function loadFiles(p) {
  cur = p; $("#fPath").value = p;
  const j = await api("/api/files?path=" + encodeURIComponent(p) + "&" + Q());
  $("#fTable").innerHTML = j.items.map(i => `<tr><td>${i.dir ? "📁" : "📄"} ${i.name}</td><td>${i.dir ? "" : i.size}</td><td><button onclick="openP('${i.name}',${i.dir})">Open</button> <button onclick="delP('${i.name}')">Del</button></td></tr>`).join("");
}
window.openP = (n, d) => { const np = cur ? cur + "/" + n : n; if (d) loadFiles(np); else window.open("/api/files?path=" + encodeURIComponent(np) + "&" + Q(), "_blank"); };
window.delP = async (n) => { if (!confirm("delete " + n + "?")) return; await api("/api/files/delete", { method: "POST", body: JSON.stringify({ path: cur ? cur + "/" + n : n, server_id: SID }) }); loadFiles(cur); };
$("#fUp").onclick = () => loadFiles(cur.split("/").slice(0, -1).join("/"));
$("#fMk").onclick = async () => { const n = prompt("folder name"); if (n) { await api("/api/files/mkdir", { method: "POST", body: JSON.stringify({ path: cur ? cur + "/" + n : n, server_id: SID }) }); loadFiles(cur); } };
$("#fFile").onchange = async (e) => { for (const f of e.target.files) { const fd = new FormData(); fd.append("file", f); await fetch("/api/files/upload?path=" + encodeURIComponent(cur) + "&" + Q(), { method: "POST", headers: { "x-token": TOKEN }, body: fd }); } loadFiles(cur); };
// worlds
async function loadWorlds() { const j = await api("/api/worlds"); $("#wList").innerHTML = j.worlds.map(w => `${w.name} (${(w.size / 1048576).toFixed(1)} MB)`).join("<br>") || "no world yet"; }
$("#wDl").onclick = () => window.open("/api/worlds/download?name=" + $("#wName").value + "&" + Q(), "_blank");
$("#wUp").onchange = async (e) => { if (!confirm("Replace old world with this zip?")) return; const fd = new FormData(); fd.append("file", e.target.files[0]); await fetch("/api/worlds/upload?" + Q(), { method: "POST", headers: { "x-token": TOKEN }, body: fd }); loadWorlds(); };
// backups/users
async function loadBk() { const j = await api("/api/backups"); $("#bkList").innerHTML = j.backups.map(b => `${b.file} <button onclick="restore('${b.file}')">Restore</button>`).join("<br>") || "no backups"; }
window.restore = async (f) => { if (confirm("restore " + f + "?")) await api("/api/backups/restore", { method: "POST", body: JSON.stringify({ file: f }) }); };
$("#bkGo").onclick = async () => { await api("/api/backups", { method: "POST", body: "{}" }); loadBk(); };
$("#bkRef").onclick = loadBk;
async function loadUsers() { try { const j = await api("/api/users"); $("#uList").innerHTML = j.users.map(u => `${u.username} (${u.role}) <button onclick="delU('${u.username}')">del</button>`).join("<br>"); } catch (e) { $("#uList").textContent = "admin only"; } }
window.delU = async (n) => { await api("/api/users/" + n, { method: "DELETE" }); loadUsers(); };
$("#uAdd").onclick = async () => { await api("/api/users", { method: "POST", body: JSON.stringify({ username: $("#uName").value, password: $("#uPass").value, role: $("#uRole").value }) }); loadUsers(); };
document.querySelector('#nav [data-t="servers"]').classList.add("on");
document.querySelector('[data-s="server"]').classList.add("hide");
loadServers();
