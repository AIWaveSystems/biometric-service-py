"use strict";

const $ = (id) => document.getElementById(id);
const TOKEN_KEY = "portal_token";
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
    setToken(null);
    showGate();
    toast("Sesión expirada. Vuelve a entrar.");
    throw new Error(data.detail || "No autorizado");
  }
  if (!r.ok) throw new Error(data.detail || `Error ${r.status}`);
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
    if (!r.ok) throw new Error(data.detail || "Credenciales invalidas");
    setToken(data.access_token);
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
  setToken(null);
  showGate();
});

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    $("tab-" + tab.dataset.tab).classList.add("active");
    if (tab.dataset.tab === "gestion") loadUsers();
  });
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

syncLoginUI();
if (getToken()) enterApp();
else showGate();
