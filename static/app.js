"use strict";

const $ = (id) => document.getElementById(id);
const TOKEN_KEY = "portal_token";
const PORTAL_USER_KEY = "portal_user";
const PORTAL_UUID_KEY = "portal_uuid";
const ENROLL_SECONDS = 5.0;
const VERIFY_SECONDS = 3.0;
const BURST_SECONDS = 2.6;
const BURST_FPS = 11;

function getToken() {
  return sessionStorage.getItem(TOKEN_KEY);
}

function setToken(t) {
  if (t) sessionStorage.setItem(TOKEN_KEY, t);
  else sessionStorage.removeItem(TOKEN_KEY);
}

function setPortalSession(data) {
  if (data?.access_token) setToken(data.access_token);
  if (data?.username) sessionStorage.setItem(PORTAL_USER_KEY, data.username);
  if (data?.uuid) sessionStorage.setItem(PORTAL_UUID_KEY, data.uuid);
  updateWhoami();
}

function clearPortalSession() {
  setToken(null);
  sessionStorage.removeItem(PORTAL_USER_KEY);
  sessionStorage.removeItem(PORTAL_UUID_KEY);
  updateWhoami();
}

function updateWhoami() {
  const el = $("whoami");
  if (!el) return;
  const user = sessionStorage.getItem(PORTAL_USER_KEY);
  el.textContent = user ? `Operador: ${user}` : "";
}

function parseJwt(token) {
  try {
    const payload = token.split(".")[1];
    return JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/")));
  } catch {
    return null;
  }
}

function restorePortalSession() {
  const token = getToken();
  if (!token) return;
  if (!sessionStorage.getItem(PORTAL_USER_KEY) || !sessionStorage.getItem(PORTAL_UUID_KEY)) {
    const p = parseJwt(token);
    if (p?.sub) sessionStorage.setItem(PORTAL_USER_KEY, p.sub);
    if (p?.uid) sessionStorage.setItem(PORTAL_UUID_KEY, p.uid);
  }
  updateWhoami();
}

async function validatePortalSession() {
  const token = getToken();
  if (!token) return false;
  try {
    const me = await api("/api/portal/me");
    if (me.username) sessionStorage.setItem(PORTAL_USER_KEY, me.username);
    if (me.uuid) sessionStorage.setItem(PORTAL_UUID_KEY, me.uuid);
    updateWhoami();
    return true;
  } catch {
    clearPortalSession();
    showGate();
    return false;
  }
}

function showGate() {
  $("app").hidden = true;
  $("gate").hidden = false;
}

function enterApp() {
  $("gate").hidden = true;
  $("app").hidden = false;
}

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), 3500);
}

function showResult(el, type, text) {
  el.className = "result " + type;
  el.textContent = text;
}

function formatError(detail) {
  if (Array.isArray(detail)) return detail.map((e) => e.msg || JSON.stringify(e)).join("; ");
  if (typeof detail === "object" && detail !== null) return JSON.stringify(detail);
  return detail || "Error desconocido";
}

function fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

async function api(url, opts = {}) {
  const headers = Object.assign({}, opts.headers);
  const token = getToken();
  if (token) headers["Authorization"] = "Bearer " + token;
  const r = await fetch(url, Object.assign({}, opts, { headers }));
  let data;
  try {
    data = await r.json();
  } catch {
    data = { detail: r.statusText };
  }
  if (r.status === 401) {
    clearPortalSession();
    showGate();
    toast("Sesión expirada. Vuelve a entrar.");
    throw new Error(formatError(data.detail) || "No autorizado");
  }
  if (!r.ok) throw new Error(formatError(data.detail) || `Error ${r.status}`);
  return data;
}

