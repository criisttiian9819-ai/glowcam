/*
 * Biblioteca de vídeos de GlowCam. Vive en el almacenamiento de la propia
 * extensión (no en el de Snapchat), así que los vídeos se quedan guardados
 * aunque Snapchat borre sus datos o cierres sesión.
 *
 * Se comunica con el panel de la página por postMessage:
 *   página → biblioteca: {gc:"init"} | {gc:"add", files} | {gc:"setRot", id, rot}
 *   biblioteca → página: {gc:"ready"} | {gc:"select", id, name, rot, blob, autoplay}
 *                        | {gc:"cleared"} | {gc:"height", h} | {gc:"count", n}
 */
(() => {
  "use strict";
  const ALLOWED_PARENT = /^https:\/\/([a-z0-9-]+\.)*snapchat\.com$/i;

  // ---------------- clave de acceso ----------------
  // URL de la aplicación web de Google Apps Script (hoja «GlowCam · Accesos»)
  const LICENSE_URL = "https://script.google.com/macros/s/AKfycbw_vJgSvLgFWNesRuxj-fetakzWUjEB_qIE2PyF4JX1uCx_LtTZNGQIWR1klGogT79x7A/exec";
  const GRACE_MS = 12 * 60 * 60 * 1000;   // sin internet: sigue funcionando 12 h
  const RECHECK_MS = 30 * 60 * 1000;      // volver a comprobar cada 30 min

  async function licGet() {
    try { return await chrome.storage.local.get(["licKey", "licDevice", "licOkAt", "licUser"]); } catch (_) { return {}; }
  }
  async function licSet(o) { try { await chrome.storage.local.set(o); } catch (_) { /* nada */ } }
  async function licClear() { try { await chrome.storage.local.remove(["licKey", "licOkAt", "licUser"]); } catch (_) { /* nada */ } }
  async function deviceId() {
    const s = await licGet();
    if (s.licDevice) return s.licDevice;
    const id = "PC-" + (crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2));
    await licSet({ licDevice: id });
    return id;
  }
  async function verify(key) {
    const dev = await deviceId();
    try {
      const url = LICENSE_URL + "?action=check&key=" + encodeURIComponent(key) + "&device=" + encodeURIComponent(dev);
      const r = await fetch(url, { cache: "no-store", redirect: "follow", credentials: "omit" });
      const j = await r.json();
      return j && typeof j.ok === "boolean" ? j : { ok: null, reason: "network" };
    } catch (_) {
      return { ok: null, reason: "network" };
    }
  }
  async function checkLicense(newKey) {
    const s = await licGet();
    const key = (newKey || s.licKey || "").trim().toUpperCase();
    if (!key) { post({ type: "license", state: "need" }); return; }
    const j = await verify(key);
    if (j.ok === true) {
      await licSet({ licKey: key, licOkAt: Date.now(), licUser: j.user || "" });
      post({ type: "license", state: "ok", user: j.user || "", until: Date.now() + GRACE_MS });
    } else if (j.ok === null) {
      // Sin conexión: si la clave guardada se validó hace poco, seguir funcionando
      if (!newKey && s.licOkAt && Date.now() - s.licOkAt < GRACE_MS) {
        post({ type: "license", state: "ok", user: s.licUser || "", offline: true, until: s.licOkAt + GRACE_MS });
      } else {
        post({ type: "license", state: newKey ? "error" : (s.licKey ? "error" : "need"), reason: "network" });
      }
    } else {
      if (!newKey) await licClear(); // la clave guardada ya no vale: pedirla de nuevo
      post({ type: "license", state: "denied", reason: j.reason || "invalid", attempt: !!newKey });
    }
  }
  setInterval(() => { if (parentOrigin) checkLicense(); }, RECHECK_MS);
  let parentOrigin = null;
  let selectedId = null;

  const $ = (id) => document.getElementById(id);

  // ---------------- almacenamiento ----------------
  let dbp = null;
  function openDb() {
    if (dbp) return dbp;
    dbp = new Promise((res, rej) => {
      const r = indexedDB.open("glowcam-library", 1);
      r.onupgradeneeded = () => r.result.createObjectStore("videos", { keyPath: "id" });
      r.onsuccess = () => res(r.result);
      r.onerror = () => rej(r.error);
    });
    return dbp;
  }
  async function tx(mode, fn) {
    const d = await openDb();
    return new Promise((res, rej) => {
      const t = d.transaction("videos", mode);
      const req = fn(t.objectStore("videos"));
      t.oncomplete = () => res(req ? req.result : undefined);
      t.onerror = () => rej(t.error);
      t.onabort = () => rej(t.error);
    });
  }
  const db = {
    list: () => tx("readonly", (s) => s.getAll()),
    get: (id) => tx("readonly", (s) => s.get(id)),
    put: (v) => tx("readwrite", (s) => s.put(v)),
    del: (id) => tx("readwrite", (s) => s.delete(id)),
  };

  // Pedir almacenamiento persistente (que Chrome no lo borre por falta de espacio)
  try { navigator.storage && navigator.storage.persist && navigator.storage.persist(); } catch (_) { /* nada */ }

  async function loadSelected() {
    try {
      const r = await chrome.storage.local.get("selectedId");
      return r.selectedId || null;
    } catch (_) { return localStorage.getItem("selectedId"); }
  }
  async function saveSelected(id) {
    selectedId = id;
    try { await chrome.storage.local.set({ selectedId: id }); } catch (_) { localStorage.setItem("selectedId", id || ""); }
  }

  // ---------------- utilidades ----------------
  function fmt(s) {
    if (!isFinite(s)) return "";
    s = Math.round(s);
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }
  function fmtSize(b) {
    return b > 1048576 ? (b / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(b / 1024)) + " KB";
  }

  // Miniatura y duración del vídeo
  function probe(blob) {
    return new Promise((resolve) => {
      const v = document.createElement("video");
      v.muted = true;
      v.playsInline = true;
      v.preload = "auto";
      const url = URL.createObjectURL(blob);
      let done = false;
      const finish = (thumb) => {
        if (done) return;
        done = true;
        const out = { duration: isFinite(v.duration) ? v.duration : null, w: v.videoWidth, h: v.videoHeight, thumb };
        URL.revokeObjectURL(url);
        resolve(out);
      };
      v.onloadedmetadata = () => { v.currentTime = Math.min(0.5, (v.duration || 1) / 3); };
      v.onseeked = () => {
        try {
          const c = document.createElement("canvas");
          const w = 60, h = 88;
          c.width = w; c.height = h;
          const g = c.getContext("2d");
          const vw = v.videoWidth, vh = v.videoHeight;
          const scale = Math.max(w / vw, h / vh);
          g.drawImage(v, (w - vw * scale) / 2, (h - vh * scale) / 2, vw * scale, vh * scale);
          finish(c.toDataURL("image/jpeg", 0.7));
        } catch (_) { finish(null); }
      };
      v.onerror = () => finish(null);
      setTimeout(() => finish(null), 8000);
      v.src = url;
    });
  }

  function post(msg, transfer) {
    if (!parentOrigin) return;
    window.parent.postMessage(Object.assign({ gc: true }, msg), parentOrigin, transfer || []);
  }

  function reportHeight() {
    post({ type: "height", h: Math.ceil(document.documentElement.scrollHeight) });
  }

  // ---------------- acciones ----------------
  async function select(id, autoplay) {
    const v = id ? await db.get(id) : null;
    if (!v) {
      await saveSelected(null);
      post({ type: "cleared" });
      render();
      return;
    }
    await saveSelected(v.id);
    post({ type: "select", id: v.id, name: v.name, rot: v.rot || 0, blob: v.blob, autoplay: !!autoplay });
    render();
  }

  async function addFiles(files) {
    const list = [...files].filter((f) => (f.type || "").startsWith("video/") || /\.(mp4|mov|m4v|webm|mkv|avi)$/i.test(f.name));
    if (!list.length) return;
    $("count").replaceChildren();
    const busy = document.createElement("span");
    busy.className = "busy";
    busy.textContent = `Guardando ${list.length} vídeo(s)…`;
    $("count").append(busy);
    let last = null;
    for (const f of list) {
      const info = await probe(f);
      const v = {
        id: Date.now().toString(36) + Math.random().toString(36).slice(2, 7),
        name: f.name,
        blob: f,
        type: f.type,
        size: f.size,
        added: Date.now(),
        duration: info.duration,
        thumb: info.thumb,
        rot: 0,
      };
      await db.put(v);
      last = v;
    }
    if (last) await select(last.id, true);
    else render();
  }

  async function remove(id) {
    await db.del(id);
    if (id === selectedId) await select(null);
    else render();
  }

  async function setRot(id, rot) {
    const v = await db.get(id);
    if (!v) return;
    v.rot = ((rot % 360) + 360) % 360;
    await db.put(v);
  }

  // ---------------- interfaz ----------------
  async function render() {
    let vids = [];
    try { vids = await db.list(); } catch (e) { /* nada */ }
    vids.sort((a, b) => b.added - a.added);
    const list = $("list");
    list.replaceChildren();
    if (!vids.length) {
      const e = document.createElement("div");
      e.className = "empty";
      e.textContent = "Aún no hay vídeos. Pulsa «＋ Añadir vídeos» o arrástralos aquí.";
      list.append(e);
    }
    for (const v of vids) {
      const row = document.createElement("div");
      row.className = "row" + (v.id === selectedId ? " sel" : "");
      row.title = v.name;
      row.dataset.id = v.id;
      const img = document.createElement(v.thumb ? "img" : "div");
      img.className = "thumb";
      if (v.thumb) img.src = v.thumb;
      const meta = document.createElement("div");
      meta.className = "meta";
      const name = document.createElement("div");
      name.className = "name";
      name.textContent = (v.id === selectedId ? "▶ " : "") + v.name;
      const sub = document.createElement("div");
      sub.className = "sub";
      sub.textContent = [fmt(v.duration), fmtSize(v.size || (v.blob && v.blob.size) || 0)].filter(Boolean).join(" · ");
      meta.append(name, sub);
      const del = document.createElement("button");
      del.className = "del";
      del.textContent = "✕";
      del.title = "Borrar de la biblioteca";
      del.addEventListener("click", (e) => {
        e.stopPropagation();
        if (confirmDelete(row, v)) remove(v.id);
      });
      row.addEventListener("click", () => select(v.id, true));
      row.append(img, meta, del);
      list.append(row);
    }
    $("count").textContent = vids.length ? `${vids.length} guardado${vids.length === 1 ? "" : "s"}` : "";
    post({ type: "count", n: vids.length });
    requestAnimationFrame(reportHeight);
  }

  // Confirmación en dos clics (sin ventanas emergentes)
  const pendingDelete = new WeakSet();
  function confirmDelete(row, v) {
    const btn = row.querySelector(".del");
    if (pendingDelete.has(row)) return true;
    pendingDelete.add(row);
    btn.textContent = "¿Borrar?";
    btn.style.color = "#ff5f7a";
    setTimeout(() => { if (row.isConnected) { pendingDelete.delete(row); btn.textContent = "✕"; btn.style.color = ""; } }, 2500);
    return false;
  }

  $("add").addEventListener("click", () => $("file").click());
  $("file").addEventListener("change", async (e) => {
    const input = e.currentTarget;
    const files = [...input.files];
    input.value = "";
    await addFiles(files);
  });
  document.addEventListener("dragover", (e) => e.preventDefault());
  document.addEventListener("drop", (e) => {
    e.preventDefault();
    if (e.dataTransfer && e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
  });

  window.addEventListener("message", async (e) => {
    if (e.source !== window.parent || !ALLOWED_PARENT.test(e.origin)) return;
    const m = e.data;
    if (!m || m.gc !== true) return;
    if (m.type === "init") {
      parentOrigin = e.origin;
      checkLicense();
      try {
        const r = await chrome.storage.local.get("settings");
        if (r.settings) post({ type: "settings", data: r.settings });
      } catch (_) { /* nada */ }
      selectedId = await loadSelected();
      await render();
      if (selectedId) await select(selectedId, false);
      else post({ type: "cleared" });
    } else if (m.type === "add" && m.files) {
      await addFiles(m.files);
    } else if (m.type === "setRot") {
      await setRot(m.id, m.rot);
    } else if (m.type === "activate") {
      await checkLicense(String(m.key || ""));
    } else if (m.type === "saveSettings") {
      try { await chrome.storage.local.set({ settings: m.data }); } catch (_) { /* nada */ }
    } else if (m.type === "refresh") {
      await render();
    }
  });

  new ResizeObserver(reportHeight).observe(document.body);
  // Avisar a la página de que la biblioteca está lista (sin datos todavía)
  try { window.parent.postMessage({ gc: true, type: "hello" }, "*"); } catch (_) { /* nada */ }
})();
