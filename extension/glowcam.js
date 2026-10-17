/*
 * GlowCam para Snapchat — se ejecuta dentro de la página de Snapchat web.
 *
 * Añade una cámara «GlowCam» a la lista de cámaras del navegador. Cuando
 * Snapchat la usa, recibe un lienzo de 720×1280 (vertical) que se dibuja con:
 *   - tu cámara real, recortada a 9:16 con zoom/encuadre, o
 *   - un vídeo guardado, con su audio enviado como micrófono.
 */
(() => {
  "use strict";
  if (window.__glowcamLoaded) return;
  window.__glowcamLoaded = true;
  if (!window.MediaDevices || !navigator.mediaDevices) return;

  const VERSION = "1.2.0";
  const DEVICE_ID = "glowcam-virtual-camera";
  const DEVICE_LABEL = "GlowCam";
  const FPS = 30;
  const FORMATS = [
    { name: "Vertical 9:16 (Snapchat)", w: 720, h: 1280, pillarbox: false },
    { name: "Vertical con bordes (16:9)", w: 1280, h: 720, pillarbox: true },
    { name: "Horizontal 16:9", w: 1280, h: 720, pillarbox: false },
  ];

  const origGUM = MediaDevices.prototype.getUserMedia;
  const origEnum = MediaDevices.prototype.enumerateDevices;
  const isTop = window.top === window;

  // ------------------------------------------------------------------
  // «Identidad» de las pistas de GlowCam: Snapchat comprueba qué cámara le
  // llegó con track.getSettings().deviceId y track.label. Sin esto marca la
  // opción y la desmarca al instante.
  // ------------------------------------------------------------------
  const branded = new WeakMap(); // pista -> { label, settings }
  const T = MediaStreamTrack.prototype;
  const origGetSettings = T.getSettings;
  const origGetCaps = T.getCapabilities;
  const origGetConstraints = T.getConstraints;
  const origClone = T.clone;
  const labelDesc = Object.getOwnPropertyDescriptor(T, "label");

  function brand(track, info) {
    branded.set(track, info);
    return track;
  }
  function hideNative(fn, name) {
    try { Object.defineProperty(fn, "toString", { value: () => `function ${name}() { [native code] }` }); } catch (_) { /* nada */ }
    return fn;
  }
  try {
    Object.defineProperty(T, "label", {
      configurable: true,
      enumerable: labelDesc ? labelDesc.enumerable : true,
      get: hideNative(function () {
        const b = branded.get(this);
        return b ? b.label : labelDesc.get.call(this);
      }, "get label"),
    });
  } catch (_) { /* navegador sin soporte */ }
  T.getSettings = hideNative(function () {
    const real = origGetSettings.call(this);
    const b = branded.get(this);
    return b ? Object.assign({}, real, b.settings()) : real;
  }, "getSettings");
  if (origGetCaps) {
    T.getCapabilities = hideNative(function () {
      const real = origGetCaps.call(this) || {};
      const b = branded.get(this);
      return b ? Object.assign({}, real, b.caps ? b.caps() : { deviceId: b.settings().deviceId, groupId: b.settings().groupId }) : real;
    }, "getCapabilities");
  }
  T.getConstraints = hideNative(function () {
    const real = origGetConstraints.call(this) || {};
    const b = branded.get(this);
    return b ? Object.assign({}, real, { deviceId: { exact: b.settings().deviceId } }) : real;
  }, "getConstraints");
  T.clone = hideNative(function () {
    const c = origClone.call(this);
    const b = branded.get(this);
    if (b) branded.set(c, b);
    return c;
  }, "clone");

  // ------------------------------------------------------------------
  // Ajustes (guardados en el navegador, por usuario)
  // ------------------------------------------------------------------
  const store = {
    get(k, d) {
      try {
        const v = localStorage.getItem("glowcam:" + k);
        return v === null ? d : JSON.parse(v);
      } catch (_) { return d; }
    },
    set(k, v) {
      try { localStorage.setItem("glowcam:" + k, JSON.stringify(v)); } catch (_) { /* sin almacenamiento */ }
    },
  };

  const S = {
    enabled: store.get("enabled", true),
    source: store.get("source", "camera"), // "camera" | "video"
    camId: store.get("camId", ""),
    format: store.get("format", 0),
    zoom: store.get("zoom", 1),
    offX: store.get("offX", 0),
    offY: store.get("offY", 0),
    mirror: store.get("mirror", false),
    loop: store.get("loop", true),
    monitor: store.get("monitor", false),
    mixMic: store.get("mixMic", false),
    autoHang: store.get("autoHang", false),
    hangBtn: store.get("hangBtn", null), // botón de colgar «enseñado» por el usuario
    rotCam: store.get("rotCam", 0),
  };
  // Copia de seguridad de los ajustes en la extensión (por si Snapchat borra sus datos)
  const SYNC_KEYS = ["enabled", "source", "camId", "format", "zoom", "offX", "offY", "mirror", "loop", "monitor", "mixMic", "autoHang", "hangBtn", "rotCam"];
  let syncTimer = null;
  function syncSettings() {
    clearTimeout(syncTimer);
    syncTimer = setTimeout(() => {
      const data = {};
      SYNC_KEYS.forEach((k) => { data[k] = S[k]; });
      if (typeof lib !== "undefined") lib.send({ type: "saveSettings", data });
    }, 300);
  }
  const save = (k) => { store.set(k, S[k]); syncSettings(); };
  window.addEventListener("pagehide", () => {
    if (!syncTimer) return;
    clearTimeout(syncTimer);
    const data = {};
    SYNC_KEYS.forEach((k) => { data[k] = S[k]; });
    try { lib.send({ type: "saveSettings", data }); } catch (_) { /* nada */ }
  });

  // ------------------------------------------------------------------
  // Lienzo de salida
  // ------------------------------------------------------------------
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d", { alpha: false });
  let outStream = null;

  function applySize() {
    const f = FORMATS[S.format] || FORMATS[0];
    if (canvas.width !== f.w || canvas.height !== f.h) {
      canvas.width = f.w;
      canvas.height = f.h;
    }
  }
  applySize();

  function getOutStream() {
    startTicker();
    if (!outStream || outStream.getVideoTracks().every((t) => t.readyState === "ended")) {
      outStream = canvas.captureStream(FPS);
    }
    return outStream;
  }

  // Recorte con proporción `aspect`, zoom >= 1, desplazamientos -1..1
  function computeCrop(sw, sh, aspect, zoom, offX, offY) {
    zoom = Math.max(1, zoom || 1);
    let cw, ch;
    if (sw / sh > aspect) { ch = sh / zoom; cw = ch * aspect; }
    else { cw = sw / zoom; ch = cw / aspect; }
    cw = Math.max(2, Math.min(sw, cw));
    ch = Math.max(2, Math.min(sh, ch));
    const ox = Math.max(-1, Math.min(1, offX || 0));
    const oy = Math.max(-1, Math.min(1, offY || 0));
    const x = Math.max(0, Math.min(sw - cw, ((sw - cw) / 2) * (1 + ox)));
    const y = Math.max(0, Math.min(sh - ch, ((sh - ch) / 2) * (1 + oy)));
    return { x, y, w: cw, h: ch };
  }
  window.__glowcamComputeCrop = computeCrop; // para pruebas

  function drawSource(el, sw, sh, dx, dy, dw, dh, zoom, offX, offY) {
    const c = computeCrop(sw, sh, dw / dh, zoom, offX, offY);
    ctx.save();
    if (S.mirror) {
      ctx.translate(dx + dw, dy);
      ctx.scale(-1, 1);
      ctx.drawImage(el, c.x, c.y, c.w, c.h, 0, 0, dw, dh);
    } else {
      ctx.drawImage(el, c.x, c.y, c.w, c.h, dx, dy, dw, dh);
    }
    ctx.restore();
  }

  function drawPlaceholder(text) {
    const { width: W, height: H } = canvas;
    const g = ctx.createLinearGradient(0, 0, W, H);
    g.addColorStop(0, "#2a1d3d");
    g.addColorStop(1, "#5a2442");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = "rgba(255,255,255,0.85)";
    ctx.textAlign = "center";
    ctx.font = `600 ${Math.round(Math.min(W, H) / 14)}px system-ui, sans-serif`;
    ctx.fillText(text, W / 2, H / 2);
  }

  function currentElement() {
    const el = S.source === "video" ? videoEl : camEl;
    if (el && el.readyState >= 2 && el.videoWidth > 0) return el;
    return null;
  }

  // Giro: 0/90/180/270 (cámara: ajuste propio; vídeo: guardado con cada vídeo)
  const rotCanvas = document.createElement("canvas");
  const rotCtx = rotCanvas.getContext("2d", { alpha: false });
  function currentRotation() {
    return S.source === "video" ? (currentVideo ? currentVideo.rot || 0 : 0) : S.rotCam || 0;
  }
  function rotated(el) {
    const rot = currentRotation();
    const vw = el.videoWidth, vh = el.videoHeight;
    if (!rot) return { src: el, sw: vw, sh: vh };
    const swap = rot === 90 || rot === 270;
    const rw = swap ? vh : vw, rh = swap ? vw : vh;
    if (rotCanvas.width !== rw || rotCanvas.height !== rh) { rotCanvas.width = rw; rotCanvas.height = rh; }
    rotCtx.save();
    rotCtx.translate(rw / 2, rh / 2);
    rotCtx.rotate((rot * Math.PI) / 180);
    rotCtx.drawImage(el, -vw / 2, -vh / 2, vw, vh);
    rotCtx.restore();
    return { src: rotCanvas, sw: rw, sh: rh };
  }

  function render() {
    applySize();
    const f = FORMATS[S.format] || FORMATS[0];
    const W = canvas.width, H = canvas.height;
    const live = currentElement();
    if (!live) {
      drawPlaceholder(S.source === "video" ? (libCount ? "Elige un vídeo" : "Añade un vídeo") : "Cargando cámara…");
      return;
    }
    const { src: el, sw, sh } = rotated(live);
    if (!f.pillarbox) {
      drawSource(el, sw, sh, 0, 0, W, H, S.zoom, S.offX, S.offY);
      return;
    }
    // Vertical centrado sobre fondo desenfocado
    ctx.save();
    ctx.filter = "blur(28px) brightness(0.45)";
    drawSource(el, sw, sh, -40, -40, W + 80, H + 80, 1, 0, 0);
    ctx.restore();
    const iw = Math.round((H * 9) / 16);
    drawSource(el, sw, sh, Math.round((W - iw) / 2), 0, iw, H, S.zoom, S.offX, S.offY);
  }

  // Reloj de dibujo: un Worker no se ralentiza tanto en segundo plano; si la
  // página no lo permite, se usa un temporizador normal.
  let tickerStarted = false;
  function startTicker() {
    if (tickerStarted) return;
    tickerStarted = true;
    let ticking = false;
    const tick = () => {
      if (ticking) return;
      ticking = true;
      try { render(); } catch (e) { /* fotograma perdido */ }
      ticking = false;
    };
    try {
      const src = `setInterval(()=>postMessage(0), ${Math.round(1000 / FPS)});`;
      const url = URL.createObjectURL(new Blob([src], { type: "text/javascript" }));
      const w = new Worker(url);
      w.onmessage = tick;
      w.onerror = () => { w.terminate(); setInterval(tick, 1000 / FPS); };
    } catch (_) {
      setInterval(tick, 1000 / FPS);
    }
  }

  // ------------------------------------------------------------------
  // Fuente: cámara real
  // ------------------------------------------------------------------
  const camEl = document.createElement("video");
  camEl.muted = true;
  camEl.playsInline = true;
  let camStream = null;
  let camStarting = null;

  async function startCamera() {
    if (camStream && camStream.getVideoTracks().some((t) => t.readyState === "live")) return;
    if (camStarting) return camStarting;
    camStarting = (async () => {
      const video = { width: { ideal: 1920 }, height: { ideal: 1080 }, frameRate: { ideal: 30 } };
      if (S.camId) video.deviceId = { exact: S.camId };
      try {
        camStream = await origGUM.call(navigator.mediaDevices, { video });
      } catch (e) {
        if (!S.camId) throw e;
        S.camId = ""; save("camId"); // la cámara guardada ya no existe
        delete video.deviceId;
        camStream = await origGUM.call(navigator.mediaDevices, { video });
      }
      camEl.srcObject = camStream;
      await camEl.play().catch(() => {});
      ui.refreshCameras();
    })();
    try { await camStarting; } finally { camStarting = null; }
  }

  function stopCamera() {
    if (camStream) camStream.getTracks().forEach((t) => t.stop());
    camStream = null;
    camEl.srcObject = null;
  }

  // ------------------------------------------------------------------
  // Fuente: vídeo (guardado en IndexedDB de esta web)
  // ------------------------------------------------------------------
  const videoEl = document.createElement("video");
  videoEl.playsInline = true;
  videoEl.loop = S.loop;
  videoEl.crossOrigin = "anonymous";
  let videoUrl = null;
  // Forzar que se pinte el primer fotograma aunque el vídeo esté en pausa
  videoEl.addEventListener("loadeddata", () => {
    if (videoEl.paused && videoEl.currentTime === 0) videoEl.currentTime = 0.001;
  });

  // La biblioteca vive en un iframe de la propia extensión (library.html):
  // sus vídeos se guardan en el almacenamiento de la extensión, no en Snapchat.
  let currentVideo = null; // { id, name, rot }
  let libCount = 0;
  const lib = {
    frame: null,
    origin: null,
    ready: false,
    queue: [],
    send(msg, transfer) {
      if (!this.frame || !this.frame.contentWindow) return;
      if (!this.ready && msg.type !== "init") { this.queue.push([msg, transfer]); return; }
      this.frame.contentWindow.postMessage(Object.assign({ gc: true }, msg), this.origin, transfer || []);
    },
    create() {
      const base = document.documentElement.getAttribute("data-glowcam-base");
      if (!base) return null;
      this.origin = new URL(base).origin;
      const f = document.createElement("iframe");
      f.src = base + "library.html";
      f.setAttribute("allow", "");
      f.style.cssText = "width:100%;height:120px;border:0;display:block;background:transparent;color-scheme:dark";
      this.frame = f;
      return f;
    },
  };

  window.addEventListener("message", async (e) => {
    if (!lib.frame || e.source !== lib.frame.contentWindow || e.origin !== lib.origin) return;
    const m = e.data;
    if (!m || m.gc !== true) return;
    if (m.type === "hello") {
      lib.frame.contentWindow.postMessage({ gc: true, type: "init" }, lib.origin);
      lib.ready = true;
      lib.queue.splice(0).forEach(([q, t]) => lib.send(q, t));
    } else if (m.type === "height") {
      lib.frame.style.height = Math.min(Math.max(m.h, 60), 320) + "px";
    } else if (m.type === "settings") {
      const d = m.data || {};
      for (const k of SYNC_KEYS) if (k in d && d[k] !== undefined) { S[k] = d[k]; store.set(k, d[k]); }
      videoEl.loop = !!S.loop;
      ui.syncControls();
    } else if (m.type === "count") {
      libCount = m.n;
    } else if (m.type === "select") {
      await loadVideoBlob({ id: m.id, name: m.name, rot: m.rot || 0 }, m.blob, m.autoplay);
    } else if (m.type === "cleared") {
      currentVideo = null;
      if (videoUrl) URL.revokeObjectURL(videoUrl);
      videoUrl = null;
      videoEl.removeAttribute("src");
      videoEl.load();
      ui.updateRotLabel();
    }
  });

  async function loadVideoBlob(info, blob, autoplay) {
    if (videoUrl) URL.revokeObjectURL(videoUrl);
    currentVideo = info;
    videoUrl = URL.createObjectURL(blob);
    videoEl.src = videoUrl;
    audio.connectVideo();
    ui.updateRotLabel();
    ui.setStatus("Vídeo: " + info.name);
    if (autoplay && S.source === "video") { await audio.resume(); await videoEl.play().catch(() => {}); }
  }

  function addVideos(files) {
    lib.send({ type: "add", files: [...files] });
  }

  // ------------------------------------------------------------------
  // Audio: el vídeo (y opcionalmente tu micro) se mezcla en un micrófono
  // ------------------------------------------------------------------
  const audio = {
    ac: null, dest: null, videoGain: null, monitorGain: null, micGain: null,
    videoNode: null, micStream: null, micNode: null,
    init() {
      if (this.ac) return;
      const AC = window.AudioContext || window.webkitAudioContext;
      this.ac = new AC();
      this.dest = this.ac.createMediaStreamDestination();
      this.videoGain = this.ac.createGain();
      this.monitorGain = this.ac.createGain();
      this.micGain = this.ac.createGain();
      this.videoGain.connect(this.dest);
      this.monitorGain.connect(this.ac.destination);
      this.micGain.connect(this.dest);
      this.update();
    },
    async resume() {
      this.init();
      if (this.ac.state !== "running") { try { await this.ac.resume(); } catch (_) { /* necesita un clic */ } }
      ui.updateAudioWarning();
    },
    connectVideo() {
      this.init();
      if (this.videoNode) return;
      this.videoNode = this.ac.createMediaElementSource(videoEl);
      this.videoNode.connect(this.videoGain);
      this.videoNode.connect(this.monitorGain);
    },
    async ensureMic(audioConstraints) {
      this.init();
      if (this.micStream && this.micStream.getAudioTracks().some((t) => t.readyState === "live")) return;
      const c = audioConstraints && typeof audioConstraints === "object" ? audioConstraints : { echoCancellation: true, noiseSuppression: true, autoGainControl: true };
      this.micStream = await origGUM.call(navigator.mediaDevices, { audio: c });
      if (this.micNode) this.micNode.disconnect();
      this.micNode = this.ac.createMediaStreamSource(this.micStream);
      this.micNode.connect(this.micGain);
    },
    update() {
      if (!this.ac) return;
      const video = S.source === "video";
      const t = this.ac.currentTime;
      this.videoGain.gain.setTargetAtTime(video ? 1 : 0, t, 0.02);
      this.monitorGain.gain.setTargetAtTime(video && S.monitor ? 1 : 0, t, 0.02);
      this.micGain.gain.setTargetAtTime(!video || S.mixMic ? 1 : 0, t, 0.02);
    },
    track() {
      this.init();
      return this.dest.stream.getAudioTracks()[0];
    },
  };

  // ------------------------------------------------------------------
  // Sustituir la cámara para Snapchat
  // ------------------------------------------------------------------
  function wantsGlowCam(video) {
    if (!S.enabled || !video) return false;
    if (video === true) return true;
    const d = video.deviceId;
    if (!d) return true; // cámara por defecto → GlowCam
    const ids = [].concat(typeof d === "object" ? (d.exact || d.ideal || []) : d);
    if (ids.length === 0) return true;
    return ids.includes(DEVICE_ID);
  }

  async function prepareSource() {
    if (S.source === "camera") {
      await startCamera();
    } else {
      stopCamera();
      audio.connectVideo();
      await audio.resume();
      if (videoEl.src && videoEl.paused) await videoEl.play().catch(() => {});
    }
  }

  async function mixedAudioTrack(audioConstraints) {
    await audio.resume();
    try { await audio.ensureMic(audioConstraints); } catch (e) { if (S.source !== "video") throw e; }
    audio.update();
    const at = audio.track().clone();
    const mic = audio.micStream && audio.micStream.getAudioTracks()[0];
    return brand(at, {
      label: mic ? mic.label : "GlowCam Audio",
      settings: () => {
        const ms = mic ? origGetSettings.call(mic) : {};
        return { deviceId: ms.deviceId || "default", groupId: ms.groupId || "glowcam", channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true };
      },
    });
  }

  async function glowGetUserMedia(constraints) {
    const c = constraints || {};
    // Petición solo de micrófono: con GlowCam activado se entrega la mezcla
    // (micro en modo cámara; audio del vídeo en modo vídeo).
    if (!c.video && c.audio && S.enabled) {
      return new MediaStream([await mixedAudioTrack(c.audio)]);
    }
    if (!wantsGlowCam(c.video)) return origGUM.call(this, constraints);

    const tracks = [];
    await prepareSource().catch((e) => ui.setStatus("Cámara: " + (e && e.message ? e.message : e)));
    const vt = brand(getOutStream().getVideoTracks()[0].clone(), {
      label: DEVICE_LABEL,
      settings: () => ({ deviceId: DEVICE_ID, groupId: "glowcam", width: canvas.width, height: canvas.height, aspectRatio: canvas.width / canvas.height, frameRate: FPS, facingMode: "user", resizeMode: "none" }),
      caps: () => ({ deviceId: DEVICE_ID, groupId: "glowcam", width: { min: 1, max: 1920 }, height: { min: 1, max: 1920 }, frameRate: { min: 1, max: FPS }, facingMode: ["user"], aspectRatio: { min: 0.1, max: 10 } }),
    });
    tracks.push(vt);
    if (c.audio) tracks.push(await mixedAudioTrack(c.audio));
    ui.setStatus("🔴 Snapchat está usando GlowCam");
    ui.setLive(true);
    handedOut.push(vt);
    return new MediaStream(tracks);
  }

  // Cuando Snapchat cuelga, apagar la cámara real si el panel está cerrado
  const handedOut = [];

  // ------------------------------------------------------------------
  // Colgar automáticamente al terminar el vídeo
  // ------------------------------------------------------------------
  const HANG_RE = /(end|leave|hang\s*up|finish|disconnect|exit)[\s_-]*(the\s*)?(video\s*)?(call|chat)?|colgar|finalizar|terminar(\s+la)?\s+llamada|salir\s+de\s+la\s+llamada|abandonar|cortar/i;

  function clickable(el) {
    return el && el.closest ? el.closest("button, [role=button], a, [tabindex]") || el : el;
  }
  function describe(el) {
    el = clickable(el);
    const txt = (el.textContent || "").trim().replace(/\s+/g, " ");
    return {
      aria: el.getAttribute("aria-label") || "",
      title: el.getAttribute("title") || "",
      testid: el.getAttribute("data-testid") || "",
      text: txt.length <= 30 ? txt : "",
      tag: el.tagName,
    };
  }
  function visible(el) {
    if (!el || !el.isConnected) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) return false;
    const st = getComputedStyle(el);
    return st.visibility !== "hidden" && st.display !== "none" && st.pointerEvents !== "none";
  }
  function candidates() {
    const root = ui.root;
    return [...document.querySelectorAll("button, [role=button], [aria-label], [title], [data-testid]")]
      .filter((el) => !(root && root.contains(el)) && visible(el));
  }
  function findHangButton() {
    const els = candidates();
    const d = S.hangBtn;
    if (d) {
      const match = (el) => {
        const e = describe(el);
        if (d.testid && e.testid === d.testid) return 3;
        if (d.aria && e.aria === d.aria) return 3;
        if (d.title && e.title === d.title) return 2;
        if (d.text && e.text === d.text && e.tag === d.tag) return 1;
        return 0;
      };
      let best = null, bestScore = 0;
      for (const el of els) { const sc = match(el); if (sc > bestScore) { best = el; bestScore = sc; } }
      if (best) return clickable(best);
    }
    for (const el of els) {
      const label = [el.getAttribute("aria-label"), el.getAttribute("title"), el.getAttribute("data-testid")].filter(Boolean).join(" ");
      if (label && HANG_RE.test(label)) return clickable(el);
    }
    for (const el of els) {
      const t = (el.textContent || "").trim();
      if (t && t.length <= 25 && HANG_RE.test(t)) return clickable(el);
    }
    return null;
  }
  function realClick(el) {
    const r = el.getBoundingClientRect();
    const opts = { bubbles: true, cancelable: true, composed: true, view: window, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2, button: 0 };
    try { el.dispatchEvent(new PointerEvent("pointerdown", opts)); } catch (_) { /* nada */ }
    el.dispatchEvent(new MouseEvent("mousedown", opts));
    try { el.dispatchEvent(new PointerEvent("pointerup", opts)); } catch (_) { /* nada */ }
    el.dispatchEvent(new MouseEvent("mouseup", opts));
    el.click();
  }
  function hangUp() {
    const btn = findHangButton();
    if (btn) {
      realClick(btn);
      ui.setStatus("📴 Vídeo terminado: llamada colgada.");
      return true;
    }
    // Sin botón: cortar la imagen y el sonido que recibe Snapchat
    for (const t of handedOut.splice(0)) {
      try { t.stop(); t.dispatchEvent(new Event("ended")); } catch (_) { /* nada */ }
    }
    ui.setStatus("⚠️ No encontré el botón de colgar. Pulsa «🎯 Enseñar botón de colgar» y luego el botón de colgar de Snapchat.");
    return false;
  }
  videoEl.addEventListener("ended", () => {
    if (S.autoHang && S.source === "video" && handedOut.some((t) => t.readyState === "live")) {
      setTimeout(hangUp, 400);
    }
  });

  // Modo «enseñar»: el siguiente clic fuera del panel se guarda como botón de colgar
  function learnHangButton() {
    ui.setStatus("🎯 Ahora pulsa el botón de colgar de Snapchat (en una llamada)…");
    const onClick = (e) => {
      const path = e.composedPath ? e.composedPath() : [e.target];
      if (ui.root && path.includes(ui.root)) return; // clics en el panel no cuentan
      document.removeEventListener("click", onClick, true);
      S.hangBtn = describe(e.target);
      save("hangBtn");
      const name = S.hangBtn.aria || S.hangBtn.title || S.hangBtn.text || S.hangBtn.testid || "botón";
      ui.setStatus(`✅ Botón de colgar guardado («${name}»).`);
    };
    document.addEventListener("click", onClick, true);
  }
  setInterval(() => {
    for (let i = handedOut.length - 1; i >= 0; i--) if (handedOut[i].readyState === "ended") handedOut.splice(i, 1);
    if (handedOut.length === 0 && ui.els.pill && ui.els.pill.classList.contains("live")) {
      ui.setLive(false);
      ui.setStatus("Llamada terminada.");
      if (!ui.els.panel.classList.contains("open")) { stopCamera(); videoEl.pause(); }
    }
  }, 2000);

  async function glowEnumerateDevices() {
    const list = await origEnum.call(this);
    if (!S.enabled) return list;
    const fake = {
      deviceId: DEVICE_ID,
      groupId: "glowcam",
      kind: "videoinput",
      label: DEVICE_LABEL,
      getCapabilities() {
        return { deviceId: DEVICE_ID, groupId: "glowcam", width: { min: 1, max: 1920 }, height: { min: 1, max: 1920 }, frameRate: { min: 1, max: FPS }, facingMode: ["user"] };
      },
      toJSON() { return { deviceId: DEVICE_ID, groupId: "glowcam", kind: "videoinput", label: DEVICE_LABEL }; },
    };
    try { Object.setPrototypeOf(fake, (window.InputDeviceInfo || window.MediaDeviceInfo).prototype); } catch (_) { /* objeto simple */ }
    // GlowCam primero para que sea la cámara por defecto
    return [fake, ...list.filter((d) => d.deviceId !== DEVICE_ID)];
  }

  function patch(name, fn) {
    const wrapped = {
      [name](...args) { return fn.apply(this, args); },
    }[name];
    Object.defineProperty(wrapped, "toString", { value: () => `function ${name}() { [native code] }` });
    Object.defineProperty(MediaDevices.prototype, name, { value: wrapped, writable: true, configurable: true });
  }
  patch("getUserMedia", glowGetUserMedia);
  patch("enumerateDevices", glowEnumerateDevices);

  // ------------------------------------------------------------------
  // Panel flotante (solo en la ventana principal)
  // ------------------------------------------------------------------
  const ui = {
    root: null, els: {},
    setStatus(t) { if (this.els.status) this.els.status.textContent = t; },
    setLive(on) { if (this.els.pill) this.els.pill.classList.toggle("live", !!on); },
    updateAudioWarning() {
      if (!this.els.audioWarn) return;
      const bad = S.source === "video" && audio.ac && audio.ac.state !== "running";
      this.els.audioWarn.style.display = bad ? "block" : "none";
    },
    async refreshCameras() {
      const sel = this.els.camSel;
      if (!sel) return;
      let devs = [];
      try { devs = (await origEnum.call(navigator.mediaDevices)).filter((d) => d.kind === "videoinput"); } catch (_) { /* nada */ }
      const current = S.camId || (camStream && camStream.getVideoTracks()[0] && camStream.getVideoTracks()[0].getSettings().deviceId) || "";
      sel.replaceChildren(...devs.map((d, i) => {
        const o = document.createElement("option");
        o.value = d.deviceId;
        o.textContent = d.label || `Cámara ${i + 1}`;
        if (d.deviceId === current) o.selected = true;
        return o;
      }));
      if (!devs.length) {
        const o = document.createElement("option");
        o.textContent = "Pulsa «Cámara» para dar permiso";
        sel.replaceChildren(o);
      }
    },
    refreshVideos() { lib.send({ type: "refresh" }); },
    syncControls() {
      const E = this.els;
      if (!E.panel) return;
      E.enabled.checked = S.enabled;
      E.pill.classList.toggle("off", !S.enabled);
      E.loop.checked = S.loop;
      E.autoHang.checked = S.autoHang;
      E.monitor.checked = S.monitor;
      E.mixMic.checked = S.mixMic;
      E.mirror.checked = S.mirror;
      E.format.value = String(S.format);
      E.zoom.value = S.zoom; E.offX.value = S.offX; E.offY.value = S.offY;
      if (this.setSource && E.panel.dataset.source !== S.source) this.setSource(S.source);
      audio.update();
      this.updateRotLabel();
    },
    updateRotLabel() {
      if (!this.els.rotLabel) return;
      const r = currentRotation();
      this.els.rotLabel.textContent = r ? r + "°" : "";
    },
  };

  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (k === "class") el.className = v;
      else if (v === true) el.setAttribute(k, "");
      else if (v !== false && v != null) el.setAttribute(k, v);
    }
    for (const kid of kids.flat()) {
      if (kid == null || kid === false) continue;
      el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }

  const CSS = `
  :host { all: initial; }
  * { box-sizing: border-box; font-family: -apple-system, system-ui, "Segoe UI", sans-serif; }
  .pill { position: fixed; right: 16px; bottom: 16px; z-index: 2147483647; background: #ff5fa2; color: #141418;
    border: none; border-radius: 999px; padding: 9px 14px; font-weight: 700; font-size: 13px; cursor: pointer;
    box-shadow: 0 6px 20px rgba(0,0,0,.35); display: flex; align-items: center; gap: 7px; }
  .pill .dot { width: 9px; height: 9px; border-radius: 50%; background: #141418; opacity: .45; }
  .pill.live .dot { background: #e8102e; opacity: 1; box-shadow: 0 0 0 3px rgba(232,16,46,.25); }
  .pill.off { background: #3a3a45; color: #ddd; }
  .panel { position: fixed; right: 16px; bottom: 64px; z-index: 2147483647; width: 320px; max-height: calc(100vh - 90px);
    overflow: auto; background: #141418; color: #f2f2f5; border: 1px solid #2c2c36; border-radius: 14px;
    box-shadow: 0 12px 40px rgba(0,0,0,.5); padding: 14px; font-size: 13px; display: none; }
  .panel.open { display: block; }
  .head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
  .title { font-size: 17px; font-weight: 800; color: #ff5fa2; }
  .switch { display: flex; align-items: center; gap: 6px; cursor: pointer; font-size: 12px; color: #c8c8d2; }
  .seg { display: grid; grid-template-columns: 1fr 1fr; border: 1px solid #34343f; border-radius: 9px; overflow: hidden; margin-bottom: 10px; }
  .seg button { background: #24242c; color: #f2f2f5; border: none; padding: 8px; font-weight: 600; cursor: pointer; font-size: 13px; }
  .seg button.on { background: #ff5fa2; color: #141418; }
  .preview { display: flex; justify-content: center; margin-bottom: 10px; }
  .preview canvas { width: 120px; height: auto; max-height: 213px; object-fit: contain; border-radius: 10px; background: #000; border: 1px solid #2c2c36; }
  label.row { display: grid; grid-template-columns: 92px 1fr; align-items: center; gap: 8px; margin: 6px 0; color: #c8c8d2; }
  select, input[type=range] { width: 100%; }
  select { background: #24242c; color: #f2f2f5; border: 1px solid #34343f; border-radius: 8px; padding: 6px; font-size: 12px; }
  input[type=range] { accent-color: #ff5fa2; }
  .checks { display: flex; flex-wrap: wrap; gap: 4px 12px; margin: 6px 0; color: #c8c8d2; font-size: 12px; }
  .checks label { display: flex; gap: 5px; align-items: center; cursor: pointer; }
  input[type=checkbox] { accent-color: #ff5fa2; }
  .btn { background: #24242c; color: #f2f2f5; border: 1px solid #34343f; border-radius: 8px; padding: 7px 10px; cursor: pointer; font-size: 12px; }
  .btn:hover { border-color: #ff5fa2; }
  .btn.primary { background: #ff5fa2; color: #141418; border: none; font-weight: 700; }
  .videos { border: 1px solid #2c2c36; border-radius: 9px; max-height: 150px; overflow: auto; margin-bottom: 8px; }
  .vid { display: flex; align-items: center; gap: 6px; padding: 6px 8px; border-bottom: 1px solid #22222a; }
  .vid:last-child { border-bottom: none; }
  .vid.sel { background: #2a1d29; }
  .vname { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; cursor: pointer; }
  .vid.sel .vname { color: #ff8cc0; font-weight: 600; }
  .del { background: none; border: none; color: #888; cursor: pointer; font-size: 12px; }
  .del:hover { color: #ff5f7a; }
  .empty { padding: 10px; color: #8a8a96; font-size: 12px; text-align: center; }
  .player { display: flex; align-items: center; gap: 8px; margin: 6px 0; }
  .player input { flex: 1; }
  .time { color: #a0a0ad; font-size: 11px; min-width: 70px; text-align: right; font-variant-numeric: tabular-nums; }
  .status { margin-top: 10px; color: #c8c8d2; font-size: 12px; }
  .hint { margin-top: 6px; color: #8a8a96; font-size: 11px; line-height: 1.4; }
  .warn { display: none; margin: 6px 0; padding: 7px 9px; background: #3a2a10; color: #ffcf7a; border-radius: 8px; font-size: 12px; cursor: pointer; }
  .hidden { display: none !important; }
  .rotlabel { color: #ff8cc0; font-size: 12px; font-weight: 700; min-width: 30px; }
  `;

  function fmtTime(s) {
    if (!isFinite(s)) return "0:00";
    s = Math.max(0, Math.floor(s));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }

  function buildUI() {
    const host = document.createElement("div");
    host.id = "glowcam-root";
    const shadow = host.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = CSS;
    shadow.append(style);
    const E = ui.els;

    const set = (k, v) => { S[k] = v; save(k); };

    E.pill = h("button", { class: "pill" + (S.enabled ? "" : " off"), title: "GlowCam", onclick: () => {
      E.panel.classList.toggle("open");
      if (E.panel.classList.contains("open")) {
        ui.refreshVideos();
        if (S.source === "camera") startCamera().catch((e) => ui.setStatus("Cámara: " + e.message));
        else ui.refreshCameras();
      } else if (!E.pill.classList.contains("live")) {
        stopCamera(); // panel cerrado y Snapchat no la usa: apagar la cámara
      }
    } }, h("span", { class: "dot" }), "GlowCam");

    E.enabled = h("input", { type: "checkbox", onchange: (e) => {
      set("enabled", e.target.checked);
      E.pill.classList.toggle("off", !S.enabled);
      ui.setStatus(S.enabled ? "GlowCam activado. En Snapchat elige la cámara «GlowCam»." : "GlowCam desactivado: Snapchat usará tu cámara normal.");
    } });
    E.enabled.checked = S.enabled;

    const segCam = h("button", { onclick: () => setSource("camera") }, "📷 Cámara");
    const segVid = h("button", { onclick: () => setSource("video") }, "🎬 Vídeo");

    // Cámara
    E.camSel = h("select", { onchange: async (e) => {
      set("camId", e.target.value);
      stopCamera();
      if (S.source === "camera") await startCamera().catch((err) => ui.setStatus("Cámara: " + err.message));
    } });
    const camBox = h("div", {}, h("label", { class: "row" }, "Cámara", E.camSel));

    // Vídeo
    const libFrame = lib.create();
    E.videoList = libFrame || h("div", { class: "empty" }, "No se pudo abrir la biblioteca. Recarga la página.");
    E.play = h("button", { class: "btn", onclick: async () => {
      await audio.resume();
      if (!videoEl.src) return;
      if (videoEl.paused) await videoEl.play().catch(() => {}); else videoEl.pause();
    } }, "▶");
    E.seek = h("input", { type: "range", min: 0, max: 1000, value: 0, oninput: (e) => {
      if (isFinite(videoEl.duration)) videoEl.currentTime = (e.target.value / 1000) * videoEl.duration;
    } });
    E.time = h("span", { class: "time" }, "0:00 / 0:00");
    E.loop = h("input", { type: "checkbox", onchange: (e) => {
      set("loop", e.target.checked); videoEl.loop = S.loop;
      if (S.loop && S.autoHang) { set("autoHang", false); E.autoHang.checked = false; }
    } });
    E.autoHang = h("input", { type: "checkbox", onchange: (e) => {
      set("autoHang", e.target.checked);
      if (S.autoHang && S.loop) { set("loop", false); E.loop.checked = false; videoEl.loop = false; }
      ui.setStatus(S.autoHang ? "Al terminar el vídeo se colgará la llamada." : "Colgar automático desactivado.");
    } });
    E.autoHang.checked = S.autoHang;
    E.loop.checked = S.loop;
    E.monitor = h("input", { type: "checkbox", onchange: (e) => { set("monitor", e.target.checked); audio.update(); } });
    E.monitor.checked = S.monitor;
    E.mixMic = h("input", { type: "checkbox", onchange: async (e) => {
      set("mixMic", e.target.checked);
      if (S.mixMic) { await audio.resume(); await audio.ensureMic().catch(() => {}); }
      audio.update();
    } });
    E.mixMic.checked = S.mixMic;
    E.audioWarn = h("div", { class: "warn", onclick: () => audio.resume() }, "🔇 Pulsa aquí para activar el sonido del vídeo");
    const vidBox = h("div", {},
      E.videoList,
      h("div", { class: "player" }, E.play, E.seek, E.time),
      h("div", { class: "checks" },
        h("label", {}, E.loop, "Repetir en bucle"),
        h("label", {}, E.autoHang, "Colgar al terminar el vídeo"),
        h("label", {}, E.monitor, "Escucharlo yo"),
        h("label", {}, E.mixMic, "Mezclar mi micro")),
      h("div", { class: "checks" },
        h("button", { class: "btn", title: "Enseñar botón de colgar", onclick: learnHangButton }, "🎯 Enseñar botón de colgar")),
      E.audioWarn);

    videoEl.addEventListener("play", () => { E.play.textContent = "⏸"; });
    videoEl.addEventListener("pause", () => { E.play.textContent = "▶"; });
    videoEl.addEventListener("timeupdate", () => {
      if (isFinite(videoEl.duration) && videoEl.duration > 0) {
        E.seek.value = Math.round((videoEl.currentTime / videoEl.duration) * 1000);
      }
      E.time.textContent = `${fmtTime(videoEl.currentTime)} / ${fmtTime(videoEl.duration)}`;
    });

    // Imagen
    E.format = h("select", { onchange: (e) => { set("format", +e.target.value); } },
      ...FORMATS.map((f, i) => h("option", { value: i, selected: i === S.format }, f.name)));
    const slider = (key, min, max, step) => {
      const r = h("input", { type: "range", min, max, step, value: S[key], oninput: (e) => set(key, +e.target.value) });
      return r;
    };
    E.zoom = slider("zoom", 1, 3, 0.01);
    E.offX = slider("offX", -1, 1, 0.01);
    E.offY = slider("offY", -1, 1, 0.01);
    E.mirror = h("input", { type: "checkbox", onchange: (e) => set("mirror", e.target.checked) });
    E.mirror.checked = S.mirror;

    E.status = h("div", { class: "status" }, S.enabled ? "Listo. En Snapchat elige la cámara «GlowCam»." : "GlowCam desactivado.");

    const previewCanvas = canvas;
    E.panel = h("div", { class: "panel" },
      h("div", { class: "head" }, h("span", { class: "title" }, "GlowCam"),
        h("label", { class: "switch" }, E.enabled, "Activado")),
      h("div", { class: "seg" }, segCam, segVid),
      h("div", { class: "preview" }, previewCanvas),
      camBox, vidBox,
      h("label", { class: "row" }, "Formato", E.format),
      h("label", { class: "row" }, "Zoom", E.zoom),
      h("label", { class: "row" }, "Izq. / Der.", E.offX),
      h("label", { class: "row" }, "Arriba / Abajo", E.offY),
      h("div", { class: "checks" },
        h("label", {}, E.mirror, "Espejo"),
        h("button", { class: "btn", title: "Girar 90°", onclick: rotate }, "⟳ Girar"),
        (E.rotLabel = h("span", { class: "rotlabel" }, "")),
        h("button", { class: "btn", onclick: () => {
          ["zoom", "offX", "offY"].forEach((k) => { set(k, k === "zoom" ? 1 : 0); E[k].value = S[k]; });
        } }, "Centrar")),
      E.status,
      h("div", { class: "hint" }, "En la videollamada elige la cámara «GlowCam». Mantén esta ventana visible durante la llamada. v" + VERSION));

    function rotate() {
      if (S.source === "video") {
        if (!currentVideo) return;
        currentVideo.rot = ((currentVideo.rot || 0) + 90) % 360;
        lib.send({ type: "setRot", id: currentVideo.id, rot: currentVideo.rot });
      } else {
        set("rotCam", ((S.rotCam || 0) + 90) % 360);
      }
      ui.updateRotLabel();
    }

    function setSource(src) {
      set("source", src);
      E.panel.dataset.source = src;
      segCam.classList.toggle("on", src === "camera");
      segVid.classList.toggle("on", src === "video");
      camBox.classList.toggle("hidden", src !== "camera");
      vidBox.classList.toggle("hidden", src !== "video");
      audio.update();
      if (src === "camera") {
        videoEl.pause();
        startCamera().catch((e) => ui.setStatus("Cámara: " + e.message));
      } else {
        prepareSource().catch(() => {});
        ui.refreshVideos();
      }
      ui.updateAudioWarning();
      ui.updateRotLabel();
    }
    ui.setSource = setSource;
    E.panel.dataset.source = S.source;
    segCam.classList.toggle("on", S.source === "camera");
    segVid.classList.toggle("on", S.source === "video");
    camBox.classList.toggle("hidden", S.source !== "camera");
    vidBox.classList.toggle("hidden", S.source !== "video");

    // Arrastrar vídeos sobre el panel
    E.panel.addEventListener("dragover", (e) => { e.preventDefault(); });
    E.panel.addEventListener("drop", async (e) => {
      e.preventDefault();
      if (e.dataTransfer && e.dataTransfer.files.length) {
        await audio.resume();
        setSource("video");
        addVideos([...e.dataTransfer.files]);
      }
    });

    shadow.append(E.pill, E.panel);
    (document.body || document.documentElement).append(host);
    ui.root = host;
  }

  if (isTop) {
    const mount = () => {
      if (document.getElementById("glowcam-root")) return;
      buildUI();
      startTicker();
    };
    if (document.body) mount();
    else document.addEventListener("DOMContentLoaded", mount, { once: true });
    // Algunas webs rehacen el <body>; volver a montar si desaparece
    setInterval(() => { if (document.body) mount(); }, 3000);
  }

  window.__glowcam = { hangUp, findHangButton, S, FORMATS, canvas, render, addVideos, videoEl, camEl, lib, get currentVideo() { return currentVideo; }, version: VERSION };
})();
