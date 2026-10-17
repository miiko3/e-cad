"""Модель документа e-cad: слои, элементы, платы, компоненты, связность, сохранение."""
from __future__ import annotations

import copy
import itertools
import json
import math
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .geom import (MIL, arc_points, bbox_grow, bbox_of, bbox_overlap, bbox_union,
                   dist, poly_length, pt_seg_dist, rot_pt, segments_intersect)

# --------------------------------------------------------------- слои
@dataclass(frozen=True)
class LayerDef:
    key: str
    name: str
    short: str
    kind: str          # copper | silk | outline
    top: bool          # отображается «сверху» (не зеркалится)
    default_color: str
    conductive: bool = False
    maskable: bool = False


LAYERS: Tuple[LayerDef, ...] = (
    LayerDef("M1", "М1 — верхний проводящий (медь, Top)", "М1", "copper", True, "#c8452d", True, True),
    LayerDef("K1", "К1 — верхняя маркировка (шёлкография)", "К1", "silk", True, "#e8e8e8"),
    LayerDef("V1", "В1 — верхний внутренний проводящий", "В1", "copper", True, "#2f8f6d", True, True),
    LayerDef("V2", "В2 — нижний внутренний проводящий", "В2", "copper", False, "#2f7fb0", True, True),
    LayerDef("M2", "М2 — нижний проводящий (Bottom)", "М2", "copper", False, "#2f6fd0", True, True),
    LayerDef("K2", "К2 — нижняя маркировка", "К2", "silk", False, "#9aa3ad"),
    LayerDef("O", "О — контур платы и вырезы", "О", "outline", True, "#d4c04a"),
)
LAYER_BY_KEY = {l.key: l for l in LAYERS}
COPPER_KEYS = [l.key for l in LAYERS if l.conductive]
SILK_KEYS = [l.key for l in LAYERS if l.kind == "silk"]
INNER_KEYS = ("V1", "V2")
TOP_KEY, BOTTOM_KEY = "M1", "M2"
ALL_LAYERS = [l.key for l in LAYERS]
TOP_ONLY = (TOP_KEY, "K1")
BOTTOM_ONLY = (BOTTOM_KEY, "K2")


# --------------------------------------------------------------- элементы
_ids = itertools.count(1)


@dataclass
class Element:
    id: str = field(default_factory=lambda: f"e{next(_ids)}")
    layer: str = TOP_KEY
    mask_open: bool = False
    negative: bool = False
    locked: bool = False
    kind: str = "track"

    # --- интерфейс -----------------------------------------------------
    def bbox(self):
        raise NotImplementedError

    def hit(self, p, tol: float) -> bool:
        raise NotImplementedError

    def copy(self):
        c = copy.deepcopy(self)
        c.id = ""
        return c

    def move(self, dx: float, dy: float):
        raise NotImplementedError

    def rotate(self, deg: float, center: Tuple[float, float]):
        raise NotImplementedError

    def mirror_x(self, center: Tuple[float, float]):
        raise NotImplementedError

    def mirror_y(self, center: Tuple[float, float]):
        raise NotImplementedError

    def flip_layer(self):
        if self.layer in TOP_ONLY:
            self.layer = "K1"
        elif self.layer == "K1":
            self.layer = TOP_KEY
        elif self.layer in BOTTOM_ONLY:
            self.layer = "K2"
        elif self.layer == "K2":
            self.layer = BOTTOM_KEY
        elif self.layer == "V1":
            self.layer = "V2"
        elif self.layer == "V2":
            self.layer = "V1"

    def outline_points(self) -> List[Tuple[float, float]]:
        return []

    # --- сериализация ---------------------------------------------------
    def to_dict(self) -> dict:
        d = {"id": self.id, "kind": self.kind, "layer": self.layer}
        if self.mask_open:
            d["mask_open"] = True
        if self.negative:
            d["neg"] = True
        if self.locked:
            d["locked"] = True
        d.update(self._fields())
        return d

    def _fields(self) -> dict:
        return {}

    @staticmethod
    def from_dict(d: dict) -> "Element":
        kind = d.get("kind", "track")
        cls = ELEMENT_CLASSES.get(kind, Track)
        el = cls()                      # все поля со значениями по умолчанию
        if d.get("id"):
            el.id = d["id"]
        el.layer = d.get("layer", TOP_KEY)
        el.kind = kind
        el.mask_open = bool(d.get("mask_open", False))
        el.negative = bool(d.get("neg", False))
        el.locked = bool(d.get("locked", False))
        el._load(d)
        return el

    def _load(self, d: dict):
        pass

    @property
    def type_name(self) -> str:
        return TYPE_NAMES.get(self.kind, self.kind)


