import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform.startswith("linux"):
    os.environ.setdefault("QT_AUDIO_BACKEND", "alsa")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import glowcam  # noqa: E402

app = QApplication.instance() or QApplication([])


def make_img(w, h):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(10, 200, 30))
    # mitad izquierda roja para comprobar espejo/posición
    for x in range(w // 2):
        for y in range(0, h, max(1, h // 8)):
            img.setPixelColor(x, y, QColor(255, 0, 0))
    return img


@pytest.mark.parametrize("w,h", [(1920, 1080), (1280, 720), (640, 480), (1080, 1920)])
def test_crop_aspect_and_bounds(w, h):
    for zoom in (1.0, 1.7, 3.0):
        for ox in (-1, 0, 1):
            for oy in (-1, 0, 1):
                x, y, cw, ch = glowcam.compute_crop(w, h, 9 / 16, zoom, ox, oy)
                assert 0 <= x and x + cw <= w
                assert 0 <= y and y + ch <= h
                assert abs(cw / ch - 9 / 16) < 0.01


def test_crop_center_and_edges():
    x, y, cw, ch = glowcam.compute_crop(1920, 1080, 9 / 16)
    assert (cw, ch) == (608, 1080)
    assert x == (1920 - 608) // 2
    assert glowcam.compute_crop(1920, 1080, 9 / 16, 1, -1, 0)[0] == 0
    assert glowcam.compute_crop(1920, 1080, 9 / 16, 1, 1, 0)[0] == 1920 - 608


@pytest.mark.parametrize("fmt", range(len(glowcam.FORMATS)))
@pytest.mark.parametrize("mirror", [False, True])
def test_compose_sizes_and_array(fmt, mirror):
    _, ow, oh, _ = glowcam.FORMATS[fmt]
    out = glowcam.compose_frame(make_img(1280, 720), fmt, 1.5, 0.3, -0.2, mirror)
    assert (out.width(), out.height()) == (ow, oh)
    arr = glowcam.qimage_to_rgb_array(out)
    assert arr.shape == (oh, ow, 3)
    assert arr.dtype.name == "uint8" and arr.flags["C_CONTIGUOUS"]


def test_array_colors_rgb_order():
    img = QImage(7, 5, QImage.Format.Format_RGB32)  # ancho impar -> padding de línea
    img.fill(QColor(255, 10, 20))
    arr = glowcam.qimage_to_rgb_array(img)
    assert arr.shape == (5, 7, 3)
    assert tuple(arr[2, 3]) == (255, 10, 20)


def test_blocked_cameras():
    assert glowcam.is_blocked_camera("OBS Virtual Camera")
    assert glowcam.is_blocked_camera("GlowCam")
    assert not glowcam.is_blocked_camera("FaceTime HD Camera")
    assert not glowcam.is_blocked_camera("DJI Osmo Pocket")


@pytest.mark.parametrize("rot", [90, 180, 270])
def test_rotation_keeps_output_size(rot):
    out = glowcam.compose_frame(make_img(1280, 720), 0, rotation=rot)
    assert (out.width(), out.height()) == (720, 1280)


def test_audio_and_video_helpers():
    assert glowcam.is_virtual_audio("CABLE Input (VB-Audio Virtual Cable)")
    assert glowcam.is_virtual_audio("BlackHole 2ch")
    assert not glowcam.is_virtual_audio("MacBook Pro Speakers")
    assert glowcam.is_video_file("clip.MOV") and glowcam.is_video_file("a.mp4")
    assert not glowcam.is_video_file("foto.jpg")
    assert glowcam.format_ms(65000) == "1:05"


def test_window_builds():
    w = glowcam.MainWindow()
    w.show()
    app.processEvents()
    assert w.fmt_combo.count() == len(glowcam.FORMATS)
    w.set_source(glowcam.SOURCE_VIDEO)
    assert w.stack.currentIndex() == 1
    w.set_source(glowcam.SOURCE_CAMERA)
    w.rotate()
    w.reset_framing()
    w.close()
