"""MilkDrop-látvány a projectM könyvtárral, a SYNCAMP pontos órájához etetve.

A projectM mindig a neki átadott legfrissebb hangmintákból rajzol. Ezért
minden képkocka előtt pontosan azokat a mintákat adjuk neki, amelyek az
előző képkocka óta a hangszóróból kijöttek (Player.heard) – így a látvány
nem a dekódoláshoz, hanem a hallható hanghoz igazodik.
"""

import ctypes
import os
import random

import numpy as np
from PySide6.QtCore import Signal
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget

HERE = os.path.dirname(os.path.abspath(__file__))
MD_DIR = os.path.join(HERE, "milkdrop")
PRESET_DIR = os.path.join(MD_DIR, "presets")
TEXTURE_DIR = os.path.join(MD_DIR, "textures")
LOGO_DIR = os.path.join(PRESET_DIR, "! SYNCAMP")    # a saját, feliratos látványok

_SWITCH_CB = ctypes.CFUNCTYPE(None, ctypes.c_bool, ctypes.c_void_p)


class _Lib:
    """A projectM-4.dll és a glew32.dll C-függvényei."""

    def __init__(self):
        os.add_dll_directory(MD_DIR)
        self.glew = ctypes.CDLL(os.path.join(MD_DIR, "glew32.dll"))
        pm = ctypes.CDLL(os.path.join(MD_DIR, "projectM-4.dll"))
        H = ctypes.c_void_p
        sig = {
            "projectm_create": (H, []),
            "projectm_destroy": (None, [H]),
            "projectm_load_preset_data": (None, [H, ctypes.c_char_p, ctypes.c_bool]),
            "projectm_reset_textures": (None, [H]),
            "projectm_pcm_add_float": (None, [H, ctypes.POINTER(ctypes.c_float), ctypes.c_uint, ctypes.c_int]),
            "projectm_pcm_get_max_samples": (ctypes.c_uint, []),
            "projectm_opengl_render_frame": (None, [H]),
            "projectm_set_window_size": (None, [H, ctypes.c_size_t, ctypes.c_size_t]),
            "projectm_set_texture_search_paths": (None, [H, ctypes.POINTER(ctypes.c_char_p), ctypes.c_size_t]),
            "projectm_set_preset_duration": (None, [H, ctypes.c_double]),
            "projectm_set_soft_cut_duration": (None, [H, ctypes.c_double]),
            "projectm_set_hard_cut_enabled": (None, [H, ctypes.c_bool]),
            "projectm_set_hard_cut_duration": (None, [H, ctypes.c_double]),
            "projectm_set_preset_locked": (None, [H, ctypes.c_bool]),
            "projectm_set_fps": (None, [H, ctypes.c_int32]),
            "projectm_set_mesh_size": (None, [H, ctypes.c_size_t, ctypes.c_size_t]),
            "projectm_set_preset_switch_requested_event_callback": (None, [H, _SWITCH_CB, ctypes.c_void_p]),
        }
        for name, (res, args) in sig.items():
            f = getattr(pm, name)
            f.restype = res
            f.argtypes = args
            setattr(self, name[len("projectm_"):], f)

    def glew_init(self):
        ctypes.c_ubyte.in_dll(self.glew, "glewExperimental").value = 1
        self.glew.glewInit.restype = ctypes.c_uint
        return self.glew.glewInit()


_lib = None


def lib():
    global _lib
    if _lib is None:
        _lib = _Lib()
    return _lib


def available():
    # a letöltött presetcsomag nélkül is megy, a SYNCAMP saját látványaival
    return os.path.exists(os.path.join(MD_DIR, "projectM-4.dll"))


class PresetList:
    def __init__(self):
        self.files = []
        for root, _dirs, files in os.walk(PRESET_DIR):
            for f in files:
                if f.lower().endswith(".milk"):
                    self.files.append(os.path.join(root, f))
        self.files.sort()
        self.logo_files = [f for f in self.files if f.startswith(LOGO_DIR + os.sep)]
        self.logo_only = False
        self.history = []
        self.pos = -1

    def name(self, path):
        rel = os.path.relpath(path, PRESET_DIR)
        return os.path.splitext(rel)[0].replace(os.sep, " / ")

    def random(self):
        pool = self.logo_files if self.logo_only and self.logo_files else self.files
        cur = self.history[self.pos] if self.pos >= 0 else None
        p = random.choice([f for f in pool if f != cur] or pool)
        del self.history[self.pos + 1:]
        self.history.append(p)
        self.pos = len(self.history) - 1
        return p

    def back(self):
        if self.pos > 0:
            self.pos -= 1
            return self.history[self.pos]
        return None


