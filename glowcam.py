"""
GlowCam — cámara virtual sencilla con formato vertical de Snapchat.

Dos fuentes:
  * Cámara: elige una webcam y la envía recortada a 9:16.
  * Vídeo: reproduce un archivo de vídeo por la cámara virtual y su audio por
    un micrófono virtual (VB-CABLE en Windows, BlackHole en Mac).

La cámara virtual usa el driver de OBS, que debe estar instalado.
"""
import os
import sys

import numpy as np
from PySide6.QtCore import QRect, QSettings, Qt, QUrl
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QTransform
from PySide6.QtMultimedia import (
    QAudioOutput,
    QCamera,
    QMediaCaptureSession,
    QMediaDevices,
    QMediaPlayer,
    QVideoSink,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

try:
    import pyvirtualcam
except Exception:  # noqa: BLE001
    pyvirtualcam = None

APP_NAME = "GlowCam"
APP_VERSION = "1.2.0"
FPS = 30

# (nombre visible, ancho salida, alto salida, vertical con bordes)
FORMATS = [
    ("Vertical 9:16 (Snapchat)", 720, 1280, False),
    ("Vertical con bordes (16:9)", 1280, 720, True),
    ("Horizontal 16:9", 1280, 720, False),
]

SOURCE_CAMERA = 0
SOURCE_VIDEO = 1

# Cámaras que no se ofrecen para evitar que la app se capture a sí misma
BLOCKED_CAMERA_WORDS = ("obs virtual", "glowcam")

# Palabras que identifican un micrófono virtual (cable de audio)
VIRTUAL_AUDIO_WORDS = ("cable input", "vb-audio", "blackhole", "loopback", "soundflower")

VIDEO_EXTENSIONS = (".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".wmv")


# ---------------------------------------------------------------------------
# Lógica de imagen (sin interfaz, se puede probar por separado)
# ---------------------------------------------------------------------------
def compute_crop(src_w, src_h, aspect, zoom=1.0, off_x=0.0, off_y=0.0):
    """Devuelve (x, y, ancho, alto) del recorte con la proporción `aspect`.

    zoom >= 1 acerca la imagen. off_x / off_y van de -1 (izquierda/arriba)
    a 1 (derecha/abajo); 0 es centrado.
    """
    zoom = max(1.0, float(zoom))
    if src_w / src_h > aspect:
        ch = src_h / zoom
        cw = ch * aspect
    else:
        cw = src_w / zoom
        ch = cw / aspect
    cw = max(2, min(src_w, int(round(cw))))
    ch = max(2, min(src_h, int(round(ch))))
    off_x = max(-1.0, min(1.0, float(off_x)))
    off_y = max(-1.0, min(1.0, float(off_y)))
    x = int(round((src_w - cw) / 2 * (1 + off_x)))
    y = int(round((src_h - ch) / 2 * (1 + off_y)))
    x = max(0, min(src_w - cw, x))
    y = max(0, min(src_h - ch, y))
    return x, y, cw, ch


def _scaled(img, w, h):
    return img.scaled(
        w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def compose_frame(src, fmt_index, zoom=1.0, off_x=0.0, off_y=0.0, mirror=False, rotation=0):
    """Convierte un QImage de la fuente en el fotograma final de salida."""
    _, out_w, out_h, pillarbox = FORMATS[fmt_index]
    rotation = int(rotation) % 360
    if rotation:
        src = src.transformed(QTransform().rotate(rotation), Qt.TransformationMode.SmoothTransformation)
    if mirror:
        src = src.flipped(Qt.Orientation.Horizontal) if hasattr(src, "flipped") else src.mirrored(True, False)
    sw, sh = src.width(), src.height()

    if not pillarbox:
        x, y, cw, ch = compute_crop(sw, sh, out_w / out_h, zoom, off_x, off_y)
        out = _scaled(src.copy(QRect(x, y, cw, ch)), out_w, out_h)
        return out.convertToFormat(QImage.Format.Format_RGB888)

    # Vertical 9:16 centrado dentro de un lienzo 16:9 con fondo desenfocado
    out = QImage(out_w, out_h, QImage.Format.Format_RGB888)
    out.fill(QColor(0, 0, 0))
    bx, by, bw, bh = compute_crop(sw, sh, out_w / out_h, 1.0, 0, 0)
    blur = _scaled(_scaled(src.copy(QRect(bx, by, bw, bh)), 32, 18), out_w, out_h)
    inner_h = out_h
    inner_w = int(round(inner_h * 9 / 16))
    x, y, cw, ch = compute_crop(sw, sh, 9 / 16, zoom, off_x, off_y)
    inner = _scaled(src.copy(QRect(x, y, cw, ch)), inner_w, inner_h)
    p = QPainter(out)
    p.drawImage(0, 0, blur)
    p.fillRect(0, 0, out_w, out_h, QColor(0, 0, 0, 140))
    p.drawImage((out_w - inner_w) // 2, 0, inner)
    p.end()
    return out


def qimage_to_rgb_array(img):
    """QImage -> array numpy (alto, ancho, 3) RGB uint8 contiguo."""
    img = img.convertToFormat(QImage.Format.Format_RGB888)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    buf = np.frombuffer(img.constBits(), dtype=np.uint8, count=bpl * h)
    arr = buf.reshape(h, bpl)[:, : w * 3].reshape(h, w, 3)
    return np.ascontiguousarray(arr)


def is_blocked_camera(description):
    d = description.lower()
    return any(word in d for word in BLOCKED_CAMERA_WORDS)


def is_virtual_audio(description):
    d = description.lower()
    return any(word in d for word in VIRTUAL_AUDIO_WORDS)


def is_video_file(path):
    return path.lower().endswith(VIDEO_EXTENSIONS)


def format_ms(ms):
    s = max(0, int(ms // 1000))
    return f"{s // 60}:{s % 60:02d}"


def pick_camera_format(device):
    """Elige la mejor resolución hasta 1080p con al menos 24 fps."""
    best, best_score = None, -1
    for f in device.videoFormats():
        res = f.resolution()
        w, h = res.width(), res.height()
        if h > 1080 or f.maxFrameRate() < 24:
            continue
        score = w * h
        if score > best_score:
            best, best_score = f, score
    return best


# ---------------------------------------------------------------------------
# Interfaz
# ---------------------------------------------------------------------------
STYLE = """
QWidget { background: #141418; color: #f2f2f5; font-size: 14px; }
QLabel#title { font-size: 22px; font-weight: 700; color: #ff5fa2; }
QLabel#hint { color: #a0a0ad; font-size: 12px; }
QLabel#status { color: #c8c8d2; font-size: 13px; }
QLabel#file { color: #c8c8d2; font-size: 12px; }
QComboBox, QPushButton { background: #24242c; border: 1px solid #34343f;
    border-radius: 8px; padding: 8px 10px; }
QComboBox QAbstractItemView { background: #24242c; selection-background-color: #ff5fa2; }
QPushButton:hover { border-color: #ff5fa2; }
QPushButton#seg { border-radius: 0; padding: 8px; }
QPushButton#seg:checked { background: #ff5fa2; color: #141418; font-weight: 700; border-color: #ff5fa2; }
QPushButton#go { background: #ff5fa2; color: #141418; font-size: 16px;
    font-weight: 700; border: none; padding: 14px; }
QPushButton#go[active="true"] { background: #e8445a; color: white; }
QSlider::groove:horizontal { height: 6px; background: #34343f; border-radius: 3px; }
QSlider::handle:horizontal { background: #ff5fa2; width: 16px; margin: -6px 0; border-radius: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #55555f; border-radius: 4px; background: #24242c; }
QCheckBox::indicator:checked { background: #ff5fa2; border-color: #ff5fa2; }
"""


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.setAcceptDrops(True)
        self.settings = QSettings("GlowModelsMedia", APP_NAME)

        self.source = SOURCE_CAMERA
        self.rotation = 0
        self.camera = None
        self.vcam = None
        self.devices = []
        self.audio_devices = []
        self.video_path = None
        self._seeking = False

        # Cámara
        self.session = QMediaCaptureSession()
        self.cam_sink = QVideoSink()
        self.session.setVideoSink(self.cam_sink)
        self.cam_sink.videoFrameChanged.connect(lambda f: self.on_frame(f, SOURCE_CAMERA))

        # Vídeo
        self.player = QMediaPlayer()
        self.video_sink = QVideoSink()
        self.player.setVideoSink(self.video_sink)
        self.video_sink.videoFrameChanged.connect(lambda f: self.on_frame(f, SOURCE_VIDEO))
        self.audio_out = QAudioOutput()
        self.player.setAudioOutput(self.audio_out)
        self.player.positionChanged.connect(self.on_position)
        self.player.durationChanged.connect(self.on_duration)
        self.player.playbackStateChanged.connect(self.on_playback_state)
        self.player.errorOccurred.connect(lambda _e, msg: self._set_status(f"Error de vídeo: {msg}"))

        self.media_devices = QMediaDevices()
        self.media_devices.videoInputsChanged.connect(self.refresh_cameras)
        self.media_devices.audioOutputsChanged.connect(self.refresh_audio_outputs)

        self._build_ui()
        self._load_settings()
        self.refresh_audio_outputs()
        self.set_source(self.source)

    # ----- UI -----
    def _build_ui(self):
        self.preview = QLabel("Elige una cámara o un vídeo")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(320, 569)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.preview.setStyleSheet("background:#000; border-radius:12px; color:#666;")

        title = QLabel(APP_NAME)
        title.setObjectName("title")

        # Selector de fuente (Cámara / Vídeo)
        self.btn_cam = QPushButton("📷  Cámara")
        self.btn_vid = QPushButton("🎬  Vídeo")
        seg = QHBoxLayout()
        seg.setSpacing(0)
        for b, src in ((self.btn_cam, SOURCE_CAMERA), (self.btn_vid, SOURCE_VIDEO)):
            b.setObjectName("seg")
            b.setCheckable(True)
            b.clicked.connect(lambda _c=False, s=src: self.set_source(s))
            seg.addWidget(b)

        # Panel cámara
        self.cam_combo = QComboBox()
        self.cam_combo.currentIndexChanged.connect(self.on_camera_changed)
        refresh_btn = QPushButton("↻")
        refresh_btn.setFixedWidth(44)
        refresh_btn.setToolTip("Buscar cámaras de nuevo")
        refresh_btn.clicked.connect(self.refresh_cameras)
        cam_row = QHBoxLayout()
        cam_row.setContentsMargins(0, 0, 0, 0)
        cam_row.addWidget(self.cam_combo, 1)
        cam_row.addWidget(refresh_btn)
        cam_panel = QWidget()
        cam_panel_l = QFormLayout(cam_panel)
        cam_panel_l.setContentsMargins(0, 0, 0, 0)
        cam_panel_l.addRow("Cámara", cam_row)

        # Panel vídeo
        choose_btn = QPushButton("Elegir vídeo…")
        choose_btn.clicked.connect(self.choose_video)
        self.file_label = QLabel("O arrastra un vídeo a la ventana")
        self.file_label.setObjectName("file")
        self.file_label.setWordWrap(True)
        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedWidth(52)
        self.play_btn.clicked.connect(self.toggle_play)
        self.pos_slider = QSlider(Qt.Orientation.Horizontal)
        self.pos_slider.setRange(0, 0)
        self.pos_slider.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.pos_slider.sliderReleased.connect(self.on_seek)
        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setObjectName("file")
        play_row = QHBoxLayout()
        play_row.setContentsMargins(0, 0, 0, 0)
        play_row.addWidget(self.play_btn)
        play_row.addWidget(self.pos_slider, 1)
        self.loop_chk = QCheckBox("Repetir en bucle")
        self.loop_chk.toggled.connect(self.on_loop_toggled)

        self.audio_combo = QComboBox()
        self.audio_combo.currentIndexChanged.connect(self.on_audio_device_changed)
        self.volume = self._slider(0, 100, 100)
        self.volume.valueChanged.connect(lambda v: self.audio_out.setVolume(v / 100.0))
        self.audio_hint = QLabel()
        self.audio_hint.setObjectName("hint")
        self.audio_hint.setWordWrap(True)

        vid_panel = QWidget()
        vid_l = QVBoxLayout(vid_panel)
        vid_l.setContentsMargins(0, 0, 0, 0)
        vid_l.addWidget(choose_btn)
        vid_l.addWidget(self.file_label)
        vid_l.addLayout(play_row)
        vid_l.addWidget(self.time_label, 0, Qt.AlignmentFlag.AlignRight)
        vid_l.addWidget(self.loop_chk)
        audio_form = QFormLayout()
        audio_form.addRow("Audio a", self.audio_combo)
        audio_form.addRow("Volumen", self.volume)
        vid_l.addLayout(audio_form)
        vid_l.addWidget(self.audio_hint)

        self.stack = QStackedWidget()
        self.stack.addWidget(cam_panel)
        self.stack.addWidget(vid_panel)

        # Imagen
        self.fmt_combo = QComboBox()
        for name, *_ in FORMATS:
            self.fmt_combo.addItem(name)
        self.fmt_combo.currentIndexChanged.connect(self.on_format_changed)
        self.zoom = self._slider(100, 300, 100)
        self.pos_x = self._slider(-100, 100, 0)
        self.pos_y = self._slider(-100, 100, 0)
        self.mirror = QCheckBox("Espejo")
        rotate_btn = QPushButton("⟳ Girar")
        rotate_btn.setToolTip("Girar 90° (por si un vídeo sale tumbado)")
        rotate_btn.clicked.connect(self.rotate)
        center_btn = QPushButton("Centrar")
        center_btn.clicked.connect(self.reset_framing)
        tools = QHBoxLayout()
        tools.addWidget(self.mirror)
        tools.addStretch(1)
        tools.addWidget(rotate_btn)
        tools.addWidget(center_btn)

        img_form = QFormLayout()
        img_form.addRow("Formato", self.fmt_combo)
        img_form.addRow("Zoom", self.zoom)
        img_form.addRow("Izq. / Der.", self.pos_x)
        img_form.addRow("Arriba / Abajo", self.pos_y)

        self.go_btn = QPushButton("▶  Activar cámara virtual")
        self.go_btn.setObjectName("go")
        self.go_btn.clicked.connect(self.toggle_vcam)
        self.status = QLabel()
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        self.hint = QLabel()
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)

        side = QVBoxLayout()
        side.addWidget(title)
        side.addLayout(seg)
        side.addSpacing(4)
        side.addWidget(self.stack)
        side.addSpacing(6)
        side.addLayout(img_form)
        side.addLayout(tools)
        side.addStretch(1)
        side.addWidget(self.go_btn)
        side.addWidget(self.status)
        side.addWidget(self.hint)

        side_w = QWidget()
        side_w.setLayout(side)
        side_w.setFixedWidth(350)

        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(16)
        root.addWidget(self.preview, 1)
        root.addWidget(side_w)
        self.setStyleSheet(STYLE)
        self.resize(800, 700)
        self._set_status("Listo.")

    def _slider(self, lo, hi, val):
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(lo, hi)
        s.setValue(val)
        return s

    def _set_status(self, text):
        self.status.setText(text)

    def reset_framing(self):
        self.zoom.setValue(100)
        self.pos_x.setValue(0)
        self.pos_y.setValue(0)

    def rotate(self):
        self.rotation = (self.rotation + 90) % 360
        self._set_status(f"Giro: {self.rotation}°")

    def _update_hint(self):
        if self.source == SOURCE_VIDEO:
            mic = "«BlackHole 2ch»" if sys.platform == "darwin" else "«CABLE Output»"
            self.hint.setText(
                "En Snapchat (web.snapchat.com), en la videollamada elige la cámara "
                f"«OBS Virtual Camera» y el micrófono {mic}."
            )
        else:
            self.hint.setText(
                "En Snapchat (web.snapchat.com), en la videollamada elige la cámara "
                "«OBS Virtual Camera» y tu micrófono normal."
            )

    # ----- Fuente -----
    def set_source(self, source):
        self.source = source
        self.btn_cam.setChecked(source == SOURCE_CAMERA)
        self.btn_vid.setChecked(source == SOURCE_VIDEO)
        self.stack.setCurrentIndex(source)
        if source == SOURCE_CAMERA:
            self.player.pause()
            self.refresh_cameras()
        else:
            self._stop_camera()
            if self.video_path is None:
                self.preview.clear()
                self.preview.setText("Elige un vídeo o arrástralo aquí")
            self._set_status("Modo vídeo.")
        self._update_hint()

    # ----- Ajustes guardados -----
    def _load_settings(self):
        s = self.settings
        self.fmt_combo.setCurrentIndex(int(s.value("format", 0)))
        self.zoom.setValue(int(s.value("zoom", 100)))
        self.pos_x.setValue(int(s.value("pos_x", 0)))
        self.pos_y.setValue(int(s.value("pos_y", 0)))
        self.mirror.setChecked(str(s.value("mirror", "false")).lower() == "true")
        self.loop_chk.setChecked(str(s.value("loop", "true")).lower() == "true")
        self.on_loop_toggled(self.loop_chk.isChecked())
        self.volume.setValue(int(s.value("volume", 100)))
        self.audio_out.setVolume(self.volume.value() / 100.0)
        self.source = int(s.value("source", SOURCE_CAMERA))
        if self.source not in (SOURCE_CAMERA, SOURCE_VIDEO):
            self.source = SOURCE_CAMERA

    def _save_settings(self):
        s = self.settings
        s.setValue("format", self.fmt_combo.currentIndex())
        s.setValue("zoom", self.zoom.value())
        s.setValue("pos_x", self.pos_x.value())
        s.setValue("pos_y", self.pos_y.value())
        s.setValue("mirror", self.mirror.isChecked())
        s.setValue("loop", self.loop_chk.isChecked())
        s.setValue("volume", self.volume.value())
        s.setValue("source", self.source)
        idx = self.cam_combo.currentIndex()
        if 0 <= idx < len(self.devices):
            s.setValue("camera", self.devices[idx].description())
        aidx = self.audio_combo.currentIndex()
        if 0 <= aidx < len(self.audio_devices):
            s.setValue("audio_out", self.audio_devices[aidx].description())

    # ----- Cámaras -----
    def refresh_cameras(self):
        idx = self.cam_combo.currentIndex()
        if 0 <= idx < len(self.devices):
            current = self.devices[idx].description()
        else:
            current = self.settings.value("camera", None)

        self.devices = [d for d in QMediaDevices.videoInputs() if not is_blocked_camera(d.description())]
        self.cam_combo.blockSignals(True)
        self.cam_combo.clear()
        for d in self.devices:
            self.cam_combo.addItem(d.description())
        self.cam_combo.blockSignals(False)

        if self.source != SOURCE_CAMERA:
            return
        if not self.devices:
            self._stop_camera()
            self.preview.clear()
            self.preview.setText("No se ha encontrado ninguna cámara.\nConéctala y pulsa ↻")
            return

        target = 0
        for i, d in enumerate(self.devices):
            if d.description() == current:
                target = i
                break
        self.cam_combo.setCurrentIndex(target)
        self.on_camera_changed(target)

    def on_camera_changed(self, index):
        if self.source != SOURCE_CAMERA or not (0 <= index < len(self.devices)):
            return
        self._stop_camera()
        device = self.devices[index]
        cam = QCamera(device)
        fmt = pick_camera_format(device)
        if fmt is not None:
            cam.setCameraFormat(fmt)
        cam.errorOccurred.connect(lambda _e, msg: self._set_status(f"Error de cámara: {msg}"))
        self.session.setCamera(cam)
        self.camera = cam
        cam.start()
        self._set_status(f"Usando: {device.description()}")

    def _stop_camera(self):
        if self.camera is not None:
            self.camera.stop()
            self.session.setCamera(None)
            self.camera.deleteLater()
            self.camera = None

    # ----- Vídeo y audio -----
    def choose_video(self):
        start = os.path.dirname(self.video_path) if self.video_path else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Elegir vídeo", start,
            "Vídeos (" + " ".join(f"*{e}" for e in VIDEO_EXTENSIONS) + ");;Todos los archivos (*)",
        )
        if path:
            self.load_video(path)

    def load_video(self, path):
        self.video_path = path
        if self.source != SOURCE_VIDEO:
            self.set_source(SOURCE_VIDEO)
        self.file_label.setText(os.path.basename(path))
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()
        self._set_status(f"Reproduciendo: {os.path.basename(path)}")

    def toggle_play(self):
        if self.video_path is None:
            self.choose_video()
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def on_playback_state(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_btn.setText("⏸" if playing else "▶")

    def on_loop_toggled(self, on):
        self.player.setLoops(-1 if on else 1)

    def on_position(self, ms):
        if not self._seeking:
            self.pos_slider.setValue(int(ms))
        self.time_label.setText(f"{format_ms(ms)} / {format_ms(self.player.duration())}")

    def on_duration(self, ms):
        self.pos_slider.setRange(0, int(ms))

    def on_seek(self):
        self.player.setPosition(self.pos_slider.value())
        self._seeking = False

    def refresh_audio_outputs(self):
        aidx = self.audio_combo.currentIndex()
        if 0 <= aidx < len(self.audio_devices):
            current = self.audio_devices[aidx].description()
        else:
            current = self.settings.value("audio_out", None)

        self.audio_devices = list(QMediaDevices.audioOutputs())
        self.audio_combo.blockSignals(True)
        self.audio_combo.clear()
        for d in self.audio_devices:
            label = d.description()
            if is_virtual_audio(label):
                label = "🎤 " + label + "  (micrófono virtual)"
            self.audio_combo.addItem(label)
        self.audio_combo.blockSignals(False)

        target = -1
        for i, d in enumerate(self.audio_devices):
            if d.description() == current:
                target = i
                break
        if target < 0:
            for i, d in enumerate(self.audio_devices):
                if is_virtual_audio(d.description()):
                    target = i
                    break
        if target < 0 and self.audio_devices:
            default = QMediaDevices.defaultAudioOutput()
            target = next(
                (i for i, d in enumerate(self.audio_devices) if d.id() == default.id()), 0
            )
        if target >= 0:
            self.audio_combo.setCurrentIndex(target)
            self.on_audio_device_changed(target)
        self._update_audio_hint()

    def on_audio_device_changed(self, index):
        if 0 <= index < len(self.audio_devices):
            self.audio_out.setDevice(self.audio_devices[index])
        self._update_audio_hint()

    def _update_audio_hint(self):
        has_virtual = any(is_virtual_audio(d.description()) for d in self.audio_devices)
        idx = self.audio_combo.currentIndex()
        selected_virtual = 0 <= idx < len(self.audio_devices) and is_virtual_audio(
            self.audio_devices[idx].description()
        )
        if not has_virtual:
            tool = "BlackHole 2ch (existential.audio/blackhole)" if sys.platform == "darwin" \
                else "VB-CABLE (vb-audio.com/Cable)"
            self.audio_hint.setText(
                f"⚠️ Para que Snapchat oiga el vídeo instala gratis {tool} y "
                "reinicia GlowCam."
            )
        elif not selected_virtual:
            self.audio_hint.setText(
                "⚠️ El audio está saliendo por tus altavoces: Snapchat no lo oirá. "
                "Elige el micrófono virtual 🎤."
            )
        else:
            self.audio_hint.setText("✅ El audio del vídeo va al micrófono virtual.")

    # ----- Arrastrar y soltar -----
    def dragEnterEvent(self, event):  # noqa: N802
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile() and is_video_file(urls[0].toLocalFile()):
            event.acceptProposedAction()

    def dropEvent(self, event):  # noqa: N802
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile():
            self.load_video(urls[0].toLocalFile())

    # ----- Fotogramas -----
    def on_frame(self, frame, origin):
        if origin != self.source or not frame.isValid():
            return
        img = frame.toImage()
        if img.isNull():
            return
        out = compose_frame(
            img,
            self.fmt_combo.currentIndex(),
            self.zoom.value() / 100.0,
            self.pos_x.value() / 100.0,
            self.pos_y.value() / 100.0,
            self.mirror.isChecked(),
            self.rotation,
        )
        pix = QPixmap.fromImage(out).scaled(
            self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview.setPixmap(pix)

        if self.vcam is not None:
            try:
                self.vcam.send(qimage_to_rgb_array(out))
            except Exception as e:  # noqa: BLE001
                self._stop_vcam()
                self._set_status(f"La cámara virtual se ha detenido: {e}")

    # ----- Cámara virtual -----
    def on_format_changed(self, _index):
        if self.vcam is not None:
            self._stop_vcam()
            self._start_vcam()

    def toggle_vcam(self):
        if self.vcam is None:
            self._start_vcam()
        else:
            self._stop_vcam()

    def _start_vcam(self):
        if pyvirtualcam is None:
            self._show_obs_help("No se ha podido cargar el módulo de cámara virtual.")
            return
        _, w, h, _ = FORMATS[self.fmt_combo.currentIndex()]
        try:
            self.vcam = pyvirtualcam.Camera(
                width=w, height=h, fps=FPS,
                fmt=pyvirtualcam.PixelFormat.RGB, backend="obs",
            )
        except Exception as e:  # noqa: BLE001
            self.vcam = None
            self._show_obs_help(str(e))
            return
        self.go_btn.setText("■  Detener cámara virtual")
        self.go_btn.setProperty("active", "true")
        self._repolish(self.go_btn)
        self._set_status(f"🔴 Cámara virtual activa ({w}×{h}).")

    def _stop_vcam(self):
        if self.vcam is not None:
            try:
                self.vcam.close()
            except Exception:  # noqa: BLE001
                pass
            self.vcam = None
        self.go_btn.setText("▶  Activar cámara virtual")
        self.go_btn.setProperty("active", "false")
        self._repolish(self.go_btn)
        self._set_status("Cámara virtual detenida.")

    def _repolish(self, w):
        w.style().unpolish(w)
        w.style().polish(w)

    def _show_obs_help(self, detail):
        if sys.platform == "darwin":
            steps = (
                "1. Instala OBS gratis desde obsproject.com\n"
                "2. Abre OBS una vez, pulsa «Iniciar cámara virtual» y acepta el "
                "permiso que pide el Mac (Ajustes del Sistema → Privacidad y "
                "seguridad).\n"
                "3. Cierra OBS y vuelve a pulsar el botón en GlowCam."
            )
            intro = "GlowCam usa la cámara virtual de OBS y no la encuentra."
        else:
            steps = (
                "1. Cierra GlowCam.\n"
                "2. Vuelve a ejecutar el instalador GlowCam-Windows.exe y acepta "
                "el permiso de administrador.\n"
                "3. Abre GlowCam de nuevo."
            )
            intro = "La cámara virtual de GlowCam no está instalada correctamente."
        QMessageBox.warning(
            self, "Falta la cámara virtual",
            f"{intro}\n\n{steps}\n\nDetalle técnico: {detail}",
        )
        self._set_status("No se ha podido activar la cámara virtual.")

    def closeEvent(self, event):  # noqa: N802
        self._save_settings()
        self.player.stop()
        self._stop_vcam()
        self._stop_camera()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
