// Le dice al script de la página dónde está la biblioteca de vídeos de la extensión.
try {
  document.documentElement.setAttribute("data-glowcam-base", chrome.runtime.getURL(""));
} catch (_) { /* sin acceso */ }