class MilkDropView(QOpenGLWidget):
    preset_changed = Signal(str)
    double_clicked = Signal()
    failed = Signal(str)

    def __init__(self, player, settings, parent=None):
        super().__init__(parent)
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.CoreProfile)
        fmt.setSwapInterval(1)
        self.setFormat(fmt)
        self.setUpdateBehavior(QOpenGLWidget.NoPartialUpdate)
        self.player = player
        self.s = settings
        self.presets = PresetList()
        self.pm = None
        self._fed_track = None
        self._fed = 0
        self._switch_wanted = False
        self._smooth = True
        self.locked = False
        self.offset_ms = 0
        self.preset_seconds = 20.0
        self.current_name = ""
        self.current_path = None
        self._cb = _SWITCH_CB(self._on_switch_requested)
        self.setMinimumSize(160, 100)

    # --- OpenGL életciklus -------------------------------------------------
    def initializeGL(self):
        L = lib()
        if L.glew_init() != 0:
            self.failed.emit("GLEW nem indult el")
            return
        self.pm = L.create()
        if not self.pm:
            self.failed.emit("projectM nem indult el (OpenGL 3.3 kell)")
            return
        paths = (ctypes.c_char_p * 1)(TEXTURE_DIR.encode("utf-8"))
        L.set_texture_search_paths(self.pm, paths, 1)
        L.set_mesh_size(self.pm, 64, 48)
        L.set_fps(self.pm, 60)
        L.set_soft_cut_duration(self.pm, 3.0)
        L.set_hard_cut_enabled(self.pm, True)
        L.set_hard_cut_duration(self.pm, 15.0)
        L.set_preset_switch_requested_event_callback(self.pm, self._cb, None)
        self.apply_options()
        self.context().aboutToBeDestroyed.connect(self._cleanup)
        self.next_preset(smooth=False)

    def _cleanup(self):
        if self.pm:
            self.makeCurrent()
            lib().destroy(self.pm)
            self.pm = None
            self.doneCurrent()

    def resizeGL(self, w, h):
        if self.pm:
            r = self.devicePixelRatioF()
            lib().set_window_size(self.pm, max(1, int(w * r)), max(1, int(h * r)))

    def paintGL(self):
        if not self.pm:
            return
        self._feed_audio()
        lib().opengl_render_frame(self.pm)
        if self._switch_wanted and not self.locked:
            self._switch_wanted = False
            self._load(self.presets.random(), self._smooth)

    # --- hang: pontosan ami MOST szól --------------------------------------
    def _feed_audio(self):
        # Saját csúszka: (+) a látvány később reagál, (−) korábban. A MilkDrop
        # belső simítása miatt itt gyakran a negatív érték a jó.
        lead = 0.016 - self.offset_ms / 1000.0
        track, frame, playing = self.player.heard(lead)
        if track is None or not playing:
            return
        now = int(frame)
        sr = self.player.sr
        # új szám vagy tekerés: ne öntsük rá a közte lévő régi hangot
        if track is not self._fed_track or now < self._fed or now - self._fed > sr // 2:
            self._fed_track = track
            self._fed = max(0, now - sr // 60)
        if now <= self._fed:
            return
        start = max(self._fed, now - 4096)
        chunk = np.ascontiguousarray(track.samples[start:now], dtype=np.float32)
        chunk *= 1.0 / 32768.0
        self._fed = now
        ptr = chunk.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        lib().pcm_add_float(self.pm, ptr, len(chunk), 2)

    # --- presetek ----------------------------------------------------------
    def _on_switch_requested(self, is_hard_cut, _user):
        # a renderelés közben jön – a betöltés a képkocka végén történik
        self._switch_wanted = True
        self._smooth = not is_hard_cut

    def _load(self, path, smooth):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            return
        # a fájlt mi olvassuk be: így az ékezetes nevű presetek is betöltődnek
        lib().load_preset_data(self.pm, data, smooth)
        self.current_path = path
        if path.startswith(PRESET_DIR + os.sep):
            self.current_name = self.presets.name(path)
        else:
            self.current_name = os.path.splitext(os.path.basename(path))[0]
        self.preset_changed.emit(self.current_name)

    def load_special(self, path):
        """Egy adott látvány (pl. a futó szöveg) elejéről indítva."""
        if self.pm:
            self.makeCurrent()
            self._load(path, False)
            self.doneCurrent()

    def reload_textures(self):
        """A szerkesztett feliratképek újratöltése, a mostani látvány újraindítása."""
        if not self.pm:
            return
        self.makeCurrent()
        lib().reset_textures(self.pm)
        if self.current_path:
            self._load(self.current_path, False)
        self.doneCurrent()

    def next_preset(self, smooth=True):
        if self.pm and self.presets.files:
            self.makeCurrent()
            self._load(self.presets.random(), smooth)
            self.doneCurrent()

    def prev_preset(self):
        p = self.presets.back()
        if self.pm and p:
            self.makeCurrent()
            self._load(p, True)
            self.doneCurrent()

    def apply_options(self):
        if self.pm:
            lib().set_preset_duration(self.pm, float(self.preset_seconds))
            lib().set_preset_locked(self.pm, self.locked)

    def mouseDoubleClickEvent(self, _):
        self.double_clicked.emit()
