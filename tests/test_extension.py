"""Prueba de la extensión en Chromium con cámara y micrófono falsos.

Se sirve una página de prueba en https://web.snapchat.com/__glowcam_test__
(interceptada, sin red) para que la extensión se inyecte como en Snapchat.
Uso: python tests/test_extension.py RUTA_VIDEO_CON_AUDIO.mp4 [captura.png]
"""
import asyncio
import os
import sys
import tempfile

from playwright.async_api import async_playwright

EXT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "extension")
TEST_URL = "https://web.snapchat.com/__glowcam_test__"
PAGE = "<!doctype html><html><head><meta charset=utf-8></head><body style='background:#fff'><h1>test</h1></body></html>"

# Lee el brillo medio y la variación de un fotograma de una pista de vídeo
FRAME_STATS = """
async (stream) => {
  const v = document.createElement('video'); v.muted = true; v.srcObject = stream; await v.play();
  await new Promise(r => setTimeout(r, 600));
  const c = document.createElement('canvas'); c.width = v.videoWidth; c.height = v.videoHeight;
  const g = c.getContext('2d'); g.drawImage(v, 0, 0);
  const d = g.getImageData(0, 0, c.width, c.height).data;
  let s = 0, s2 = 0, n = 0, rs = 0, gs = 0, bs = 0;
  for (let i = 0; i < d.length; i += 4 * 97) { const y = (d[i] + d[i+1] + d[i+2]) / 3; s += y; s2 += y*y; n++; rs += d[i]; gs += d[i+1]; bs += d[i+2]; }
  const m = s / n;
  return { w: v.videoWidth, h: v.videoHeight, mean: Math.round(m), std: Math.round(Math.sqrt(s2/n - m*m)), rgb: [rs/n|0, gs/n|0, bs/n|0], hash: (() => { let a = 7; for (let i = 0; i < d.length; i += 4 * 13) a = (a * 31 + d[i] + d[i+1]) % 1000003; return a; })() };
}
"""

AUDIO_LEVEL = """
async (stream) => {
  const ac = new AudioContext(); await ac.resume();
  const src = ac.createMediaStreamSource(stream); const an = ac.createAnalyser(); an.fftSize = 2048; src.connect(an);
  const buf = new Float32Array(an.fftSize); let peak = 0;
  for (let k = 0; k < 15; k++) { await new Promise(r => setTimeout(r, 100)); an.getFloatTimeDomainData(buf); for (const x of buf) peak = Math.max(peak, Math.abs(x)); }
  return Math.round(peak * 1000) / 1000;
}
"""


