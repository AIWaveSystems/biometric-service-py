"use strict";

const $ = (id) => document.getElementById(id);
const TOKEN_KEY = "portal_token";
const PORTAL_USER_KEY = "portal_user";
const PORTAL_UUID_KEY = "portal_uuid";
const ENROLL_SECONDS = 5.0;
const VERIFY_SECONDS = 3.0;
const BURST_SECONDS = 2.6;
const BURST_FPS = 11;
const BLINK_CUE_AT = 0.45;
const BLINK_COUNTDOWN = 3;

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
    returnToGate();
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
  const name = hashTab();
  if (name) applyTab(name);
}

function returnToGate(message) {
  closeAllCameras();
  stopVoice();
  ["reg", "login", "challenge", "enroll", "analizar"].forEach(clearPlayback);
  window._regPhotos = null;
  window._regVoice = null;
  window._digitEnroll = null;
  window._challenge = null;
  window._loginFrames = null;
  window._loginVoice = null;
  clearPortalSession();
  showGate();
  $("gate-user").focus();
  if (message) toast(message);
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
    returnToGate("Sesión expirada. Vuelve a entrar.");
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
  returnToGate();
});

const TABS = ["login", "registro", "gestion", "clientes", "operadores"];

function hashTab() {
  const name = decodeURIComponent(location.hash.replace(/^#/, ""));
  return TABS.includes(name) ? name : null;
}

function applyTab(name) {
  document.querySelectorAll(".tab").forEach((t) => {
    t.classList.toggle("active", t.dataset.tab === name);
  });
  document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
  const panel = $("tab-" + name);
  if (panel) panel.classList.add("active");
  if (name === "gestion") {
    loadUsers();
    loadVoiceSystemBanner();
  }
  if (name === "clientes") loadClients();
  if (name === "operadores") loadOperators();
}

function activateTab(name) {
  applyTab(name);
  if (hashTab() !== name) location.hash = encodeURIComponent(name);
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => activateTab(tab.dataset.tab));
});

window.addEventListener("hashchange", () => {
  const name = hashTab();
  const visible = document.querySelector(".panel.active");
  if (name && (!visible || visible.id !== "tab-" + name)) applyTab(name);
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

async function captureBurst(video, canvas, seconds, fps, onCue) {
  const frames = [];
  const interval = 1000 / fps;
  const count = Math.max(1, Math.round(seconds * fps));
  const start = performance.now();
  const cueAt = seconds * 1000 * BLINK_CUE_AT;
  let cued = false;
  for (let i = 0; i < count; i++) {
    const elapsed = performance.now() - start;
    if (!cued && elapsed >= cueAt) {
      cued = true;
      if (onCue) onCue();
    }
    canvas.width = video.videoWidth || 640;
    canvas.height = video.videoHeight || 480;
    canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((r) => canvas.toBlob(r, "image/jpeg", 0.85));
    if (blob) frames.push(blob);
    const target = start + (i + 1) * interval;
    const wait = target - performance.now();
    if (wait > 0) await new Promise((r) => setTimeout(r, wait));
  }
  return frames;
}

function showCue(text, cls) {
  const cue = $("login-cue");
  if (!cue) return;
  cue.textContent = text;
  cue.className = "cue" + (cls ? " " + cls : "");
  cue.hidden = false;
}

function hideCue() {
  const cue = $("login-cue");
  if (cue) cue.hidden = true;
}

async function countdown(seconds) {
  for (let n = seconds; n > 0; n--) {
    showCue(`Mantén los ojos abiertos · ${n}`, "wait");
    await new Promise((r) => setTimeout(r, 1000));
  }
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
  audioStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      echoCancellation: false,
      noiseSuppression: false,
      autoGainControl: false,
      channelCount: 1,
    },
  });
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
    if (!result) {
      setState(stateEl, "No se pudo grabar", "err");
      clearPlayback(kind);
      return null;
    }
    showPlayback(kind, result.blob);
    if (result.peak < 0.02) {
      setState(stateEl, "Volumen muy bajo, repite", "err");
      toast("Apenas se detecta señal. Acércate al micrófono y repite.");
      return null;
    }
    setState(stateEl, `Grabado ${result.seconds.toFixed(1)}s`, "ok");
    return result.blob;
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
  window._regVoice = null;
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
  $("login-challenge-sensor").hidden = mode !== "challenge";
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
  setState($("login-photo-state"), "Preparando…", "busy");
  try {
    await countdown(BLINK_COUNTDOWN);
    setState($("login-photo-state"), "Grabando…", "busy");
    showCue("Grabando · ojos abiertos", "wait");
    const frames = await captureBurst(
      $("login-video"),
      $("login-canvas"),
      BURST_SECONDS,
      BURST_FPS,
      () => showCue("PARPADEA AHORA", "go")
    );
    window._loginFrames = frames;
    setState($("login-photo-state"), `Capturado (${frames.length} frames)`, "ok");
  } catch {
    setState($("login-photo-state"), "Error de captura", "err");
  }
  hideCue();
  btn.disabled = false;
  setBtnText(btn, "Capturar (parpadea)");
  closeCamera(video);
});

