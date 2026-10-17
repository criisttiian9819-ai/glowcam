"""Prueba de la extensión en Chromium con cámara y micrófono falsos.

Se sirve una página de prueba en https://web.snapchat.com/__glowcam_test__
(interceptada, sin red) para que la extensión se inyecte como en Snapchat.
Uso: python tests/test_extension.py RUTA_VIDEO_CON_AUDIO.mp4 [captura.png]
"""
import asyncio
import os
import sys
import json
import re
import shutil
import tempfile
from urllib.parse import parse_qs, urlparse

from playwright.async_api import async_playwright

EXT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "extension")
LICENSE_URL = "https://script.google.com/macros/s/TEST/exec"
GOOD_KEY = "GLOW-TEST-1234-ABCD"
SERVER = {"offline": False, "calls": 0, "keys": {GOOD_KEY: {"user": "Nicolás", "active": True, "device": ""}}}
TEST_URL = "https://web.snapchat.com/__glowcam_test__"
PAGE = ("<!doctype html><html><head><meta charset=utf-8></head><body style='background:#fff'><h1>test</h1>"
        "<button aria-label='End call' id='endcall' onclick='window.__hang=(window.__hang||0)+1'>📞</button> "
        "<button id='weird' onclick='window.__weird=(window.__weird||0)+1'>✖</button></body></html>")

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
        # Copia de la extensión apuntando a un panel de claves simulado
        ext = os.path.join(tempfile.mkdtemp(), "ext")
        shutil.copytree(EXT, ext)
        lp = os.path.join(ext, "library.js")
        with open(lp, encoding="utf-8") as f:
            src = f.read()
        with open(lp, "w", encoding="utf-8") as f:
            f.write(re.sub(r'const LICENSE_URL = "[^"]*";', 'const LICENSE_URL = "' + LICENSE_URL + '";', src))
        ctx = await p.chromium.launch_persistent_context(
            user_dir,
            headless=True,
            channel="chromium",
            args=[
                f"--disable-extensions-except={ext}",
                f"--load-extension={ext}",
                "--use-fake-device-for-media-stream",
                "--use-fake-ui-for-media-stream",
                "--autoplay-policy=no-user-gesture-required",
            ],
            permissions=["camera", "microphone"],
            viewport={"width": 1280, "height": 860},
        )
        await ctx.route("https://web.snapchat.com/**", lambda r: r.fulfill(status=200, content_type="text/html", body=PAGE))

        async def license_route(route):
            if SERVER["offline"]:
                await route.abort()
                return
            q = {k: v[0] for k, v in parse_qs(urlparse(route.request.url).query).items()}
            SERVER["calls"] += 1
            u = SERVER["keys"].get(q.get("key", "").upper())
            if q.get("action") != "check":
                res = {"ok": False, "reason": "bad_request"}
            elif not u:
                res = {"ok": False, "reason": "invalid"}
            elif not u["active"]:
                res = {"ok": False, "reason": "disabled"}
            elif u["device"] and u["device"] != q.get("device"):
                res = {"ok": False, "reason": "device"}
            else:
                u["device"] = u["device"] or q.get("device")
                res = {"ok": True, "user": u["user"]}
            await route.fulfill(status=200, content_type="application/json", body=json.dumps(res))
        await ctx.route("https://script.google.com/**", license_route)
        await ctx.route("https://raw.githubusercontent.com/**", lambda r: r.fulfill(status=200, content_type="application/json", body='{"version": "9.9.9"}'))
        page = await ctx.new_page()
        page.on("pageerror", lambda e: print("pageerror:", e))
        await page.goto(TEST_URL)
        await page.wait_for_function("window.__glowcam && document.getElementById('glowcam-root')", timeout=15000)
        check("Extensión cargada y panel visible", True)

        # --- Clave de acceso ---
        await page.wait_for_timeout(1500)
        locked_devs = await page.evaluate("navigator.mediaDevices.enumerateDevices().then(l => l.filter(d=>d.kind==='videoinput').map(d=>d.label))")
        check("Sin clave: GlowCam no aparece en Snapchat", "GlowCam" not in locked_devs, str(locked_devs))
        await page.click("#glowcam-root >> .pill")
        await page.fill("#glowcam-root >> .keyinput", "GLOW-AAAA-BBBB-CCCC")
        await page.click("#glowcam-root >> .lock .btn.primary")
        await page.wait_for_function("document.querySelector('#glowcam-root').shadowRoot.querySelector('.lockmsg').textContent.length > 0", timeout=10000)
        msg = await page.evaluate("document.querySelector('#glowcam-root').shadowRoot.querySelector('.lockmsg').textContent")
        check("Clave incorrecta: avisa y sigue bloqueado", "incorrecta" in msg, msg)
        await page.fill("#glowcam-root >> .keyinput", GOOD_KEY.lower())
        await page.click("#glowcam-root >> .lock .btn.primary")
        await page.wait_for_function("!document.querySelector('#glowcam-root').shadowRoot.querySelector('.panel').classList.contains('locked')", timeout=10000)
        who = await page.evaluate("document.querySelector('#glowcam-root').shadowRoot.querySelector('.who').textContent")
        check("Clave buena: se desbloquea y muestra el chatter", "Nicolás" in who, who)
        upd = await page.evaluate("getComputedStyle(document.querySelector('#glowcam-root').shadowRoot.querySelector('.update')).display")
        check("Avisa cuando hay una versión nueva", upd == "block", upd)

        # Botón abajo a la izquierda, arrastrable y que recuerda su sitio
        SR = "document.querySelector('#glowcam-root').shadowRoot"
        pr = await page.evaluate(f"(() => {{ const r = {SR}.querySelector('.panel').getBoundingClientRect(); return [r.left, r.top]; }})()")
        await page.click("#glowcam-root >> .close")
        closed = await page.evaluate(f"!{SR}.querySelector('.panel').classList.contains('open')")
        check("El ✕ cierra la ventana", closed)
        b = await page.evaluate(f"(() => {{ const r = {SR}.querySelector('.pill').getBoundingClientRect(); return [r.left, r.bottom, innerHeight]; }})()")
        check("El botón sale abajo a la izquierda", b[0] < 40 and b[2] - b[1] < 40, str(b))
        await page.mouse.move(b[0] + 30, b[1] - 15)
        await page.mouse.down()
        await page.mouse.move(400, 300, steps=8)
        await page.mouse.up()
        b2 = await page.evaluate(f"(() => {{ const r = {SR}.querySelector('.pill').getBoundingClientRect(); return [Math.round(r.left), Math.round(r.top)]; }})()")
        still_closed = await page.evaluate(f"!{SR}.querySelector('.panel').classList.contains('open')")
        check("Se puede arrastrar el botón (sin abrir la ventana)", abs(b2[0] - 370) < 25 and abs(b2[1] - 285) < 25 and still_closed, str(b2))
        await page.wait_for_timeout(600)
        await page.click("#glowcam-root >> .pill")
        hd = await page.evaluate(f"(() => {{ const r = {SR}.querySelector('.head .title').getBoundingClientRect(); return [r.left + 5, r.top + 5]; }})()")
        await page.mouse.move(hd[0], hd[1])
        await page.mouse.down()
        await page.mouse.move(hd[0] + 250, hd[1] + 40, steps=8)
        await page.mouse.up()
        p2 = await page.evaluate(f"(() => {{ const r = {SR}.querySelector('.panel').getBoundingClientRect(); return [Math.round(r.left), Math.round(r.top)]; }})()")
        check("Se puede arrastrar la ventana por el título", p2[0] > 200, f"antes={[round(x) for x in pr]} después={p2}")
        await page.reload()
        await page.wait_for_function("document.getElementById('glowcam-root')", timeout=15000)
        await page.wait_for_timeout(1500)
        b3 = await page.evaluate(f"(() => {{ const r = {SR}.querySelector('.pill').getBoundingClientRect(); return [Math.round(r.left), Math.round(r.top)]; }})()")
        check("Recuerda dónde dejaste el botón", abs(b3[0] - b2[0]) < 3 and abs(b3[1] - b2[1]) < 3, str(b3))
        await page.click("#glowcam-root >> .pill")
        p3 = await page.evaluate(f"(() => {{ const r = {SR}.querySelector('.panel').getBoundingClientRect(); return [Math.round(r.left), Math.round(r.top)]; }})()")
        check("Recuerda dónde dejaste la ventana", abs(p3[0] - p2[0]) < 3 and abs(p3[1] - p2[1]) < 3, str(p3))
        await page.click("#glowcam-root >> .close")


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

        # --- Modo vídeo: biblioteca (iframe de la extensión), como haría un chatter ---
        LIB = "#glowcam-root iframe"
        await page.click("#glowcam-root >> .pill")
        await page.click("#glowcam-root >> .seg button:nth-child(2)")
        lib = page.frame_locator(LIB)
        await lib.locator("#add").wait_for(timeout=10000)
        await lib.locator("#file").set_input_files(video_path)
        await page.wait_for_function("window.__glowcam.currentVideo", timeout=15000)
        await lib.locator("#file").set_input_files(video_path)
        await lib.locator(".row >> nth=1").wait_for(timeout=15000)
        rows = await lib.locator(".row").count()
        check("Se pueden guardar varios vídeos en la biblioteca", rows == 2, f"{rows} vídeos")
        thumbs = await lib.locator("img.thumb").count()
        check("Cada vídeo tiene miniatura", thumbs == 2, f"{thumbs} miniaturas")
        # Elegir el otro vídeo de la lista
        first_id = await page.evaluate("window.__glowcam.currentVideo.id")
        await lib.locator(".row:not(.sel)").first.click()
        await page.wait_for_function(f"window.__glowcam.currentVideo && window.__glowcam.currentVideo.id !== '{first_id}'", timeout=10000)
        check("Elegir otro vídeo de la lista lo cambia", True)
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

        # Girar el vídeo 90°
        await page.evaluate("window.__glowcam.videoEl.pause(); window.__glowcam.videoEl.currentTime = 1")
        await page.wait_for_timeout(600)
        before = await page.evaluate(f"({FRAME_STATS})(window.__s)")
        await page.click("#glowcam-root >> button[title='Girar 90°']")
        await page.wait_for_timeout(600)
        after = await page.evaluate(f"({FRAME_STATS})(window.__s)")
        rot = await page.evaluate("window.__glowcam.currentVideo.rot")
        label = await page.evaluate("document.querySelector('#glowcam-root').shadowRoot.querySelector('.rotlabel').textContent")
        check("Girar 90° cambia la imagen y mantiene 720×1280",
              rot == 90 and before["hash"] != after["hash"] and (after["w"], after["h"]) == (720, 1280) and label == "90°",
              f"rot={rot} etiqueta={label} {after['w']}x{after['h']}")
        sel_id = await page.evaluate("window.__glowcam.currentVideo.id")

        # Colgar al terminar el vídeo
        await page.click("#glowcam-root >> text=Colgar al terminar el vídeo")
        loop_off = await page.evaluate("!window.__glowcam.S.loop && window.__glowcam.S.autoHang")
        await page.evaluate("(() => { const v = window.__glowcam.videoEl; v.currentTime = Math.max(0, v.duration - 0.4); return v.play(); })()")
        await page.wait_for_timeout(2500)
        hang = await page.evaluate("window.__hang || 0")
        check("Al terminar el vídeo pulsa el botón de colgar", hang == 1 and loop_off, f"clics en colgar={hang}, bucle desactivado={loop_off}")

        # Enseñar un botón de colgar con otro nombre
        await page.click("#glowcam-root >> button[title='Enseñar botón de colgar']")
        await page.click("#weird")
        await page.evaluate("window.__glowcam.hangUp()")
        weird = await page.evaluate("window.__weird || 0")
        check("El botón «enseñado» se usa para colgar", weird == 2, f"clics={weird} (1 al enseñarlo + 1 al colgar)")
        await page.wait_for_timeout(1000)

        # Persistencia: Snapchat borra SUS datos y se recarga → la biblioteca sigue
        await page.evaluate("""async () => {
            localStorage.clear(); sessionStorage.clear();
            const dbs = indexedDB.databases ? await indexedDB.databases() : [];
            await Promise.all(dbs.map(d => new Promise(r => { const q = indexedDB.deleteDatabase(d.name); q.onsuccess = q.onerror = q.onblocked = r; })));
        }""")
        await page.reload()
        await page.wait_for_function("document.getElementById('glowcam-root')", timeout=15000)
        await page.click("#glowcam-root >> .pill")
        await page.click("#glowcam-root >> .seg button:nth-child(2)")
        lib = page.frame_locator(LIB)
        await lib.locator(".row >> nth=1").wait_for(timeout=15000)
        n = await lib.locator(".row").count()
        check("Los vídeos siguen guardados aunque Snapchat borre sus datos", n == 2, f"{n} vídeo(s)")
        await page.wait_for_function("window.__glowcam.currentVideo", timeout=10000)
        restored = await page.evaluate("({id: window.__glowcam.currentVideo.id, rot: window.__glowcam.currentVideo.rot})")
        check("Se recuerda el vídeo elegido y su giro", restored == {"id": sel_id, "rot": 90}, str(restored))
        await page.wait_for_timeout(800)
        kept = await page.evaluate("({ah: window.__glowcam.S.autoHang, loop: window.__glowcam.S.loop, btn: !!window.__glowcam.S.hangBtn, src: window.__glowcam.S.source})")
        check("Los ajustes (colgar, bucle, botón enseñado) también se conservan", kept == {"ah": True, "loop": False, "btn": True, "src": "video"}, str(kept))
        devs2 = await page.evaluate("navigator.mediaDevices.enumerateDevices().then(l => l.map(d=>d.label))")
        check("La clave sigue activa tras recargar (no la vuelve a pedir)", "GlowCam" in devs2)

        # Sin internet: sigue funcionando (margen de 12 h)
        SERVER["offline"] = True
        await page.reload()
        await page.wait_for_function("document.getElementById('glowcam-root')", timeout=15000)
        await page.wait_for_timeout(2500)
        off = await page.evaluate("document.querySelector('#glowcam-root').shadowRoot.querySelector('.panel').classList.contains('locked')")
        check("Sin internet sigue funcionando", off is False)
        SERVER["offline"] = False

        # El responsable desactiva la clave → al volver a abrir Snapchat se bloquea
        SERVER["keys"][GOOD_KEY]["active"] = False
        await page.reload()
        await page.wait_for_function("document.getElementById('glowcam-root')", timeout=15000)
        await page.wait_for_function("document.querySelector('#glowcam-root').shadowRoot.querySelector('.panel').classList.contains('locked')", timeout=10000)
        devs3 = await page.evaluate("navigator.mediaDevices.enumerateDevices().then(l => l.map(d=>d.label))")
        await page.click("#glowcam-root >> .pill")
        msg3 = await page.evaluate("document.querySelector('#glowcam-root').shadowRoot.querySelector('.lockmsg').textContent")
        check("Clave desactivada: se bloquea y pide clave", "GlowCam" not in devs3 and "desactivado" in msg3, msg3)
        prev_calls = SERVER["calls"]

        # Clave usada ya en otro ordenador
        SERVER["keys"]["GLOW-OTRO-PC22-XXXX"] = {"user": "Ana", "active": True, "device": "PC-de-otra-persona"}
        await page.fill("#glowcam-root >> .keyinput", "GLOW-OTRO-PC22-XXXX")
        await page.click("#glowcam-root >> .lock .btn.primary")
        await page.wait_for_function("document.querySelector('#glowcam-root').shadowRoot.querySelector('.lockmsg').textContent.includes('ordenador')", timeout=10000)
        check("Clave de otro ordenador: no se puede compartir", SERVER["calls"] > prev_calls)

        # Reactivar → vuelve a funcionar al meter la clave
        SERVER["keys"][GOOD_KEY]["active"] = True
        await page.fill("#glowcam-root >> .keyinput", GOOD_KEY)
        await page.click("#glowcam-root >> .lock .btn.primary")
        await page.wait_for_function("!document.querySelector('#glowcam-root').shadowRoot.querySelector('.panel').classList.contains('locked')", timeout=10000)
        check("Al reactivarla y meter la clave vuelve a funcionar", True)

        if shot:
            await page.wait_for_timeout(1500)
            await page.screenshot(path=shot)
        await ctx.close()
    return ok


if __name__ == "__main__":
    good = asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))
    print("\nRESULTADO:", "TODO OK" if good else "HAY FALLOS")
    sys.exit(0 if good else 1)
