"""Prueba en la máquina de compilación: ¿funciona la cámara virtual instalada?"""
import numpy as np
import pyvirtualcam

for w, h in ((720, 1280), (1280, 720)):
    with pyvirtualcam.Camera(width=w, height=h, fps=30, fmt=pyvirtualcam.PixelFormat.RGB, backend="obs") as cam:
        frame = np.zeros((h, w, 3), np.uint8)
        frame[:, :, 0] = 255
        for _ in range(10):
            cam.send(frame)
            cam.sleep_until_next_frame()
        print(f"OK cámara virtual {w}x{h}: {cam.device}")
