"""SYNCAMP – Winamp-stílusú lejátszó, hanggal pontosan szinkron oszcilloszkóppal."""

import json
import math
import os
import random
import sys
import threading

from PySide6.QtCore import QObject, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QIcon, QKeySequence, QPainter, QPen,
                           QPixmap, QPolygonF, QShortcut)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog,
                               QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QSizeGrip, QSizePolicy,
                               QSlider, QStyle, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

import engine
import milkdrop
import vizgen
from scope import GAINS, MODES, TIMEBASES_MS, Scope, ScopeSettings
from windows import SkinWindow, WindowGroup, on_some_screen

APP = "Syncamp"
SETTINGS_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP)
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")

LED = QColor(0, 230, 40)
LED_OFF = QColor(0, 40, 10)

QSS = """
QWidget#body { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #41415c, stop:1 #26263a);
               border: 1px solid #7a7a9c; }
QWidget#panel { background: transparent; }
QPushButton { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #d4d4e2, stop:1 #8a8aa2);
              color: #16162a; border: 1px solid #1c1c28; border-top-color: #f4f4ff;
              border-left-color: #f4f4ff; font: bold 11px "Segoe UI"; padding: 2px 6px; }
QPushButton:pressed { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #7a7a92, stop:1 #b8b8cc);
                      border-top-color: #1c1c28; border-left-color: #1c1c28;
                      border-bottom-color: #f4f4ff; border-right-color: #f4f4ff; }
QPushButton:checked { color: #00b020; }
QPushButton#transport { font: 15px "Segoe UI Symbol"; min-width: 34px; min-height: 26px; padding: 0; }
QPushButton#small { font: bold 9px "Segoe UI"; padding: 1px 5px; min-height: 16px; }
QPushButton#tb { background: #2a2a3e; color: #c8c8e0; border: 1px solid #55557a;
                 font: bold 10px "Segoe UI"; padding: 0; min-width: 16px; min-height: 14px; }
QSlider::groove:horizontal { height: 6px; background: #0e0e18; border: 1px solid #55557a; }
QSlider::sub-page:horizontal { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #105020, stop:1 #30d050); }
QSlider::handle:horizontal { width: 12px; margin: -5px 0; background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                 stop:0 #f0e090, stop:1 #a08020); border: 1px solid #302808; }
QSlider#seek::sub-page:horizontal { background: #24243a; }
QSlider#seek::handle:horizontal { width: 28px; }
QLabel#info { background: #000; color: #00e028; font: bold 11px "Consolas"; border: 1px solid #55557a;
              padding: 1px 4px; }
QLabel#cap { color: #c8c8e0; font: bold 9px "Segoe UI"; }
QLabel#ind { color: #00e028; font: bold 10px "Segoe UI"; }
QLabel#indoff { color: #1d4a26; font: bold 10px "Segoe UI"; }
QTreeWidget { background: #000; color: #00e028; border: 1px solid #55557a;
              font: 12px "Segoe UI"; outline: 0; }
QTreeWidget::item { height: 18px; }
QTreeWidget::item:selected { background: #0000c6; color: #ffffff; }
QScrollBar:vertical { background: #1a1a28; width: 12px; }
QScrollBar::handle:vertical { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #9a9ab4, stop:1 #5a5a74);
                              min-height: 20px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
"""


def fmt_time(sec):
    sec = max(0, int(sec))
    return f"{sec // 60}:{sec % 60:02d}"


# --------------------------------------------------------------------------
# 7-szegmenses LED számjegyek
# --------------------------------------------------------------------------
SEGMENTS = {"0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc",
            "5": "afgcd", "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcdfg",
            "-": "g", " ": ""}


def _hseg(x, y, w, t):
    return QPolygonF([QPointF(x + t * .5 + 1, y), QPointF(x + t + 1, y - t / 2),
                      QPointF(x + w - t - 1, y - t / 2), QPointF(x + w - t * .5 - 1, y),
                      QPointF(x + w - t - 1, y + t / 2), QPointF(x + t + 1, y + t / 2)])


def _vseg(x, y0, y1, t):
    return QPolygonF([QPointF(x, y0 + t * .5 + 1), QPointF(x + t / 2, y0 + t + 1),
                      QPointF(x + t / 2, y1 - t - 1), QPointF(x, y1 - t * .5 - 1),
                      QPointF(x - t / 2, y1 - t - 1), QPointF(x - t / 2, y0 + t + 1)])


def draw_digit(p, ch, x, y, w, h):
    t = max(2.0, w * 0.2)
    polys = {
        "a": _hseg(x, y + t / 2, w, t), "g": _hseg(x, y + h / 2, w, t),
        "d": _hseg(x, y + h - t / 2, w, t),
        "f": _vseg(x + t / 2, y, y + h / 2, t), "b": _vseg(x + w - t / 2, y, y + h / 2, t),
        "e": _vseg(x + t / 2, y + h / 2, y + h, t), "c": _vseg(x + w - t / 2, y + h / 2, y + h, t),
    }
    on = SEGMENTS.get(ch, "")
    p.setPen(Qt.NoPen)
    for name, poly in polys.items():
        p.setBrush(LED if name in on else LED_OFF)
        p.drawPolygon(poly)