async def main(video_path, shot):
    results = {}
    ok = True

    def check(name, cond, info=""):
        nonlocal ok
        ok &= bool(cond)
        print(("✅" if cond else "❌"), name, info)

    async with async_playwright() as p:
        user_dir = tempfile.mkdtemp()
        ctx = await p.chromium.launch_persistent_context(
            user_dir,
            headless=True,
            channel="chromium",
            args=[
                f"--disable-extensions-except={EXT}",
                f"--load-extension={EXT}",
                "--use-fake-device-for-media-stream",
                "--use-fake-ui-for-media-stream",
                "--autoplay-policy=no-user-gesture-required",
            ],
            permissions=["camera", "microphone"],
            viewport={"width": 1280, "height": 860},
        )
        await ctx.route("https://web.snapchat.com/**", lambda r: r.fulfill(status=200, content_type="text/html", body=PAGE))
        page = await ctx.new_page()
        page.on("pageerror", lambda e: print("pageerror:", e))
        await page.goto(TEST_URL)
        await page.wait_for_function("window.__glowcam && document.getElementById('glowcam-root')", timeout=15000)
        check("Extensión cargada y panel visible", True)

        devs = await page.evaluate("navigator.mediaDevices.enumerateDevices().then(l => l.filter(d=>d.kind==='videoinput').map(d=>({id:d.deviceId,label:d.label})))")
        check("«GlowCam» aparece primero en la lista de cámaras", devs and devs[0]["label"] == "GlowCam", str([d["label"] for d in devs]))

        # --- Modo cámara ---
        await page.evaluate("window.__s = null")
        cam = await page.evaluate(f"""async () => {{
            const s = await navigator.mediaDevices.getUserMedia({{video: {{deviceId: {{exact: 'glowcam-virtual-camera'}}}}, audio: true}});
            window.__s = s;
            return {{v: s.getVideoTracks().length, a: s.getAudioTracks().length}};
        }}""")
        check("getUserMedia con GlowCam devuelve vídeo + audio", cam == {"v": 1, "a": 1}, str(cam))
        ident = await page.evaluate("""() => {
            const t = window.__s.getVideoTracks()[0]; const c = t.clone();
            const fake = (navigator.mediaDevices.enumerateDevices + '').includes('native code');
            return {id: t.getSettings().deviceId, label: t.label, cloneId: c.getSettings().deviceId, cloneLabel: c.label,
                    capsId: t.getCapabilities().deviceId, w: t.getSettings().width, h: t.getSettings().height, nativeLook: fake};
        }""")
        check("La pista dice ser «GlowCam» (Snapchat deja la opción marcada)",
              ident["id"] == "glowcam-virtual-camera" and ident["label"] == "GlowCam" and ident["cloneId"] == "glowcam-virtual-camera"
              and ident["cloneLabel"] == "GlowCam" and ident["capsId"] == "glowcam-virtual-camera" and (ident["w"], ident["h"]) == (720, 1280), str(ident))
        await page.wait_for_timeout(1500)
        st1 = await page.evaluate(f"({FRAME_STATS})(window.__s)")
        await page.wait_for_timeout(700)
        st2 = await page.evaluate(f"({FRAME_STATS})(window.__s)")
        check("Salida vertical 720×1280", (st1["w"], st1["h"]) == (720, 1280), f"{st1['w']}x{st1['h']}")
        check("Imagen de la cámara en movimiento (no congelada)", st1["hash"] != st2["hash"], f"std={st1['std']}")
        mic = await page.evaluate(f"({AUDIO_LEVEL})(new MediaStream(window.__s.getAudioTracks()))")
        check("Micrófono llega en modo cámara", mic > 0.01, f"pico={mic}")

        # Cámara real elegida explícitamente → no se sustituye
        real = await page.evaluate("""async () => {
            const l = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind==='videoinput' && d.deviceId !== 'glowcam-virtual-camera');
            const s = await navigator.mediaDevices.getUserMedia({video: {deviceId: {exact: l[0].deviceId}}});
            const t = s.getVideoTracks()[0]; const r = {label: t.label}; t.stop(); return r;
        }""")
        realset = await page.evaluate("""async () => {
            const l = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind==='videoinput' && d.deviceId !== 'glowcam-virtual-camera');
            const s = await navigator.mediaDevices.getUserMedia({video: {deviceId: {exact: l[0].deviceId}}});
            const t = s.getVideoTracks()[0]; const ok = t.getSettings().deviceId === l[0].deviceId; t.stop(); return ok;
        }""")
        check("Las cámaras reales conservan su propio identificador", realset)
        check("Elegir otra cámara en Snapchat sigue funcionando", "glowcam" not in real["label"].lower() and real["label"] != "", real["label"])

        # Formato con bordes
        await page.evaluate("window.__glowcam.S.format = 1")
        await page.wait_for_timeout(500)
        st3 = await page.evaluate(f"({FRAME_STATS})(window.__s)")
        check("Formato «con bordes» sale a 1280×720", (st3["w"], st3["h"]) == (1280, 720), f"{st3['w']}x{st3['h']}")
        await page.evaluate("window.__glowcam.S.format = 0")

        # --- Modo vídeo (subido desde el panel, como haría un chatter) ---
        await page.click("#glowcam-root >> .pill")
        await page.click("#glowcam-root >> .seg button:nth-child(2)")
        await page.set_input_files("#glowcam-root >> input[type=file]", video_path)
        await page.wait_for_function("window.__glowcam.S.videoId && !document.querySelector('#glowcam-root').shadowRoot.querySelector('.empty')", timeout=10000)
        await page.wait_for_timeout(1500)
        await page.evaluate("window.__s.getTracks().forEach(t => t.stop())")
        vid = await page.evaluate("""async () => {
            const s = await navigator.mediaDevices.getUserMedia({video: true, audio: true});
            window.__s = s; return {v: s.getVideoTracks().length, a: s.getAudioTracks().length};
        }""")
        check("getUserMedia en modo vídeo devuelve vídeo + audio", vid == {"v": 1, "a": 1}, str(vid))
        await page.wait_for_timeout(1000)
        sv = await page.evaluate(f"({FRAME_STATS})(window.__s)")
        check("Se ve el vídeo (imagen con contenido)", sv["std"] > 20, f"std={sv['std']} rgb={sv['rgb']}")
        lvl = await page.evaluate(f"({AUDIO_LEVEL})(new MediaStream(window.__s.getAudioTracks()))")
        check("El audio del vídeo llega a Snapchat", lvl > 0.05, f"pico={lvl}")

        # Audio-only (Snapchat a veces pide el micro por separado)
        ao = await page.evaluate(f"""async () => {{
            const s = await navigator.mediaDevices.getUserMedia({{audio: true}});
            return ({AUDIO_LEVEL})(s);
        }}""")
        check("Petición solo de micrófono también lleva el audio del vídeo", ao > 0.05, f"pico={ao}")

        # Persistencia: recargar y comprobar que el vídeo sigue en la lista
        await page.reload()
        await page.wait_for_function("document.getElementById('glowcam-root')", timeout=15000)
        await page.click("#glowcam-root >> .pill")
        await page.wait_for_timeout(1200)
        n = await page.evaluate("document.querySelector('#glowcam-root').shadowRoot.querySelectorAll('.vid').length")
        check("El vídeo queda guardado tras recargar", n == 1, f"{n} vídeo(s)")

        if shot:
            await page.wait_for_timeout(1500)
            await page.screenshot(path=shot)
        await ctx.close()
    return ok


if __name__ == "__main__":
    good = asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))
    print("\nRESULTADO:", "TODO OK" if good else "HAY FALLOS")
    sys.exit(0 if good else 1)