function apiJson(url, body) {
  return api(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function setState(el, text, cls) {
  el.textContent = text;
  el.className = "state" + (cls ? " " + cls : "");
}

function setBtnText(btn, text) {
  const span = btn.querySelector("span");
  if (span) span.textContent = text;
}

const playbackUrls = {};

function showPlayback(kind, blob) {
  const panel = $(kind + "-playback");
  const audio = $(kind + "-audio");
  if (playbackUrls[kind]) URL.revokeObjectURL(playbackUrls[kind]);
  playbackUrls[kind] = URL.createObjectURL(blob);
  audio.src = playbackUrls[kind];
  audio.load();
  panel.hidden = false;
}

function clearPlayback(kind) {
  const panel = $(kind + "-playback");
  const audio = $(kind + "-audio");
  audio.pause();
  audio.removeAttribute("src");
  audio.load();
  if (playbackUrls[kind]) {
    URL.revokeObjectURL(playbackUrls[kind]);
    delete playbackUrls[kind];
  }
  panel.hidden = true;
}

$("gate-btn").addEventListener("click", async () => {
  const err = $("gate-error");
  err.hidden = true;
  const username = $("gate-user").value.trim();
  const password = $("gate-pass").value;
  try {
    const r = await fetch("/api/portal/auth", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(formatError(data.detail) || "Credenciales invalidas");
    setPortalSession(data);
    enterApp();
    toast("Bienvenido al portal");
  } catch (e) {
    err.hidden = false;
    err.className = "result err";
    err.textContent = "❌ " + e.message;
  }
});

$("gate-pass").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("gate-btn").click();
});

$("logout-btn").addEventListener("click", () => {
  closeAllCameras();
  clearPlayback("reg");
  clearPlayback("login");
  clearPortalSession();
  showGate();
});

function activateTab(name) {
  document.querySelectorAll(".tab").forEach((t) => {
    t.classList.toggle("active", t.dataset.tab === name);
  });
  document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
  const panel = $("tab-" + name);
  if (panel) panel.classList.add("active");
  if (name === "gestion") loadUsers();
  if (name === "clientes") loadClients();
  if (name === "operadores") loadOperators();
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => activateTab(tab.dataset.tab));
});

let camStreams = {};

async function openCamera(video) {
  if (camStreams[video.id]) return;
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: "user", width: 640, height: 480 },
  });
  camStreams[video.id] = stream;
  video.srcObject = stream;
  await video.play().catch(() => {});
}

function closeCamera(video) {
  const s = camStreams[video.id];
  if (s) {
    s.getTracks().forEach((t) => t.stop());
    delete camStreams[video.id];
    video.srcObject = null;
  }
}

function closeAllCameras() {
  Object.keys(camStreams).forEach((id) => closeCamera($(id)));
}

function capturePhoto(video, canvas) {
  canvas.width = video.videoWidth || 640;
  canvas.height = video.videoHeight || 480;
  canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
  return new Promise((res) => canvas.toBlob((b) => res(b), "image/jpeg", 0.92));
}

async function captureBurst(video, canvas, seconds, fps) {
  const frames = [];
  const interval = 1000 / fps;
  const start = performance.now();
  const total = seconds * 1000;
  await new Promise((resolve) => {
    const tick = async () => {
      if (performance.now() - start >= total) return resolve();
      canvas.width = video.videoWidth || 640;
      canvas.height = video.videoHeight || 480;
      canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise((r) => canvas.toBlob(r, "image/jpeg", 0.85));
      if (blob) frames.push(blob);
      setTimeout(tick, interval);
    };
    tick();
  });
  return frames;
}

let audioCtx = null;
let audioStream = null;
let recorder = null;
let audioSamples = [];

function floatToWav(samples, sampleRate) {
  const n = samples.length;
  const buf = new ArrayBuffer(44 + n * 2);
  const dv = new DataView(buf);
  const w = (off, str) => {
    for (let i = 0; i < str.length; i++) dv.setUint8(off + i, str.charCodeAt(i));
  };
  w(0, "RIFF");
  dv.setUint32(4, 36 + n * 2, true);
  w(8, "WAVE");
  w(12, "fmt ");
  dv.setUint32(16, 16, true);
  dv.setUint16(20, 1, true);
  dv.setUint16(22, 1, true);
  dv.setUint32(24, sampleRate, true);
  dv.setUint32(28, sampleRate * 2, true);
  dv.setUint16(32, 2, true);
  dv.setUint16(34, 16, true);
  w(36, "data");
  dv.setUint32(40, n * 2, true);
  let off = 44;
  for (let i = 0; i < n; i++) {
    const v = Math.max(-1, Math.min(1, samples[i]));
    dv.setInt16(off, v * 32767, true);
    off += 2;
  }
  return new Blob([buf], { type: "audio/wav" });
}