@dataclass
class Track(Element):
    kind: str = "track"
    points: List[Tuple[float, float]] = field(default_factory=list)
    width: float = 0.4
    square_ends: bool = False
    imax: float = 0.0
    rubber: bool = False
    auto: bool = False

    def _fields(self):
        return {"points": [list(p) for p in self.points], "w": self.width,
                "sq": self.square_ends, "imax": self.imax, "rubber": self.rubber,
                "auto": self.auto}

    def _load(self, d):
        self.points = [tuple(p) for p in d.get("points", [])]
        self.width = float(d.get("w", 0.4))
        self.square_ends = bool(d.get("sq", False))
        self.imax = float(d.get("imax", 0.0))
        self.rubber = bool(d.get("rubber", False))
        self.auto = bool(d.get("auto", False))

    def length(self) -> float:
        return poly_length(self.points)

    def bbox(self):
        if not self.points:
            return None
        return bbox_grow(bbox_of(self.points), self.width / 2.0)

    def hit(self, p, tol):
        if not self.points:
            return False
        if len(self.points) == 1:
            return dist(p, self.points[0]) <= self.width / 2.0 + tol
        for i in range(len(self.points) - 1):
            if pt_seg_dist(p, self.points[i], self.points[i + 1]) <= self.width / 2.0 + tol:
                return True
        return False

    def outline_points(self):
        return list(self.points)

    def move(self, dx, dy):
        self.points = [(x + dx, y + dy) for x, y in self.points]

    def rotate(self, deg, center):
        self.points = [rot_pt(p, center, deg) for p in self.points]

    def mirror_x(self, center):
        self.points = [(2 * center[0] - x, y) for x, y in self.points]

    def mirror_y(self, center):
        self.points = [(x, 2 * center[1] - y) for x, y in self.points]


@dataclass
class Pad(Element):
    """Контакт сквозного монтажа (THT)."""
    kind: str = "pad"
    x: float = 0.0
    y: float = 0.0
    pad_dia: float = 1.8
    hole_dia: float = 0.9
    shape: str = "circle"      # circle | rect | oval | rounded
    size: Tuple[float, float] = (1.8, 1.8)
    plated: bool = True
    thermal: bool = False
    thermal_layers: Dict[str, bool] = field(default_factory=dict)
    clearance: float = 0.25
    layers: List[str] = field(default_factory=list)

    def _fields(self):
        d = {"x": self.x, "y": self.y, "pd": self.pad_dia, "hd": self.hole_dia,
             "shape": self.shape, "size": list(self.size), "plated": self.plated,
             "thermal": self.thermal, "clr": self.clearance}
        if self.thermal_layers:
            d["tl"] = dict(self.thermal_layers)
        if self.layers:
            d["layers"] = list(self.layers)
        return d

    def _load(self, d):
        self.x = float(d.get("x", 0))
        self.y = float(d.get("y", 0))
        self.pad_dia = float(d.get("pd", 1.8))
        self.hole_dia = float(d.get("hd", 0.9))
        self.shape = d.get("shape", "circle")
        self.size = tuple(d.get("size", (self.pad_dia, self.pad_dia)))
        self.plated = bool(d.get("plated", True))
        self.thermal = bool(d.get("thermal", False))
        self.clearance = float(d.get("clr", 0.25))
        self.thermal_layers = dict(d.get("tl", {}))
        self.layers = list(d.get("layers", []))

    def copper_layers(self) -> List[str]:
        if self.layers:
            return [k for k in ALL_LAYERS if k in self.layers]
        return list(COPPER_KEYS)

    def outer(self) -> Tuple[float, float]:
        if self.shape == "circle":
            return (self.pad_dia, self.pad_dia)
        return tuple(self.size)

    def bbox(self):
        w, h = self.outer()
        return (self.x - w / 2, self.y - h / 2, self.x + w / 2, self.y + h / 2)

    def hit(self, p, tol):
        b = self.bbox()
        if not (b[0] - tol <= p[0] <= b[2] + tol and b[1] - tol <= p[1] <= b[3] + tol):
            return False
        dx = abs(p[0] - self.x)
        dy = abs(p[1] - self.y)
        w, h = self.outer()
        if self.shape == "circle":
            return math.hypot(dx, dy) <= w / 2 + tol
        if self.shape in ("oval", "rounded"):
            r = min(w, h) / 2 if self.shape == "oval" else min(w, h) * 0.25
            return (dx <= w / 2 + tol and dy <= h / 2 + tol and
                    math.hypot(max(dx - (w / 2 - r), 0), max(dy - (h / 2 - r), 0)) <= r + tol)
        return True

    def outline_points(self):
        w, h = self.outer()
        if self.shape == "circle":
            return arc_points(self.x, self.y, w / 2, 0, 360, 30)
        return [(self.x - w / 2, self.y - h / 2), (self.x + w / 2, self.y - h / 2),
                (self.x + w / 2, self.y + h / 2), (self.x - w / 2, self.y + h / 2)]

    def move(self, dx, dy):
        self.x += dx
        self.y += dy

    def rotate(self, deg, center):
        self.x, self.y = rot_pt((self.x, self.y), center, deg)

    def mirror_x(self, center):
        self.x = 2 * center[0] - self.x

    def mirror_y(self, center):
        self.y = 2 * center[1] - self.y