# --------------------------------------------------------------------------
# Kijelző (idő + állapot + mini szkóp)
# --------------------------------------------------------------------------
class Display(QWidget):
    clicked_time = Signal()

    def __init__(self, player, settings):
        super().__init__()
        self.setFixedSize(210, 104)
        self.state = "stop"
        self.seconds = 0.0
        self.duration = 0.0
        self.remaining = False
        self.blink = True
        self.mini = Scope(player, settings, compact=True, parent=self)
        self.mini.setGeometry(10, 64, 190, 32)
        self.mini.mousePressEvent = self._cycle_mode
        self._settings = settings

    def _cycle_mode(self, _):
        self._settings.mode = (self._settings.mode + 1) % len(MODES)

    def mousePressEvent(self, e):
        if e.position().y() < 60:
            self.remaining = not self.remaining

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), Qt.black)
        p.setPen(QColor(85, 85, 122))
        p.drawRect(0, 0, self.width() - 1, self.height() - 1)
        # állapotjel
        p.setPen(Qt.NoPen)
        p.setBrush(LED)
        if self.state == "play":
            p.drawPolygon(QPolygonF([QPointF(12, 14), QPointF(24, 21), QPointF(12, 28)]))
        elif self.state == "pause":
            p.drawRect(12, 14, 4, 14)
            p.drawRect(19, 14, 4, 14)
        else:
            p.drawRect(12, 15, 12, 12)
        # idő
        if self.remaining and self.duration:
            sec = self.duration - self.seconds
            sign = "-"
        else:
            sec, sign = self.seconds, " "
        sec = max(0, int(sec))
        mins, secs = min(99, sec // 60), sec % 60
        text = f"{sign}{mins:2d}{secs:02d}"
        visible = not (self.state == "pause" and not self.blink)
        x0, w, h, y = 40, 22, 40, 10
        xs = [x0, x0 + 30, x0 + 58, x0 + 102, x0 + 130]
        if visible:
            for ch, x in zip(text, xs):
                draw_digit(p, ch, x, y, w, h)
            p.setBrush(LED)
            p.setPen(Qt.NoPen)
            p.drawRect(QRectF(x0 + 89, y + 11, 5, 5))
            p.drawRect(QRectF(x0 + 89, y + 25, 5, 5))
        p.setPen(QColor(40, 90, 55))
        p.drawLine(8, 60, self.width() - 8, 60)


class Marquee(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(24)
        self.text = f"{APP} – húzd ide a zenéidet, vagy nyomd meg a ⏏ gombot"
        self.offset = 0
        t = QTimer(self)
        t.timeout.connect(self._step)
        t.start(30)

    def set_text(self, text):
        if text != self.text:
            self.text = text
            self.offset = 0
            self.update()

    def _step(self):
        self.offset += 1
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.black)
        p.setPen(QColor(85, 85, 122))
        p.drawRect(0, 0, self.width() - 1, self.height() - 1)
        p.setFont(QFont("Consolas", 11, QFont.Bold))
        p.setPen(LED)
        fm = p.fontMetrics()
        y = (self.height() + fm.ascent() - fm.descent()) // 2
        tw = fm.horizontalAdvance(self.text)
        p.setClipRect(self.rect().adjusted(3, 1, -3, -1))
        if tw < self.width() - 10:
            p.drawText(6, y, self.text)
            return
        unit = self.text + "   ***   "
        uw = fm.horizontalAdvance(unit)
        x = 6 - (self.offset % uw)
        while x < self.width():
            p.drawText(x, y, unit)
            x += uw


class JumpSlider(QSlider):
    """Kattintásra oda ugrik, ahova kattintottál (mint a Winampban)."""

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            v = QStyle.sliderValueFromPosition(self.minimum(), self.maximum(),
                                               int(e.position().x()), self.width())
            self.setValue(v)
            self.sliderMoved.emit(v)
        super().mousePressEvent(e)


def small_btn(text, checkable=False):
    b = QPushButton(text)
    b.setObjectName("small")
    b.setCheckable(checkable)
    b.setFocusPolicy(Qt.NoFocus)
    return b


# --------------------------------------------------------------------------
# Nagy oszcilloszkóp panel + teljes képernyő
# --------------------------------------------------------------------------
class ScopePanel(QWidget):
    fullscreen_requested = Signal()

    def __init__(self, player, settings):
        super().__init__()
        self.s = settings
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        self.scope = Scope(player, settings)
        self.scope.setMinimumHeight(160)
        self.scope.mouseDoubleClickEvent = lambda _e: self.fullscreen_requested.emit()
        self.scope.setToolTip("Dupla kattintás: teljes képernyő (Esc: vissza)")
        lay.addWidget(self.scope, 1)

        # teljes képernyőn ez a vezérlősor elrejtőzik
        self.controls = QWidget()
        row = QHBoxLayout(self.controls)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(3)
        self.b_mode = small_btn("")
        self.b_mode.clicked.connect(self._mode)
        self.b_trig = small_btn("TRIGGER", True)
        self.b_trig.toggled.connect(lambda v: setattr(self.s, "trigger", v))
        self.b_pers = small_btn("FOSZFOR", True)
        self.b_pers.setToolTip("Foszfor utánvilágítás (elhalványuló nyom), mint egy igazi szkópon")
        self.b_pers.toggled.connect(lambda v: setattr(self.s, "persistence", v))
        row.addWidget(self.b_mode)
        row.addWidget(self.b_trig)
        row.addWidget(self.b_pers)
        row.addSpacing(8)
        for label, attr, d, n in (("IDŐ", "timebase", 1, len(TIMEBASES_MS)),
                                  ("ERŐSÍTÉS", "gain", 1, len(GAINS))):
            cap = QLabel(label)
            cap.setObjectName("cap")
            row.addWidget(cap)
            for sym, step in (("−", -d), ("+", d)):
                b = small_btn(sym)
                if attr == "timebase":
                    step = -step   # "+" = nagyítás = rövidebb ablak
                b.clicked.connect(lambda _=False, a=attr, s=step, m=n:
                                  setattr(self.s, a, max(0, min(m - 1, getattr(self.s, a) + s))))
                row.addWidget(b)
            row.addSpacing(6)
        cap = QLabel("KÉP-KÉSÉS")
        cap.setObjectName("cap")
        cap.setToolTip("Ha a kép a hanghoz képest siet, told jobbra; ha késik, balra.\n"
                       "Bluetooth fejhallgatónál ez akár +150…+250 ms is lehet.")
        row.addWidget(cap)
        self.offset = QSlider(Qt.Horizontal)
        self.offset.setRange(-300, 300)
        self.offset.setFixedWidth(110)
        self.offset.setFocusPolicy(Qt.NoFocus)
        self.offset.setToolTip(cap.toolTip())
        self.offset.valueChanged.connect(self._offset)
        self.offset.mouseDoubleClickEvent = lambda _e: self.offset.setValue(0)
        row.addWidget(self.offset)
        self.off_lbl = QLabel()
        self.off_lbl.setObjectName("info")
        self.off_lbl.setFixedWidth(64)
        row.addWidget(self.off_lbl)
        row.addStretch(1)
        b_full = small_btn("⛶ TELJES")
        b_full.setToolTip("Teljes képernyős szkóp (F vagy dupla katt a képre, kilépés: Esc)")
        b_full.clicked.connect(self.fullscreen_requested.emit)
        row.addWidget(b_full)
        lay.addWidget(self.controls)
        self.sync_from_settings()

    def sync_from_settings(self):
        self.b_mode.setText(f"MÓD: {MODES[self.s.mode]}")
        self.b_trig.setChecked(self.s.trigger)
        self.b_pers.setChecked(self.s.persistence)
        self.offset.setValue(self.s.offset_ms)
        self.off_lbl.setText(f"{self.s.offset_ms:+d} ms")

    def sync_from_settings_light(self):
        """A görgővel / mini kijelzővel állított értékek a gombokon is látszódjanak."""
        txt = f"MÓD: {MODES[self.s.mode]}"
        if self.b_mode.text() != txt:
            self.b_mode.setText(txt)

    def _mode(self):
        self.s.mode = (self.s.mode + 1) % len(MODES)

    def _offset(self, v):
        if abs(v) < 6:
            v = 0
        self.s.offset_ms = v
        self.off_lbl.setText(f"{v:+d} ms")


MD_SECONDS = [10, 20, 30, 60, 120]


class TextDialog(QDialog):
    """A felirat és a csillagháborús futó szöveg szerkesztése."""

    def __init__(self, texts, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SYNCAMP – feliratok")
        self.setStyleSheet(
            "QDialog { background: #26263a; } QLabel { color: #c8c8e0; font: bold 10px 'Segoe UI'; }"
            "QPlainTextEdit, QLineEdit, QComboBox { background: #000; color: #00e028; "
            "border: 1px solid #55557a; font: 12px 'Segoe UI'; padding: 3px; }")
        lay = QVBoxLayout(self)

        def label(text):
            lb = QLabel(text)
            lay.addWidget(lb)

        label("FELIRAT  a logó-látványokhoz (lehet hosszú is; Enterrel saját sortörés)")
        self.logo = QPlainTextEdit(texts.get("logo", ""))
        self.logo.setFixedHeight(64)
        lay.addWidget(self.logo)
        label("CSILLAGOK – BEVEZETŐ SOR  (kék, mint a film elején)")
        self.intro = QPlainTextEdit(texts.get("intro", ""))
        self.intro.setFixedHeight(56)
        lay.addWidget(self.intro)
        label("CSILLAGOK – ALCÍM  (pl. I. RÉSZ)")
        self.subtitle = QLineEdit(texts.get("subtitle", ""))
        lay.addWidget(self.subtitle)
        label("CSILLAGOK – CÍM")
        self.title = QLineEdit(texts.get("title", ""))
        lay.addWidget(self.title)
        label("CSILLAGOK – FUTÓ SZÖVEG  (üres sor = új bekezdés)")
        self.crawl = QPlainTextEdit(texts.get("crawl", ""))
        self.crawl.setMinimumHeight(180)
        lay.addWidget(self.crawl, 1)
        row = QHBoxLayout()
        cap = QLabel("SEBESSÉG")
        row.addWidget(cap)
        self.speed = QComboBox()
        self.speed.addItems(list(vizgen.SPEEDS))
        self.speed.setCurrentText(texts.get("speed", "közepes"))
        row.addWidget(self.speed)
        row.addStretch(1)
        b_reset = small_btn("ALAPSZÖVEG")
        b_reset.setToolTip("Az eredeti SYNCAMP-szövegek visszaállítása")
        b_reset.clicked.connect(lambda: self._fill(vizgen.DEFAULT_TEXTS))
        row.addWidget(b_reset)
        b_ok = small_btn("MENTÉS")
        b_ok.clicked.connect(self.accept)
        b_cancel = small_btn("MÉGSE")
        b_cancel.clicked.connect(self.reject)
        row.addWidget(b_ok)
        row.addWidget(b_cancel)
        lay.addLayout(row)
        self.resize(560, 620)

    def _fill(self, t):
        self.logo.setPlainText(t["logo"])
        self.intro.setPlainText(t["intro"])
        self.subtitle.setText(t["subtitle"])
        self.title.setText(t["title"])
        self.crawl.setPlainText(t["crawl"])
        self.speed.setCurrentText(t["speed"])

    def values(self):
        return {
            "logo": self.logo.toPlainText(), "intro": self.intro.toPlainText(),
            "subtitle": self.subtitle.text(), "title": self.title.text(),
            "crawl": self.crawl.toPlainText(), "speed": self.speed.currentText(),
        }


class MilkDropPanel(QWidget):
    fullscreen_requested = Signal()

    def __init__(self, player, settings):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(4)
        # első indításkor a saját látványok még nincsenek meg – a listázás előtt kellenek
        vizgen.ensure_generated(vizgen.DEFAULT_TEXTS)
        self.view = milkdrop.MilkDropView(player, settings)
        self.view.setToolTip("Dupla kattintás: teljes képernyő (Esc: vissza)")
        self.view.double_clicked.connect(self.fullscreen_requested.emit)
        lay.addWidget(self.view, 1)

        # két sor: fent a látványok léptetése, lent a feliratok és a szinkron
        self.controls = QWidget()
        rows = QVBoxLayout(self.controls)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(3)
        row = QHBoxLayout()
        row.setSpacing(3)
        row2 = QHBoxLayout()
        row2.setSpacing(3)
        rows.addLayout(row)
        rows.addLayout(row2)
        self.texts = dict(vizgen.DEFAULT_TEXTS)
        b_prev = small_btn("◀ ELŐZŐ")
        b_prev.setToolTip("Az előző látvány")
        b_prev.clicked.connect(self.view.prev_preset)
        b_next = small_btn("KÖVETKEZŐ ▶")
        b_next.setToolTip("Új, véletlen látvány (N)")
        b_next.clicked.connect(lambda: self.view.next_preset())
        self.b_lock = small_btn("ZÁR", True)
        self.b_lock.setToolTip("Maradjon ez a látvány, ne váltson magától")
        self.b_lock.toggled.connect(self._lock)
        self.b_secs = small_btn("")
        self.b_secs.setToolTip("Ennyi idő után vált magától új látványra\n"
                               "(nagy dobütésnél előbb is válthat)")
        self.b_secs.clicked.connect(self._cycle_secs)
        self.b_logo = small_btn("LOGÓ", True)
        self.b_logo.setToolTip("Csak a SYNCAMP-feliratos látványok váltakozzanak")
        self.b_logo.toggled.connect(self._logo_only)
        for b in (b_prev, b_next, self.b_lock, self.b_secs):
            row.addWidget(b)
        self.name = QLabel("")
        self.name.setObjectName("info")
        self.name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        row.addWidget(self.name, 1)
        b_full = small_btn("⛶ TELJES")
        b_full.setToolTip("Teljes képernyő (dupla katt a képre, kilépés: Esc)")
        b_full.clicked.connect(self.fullscreen_requested.emit)
        row.addWidget(b_full)

        b_text = small_btn("✎ SZÖVEG…")
        b_text.setToolTip("A felirat és a futó szöveg szerkesztése")
        b_text.clicked.connect(self.edit_texts)
        b_crawl = small_btn("★ CSILLAGOK")
        b_crawl.setToolTip("Csillagok háborúja-stílusú futó szöveg az elejéről\n"
                           "(bekapcsolja a ZÁR-at, hogy ne váltson el közben)")
        b_crawl.clicked.connect(self.start_crawl)
        for b in (self.b_logo, b_text, b_crawl):
            row2.addWidget(b)
        row2.addStretch(1)
        cap = QLabel("KÉSÉS")
        cap.setObjectName("cap")
        cap.setToolTip("A MilkDrop saját szinkronja.\n"
                       "Ha a látvány a dobütés után reagál, told balra (−);\n"
                       "ha előtte, jobbra (+). Dupla katt: nulla.")
        row2.addWidget(cap)
        self.offset = QSlider(Qt.Horizontal)
        self.offset.setRange(-400, 400)
        self.offset.setFixedWidth(110)
        self.offset.setFocusPolicy(Qt.NoFocus)
        self.offset.setToolTip(cap.toolTip())
        self.offset.valueChanged.connect(self._offset)
        self.offset.mouseDoubleClickEvent = lambda _e: self.offset.setValue(0)
        row2.addWidget(self.offset)
        self.off_lbl = QLabel("+0 ms")
        self.off_lbl.setObjectName("info")
        self.off_lbl.setFixedWidth(60)
        row2.addWidget(self.off_lbl)
        lay.addWidget(self.controls)
        self.view.preset_changed.connect(self._show_name)
        self.view.failed.connect(lambda m: self.name.setText(f"Hiba: {m}"))
        self.set_options(20, False)

    def set_options(self, seconds, locked, offset_ms=None, logo_only=None):
        self.view.preset_seconds = seconds
        self.view.locked = locked
        self.b_secs.setText(f"VÁLTÁS: {seconds} mp")
        self.b_lock.setChecked(locked)
        if offset_ms is not None:
            self.offset.setValue(offset_ms)
        if logo_only is not None:
            self.b_logo.setChecked(logo_only)
        self.view.apply_options()

    def _offset(self, v):
        if abs(v) < 8:
            v = 0
        self.view.offset_ms = v
        self.off_lbl.setText(f"{v:+d} ms")

    def _logo_only(self, on):
        self.view.presets.logo_only = on
        if on:
            self.view.next_preset()

    def set_texts(self, texts):
        self.texts = dict(vizgen.DEFAULT_TEXTS)
        self.texts.update(texts or {})
        vizgen.ensure_generated(self.texts)

    def edit_texts(self):
        dlg = TextDialog(self.texts, self.window())
        if dlg.exec():
            self.texts = dlg.values()
            vizgen.generate_all(self.texts)
            self.view.reload_textures()

    def start_crawl(self):
        self.b_lock.setChecked(True)
        self.view.load_special(vizgen.CRAWL_PRESET)

    def _show_name(self, name):
        self.name.setText(name)
        self.name.setToolTip(name)

    def _lock(self, on):
        self.view.locked = on
        self.view.apply_options()

    def _cycle_secs(self):
        cur = self.view.preset_seconds
        i = MD_SECONDS.index(cur) if cur in MD_SECONDS else 0
        self.set_options(MD_SECONDS[(i + 1) % len(MD_SECONDS)], self.view.locked)


class VisWindow(SkinWindow):
    """Külön, méretezhető látvány-ablak. Dupla katt a képen: teljes képernyő."""

    def __init__(self, title, panel, group, parent):
        super().__init__(title, group, parent)
        self.panel = panel
        self.content.addWidget(panel)
        panel.fullscreen_requested.connect(self.toggle_fullscreen)
        self._full_from = None
        self.setMinimumSize(360, 200)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            if self._full_from is not None:
                self.setGeometry(self._full_from)
            self._full_from = None
            self.title.show()
            self.panel.controls.show()
            self.body_layout.setContentsMargins(4, 4, 4, 4)
            self.panel.layout().setContentsMargins(6, 4, 6, 4)
            return
        if self._maxed_from is not None:
            self.toggle_maximize()
        self._full_from = QRect(self.geometry())
        self.title.hide()
        self.panel.controls.hide()
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.panel.layout().setContentsMargins(0, 0, 0, 0)
        self.showFullScreen()
        self.activateWindow()


# --------------------------------------------------------------------------
# Lejátszási lista
# --------------------------------------------------------------------------
class Bridge(QObject):
    loaded = Signal(int, object, str)
    info = Signal(str, float)


class Playlist(QTreeWidget):
    files_dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setColumnCount(2)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(False)
        self.setIndentation(0)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setAcceptDrops(True)
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.setMinimumHeight(90)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            self.files_dropped.emit([u.toLocalFile() for u in e.mimeData().urls()])
            e.acceptProposedAction()
        else:
            super().dropEvent(e)


def expand_paths(paths):
    out = []
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, files in os.walk(p):
                for f in sorted(files):
                    if os.path.splitext(f)[1].lower() in engine.AUDIO_EXTS:
                        out.append(os.path.join(root, f))
        elif os.path.splitext(p)[1].lower() in engine.AUDIO_EXTS:
            out.append(p)
    return out


# --------------------------------------------------------------------------
# Főablak
# --------------------------------------------------------------------------
class MainWindow(SkinWindow):
    def __init__(self):
        self.wgroup = WindowGroup()
        # a főablak csak szélességben méretezhető, mint a Winampé
        super().__init__(APP.upper(), self.wgroup, edges=(Qt.LeftEdge, Qt.RightEdge), minimize=True)
        self.wgroup.add(self, leader=True)
        self.allow_close = True
        self.on_drop = self.add_paths
        self.setWindowTitle(APP)
        self.setWindowIcon(make_icon())
        QApplication.instance().setStyleSheet(QSS)
        self._layout_done = False
        self._saved = {}
        self.player = engine.Player()
        self.ss = ScopeSettings()
        self.bridge = Bridge()
        self.bridge.loaded.connect(self._on_loaded)
        self.bridge.info.connect(self._on_info)
        self.paths = []           # lejátszási lista útvonalai, sorrendben
        self.current = -1         # épp betöltött szám indexe
        self.state = "stop"
        self._load_token = 0
        self._failures = 0
        self._loading_title = None
        self._seeking = False
        self._durations = {}
        self._build()
        self._shortcuts()
        self._restore()

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        self.timer.start(15)
        self.blink_timer = QTimer(self)
        self.blink_timer.timeout.connect(self._blink)
        self.blink_timer.start(500)

    # --- felépítés ---------------------------------------------------------
    def _build(self):
        self.panel = QWidget()
        self.panel.setObjectName("panel")
        pv = QVBoxLayout(self.panel)
        pv.setContentsMargins(8, 6, 8, 6)
        pv.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.display = Display(self.player, self.ss)
        top.addWidget(self.display)
        right = QVBoxLayout()
        right.setSpacing(5)
        self.marquee = Marquee()
        right.addWidget(self.marquee)
        info = QHBoxLayout()
        info.setSpacing(4)
        self.kbps = QLabel("   ")
        self.kbps.setObjectName("info")
        self.kbps.setFixedWidth(48)
        self.kbps.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.khz = QLabel("  ")
        self.khz.setObjectName("info")
        self.khz.setFixedWidth(30)
        self.khz.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        for w, cap in ((self.kbps, "kbps"), (self.khz, "kHz")):
            info.addWidget(w)
            c = QLabel(cap)
            c.setObjectName("cap")
            info.addWidget(c)
            info.addSpacing(4)
        info.addStretch(1)
        self.l_mono = QLabel("mono")
        self.l_stereo = QLabel("stereo")
        info.addWidget(self.l_mono)
        info.addWidget(self.l_stereo)
        right.addLayout(info)
        sl = QHBoxLayout()
        sl.setSpacing(6)
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setToolTip("Hangerő")
        self.vol.setFocusPolicy(Qt.NoFocus)
        self.vol.valueChanged.connect(lambda x: setattr(self.player, "volume", x / 100))
        self.bal = QSlider(Qt.Horizontal)
        self.bal.setRange(-100, 100)
        self.bal.setFixedWidth(60)
        self.bal.setToolTip("Balansz (dupla katt: közép)")
        self.bal.setFocusPolicy(Qt.NoFocus)
        self.bal.valueChanged.connect(self._balance)
        self.bal.mouseDoubleClickEvent = lambda _e: self.bal.setValue(0)
        sl.addWidget(self.vol, 3)
        sl.addWidget(self.bal)
        self.b_vis = small_btn("VIS", True)
        self.b_vis.setToolTip("Nagy oszcilloszkóp ki/be")
        self.b_vis.toggled.connect(lambda on: self.scope_win.setVisible(on))
        self.b_pl = small_btn("PL", True)
        self.b_pl.setToolTip("Lejátszási lista ki/be")
        self.b_pl.toggled.connect(lambda on: self.pl_win.setVisible(on))
        self.b_md = small_btn("MD", True)
        self.b_md.setToolTip("MilkDrop-látvány ki/be (M)")
        self.b_md.toggled.connect(lambda on: self.md_win.setVisible(on) if self.md_win else None)
        self.b_md.setVisible(milkdrop.available())
        sl.addWidget(self.b_vis)
        sl.addWidget(self.b_md)
        sl.addWidget(self.b_pl)
        right.addLayout(sl)
        top.addLayout(right, 1)
        pv.addLayout(top)

        self.seek = JumpSlider(Qt.Horizontal)
        self.seek.setObjectName("seek")
        self.seek.setRange(0, 1000)
        self.seek.setFocusPolicy(Qt.NoFocus)
        self.seek.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.seek.sliderReleased.connect(self._seek_release)
        pv.addWidget(self.seek)

        tr = QHBoxLayout()
        tr.setSpacing(2)
        for sym, tip, slot in (("⏮", "Előző (Z)", self.prev), ("▶", "Lejátszás (X)", self.play),
                               ("⏸", "Szünet (C)", self.pause), ("⏹", "Stop (V)", self.stop),
                               ("⏭", "Következő (B)", self.next), ("⏏", "Fájlok megnyitása (L)", self.open_files)):
            b = QPushButton(sym)
            b.setObjectName("transport")
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(slot)
            tr.addWidget(b)
            if sym == "⏭":
                tr.addSpacing(6)
        tr.addSpacing(10)
        self.b_shuffle = small_btn("SHUFFLE", True)
        self.b_repeat = small_btn("REPEAT", True)
        tr.addWidget(self.b_shuffle)
        tr.addWidget(self.b_repeat)
        tr.addStretch(1)
        logo = QLabel("◉ SYNCAMP")
        logo.setStyleSheet("color:#c8a028; font: bold italic 11px 'Segoe UI';")
        tr.addWidget(logo)
        pv.addLayout(tr)
        self.content.addWidget(self.panel)

        self.scope_panel = ScopePanel(self.player, self.ss)
        self.scope_win = VisWindow("SYNCAMP  OSZCILLOSZKÓP", self.scope_panel, self.wgroup, self)
        self.scope_win.on_drop = self.add_paths
        self.scope_win.closed.connect(lambda: self.b_vis.setChecked(False))
        self.wgroup.add(self.scope_win)

        self.md_win = None
        if milkdrop.available():
            self.md_panel = MilkDropPanel(self.player, self.ss)
            self.md_win = VisWindow("SYNCAMP  MILKDROP", self.md_panel, self.wgroup, self)
            self.md_win.on_drop = self.add_paths
            self.md_win.closed.connect(lambda: self.b_md.setChecked(False))
            self.wgroup.add(self.md_win)

        self.pl_win = SkinWindow("SYNCAMP  LEJÁTSZÁSI LISTA", self.wgroup, self)
        self.pl_win.on_drop = self.add_paths
        self.pl_win.closed.connect(lambda: self.b_pl.setChecked(False))
        self.pl_win.setMinimumSize(300, 140)
        self.wgroup.add(self.pl_win)
        self.pl_box = QWidget()
        plv = QVBoxLayout(self.pl_box)
        plv.setContentsMargins(6, 2, 6, 2)
        plv.setSpacing(3)
        self.pl = Playlist()
        self.pl.itemDoubleClicked.connect(lambda it: self.play_index(self.pl.indexOfTopLevelItem(it)))
        self.pl.files_dropped.connect(self.add_paths)
        self.pl.model().rowsMoved.connect(self._rows_moved)
        plv.addWidget(self.pl, 1)
        foot = QHBoxLayout()
        foot.setSpacing(3)
        for text, slot in (("+ ADD", self.open_files), ("+ MAPPA", self.open_folder),
                           ("− REM", self.remove_selected), ("CLR", self.clear_playlist)):
            b = small_btn(text)
            b.clicked.connect(slot)
            foot.addWidget(b)
        foot.addStretch(1)
        self.total = QLabel("")
        self.total.setObjectName("info")
        foot.addWidget(self.total)
        foot.addWidget(QSizeGrip(self.pl_box))
        plv.addLayout(foot)
        self.pl_win.content.addWidget(self.pl_box)

        self.setMinimumWidth(560)
        self.setFixedHeight(self.sizeHint().height())
        self.resize(640, self.height())

    def _shortcuts(self):
        for key, slot in (("Z", self.prev), ("X", self.play), ("C", self.pause), ("V", self.stop),
                          ("B", self.next), ("L", self.open_files), ("F", self.toggle_fullscreen),
                          ("Escape", self.exit_fullscreen),
                          ("M", lambda: self.b_md.setChecked(not self.b_md.isChecked())),
                          ("N", lambda: self.md_win and self.md_panel.view.next_preset()),
                          ("Space", self.pause), ("Left", lambda: self.seek_rel(-5)),
                          ("Right", lambda: self.seek_rel(5)),
                          ("Up", lambda: self.vol.setValue(self.vol.value() + 5)),
                          ("Down", lambda: self.vol.setValue(self.vol.value() - 5)),
                          ("Return", self._play_selected), ("Delete", self.remove_selected)):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(slot)

    def title_double_clicked(self):
        pass    # a főablak mérete fix magasságú, nincs mit kinagyítani

    # --- lejátszási lista --------------------------------------------------
    def add_paths(self, paths):
        files = expand_paths(paths)
        was_empty = not self.paths
        for f in files:
            self.paths.append(f)
            it = QTreeWidgetItem(["", self._dur_text(f)])
            it.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            it.setData(0, Qt.UserRole, f)
            it.setFlags(it.flags() & ~Qt.ItemIsDropEnabled)
            self.pl.addTopLevelItem(it)
        self._renumber()
        missing = [f for f in files if f not in self._durations]
        if missing:
            threading.Thread(target=self._info_worker, args=(missing,), daemon=True).start()
        if was_empty and files and self.state == "stop":
            self.play_index(0)

    def _info_worker(self, files):
        for f in files:
            try:
                d = engine.file_info(f)[0]
            except Exception:
                d = -1.0
            self.bridge.info.emit(f, d)

    def _on_info(self, path, dur):
        self._durations[path] = dur
        for i in range(self.pl.topLevelItemCount()):
            it = self.pl.topLevelItem(i)
            if it.data(0, Qt.UserRole) == path:
                it.setText(1, self._dur_text(path))
        self._update_total()

    def _dur_text(self, path):
        d = self._durations.get(path)
        if d is None:
            return ""
        return "hiba" if d < 0 else fmt_time(d)

    def _update_total(self):
        total = sum(d for p in self.paths if (d := self._durations.get(p, 0)) > 0)
        h, rest = divmod(int(total), 3600)
        tt = f"{h}:{rest // 60:02d}:{rest % 60:02d}" if h else fmt_time(total)
        self.total.setText(f"{len(self.paths)} szám  {tt}")

    def _rows_moved(self, *_):
        cur = self.paths[self.current] if 0 <= self.current < len(self.paths) else None
        self.paths = [self.pl.topLevelItem(i).data(0, Qt.UserRole)
                      for i in range(self.pl.topLevelItemCount())]
        # ugyanaz a fájl többször is szerepelhet – a jelöltet tartsuk meg
        if cur is not None:
            for i in range(self.pl.topLevelItemCount()):
                if self.pl.topLevelItem(i).data(0, Qt.UserRole + 1):
                    self.current = i
                    break
        QTimer.singleShot(0, self._renumber)

    def _renumber(self):
        f = QFont("Segoe UI", 9)
        for i in range(self.pl.topLevelItemCount()):
            it = self.pl.topLevelItem(i)
            path = it.data(0, Qt.UserRole)
            is_cur = i == self.current
            it.setData(0, Qt.UserRole + 1, is_cur)
            it.setText(0, f"{i + 1}. {title_of(path)}")
            col = QColor(255, 255, 255) if is_cur else QColor(0, 224, 40)
            it.setForeground(0, col)
            it.setForeground(1, col)
            f.setBold(is_cur)
            it.setFont(0, f)
        self._update_total()

    def remove_selected(self):
        rows = sorted((self.pl.indexOfTopLevelItem(it) for it in self.pl.selectedItems()), reverse=True)
        for r in rows:
            self.pl.takeTopLevelItem(r)
            del self.paths[r]
            if r == self.current:
                self.current = -1
            elif r < self.current:
                self.current -= 1
        self._renumber()

    def clear_playlist(self):
        self.pl.clear()
        self.paths = []
        self.current = -1
        self._renumber()

    def open_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Zenék megnyitása", self._last_dir(),
            "Hangfájlok (*.mp3 *.flac *.wav *.ogg);;Minden fájl (*.*)")
        if files:
            self.add_paths(files)

    def open_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Mappa hozzáadása", self._last_dir())
        if d:
            self.add_paths([d])

    def _last_dir(self):
        return os.path.dirname(self.paths[-1]) if self.paths else os.path.expanduser("~/Music")

    # --- vezérlés ----------------------------------------------------------
    def play_index(self, i, start_at=0.0, autoplay=True):
        if not (0 <= i < len(self.paths)):
            return
        path = self.paths[i]
        self.current = i
        self._renumber()
        self._load_token += 1
        token = self._load_token
        self._loading_title = f"Feldolgozás: {title_of(path)} …"
        self.player.stop()
        self.state = "stop"

        def work():
            try:
                tr = engine.load_track(path, self.player.sr)
                self.bridge.loaded.emit(token, (tr, start_at, autoplay), "")
            except Exception as ex:
                self.bridge.loaded.emit(token, None, str(ex))

        threading.Thread(target=work, daemon=True).start()

    def _on_loaded(self, token, payload, err):
        if token != self._load_token:
            return
        self._loading_title = None
        if payload is None:
            self._failures += 1
            self._durations[self.paths[self.current]] = -1.0
            it = self.pl.topLevelItem(self.current)
            if it is not None:
                it.setText(1, "hiba")
            if self._failures >= len(self.paths):
                # minden szám hibás – ne pörögjön körbe a végtelenségig
                self._failures = 0
                self.stop()
                self._loading_title = f"Egyik szám sem nyitható meg ({err})"
                return
            self._loading_title = f"Nem sikerült megnyitni: {title_of(self.paths[self.current])} – ugrás"
            QTimer.singleShot(1500, self.next)
            return
        self._failures = 0
        track, start_at, autoplay = payload
        self.player.load(track)
        if start_at:
            self.player.seek(start_at)
        self._durations[track.path] = track.duration
        self.kbps.setText(str(track.kbps))
        self.khz.setText(str(track.khz))
        stereo = track.channels > 1
        self.l_mono.setObjectName("indoff" if stereo else "ind")
        self.l_stereo.setObjectName("ind" if stereo else "indoff")
        for lbl in (self.l_mono, self.l_stereo):
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)
        if autoplay:
            self.player.play()
            self.state = "play"
        else:
            self.state = "pause" if start_at else "stop"

    def play(self):
        if self.state == "pause" and self.player.track is not None:
            self.player.play()
            self.state = "play"
            return
        sel = self.pl.selectedItems()
        if self.current < 0 and sel:
            self.play_index(self.pl.indexOfTopLevelItem(sel[0]))
        elif self.current < 0:
            self.play_index(0)
        elif self.player.track is not None and self.player.track.path == self.paths[self.current]:
            self.player.seek(0)
            self.player.play()
            self.state = "play"
        else:
            self.play_index(self.current)

    def _play_selected(self):
        sel = self.pl.selectedItems()
        if sel:
            self.play_index(self.pl.indexOfTopLevelItem(sel[0]))

    def pause(self):
        if self.state == "play":
            self.player.pause()
            self.state = "pause"
        elif self.state == "pause":
            self.player.play()
            self.state = "play"
        elif self.state == "stop" and self.player.track is not None:
            self.play()

    def stop(self):
        self.player.stop()
        self.state = "stop"

    def _next_index(self, step):
        n = len(self.paths)
        if n == 0:
            return -1
        if self.b_shuffle.isChecked() and n > 1:
            return random.choice([i for i in range(n) if i != self.current])
        i = self.current + step
        if i >= n or i < 0:
            if not self.b_repeat.isChecked() and step > 0:
                return -1
            i %= n
        return i

    def next(self):
        i = self._next_index(1)
        if i < 0:
            i = 0 if self.paths else -1
        if i >= 0:
            self.play_index(i)

    def prev(self):
        _, frame, _ = self.player.heard()
        if self.player.track is not None and frame / self.player.sr > 3:
            self.player.seek(0)
            return
        i = self._next_index(-1)
        if i >= 0:
            self.play_index(i)

    def seek_rel(self, d):
        if self.player.track is None:
            return
        _, frame, _ = self.player.heard()
        self.player.seek(frame / self.player.sr + d)

    def _seek_release(self):
        self._seeking = False
        tr = self.player.track
        if tr is not None:
            self.player.seek(self.seek.value() / 1000 * tr.duration)

    def _balance(self, v):
        if abs(v) < 8:
            v = 0
        self.player.balance = v / 100

    def toggle_fullscreen(self):
        """F: a MilkDrop-ablakot nagyítja, ha látszik, különben a szkópot."""
        if self.md_win is not None and (self.md_win.isVisible() or self.md_win.isFullScreen()) \
                and not self.scope_win.isFullScreen():
            self.md_win.toggle_fullscreen()
            return
        if not self.scope_win.isVisible():
            self.b_vis.setChecked(True)
        self.scope_win.toggle_fullscreen()

    def exit_fullscreen(self):
        for w in (self.scope_win, self.md_win):
            if w is not None and w.isFullScreen():
                w.toggle_fullscreen()

    # --- óraütés: minden képkockánál -------------------------------------
    def _tick(self):
        tr, frame, audible = self.player.heard(0.016)
        if self.player.ended and not self.player.heard()[2]:
            self.player.ended = False
            i = self._next_index(1)
            if i >= 0:
                self.play_index(i)
            else:
                self.stop()
        self.display.state = self.state
        if tr is not None:
            self.display.seconds = frame / self.player.sr
            self.display.duration = tr.duration
            if not self._seeking:
                self.seek.blockSignals(True)
                self.seek.setValue(int(1000 * frame / max(1, tr.frames)))
                self.seek.blockSignals(False)
        else:
            self.display.seconds = 0
        if self._loading_title:
            self.marquee.set_text(self._loading_title)
        elif 0 <= self.current < len(self.paths):
            p = self.paths[self.current]
            d = self._durations.get(p)
            suffix = f" ({fmt_time(d)})" if d and d > 0 else ""
            self.marquee.set_text(f"{self.current + 1}. {title_of(p)}{suffix}")
        self.display.update()
        self.display.mini.update()
        if self.scope_win.isVisible():
            self.scope_panel.scope.update()
            self.scope_panel.sync_from_settings_light()
        if self.md_win is not None and self.md_win.isVisible():
            self.md_panel.view.update()

    def _blink(self):
        self.display.blink = not self.display.blink

    # --- beállítások -------------------------------------------------------
    def _restore(self):
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                s = json.load(f)
        except Exception:
            s = {}
        self.vol.setValue(s.get("volume", 80))
        self.bal.setValue(s.get("balance", 0))
        self.ss.timebase = s.get("timebase", self.ss.timebase)
        self.ss.gain = s.get("gain", self.ss.gain)
        self.ss.mode = s.get("mode", self.ss.mode)
        self.ss.trigger = s.get("trigger", True)
        self.ss.persistence = s.get("persistence", True)
        self.ss.offset_ms = s.get("offset_ms", 0)
        self.scope_panel.sync_from_settings()
        self.b_shuffle.setChecked(s.get("shuffle", False))
        self.b_repeat.setChecked(s.get("repeat", True))
        self._saved = s     # az ablakok helye a megjelenés után áll be
        self._durations.update(s.get("durations", {}))
        paths = [p for p in s.get("playlist", []) if os.path.exists(p)]
        self.add_paths_silent(paths)
        cur = s.get("current", -1)
        if 0 <= cur < len(self.paths):
            self.play_index(cur, start_at=s.get("position", 0.0), autoplay=False)

    def showEvent(self, e):
        super().showEvent(e)
        if not self._layout_done:
            self._layout_done = True
            QTimer.singleShot(0, self._apply_layout)

    def _apply_layout(self):
        """Ablakok helye: a mentett, vagy alapból egymás alá tapasztva."""
        s = self._saved
        wins = s.get("windows", {})
        g = wins.get("main")
        if g and on_some_screen(QRect(*g)):
            self.setGeometry(g[0], g[1], max(g[2], self.minimumWidth()), self.height())
        else:
            # első indítás: a három ablak egymás alatt férjen el a képernyőn
            avail = self.screen().availableGeometry()
            total = self.height() + 300 + 260
            y = max(avail.y(), min(self.y(), avail.y() + avail.height() - total))
            self.move(self.x(), y)
        below = QRect(self.x(), self.y() + self.height(), self.width(), 300)
        sg = QRect(*wins["scope"]) if "scope" in wins else below
        if not on_some_screen(sg):
            sg = below
        self.scope_win.setGeometry(sg)
        below = QRect(self.x(), sg.y() + sg.height(), self.width(), 260)
        pg = QRect(*wins["pl"]) if "pl" in wins else below
        if not on_some_screen(pg):
            pg = below
        self.pl_win.setGeometry(pg)
        if self.md_win is not None:
            # alapból a főablak jobb oldalához tapad
            right = QRect(self.x() + self.width(), self.y(), 640, 480)
            mg = QRect(*wins["md"]) if "md" in wins else right
            if not on_some_screen(mg):
                mg = right if on_some_screen(right) else QRect(self.x() + 40, self.y() + 40, 640, 480)
            self.md_win.setGeometry(mg)
            self.md_panel.set_texts(s.get("md_texts"))
            self.md_panel.set_options(s.get("md_seconds", 20), s.get("md_lock", False),
                                      s.get("md_offset_ms", 0), s.get("md_logo", False))
            self.b_md.setChecked(s.get("md", True))
        self.b_vis.setChecked(s.get("vis", True))
        self.b_pl.setChecked(s.get("pl", True))

    def add_paths_silent(self, paths):
        state = self.state
        self.state = "busy"     # ne induljon automatikusan
        self.add_paths(paths)
        self.state = state

    def closeEvent(self, e):
        tr, frame, _ = self.player.heard()
        pos = frame / self.player.sr if tr is not None and self.state != "stop" else 0.0
        def rect(w):
            r = w.normal_geometry()
            return [r.x(), r.y(), r.width(), r.height()]

        s = {
            "volume": self.vol.value(), "balance": self.bal.value(),
            "timebase": self.ss.timebase, "gain": self.ss.gain, "mode": self.ss.mode,
            "trigger": self.ss.trigger, "persistence": self.ss.persistence,
            "offset_ms": self.ss.offset_ms, "shuffle": self.b_shuffle.isChecked(),
            "repeat": self.b_repeat.isChecked(), "vis": self.b_vis.isChecked(),
            "pl": self.b_pl.isChecked(),
            "windows": {"main": rect(self), "scope": rect(self.scope_win), "pl": rect(self.pl_win)},
            "md": self.b_md.isChecked(),
            "playlist": self.paths, "current": self.current, "position": pos,
            "durations": {p: self._durations[p] for p in self.paths if p in self._durations},
        }
        if self.md_win is not None:
            s["windows"]["md"] = rect(self.md_win)
            s["md_seconds"] = self.md_panel.view.preset_seconds
            s["md_lock"] = self.md_panel.view.locked
            s["md_offset_ms"] = self.md_panel.view.offset_ms
            s["md_logo"] = self.md_panel.b_logo.isChecked()
            s["md_texts"] = self.md_panel.texts
        try:
            os.makedirs(SETTINGS_DIR, exist_ok=True)
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(s, f, ensure_ascii=False, indent=1)
        except Exception:
            pass
        self.timer.stop()
        self.player.close()
        for w in (self.scope_win, self.pl_win, self.md_win):
            if w is not None:
                w.allow_close = True
                w.close()
        super().closeEvent(e)
        QTimer.singleShot(0, QApplication.quit)


def title_of(path):
    return os.path.splitext(os.path.basename(path))[0]


def make_icon():
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(10, 20, 14))
    p.setPen(QColor(200, 160, 40))
    p.drawRoundedRect(2, 2, 60, 60, 10, 10)
    pts = [QPointF(6 + i, 32 - 18 * math.sin(i / 52 * 2 * math.pi * 1.5)) for i in range(53)]
    p.setPen(QPen(QColor(60, 255, 110), 4))
    p.drawPolyline(QPolygonF(pts))
    p.end()
    return QIcon(pm)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP)
    w = MainWindow()
    w.show()
    if len(sys.argv) > 1:
        w.add_paths(sys.argv[1:])
    rc = app.exec()
    # A beállítás már a closeEvent-ben elmentődött; a hangkártya-könyvtár
    # leállása ne tarthassa életben a folyamatot ablak nélkül.
    os._exit(rc)


if __name__ == "__main__":
    main()
