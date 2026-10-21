"""Winamp-szerű különálló ablakok: saját keret, méretezés a széleknél,
mágneses tapadás egymáshoz és a képernyő széléhez, és ha a főablakot
húzod, a hozzá tapadt ablakok vele mozognak."""

from functools import reduce

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter
from PySide6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

SNAP = 12      # ennyi képponton belül odatapad
EDGE = 5       # ilyen széles sávban lehet a keretnél méretezni

ALL_EDGES = (Qt.LeftEdge, Qt.RightEdge, Qt.TopEdge, Qt.BottomEdge)

_CURSORS = {
    frozenset([Qt.LeftEdge]): Qt.SizeHorCursor, frozenset([Qt.RightEdge]): Qt.SizeHorCursor,
    frozenset([Qt.TopEdge]): Qt.SizeVerCursor, frozenset([Qt.BottomEdge]): Qt.SizeVerCursor,
    frozenset([Qt.LeftEdge, Qt.TopEdge]): Qt.SizeFDiagCursor,
    frozenset([Qt.RightEdge, Qt.BottomEdge]): Qt.SizeFDiagCursor,
    frozenset([Qt.RightEdge, Qt.TopEdge]): Qt.SizeBDiagCursor,
    frozenset([Qt.LeftEdge, Qt.BottomEdge]): Qt.SizeBDiagCursor,
}


