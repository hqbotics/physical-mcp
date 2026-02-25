"""Web dashboard for Physical MCP — works on iOS Safari + all browsers.

Serves a single-page mobile-first dashboard that shows:
- Live camera feed (JS frame loop — works on iOS unlike MJPEG)
- AI scene description + objects + people count
- Watch rules + recent alerts
- Camera health status

No build tools, no npm, no React. Pure vanilla HTML/CSS/JS.
"""

from __future__ import annotations

MANIFEST_JSON = """{
  "name": "Physical MCP",
  "short_name": "PhysMCP",
  "description": "AI camera vision dashboard",
  "start_url": "/dashboard",
  "display": "standalone",
  "background_color": "#0f0f17",
  "theme_color": "#0f0f17",
  "orientation": "portrait-primary"
}"""

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Physical MCP">
<meta name="theme-color" content="#0f0f17">
<link rel="manifest" href="/manifest.json">
<title>Physical MCP</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#0f0f17;--surface:#1a1a2e;--surface2:#252540;
  --text:#e0e0e0;--text2:#888;--accent:#00d4aa;--accent2:#7c5cfc;
  --danger:#ff4757;--warn:#ffa502;--radius:12px;
}
body{
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  background:var(--bg);color:var(--text);
  min-height:100vh;min-height:100dvh;
  padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left);
}
.container{max-width:480px;margin:0 auto;padding:8px}

/* Status bar */
.status-bar{
  display:flex;align-items:center;justify-content:space-between;
  padding:10px 12px;background:var(--surface);border-radius:var(--radius);
  margin-bottom:8px;position:sticky;top:0;z-index:10;
}
.status-dot{width:10px;height:10px;border-radius:50%;margin-right:8px;flex-shrink:0}
.status-dot.connected{background:var(--accent);box-shadow:0 0 6px var(--accent)}
.status-dot.disconnected{background:var(--danger);box-shadow:0 0 6px var(--danger)}
.status-bar .title{font-weight:600;font-size:15px;flex:1}
.status-bar .people{
  background:var(--accent2);color:#fff;border-radius:20px;
  padding:2px 10px;font-size:13px;font-weight:600;
}