async function startVoice() {
  if (audioCtx) return;
  audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  await audioCtx.resume();
  const src = audioCtx.createMediaStreamSource(audioStream);
  recorder = audioCtx.createScriptProcessor(4096, 1, 1);
  audioSamples = [];
  recorder.onaudioprocess = (e) => {
    audioSamples.push(new Float32Array(e.inputBuffer.getChannelData(0)));
  };
  src.connect(recorder);
  recorder.connect(audioCtx.destination);
}

function stopVoice() {
  if (recorder) {
    recorder.disconnect();
    recorder = null;
  }
  if (audioCtx) {
    audioCtx.close();
    audioCtx = null;
  }
  if (audioStream) {
    audioStream.getTracks().forEach((t) => t.stop());
    audioStream = null;
  }
}

function peakLevel(samples) {
  let peak = 0;
  for (const chunk of samples) {
    for (let i = 0; i < chunk.length; i++) {
      const v = Math.abs(chunk[i]);
      if (v > peak) peak = v;
    }
  }
  return peak;
}

async function recordVoice(seconds) {
  if (audioCtx) return null;
  await startVoice();
  const sr = audioCtx.sampleRate;
  const target = Math.floor(seconds * sr);
  return new Promise((resolve) => {
    const timer = setInterval(() => {
      const total = audioSamples.reduce((s, a) => s + a.length, 0);
      if (total >= target) {
        clearInterval(timer);
        const peak = peakLevel(audioSamples);
        stopVoice();
        const all = new Float32Array(total);
        let off = 0;
        for (const chunk of audioSamples) {
          all.set(chunk, off);
          off += chunk.length;
        }
        resolve({ blob: floatToWav(all, sr), peak, seconds: total / sr });
      }
    }, 100);
  });
}

async function handleRecording(kind, seconds, stateEl, btn, label) {
  btn.disabled = true;
  setBtnText(btn, "Grabando…");
  setState(stateEl, `Grabando ${seconds}s, habla ahora…`, "busy");
  try {
    const result = await recordVoice(seconds);
    if (result) {
      showPlayback(kind, result.blob);
      if (result.peak < 0.02) {
        setState(stateEl, "Volumen muy bajo, repite", "err");
        toast("Apenas se detecta señal. Acércate al micrófono y repite.");
      } else {
        setState(stateEl, `Grabado ${result.seconds.toFixed(1)}s`, "ok");
      }
      return result.blob;
    }
  } catch {
    setState(stateEl, "Micrófono no disponible", "err");
    clearPlayback(kind);
  } finally {
    btn.disabled = false;
    setBtnText(btn, label);
  }
  return null;
}

$("reg-open-camera").addEventListener("click", async () => {
  try {
    await openCamera($("reg-video"));
    $("reg-take-photo").hidden = false;
    setBtnText($("reg-open-camera"), "Cámara activa");
  } catch {
    toast("No se pudo acceder a la cámara");
  }
});

const POSE_HINTS = [
  "Foto 1 de 3: mira de frente, centrado.",
  "Foto 2 de 3: acércate o aléjate un poco de la cámara y vuelve a mirar de frente.",
  "Foto 3 de 3: cambia la iluminación o inclina levemente la cabeza, siempre mirando a la cámara.",
];

$("reg-take-photo").addEventListener("click", async () => {
  try {
    if (!window._regPhotos) window._regPhotos = [];
    if (window._regPhotos.length >= 3) return;
    const blob = await capturePhoto($("reg-video"), $("reg-canvas"));
    window._regPhotos.push(blob);
    const n = window._regPhotos.length;
    setState($("reg-photo-state"), `Fotos: ${n}/3`, "ok");
    if (n < 3) {
      toast(POSE_HINTS[n]);
    } else {
      closeCamera($("reg-video"));
      setBtnText($("reg-open-camera"), "Reactivar cámara");
      $("reg-take-photo").hidden = true;
      toast("3 fotos capturadas");
    }
  } catch {
    toast("Error al capturar");
  }
});

