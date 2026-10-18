"""Холст редактора: рабочее поле, сетка, линейки, 16 инструментов, виды."""
from __future__ import annotations

import copy
import math
import time
from typing import Dict, List, Optional, Sequence, Set, Tuple

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QImage, QPainter,
                           QPainterPath, QPen, QPixmap, QPolygon, QPolygonF,
                           QBrush, QTransform)
from PySide6.QtWidgets import QApplication, QWidget

from ..core import drc as drc_mod
from ..core.fill import compute_fill
from ..core.geom import (MIL, arc_points, bbox_of, bbox_union, dist, pt_seg_dist,
                         rdp)
from ..core.model import (ALL_LAYERS, BOTTOM_KEY, COPPER_KEYS, LAYER_BY_KEY,
                          draw_sort_key,
                          TOP_KEY, Board, CircleEl, Component, Connection,
                          Document, Element, FillEl, Pad, PolygonEl, RectEl,
                          SmdPad, TextEl, Track, nets)
from ..core.tools_lib import Macro, RouteParams, autotrace

RULER = 22
STATUS_H = 0

TOOLS = [
    ("cursor", "Курсор", "Esc", "cursor"),
    ("zoom", "Масштаб", "Z", "zoom"),
    ("track", "Дорожка / Линия", "T", "track"),
    ("pad", "Контакт THT", "P", "pad"),
    ("smd", "SMD-контакт", "S", "smd"),
    ("circle", "Круг / Дуга", "R", "circle"),
    ("poly", "Полигон", "F", "poly"),
    ("text", "Текст", "L", "text"),
    ("rect", "Прямоугольник", "Q", "rect"),
    ("shape", "Фигура", "N", "shape"),
    ("mask", "Маска", "O", "mask"),
    ("conn", "Линии связи", "C", "conn"),
    ("route", "Автотрасса", "A", "route"),
    ("probe", "Контроль (тест)", "X", "probe"),
    ("measure", "Измеритель", "M", "measure"),
    ("photo", "Фотовид", "V", "photo"),
]

DEFAULT_SETTINGS: Dict = {
    "units": "mm",                 
    "grid_step": 0.5,
    "grid_steps": [0.1, 0.25, 0.5, 1.0, 1.27, 2.54, 5.0, 10.0, 25.4],
    "wheel_step": 90.0,
    "grid_visible": True,
    "grid_thick": 5,
    "snap": True,
    "autograb": True,
    "rubber": 1,                   
    "metallization": False,
    "track_width": 0.4,
    "track_widths": [0.2, 0.3, 0.4, 0.6, 0.8, 1.0],
    "clearance": 0.25,
    "thermal_gap": 0.4,
    "thermal_spoke": 0.5,
    "thermal_dirs": [True, True, True, True],
    "fill_per_element": False,
    "fill_dim": False,
    "fill_through": False,
    "auto_fill_on_edit": False,
    "pad_dia": 1.8,
    "hole_dia": 0.9,
    "pad_shape": "circle",
    "smd_w": 1.0,
    "smd_h": 1.5,
    "text_height": 1.6,
    "text_thickness": 0.2,
    "text_style": 0,
    "text_auto": False,
    "poly_contour": 0.25,
    "circle_width": 0.3,
    "rect_width": 0.25,
    "route_width": 0.4,
    "route_clearance": 0.3,
    "route_grid": 0.25,
    "route_coeff": 1,
    "undo_depth": 40,
    "probe_blink": True,
    "probe_virtual": True,
    "min_text_thickness": 0.15,
    "autosave_min": 5,
    "show_origin": True,
    "show_grid_dots": False,
    "drc_rules": dict(drc_mod.DEFAULT_RULES),
    "imask_gap_tht": 0.15,
    "mask_gap_smd": 0.1,
    "hole_color": "dark",
    "imax_cu": 35.0,
    "imax_temp": 25.0,
    "keys": {t[2]: t[0] for t in TOOLS},
}


def fmt_len(v: float, units: str = "", digits: int = None) -> str:
    units = units or DEFAULT_SETTINGS["units"]
    if units == "mil":
        return f"{v / MIL:.{3 if digits is None else digits}f}"
    return f"{v:.{3 if digits is None else digits}f}"