/* Camera tabs */
.cam-tabs{display:flex;gap:6px;margin-bottom:8px;overflow-x:auto;padding:2px 0}
.cam-tab{
  background:var(--surface);border:none;color:var(--text2);
  padding:6px 14px;border-radius:20px;font-size:13px;cursor:pointer;
  white-space:nowrap;
}
.cam-tab.active{background:var(--accent);color:#000;font-weight:600}

/* Camera feed */
.feed-container{
  position:relative;border-radius:var(--radius);overflow:hidden;
  background:#000;margin-bottom:8px;aspect-ratio:16/9;
}
.feed-container img{width:100%;height:100%;object-fit:contain;display:block}
.feed-overlay{
  position:absolute;bottom:0;left:0;right:0;
  background:linear-gradient(transparent,rgba(0,0,0,.7));
  padding:20px 12px 8px;font-size:12px;color:#ccc;
}
.feed-fps{position:absolute;top:8px;right:8px;background:rgba(0,0,0,.6);
  color:var(--accent);padding:2px 8px;border-radius:6px;font-size:11px;font-family:monospace}
.feed-error{
  position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  background:rgba(0,0,0,.8);color:var(--danger);font-size:14px;display:none;
}
.fullscreen-overlay{
  position:fixed;inset:0;background:#000;z-index:100;display:none;
  align-items:center;justify-content:center;cursor:pointer;
}
.fullscreen-overlay img{max-width:100%;max-height:100%;object-fit:contain}

/* Cards */
.card{background:var(--surface);border-radius:var(--radius);padding:12px;margin-bottom:8px}
.card-title{font-size:12px;color:var(--text2);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px}
.card-body{font-size:14px;line-height:1.5}

/* Scene */
.scene-summary{font-size:14px;line-height:1.5;color:var(--text)}
.objects{display:flex;flex-wrap:wrap;gap:4px;margin-top:8px}
.obj-pill{
  background:var(--surface2);padding:3px 10px;border-radius:12px;
  font-size:12px;color:var(--text2);
}

/* Rules */
.rule-item{
  display:flex;align-items:center;justify-content:space-between;
  padding:8px 0;border-bottom:1px solid var(--surface2);
}
.rule-item:last-child{border-bottom:none}
.rule-name{font-size:13px;font-weight:500}
.rule-condition{font-size:12px;color:var(--text2);margin-top:2px}
.rule-badge{
  font-size:11px;padding:2px 8px;border-radius:8px;
  background:var(--surface2);color:var(--text2);
}
.rule-badge.high{background:var(--warn);color:#000}
.rule-badge.critical{background:var(--danger);color:#fff}

/* Alerts */
.alert-item{padding:6px 0;border-bottom:1px solid var(--surface2);font-size:13px}
.alert-item:last-child{border-bottom:none}
.alert-time{color:var(--text2);font-size:11px}
.alert-msg{margin-top:2px}

/* Health */
.health-row{display:flex;align-items:center;gap:8px;font-size:13px}
.health-indicator{width:8px;height:8px;border-radius:50%}
.health-indicator.ok{background:var(--accent)}
.health-indicator.error{background:var(--danger)}

/* Login */
.login-card{
  position:fixed;inset:0;background:var(--bg);z-index:200;
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  padding:20px;
}
.login-card h2{margin-bottom:16px;font-size:18px}
.login-card input{
  width:100%;max-width:300px;padding:12px;border-radius:var(--radius);
  border:1px solid var(--surface2);background:var(--surface);color:var(--text);
  font-size:16px;text-align:center;margin-bottom:12px;
}
.login-card button{
  padding:10px 24px;border-radius:var(--radius);border:none;
  background:var(--accent);color:#000;font-weight:600;font-size:15px;cursor:pointer;
}
.empty{color:var(--text2);font-size:13px;font-style:italic}

/* Pending cameras */
.pending-banner{
  background:linear-gradient(135deg,#1a2a3a,#1a1a2e);
  border:1px solid var(--accent);border-radius:var(--radius);
  padding:12px;margin-bottom:8px;animation:pendingPulse 2s ease-in-out infinite;
}
@keyframes pendingPulse{0%,100%{border-color:var(--accent)}50%{border-color:var(--accent2)}}
.pending-header{font-size:13px;color:var(--accent);font-weight:600;margin-bottom:8px}
.pending-item{
  display:flex;align-items:center;justify-content:space-between;
  padding:8px 0;border-bottom:1px solid var(--surface2);
}
.pending-item:last-child{border-bottom:none}
.pending-info{flex:1}
.pending-name{font-size:14px;font-weight:500}
.pending-details{font-size:11px;color:var(--text2);margin-top:2px}
.pending-actions{display:flex;gap:6px}
.pending-btn{
  border:none;border-radius:8px;padding:6px 14px;
  font-size:13px;font-weight:600;cursor:pointer;
  transition:opacity .2s;
}
.pending-btn:hover{opacity:.8}
.pending-btn.accept{background:var(--accent);color:#000}
.pending-btn.reject{background:var(--danger);color:#fff}
.pending-toast{
  position:fixed;bottom:20px;left:50%;transform:translateX(-50%);
  background:var(--accent);color:#000;padding:10px 20px;border-radius:20px;
  font-size:14px;font-weight:600;z-index:50;opacity:0;
  transition:opacity .3s;pointer-events:none;
}
.pending-toast.show{opacity:1}
</style>
</head>
<body>

<div class="login-card" id="loginCard" style="display:none">
  <h2>Physical MCP</h2>
  <input type="text" id="tokenInput" placeholder="Enter access token" autocomplete="off">
  <button onclick="submitToken()">Connect</button>
</div>

<div class="fullscreen-overlay" id="fullscreen" onclick="exitFullscreen()">
  <img id="fullscreenImg">
</div>

<div class="container" id="app" style="display:none">
  <!-- Status Bar -->
  <div class="status-bar">
    <div class="status-dot disconnected" id="statusDot"></div>
    <div class="title" id="cameraTitle">Physical MCP</div>
    <div class="people" id="peopleCount" style="display:none">0</div>
  </div>

  <!-- Camera Tabs (multi-camera) -->
  <div class="cam-tabs" id="camTabs" style="display:none"></div>

  <!-- Pending Cameras -->
  <div class="pending-banner" id="pendingBanner" style="display:none">
    <div class="pending-header">📹 New cameras detected</div>
    <div id="pendingList"></div>
  </div>
  <div class="pending-toast" id="pendingToast"></div>

  <!-- Camera Feed -->
  <div class="feed-container" onclick="enterFullscreen()">
    <img id="feedImg" alt="Camera feed">
    <div class="feed-fps" id="feedFps">-- fps</div>
    <div class="feed-error" id="feedError">Connection lost</div>
  </div>

  <!-- Scene Summary -->
  <div class="card">
    <div class="card-title">Scene</div>
    <div class="scene-summary" id="sceneSummary"><span class="empty">Waiting for analysis...</span></div>
    <div class="objects" id="objectsList"></div>
  </div>

  <!-- Watch Rules -->
  <div class="card" id="rulesCard" style="display:none">
    <div class="card-title">Watch Rules</div>
    <div id="rulesList"></div>
  </div>

  <!-- Recent Alerts -->
  <div class="card" id="alertsCard" style="display:none">
    <div class="card-title">Recent Alerts</div>
    <div id="alertsList"></div>
  </div>

  <!-- Health -->
  <div class="card">
    <div class="card-title">Camera Health</div>
    <div class="health-row" id="healthRow">
      <div class="health-indicator" id="healthDot"></div>
      <span id="healthText">Connecting...</span>
    </div>
  </div>
</div>

<script>
// ── Config ──────────────────────────────────────────
const BASE = location.origin;
let token = new URLSearchParams(location.search).get('token')
  || sessionStorage.getItem('pmcp_token') || '';
let activeCam = '';
let cameras = [];
let frameInterval = null;
let sseSource = null;
let connected = false;
let frameErrors = 0;
let frameCount = 0;
let fpsStart = Date.now();

// Clean token from URL bar
if (location.search.includes('token=')) {
  history.replaceState({}, '', '/dashboard');
}

// ── Init ────────────────────────────────────────────
async function init() {
  if (token) sessionStorage.setItem('pmcp_token', token);

  // Test connection
  try {
    const r = await apiFetch('/scene');
    if (r.status === 401) { showLogin(); return; }
    const data = await r.json();
    cameras = Object.keys(data.cameras || {});
    if (cameras.length === 0) cameras = ['usb:0'];
    activeCam = cameras[0];
  } catch (e) {
    // Server might be down — try anyway
    cameras = ['usb:0'];
    activeCam = 'usb:0';
  }

  document.getElementById('app').style.display = 'block';
  document.getElementById('loginCard').style.display = 'none';

  setupCameraTabs();
  startFrameLoop();
  startSSE();
  refreshAll();
  setInterval(refreshAll, 30000);
}

// ── Auth ────────────────────────────────────────────
function showLogin() {
  document.getElementById('loginCard').style.display = 'flex';
  document.getElementById('app').style.display = 'none';
}

function submitToken() {
  token = document.getElementById('tokenInput').value.trim();
  if (token) {
    sessionStorage.setItem('pmcp_token', token);
    init();
  }
}

function apiFetch(path) {
  const sep = path.includes('?') ? '&' : '?';
  const url = token ? `${BASE}${path}${sep}token=${token}` : `${BASE}${path}`;
  return fetch(url);
}

// ── Camera Tabs ─────────────────────────────────────
function setupCameraTabs() {
  if (cameras.length <= 1) return;
  const tabs = document.getElementById('camTabs');
  tabs.style.display = 'flex';
  tabs.innerHTML = cameras.map(id =>
    `<button class="cam-tab${id === activeCam ? ' active' : ''}" onclick="switchCam('${id}')">${id}</button>`
  ).join('');
}

function switchCam(id) {
  activeCam = id;
  setupCameraTabs();
  frameErrors = 0;
  document.getElementById('feedError').style.display = 'none';
  refreshScene();
}

// ── Frame Loop (iOS-compatible) ─────────────────────
function startFrameLoop() {
  if (frameInterval) clearInterval(frameInterval);
  const img = document.getElementById('feedImg');
  const FPS = 3;

  frameInterval = setInterval(() => {
    const url = `${BASE}/frame/${activeCam}?quality=50&t=${Date.now()}` +
      (token ? `&token=${token}` : '');
    const newImg = new Image();
    newImg.onload = () => {
      img.src = newImg.src;
      frameErrors = 0;
      frameCount++;
      document.getElementById('feedError').style.display = 'none';
      updateFps();
    };
    newImg.onerror = () => {
      frameErrors++;
      if (frameErrors > 5) {
        document.getElementById('feedError').style.display = 'flex';
      }
    };
    newImg.src = url;
  }, 1000 / FPS);
}

function updateFps() {
  const now = Date.now();
  const elapsed = (now - fpsStart) / 1000;
  if (elapsed >= 2) {
    const fps = (frameCount / elapsed).toFixed(1);
    document.getElementById('feedFps').textContent = `${fps} fps`;
    frameCount = 0;
    fpsStart = now;
  }
}

// ── SSE ─────────────────────────────────────────────
function startSSE() {
  if (sseSource) sseSource.close();
  const url = `${BASE}/events` + (token ? `?token=${token}` : '');
  sseSource = new EventSource(url);

  sseSource.addEventListener('scene', (e) => {
    try {
      const d = JSON.parse(e.data);
      updateScene(d);
    } catch {}
  });

  sseSource.addEventListener('change', (e) => {
    try {
      const d = JSON.parse(e.data);
      prependAlert({
        timestamp: d.timestamp || new Date().toISOString(),
        message: d.description || 'Scene changed',
        camera_id: d.camera_id || activeCam,
      });
    } catch {}
  });

  sseSource.onopen = () => setConnected(true);
  sseSource.onerror = () => {
    setConnected(false);
    // Auto-reconnect is built into EventSource
  };
}

// Reconnect SSE when page becomes visible (iOS kills background connections)
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) {
    startSSE();
    refreshAll();
  }
});

// ── Data Refresh ────────────────────────────────────
async function refreshAll() {
  await Promise.all([refreshScene(), refreshHealth(), refreshRules(), refreshAlerts(), refreshPending()]);
}

async function refreshScene() {
  try {
    const r = await apiFetch(`/scene/${activeCam}`);
    if (r.ok) {
      const d = await r.json();
      updateScene(d);
    }
  } catch {}
}

function updateScene(d) {
  const summary = d.summary || '';
  const objects = d.objects_present || d.objects || [];
  const people = d.people_count ?? 0;

  const el = document.getElementById('sceneSummary');
  el.textContent = summary || 'No analysis yet';
  if (!summary) el.innerHTML = '<span class="empty">Waiting for analysis...</span>';

  const objEl = document.getElementById('objectsList');
  objEl.innerHTML = objects.map(o => `<span class="obj-pill">${o}</span>`).join('');

  const pEl = document.getElementById('peopleCount');
  if (people > 0) {
    pEl.textContent = `${people} ${people === 1 ? 'person' : 'people'}`;
    pEl.style.display = 'inline-block';
  } else {
    pEl.style.display = 'none';
  }

  document.getElementById('cameraTitle').textContent = activeCam;
}

async function refreshHealth() {
  try {
    const r = await apiFetch('/health');
    if (!r.ok) return;
    const d = await r.json();
    const cam = d.cameras?.[activeCam];
    const dot = document.getElementById('healthDot');
    const txt = document.getElementById('healthText');
    if (cam) {
      const ok = cam.status === 'running' && cam.consecutive_errors === 0;
      dot.className = `health-indicator ${ok ? 'ok' : 'error'}`;
      const lastFrame = cam.last_frame_at ? timeAgo(cam.last_frame_at) : 'never';
      txt.textContent = ok ? `Running \u2014 last frame ${lastFrame}` : `Error: ${cam.last_error || 'unknown'}`;
      setConnected(ok);
    }
  } catch { setConnected(false); }
}

async function refreshRules() {
  try {
    const r = await apiFetch('/rules');
    if (!r.ok) return;
    const d = await r.json();
    const rules = d.rules || [];
    const card = document.getElementById('rulesCard');
    const list = document.getElementById('rulesList');
    if (rules.length === 0) { card.style.display = 'none'; return; }
    card.style.display = 'block';
    list.innerHTML = rules.map(r => `
      <div class="rule-item">
        <div>
          <div class="rule-name">${esc(r.name)}</div>
          <div class="rule-condition">${esc(r.condition)}</div>
        </div>
        <div class="rule-badge ${r.priority}">${r.priority}</div>
      </div>
    `).join('');
  } catch {}
}

async function refreshAlerts() {
  try {
    const r = await apiFetch('/alerts?limit=10');
    if (!r.ok) return;
    const d = await r.json();
    const events = d.events || [];
    const card = document.getElementById('alertsCard');
    const list = document.getElementById('alertsList');
    if (events.length === 0) { card.style.display = 'none'; return; }
    card.style.display = 'block';
    list.innerHTML = events.slice(0, 10).map(a => `
      <div class="alert-item">
        <div class="alert-time">${formatTime(a.timestamp)} \u2014 ${esc(a.camera_name || a.camera_id || '')}</div>
        <div class="alert-msg">${esc(a.message || a.rule_name || 'Alert')}</div>
      </div>
    `).join('');
  } catch {}
}

function prependAlert(a) {
  const card = document.getElementById('alertsCard');
  const list = document.getElementById('alertsList');
  card.style.display = 'block';
  const html = `<div class="alert-item">
    <div class="alert-time">${formatTime(a.timestamp)} \u2014 ${esc(a.camera_id)}</div>
    <div class="alert-msg">${esc(a.message)}</div>
  </div>`;
  list.insertAdjacentHTML('afterbegin', html);
  // Keep max 10
  while (list.children.length > 10) list.lastChild.remove();
}

// ── Fullscreen ──────────────────────────────────────
function enterFullscreen() {
  const img = document.getElementById('feedImg');
  document.getElementById('fullscreenImg').src = img.src;
  document.getElementById('fullscreen').style.display = 'flex';
}
function exitFullscreen() {
  document.getElementById('fullscreen').style.display = 'none';
}

// ── Status ──────────────────────────────────────────
function setConnected(state) {
  connected = state;
  document.getElementById('statusDot').className = `status-dot ${state ? 'connected' : 'disconnected'}`;
}

// ── Helpers ─────────────────────────────────────────
function esc(s) {
  const d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}
function formatTime(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});
  } catch { return iso; }
}
function timeAgo(iso) {
  try {
    const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 5) return 'just now';
    if (s < 60) return `${s}s ago`;
    if (s < 3600) return `${Math.floor(s/60)}m ago`;
    return `${Math.floor(s/3600)}h ago`;
  } catch { return 'unknown'; }
}