$("reg-record").addEventListener("click", async () => {
  const blob = await handleRecording(
    "reg",
    ENROLL_SECONDS,
    $("reg-voice-state"),
    $("reg-record"),
    `Grabar voz (${ENROLL_SECONDS}s)`
  );
  if (blob) window._regVoice = blob;
});

$("reg-btn").addEventListener("click", async () => {
  const btn = $("reg-btn");
  if (btn.disabled) return;
  const username = $("reg-username").value.trim();
  const password = $("reg-password").value || null;
  const out = $("reg-result");
  if (!username) return showResult(out, "err", "Ingresa un nombre de usuario");
  const photos = window._regPhotos || [];
  if (!photos.length && !window._regVoice && !password) {
    return showResult(out, "err", "Registra al menos una biometría o una contraseña");
  }
  const fd = new FormData();
  fd.append("username", username);
  if (password) fd.append("password", password);
  photos.forEach((b, i) => fd.append("images", b, `face${i}.jpg`));
  if (window._regVoice) fd.append("audio", window._regVoice, "voice.wav");

  btn.disabled = true;
  setBtnText(btn, "Registrando…");
  try {
    const res = await api("/api/users/register", { method: "POST", body: fd });
    const parts = [];
    if (res.password) parts.push("Contraseña");
    const caras = res.registered.find((s) => s.startsWith("cara"));
    if (caras) parts.push(`Biometría facial (${caras.replace("cara x", "")} plantillas)`);
    const descartadas = res.registered.find((s) => s.includes("identicas"));
    if (res.registered.includes("voz")) parts.push("Biometría de voz");
    showResult(out, "ok", `Usuario "${res.username}" registrado.\nMétodos: ${parts.join(", ")}.\nYa puedes iniciar sesión.`);
    window._regPhotos = null;
    window._regVoice = null;
    clearPlayback("reg");
    setState($("reg-photo-state"), "Sin fotos", "");
    setState($("reg-voice-state"), "Sin grabación", "");
  } catch (e) {
    showResult(out, "err", e.message);
  } finally {
    btn.disabled = false;
    setBtnText(btn, "Registrar");
  }
});

function syncLoginUI() {
  const mode = $("login-mode").value;
  $("login-password-field").hidden = mode !== "password";
  $("login-face-sensor").hidden = !["face", "both"].includes(mode);
  $("login-voice-sensor").hidden = !["voice", "both"].includes(mode);
  $("login-result").textContent = "";
  $("login-result").className = "result";
}

$("login-mode").addEventListener("change", syncLoginUI);

$("login-take-photo").addEventListener("click", async () => {
  const video = $("login-video");
  if (!camStreams[video.id]) {
    try {
      await openCamera(video);
      setBtnText($("login-take-photo"), "Capturar (parpadea)");
      toast("Mira a la cámara, presiona el botón y parpadea una vez");
    } catch {
      toast("No se pudo acceder a la cámara");
    }
    return;
  }
  const btn = $("login-take-photo");
  btn.disabled = true;
  setBtnText(btn, "Capturando…");
  setState($("login-photo-state"), "Grabando, parpadea…", "busy");
  try {
    const frames = await captureBurst($("login-video"), $("login-canvas"), BURST_SECONDS, BURST_FPS);
    window._loginFrames = frames;
    setState($("login-photo-state"), `Capturado (${frames.length} frames)`, "ok");
  } catch {
    setState($("login-photo-state"), "Error de captura", "err");
  }
  btn.disabled = false;
  setBtnText(btn, "Capturar (parpadea)");
  closeCamera(video);
});

$("login-record").addEventListener("click", async () => {
  const blob = await handleRecording(
    "login",
    VERIFY_SECONDS,
    $("login-voice-state"),
    $("login-record"),
    `Grabar voz (${VERIFY_SECONDS}s)`
  );
  if (blob) window._loginVoice = blob;
});

function sessionLine(res) {
  if (!res.access_token) return "";
  const minutes = Math.round((res.expires_in || 0) / 60);
  return `\nSesión iniciada (token válido ${minutes} min): ${res.access_token.slice(0, 24)}…`;
}

