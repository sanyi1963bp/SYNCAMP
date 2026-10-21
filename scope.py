"""Oszcilloszkóp kijelző: vízszintes eltérítés = idő, függőleges = amplitúdó."""

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

TIMEBASES_MS = [2, 5, 10, 20, 50, 100, 200]   # a teljes képernyőszélesség
GAINS = [0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0]
MODES = ["MONO", "L+R", "XY"]

PHOSPHOR = QColor(60, 255, 110)


class ScopeSettings:
    """Közös beállítás a kis és a nagy kijelzőnek."""

    def __init__(self):
        self.timebase = 3          # index -> 20 ms
        self.gain = 2              # index -> 1.0
        self.mode = 0
        self.trigger = True
        self.persistence = True
        self.offset_ms = 0         # felhasználói finomhangolás


class Scope(QWidget):
    def __init__(self, player, settings, compact=False, parent=None):
        super().__init__(parent)
        self.player = player
        self.s = settings
        self.compact = compact
        self._buf = None
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.setMinimumSize(60, 24)

    # --- adat --------------------------------------------------------------
    def _window(self):
        """A most hallható pillanat köré eső mintaablak (float, -1..1)."""
        # ~1 képkocka előretekintés: mire a kép kikerül a monitorra, addigra
        # ez a minta szól.
        # A KÉP-KÉSÉS (+) későbbre tolja a képet, (−) korábbra.
        lead = 0.016 - self.s.offset_ms / 1000.0
        track, frame, _ = self.player.heard(lead)
        sr = self.player.sr
        n = max(16, int(TIMEBASES_MS[self.s.timebase] * sr / 1000))
        if track is None:
            return np.zeros((n, 2), np.float32)
        data = track.samples
        start = int(frame) - n // 2
        if self.s.trigger and self.s.mode != 2:
            start = self._trigger(data, start, n)
        a, b = max(0, start), min(len(data), start + n)
        seg = np.zeros((n, 2), np.float32)
        if b > a:
            seg[a - start:b - start] = data[a:b] / 32768.0
        return seg

    @staticmethod
    def _trigger(data, start, n):
        """Felfutó nullátmenet a középhez legközelebb – álló hullámkép."""
        lo, hi = max(1, start - n // 2), min(len(data), start + n // 2)
        if hi - lo < 4:
            return start
        m = data[lo:hi].astype(np.int32).sum(axis=1)
        hyst = 200
        cross = np.nonzero((m[:-1] < -hyst) & (m[1:] >= -hyst))[0]
        if len(cross) == 0:
            return start
        idx = cross[np.argmin(np.abs(cross + lo - start))]
        return int(idx + lo)

    # --- rajz --------------------------------------------------------------
    def _trace(self, p, xs, ys):
        poly = QPolygonF([QPointF(x, y) for x, y in zip(xs, ys)])
        if self.compact:
            p.setPen(QPen(PHOSPHOR, 1))
            p.drawPolyline(poly)
            return
        for width, alpha in ((7, 35), (3.5, 90), (1.4, 255)):
            c = QColor(PHOSPHOR) if width > 2 else QColor(200, 255, 210)
            c.setAlpha(alpha)
            p.setPen(QPen(c, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPolyline(poly)

    def _draw_signal(self, p, w, h):
        seg = self._window()
        g = GAINS[self.s.gain] * (0.45 if not self.compact else 0.48)
        mode = MODES[self.s.mode]
        if mode == "XY":
            size = min(w, h)
            cx, cy = w / 2, h / 2
            step = max(1, len(seg) // 1500)
            pts = seg[::step]
            xs = cx + pts[:, 0] * size * g
            ys = cy - pts[:, 1] * size * g
            self._trace(p, xs, ys)
            return
        npts = min(len(seg), int(w * 2))
        idx = np.linspace(0, len(seg) - 1, npts).astype(np.int64)
        xs = np.linspace(0, w - 1, npts)
        if mode == "MONO":
            y = seg[idx].mean(axis=1)
            self._trace(p, xs, h / 2 - y * h * g)
        else:
            for ch, mid in ((0, h * 0.27), (1, h * 0.73)):
                y = seg[idx, ch]
                self._trace(p, xs, mid - y * h * g * 0.5)

    def _draw_graticule(self, p, w, h):
        p.setPen(QPen(QColor(40, 90, 55, 150), 1))
        for i in range(1, 10):
            x = int(w * i / 10)
            p.drawLine(x, 0, x, h)
        for i in range(1, 8):
            y = int(h * i / 8)
            p.drawLine(0, y, w, y)
        p.setPen(QPen(QColor(60, 140, 80, 190), 1))
        p.drawLine(0, h // 2, w, h // 2)
        p.drawLine(w // 2, 0, w // 2, h)
        # osztásjelek a középvonalakon
        for i in range(50):
            x = int(w * i / 50)
            p.drawLine(x, h // 2 - 3, x, h // 2 + 3)
        for i in range(40):
            y = int(h * i / 40)
            p.drawLine(w // 2 - 3, y, w // 2 + 3, y)

    def _draw_labels(self, p, w, h):
        p.setFont(QFont("Consolas", 9))
        p.setPen(QColor(90, 200, 120))
        tb = TIMEBASES_MS[self.s.timebase] / 10
        tb_txt = f"{tb:g} ms/div"
        mode = MODES[self.s.mode]
        left = f"{mode}   {tb_txt}   x{GAINS[self.s.gain]:g}"
        if mode == "XY":
            left = f"XY   x{GAINS[self.s.gain]:g}"
        p.drawText(8, h - 8, left)
        right = []
        if self.s.trigger and mode != "XY":
            right.append("TRIG ↑")
        if self.s.offset_ms:
            right.append(f"késés {self.s.offset_ms:+d} ms")
        txt = "   ".join(right)
        p.drawText(w - 8 - p.fontMetrics().horizontalAdvance(txt), h - 8, txt)

    def paintEvent(self, _):
        w, h = self.width(), self.height()
        p = QPainter(self)
        if self.compact:
            p.fillRect(0, 0, w, h, Qt.black)
            p.setRenderHint(QPainter.Antialiasing, True)
            self._draw_signal(p, w, h)
            return
        if self._buf is None or self._buf.size() != self.size():
            self._buf = QImage(self.size(), QImage.Format_RGB32)
            self._buf.fill(Qt.black)
        bp = QPainter(self._buf)
        # foszfor utánvilágítás: az előző kép csak elhalványul
        bp.fillRect(0, 0, w, h, QColor(0, 0, 0, 110 if self.s.persistence else 255))
        bp.setRenderHint(QPainter.Antialiasing, True)
        self._draw_signal(bp, w, h)
        bp.end()
        p.fillRect(0, 0, w, h, QColor(4, 14, 8))
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        p.drawImage(0, 0, self._buf)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        self._draw_graticule(p, w, h)
        self._draw_labels(p, w, h)

    def wheelEvent(self, e):
        up = e.angleDelta().y() > 0
        if e.modifiers() & Qt.ShiftModifier:
            self.s.gain = max(0, min(len(GAINS) - 1, self.s.gain + (1 if up else -1)))
        else:
            self.s.timebase = max(0, min(len(TIMEBASES_MS) - 1, self.s.timebase + (-1 if up else 1)))