@dataclass
class SmdPad(Element):
    kind: str = "smd"
    x: float = 0.0
    y: float = 0.0
    w: float = 1.0
    h: float = 1.5
    shape: str = "rect"        # rect | roundrect | circle | oval
    thermal: bool = False
    clearance: float = 0.2

    def _fields(self):
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h,
                "shape": self.shape, "thermal": self.thermal, "clr": self.clearance}

    def _load(self, d):
        self.x = float(d.get("x", 0))
        self.y = float(d.get("y", 0))
        self.w = float(d.get("w", 1.0))
        self.h = float(d.get("h", 1.5))
        self.shape = d.get("shape", "rect")
        self.thermal = bool(d.get("thermal", False))
        self.clearance = float(d.get("clr", 0.2))

    def bbox(self):
        return (self.x - self.w / 2, self.y - self.h / 2, self.x + self.w / 2, self.y + self.h / 2)

    def hit(self, p, tol):
        b = self.bbox()
        if not (b[0] - tol <= p[0] <= b[2] + tol and b[1] - tol <= p[1] <= b[3] + tol):
            return False
        if self.shape == "circle":
            return math.hypot(p[0] - self.x, p[1] - self.y) <= self.w / 2 + tol
        return True

    def outline_points(self):
        if self.shape == "circle":
            return arc_points(self.x, self.y, self.w / 2, 0, 360, 30)
        return [(self.x - self.w / 2, self.y - self.h / 2), (self.x + self.w / 2, self.y - self.h / 2),
                (self.x + self.w / 2, self.y + self.h / 2), (self.x - self.w / 2, self.y + self.h / 2)]

    def move(self, dx, dy):
        self.x += dx
        self.y += dy

    def rotate(self, deg, center):
        self.x, self.y = rot_pt((self.x, self.y), center, deg)

    def mirror_x(self, center):
        self.x = 2 * center[0] - self.x

    def mirror_y(self, center):
        self.y = 2 * center[1] - self.y


