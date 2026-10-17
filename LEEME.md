# GlowCam

Cámara virtual sencilla para Snapchat web, con dos modos:

- **📷 Cámara:** eliges la webcam y sale en el recuadro vertical de Snapchat (9:16).
- **🎬 Vídeo:** reproduces un vídeo; la imagen sale por la cámara virtual y el **audio por un micrófono virtual**, así Snapchat ve y oye el vídeo.

---

## Guía para el equipo — Windows

### Instalar (una sola vez)

1. Descarga **GlowCam-Windows.exe** desde el link que te pasa Cristian y ábrelo.
2. Si sale «Windows protegió su PC»: **Más información → Ejecutar de todas formas**.
3. Acepta el permiso de administrador → **Instalar** → **Finalizar**.

Ya está: la cámara virtual va incluida. **No hace falta OBS.**

*Solo si vas a usar el modo Vídeo:* instala también **VB-CABLE** (gratis) desde https://vb-audio.com/Cable → descomprimir → clic derecho en `VBCABLE_Setup_x64.exe` → *Ejecutar como administrador* → *Install Driver* → reiniciar el PC.

### Usar la cámara

1. Abre **GlowCam** (icono del escritorio) → **📷 Cámara** → elige tu cámara.
2. Pulsa **Activar cámara virtual**.
3. En **web.snapchat.com**, en la videollamada: cámara **«OBS Virtual Camera»** y tu micrófono normal.

### Reproducir un vídeo con su audio

1. **🎬 Vídeo** → **Elegir vídeo…** (o arrastra el vídeo a la ventana).
2. En **«Audio a»** elige **CABLE Input** (marcado con 🎤).
3. Pulsa **Activar cámara virtual**.
4. En **web.snapchat.com**: cámara **«OBS Virtual Camera»** y micrófono **«CABLE Output»**.

> Mientras el audio va al micrófono virtual no lo oyes por tus altavoces (lo oye Snapchat). Es normal.
> Si un vídeo sale tumbado, pulsa **⟳ Girar**.

---

## Mac (Cristian)

1. Instala **OBS** (https://obsproject.com), ábrelo una vez, pulsa **«Iniciar cámara virtual»**, acepta el permiso en *Ajustes del Sistema → Privacidad y seguridad* y ciérralo.
2. Para el modo Vídeo: instala **BlackHole 2ch** (https://existential.audio/blackhole). En GlowCam, «Audio a» → BlackHole 2ch; en Snapchat, micrófono → BlackHole 2ch.
3. Abre **GlowCam-Mac.dmg** y arrastra GlowCam a Aplicaciones. Si el Mac lo bloquea: *Ajustes del Sistema → Privacidad y seguridad → Abrir igualmente*.

---

## Formatos

- *Vertical 9:16 (Snapchat)*: el normal.
- *Vertical con bordes (16:9)*: por si Snapchat recorta la imagen vertical.
- *Horizontal 16:9*: imagen apaisada clásica.

## Nuevas versiones

Cada vez que se publica una etiqueta nueva (`v1.2.1`, `v1.3.0`…) en el repositorio, GitHub compila y prueba los instaladores solo. Los links siempre apuntan a la última versión:

- `https://github.com/USUARIO/glowcam/releases/latest/download/GlowCam-Windows.exe`
- `https://github.com/USUARIO/glowcam/releases/latest/download/GlowCam-Mac.dmg`

La cámara virtual de Windows es el componente de OBS Studio (licencia GPL, incluida en `vcam\OBS-LICENSE.txt`).
