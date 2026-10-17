# PyInstaller: genera la carpeta GlowCam (Windows, luego va al instalador) o GlowCam.app (Mac)
import sys

a = Analysis(
    ["glowcam.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=["pyvirtualcam"],
    excludes=["PySide6.QtWebEngineCore", "PySide6.QtQml", "PySide6.QtQuick", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True, name="GlowCam", console=False, upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="GlowCam", upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="GlowCam.app",
        bundle_identifier="com.glowmodelsmedia.glowcam",
        info_plist={
            "CFBundleShortVersionString": "1.2.0",
            "NSCameraUsageDescription": "GlowCam necesita la cámara para enviarla a Snapchat.",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
        },
    )