@dataclass
class CircleEl(Element):
    kind: str = "circle"
    cx: float = 0.0
    cy: float = 0.0
    r: float = 1.0
    width: float = 0.3
    a0: float = 0.0
    a1: float = 360.0
    filled: bool = False

    def _fields(self):
        return {"cx": self.cx, "cy": self.cy, "r": self.r, "w": self.width,
                "a0": self.a0, "a1": self.a1, "fill": self.filled}

    def _load(self, d):
        self.cx = float(d.get("cx", 0))
        self.cy = float(d.get("cy", 0))
        self.r = float(d.get("r", 1))
        self.width = float(d.get("w", 0.3))
        self.a0 = float(d.get("a0", 0))
        self.a1 = float(d.get("a1", 360))
        self.filled = bool(d.get("fill", False))

    def is_arc(self) -> bool:
        return abs((self.a1 - self.a0) % 360.0) > 1e-6

    def bbox(self):
        full = abs((self.a1 - self.a0) % 360.0) <= 1e-6
        if full or self.filled:
            r = self.r + (0 if self.filled else self.width / 2)
            return (self.cx - r, self.cy - r, self.cx + r, self.cy + r)
        pts = arc_points(self.cx, self.cy, self.r, self.a0, self.a1, 4)
        return bbox_grow(bbox_of(pts), self.width / 2)

    def hit(self, p, tol):
        if self.filled:
            return math.hypot(p[0] - self.cx, p[1] - self.cy) <= self.r + tol
        pts = arc_points(self.cx, self.cy, self.r, self.a0, self.a1, 3)
        for i in range(len(pts) - 1):
            if pt_seg_dist(p, pts[i], pts[i + 1]) <= self.width / 2 + tol:
                return True
        return False

    def outline_points(self):
        if self.filled:
            return arc_points(self.cx, self.cy, self.r, 0, 360, 30)
        return arc_points(self.cx, self.cy, self.r, self.a0, self.a1, 10)

    def move(self, dx, dy):
        self.cx += dx
        self.cy += dy

    def rotate(self, deg, center):
        self.cx, self.cy = rot_pt((self.cx, self.cy), center, deg)
        self.a0 = (self.a0 + deg) % 360.0
        self.a1 = (self.a1 + deg) % 360.0

    def mirror_x(self, center):
        self.cx = 2 * center[0] - self.cx
        self.a0, self.a1 = 180.0 - self.a1, 180.0 - self.a0

    def mirror_y(self, center):
        self.cy = 2 * center[1] - self.cy
        self.a0, self.a1 = -self.a1, -self.a0


@dataclass
class PolygonEl(Element):
    kind: str = "poly"
    points: List[Tuple[float, float]] = field(default_factory=list)
    contour: float = 0.25
    hatched: bool = False
    hatch_pitch: float = 0.6
    hatch_width: float = 0.15

    def _fields(self):
        return {"points": [list(p) for p in self.points], "cw": self.contour,
                "grid": self.hatched, "pitch": self.hatch_pitch, "hw": self.hatch_width}

    def _load(self, d):
        self.points = [tuple(p) for p in d.get("points", [])]
        self.contour = float(d.get("cw", 0.25))
        self.hatched = bool(d.get("grid", False))
        self.hatch_pitch = float(d.get("pitch", 0.6))
        self.hatch_width = float(d.get("hw", 0.15))

    def bbox(self):
        if not self.points:
            return None
        return bbox_grow(bbox_of(self.points), self.contour / 2.0)

    def hit(self, p, tol):
        if len(self.points) < 2:
            return False
        n = len(self.points)
        for i in range(n):
            if pt_seg_dist(p, self.points[i], self.points[(i + 1) % n]) <= self.contour / 2 + tol:
                return True
        return False

    def outline_points(self):
        return list(self.points)

    def move(self, dx, dy):
        self.points = [(x + dx, y + dy) for x, y in self.points]

    def rotate(self, deg, center):
        self.points = [rot_pt(p, center, deg) for p in self.points]

    def mirror_x(self, center):
        self.points = [(2 * center[0] - x, y) for x, y in self.points]

    def mirror_y(self, center):
        self.points = [(x, 2 * center[1] - y) for x, y in self.points]


@dataclass
class TextEl(Element):
    kind: str = "text"
    x: float = 0.0
    y: float = 0.0
    text: str = ""
    height: float = 1.6
    thickness: float = 0.2
    style: int = 0            # 0..8
    angle: float = 0.0
    mirror: str = ""          # "" | "X" | "Y"
    auto_num: bool = False
    prefix: str = "R"

    def _fields(self):
        return {"x": self.x, "y": self.y, "t": self.text, "h": self.height,
                "th": self.thickness, "st": self.style, "ang": self.angle,
                "mir": self.mirror, "auto": self.auto_num, "pfx": self.prefix}

    def _load(self, d):
        self.x = float(d.get("x", 0))
        self.y = float(d.get("y", 0))
        self.text = d.get("t", "")
        self.height = float(d.get("h", 1.6))
        self.thickness = float(d.get("th", 0.2))
        self.style = int(d.get("st", 0))
        self.angle = float(d.get("ang", 0))
        self.mirror = d.get("mir", "")
        self.auto_num = bool(d.get("auto", False))
        self.prefix = d.get("pfx", "R")

    def display_text(self) -> str:
        return self.text or f"{self.prefix}?"

    def bbox(self):
        w = max(1.0, len(self.display_text())) * self.height * 0.62
        return (self.x - self.thickness, self.y - self.height * 0.8,
                self.x + w, self.y + self.height * 0.5)

    def hit(self, p, tol):
        b = self.bbox()
        return (b[0] - tol <= p[0] <= b[2] + tol) and (b[1] - tol <= p[1] <= b[3] + tol)

    def move(self, dx, dy):
        self.x += dx
        self.y += dy

    def rotate(self, deg, center):
        self.x, self.y = rot_pt((self.x, self.y), center, deg)
        self.angle = (self.angle + deg) % 360.0

    def mirror_x(self, center):
        self.x = 2 * center[0] - self.x
        self.mirror = {"X": "Y", "Y": "X"}.get(self.mirror, self.mirror)

    def mirror_y(self, center):
        self.y = 2 * center[1] - self.y
        self.mirror = {"X": "Y", "Y": "X"}.get(self.mirror, self.mirror)


