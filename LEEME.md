# GlowCam

Herramientas para usar en las videollamadas de **Snapchat web** (o la app de Snapchat instalada desde Chrome):

- **📷 Cámara:** tu cámara en el recuadro vertical de Snapchat (9:16), con zoom y encuadre.
- **🎬 Vídeo:** reproduce un vídeo en la llamada, **con su audio**.

Hay dos formas de usarlo. **La recomendada es la extensión de Chrome.**

---

## ⭐ Extensión de Chrome (Mac y Windows) — recomendada

No necesita OBS, ni drivers, ni micrófono virtual. El audio del vídeo va incluido.

### Instalar (una sola vez, 1 minuto)

1. Descarga **GlowCam-Extension.zip**:
   https://github.com/criisttiian9819-ai/glowcam/releases/latest/download/GlowCam-Extension.zip
2. Descomprímelo (doble clic) y **mueve la carpeta `GlowCam-Extension` a Documentos**. No la borres: Chrome la usa.
3. En Chrome, escribe en la barra de direcciones: `chrome://extensions`
4. Arriba a la derecha, activa **«Modo de desarrollador»**.
5. Pulsa **«Cargar descomprimida»** y elige la carpeta **GlowCam-Extension**.
6. Cierra y vuelve a abrir Snapchat (la web o la app instalada desde Chrome).

### Usar

1. En Snapchat aparece abajo a la derecha el botón rosa **● GlowCam**. Púlsalo para abrir el panel.
2. Elige **📷 Cámara** (y qué cámara) o **🎬 Vídeo** (pulsa «＋ Añadir vídeo» o arrastra el vídeo al panel; se quedan guardados).
3. Ajusta formato, zoom y encuadre mirando la vista previa.
4. En la videollamada, en el selector de cámara de Snapchat, elige **«GlowCam»**.

Opciones del modo vídeo:
- **Repetir en bucle**.
- **Escucharlo yo**: oyes el vídeo por tus altavoces (mejor con auriculares).
- **Mezclar mi micro**: el fan oye el vídeo y además tu voz.

> Mantén la ventana de Snapchat visible durante la llamada para que la imagen vaya fluida.
> Para volver a tu cámara normal: elige tu cámara de siempre en Snapchat, o desmarca «Activado» en el panel.

---

## Programa GlowCam para Windows (alternativa)

Instalador todo en uno con cámara virtual incluida (sin OBS):
https://github.com/criisttiian9819-ai/glowcam/releases/latest/download/GlowCam-Windows.exe

1. Ábrelo. Si sale «Windows protegió su PC»: **Más información → Ejecutar de todas formas**. Acepta el permiso → Instalar.
2. Abre GlowCam, elige la cámara y pulsa **Activar cámara virtual**.
3. En Snapchat elige la cámara **«OBS Virtual Camera»**.
4. Para el modo Vídeo con audio hace falta además VB-CABLE (https://vb-audio.com/Cable); en Snapchat, micrófono «CABLE Output».

(En Mac el programa necesita OBS y no es fiable: usa la extensión.)

---

## Nuevas versiones

Cada etiqueta nueva (`v1.3.1`, `v1.4.0`…) en el repositorio hace que GitHub pruebe y genere las descargas solo. Los links siempre apuntan a la última versión.

Para actualizar la extensión: descarga el zip nuevo, sustituye la carpeta GlowCam-Extension por la nueva y en `chrome://extensions` pulsa ↻ en GlowCam.

La cámara virtual de Windows es el componente de OBS Studio (licencia GPL, incluida en `vcam\OBS-LICENSE.txt`).