class TitleBar(QWidget):
    def __init__(self, win, text, minimize=False):
        super().__init__()
        self.win = win
        self.text = text
        self.setFixedHeight(20)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 3, 2)
        lay.addStretch(1)
        buttons = [("✕", win.close)]
        if minimize:
            buttons.insert(0, ("_", win.showMinimized))
        self._btn_space = 6 + 20 * len(buttons)
        for sym, slot in buttons:
            b = QPushButton(sym)
            b.setObjectName("tb")
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(slot)
            lay.addWidget(b)

    def paintEvent(self, _):
        p = QPainter(self)
        g = QLinearGradient(0, 0, 0, self.height())
        active = self.win.isActiveWindow()
        g.setColorAt(0, QColor(28, 28, 52))
        g.setColorAt(1, QColor(18, 18, 34))
        p.fillRect(self.rect(), g)
        p.setFont(QFont("Segoe UI", 8, QFont.Bold))
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(self.text)
        cx = self.width() // 2
        p.setPen(QColor(200, 160, 40) if active else QColor(110, 100, 80))
        for y in (6, 10, 14):
            p.drawLine(8, y, cx - tw // 2 - 10, y)
            p.drawLine(cx + tw // 2 + 10, y, self.width() - self._btn_space, y)
        p.setPen(QColor(240, 230, 200) if active else QColor(150, 150, 170))
        p.drawText(cx - tw // 2, 14, self.text)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.win.begin_drag(e.globalPosition().toPoint())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self.win.drag_to(e.globalPosition().toPoint())

    def mouseReleaseEvent(self, _):
        self.win.end_drag()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.win.title_double_clicked()


class WindowGroup:
    """Az összes ablakot ismeri: tapadás és együtt mozgás."""

    def __init__(self):
        self.windows = []
        self.leader = None

    def add(self, w, leader=False):
        self.windows.append(w)
        if leader:
            self.leader = w

    def visible(self):
        return [w for w in self.windows if w.isVisible() and not w.is_expanded()]

    @staticmethod
    def _touch(a, b):
        ax1, ay1, ax2, ay2 = a.x(), a.y(), a.x() + a.width(), a.y() + a.height()
        bx1, by1, bx2, by2 = b.x(), b.y(), b.x() + b.width(), b.y() + b.height()
        v_overlap = ay1 < by2 and by1 < ay2
        h_overlap = ax1 < bx2 and bx1 < ax2
        if v_overlap and (abs(ax2 - bx1) <= 1 or abs(bx2 - ax1) <= 1):
            return True
        return h_overlap and (abs(ay2 - by1) <= 1 or abs(by2 - ay1) <= 1)

    def docked_with(self, w):
        """Minden ablak, ami (akár közvetve) hozzá tapad."""
        vis = self.visible()
        group, todo = [w], [w]
        while todo:
            cur = todo.pop()
            for o in vis:
                if o not in group and self._touch(cur.geometry(), o.geometry()):
                    group.append(o)
                    todo.append(o)
        return group

    def snap(self, w, target, group):
        x, y, W, H = target.x(), target.y(), w.width(), w.height()
        cx, cy = [], []
        for o in self.visible():
            if o in group:
                continue
            r = o.geometry()
            ox1, oy1, ox2, oy2 = r.x(), r.y(), r.x() + r.width(), r.y() + r.height()
            if y < oy2 + SNAP and oy1 < y + H + SNAP:
                cx += [ox2 - x, ox1 - (x + W), ox1 - x, ox2 - (x + W)]
            if x < ox2 + SNAP and ox1 < x + W + SNAP:
                cy += [oy2 - y, oy1 - (y + H), oy1 - y, oy2 - (y + H)]
        scr = w.screen().availableGeometry()
        cx += [scr.x() - x, scr.x() + scr.width() - (x + W)]
        cy += [scr.y() - y, scr.y() + scr.height() - (y + H)]
        dx = min((c for c in cx if abs(c) <= SNAP), key=abs, default=0)
        dy = min((c for c in cy if abs(c) <= SNAP), key=abs, default=0)
        return QPoint(x + dx, y + dy)


class SkinWindow(QWidget):
    closed = Signal()

    def __init__(self, title, group, parent=None, edges=ALL_EDGES, minimize=False):
        super().__init__(parent)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setWindowTitle(title)
        self.group = group
        self._edges = edges
        self._drag_off = None
        self._drag_group = None
        self._maxed_from = None     # "teljes ablak" előtti méret
        self.allow_close = False
        self.on_drop = None
        self.setAcceptDrops(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.body = QWidget()
        self.body.setObjectName("body")
        self.body.setMouseTracking(True)
        self.body.installEventFilter(self)
        outer.addWidget(self.body)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(4, 4, 4, 4)
        self.body_layout.setSpacing(0)
        self.title = TitleBar(self, title, minimize)
        self.body_layout.addWidget(self.title)
        self.content = QVBoxLayout()
        self.content.setContentsMargins(0, 0, 0, 0)
        self.content.setSpacing(0)
        self.body_layout.addLayout(self.content, 1)

    # --- méretezés a keretnél ---------------------------------------------
    def _hit(self, pos):
        if self.is_expanded():
            return []
        w, h = self.body.width(), self.body.height()
        hits = []
        if pos.x() < EDGE:
            hits.append(Qt.LeftEdge)
        elif pos.x() >= w - EDGE:
            hits.append(Qt.RightEdge)
        if pos.y() < EDGE:
            hits.append(Qt.TopEdge)
        elif pos.y() >= h - EDGE:
            hits.append(Qt.BottomEdge)
        return [e for e in hits if e in self._edges]

    def eventFilter(self, obj, ev):
        if obj is self.body:
            t = ev.type()
            if t == QEvent.MouseMove and not ev.buttons():
                hits = self._hit(ev.position().toPoint())
                if hits:
                    self.body.setCursor(_CURSORS[frozenset(hits)])
                else:
                    self.body.unsetCursor()
            elif t == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
                hits = self._hit(ev.position().toPoint())
                if hits:
                    self.windowHandle().startSystemResize(reduce(lambda a, b: a | b, hits))
                    return True
            elif t == QEvent.Leave:
                self.body.unsetCursor()
        return super().eventFilter(obj, ev)

    # --- húzás, tapadás ----------------------------------------------------
    def begin_drag(self, gpos):
        if self.is_expanded():
            return
        self._drag_off = gpos - self.pos()
        if self is self.group.leader:
            self._drag_group = self.group.docked_with(self)
        else:
            self._drag_group = [self]

    def drag_to(self, gpos):
        if self._drag_off is None:
            return
        target = self.group.snap(self, gpos - self._drag_off, self._drag_group)
        d = target - self.pos()
        if d.isNull():
            return
        for w in self._drag_group:
            w.move(w.pos() + d)

    def end_drag(self):
        self._drag_off = None
        self._drag_group = None

    # --- "teljes ablak" / teljes képernyő ------------------------------
    def is_expanded(self):
        return self.isFullScreen() or self._maxed_from is not None

    def normal_geometry(self):
        """A mentéshez: a nem kinagyított méret."""
        if self._maxed_from is not None:
            return self._maxed_from
        if self.isFullScreen() and getattr(self, "_full_from", None) is not None:
            return self._full_from
        return self.geometry()

    def toggle_maximize(self):
        if self._maxed_from is not None:
            self.setGeometry(self._maxed_from)
            self._maxed_from = None
        elif not self.isFullScreen():
            self._maxed_from = QRect(self.geometry())
            self.setGeometry(self.screen().availableGeometry())

    def title_double_clicked(self):
        self.toggle_maximize()

    def changeEvent(self, e):
        if e.type() == QEvent.ActivationChange:
            self.title.update()
        super().changeEvent(e)

    def closeEvent(self, e):
        if self.allow_close:
            super().closeEvent(e)
            return
        # a mellékablakok csak elrejtőznek, mint a Winampban
        e.ignore()
        self.hide()
        self.closed.emit()

    def dragEnterEvent(self, e):
        if self.on_drop and e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        if self.on_drop:
            self.on_drop([u.toLocalFile() for u in e.mimeData().urls()])


def on_some_screen(rect):
    c = rect.center()
    return any(s.geometry().contains(c) for s in QApplication.screens())