@dataclass
class RectEl(Element):
    kind: str = "rect"
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0
    width: float = 0.25
    filled: bool = False

    def _fields(self):
        return {"x0": self.x0, "y0": self.y0, "x1": self.x1, "y1": self.y1,
                "w": self.width, "fill": self.filled}

    def _load(self, d):
        self.x0 = float(d.get("x0", 0))
        self.y0 = float(d.get("y0", 0))
        self.x1 = float(d.get("x1", 0))
        self.y1 = float(d.get("y1", 0))
        self.width = float(d.get("w", 0.25))
        self.filled = bool(d.get("fill", False))

    def points(self) -> List[Tuple[float, float]]:
        return [(self.x0, self.y0), (self.x1, self.y0), (self.x1, self.y1), (self.x0, self.y1)]

    def bbox(self):
        return bbox_grow((min(self.x0, self.x1), min(self.y0, self.y1),
                          max(self.x0, self.x1), max(self.y0, self.y1)),
                         0 if self.filled else self.width / 2)

    def hit(self, p, tol):
        b = self.bbox()
        if not (b[0] - tol <= p[0] <= b[2] + tol and b[1] - tol <= p[1] <= b[3] + tol):
            return False
        if self.filled:
            return (min(self.x0, self.x1) <= p[0] <= max(self.x0, self.x1)
                    and min(self.y0, self.y1) <= p[1] <= max(self.y0, self.y1))
        pts = self.points()
        for i in range(4):
            if pt_seg_dist(p, pts[i], pts[(i + 1) % 4]) <= self.width / 2 + tol:
                return True
        return False

    def outline_points(self):
        return self.points()

    def move(self, dx, dy):
        self.x0 += dx
        self.y0 += dy
        self.x1 += dx
        self.y1 += dy

    def rotate(self, deg, center):
        pts = [rot_pt(p, center, deg) for p in self.points()]
        xs = [q[0] for q in pts]
        ys = [q[1] for q in pts]
        self.x0, self.x1 = min(xs), max(xs)
        self.y0, self.y1 = min(ys), max(ys)

    def mirror_x(self, center):
        self.x0, self.x1 = 2 * center[0] - self.x0, 2 * center[0] - self.x1

    def mirror_y(self, center):
        self.y0, self.y1 = 2 * center[1] - self.y0, 2 * center[1] - self.y1


@dataclass
class Connection(Element):
    """Виртуальная линия связи между двумя контактами."""
    kind: str = "conn"
    a: str = ""
    b: str = ""
    net: str = ""
    layer: str = TOP_KEY

    def _fields(self):
        return {"a": self.a, "b": self.b, "net": self.net}

    def _load(self, d):
        self.a = d.get("a", "")
        self.b = d.get("b", "")
        self.net = d.get("net", "")

    def bbox(self):
        return None

    def hit(self, p, tol):
        return False

    def move(self, dx, dy):
        pass

    def rotate(self, deg, center):
        pass

    def mirror_x(self, center):
        pass

    def mirror_y(self, center):
        pass