$("login-record").addEventListener("click", async () => {
  window._loginVoice = null;
  const blob = await handleRecording(
    "login",
    VERIFY_SECONDS,
    $("login-voice-state"),
    $("login-record"),
    `Grabar voz (${VERIFY_SECONDS}s)`
  );
  if (blob) window._loginVoice = blob;
});

const ENROLL_DIGITS = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"];

$("enroll-digits").addEventListener("click", async () => {
  const username = $("reg-username").value.trim();
  const btn = $("enroll-digits");
  const state = $("enroll-digits-state");
  const out = $("enroll-digits-result");
  if (!username) return toast("Escribe arriba el nombre de usuario");
  if (audioCtx) return toast("Ya hay una grabación en curso");

  btn.disabled = true;
  $("enroll-digits-send").disabled = true;
  window._digitEnroll = null;
  clearPlayback("enroll");
  out.textContent = "";
  out.className = "result";
  setBtnText(btn, "Grabando…");
  try {
    const result = await recordPrompted(ENROLL_DIGITS, $("enroll-cue"));
    if (!result) {
      setState(state, "No se pudo grabar", "err");
      return;
    }
    showPlayback("enroll", result.blob);
    if (result.peak < 0.02) {
      setState(state, "Volumen muy bajo, repite", "err");
      toast("Apenas se detecta señal. Acércate al micrófono y repite.");
      return;
    }
    window._digitEnroll = result.blob;
    $("enroll-digits-send").disabled = false;
    setState(state, `Grabado ${result.seconds.toFixed(1)}s · revisa y sube`, "ok");
  } catch {
    setState(state, "Error de grabación", "err");
  } finally {
    btn.disabled = false;
    setBtnText(btn, "Grabar los 10 dígitos");
  }
});

$("enroll-digits-send").addEventListener("click", async () => {
  const username = $("reg-username").value.trim();
  const btn = $("enroll-digits-send");
  const out = $("enroll-digits-result");
  if (!window._digitEnroll) return;

  btn.disabled = true;
  setBtnText(btn, "Subiendo…");
  try {
    const fd = new FormData();
    fd.append("username", username);
    fd.append("digits", ENROLL_DIGITS.join(","));
    fd.append("audio", window._digitEnroll, "digits.wav");
    const r = await api("/api/voice/digits/enroll", { method: "POST", body: fd });
    window._digitEnroll = null;
    clearPlayback("enroll");
    setState($("enroll-digits-state"), "Sin matrícula", "");
    showResult(
      out,
      "ok",
      `Dígitos matriculados para ${r.username}: ${r.digits.join(" ")}\n` +
        `${r.n_segments} locuciones en ${r.duration_seconds}s. ` +
        `Ya puede entrar con "Voz + dígitos".`
    );
  } catch (e) {
    showResult(out, "err", e.message);
    btn.disabled = false;
  } finally {
    setBtnText(btn, "Subir matrícula");
  }
});

const CHALLENGE_LEAD = 1.5;
const CHALLENGE_PER_DIGIT = 1.5;
const CHALLENGE_TAIL = 1.0;

async function recordPrompted(digits, cueEl) {
  const show = (text, cls) => {
    cueEl.textContent = text;
    cueEl.className = "digit-cue" + (cls ? " " + cls : "");
  };
  const total = CHALLENGE_LEAD + digits.length * CHALLENGE_PER_DIGIT + CHALLENGE_TAIL;
  const pending = recordVoice(total);
  if (!pending) return null;
  const start = performance.now();
  const at = (s) =>
    new Promise((r) => setTimeout(r, Math.max(0, start + s * 1000 - performance.now())));

  show("Prepárate…", "wait");
  for (let i = 0; i < digits.length; i++) {
    await at(CHALLENGE_LEAD + i * CHALLENGE_PER_DIGIT);
    show(digits[i], "go");
    at(CHALLENGE_LEAD + i * CHALLENGE_PER_DIGIT + CHALLENGE_PER_DIGIT * 0.55).then(() =>
      show("···", "wait")
    );
  }
  await at(CHALLENGE_LEAD + digits.length * CHALLENGE_PER_DIGIT);
  show("Listo", "wait");
  const result = await pending;
  show("···", "");
  return result;
}

