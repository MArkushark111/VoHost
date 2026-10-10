// VoHost frontend — no build step.
let TOKEN = localStorage.getItem("vohost_tok") || "";
const H = () => ({ "Content-Type": "application/json", "x-token": TOKEN });
async function api(p, o = {}) {
  const r = await fetch(p, { ...o, headers: { ...H(), ...(o.headers || {}) } });
  if (!r.ok) throw new Error(await r.text());
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r.text();
}
function ansi(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/\x1b\[(\d+)m/g, (m, c) => { const map = { 31: "red", 32: "green", 33: "goldenrod", 36: "cyan", 0: "inherit" }; return `<span style="color:${map[c] || "inherit"}">`; });
}
const $ = (s) => document.querySelector(s);
// nav
document.querySelectorAll("#nav button").forEach(b => b.onclick = () => {
  document.querySelectorAll("#nav button").forEach(x => x.classList.remove("on"));
  b.classList.add("on");
  const t = b.dataset.t;
  document.querySelectorAll("main section").forEach(s => s.classList.toggle("hide", s.dataset.s !== t));
  if (t === "log") loadLog(); if (t === "files") loadFiles(""); if (t === "worlds") loadWorlds();
  if (t === "backups") loadBk(); if (t === "access") loadUsers(); if (t === "options") loadOpts();
  if (t === "software") loadSw(); if (t === "players") loadSeen(); if (t === "server") loadStatus();
});
document.querySelector('#nav [data-t="server"]').classList.add("on");
// auth
$("#btnLogin").onclick = async () => {
  const u = prompt("username", "admin"); if (!u) return;
  const p = prompt("password"); if (p === null) return;
  try { const r = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: u, password: p }) }); const j = await r.json(); TOKEN = r.headers.get("x-token") || ""; localStorage.setItem("vohost_tok", TOKEN); $("#me").textContent = j.user.username + " (" + j.user.role + ")"; loadStatus(); } catch (e) { alert("login failed: " + e.message); }
};
// server
let hist = [];
async function loadStatus() {
  try {
    const s = await api("/api/status");
    $("#mCpu").textContent = s.cpu + " %"; $("#mRam").textContent = s.ram_pct + " %";
    $("#mMc").textContent = s.mc_rss_mb + " MB"; $("#mTps").textContent = s.tps;
    $("#mOn").textContent = s.online ? "ONLINE" : "OFFLINE";
    $("#softCur").textContent = JSON.stringify(s.software || {});
    $("#motdCur").textContent = (s.props || {}).motd || "";
    hist.push(s.cpu); if (hist.length > 60) hist.shift(); draw();
    const bk = await api("/api/backups"); $("#bkBadge").style.display = bk.needs_attention ? "" : "none";
  } catch (e) { $("#mOn").textContent = "login required"; }
}
function draw() { const c = $("#graph").getContext("2d"); c.clearRect(0, 0, 900, 120); c.strokeStyle = "#3fa7ff"; c.beginPath(); hist.forEach((v, i) => { const x = i * 15, y = 120 - v * 1.2; i ? c.lineTo(x, y) : c.moveTo(x, y); }); c.stroke(); }
document.querySelectorAll("[data-a]").forEach(b => b.onclick = async () => { await api("/api/server/" + b.dataset.a, { method: "POST", body: "{}" }); setTimeout(loadStatus, 1500); });
$("#btnStop").onclick = async () => { await api("/api/server/stop", { method: "POST", body: "{}" }); loadStatus(); };
$("#btnEula").onclick = async () => { await api("/api/eula", { method: "POST", body: JSON.stringify({ accept: true }) }); alert("EULA accepted"); };
setInterval(() => { if (!document.querySelector('[data-s="server"]').classList.contains("hide")) loadStatus(); }, 4000);
// console WS
let ws;
function connectWS() {
  ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/console?token=" + encodeURIComponent(TOKEN));
  ws.onmessage = (e) => { const t = $("#term"); t.innerHTML += ansi(e.data) + "\n"; t.scrollTop = t.scrollHeight; };
  ws.onclose = () => setTimeout(connectWS, 3000);
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
  const editable = ["server-name", "motd", "max-players", "gamemode", "difficulty", "spawn-protection", "server-port", "resource-pack", "resource-pack-prompt"];
  editable.forEach(k => { f.innerHTML += `<label>${k}</label><input data-k="${k}" value="${(o.props[k] || "").replace(/"/g, "&quot;")}">`; });
  ["white-list", "allow-flight", "force-gamemode", "pvp", "online-mode", "enable-rcon", "require-resource-pack"].forEach(k => {
    const on = (o.props[k] || "false") === "true";
    f.innerHTML += `<div class="tgl"><span>${k}</span><input type="checkbox" data-k="${k}" style="width:auto" ${on ? "checked" : ""}></div>`;
  });
  $("#optTz").value = o.timezone || "UTC"; $("#optEnv").value = o.env || "";
  window._iconB64 = "";
  if (o.icon) { f.innerHTML += `<p>Current icon:</p><img src="data:image/png;base64,${o.icon}" width=64 height=64>`; }
}
$("#optIcon").onchange = (e) => { const r = new FileReader(); r.onload = () => window._iconB64 = r.result.split(",")[1]; r.readAsDataURL(e.target.files[0]); };
$("#optSave").onclick = async () => {
  const props = {};
  document.querySelectorAll("#optForm [data-k]").forEach(el => { props[el.dataset.k] = el.type === "checkbox" ? String(el.checked) : el.value; });
  await api("/api/options", { method: "PUT", body: JSON.stringify({ props, timezone: $("#optTz").value, env: $("#optEnv").value, icon_b64: window._iconB64 || undefined, curseforge_api_key: $("#optCF").value || undefined, discord_webhook: $("#optDiscord").value || undefined }) });
  alert("saved — restart server to apply server.properties");
};
// players
$("#plGo").onclick = async () => { const r = await api("/api/players/action", { method: "POST", body: JSON.stringify({ name: $("#plName").value, action: $("#plAct").value, duration: $("#plDur").value, reason: $("#plReason").value }) }); $("#plOut").textContent = JSON.stringify(r).slice(0, 300); };
async function loadSeen() { try { const j = await api("/api/players/seen"); $("#plSeen").innerHTML = j.players.slice(0, 50).map(p => `<button class="act" onclick="plData('${p.uuid || ""}')">${p.name || p.uuid || JSON.stringify(p)}</button>`).join(" "); } catch (e) { } }
window.plData = async (uuid) => { if (!uuid) return alert("need uuid (join server once)"); const j = await api("/api/players/data?uuid=" + uuid); $("#plData").innerHTML = "<pre>" + JSON.stringify(j, null, 1).slice(0, 4000) + "</pre>"; };
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
  const vs = j.versions || [];
  $("#swBuild").innerHTML = vs.map(v => `<option>${v}</option>`).join("") || `<option>latest</option>`;
  $("#swOut").textContent = j.note || "";
  const ml = $("#swLoader").value;
  $("#navMods").style.display = ["fabric", "quilt", "forge", "neoforge", "arclight", "modpack"].includes(ml) ? "" : "none";
  $("#navPlugins").style.display = ["paper", "purpur", "spigot", "arclight", "hytale"].includes(ml) ? "" : "none";
}
$("#swLoader").onchange = loadBuilds; $("#swMc").onchange = loadBuilds;
$("#swInstall").onclick = async () => { const r = await api("/api/software/install", { method: "POST", body: JSON.stringify({ loader: $("#swLoader").value, mc_version: $("#swMc").value, loader_version: $("#swBuild").value, accept_eula: $("#swEula").checked }) }); $("#swOut").textContent = r.note; };
// catalog
async function search(into, src, q, kind, mc) {
  const j = await api(`/api/catalog/search?source=${src}&q=${encodeURIComponent(q)}&kind=${kind}&mc=${mc || ""}&loader=${$("#swLoader")?.value || ""}`);
  document.querySelector(into).innerHTML = j.results.map(r => `<div class="mod">${r.icon ? `<img src="${r.icon}">` : ""}<div><b>${r.title}</b><br><span class="mut">${(r.description || "").slice(0, 140)}</span><br><button class="act" onclick="inst('${src}','${r.id}','${kind}')">Install (pick version)</button></div></div>`).join("") || "no results";
}
window.inst = async (src, id, kind) => {
  const mc = prompt("MC version (e.g. 1.21):", $("#swMc")?.value || "1.21"); if (mc === null) return;
  let ver = "";
  if (src === "modrinth") { const j = await api(`/api/catalog/versions?source=modrinth&project=${id}&mc=${mc}`); ver = prompt("version_id:\n" + j.versions.map(v => v.id + " = " + v.number).join("\n")); if (!ver) return; }
  else { ver = ""; const url = prompt("paste CurseForge file URL:"); if (!url) return; await api("/api/catalog/install", { method: "POST", body: JSON.stringify({ source: src, kind, project: id, file_url: url }) }); return alert("installed"); }
  await api("/api/catalog/install", { method: "POST", body: JSON.stringify({ source: src, kind, project: id, version_id: ver, mc }) });
  alert("installed");
};
$("#modGo").onclick = () => search("#modList", $("#modSrc").value, $("#modQ").value, $("#modKind").value, $("#swMc")?.value);
$("#plgGo").onclick = () => search("#plgList", $("#plgSrc").value, $("#plgQ").value, "plugin", $("#swMc")?.value);
// files
let cur = "";
async function loadFiles(p) {
  cur = p; $("#fPath").value = p;
  const j = await api("/api/files?path=" + encodeURIComponent(p));
  $("#fTable").innerHTML = j.items.map(i => `<tr><td>${i.dir ? "📁" : "📄"} ${i.name}</td><td>${i.dir ? "" : i.size}</td><td><button onclick="openP('${i.name}',${i.dir})">Open</button> <button onclick="delP('${i.name}')">Del</button></td></tr>`).join("");
}
window.openP = (n, d) => { const np = cur ? cur + "/" + n : n; if (d) loadFiles(np); else window.open("/api/files?path=" + encodeURIComponent(np) + "&token=" + TOKEN, "_blank"); };
window.delP = async (n) => { if (!confirm("delete " + n + "?")) return; await api("/api/files/delete", { method: "POST", body: JSON.stringify({ path: cur ? cur + "/" + n : n }) }); loadFiles(cur); };
$("#fUp").onclick = () => loadFiles(cur.split("/").slice(0, -1).join("/"));
$("#fMk").onclick = async () => { const n = prompt("folder name"); if (n) { await api("/api/files/mkdir", { method: "POST", body: JSON.stringify({ path: cur ? cur + "/" + n : n }) }); loadFiles(cur); } };
$("#fFile").onchange = async (e) => { for (const f of e.target.files) { const fd = new FormData(); fd.append("file", f); await fetch("/api/files/upload?path=" + encodeURIComponent(cur), { method: "POST", headers: { "x-token": TOKEN }, body: fd }); } loadFiles(cur); };
// worlds
async function loadWorlds() { const j = await api("/api/worlds"); $("#wList").innerHTML = j.worlds.map(w => `${w.name} (${(w.size / 1048576).toFixed(1)} MB)`).join("<br>") || "no world yet"; }
$("#wDl").onclick = () => window.open("/api/worlds/download?name=" + $("#wName").value, "_blank");
$("#wUp").onchange = async (e) => { if (!confirm("Replace old world with this zip?")) return; const fd = new FormData(); fd.append("file", e.target.files[0]); await fetch("/api/worlds/upload", { method: "POST", headers: { "x-token": TOKEN }, body: fd }); loadWorlds(); };
// backups/users
async function loadBk() { const j = await api("/api/backups"); $("#bkList").innerHTML = j.backups.map(b => `${b.file} <button onclick="restore('${b.file}')">Restore</button>`).join("<br>") || "no backups — create one to clear the warning"; }
window.restore = async (f) => { if (confirm("restore " + f + "?")) await api("/api/backups/restore", { method: "POST", body: JSON.stringify({ file: f }) }); };
$("#bkGo").onclick = async () => { await api("/api/backups", { method: "POST", body: "{}" }); loadBk(); };
$("#bkRef").onclick = loadBk;
async function loadUsers() { try { const j = await api("/api/users"); $("#uList").innerHTML = j.users.map(u => `${u.username} (${u.role}) <button onclick="delU('${u.username}')">del</button>`).join("<br>"); } catch (e) { $("#uList").textContent = "admin only"; } }
window.delU = async (n) => { await api("/api/users/" + n, { method: "DELETE" }); loadUsers(); };
$("#uAdd").onclick = async () => { await api("/api/users", { method: "POST", body: JSON.stringify({ username: $("#uName").value, password: $("#uPass").value, role: $("#uRole").value }) }); loadUsers(); };
loadStatus();