@dataclass
class FillEl(Element):
    """Результат авто-земли: список прямоугольников."""
    kind: str = "fill"
    rects: List[List[float]] = field(default_factory=list)
    no_drc: bool = True
    cell: float = 0.0          # шаг растра, из которого собраны прямоугольники

    def _fields(self):
        return {"rects": self.rects, "no_drc": self.no_drc, "cell": self.cell}

    def _load(self, d):
        self.rects = [list(r) for r in d.get("rects", [])]
        self.no_drc = bool(d.get("no_drc", True))
        self.cell = float(d.get("cell", 0.0))

    def bbox(self):
        if not self.rects:
            return None
        return (min(r[0] for r in self.rects), min(r[1] for r in self.rects),
                max(r[2] for r in self.rects), max(r[3] for r in self.rects))

    def hit(self, p, tol):
        for r in self.rects:
            if r[0] - tol <= p[0] <= r[2] + tol and r[1] - tol <= p[1] <= r[3] + tol:
                return True
        return False

    def move(self, dx, dy):
        for r in self.rects:
            r[0] += dx
            r[1] += dy
            r[2] += dx
            r[3] += dy

    def rotate(self, deg, center):
        for r in self.rects:
            x0, y0 = rot_pt((r[0], r[1]), center, deg)
            x1, y1 = rot_pt((r[2], r[3]), center, deg)
            r[:] = [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]

    def mirror_x(self, center):
        for r in self.rects:
            r[0], r[2] = 2 * center[0] - r[0], 2 * center[0] - r[2]

    def mirror_y(self, center):
        for r in self.rects:
            r[1], r[3] = 2 * center[1] - r[1], 2 * center[1] - r[3]


ELEMENT_CLASSES = {
    "track": Track, "pad": Pad, "smd": SmdPad, "circle": CircleEl,
    "poly": PolygonEl, "text": TextEl, "rect": RectEl, "conn": Connection,
    "fill": FillEl,
}
TYPE_NAMES = {
    "track": "Дорожка", "pad": "Контакт THT", "smd": "Контакт SMD",
    "circle": "Круг/дуга", "poly": "Полигон", "text": "Текст",
    "rect": "Прямоугольник", "conn": "Линия связи", "fill": "Металлизация",
}


# --------------------------------------------------------------- компонент
@dataclass
class Component:
    ids: List[str] = field(default_factory=list)
    refdes: str = ""
    value: str = ""
    comment: str = ""
    side: str = "top"
    layer: str = TOP_KEY
    rotation: float = 0.0
    x: float = 0.0
    y: float = 0.0
    footprint: str = ""

    def to_dict(self):
        return {"ids": self.ids, "refdes": self.refdes, "value": self.value,
                "comment": self.comment, "side": self.side, "layer": self.layer,
                "rot": self.rotation, "x": self.x, "y": self.y, "fp": self.footprint}

    @staticmethod
    def from_dict(d):
        c = Component()
        c.ids = list(d.get("ids", []))
        c.refdes = d.get("refdes", "")
        c.value = d.get("value", "")
        c.comment = d.get("comment", "")
        c.side = d.get("side", "top")
        c.layer = d.get("layer", TOP_KEY)
        c.rotation = float(d.get("rot", 0))
        c.x = float(d.get("x", 0))
        c.y = float(d.get("y", 0))
        c.footprint = d.get("fp", "")
        return c


# ------------------------------------------------------- плата / документ
@dataclass
class Board:
    name: str = "Плата 1"
    width: float = 100.0
    height: float = 80.0
    origin: Tuple[float, float] = (10.0, 10.0)
    outline_round: float = 0.0
    multilayer: bool = False
    elements: Dict[str, Element] = field(default_factory=dict)
    components: List[Component] = field(default_factory=list)
    visible: Dict[str, bool] = field(default_factory=lambda: {k: True for k in ALL_LAYERS})
    fill_layers: Dict[str, bool] = field(default_factory=dict)
    colors: Dict[str, str] = field(default_factory=dict)

    def to_dict(self):
        return {"name": self.name, "width": self.width, "height": self.height,
                "origin": list(self.origin), "round": self.outline_round,
                "multilayer": self.multilayer,
                "elements": [e.to_dict() for e in self.elements.values()],
                "components": [c.to_dict() for c in self.components],
                "visible": self.visible, "fills": self.fill_layers, "colors": self.colors}

    @staticmethod
    def from_dict(d):
        b = Board()
        b.name = d.get("name", "Плата 1")
        b.width = float(d.get("width", 100))
        b.height = float(d.get("height", 80))
        b.origin = tuple(d.get("origin", (10, 10)))
        b.outline_round = float(d.get("round", 0))
        b.multilayer = bool(d.get("multilayer", False))
        for ed in d.get("elements", []):
            el = Element.from_dict(ed)
            b.elements[el.id] = el
        for cd in d.get("components", []):
            b.components.append(Component.from_dict(cd))
        b.visible.update(d.get("visible", {}))
        b.fill_layers.update(d.get("fills", {}))
        b.colors.update(d.get("colors", {}))
        return b

    def outline_rect(self):
        ox, oy = self.origin
        return (ox, oy, ox + self.width, oy + self.height)

    def outline_points(self) -> List[Tuple[float, float]]:
        x0, y0, x1, y1 = self.outline_rect()
        if self.outline_round > 0:
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            return arc_points(cx, cy, self.outline_round / 2, 0, 360, 15)
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

    def elements_on(self, layer: Optional[str] = None):
        for el in self.elements.values():
            if el.kind == "conn":
                continue
            if layer is None or el.layer == layer:
                yield el

    def bbox(self):
        return self.outline_rect()