$("login-btn").addEventListener("click", async () => {
  const username = $("login-username").value.trim();
  const mode = $("login-mode").value;
  const out = $("login-result");
  const btn = $("login-btn");
  if (!username) return showResult(out, "err", "Ingresa tu nombre de usuario");

  btn.disabled = true;
  setBtnText(btn, "Verificando…");
  try {
    if (mode === "password") {
      const r = await apiJson("/api/auth/login", {
        username,
        password: $("login-password").value,
      });
      showResult(out, "ok", `Autenticado correctamente.${sessionLine(r)}`);
      return;
    }

    let faceInfo = "";
    if (mode === "face" || mode === "both") {
      if (!window._loginFrames || !window._loginFrames.length) {
        return showResult(out, "err", "Captura primero el parpadeo (botón 'Capturar (parpadea)')");
      }
      const fd = new FormData();
      fd.append("username", username);
      window._loginFrames.forEach((b, i) => fd.append("frames", b, `f${i}.jpg`));
      const r = await api("/api/face/login", { method: "POST", body: fd });
      window._loginFrames = null;
      setState($("login-photo-state"), "Sin captura", "");
      if (!r.verified) {
        return showResult(
          out,
          "err",
          `Rostro NO verificado.\n${r.reason || ""}\n` +
            `Liveness: ${r.liveness_passed ? "detectado" : "no detectado"} · ` +
            `Similitud: ${r.similarity} (umbral ${r.threshold}) · Caras: ${r.n_faces}/${r.n_frames}`
        );
      }
      faceInfo = `Rostro verificado (liveness OK · similitud ${r.similarity})`;
      if (mode === "face") {
        return showResult(out, "ok", `${faceInfo}\nBienvenido, ${username}.${sessionLine(r)}`);
      }
      showResult(out, "info", faceInfo + "\nVerificando voz…");
    }

    if (mode === "voice" || mode === "both") {
      if (!window._loginVoice) return showResult(out, "err", "Graba tu voz primero");
      const fd = new FormData();
      fd.append("username", username);
      fd.append("audio", window._loginVoice, "voice.wav");
      const r = await api("/api/voice/verify", { method: "POST", body: fd });
      window._loginVoice = null;
      clearPlayback("login");
      setState($("login-voice-state"), "Sin grabación", "");
      if (!r.verified) {
        const ratio = r.ratio != null ? ` · Ratio: ${r.ratio} (umbral ${r.ratio_threshold})` : "";
        return showResult(
          out,
          "err",
          `Voz NO verificada.\n${r.reason || ""}\n` +
            `z=${r.z_score} (umbral ${r.z_threshold})${ratio}`
        );
      }
      const prefix = faceInfo ? faceInfo + "\n" : "";
      showResult(out, "ok", `${prefix}Bienvenido, ${username}. Autenticación completada.${sessionLine(r)}`);
    }
  } catch (e) {
    showResult(out, "err", e.message);
  } finally {
    btn.disabled = false;
    setBtnText(btn, "Entrar");
  }
});