class Canvas(QWidget):
    toolChanged = Signal(str)
    cursorMoved = Signal(float, float, str)
    selectionChanged = Signal(int)
    documentChanged = Signal()
    statusMessage = Signal(str)
    requestDialog = Signal(str)        
    viewChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(520, 380)
        self.setAutoFillBackground(False)

        self.doc: Document = Document()
        self.settings: Dict = copy.deepcopy(DEFAULT_SETTINGS)
        self.tokens: Dict = {}
        self.field_origin = QPoint(RULER, RULER)   

        
        self.scale = 6.0                 
        self.offset = QPointF(0.0, 0.0)  
        self.prev_view: List[Tuple[float, QPointF]] = []

        
        self.tool = "cursor"
        self.active_layer = TOP_KEY
        self.selection: List[str] = []
        self.rev = 0
        self.cache: Optional[QPixmap] = None
        self.cache_key = None
        self._cache_pixmap = None
        self._paint_rev = 0
        self._bg: Optional[QPixmap] = None
        self._bg_key = None
        self._bbox_cache: Dict[str, object] = {}

        self.preview: List[Element] = []
        self.temp_points: List[Tuple[float, float]] = []
        self.measure_from: Optional[Tuple[float, float]] = None
        self.measure_to: Optional[Tuple[float, float]] = None
        self.drag_start: Optional[Tuple[float, float]] = None
        self.drag_elems: List[Tuple[Element, Tuple[float, float]]] = []
        self.marquee: Optional[Tuple[Tuple[float, float], Tuple[float, float]]] = None
        self.conn_first: Optional[str] = None
        self.route_first: Optional[str] = None
        self.panning = False
        self.pan_origin = QPointF()
        self.cursor_mm = (0.0, 0.0)
        self.probe_ids: Set[str] = set()
        self.probe_hits: List[Tuple[float, float]] = []
        self.pads_of_width: Dict[str, float] = {}
        self.grabbed = False
        self.mask_open_default = True
        self.placed_macro: Optional[Macro] = None
        self._placed_name = "макрос"
        self.macro_rot = 0.0
        self.macro_bottom = False
        self.photo_side = "top"
        self.photo_components = False
        self.photo_transparent = False
        self.template = None
        self.template_offset = (0.0, 0.0)
        self.template_dpi = 300

        self.undo_stack: List[dict] = []
        self.redo_stack: List[dict] = []
        self._blink = False
        self.blink_timer = QTimer(self)
        self.blink_timer.timeout.connect(self._toggle_blink)
        self.blink_timer.start(420)

    
    def set_document(self, doc: Document):
        self.doc = doc
        self.selection = []
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.probe_ids.clear()
        self.rev += 1
        self._paint_rev += 1
        self._bbox_cache.clear()
        self.update()

    def board(self) -> Board:
        return self.doc.board()

    def invalidate(self, structural: bool = True):
        if structural:
            self.rev += 1
        self._paint_rev += 1
        self._bbox_cache.clear()
        self.update()

    def touch(self):
        self.doc.dirty = True
        self._paint_rev += 1
        self._bbox_cache.clear()
        self.documentChanged.emit()

    
    def field_rect(self) -> QRect:
        o = self.field_origin
        return QRect(o.x(), o.y(), max(1, self.width() - o.x()),
                     max(1, self.height() - o.y()))

    def to_model(self, pos: QPointF) -> Tuple[float, float]:
        f = self.field_rect()
        x = (pos.x() - f.left()) / self.scale + self.offset.x()
        y = (pos.y() - f.top()) / self.scale + self.offset.y()
        return (x, y)

    def to_screen(self, mm: Tuple[float, float], mirror_x: bool = False) -> QPointF:
        f = self.field_rect()
        x, y = mm
        if mirror_x:
            x = self._mirror_x(x)
        return QPointF(f.left() + (x - self.offset.x()) * self.scale,
                       f.top() + (y - self.offset.y()) * self.scale)

    def _mirror_x(self, x: float) -> float:
        b = self.board()
        x0, y0, x1, y1 = b.outline_rect()
        return (x0 + x1) - x

    def layer_mirror(self, layer: str) -> bool:
        if self.photo_mode():
            return self.photo_side == "bottom"
        return not LAYER_BY_KEY[layer].top if layer in LAYER_BY_KEY else False

    def photo_mode(self) -> bool:
        return self.tool == "photo"

    def tol_mm(self) -> float:
        return 5.0 / max(self.scale, 0.01)

    def snap_point(self, p: Tuple[float, float], fine: bool = False,
                   free: bool = False) -> Tuple[float, float]:
        step = self.settings["grid_step"]
        if fine:
            step = step / 2.0
        if free or not self.settings["snap"]:
            return p
        if self.grabbed:
            return p
        return (round(p[0] / step) * step, round(p[1] / step) * step)

    def snap_with_cursor(self, p) -> Tuple[float, float]:
        """Применяет привязку + автозахват к контактам и узлам."""
        free = bool(self._mods_ctrl)
        if not free and self.settings["autograb"] and not self._mods_shift:
            g = self._grab_target(p)
            if g:
                self.grabbed = True
                return g
        self.grabbed = False
        return self.snap_point(self.to_model(p), fine=self._mods_shift, free=free)

    def _grab_target(self, pos) -> Optional[Tuple[float, float]]:
        """Ближайшая точка захвата: центр КП или узел дорожки/полигона."""
        if hasattr(pos, "x") and not isinstance(pos, (tuple, list)):
            px, py = pos.x(), pos.y()
        else:
            px, py = pos[0], pos[1]
        screen_pos = (px, py)
        b = self.board()
        tol = max(self.tol_mm() * 1.5, 0.35)
        best = None
        best_d = tol
        for el in b.elements.values():
            if el.locked or el.kind in ("fill", "conn"):
                continue
            if isinstance(el, Pad):
                d = math.hypot(el.x - px, el.y - py)
                if d < best_d:
                    best, best_d = (el.x, el.y), d
            elif el.kind in ("track", "poly", "smd"):
                if isinstance(el, SmdPad):
                    d = math.hypot(el.x - px, el.y - py)
                    if d < best_d:
                        best, best_d = (el.x, el.y), d
                    continue
                pts = el.outline_points()
                for i in range(len(pts)):
                    d = math.hypot(pts[i][0] - px, pts[i][1] - py)
                    if d < best_d:
                        best, best_d = pts[i], d
                    if i + 1 < len(pts):
                        d2 = pt_seg_dist(screen_pos, pts[i], pts[i + 1])
                        if d2 < best_d * 0.6:
                            best, best_d = pts[i], d2
        return best

    
    def find_element(self, p, tol=None, layer_filter=True) -> Optional[Element]:
        b = self.board()
        tol = self.tol_mm() if tol is None else tol
        found = None
        for el in b.elements.values():
            if el.kind in ("conn",):
                continue
            if layer_filter and el.layer != self.active_layer and \
                    not (self.settings["probe_virtual"] and el.kind == "pad"):
                if not self._layer_relevant(el):
                    continue
            bb = el.bbox()
            if bb and not (bb[0] - tol <= p[0] <= bb[2] + tol and bb[1] - tol <= p[1] <= bb[3] + tol):
                continue
            if el.hit(p, tol):
                if el.locked:
                    continue
                found = el
        return found

    def _layer_relevant(self, el: Element) -> bool:
        if el.kind == "pad" and self.active_layer in el.copper_layers():
            return True
        if el.kind == "smd" and el.layer == self.active_layer:
            return True
        return False

    def element_at_all_layers(self, p, tol=None) -> Optional[Element]:
        b = self.board()
        tol = self.tol_mm() if tol is None else tol
        for el in b.elements.values():
            if el.kind in ("conn", "fill"):
                continue
            if el.hit(p, tol):
                return el
        return None

    def pad_at(self, p, tol=None) -> Optional[Element]:
        tol = self.tol_mm() if tol is None else tol
        b = self.board()
        for el in b.elements.values():
            if isinstance(el, (Pad, SmdPad)) and el.hit(p, tol):
                return el
        return None

    def conn_at(self, p, tol=None) -> Optional[Connection]:
        tol = self.tol_mm() if tol is None else tol
        b = self.board()
        for el in b.elements.values():
            if isinstance(el, Connection) and el.a and el.b:
                a, bb = el.a, el.b
                ea, eb = b.elements.get(a), b.elements.get(b)
                if ea is None or eb is None:
                    continue
                pa, pb = _el_center(ea), _el_center(eb)
                from ..core.geom import seg_seg_dist
                if seg_seg_dist(pa, pb, p, (p[0] + 0.01, p[1] + 0.001)) <= tol:
                    return el
        return None

    
    def zoom_at(self, factor: float, anchor: Optional[QPointF] = None):
        f = self.field_rect()
        anchor = anchor if anchor is not None else QPointF(f.center())
        before = self.to_model(anchor)
        self.scale = max(0.05, min(400.0, self.scale * factor))
        self.offset = QPointF(self.offset.x(), self.offset.y())
        after = self.to_screen(before, False)
        delta = anchor - after
        self.offset = QPointF(self.offset.x() - delta.x() / self.scale,
                              self.offset.y() - delta.y() / self.scale)
        self.invalidate(structural=True)
        self.viewChanged.emit()

    def zoom_all(self):
        b = self.board()
        box = bbox_union([b.outline_rect()] +
                         [el.bbox() for el in b.elements.values() if el.bbox()],
                         b.outline_rect())
        self._zoom_to_box(box)

    def zoom_board(self):
        self._zoom_to_box(self.board().outline_rect())

    def zoom_objects(self):
        els = [self.board().elements[i] for i in self.selection if i in self.board().elements]
        box = bbox_union([el.bbox() for el in els if el.bbox()], None)
        if box:
            self._zoom_to_box(box)

    def _zoom_to_box(self, box, pad: float = 12.0):
        f = self.field_rect()
        w = max(0.5, box[2] - box[0])
        h = max(0.5, box[3] - box[1])
        s = min((f.width() - 2 * pad) / w, (f.height() - 2 * pad) / h)
        self.scale = max(0.05, min(400.0, s))
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        self.offset = QPointF(cx - f.width() / (2 * self.scale), cy - f.height() / (2 * self.scale))
        self.invalidate(structural=True)
        self.viewChanged.emit()

    def zoom_previous(self):
        if len(self.prev_view) >= 2:
            cur = (self.scale, QPointF(self.offset))
            target = self.prev_view.pop()
            self.prev_view.pop()
            self.scale, self.offset = target[0], QPointF(target[1])
            self.prev_view.append(cur)
            self.invalidate(structural=True)
            self.viewChanged.emit()

    def remember_view(self):
        self.prev_view.append((self.scale, QPointF(self.offset)))

    def set_scale(self, s: float):
        self.remember_view()
        self.scale = max(0.05, min(400.0, s))
        self.invalidate(structural=True)
        self.viewChanged.emit()

    
    def _bbox_of(self, el: Element):
        """Габариты элемента с кэшем (пересчёт при каждом изменении документа)."""
        bb = self._bbox_cache.get(el.id, False)
        if bb is False:
            bb = el.bbox()
            self._bbox_cache[el.id] = bb
        return bb

    def _visible_box(self):
        f = self.field_rect()
        x0 = self.offset.x() - 2.0
        y0 = self.offset.y() - 2.0
        return (x0, y0,
                x0 + f.width() / self.scale + 4.0,
                y0 + f.height() / self.scale + 4.0)

    @staticmethod
    def _box_hits(box, view) -> bool:
        return not (box[2] < view[0] or box[0] > view[2] or
                    box[3] < view[1] or box[1] > view[3])

    def _static_key(self):
        return (self.rev, self._paint_rev, round(self.scale, 6),
                round(self.offset.x(), 4), round(self.offset.y(), 4),
                self.width(), self.height(), self.active_layer, self.tool == "photo",
                self.photo_side, self.photo_components, self.photo_transparent,
                self.template_dpi, id(self.tokens),
                self.settings["grid_visible"], self.settings["grid_step"],
                self.settings["grid_thick"], self.settings["snap"],
                self.settings["fill_dim"], self.settings["fill_through"],
                self.settings["hole_color"], self.settings["units"],
                self.settings["show_origin"], self.template is not None)

    def paintEvent(self, event):
        p = QPainter(self)
        key = self._static_key()
        if self._bg is None or self._bg_key != key:
            self._render_bg(key)
        if self._bg is not None:
            p.drawPixmap(0, 0, self._bg)
        self._draw_preview(p)
        self._draw_marquee(p)
        self._draw_selection_marks(p)
        self._draw_probe(p)
        self._draw_measure(p)
        self._draw_conn_hot(p)
        self._draw_macro_preview(p)
        self._draw_ruler_cursor(p)
        self._draw_cursor(p)
        p.end()

    def _render_bg(self, key):
        pm = QPixmap(self.size())
        t = self.tokens or {}
        pm.fill(QColor(t.get("canvas", "#0a0d10")))
        p = QPainter(pm)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            field = self.field_rect()
            p.fillRect(field, QColor(t.get("canvas", "#0a0d10")))
            self._draw_board_bg(p, field)
            if self.settings["grid_visible"]:
                self._draw_grid(p, field)
            if self.template is not None:
                self._draw_template(p, field)
            self._draw_elements(p)
            self._draw_connections(p)
            self._draw_rulers(p)
        finally:
            p.end()
        self._bg = pm
        self._bg_key = key

    def _draw_board_bg(self, p: QPainter, field: QRect):
        t = self.tokens or {}
        b = self.board()
        if self.photo_mode():
            return
        poly = QPolygonF([self.to_screen(pt) for pt in b.outline_points()])
        p.setPen(QPen(QColor(t.get("outline", "#8c9199")), 1, Qt.PenStyle.DashLine))
        p.setBrush(QColor(t.get("board", "#14181c")))
        p.drawPolygon(poly)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if self.settings["show_origin"]:
            o = self.to_screen(b.origin)
            p.setPen(QPen(QColor("#ffffff"), 1))
            p.drawEllipse(o, 6, 6)
            p.drawLine(QPointF(o.x() - 9, o.y()), QPointF(o.x() + 9, o.y()))
            p.drawLine(QPointF(o.x(), o.y() - 9), QPointF(o.x(), o.y() + 9))

    def _draw_grid(self, p: QPainter, field: QRect):
        t = self.tokens or {}
        step = self.settings["grid_step"]
        if step * self.scale < 2.5:
            return
        thick_n = max(1, int(self.settings["grid_thick"]))
        minor = QColor(t.get("grid", "#2a2f35"))
        major = QColor(t.get("grid_thick", "#3a4149"))
        f = self.field_rect()
        x0 = self.offset.x()
        y0 = self.offset.y()
        x1 = x0 + f.width() / self.scale
        y1 = y0 + f.height() / self.scale
        gx0 = math.floor(x0 / step) * step
        gy0 = math.floor(y0 / step) * step
        if step * self.scale >= 6:
            i = int(round((gx0 / step)))
            x = gx0
            while x <= x1:
                sp = self.to_screen((x, 0))
                p.setPen(QPen(major if i % thick_n == 0 else minor, 1))
                p.drawLine(QPointF(sp.x(), f.top()), QPointF(sp.x(), f.bottom()))
                x += step
                i += 1
            j = int(round((gy0 / step)))
            y = gy0
            while y <= y1:
                sp = self.to_screen((0, y))
                p.setPen(QPen(major if j % thick_n == 0 else minor, 1))
                p.drawLine(QPointF(f.left(), sp.y()), QPointF(f.right(), sp.y()))
                y += step
                j += 1
        else:
            p.setPen(QPen(minor, 1))
            x = gx0
            while x <= x1:
                sp = self.to_screen((x, 0))
                p.drawPoint(QPointF(sp.x(), f.top()))
                x += step
            y = gy0
            while y <= y1:
                sp = self.to_screen((0, y))
                p.drawPoint(QPointF(f.left(), sp.y()))
                y += step

    def _draw_template(self, p: QPainter, field: QRect):
        img = self.template
        if img is None or img.isNull():
            return
        b = self.board()
        w_mm = img.width() / max(1.0, self.template_dpi) * 25.4
        h_mm = img.height() / max(1.0, self.template_dpi) * 25.4
        ox, oy = b.origin
        ox += self.template_offset[0]
        oy += self.template_offset[1]
        target = QRectF(self.to_screen((ox, oy)),
                        QPointF(w_mm * self.scale, h_mm * self.scale))
        p.setOpacity(0.75)
        p.drawImage(target, img)
        p.setOpacity(1.0)

    
    @staticmethod
    def _mix(c: QColor, other: QColor, t: float) -> QColor:
        """Смешать цвет c с other: t=0 — c, t=1 — other."""
        return QColor(int(c.red() * (1 - t) + other.red() * t),
                      int(c.green() * (1 - t) + other.green() * t),
                      int(c.blue() * (1 - t) + other.blue() * t),
                      c.alpha())

    def _layer_color(self, layer: str) -> QColor:
        b = self.board()
        custom = b.colors.get(layer)
        if custom:
            return QColor(custom)
        if layer in LAYER_BY_KEY:
            return QColor(LAYER_BY_KEY[layer].default_color)
        return QColor(LAYER_BY_KEY[self.active_layer].default_color)

    def _visible(self, layer: str) -> bool:
        return self.board().visible.get(layer, True)

    def _draw_elements(self, p: QPainter):
        b = self.board()
        photo = self.photo_mode()
        view = self._visible_box()
        items = []
        for el in b.elements.values():
            if el.kind == "conn":
                continue
            if photo:
                if not self._el_on_side(el, self.photo_side):
                    continue
            elif not (self._visible(el.layer) or el.layer == self.active_layer):
                continue
            if el.kind != "fill":
                bb = self._bbox_of(el)
                if bb is None or not self._box_hits(bb, view):
                    continue
            items.append(el)
        items.sort(key=draw_sort_key)
        for el in items:
            mir = self.layer_mirror(el.layer)
            col = self._layer_color(el.layer)
            if photo:
                col = self._photo_color(el)
            alpha = 255
            bg = QColor(self.tokens.get("canvas", "#0a0d10"))
            if not photo and el.kind == "fill":
                
                col = self._mix(col, bg, 0.45 if el.layer in ("M1", "V1") else 0.6)
                if self.settings["fill_dim"]:
                    alpha = 120
                if el.layer in ("M2", "V2", "K2") and not self.settings["fill_through"]:
                    alpha = min(alpha, 120)
            elif not photo and el.layer in ("M2", "K2", "V2"):
                
                alpha = 255 if self.settings["fill_through"] else 120
            col.setAlpha(alpha)
            if mir:
                
                b = self.board()
                x0, _y0, x1, _y1 = b.outline_rect()
                axis = self.to_screen(((x0 + x1) / 2, 0)).x()
                p.save()
                p.translate(2 * axis, 0)
                p.scale(-1.0, 1.0)
                self._draw_element(p, el, col, False, photo=photo)
                p.restore()
            else:
                self._draw_element(p, el, col, False, photo=photo)

    def _el_on_side(self, el: Element, side: str) -> bool:
        if side == "top":
            layers = [TOP_KEY, "K1"] + (["V1"] if el.kind == "pad" else [])
            if isinstance(el, Pad):
                return el.plated or True
            return el.layer in (TOP_KEY, "K1", "O", "V1")
        if isinstance(el, Pad):
            return True
        return el.layer in (BOTTOM_KEY, "K2", "O", "V2")

    def _photo_color(self, el: Element) -> QColor:
        if isinstance(el, Pad):
            return QColor("#d9a441")
        if isinstance(el, SmdPad):
            return QColor("#e8c46a")
        if el.layer in (TOP_KEY, BOTTOM_KEY, "V1", "V2"):
            return QColor("#c9a227")
        if el.kind == "text" or el.layer in ("K1", "K2"):
            return QColor("#101010")
        return QColor("#8a8a8a")

    def _draw_element(self, p: QPainter, el: Element, col: QColor, mir: bool,
                      photo: bool = False):
        pen = QPen(col)
        k = el.kind
        if k == "track":
            pen.setCapStyle(Qt.PenCapStyle.FlatCap if el.square_ends else Qt.PenCapStyle.RoundCap)
            pts = [self.to_screen(pt, mir) for pt in el.points]
            if len(pts) >= 2:
                path = QPainterPath(pts[0])
                for pt in pts[1:]:
                    path.lineTo(pt)
                if not photo and LAYER_BY_KEY[el.layer].top and el.layer != "O":
                    shade = QPen(QColor(self.tokens.get("canvas", "#0a0d10")))
                    shade.setWidthF(max(1.6, el.width * self.scale + 2.0))
                    shade.setCapStyle(pen.capStyle())
                    p.setPen(shade)
                    p.drawPath(path)
                pen.setWidthF(max(0.8, el.width * self.scale))
                p.setPen(pen)
                p.drawPath(path)
            if el.auto and not photo:
                p.setPen(QPen(QColor(150, 150, 150, 110), 0))
                p.drawPath(path)
        elif k == "pad":
            self._draw_pad(p, el, mir, photo)
        elif k == "smd":
            self._draw_smd(p, el, mir, photo)
        elif k == "circle":
            pen.setWidthF(max(0.8, el.width * self.scale))
            p.setPen(pen)
            pts = [self.to_screen(pt, mir) for pt in
                   arc_points(el.cx, el.cy, el.r, el.a0, el.a1, 4)]
            if el.filled:
                p.setBrush(QBrush(col))
                path = QPainterPath()
                path.addPolygon(QPolygonF(pts))
                p.drawPath(path)
                p.setBrush(Qt.BrushStyle.NoBrush)
            else:
                path = QPainterPath(pts[0])
                for pt in pts[1:]:
                    path.lineTo(pt)
                p.drawPath(path)
        elif k == "poly":
            pen.setWidthF(max(0.8, el.contour * self.scale))
            p.setPen(pen)
            pts = [self.to_screen(pt, mir) for pt in el.points]
            if len(pts) >= 3:
                p.setBrush(QBrush(col) if not el.hatched else Qt.BrushStyle.NoBrush)
                p.drawPolygon(QPolygonF(pts))
                p.setBrush(Qt.BrushStyle.NoBrush)
        elif k == "rect":
            a = self.to_screen((el.x0, el.y0), mir)
            b = self.to_screen((el.x1, el.y1), mir)
            r = QRectF(a, b).normalized()
            pen.setWidthF(max(0.8, el.width * self.scale))
            p.setPen(pen)
            p.setBrush(QBrush(col) if el.filled else Qt.BrushStyle.NoBrush)
            p.drawRect(r)
            p.setBrush(Qt.BrushStyle.NoBrush)
        elif k == "text":
            self._draw_text(p, el, mir)
        elif k == "fill":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(col))
            grow = (getattr(el, "cell", 0.0) or 0.0) * 0.85
            for r in el.rects:
                a = self.to_screen((r[0] - grow, r[1] - grow), mir)
                b = self.to_screen((r[2] + grow, r[3] + grow), mir)
                p.drawRect(QRectF(a, b).normalized())
            p.setBrush(Qt.BrushStyle.NoBrush)
        if el.negative and not photo:
            p.setPen(QPen(QColor("#ffffff"), 0))

    def _draw_pad(self, p: QPainter, el: Pad, mir: bool, photo: bool = False):
        t = self.tokens or {}
        col = self._layer_color(el.layer)
        w, h = el.outer()
        c = self.to_screen((el.x, el.y), mir)
        sw = max(0.8, w * self.scale)
        sh = max(0.8, h * self.scale)
        
        hole = QColor(t.get("hole", "#0a0d10"))
        if self.settings["hole_color"] == "white":
            hole = QColor("#ffffff")
        elif self.settings["hole_color"] == "clear":
            hole = Qt.GlobalColor.transparent
        rect = QRectF(c.x() - sw / 2, c.y() - sh / 2, sw, sh)
        if not photo and LAYER_BY_KEY[el.layer].top and el.layer != "O":
            p.setPen(QPen(QColor(self.tokens.get("canvas", "#0a0d10")), 1.8))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(rect.adjusted(-1, -1, 1, 1)) if el.shape == "circle" \
                else p.drawRect(rect.adjusted(-1, -1, 1, 1))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(col))
        if el.shape == "circle":
            p.drawEllipse(rect)
        else:
            p.drawRoundedRect(rect, min(sw, sh) * (0.25 if el.shape == "rounded" else 0.0),
                              min(sw, sh) * (0.25 if el.shape == "rounded" else 0.0))
        
        if el.hole_dia > 0:
            hr = el.hole_dia * self.scale / 2
            p.setBrush(QBrush(hole))
            p.drawEllipse(c, hr, hr)
            if not el.plated:
                p.setPen(QPen(QColor("#e6e9ee"), 1))
                p.drawLine(QPointF(c.x() - hr, c.y()), QPointF(c.x() + hr, c.y()))
                p.drawLine(QPointF(c.x(), c.y() - hr), QPointF(c.x(), c.y() + hr))
            p.setPen(Qt.PenStyle.NoPen)
        if el.thermal and not self.photo_mode():
            p.setPen(QPen(QColor("#ffd166"), 0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, sw / 2 + 2, sh / 2 + 2)

    def _draw_smd(self, p: QPainter, el: SmdPad, mir: bool, photo: bool = False):
        col = self._layer_color(el.layer)
        c = self.to_screen((el.x, el.y), mir)
        r = QRectF(c.x() - el.w * self.scale / 2, c.y() - el.h * self.scale / 2,
                   el.w * self.scale, el.h * self.scale)
        if not photo and LAYER_BY_KEY[el.layer].top and el.layer != "O":
            p.setPen(QPen(QColor(self.tokens.get("canvas", "#0a0d10")), 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            if el.shape == "circle":
                p.drawEllipse(r.adjusted(-1, -1, 1, 1))
            else:
                p.drawRect(r.adjusted(-1, -1, 1, 1))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(col))
        if el.shape == "circle":
            p.drawEllipse(r)
        elif el.shape == "roundrect":
            p.drawRoundedRect(r, 3, 3)
        else:
            p.drawRect(r)

    def _draw_text(self, p: QPainter, el: TextEl, mir: bool):
        col = self._layer_color(el.layer)
        px = max(4.0, el.height * self.scale)
        f = QFont("Segoe UI")
        f.setPixelSize(int(px))
        bold = (el.style // 3) == 1
        f.setBold(bold)
        f.setItalic((el.style // 3) == 2)
        path = QPainterPath()
        p.save()
        sp = self.to_screen((el.x, el.y), mir)
        p.translate(sp)
        p.rotate(-el.angle)
        if (el.style // 3) == 1 and (el.style % 3) == 2:
            p.scale(0.82, 1.0)
        path.addText(0, 0, f, el.display_text())
        if (el.style % 3) == 1:
            pw = max(0.6, el.thickness * self.scale * 1.6)
            pen = QPen(QBrush(col), pw)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        elif (el.style % 3) == 2:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(col.lighter(115)))
            p.drawPath(path)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(col))
            p.drawPath(path)
        p.restore()

    
    def _draw_connections(self, p: QPainter):
        if self.photo_mode():
            return
        view = self._visible_box()
        for a, c in self._conn_segments():
            x0, y0 = min(a.x(), c.x()), min(a.y(), c.y())
            x1, y1 = max(a.x(), c.x()), max(a.y(), c.y())
            m = 4.0
            if x1 < view[0] - m or x0 > view[2] + m or y1 < view[1] - m or y0 > view[3] + m:
                continue
            p.setPen(QPen(QColor("#5aa87a"), 1.2, Qt.PenStyle.DashLine))
            p.drawLine(a, c)

    def _conn_segments(self):
        b = self.board()
        out = []
        for el in b.elements.values():
            if not isinstance(el, Connection) or not el.a or not el.b:
                continue
            ea, eb = b.elements.get(el.a), b.elements.get(el.b)
            if ea is None or eb is None:
                continue
            out.append((self.to_screen(_el_center(ea)), self.to_screen(_el_center(eb))))
        return out

    def _draw_conn_hot(self, p: QPainter):
        """Подсветка связи под курсором — поверх кэша, при автотрассе."""
        if self.photo_mode() or self.tool != "route" or not self._mouse_in:
            return
        p.setPen(QPen(QColor((self.tokens or {}).get("warning", "#f5c96a")), 2.4))
        for a, c in self._conn_segments():
            if self._near_conn(a, c):
                p.drawLine(a, c)

    def _near_conn(self, a: QPointF, b: QPointF) -> bool:
        if not self._mouse_in:
            return False
        p = self._mouse_in
        from ..core.geom import seg_seg_dist
        return seg_seg_dist((a.x(), a.y()), (b.x(), b.y()), (p.x(), p.y()),
                            (p.x() + 0.01, p.y() + 0.001)) < self.tol_mm()

    def _draw_preview(self, p: QPainter):
        if not self.preview:
            return
        col = QColor(self.tokens.get("primary", "#d0e4ff"))
        for el in self.preview:
            c = QColor(col)
            c.setAlpha(190)
            self._draw_element(p, el, c, self.layer_mirror(el.layer))

    def _draw_marquee(self, p: QPainter):
        if not self.marquee:
            return
        (ax, ay), (bx, by) = self.marquee
        a = self.to_screen((ax, ay))
        b = self.to_screen((bx, by))
        p.setPen(QPen(QColor(self.tokens.get("primary", "#d0e4ff")), 1,
                      Qt.PenStyle.DashLine))
        p.setBrush(QColor(120, 170, 255, 30))
        p.drawRect(QRectF(a, b).normalized())
        p.setBrush(Qt.BrushStyle.NoBrush)

    def _draw_selection_marks(self, p: QPainter):
        if not self.selection:
            return
        b = self.board()
        col = QColor(self.tokens.get("selection", "#ff8a00"))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i in self.selection:
            el = b.elements.get(i)
            if el is None or el.bbox() is None:
                continue
            mir = self.layer_mirror(el.layer)
            bb = el.bbox()
            a = self.to_screen((bb[0], bb[1]), mir)
            c = self.to_screen((bb[2], bb[3]), mir)
            rect = QRectF(a, c).normalized().adjusted(-2, -2, 2, 2)
            if el.kind in ("track", "poly") and len(el.outline_points()) > 1:
                pts = [self.to_screen(pt, mir) for pt in el.outline_points()]
                p.setPen(QPen(col, 1.2, Qt.PenStyle.DashLine))
                p.drawPolyline(QPolygonF(pts))
                continue
            p.setPen(QPen(col, 1.4, Qt.PenStyle.DashLine))
            p.drawRect(rect)
            
            if el.kind in ("track", "poly"):
                for pt in el.outline_points():
                    sp = self.to_screen(pt, mir)
                    p.setBrush(QBrush(col))
                    p.drawEllipse(sp, 3, 3)
                    p.setBrush(Qt.BrushStyle.NoBrush)

    def _draw_probe(self, p: QPainter):
        if not self.probe_ids:
            return
        b = self.board()
        col = QColor(self.tokens.get("probe", "#7ddb9a"))
        if self.settings["probe_blink"] and not self._blink:
            col.setAlpha(120)
        p.setPen(QPen(col, 2.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i in self.probe_ids:
            el = b.elements.get(i)
            if el is None or el.bbox() is None:
                continue
            mir = self.layer_mirror(el.layer)
            bb = el.bbox()
            a = self.to_screen((bb[0], bb[1]), mir)
            c = self.to_screen((bb[2], bb[3]), mir)
            p.drawRect(QRectF(a, c).normalized().adjusted(-1, -1, 1, 1))

    def _draw_measure(self, p: QPainter):
        if self.measure_from is None or self.measure_to is None:
            return
        a = self.to_screen(self.measure_from)
        b = self.to_screen(self.measure_to)
        p.setPen(QPen(QColor("#ffffff"), 1))
        p.drawLine(a, b)
        dx = self.measure_to[0] - self.measure_from[0]
        dy = self.measure_to[1] - self.measure_from[1]
        d = math.hypot(dx, dy)
        ang = math.degrees(math.atan2(dy, dx))
        txt = (f"ΔX {fmt_len(dx, self.settings['units'])}   ΔY {fmt_len(dy, self.settings['units'])}\n"
               f"Расстояние {fmt_len(d, self.settings['units'])}   Угол {ang:.1f}°")
        _draw_bubble(p, QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2), txt)

    def _draw_macro_preview(self, p: QPainter):
        if self.placed_macro is None or not self._mouse_in:
            return
        mm = self.snap_point(self.to_model(self._mouse_in))
        els = self.placed_macro.instance(mm[0], mm[1], self.macro_rot, self.macro_bottom)
        col = QColor(self.tokens.get("primary", "#d0e4ff"))
        col.setAlpha(200)
        for el in els:
            mir = self.layer_mirror(el.layer)
            self._draw_element(p, el, col, mir)

    
    def _draw_rulers(self, p: QPainter):
        t = self.tokens or {}
        field = self.field_rect()
        p.fillRect(0, 0, self.width(), RULER, QColor(t.get("surface_container", "#1c2024")))
        p.fillRect(0, 0, RULER, self.height(), QColor(t.get("surface_container", "#1c2024")))
        p.setPen(QPen(QColor(t.get("outline_variant", "#42474e")), 1))
        p.drawLine(0, RULER, self.width(), RULER)
        p.drawLine(RULER, 0, RULER, self.height())
        step = self.settings["grid_step"]
        if step * self.scale < 5:
            step = self._nice_step(self.settings["grid_step"] * self.scale)
        f = QFont("Segoe UI")
        f.setPixelSize(9)
        p.setFont(f)
        
        x0 = self.offset.x()
        x1 = x0 + field.width() / self.scale
        v = math.ceil(x0 / step) * step
        label_every = max(1, int(math.ceil(48 / max(step * self.scale, 0.001))))
        idx = int(round(v / step)) if step else 0
        while v <= x1:
            sp = self.to_screen((v, 0))
            major = idx % max(1, int(self.settings["grid_thick"])) == 0
            p.setPen(QPen(QColor(t.get("outline", "#8c9199")) if major
                          else QColor(t.get("outline_variant", "#42474e")), 1))
            p.drawLine(QPointF(sp.x(), RULER - 5), QPointF(sp.x(), RULER))
            if idx % label_every == 0:
                p.setPen(QColor(t.get("on_surface_variant", "#c2c7cf")))
                p.drawText(QRectF(sp.x() - 30, 2, 60, 13), Qt.AlignmentFlag.AlignCenter,
                           fmt_len(v, self.settings["units"], 2))
            v += step
            idx += 1
        y0 = self.offset.y()
        y1 = y0 + field.height() / self.scale
        v = math.ceil(y0 / step) * step
        idx = int(round(v / step)) if step else 0
        while v <= y1:
            sp = self.to_screen((0, v))
            major = idx % max(1, int(self.settings["grid_thick"])) == 0
            p.setPen(QPen(QColor(t.get("outline", "#8c9199")) if major
                          else QColor(t.get("outline_variant", "#42474e")), 1))
            p.drawLine(QPointF(RULER - 5, sp.y()), QPointF(RULER, sp.y()))
            if major:
                p.setPen(QColor(t.get("on_surface_variant", "#c2c7cf")))
                p.drawText(QRectF(1, sp.y() - 8, RULER - 3, 16),
                           Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                           fmt_len(v, self.settings["units"], 2))
            v += step
            idx += 1
        p.setPen(QPen(QColor(t.get("outline", "#8c9199")), 1))
        p.drawLine(0, RULER - 1, RULER - 1, RULER - 1)

    def _draw_ruler_cursor(self, p: QPainter):
        if not self._mouse_in:
            return
        p.setPen(QPen(QColor("#ff5252"), 1))
        cx = self.to_screen((self.cursor_mm[0], 0))
        cy = self.to_screen((0, self.cursor_mm[1]))
        p.drawLine(QPointF(cx.x(), 0), QPointF(cx.x(), RULER))
        p.drawLine(QPointF(0, cy.y()), QPointF(RULER, cy.y()))

    def _nice_step(self, px: float) -> float:
        steps = [0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500]
        for s in steps:
            if s * self.scale >= px:
                return s
        return steps[-1]

    def _draw_cursor(self, p: QPainter):
        if not self._mouse_in or self.panning:
            return
        f = self.field_rect()
        if not f.contains(self._mouse_in.toPoint()):
            return
        c = self.to_screen(self.cursor_mm)
        col = QColor("#ff5252") if self.grabbed else QColor("#e6e9ee")
        pen = QPen(col, 1)
        p.setPen(pen)
        p.drawLine(QPointF(f.left(), c.y()), QPointF(f.right(), c.y()))
        p.drawLine(QPointF(c.x(), f.top()), QPointF(c.x(), f.bottom()))
        p.drawLine(QPointF(c.x() - 12, c.y() - 12), QPointF(c.x() - 4, c.y() - 12))
        p.drawLine(QPointF(c.x() + 4, c.y() - 12), QPointF(c.x() + 12, c.y() - 12))
        p.drawLine(QPointF(c.x() - 12, c.y() + 12), QPointF(c.x() - 4, c.y() + 12))
        p.drawLine(QPointF(c.x() + 4, c.y() + 12), QPointF(c.x() + 12, c.y() + 12))
        p.drawLine(QPointF(c.x() - 12, c.y() - 12), QPointF(c.x() - 12, c.y() - 4))
        p.drawLine(QPointF(c.x() - 12, c.y() + 4), QPointF(c.x() - 12, c.y() + 12))
        p.drawLine(QPointF(c.x() + 12, c.y() - 12), QPointF(c.x() + 12, c.y() - 4))
        p.drawLine(QPointF(c.x() + 12, c.y() + 4), QPointF(c.x() + 12, c.y() + 12))
        txt = f"X {fmt_len(self.cursor_mm[0], self.settings['units'])}   Y {fmt_len(self.cursor_mm[1], self.settings['units'])}"
        _draw_bubble(p, QPointF(c.x() + 16, c.y() + 20), txt)

    def _toggle_blink(self):
        if self.probe_ids and self.settings["probe_blink"]:
            self._blink = not self._blink
            self.update()

    
    _mods_ctrl = False
    _mods_shift = False
    _mouse_in = None

    def mousePressEvent(self, ev):
        self.setFocus()
        pos = ev.position()
        self._mouse_in = pos
        mods = ev.modifiers()
        self._mods_ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        self._mods_shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)

        if ev.button() == Qt.MouseButton.MiddleButton or \
                (ev.button() == Qt.MouseButton.LeftButton and self._mods_ctrl and self.tool == "cursor" and False):
            self.panning = True
            self.pan_origin = pos
            self.remember_view()
            return
        if ev.button() == Qt.MouseButton.RightButton:
            if self.placed_macro is not None:
                self.cancel_macro_place("Размещение макроса отменено (ПКМ)")
                return
            
            if self.tool == "track" and len(self.temp_points) >= 2:
                self.finish_track()
                return
            if self.tool == "poly" and len(self.temp_points) >= 3:
                self.close_polygon()
                return
            if self.temp_points or self.preview:
                self.temp_points.clear()
                self.preview.clear()
                self.update()
                return
            self.set_tool("cursor")
            return
        if not self.field_rect().contains(pos.toPoint()):
            return
        handler = {
            "cursor": self.t_cursor_press, "zoom": self.t_zoom_press,
            "track": self.t_track_press, "pad": self.t_pad_press, "smd": self.t_smd_press,
            "circle": self.t_circle_press, "poly": self.t_poly_press,
            "rect": self.t_rect_press, "mask": self.t_mask_press,
            "conn": self.t_conn_press, "route": self.t_route_press,
            "probe": self.t_probe_press, "measure": self.t_measure_press,
            "photo": self.t_probe_press,
            "text": self.t_text_press, "shape": self.t_shape_press,
        }.get(self.tool)
        if handler:
            handler(ev, self.snap_with_cursor(pos))

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        self._mouse_in = pos
        mods = ev.modifiers()
        self._mods_ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        self._mods_shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if self.panning:
            d = pos - self.pan_origin
            self.offset = QPointF(self.offset.x() - d.x() / self.scale,
                                  self.offset.y() - d.y() / self.scale)
            self.update()
            return
        mm = self.to_model(pos)
        self.cursor_mm = mm
        self.cursorMoved.emit(mm[0], mm[1], fmt_len(mm[0], self.settings["units"]))
        if self.placed_macro is not None:
            self.update()
            return
        drag = {
            "cursor": self.d_cursor_move, "track": self.d_track, "pad": self.d_simple_preview,
            "smd": self.d_simple_preview, "circle": self.d_circle, "poly": self.d_poly,
            "rect": self.d_rect, "mask": self.d_mask_hover, "conn": self.d_conn_hover,
            "measure": self.d_measure, "route": self.d_route_hover,
        }.get(self.tool)
        if drag and (ev.buttons() & Qt.MouseButton.LeftButton or
                     self.tool in ("measure", "mask", "route", "conn", "poly", "circle", "rect", "track")):
            drag(ev, self.snap_with_cursor(pos))
        else:
            self.update()

    def mouseReleaseEvent(self, ev):
        if self.panning:
            self.panning = False
            return
        mm = self.snap_with_cursor(ev.position())
        rel = {
            "cursor": self.r_cursor_release, "zoom": self.r_zoom_release,
            "track": self.r_track_release, "poly": self.r_poly_release,
            "circle": self.r_circle_release, "rect": self.r_rect_release,
            "measure": self.r_measure, "probe": None, "photo": None,
        }.get(self.tool)
        if rel:
            rel(ev, mm)
        self.drag_start = None
        self.drag_elems = []
        self.update()

    def mouseDoubleClickEvent(self, ev):
        pos = ev.position()
        mm = self.snap_with_cursor(pos)
        if self.tool == "poly" and len(self.temp_points) >= 2:
            self.temp_points.append(mm)
            self.close_polygon()
            return
        if self.tool == "track" and len(self.temp_points) >= 2:
            self.finish_track()
            return
        el = self.find_element(mm)
        if el is not None and el.kind == "text":
            self.requestDialog.emit("text")
        elif el is not None:
            self.select([el.id])
            self.requestDialog.emit("component")

    def pan_px(self, dx: float, dy: float):
        self.offset = QPointF(self.offset.x() - dx / self.scale,
                              self.offset.y() - dy / self.scale)
        self.update()

    def wheelEvent(self, ev):
        mods = ev.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            ad = ev.angleDelta()
            pd = ev.pixelDelta()
            delta = ad.y() if ad.y() else (pd.y() if pd.y() else 0)
            if not delta:
                return
            factor = 1.2 ** (delta / 120.0)
            self.remember_view()
            self.zoom_at(factor, ev.position())
            return
        dx, dy = self._wheel_delta(ev)
        if not dx and not dy:
            return
        if mods & Qt.KeyboardModifier.ShiftModifier:
            dx = dx or dy
            dy = 0
        px = float(self.settings.get("wheel_step", 90.0))
        self.pan_px(dx * px, dy * px)
        self.viewChanged.emit()

    def _wheel_delta(self, ev) -> Tuple[float, float]:
        """Шаг колеса в «щелчках»: обычное колесо, трекпад и наклон по X."""
        ad, pd = ev.angleDelta(), ev.pixelDelta()
        acc_x, acc_y = self._wheel_x + ad.x() / 120.0 + pd.x() / 40.0, \
            self._wheel_y + ad.y() / 120.0 + pd.y() / 40.0
        self._wheel_x, self._wheel_y = acc_x, acc_y
        return round(acc_x), round(acc_y)

    _wheel_x = 0.0
    _wheel_y = 0.0

    def pan_by(self, dx: float, dy: float):
        self.offset = QPointF(self.offset.x() - dx / self.scale,
                              self.offset.y() - dy / self.scale)
        self.update()

    
    def set_tool(self, name: str):
        if name not in dict((t[0], t) for t in TOOLS):
            return
        self.tool = name
        self.temp_points.clear()
        if name != "cursor" and self.placed_macro is not None:
            self.placed_macro = None
        self.preview.clear()
        self.measure_from = None
        self.measure_to = None
        self.conn_first = None
        self.route_first = None
        self.drag_start = None
        self.marquee = None
        self.toolChanged.emit(name)
        self.setCursor(self._tool_cursor(name))
        self.update()

    def _tool_cursor(self, name: str) -> Qt.CursorShape:
        if name == "zoom":
            return Qt.CursorShape.SizeAllCursor
        if name == "measure":
            return Qt.CursorShape.CrossCursor
        return Qt.CursorShape.CrossCursor

    
    def t_cursor_press(self, ev, mm):
        if self.placed_macro is not None:
            
            self.place_macro_at(mm)
            return
        el = self.find_element(mm)
        if self._mods_shift:
            if el:
                self.select_toggle(el.id)
            else:
                self.marquee = (mm, mm)
            self.update()
            return
        if el:
            self.select([el.id])
            self.begin_drag(mm)
        else:
            if not self._mods_ctrl:
                self.select([])
            self.marquee = (mm, mm)
        self.update()

    def begin_drag(self, mm):
        b = self.board()
        self.drag_start = mm
        ids = set(self.selection)
        
        comp = None
        for c in b.components:
            if any(i in ids for i in c.ids):
                comp = c
                break
        if comp:
            ids = set(comp.ids) | ids
        self.drag_elems = [(b.elements[i], _el_center(b.elements[i]))
                           for i in ids if i in b.elements and not b.elements[i].locked]
        
        if self.settings["rubber"] and ids:
            extra = self._rubber_ids(ids)
            for i in extra:
                if i not in ids and i in b.elements:
                    ids.add(i)
                    self.drag_elems.append((b.elements[i], _el_center(b.elements[i])))

    def _rubber_ids(self, ids: Set[str]) -> Set[str]:
        b = self.board()
        uf = nets(b, True)
        out: Set[str] = set()
        roots = {uf.find(i) for i in ids if i in uf.p}
        for i in list(uf.p):
            if uf.find(i) in roots:
                out.add(i)
        return out

    def d_cursor_move(self, ev, mm):
        if self.marquee:
            self.marquee = (self.marquee[0], mm)
            self.update()
            return
        if self.drag_elems and self.drag_start:
            dx = mm[0] - self.drag_start[0]
            dy = mm[1] - self.drag_start[1]
            if self._mods_ctrl:
                dx = round(dx / self.settings["grid_step"]) * self.settings["grid_step"]
                dy = round(dy / self.settings["grid_step"]) * self.settings["grid_step"]
            for el, base in self.drag_elems:
                el.move(dx - self._last_dx, dy - self._last_dy)
            self._last_dx = dx
            self._last_dy = dy
            self.invalidate()
            self.viewChanged.emit()

    _last_dx = 0.0
    _last_dy = 0.0

    def r_cursor_release(self, ev, mm):
        if self.marquee:
            a, c = self.marquee
            self.marquee = None
            box = (min(a[0], c[0]), min(a[1], c[1]), max(a[0], c[0]), max(a[1], c[1]))
            ids = []
            b = self.board()
            for el in b.elements.values():
                if el.kind in ("conn", "fill") or el.locked:
                    continue
                if not self._visible(el.layer) and el.layer != self.active_layer:
                    continue
                bb = el.bbox()
                if bb and bb[0] >= box[0] and bb[1] >= box[1] and bb[2] <= box[2] and bb[3] <= box[3]:
                    ids.append(el.id)
            self.select(ids if not self._mods_ctrl else self.selection + ids)
        if self.drag_elems:
            self.push_undo()
            self.touch()
            self.on_geometry_changed()
        self._last_dx = self._last_dy = 0.0
        self.update()

    
    def t_zoom_press(self, ev, mm):
        self.drag_start = mm
        self.marquee = (mm, mm)

    def d_zoom_press(self, ev, mm):
        pass

    def d_zoom_move(self, ev, mm):
        if self.marquee:
            self.marquee = (self.marquee[0], mm)
            self.update()

    def r_zoom_release(self, ev, mm):
        if self.marquee:
            a, c = self.marquee
            self.marquee = None
            if abs(c[0] - a[0]) > 0.2 and abs(c[1] - a[1]) > 0.2:
                self._zoom_to_box((min(a[0], c[0]), min(a[1], c[1]),
                                   max(a[0], c[0]), max(a[1], c[1])), pad=2)
            else:
                self.remember_view()
                self.zoom_at(1.3 if ev.button() == Qt.MouseButton.LeftButton else 1 / 1.3)

    def zoom_click(self, positive: bool):
        self.remember_view()
        self.zoom_at(1.3 if positive else 1 / 1.3)

    
    def t_track_press(self, ev, mm):
        if not self.temp_points:
            self.push_undo()
            self.temp_points = [mm]
        elif dist(mm, self.temp_points[-1]) > 1e-6:
            self.temp_points.append(mm)

    def d_track(self, ev, mm):
        if not self.temp_points:
            return
        pts = self.temp_points + [mm]
        self.preview = [Track(layer=self.active_layer, points=pts,
                              width=self.settings["track_width"])]
        self.update()

    def r_track_release(self, ev, mm):
        
        if len(self.temp_points) == 1 and dist(mm, self.temp_points[0]) > 1e-4:
            self.temp_points.append(mm)
            self.finish_track()
            return
        
        self.update()

    def finish_track(self, negative: bool = False):
        if len(self.temp_points) >= 2:
            t = Track(layer=self.active_layer, points=list(self.temp_points),
                      width=self.settings["track_width"], negative=negative)
            self._add(t)
        self.temp_points = []
        self.preview.clear()
        self.update()

    
    def t_pad_press(self, ev, mm):
        self.push_undo()
        p = Pad(layer=self.active_layer, x=mm[0], y=mm[1],
                pad_dia=self.settings["pad_dia"], hole_dia=self.settings["hole_dia"],
                shape=self.settings["pad_shape"], plated=True,
                size=(self.settings["pad_dia"], self.settings["pad_dia"]),
                clearance=self.settings["clearance"], mask_open=self.mask_open_default)
        self._add(p, select=True)
        self.statusMessage.emit(f"Контакт: Ø{self.settings['hole_dia']} / "
                                f"Ø{self.settings['pad_dia']} мм · F12 — металлизация")

    def d_simple_preview(self, ev, mm):
        self.update()

    def t_smd_press(self, ev, mm):
        self.push_undo()
        s = SmdPad(layer=self.active_layer, x=mm[0], y=mm[1],
                   w=self.settings["smd_w"], h=self.settings["smd_h"],
                   clearance=self.settings["clearance"], mask_open=self.mask_open_default)
        self._add(s, select=True)

    def toggle_plating(self):
        b = self.board()
        pads = [b.elements[i] for i in self.selection if isinstance(b.elements.get(i), Pad)]
        if not pads:
            return
        self.push_undo()
        for p in pads:
            p.plated = not p.plated
        self.on_geometry_changed()
        self.invalidate()
        self.statusMessage.emit("Металлизация: " + ("вкл" if pads[0].plated else "выкл"))

    
    def t_text_press(self, ev, mm):
        self.requestDialog.emit("text")

    def t_shape_press(self, ev, mm):
        self.requestDialog.emit("shape")

    
    def t_circle_press(self, ev, mm):
        self.push_undo()
        self.temp_points = [mm]

    def d_circle(self, ev, mm):
        if not self.temp_points:
            return
        c = self.temp_points[0]
        r = dist(c, mm)
        self.preview = [CircleEl(layer=self.active_layer, cx=c[0], cy=c[1], r=r,
                                 width=self.settings["circle_width"], filled=False)]
        self.update()

    def r_circle_release(self, ev, mm):
        if not self.temp_points:
            return
        c = self.temp_points[0]
        r = dist(c, mm)
        if r > 1e-4:
            self._add(CircleEl(layer=self.active_layer, cx=c[0], cy=c[1], r=r,
                               width=self.settings["circle_width"]))
        self.temp_points = []
        self.preview.clear()

    
    def t_poly_press(self, ev, mm):
        if not self.temp_points:
            self.push_undo()
            self.temp_points = [mm]
        elif dist(mm, self.temp_points[-1]) > 1e-6:
            self.temp_points.append(mm)

    def d_poly(self, ev, mm):
        if len(self.temp_points) < 1:
            return
        pts = self.temp_points + [mm]
        if len(pts) >= 3:
            self.preview = [PolygonEl(layer=self.active_layer, points=list(pts),
                                      contour=self.settings["poly_contour"])]
        self.update()

    def r_poly_release(self, ev, mm):
        
        if len(self.temp_points) == 1 and dist(mm, self.temp_points[0]) > 1e-4:
            self.temp_points.append(mm)
            self.update()
        return

    def close_polygon(self, negative: bool = False):
        if len(self.temp_points) >= 3:
            self._add(PolygonEl(layer=self.active_layer, points=list(self.temp_points),
                                contour=self.settings["poly_contour"], negative=negative))
        self.temp_points = []
        self.preview.clear()
        self.update()

    
    def t_rect_press(self, ev, mm):
        self.push_undo()
        self.temp_points = [mm]

    def d_rect(self, ev, mm):
        if not self.temp_points:
            return
        a = self.temp_points[0]
        self.preview = [RectEl(layer=self.active_layer, x0=a[0], y0=a[1], x1=mm[0], y1=mm[1],
                               width=self.settings["rect_width"])]
        self.update()

    def r_rect_release(self, ev, mm):
        if not self.temp_points:
            return
        a = self.temp_points[0]
        if abs(a[0] - mm[0]) > 1e-4 and abs(a[1] - mm[1]) > 1e-4:
            self._add(RectEl(layer=self.active_layer, x0=a[0], y0=a[1], x1=mm[0], y1=mm[1],
                             width=self.settings["rect_width"]))
        self.temp_points = []
        self.preview.clear()

    
    def t_mask_press(self, ev, mm):
        el = self.element_at_all_layers(mm, max(self.tol_mm(), 0.3))
        if el is None or el.kind in ("fill", "conn"):
            return
        self.push_undo()
        el.mask_open = not el.mask_open
        self.touch()
        self.invalidate()
        self.statusMessage.emit(f"{el.type_name}: маска "
                                f"{'открыта' if el.mask_open else 'закрыта'}")

    def d_mask_hover(self, ev, mm):
        el = self.element_at_all_layers(mm, max(self.tol_mm(), 0.3))
        self.statusMessage.emit(
            f"{el.type_name}: маска {'открыта' if el.mask_open else 'закрыта'}" if el
            else "Маска: ЛКМ по элементу — открыть/закрыть окно маски")

    def reset_mask(self):
        self.push_undo()
        for el in self.board().elements.values():
            if isinstance(el, (Pad, SmdPad)):
                el.mask_open = True
        self.touch()
        self.invalidate()

    
    def t_conn_press(self, ev, mm):
        pad = self.pad_at(mm, max(self.tol_mm(), 0.4))
        if pad is None:
            self.conn_first = None
            self.statusMessage.emit("Линии связи: укажите контакт (КП THT/SMD)")
            return
        if self.conn_first is None:
            self.conn_first = pad.id
            self.statusMessage.emit("Линии связи: укажите второй контакт")
        elif self.conn_first != pad.id:
            self.push_undo()
            self._add(Connection(a=self.conn_first, b=pad.id, layer=self.active_layer))
            self.conn_first = None
        else:
            self.conn_first = None

    def d_conn_hover(self, ev, mm):
        self.update()

    def remove_conn_at(self, mm):
        c = self.conn_at(mm, max(self.tol_mm(), 0.6))
        if c:
            self.push_undo()
            self._remove(c.id)
            self.invalidate()

    
    def t_route_press(self, ev, mm):
        pad = self.pad_at(mm, max(self.tol_mm(), 0.6))
        if pad is None:
            return
        b = self.board()
        for el in b.elements.values():
            if isinstance(el, Connection) and (el.a == pad.id or el.b == pad.id):
                tr = self._routed_track(b, el)
                if tr is not None:
                    self.push_undo()
                    self._remove(tr.id)
                    self.statusMessage.emit(
                        f"Трасса снята ({tr.length():.2f} мм), линия связи осталась")
                    self.invalidate()
                    return
                tr = autotrace(b, el, RouteParams(width=self.settings["route_width"],
                                                   clearance=self.settings["route_clearance"],
                                                   grid=self.settings["route_grid"]))
                if tr:
                    self.push_undo()
                    self._add(tr)
                    self.statusMessage.emit(f"Автотрасса проложена: {len(tr.points)} узла, "
                                            f"длина {tr.length():.2f} мм")
                else:
                    self.statusMessage.emit("Автотрасса: не удалось найти свободный путь")
                return
        if self.route_first is None:
            self.route_first = pad.id
            self.statusMessage.emit("Автотрасса: укажите второй контакт")
            return
        first = self.route_first
        self.route_first = None
        if first == pad.id:
            return
        conn = Connection(a=first, b=pad.id, layer=self.active_layer)
        b.elements[conn.id] = conn
        tr = autotrace(b, conn, RouteParams(width=self.settings["route_width"],
                                             clearance=self.settings["route_clearance"],
                                             grid=self.settings["route_grid"]))
        if tr:
            self.push_undo()
            self._add(tr)
            self.statusMessage.emit(f"Автотрасса проложена: длина {tr.length():.2f} мм")
        else:
            self._remove(conn.id)
            self.invalidate()
            self.statusMessage.emit("Автотрасса: свободный путь не найден")

    def _routed_track(self, b, conn) -> Optional[Track]:
        """Автотрасса, соединяющая контакты этой связи (если она разведена)."""
        for el in b.elements.values():
            if isinstance(el, Track) and el.auto:
                pa = b.elements.get(conn.a)
                pb = b.elements.get(conn.b)
                if pa is None or pb is None:
                    continue
                for p in el.points:
                    if dist(p, _el_center(pa)) < 0.3 or dist(p, _el_center(pb)) < 0.3:
                        return el
        return None

    def _already_routed(self, b, conn) -> bool:
        for el in b.elements.values():
            if isinstance(el, Track) and el.auto:
                pa = b.elements.get(conn.a)
                pb = b.elements.get(conn.b)
                if pa is None or pb is None:
                    continue
                for p in el.points:
                    if dist(p, _el_center(pa)) < 0.3 or dist(p, _el_center(pb)) < 0.3:
                        return True
        return False

    def d_route_hover(self, ev, mm):
        self.update()

    def route_all(self):
        b = self.board()
        made = 0
        self.push_undo()
        params = RouteParams(width=self.settings["route_width"],
                             clearance=self.settings["route_clearance"],
                             grid=self.settings["route_grid"])
        for el in list(b.elements.values()):
            if isinstance(el, Connection) and not self._already_routed(b, el):
                tr = autotrace(b, el, params)
                if tr:
                    b.elements[tr.id] = tr
                    made += 1
        self.touch()
        self.invalidate()
        self.statusMessage.emit(f"Автотрасса: проложено {made} связей")

    
    def t_probe_press(self, ev, mm):
        el = self.element_at_all_layers(mm, max(self.tol_mm(), 0.5))
        if el is None:
            self.probe_ids.clear()
            self.update()
            return
        b = self.board()
        uf = nets(b, self.settings["probe_virtual"])
        root = uf.find(el.id)
        self.probe_ids = {i for i in uf.p if uf.find(i) == root}
        comp = None
        for c in b.components:
            if el.id in c.ids:
                comp = c
        label = f"Цепь: {len(self.probe_ids)} элемент(ов)"
        if comp and comp.refdes:
            label += f" · компонент {comp.refdes}"
        self.statusMessage.emit(label)
        self.update()

    
    def t_measure_press(self, ev, mm):
        self.measure_from = mm
        self.measure_to = mm

    def d_measure(self, ev, mm):
        self.measure_to = mm
        self.update()

    def r_measure(self, ev, mm):
        pass

    
    def _add(self, el: Element, select: bool = False):
        b = self.board()
        if not el.id:
            el.id = _next_id()
        b.elements[el.id] = el
        if select:
            self.select([el.id])
        self.touch()
        self.on_geometry_changed()
        self.invalidate()
        return el

    def _remove(self, el_id: str):
        b = self.board()
        b.elements.pop(el_id, None)
        for c in b.components:
            if el_id in c.ids:
                c.ids.remove(el_id)
        if el_id in self.selection:
            self.selection.remove(el_id)

    def on_geometry_changed(self):
        if self.settings["auto_fill_on_edit"] and self.settings["metallization"]:
            self.apply_fill()
        self.clear_stale_fills()

    def clear_stale_fills(self):
        b = self.board()
        keep = set()
        for el in b.elements.values():
            if isinstance(el, FillEl):
                lk = el.layer
                keep.add(lk)
        for lk in list(b.fill_layers):
            if lk not in keep and b.fill_layers.get(lk):
                for el in list(b.elements.values()):
                    if isinstance(el, FillEl) and el.layer == lk:
                        b.elements.pop(el.id, None)
                b.fill_layers[lk] = False
        self.invalidate(structural=False)

    
    def select(self, ids: Sequence[str]):
        self.selection = [i for i in ids if i in self.board().elements]
        self.selectionChanged.emit(len(self.selection))
        self.update()

    def select_toggle(self, el_id: str):
        if el_id in self.selection:
            self.selection.remove(el_id)
        else:
            self.selection.append(el_id)
        self.selectionChanged.emit(len(self.selection))
        self.update()

    def select_all(self):
        b = self.board()
        self.select([el.id for el in b.elements.values()
                     if el.kind not in ("conn", "fill") and
                     (self._visible(el.layer) or el.layer == self.active_layer)])

    def delete_selected(self):
        if not self.selection:
            return
        self.push_undo()
        for i in list(self.selection):
            self._remove(i)
        self.selection = []
        self.touch()
        self.on_geometry_changed()
        self.selectionChanged.emit(0)
        self.invalidate()

    def selection_center(self) -> Optional[Tuple[float, float]]:
        b = self.board()
        els = [b.elements[i] for i in self.selection if i in b.elements]
        boxes = [e.bbox() for e in els if e.bbox()]
        if not boxes:
            return None
        box = bbox_union(boxes, None)
        return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)

    
    def rotate_selected(self, deg: float):
        c = self.selection_center()
        if c is None:
            return
        self.push_undo()
        for i in self.selection:
            el = self.board().elements.get(i)
            if el:
                el.rotate(deg, c)
        self.touch()
        self.on_geometry_changed()
        self.invalidate()

    def mirror_selected_x(self):
        c = self.selection_center()
        if c is None:
            return
        self.push_undo()
        for i in self.selection:
            el = self.board().elements.get(i)
            if el:
                el.mirror_x(c)
        self.touch()
        self.on_geometry_changed()
        self.invalidate()

    def mirror_selected_y(self):
        c = self.selection_center()
        if c is None:
            return
        self.push_undo()
        for i in self.selection:
            el = self.board().elements.get(i)
            if el:
                el.mirror_y(c)
        self.touch()
        self.on_geometry_changed()
        self.invalidate()

    def flip_selected_layer(self):
        if not self.selection:
            return
        self.push_undo()
        for i in self.selection:
            el = self.board().elements.get(i)
            if el:
                el.flip_layer()
        self.touch()
        self.invalidate()

    def move_to_layer(self, layer: str):
        if not self.selection:
            return
        self.push_undo()
        for i in self.selection:
            el = self.board().elements.get(i)
            if el and el.kind != "pad":
                el.layer = layer
        self.touch()
        self.invalidate()

    def snap_selected_to_grid(self):
        b = self.board()
        if not self.selection:
            return
        self.push_undo()
        step = self.settings["grid_step"]
        for i in self.selection:
            el = b.elements.get(i)
            if el is None:
                continue
            if isinstance(el, (Pad, SmdPad)):
                el.x = round(el.x / step) * step
                el.y = round(el.y / step) * step
            elif el.kind == "text":
                el.x = round(el.x / step) * step
                el.y = round(el.y / step) * step
            elif isinstance(el, Track) and len(el.points) == 2:
                el.points = [(round(x / step) * step, round(y / step) * step) for x, y in el.points]
        self.touch()
        self.invalidate()

    def array_selected(self, count: int, dx: float, dy: float, radial: bool = False,
                       radius: float = 0.0, angle_step: float = 0.0, start: Optional[Tuple[float, float]] = None):
        b = self.board()
        ids = [i for i in self.selection if i in b.elements]
        if not ids or count < 2:
            return
        self.push_undo()
        origin = start or self.selection_center() or (0, 0)
        for n in range(1, count):
            new_ids = []
            for i in ids:
                el = b.elements[i].copy()
                if radial:
                    el.rotate(angle_step * n, origin)
                else:
                    el.move(dx * n, dy * n)
                b.elements[el.id] = el
                new_ids.append(el.id)
            if radial:
                ids = new_ids
        self.touch()
        self.on_geometry_changed()
        self.invalidate()

    def align_selected(self, mode: str):
        els = [self.board().elements[i] for i in self.selection if i in self.board().elements]
        if len(els) < 2:
            return
        self.push_undo()
        boxes = [(el, el.bbox()) for el in els if el.bbox()]
        if mode == "left":
            x = min(b[0] for _, b in boxes)
            for el, b in boxes:
                el.move(x - b[0], 0)
        elif mode == "right":
            x = max(b[2] for _, b in boxes)
            for el, b in boxes:
                el.move(x - b[2], 0)
        elif mode == "top":
            y = max(b[3] for _, b in boxes)
            for el, b in boxes:
                el.move(0, y - b[3])
        elif mode == "bottom":
            y = min(b[1] for _, b in boxes)
            for el, b in boxes:
                el.move(0, y - b[1])
        elif mode == "hcenter":
            x = (min(b[0] for _, b in boxes) + max(b[2] for _, b in boxes)) / 2
            for el, b in boxes:
                el.move(x - (b[0] + b[2]) / 2, 0)
        elif mode == "vcenter":
            y = (min(b[1] for _, b in boxes) + max(b[3] for _, b in boxes)) / 2
            for el, b in boxes:
                el.move(0, y - (b[1] + b[3]) / 2)
        self.touch()
        self.on_geometry_changed()
        self.invalidate()

    
    def copy_selected(self) -> List[Element]:
        b = self.board()
        els = [b.elements[i].copy() for i in self.selection if i in b.elements]
        self.clipboard = els
        return els

    def cut_selected(self):
        self.copy_selected()
        self.delete_selected()

    def paste(self, dx: float = 2.0, dy: float = 2.0):
        self.push_undo()
        ids = []
        for el in getattr(self, "clipboard", []):
            c = el.copy()
            c.move(dx, dy)
            self.board().elements[c.id] = c
            ids.append(c.id)
        self.select(ids)
        self.touch()
        self.invalidate()

    def join_tracks(self):
        """«Соединить линию» — объединение двух трасс в общий конец."""
        els = [self.board().elements[i] for i in self.selection if i in self.board().elements]
        tracks = [e for e in els if isinstance(e, Track)]
        if len(tracks) < 2:
            return
        self.push_undo()
        tracks.sort(key=lambda t: -t.length())
        main = tracks[0]
        for t in tracks[1:]:
            ends = [(main.points[0], main.points[1]),
                    (main.points[-1], main.points[-2])]
            best = None
            for pt in t.points:
                for i, (e, n) in enumerate(ends):
                    d = dist(pt, e)
                    if best is None or d < best[0]:
                        best = (d, pt, i)
            if best:
                _, pt, i = best
                e, n = ends[i]
                d = dist(pt, e)
                if d < 1e-6:
                    if i == 0:
                        main.points = t.points[:-1] + main.points
                    else:
                        main.points = main.points + t.points[1:]
                    self._remove(t.id)
                    if i == 0:
                        main.points.reverse()
                        main.points = [p for p in main.points]
                    self.selection = [main.id]
        self.touch()
        self.on_geometry_changed()
        self.invalidate()

    
    def snapshot(self) -> dict:
        b = self.board()
        return {"elements": copy.deepcopy(b.elements),
                "components": copy.deepcopy(b.components),
                "fills": dict(b.fill_layers)}

    def restore(self, snap: dict):
        b = self.board()
        b.elements = copy.deepcopy(snap["elements"])
        b.components = copy.deepcopy(snap["components"])
        b.fill_layers = dict(snap["fills"])
        self.selection = [i for i in self.selection if i in b.elements]
        self.probe_ids.clear()
        self.selectionChanged.emit(len(self.selection))
        self.invalidate()
        self.viewChanged.emit()

    def push_undo(self):
        self.undo_stack.append(self.snapshot())
        depth = int(self.settings.get("undo_depth", 40))
        if len(self.undo_stack) > depth:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def undo(self):
        if not self.undo_stack:
            return False
        self.redo_stack.append(self.snapshot())
        self.restore(self.undo_stack.pop())
        self.touch()
        return True

    def redo(self):
        if not self.redo_stack:
            return False
        self.undo_stack.append(self.snapshot())
        self.restore(self.redo_stack.pop())
        self.touch()
        return True

    
    def set_layer(self, layer: str):
        if layer in LAYER_BY_KEY:
            self.active_layer = layer
            self.update()

    def toggle_layer_visible(self, layer: str):
        b = self.board()
        b.visible[layer] = not b.visible.get(layer, True)
        self.invalidate(structural=False)

    def flip_side(self):
        b = self.board()
        if b.multilayer:
            cur = self.active_layer
            mapping = {TOP_KEY: BOTTOM_KEY, BOTTOM_KEY: TOP_KEY, "K1": "K2", "K2": "K1",
                       "V1": "V2", "V2": "V1"}
            self.active_layer = mapping.get(cur, cur)
        self.update()

    
    def apply_fill(self, layers: Optional[Sequence[str]] = None):
        b = self.board()
        targets = list(layers or [lk for lk in COPPER_KEYS
                                  if (b.multilayer or lk in ("M1", "M2")) and b.visible.get(lk, True)])
        self.push_undo()
        t0 = time.time()
        total = 0
        for lk in targets:
            for el in list(b.elements.values()):
                if isinstance(el, FillEl) and el.layer == lk:
                    b.elements.pop(el.id, None)
            f = compute_fill(b, lk, clearance=self.settings["clearance"],
                             thermal_gap=self.settings["thermal_gap"],
                             spoke_width=self.settings["thermal_spoke"],
                             spoke_dirs=tuple(self.settings["thermal_dirs"]),
                             per_element_clearance=self.settings["fill_per_element"])
            if f.rects:
                b.elements[f.id] = f
                b.fill_layers[lk] = True
                total += len(f.rects)
            else:
                b.fill_layers[lk] = False
        self.touch()
        self.invalidate()
        dt = time.time() - t0
        self.statusMessage.emit(f"Металлизация: {total} участков за {dt:.1f} с "
                                f"({'внимание: проверьте тонкие мостики!' if total else 'пусто'})")

    def clear_fills(self):
        self.push_undo()
        b = self.board()
        for el in list(b.elements.values()):
            if isinstance(el, FillEl):
                b.elements.pop(el.id, None)
        b.fill_layers = {}
        self.touch()
        self.invalidate()
        self.statusMessage.emit("Металлизация снята")

    def toggle_metallization(self):
        s = self.settings
        s["metallization"] = not s["metallization"]
        if s["metallization"]:
            self.apply_fill()
        else:
            self.clear_fills()
        self.viewChanged.emit()

    
    def run_drc(self, window: bool = False) -> List:
        box = None
        if window:
            f = self.field_rect()
            box = (self.offset.x(), self.offset.y(),
                   self.offset.x() + f.width() / self.scale,
                   self.offset.y() + f.height() / self.scale)
        errs = drc_mod.check(self.board(), self.settings["drc_rules"], window=box)
        self.drc_errors = errs
        return errs

    def jump_to_error(self, err):
        if err.box:
            self._zoom_to_box(err.box, pad=14)

    
    def start_macro_place(self, macro: Macro):
        self.placed_macro = macro
        self._placed_name = macro.name
        self.set_tool("cursor")
        self.statusMessage.emit(f"Размещение макроса «{macro.name}»: ЛКМ — поставить "
                                f"(можно много раз), ПКМ или Esc — отменить")

    def place_macro_at(self, pos: Tuple[float, float]):
        if self.placed_macro is None:
            return
        self.push_undo()
        els = self.placed_macro.instance(pos[0], pos[1], self.macro_rot, self.macro_bottom)
        ids = []
        for el in els:
            el.id = _next_id()
            self.board().elements[el.id] = el
            ids.append(el.id)
        name = self.placed_macro.name or self._placed_name
        self.select(ids)
        self.touch()
        self.invalidate()
        self.statusMessage.emit(f"Макрос «{name}» размещён · ЛКМ — ещё один, "
                                f"Esc — закончить")

    def cancel_macro_place(self, message: str = "Размещение макроса отменено"):
        if self.placed_macro is None:
            return
        self.placed_macro = None
        self.preview.clear()
        self.temp_points.clear()
        self.marquee = None
        self.statusMessage.emit(message)
        self.update()

    
    def cancel_current(self, message: str = "Действие отменено (Esc)"):
        """Сбросить всё незавершённое: макрос, точки, рамку, связи, измерение."""
        had = (self.placed_macro is not None or bool(self.temp_points) or
               bool(self.preview) or self.marquee is not None or
               self.conn_first is not None or self.route_first is not None)
        self.temp_points.clear()
        self.preview.clear()
        self.conn_first = None
        self.route_first = None
        self.measure_from = None
        self.measure_to = None
        self.marquee = None
        if self.placed_macro is not None:
            self.placed_macro = None
            self.statusMessage.emit("Размещение макроса отменено (Esc)")
        elif had:
            self.statusMessage.emit(message)
        self.set_tool("cursor")
        self.update()

    def keyPressEvent(self, ev):
        key = ev.key()
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            if self.placed_macro is not None:
                ang = {Qt.Key.Key_Left: -90.0, Qt.Key.Key_Right: 90.0,
                       Qt.Key.Key_Up: 90.0, Qt.Key.Key_Down: -90.0}[key]
                self.macro_rot = (self.macro_rot + ang) % 360
                self.statusMessage.emit(f"Поворот макроса «{self._placed_name}»: "
                                        f"{self.macro_rot:g}° (Esc — отмена)")
                self.update()
                return
            if self.selection:
                ang = {Qt.Key.Key_Left: -90.0, Qt.Key.Key_Right: 90.0,
                       Qt.Key.Key_Up: 90.0, Qt.Key.Key_Down: -90.0}[key]
                self.rotate_selected(ang)
                return
            step = self.settings["grid_step"] * self.scale
            if key == Qt.Key.Key_Left:
                self.pan_px(step, 0)
            elif key == Qt.Key.Key_Right:
                self.pan_px(-step, 0)
            elif key == Qt.Key.Key_Up:
                self.pan_px(0, step)
            else:
                self.pan_px(0, -step)
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.tool == "poly":
                self.close_polygon()
                return
            if self.tool == "track":
                self.finish_track()
                return
        if key == Qt.Key.Key_Escape:
            self.cancel_current()
            return
        if key == Qt.Key.Key_Delete:
            self.delete_selected()
            return
        super().keyPressEvent(ev)



_ids = [0]


def _next_id() -> str:
    _ids[0] += 1
    return f"e{_ids[0]}x{int(time.time() * 1000) % 100000}"


def _el_center(el: Element) -> Tuple[float, float]:
    if isinstance(el, (Pad, SmdPad)):
        return (el.x, el.y)
    b = el.bbox()
    if b is None:
        return (0.0, 0.0)
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def _draw_bubble(p: QPainter, at: QPointF, text: str):
    f = QFont("Segoe UI")
    f.setPixelSize(10)
    p.setFont(f)
    rect = QRectF(at.x(), at.y(), 0, 0)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, 170))
    for i, line in enumerate(text.split("\n")):
        w = p.fontMetrics().horizontalAdvance(line) + 12
        rect = QRectF(at.x() + 8, at.y() + i * 16, w, 16)
        p.drawRoundedRect(rect, 4, 4)
        p.setPen(QColor("#e0e2e8"))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, line)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 170))