@dataclass
class Document:
    boards: List[Board] = field(default_factory=list)
    active: int = 0
    file: Optional[str] = None
    dirty: bool = False
    author: str = ""
    comment: str = ""
    template_top: Optional[str] = None
    template_bottom: Optional[str] = None
    settings: Dict = field(default_factory=dict)

    def board(self) -> Board:
        if not self.boards:
            self.boards.append(Board())
        return self.boards[self.active]

    def new_board(self, template: int = 0, w=100.0, h=80.0, margin=10.0,
                  round_dia=0.0, name="Плата") -> Board:
        if template == 2:
            b = Board(name=name, width=round_dia, height=round_dia,
                      origin=(margin, margin), outline_round=round_dia)
        else:
            b = Board(name=name, width=w, height=h, origin=(margin, margin))
        self.boards.append(b)
        return b

    def active_layers(self) -> List[str]:
        keys = list(ALL_LAYERS)
        if not self.board().multilayer:
            keys = [k for k in keys if k not in INNER_KEYS]
        return keys

    def save(self, path: str):
        data = {"format": "ecad/1.0", "app": "e-cad", "saved": time.time(),
                "author": self.author, "comment": self.comment,
                "template_top": self.template_top,
                "template_bottom": self.template_bottom,
                "active": self.active, "settings": self.settings,
                "boards": [b.to_dict() for b in self.boards]}
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
        self.file = path
        self.dirty = False

    @staticmethod
    def load(path: str) -> "Document":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        doc = Document()
        doc.file = path
        doc.author = data.get("author", "")
        doc.comment = data.get("comment", "")
        doc.template_top = data.get("template_top")
        doc.template_bottom = data.get("template_bottom")
        doc.settings = data.get("settings", {}) or {}
        doc.boards = [Board.from_dict(b) for b in data.get("boards", [])]
        doc.active = min(data.get("active", 0), max(0, len(doc.boards) - 1))
        if not doc.boards:
            doc.boards.append(Board())
        return doc


# --------------------------------------------------------------- связность
class UnionFind:
    def __init__(self, items: Sequence[str] = ()):
        self.p = {i: i for i in items}

    def find(self, a):
        p = self.p
        if a not in p:
            p[a] = a
            return a
        root = a
        while p[root] != root:
            root = p[root]
        while p[a] != root:
            p[a], a = root, p[a]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra

    def groups(self) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for a in self.p:
            out.setdefault(self.find(a), []).append(a)
        return out


DRAW_ORDER = {"fill": 0, "track": 2, "circle": 2, "poly": 2, "rect": 2,
              "pad": 3, "smd": 3, "text": 5}
LAYER_ORDER = {"V2": 0, "M2": 0, "K2": 0, "O": 1, "V1": 2, "M1": 2, "K1": 2}


def draw_sort_key(el: Element):
    """Порядок отрисовки: нижние слои → верхние → контур; заливка под дорожками."""
    return (LAYER_ORDER.get(el.layer, 2), DRAW_ORDER.get(el.layer, 2),
            DRAW_ORDER.get(el.kind, 2))