async function loadUsers() {
  const tbody = $("users-table").querySelector("tbody");
  tbody.innerHTML = '<tr><td colspan="5">Cargando…</td></tr>';
  try {
    const users = await api("/api/users");
    tbody.innerHTML = "";
    for (const u of users) {
      const tr = document.createElement("tr");
      const badge = (ok) => `<span class="badge ${ok ? "yes" : "no"}">${ok ? "Sí" : "No"}</span>`;
      const del = document.createElement("button");
      del.className = "btn danger";
      del.innerHTML =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>' +
        "<span>Eliminar</span>";
      del.addEventListener("click", async () => {
        if (!confirm(`¿Eliminar al usuario ${u.username}?`)) return;
        await api(`/api/users/${encodeURIComponent(u.username)}`, { method: "DELETE" });
        toast(`Usuario ${u.username} eliminado`);
        loadUsers();
      });
      tr.innerHTML = `
        <td>${u.username}</td>
        <td>${badge(u.has_password)}</td>
        <td>${u.face_templates.length ? badge(true) + ` (${u.face_templates.length})` : badge(false)}</td>
        <td>${u.voice_templates.length ? badge(true) + ` (${u.voice_templates.length})` : badge(false)}</td>`;
      const td = document.createElement("td");
      td.appendChild(del);
      tr.appendChild(td);
      tbody.appendChild(tr);
    }
    if (!users.length) tbody.innerHTML = '<tr><td colspan="5">Sin usuarios registrados</td></tr>';
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="5">Error: ${e.message}</td></tr>`;
  }
}

$("refresh-users").addEventListener("click", loadUsers);

function clientStatus(c) {
  if (!c.active) return '<span class="badge no">Revocada</span>';
  if (c.expired) return '<span class="badge no">Expirada</span>';
  return '<span class="badge yes">Activa</span>';
}

function showKeyResult(el, apiKey, aviso) {
  el.hidden = false;
  el.className = "result ok";
  el.innerHTML =
    `<strong>API key generada.</strong> ${aviso || "Copia y guarda la clave ahora."}` +
    `<div class="key-box">${apiKey}</div>`;
}

async function loadClients() {
  const tbody = $("clients-table").querySelector("tbody");
  tbody.innerHTML = '<tr><td colspan="7">Cargando…</td></tr>';
  try {
    const clients = await api("/api/clients");
    tbody.innerHTML = "";
    for (const c of clients) {
      const tr = document.createElement("tr");
      const scopes = (c.scopes || []).join(", ");
      const tdActions = document.createElement("td");
      const row = document.createElement("div");
      row.className = "btn-row";
      if (c.active) {
        const revoke = document.createElement("button");
        revoke.className = "btn sm danger";
        revoke.textContent = "Revocar";
        revoke.addEventListener("click", async () => {
          if (!confirm(`¿Revocar la API key de "${c.name}"?`)) return;
          await api(`/api/clients/${c.uuid}/revoke`, { method: "POST" });
          toast(`Cliente ${c.name} revocado`);
          loadClients();
        });
        row.appendChild(revoke);
      }
      const rotate = document.createElement("button");
      rotate.className = "btn sm";
      rotate.textContent = "Rotar";
      rotate.addEventListener("click", async () => {
        if (!confirm(`¿Generar nueva clave para "${c.name}"? La anterior dejará de funcionar.`)) return;
        const res = await api(`/api/clients/${c.uuid}/rotate`, { method: "POST" });
        const out = $("client-create-result");
        showKeyResult(out, res.api_key, res.aviso);
        toast(`Clave rotada para ${c.name}`);
        loadClients();
      });
      row.appendChild(rotate);
      tdActions.appendChild(row);
      tr.innerHTML = `
        <td>${c.name}</td>
        <td><code>lbs_${c.key_prefix}_…</code></td>
        <td>${scopes}</td>
        <td>${clientStatus(c)}</td>
        <td>${fmtDate(c.expires_at)}</td>
        <td>${fmtDate(c.last_used_at)}</td>`;
      tr.appendChild(tdActions);
      tbody.appendChild(tr);
    }
    if (!clients.length) tbody.innerHTML = '<tr><td colspan="7">Sin clientes API</td></tr>';
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7">Error: ${e.message}</td></tr>`;
  }
}

$("refresh-clients").addEventListener("click", loadClients);

$("client-create-btn").addEventListener("click", async () => {
  const btn = $("client-create-btn");
  const out = $("client-create-result");
  out.hidden = true;
  const name = $("client-name").value.trim();
  const scopes = [];
  if ($("scope-auth").checked) scopes.push("auth");
  if ($("scope-enroll").checked) scopes.push("enroll");
  if ($("scope-admin").checked) scopes.push("admin");
  const daysRaw = $("client-days").value.trim();
  const body = { name, scopes };
  if (daysRaw) body.expires_in_days = parseInt(daysRaw, 10);
  if (!name) return toast("Indica un nombre para el cliente");
  if (!scopes.length) return toast("Selecciona al menos un permiso");
  btn.disabled = true;
  try {
    const res = await apiJson("/api/clients", body);
    showKeyResult(out, res.api_key, res.aviso);
    $("client-name").value = "";
    $("client-days").value = "";
    toast(`Cliente "${res.name}" creado`);
    loadClients();
  } catch (e) {
    out.hidden = false;
    out.className = "result err";
    out.textContent = e.message;
  } finally {
    btn.disabled = false;
  }
});