$("login-challenge").addEventListener("click", async () => {
  const username = $("login-username").value.trim();
  const btn = $("login-challenge");
  const state = $("login-challenge-state");
  if (!username) return toast("Ingresa primero tu nombre de usuario");
  if (audioCtx) return toast("Ya hay una grabación en curso");

  btn.disabled = true;
  window._challenge = null;
  clearPlayback("challenge");
  setState(state, "Pidiendo desafío…", "busy");
  try {
    const fd = new FormData();
    fd.append("username", username);
    const ch = await api("/api/voice/challenge", { method: "POST", body: fd });

    setBtnText(btn, "Grabando…");
    setState(state, `Di: ${ch.digits.join(" · ")}`, "busy");
    const result = await recordPrompted(ch.digits, $("challenge-cue"));

    if (!result) {
      setState(state, "No se pudo grabar", "err");
      return;
    }
    showPlayback("challenge", result.blob);
    if (result.peak < 0.02) {
      setState(state, "Volumen muy bajo, repite", "err");
      toast("Apenas se detecta señal. Acércate al micrófono y repite.");
      return;
    }
    window._challenge = {
      id: ch.challenge_id,
      blob: result.blob,
      digits: ch.digits,
      expiresAt: Date.now() + ch.expires_in * 1000,
    };
    setState(state, `Grabado (${ch.digits.join(" ")}) · pulsa Entrar`, "ok");
  } catch (e) {
    setState(state, "Error", "err");
    showResult($("login-result"), "err", e.message);
  } finally {
    btn.disabled = false;
    setBtnText(btn, "Pedir dígitos y grabar");
  }
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

    if (mode === "challenge") {
      if (!window._challenge) {
        return showResult(out, "err", "Pide primero los dígitos y grábalos");
      }
      if (Date.now() > window._challenge.expiresAt) {
        window._challenge = null;
        return showResult(out, "err", "El desafío caducó. Pide uno nuevo y vuelve a grabar.");
      }
      const { id, blob, digits } = window._challenge;
      const fd = new FormData();
      fd.append("username", username);
      fd.append("challenge_id", id);
      fd.append("audio", blob, "challenge.wav");
      const r = await api("/api/voice/challenge/verify", { method: "POST", body: fd });
      window._challenge = null;
      clearPlayback("challenge");
      setState($("login-challenge-state"), "Sin desafío", "");
      if (!r.verified) {
        return showResult(
          out,
          "err",
          `Acceso denegado.\n${r.reason || ""}\n` +
            `Identidad: ${r.identity_ok ? "OK" : "no coincide"} (${r.scoring} ${r.score}) · ` +
            `Contenido: ${r.content_ok ? "OK" : "no coincide"}\n` +
            `Pedidos: ${digits.join(" ")} · Reconocidos: ${r.recognised.join(" ")} ` +
            `(${r.n_segments} locuciones, ${r.n_errors} errores)`
        );
      }
      return showResult(
        out,
        "ok",
        `Voz y dígitos verificados (${digits.join(" ")}).\n` +
          `Bienvenido, ${username}.${sessionLine(r)}`
      );
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
        const usable =
          r.n_usable != null
            ? ` · Usables: ${r.n_usable}/${r.n_frames}` +
              (r.n_moved ? ` (${r.n_moved} con movimiento)` : "")
            : "";
        return showResult(
          out,
          "err",
          `Rostro NO verificado.\n${r.reason || ""}\n` +
            `Liveness: ${r.liveness_passed ? "detectado" : "no detectado"} · ` +
            `Similitud: ${r.similarity} (umbral ${r.threshold}) · ` +
            `Caras: ${r.n_faces}/${r.n_frames}${usable}`
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

const COLS = 7;
const listState = {
  users: { page: 1, limit: 25 },
  clients: { page: 1, limit: 25 },
  operators: { page: 1, limit: 25 },
};

function listUrl(path, key) {
  const state = listState[key];
  const search = $(key + "-search").value.trim();
  const query = new URLSearchParams({
    page: state.page,
    limit: state.limit,
    sort_by: $(key + "-sort").value,
    sort_dir: $(key + "-direction").value,
  });
  if (search) query.set("search", search);
  return `${path}?${query}`;
}

function renderPagination(key, data, load) {
  const target = $(key + "-pagination");
  target.innerHTML = "";
  if (!data || data.pages <= 1) return;
  const previous = document.createElement("button");
  previous.className = "btn sm";
  previous.textContent = "Anterior";
  previous.disabled = data.page <= 1;
  previous.addEventListener("click", () => {
    listState[key].page -= 1;
    load();
  });
  const next = document.createElement("button");
  next.className = "btn sm";
  next.textContent = "Siguiente";
  next.disabled = data.page >= data.pages;
  next.addEventListener("click", () => {
    listState[key].page += 1;
    load();
  });
  const label = document.createElement("span");
  label.textContent = `Página ${data.page} de ${data.pages} · ${data.total} registros`;
  target.append(previous, label, next);
}

function setupListControls(key, load) {
  [$(key + "-sort"), $(key + "-direction")].forEach((control) => {
    control.addEventListener("change", () => {
      listState[key].page = 1;
      load();
    });
  });
  const search = $(key + "-search");
  search.addEventListener("input", () => {
    clearTimeout(setupListControls[key]);
    setupListControls[key] = setTimeout(() => {
      listState[key].page = 1;
      load();
    }, 250);
  });
}
const badge = (ok, extra) =>
  `<span class="badge ${ok ? "yes" : "no"}">${ok ? "Sí" : "No"}</span>` +
  (extra ? ` <span class="muted-inline">${extra}</span>` : "");
const warnBadge = (text) => `<span class="badge warn">${text}</span>`;

async function loadVoiceSystemBanner() {
  const el = $("voice-system-banner");
  if (!el) return;
  try {
    const s = await api("/api/voice/system");
    const cola = `Desafío de dígitos: ${s.challenge_digits} por intento, mín. ${s.challenge_min_enrolled} matriculados.`;
    if (!s.embedding_model) {
      el.className = "system-banner warn";
      el.textContent =
        `Voz: falta el modelo de locutor. Ejecuta "python scripts/fetch_models.py" y reinicia. ` +
        `Mientras tanto se usa MFCC+GMM, mucho menos preciso y dependiente de cuánta gente haya registrada.`;
    } else if (s.scoring_active === "embedding") {
      el.className = "system-banner ok";
      el.textContent =
        `Voz: modo embedding (CAM++), umbral ${s.embedding_threshold}. ` +
        `${s.voice_users} usuario(s) con voz. No hace falta registrar más gente: el modelo ya trae ` +
        `su población de fondo. ${cola}`;
    } else if (s.users_without_embedding > 0) {
      el.className = "system-banner warn";
      el.textContent =
        `Voz: ${s.users_without_embedding} de ${s.voice_users} usuario(s) sin embedding. ` +
        `Esos usan MFCC+GMM, más débil. Regraba su voz desde Editar → Voz para pasarlos a CAM++. ${cola}`;
    } else {
      el.className = "system-banner warn";
      el.textContent = `Voz: no hay usuarios con plantilla de voz todavía. ${cola}`;
    }
    el.hidden = false;
  } catch {
    el.hidden = true;
  }
}

let editando = null;

function userPath(uuid, suffix = "") {
  return `/api/users/by-uuid/${encodeURIComponent(uuid)}${suffix}`;
}

function buildEditor(u, refrescar) {
  const box = document.createElement("div");
  box.className = "editor";

  const out = document.createElement("div");
  out.className = "result";

  const ok = (msg) => {
    showResult(out, "ok", msg);
    refrescar();
  };
  const err = (e) => showResult(out, "err", e.message);

  const seccion = (titulo, hint) => {
    const s = document.createElement("div");
    s.className = "editor-block";
    s.innerHTML = `<h4>${titulo}</h4>` + (hint ? `<p class="hint">${hint}</p>` : "");
    box.appendChild(s);
    return s;
  };

  const fila = (parent) => {
    const f = document.createElement("div");
    f.className = "editor-row";
    parent.appendChild(f);
    return f;
  };

  const boton = (texto, clase, accion) => {
    const b = document.createElement("button");
    b.className = "btn " + (clase || "");
    b.innerHTML = `<span>${texto}</span>`;
    b.addEventListener("click", async () => {
      b.disabled = true;
      const previo = b.textContent;
      setBtnText(b, "…");
      try {
        await accion();
      } catch (e) {
        err(e);
      } finally {
        b.disabled = false;
        setBtnText(b, previo);
      }
    });
    return b;
  };

  const ident = seccion(
    "Identidad",
    `UUID <code>${u.uuid}</code> — es lo que guardan los sistemas clientes. ` +
      `Renombrar NO lo cambia, así que sus vínculos se conservan.`
  );
  const fIdent = fila(ident);
  const inNombre = document.createElement("input");
  inNombre.type = "text";
  inNombre.value = u.username;
  inNombre.placeholder = "Nuevo nombre de usuario";
  inNombre.autocomplete = "off";
  inNombre.setAttribute("aria-label", "Renombrar usuario");
  fIdent.appendChild(inNombre);
  fIdent.appendChild(
    boton("Renombrar", "", async () => {
      const nuevo = inNombre.value.trim();
      if (!nuevo || nuevo === u.username) return;
      const fd = new FormData();
      fd.append("new_username", nuevo);
      const r = await api(userPath(u.uuid, "/rename"), { method: "POST", body: fd });
      ok(`Renombrado: ${r.previous} → ${r.username}`);
    })
  );

  const clave = seccion(
    "Contraseña",
    u.has_password
      ? "Tiene contraseña. Puedes cambiarla o quitarla y dejarlo solo con biometría."
      : "No tiene contraseña. Solo puede entrar con biometría."
  );
  const fClave = fila(clave);
  const inClave = document.createElement("input");
  inClave.type = "password";
  inClave.placeholder = "Nueva contraseña (mín. 6)";
  inClave.autocomplete = "new-password";
  inClave.setAttribute("aria-label", "Nueva contraseña del usuario");
  fClave.appendChild(inClave);
  fClave.appendChild(
    boton("Guardar", "primary", async () => {
      if (inClave.value.length < 6) throw new Error("Mínimo 6 caracteres");
      const fd = new FormData();
      fd.append("password", inClave.value);
      await api(userPath(u.uuid, "/password"), { method: "POST", body: fd });
      inClave.value = "";
      ok("Contraseña actualizada");
    })
  );
  if (u.has_password) {
    fClave.appendChild(
      boton("Quitar", "danger", async () => {
        if (!confirm(`¿Quitar la contraseña de ${u.username}?`)) return;
        await api(userPath(u.uuid, "/password"), { method: "POST", body: new FormData() });
        ok("Contraseña retirada: ahora solo entra con biometría");
      })
    );
  }

  const rostro = seccion(
    `Rostro — ${u.face_templates.length} plantilla(s)`,
    u.face_templates.length >= 3
      ? "Varias plantillas en distintas luces reducen falsos rechazos."
      : "<strong>Recomendado:</strong> al menos 3 plantillas en distintas luces y ángulos."
  );
  if (u.face_templates.length) {
    const chips = document.createElement("div");
    chips.className = "chips";
    for (const t of u.face_templates) {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.innerHTML = `#${t.id} <button title="Borrar esta plantilla">✕</button>`;
      chip.querySelector("button").addEventListener("click", async () => {
        if (u.face_templates.length === 1 && !confirm("Es la única plantilla facial. ¿Borrarla?"))
          return;
        try {
          await api(`/api/face/templates/${t.id}`, { method: "DELETE" });
          ok(`Plantilla facial #${t.id} borrada`);
        } catch (e) {
          err(e);
        }
      });
      chips.appendChild(chip);
    }
    rostro.appendChild(chips);
  }
  const fRostro = fila(rostro);
  const inFotos = document.createElement("input");
  inFotos.type = "file";
  inFotos.accept = "image/*";
  inFotos.multiple = true;
  inFotos.setAttribute("aria-label", "Elegir fotos de rostro");
  inFotos.title = "Elige una o varias fotos de rostro";
  fRostro.appendChild(inFotos);
  fRostro.appendChild(
    boton("Subir fotos", "primary", async () => {
      if (!inFotos.files.length) throw new Error("Elige al menos una foto");
      const fd = new FormData();
      for (const f of inFotos.files) fd.append("images", f, f.name);
      const r = await api(userPath(u.uuid, "/faces"), { method: "POST", body: fd });
      inFotos.value = "";
      ok(
        `Añadidas ${r.added} plantilla(s). Total: ${r.total_templates}.` +
          (r.redundant ? ` ${r.redundant} descartada(s) por redundancia.` : "") +
          (r.without_face ? ` ${r.without_face} sin cara detectable.` : "")
      );
    })
  );

  const camWrap = document.createElement("div");
  camWrap.className = "editor-cam";
  camWrap.hidden = true;
  const video = document.createElement("video");
  video.id = `edit-video-${u.uuid}`;
  video.autoplay = true;
  video.playsInline = true;
  video.muted = true;
  const canvas = document.createElement("canvas");
  canvas.hidden = true;
  camWrap.appendChild(video);
  camWrap.appendChild(canvas);
  rostro.appendChild(camWrap);

  const pendientes = [];
  const estadoCam = document.createElement("span");
  estadoCam.className = "state";
  const fCam = fila(rostro);
  fCam.appendChild(
    boton("Usar cámara", "", async () => {
      if (camStreams[video.id]) return;
      camWrap.hidden = false;
      await openCamera(video);
      setState(estadoCam, "Cámara activa", "busy");
    })
  );
  fCam.appendChild(
    boton("Tomar foto", "", async () => {
      if (!camStreams[video.id]) throw new Error("Activa primero la cámara");
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvas.getContext("2d").drawImage(video, 0, 0);
      const blob = await new Promise((r) => canvas.toBlob(r, "image/jpeg", 0.92));
      pendientes.push(blob);
      setState(estadoCam, `${pendientes.length} foto(s) en cola`, "ok");
    })
  );
  fCam.appendChild(
    boton("Subir capturas", "primary", async () => {
      if (!pendientes.length) throw new Error("No hay fotos capturadas");
      const fd = new FormData();
      pendientes.forEach((b, i) => fd.append("images", b, `cam${i}.jpg`));
      const r = await api(userPath(u.uuid, "/faces"), { method: "POST", body: fd });
      pendientes.length = 0;
      closeCamera(video);
      camWrap.hidden = true;
      setState(estadoCam, "", "");
      ok(`Añadidas ${r.added} plantilla(s) desde la cámara. Total: ${r.total_templates}.`);
    })
  );
  fCam.appendChild(estadoCam);

  const voz = seccion(
    `Voz — ${u.voice_templates.length ? "matriculada" : "sin matricular"}`,
    "Registrar de nuevo REEMPLAZA la plantilla anterior: solo se guarda una por usuario."
  );
  const fVoz = fila(voz);
  const inAudio = document.createElement("input");
  inAudio.type = "file";
  inAudio.accept = "audio/wav";
  inAudio.setAttribute("aria-label", "Elegir archivo WAV de voz");
  inAudio.title = "Elige un archivo WAV con la voz del usuario";
  fVoz.appendChild(inAudio);
  fVoz.appendChild(
    boton("Subir voz", "primary", async () => {
      if (!inAudio.files.length) throw new Error("Elige un WAV");
      const fd = new FormData();
      fd.append("username", u.username);
      fd.append("audio", inAudio.files[0], inAudio.files[0].name);
      const r = await api("/api/voice/register", { method: "POST", body: fd });
      inAudio.value = "";
      ok(`Voz registrada: ${r.duration_seconds}s, ${r.n_frames} frames`);
    })
  );
  const estadoVoz = document.createElement("span");
  estadoVoz.className = "state";
  const fVoz2 = fila(voz);
  fVoz2.appendChild(
    boton(`Grabar ${ENROLL_SECONDS}s`, "", async () => {
      if (audioCtx) throw new Error("Ya hay una grabación en curso");
      setState(estadoVoz, "Grabando, habla ahora…", "busy");
      const res = await recordVoice(ENROLL_SECONDS);
      if (!res) throw new Error("No se pudo grabar");
      if (res.peak < 0.02) {
        setState(estadoVoz, "Volumen muy bajo, repite", "err");
        return;
      }
      const fd = new FormData();
      fd.append("username", u.username);
      fd.append("audio", res.blob, "voz.wav");
      const r = await api("/api/voice/register", { method: "POST", body: fd });
      setState(estadoVoz, "", "");
      ok(`Voz registrada: ${r.duration_seconds}s, ${r.n_frames} frames`);
    })
  );
  fVoz2.appendChild(estadoVoz);
  if (u.voice_templates.length) {
    fVoz2.appendChild(
      boton("Borrar voz", "danger", async () => {
        if (!confirm(`¿Borrar la plantilla de voz de ${u.username}?`)) return;
        await api(`/api/voice/templates/${u.voice_templates[0].id}`, { method: "DELETE" });
        ok("Plantilla de voz borrada");
      })
    );
  }

  const dig = seccion(
    `Dígitos — ${u.digits.length ? u.digits.join(" ") : "sin matricular"}`,
    u.digits_challenge_ready
      ? "Puede entrar con <strong>Voz + dígitos</strong> (resiste grabaciones previas)."
      : !u.digits_cmvn_ok && u.digits.length
        ? "<strong>Matrícula antigua:</strong> vuelve a grabar los 10 dígitos (falta normalización CMVN)."
        : u.digits.length >= 5
          ? "Faltan dígitos o la matrícula no está completa para el desafío."
          : "Sin al menos 5 dígitos matriculados no puede usarse el desafío."
  );
  const estadoDig = document.createElement("span");
  estadoDig.className = "state";
  const fDig = fila(dig);
  fDig.appendChild(
    boton("Grabar los 10 dígitos", "primary", async () => {
      if (audioCtx) throw new Error("Ya hay una grabación en curso");
      const escenario = document.createElement("div");
      escenario.className = "digit-stage";
      const cue = document.createElement("div");
      cue.className = "digit-cue";
      cue.textContent = "···";
      escenario.appendChild(cue);
      dig.appendChild(escenario);
      try {
        const res = await recordPrompted(ENROLL_DIGITS, cue);
        if (!res) throw new Error("No se pudo grabar");
        if (res.peak < 0.02) throw new Error("Volumen muy bajo, repite");
        const fd = new FormData();
        fd.append("username", u.username);
        fd.append("digits", ENROLL_DIGITS.join(","));
        fd.append("audio", res.blob, "digits.wav");
        const r = await api("/api/voice/digits/enroll", { method: "POST", body: fd });
        ok(`Dígitos matriculados: ${r.digits.join(" ")} (${r.n_segments} locuciones)`);
      } finally {
        escenario.remove();
      }
    })
  );
  if (u.digits.length) {
    fDig.appendChild(
      boton("Borrar dígitos", "danger", async () => {
        if (!confirm(`¿Borrar la matrícula de dígitos de ${u.username}?`)) return;
        const r = await api(`/api/voice/digits/${encodeURIComponent(u.username)}`, {
          method: "DELETE",
        });
        ok(`${r.deleted} dígito(s) borrados`);
      })
    );
  }
  fDig.appendChild(estadoDig);

  box.appendChild(out);
  return { box, cleanup: () => closeCamera(video) };
}

$("analizar-btn").addEventListener("click", async () => {
  const btn = $("analizar-btn");
  const estado = $("analizar-state");
  const out = $("analizar-result");
  if (audioCtx) return toast("Ya hay una grabación en curso");

  btn.disabled = true;
  setBtnText(btn, "Grabando…");
  setState(estado, `Grabando ${ENROLL_SECONDS}s, habla ahora…`, "busy");
  out.textContent = "";
  out.className = "result";
  try {
    const res = await recordVoice(ENROLL_SECONDS);
    if (!res) throw new Error("No se pudo grabar");
    showPlayback("analizar", res.blob);
    $("analizar-descargar").href = playbackUrls["analizar"];
    $("analizar-descargar").download = `voz_${Date.now()}.wav`;

    const pico = (20 * Math.log10(Math.max(res.peak, 1e-9))).toFixed(1);
    setState(estado, `Grabado ${res.seconds.toFixed(1)}s · pico ${pico} dBFS`, "ok");

    const fd = new FormData();
    fd.append("audio", res.blob, "voz.wav");
    const r = await api("/api/voice/identify", { method: "POST", body: fd });

    const filas = (r.ranking || [])
      .map((x) => `  ${x.username.padEnd(16)} ${x.similarity.toFixed(4)}`)
      .join("\n");
    const veredicto = r.username
      ? `Se parece a "${r.username}" (${r.similarity})`
      : "No se parece a ninguna cuenta registrada";
    showResult(
      out,
      r.ambiguous ? "err" : "info",
      `${veredicto}\nUmbral: ${r.threshold} · pico ${pico} dBFS\n\n` +
        `Similitud contra cada cuenta:\n${filas || "  (no hay cuentas con voz)"}\n\n` +
        (r.ambiguous
          ? `AMBIGUA: encaja en ${r.matches.length} cuentas (${r.matches.join(", ")}). ` +
            `Esas cuentas comparten voz.`
          : "Por encima del umbral solo puede haber una cuenta.")
    );
  } catch (e) {
    setState(estado, "Error", "err");
    showResult(out, "err", e.message);
  } finally {
    btn.disabled = false;
    setBtnText(btn, `Grabar y analizar (${ENROLL_SECONDS}s)`);
  }
});

async function loadUsers() {
  const tbody = $("users-table").querySelector("tbody");
  tbody.innerHTML = `<tr><td colspan="${COLS}">Cargando…</td></tr>`;
  try {
    const data = await api(listUrl("/api/users", "users"));
    const users = data.items || data;
    tbody.innerHTML = "";
    for (const u of users) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${u.username}</td>
        <td>${u.owner ? `${u.owner.name} <code>lbs_${u.owner.key_prefix}_…</code>` : "Portal / admin"}</td>
        <td>${badge(u.has_password)}</td>
        <td>${
          u.face_templates.length >= 3
            ? badge(true, u.face_templates.length)
            : warnBadge(u.face_templates.length ? `${u.face_templates.length}/3` : "0")
        }</td>
        <td>${badge(u.voice_templates.length > 0)}</td>
        <td>${
          u.digits_challenge_ready
            ? badge(true, `${u.digits.length}/10`)
            : u.digits.length
              ? warnBadge(`${u.digits.length}/10`)
              : badge(false)
        }</td>`;

      const acciones = document.createElement("td");
      acciones.className = "acciones";

      const edit = document.createElement("button");
      edit.className = "btn";
      edit.innerHTML =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4z"></path></svg>' +
        "<span>Editar</span>";

      const del = document.createElement("button");
      del.className = "btn danger";
      del.innerHTML =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>' +
        "<span>Eliminar</span>";
      del.addEventListener("click", async () => {
        if (!confirm(`¿Eliminar al usuario ${u.username}? Se borran también sus plantillas.`))
          return;
        await api(userPath(u.uuid), { method: "DELETE" });
        toast(`Usuario ${u.username} eliminado`);
        editando = null;
        loadUsers();
      });

      acciones.appendChild(edit);
      acciones.appendChild(del);
      tr.appendChild(acciones);
      tbody.appendChild(tr);

      const fila = document.createElement("tr");
      fila.className = "editor-fila";
      const celda = document.createElement("td");
      celda.colSpan = COLS;
      fila.appendChild(celda);
      fila.hidden = u.uuid !== editando;
      tbody.appendChild(fila);

      let montado = null;
      const montar = () => {
        if (montado) return;
        montado = buildEditor(u, loadUsers);
        celda.appendChild(montado.box);
      };
      if (u.uuid === editando) montar();

      edit.addEventListener("click", () => {
        const abrir = fila.hidden;
        editando = abrir ? u.uuid : null;
        fila.hidden = !abrir;
        if (abrir) montar();
        else if (montado) montado.cleanup();
        setBtnText(edit, abrir ? "Cerrar" : "Editar");
      });
      if (u.uuid === editando) setBtnText(edit, "Cerrar");
    }
    if (!users.length)
      tbody.innerHTML = `<tr><td colspan="${COLS}">Sin usuarios registrados</td></tr>`;
    renderPagination("users", data, loadUsers);
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="${COLS}">Error: ${e.message}</td></tr>`;
  }
}

$("refresh-users").addEventListener("click", () => {
  loadUsers();
  loadVoiceSystemBanner();
});

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
    const data = await api(listUrl("/api/clients", "clients"));
    const clients = data.items || data;
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
    renderPagination("clients", data, loadClients);
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
    const data = await api(listUrl("/api/portal/users", "operators"));
    const ops = data.items || data;
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
    renderPagination("operators", data, loadOperators);
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="4">Error: ${e.message}</td></tr>`;
  }
}

["users", "clients", "operators"].forEach((key) => {
  setupListControls(key, { users: loadUsers, clients: loadClients, operators: loadOperators }[key]);
});

$("refresh-operators").addEventListener("click", loadOperators);

function generarContrasena(len = 16) {
  const grupos = [
    "abcdefghijkmnpqrstuvwxyz",
    "ABCDEFGHJKLMNPQRSTUVWXYZ",
    "23456789",
    "!@#$%&*+-_?",
  ];
  const todos = grupos.join("");
  const azar = () => {
    const a = new Uint32Array(1);
    crypto.getRandomValues(a);
    return a[0];
  };
  const chars = grupos.map((g) => g[azar() % g.length]);
  while (chars.length < len) chars.push(todos[azar() % todos.length]);
  for (let i = chars.length - 1; i > 0; i--) {
    const j = azar() % (i + 1);
    [chars[i], chars[j]] = [chars[j], chars[i]];
  }
  return chars.join("");
}

function wireGenerador(btnId, inputId) {
  $(btnId).addEventListener("click", () => {
    const inp = $(inputId);
    inp.value = generarContrasena();
    inp.type = "text";
    inp.focus();
    inp.select();
    toast("Contraseña generada: cópiala y guárdala antes de continuar");
  });
}

wireGenerador("op-gen-pass", "op-password");
wireGenerador("op-gen-new", "op-new-pass");

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