// ── Pending Cameras ─────────────────────────────────
async function refreshPending() {
  try {
    const r = await apiFetch('/cameras/pending');
    if (!r.ok) return;
    const list = await r.json();
    const banner = document.getElementById('pendingBanner');
    const container = document.getElementById('pendingList');
    if (!list || list.length === 0) {
      banner.style.display = 'none';
      return;
    }
    banner.style.display = 'block';
    container.innerHTML = list.map(c => `
      <div class="pending-item" id="pending-${esc(c.camera_id)}">
        <div class="pending-info">
          <div class="pending-name">${esc(c.name || c.camera_id)}</div>
          <div class="pending-details">
            ${c.firmware_version ? 'Firmware ' + esc(c.firmware_version) + ' · ' : ''}
            Registered ${timeAgo(c.registered_at)}
          </div>
        </div>
        <div class="pending-actions">
          <button class="pending-btn accept" onclick="acceptCamera('${esc(c.camera_id)}')">Accept</button>
          <button class="pending-btn reject" onclick="rejectCamera('${esc(c.camera_id)}')">Reject</button>
        </div>
      </div>
    `).join('');
  } catch {}
}

async function acceptCamera(id) {
  try {
    const sep = token ? `?token=${token}` : '';
    const r = await fetch(`${BASE}/cameras/${id}/accept${sep}`, {method:'POST'});
    if (r.ok) {
      showToast('Camera added!');
      refreshPending();
      // Refresh camera list after a moment
      setTimeout(() => { refreshAll(); setupCameraTabs(); }, 1000);
    } else {
      const d = await r.json().catch(() => ({}));
      showToast(d.message || 'Failed to accept');
    }
  } catch { showToast('Connection error'); }
}

async function rejectCamera(id) {
  try {
    const sep = token ? `?token=${token}` : '';
    const r = await fetch(`${BASE}/cameras/${id}/reject${sep}`, {method:'POST'});
    if (r.ok) {
      showToast('Camera rejected');
      refreshPending();
    } else {
      showToast('Failed to reject');
    }
  } catch { showToast('Connection error'); }
}

function showToast(msg) {
  const el = document.getElementById('pendingToast');
  el.textContent = msg;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 2500);
}

// Poll pending cameras every 5 seconds
setInterval(refreshPending, 5000);

// ── Start ───────────────────────────────────────────
init();
</script>
</body>
</html>"""