def conductive_elements(board: Board) -> List[Element]:
    return [el for el in board.elements.values()
            if el.kind in ("track", "pad", "smd", "circle", "poly", "rect") and not el.negative]


def pad_layers(el: Element) -> List[str]:
    if isinstance(el, Pad):
        return el.copper_layers()
    return [el.layer]


def nets(board: Board, use_virtual: bool = True, extra: Sequence[Element] = ()) -> UnionFind:
    """Объединение проводящих элементов в цепи: пересечения + виртуальные связи."""
    els = conductive_elements(board) + list(extra)
    uf = UnionFind([el.id for el in els])
    by_layer: Dict[str, List[Element]] = {}
    for el in els:
        for lk in pad_layers(el):
            by_layer.setdefault(lk, []).append(el)

    for lk, items in by_layer.items():
        n = len(items)
        boxes = [el.bbox() for el in items]
        for i in range(n):
            if boxes[i] is None:
                continue
            for j in range(i + 1, n):
                if boxes[j] is None:
                    continue
                if not bbox_overlap(boxes[i], boxes[j]):
                    continue
                if _elements_touch(items[i], items[j]):
                    uf.union(items[i].id, items[j].id)

    if use_virtual:
        for el in board.elements.values():
            if isinstance(el, Connection) and el.a and el.b:
                if el.a in uf.p and el.b in uf.p:
                    uf.union(el.a, el.b)
    return uf


def _elements_touch(a: Element, b: Element, tol: float = 0.02) -> bool:
    return _touch_with(a, b, tol) or _touch_with(b, a, tol)


def _touch_with(src: Element, dst: Element, tol: float) -> bool:
    sp = src.outline_points()
    db = dst.bbox()
    if not sp or db is None:
        return False
    half = _src_half(src)
    need = tol + half
    if isinstance(src, Track):
        segs = [(sp[i], sp[i + 1]) for i in range(len(sp) - 1)]
    else:
        segs = [(sp[i], sp[(i + 1) % len(sp)]) for i in range(len(sp))]
    for p, q in segs:
        seg_box = (min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1]))
        if not bbox_overlap(bbox_grow(seg_box, need), bbox_grow(db, tol)):
            continue
        if _seg_touches_box(p, q, db, need):
            return True
    return False


def _src_half(src: Element) -> float:
    if isinstance(src, Track):
        return src.width / 2
    if isinstance(src, CircleEl):
        return 0.0 if src.filled else src.width / 2
    if isinstance(src, PolygonEl):
        return src.contour / 2
    if isinstance(src, RectEl):
        return 0.0 if src.filled else src.width / 2
    if isinstance(src, Pad):
        return min(src.outer()) / 2
    if isinstance(src, SmdPad):
        return min(src.w, src.h) / 2
    return 0.0


def _seg_touches_box(p, q, box, tol) -> bool:
    x0, y0, x1, y1 = box
    if min(p[0], q[0]) - tol > x1 or max(p[0], q[0]) + tol < x0:
        return False
    if min(p[1], q[1]) - tol > y1 or max(p[1], q[1]) + tol < y0:
        return False
    edges = [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)),
             ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]
    for e1, e2 in edges:
        if segments_intersect(p, q, e1, e2):
            return True
    return x0 - tol <= p[0] <= x1 + tol and y0 - tol <= p[1] <= y1 + tol


def netlist(board: Board, use_virtual: bool = True) -> Dict[str, List[str]]:
    """Список цепей: ключ — корень объединения, значение — id элементов."""
    return nets(board, use_virtual).groups()


def board_stats(board: Board) -> Dict[str, float]:
    holes: Dict[float, int] = {}
    stats = {"elements": len(board.elements), "tracks": 0, "pads": 0, "smd": 0,
             "length": 0.0, "holes": holes, "vias": 0, "texts": 0}
    for el in board.elements.values():
        if el.kind == "track":
            stats["tracks"] += 1
            stats["length"] += el.length()
        elif el.kind == "pad":
            stats["pads"] += 1
            if el.hole_dia > 0:
                holes[round(el.hole_dia, 3)] = holes.get(round(el.hole_dia, 3), 0) + 1
                if el.hole_dia < el.pad_dia - 0.1 and el.pad_dia <= 1.4:
                    stats["vias"] += 1
        elif el.kind == "smd":
            stats["smd"] += 1
        elif el.kind == "text":
            stats["texts"] += 1
    return stats