async function loadOperators() {
  const tbody = $("operators-table").querySelector("tbody");
  tbody.innerHTML = '<tr><td colspan="4">Cargando…</td></tr>';
  try {
    const ops = await api("/api/portal/users");
    tbody.innerHTML = "";
    const me = sessionStorage.getItem(PORTAL_USER_KEY);
    for (const u of ops) {
      const tr = document.createElement("tr");
      const status = u.active
        ? '<span class="badge yes">Activo</span>'
        : '<span class="badge no">Inactivo</span>';
      const bootstrap = u.is_bootstrap ? ' <span class="badge yes">bootstrap</span>' : "";
      const tdActions = document.createElement("td");
      if (u.active && u.username !== me) {
        const disable = document.createElement("button");
        disable.className = "btn sm danger";
        disable.textContent = "Desactivar";
        disable.addEventListener("click", async () => {
          if (!confirm(`¿Desactivar al operador "${u.username}"?`)) return;
          await api(`/api/portal/users/${u.uuid}/disable`, { method: "POST" });
          toast(`Operador ${u.username} desactivado`);
          loadOperators();
        });
        tdActions.appendChild(disable);
      } else if (u.username === me) {
        tdActions.textContent = "—";
      } else {
        tdActions.textContent = "—";
      }
      tr.innerHTML = `
        <td>${u.username}${bootstrap}</td>
        <td>${status}</td>
        <td>${fmtDate(u.last_login_at)}</td>`;
      tr.appendChild(tdActions);
      tbody.appendChild(tr);
    }
    if (!ops.length) tbody.innerHTML = '<tr><td colspan="4">Sin operadores</td></tr>';
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="4">Error: ${e.message}</td></tr>`;
  }
}

$("refresh-operators").addEventListener("click", loadOperators);

$("op-create-btn").addEventListener("click", async () => {
  const btn = $("op-create-btn");
  const out = $("op-create-result");
  out.hidden = true;
  const username = $("op-username").value.trim();
  const password = $("op-password").value;
  if (!username || !password) return toast("Completa usuario y contraseña");
  btn.disabled = true;
  try {
    const res = await apiJson("/api/portal/users", { username, password });
    out.hidden = false;
    out.className = "result ok";
    out.textContent = `Operador "${res.username}" creado.`;
    $("op-username").value = "";
    $("op-password").value = "";
    toast(`Operador ${res.username} creado`);
    loadOperators();
  } catch (e) {
    out.hidden = false;
    out.className = "result err";
    out.textContent = e.message;
  } finally {
    btn.disabled = false;
  }
});

$("op-change-pass-btn").addEventListener("click", async () => {
  const btn = $("op-change-pass-btn");
  const out = $("op-pass-result");
  out.hidden = true;
  const uuid = sessionStorage.getItem(PORTAL_UUID_KEY);
  if (!uuid) return toast("Vuelve a iniciar sesión en el portal");
  const current_password = $("op-current-pass").value;
  const new_password = $("op-new-pass").value;
  if (!current_password || !new_password) return toast("Completa ambas contraseñas");
  btn.disabled = true;
  try {
    await apiJson(`/api/portal/users/${uuid}/password`, { current_password, new_password });
    out.hidden = false;
    out.className = "result ok";
    out.textContent = "Contraseña actualizada.";
    $("op-current-pass").value = "";
    $("op-new-pass").value = "";
    toast("Contraseña actualizada");
  } catch (e) {
    out.hidden = false;
    out.className = "result err";
    out.textContent = e.message;
  } finally {
    btn.disabled = false;
  }
});

function updateClientExample() {
  const el = $("client-example");
  if (!el) return;
  const base = window.location.origin;
  el.textContent =
    `curl -X POST ${base}/api/face/login \\\n` +
    `  -H "X-API-Key: lbs_xxxxxxxxxxxx_secreto" \\\n` +
    `  -F "username=maria" \\\n` +
    `  -F "frames=@f0.jpg"`;
}

syncLoginUI();
restorePortalSession();
updateClientExample();
if (getToken()) {
  validatePortalSession().then((ok) => {
    if (ok) enterApp();
    else showGate();
  });
} else {
  showGate();
}
