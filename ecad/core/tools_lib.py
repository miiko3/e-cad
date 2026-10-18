"""Библиотека макросов, компоненты, мастер площадок, автотрасса."""
from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .geom import MIL, arc_points, dist, pt_seg_dist
from .model import (Board, CircleEl, Component, Connection, Element, Pad,
                    PolygonEl, RectEl, SmdPad, TextEl, TOP_KEY, Track, nets)




MACRO_VERSION = 2


@dataclass
class Macro:
    name: str
    group: str = "Общие"
    elements: List[Element] = field(default_factory=list)
    path: Optional[str] = None
    modified: float = field(default_factory=time.time)
    version: int = 1

    def bbox(self):
        boxes = [el.bbox() for el in self.elements]
        boxes = [b for b in boxes if b]
        if not boxes:
            return (0, 0, 0, 0)
        return (min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes))

    def anchor_box(self):
        """Опорный прямоугольник для размещения: только выводы и дорожки.

        Контуры корпуса и подписи на маркировке не должны смещать центр,
        иначе макрос встаёт не под курсором.
        """
        boxes = [el.bbox() for el in self.elements
                 if el.kind in ("pad", "smd", "track", "poly", "circle", "rect")
                 and el.layer not in ("K1", "K2", "O")]
        boxes = [b for b in boxes if b]
        if not boxes:
            return self.bbox()
        return (min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes))

    def center(self):
        b = self.bbox()
        return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)

    def instance(self, x: float, y: float, rotation: float = 0.0,
                 mirror: bool = False, side: Optional[str] = None) -> List[Element]:
        """Создать копию макроса с центром в (x, y)."""
        ab = self.anchor_box()
        cx, cy = (ab[0] + ab[2]) / 2, (ab[1] + ab[3]) / 2
        out: List[Element] = []
        for el in self.elements:
            e = el.copy()
            if rotation:
                e.rotate(rotation, (cx, cy))
            if mirror:
                e.mirror_x((cx, cy))
            e.move(x - cx, y - cy)
            if side == "bottom":
                e.flip_layer()
            e.id = ""            
            out.append(e)
        return out

    def to_dict(self):
        return {"name": self.name, "group": self.group, "v": MACRO_VERSION,
                "elements": [e.to_dict() for e in self.elements]}

    @staticmethod
    def from_dict(d) -> "Macro":
        m = Macro(d.get("name", "macro"))
        m.group = d.get("group", "Общие")
        m.version = int(d.get("v", 1))
        for ed in d.get("elements", []):
            m.elements.append(Element.from_dict(ed))
        return m


class Library:
    """Файловая библиотека макросов: папка с .ecadm/.json и .kicad_mod.

    Поддерживает вложенные папки: имя папки становится группой.
    """

    EXT = ".ecadm"
    EXTRA_EXT = (".json", ".kicad_mod", ".kicad_mod.txt")

    def __init__(self, folder: str):
        self.folder = folder
        self.macros: List[Macro] = []

    def scan(self):
        self.macros = []
        if not os.path.isdir(self.folder):
            os.makedirs(self.folder, exist_ok=True)
            return self.macros
        for path, group in self._iter_files(self.folder, ""):
            m = self._load(path, group)
            if m is not None:
                self.macros.append(m)
        return self.macros

    def _iter_files(self, root: str, prefix: str):
        try:
            entries = sorted(os.listdir(root))
        except OSError:
            return
        for fn in entries:
            full = os.path.join(root, fn)
            if os.path.isdir(full):
                sub = f"{prefix}/{fn}" if prefix else fn
                yield from self._iter_files(full, sub)
                continue
            if not fn.lower().endswith((self.EXT,) + self.EXTRA_EXT):
                continue
            group = prefix or "Общие"
            yield full, group

    def _load(self, path: str, group: str) -> Optional[Macro]:
        try:
            if path.lower().endswith(".kicad_mod") or path.lower().endswith(".kicad_mod.txt"):
                m = footprint_from_kicad(path, group)
            else:
                with open(path, "r", encoding="utf-8") as f:
                    m = Macro.from_dict(json.load(f))
            if not m.elements:
                return None
            m.path = path
            m.name = m.name or os.path.splitext(os.path.basename(path))[0]
            if not m.group or m.group == "Общие":
                m.group = group
            m.modified = os.path.getmtime(path)
            return m
        except Exception:
            return None

    def folders(self) -> List[str]:
        """Все вложенные папки библиотеки (для наблюдения за изменениями)."""
        out = [self.folder]
        for root, dirs, _files in os.walk(self.folder):
            for d in dirs:
                out.append(os.path.join(root, d))
        return out

    def groups(self) -> List[str]:
        return sorted({m.group for m in self.macros})

    def save(self, macro: Macro) -> str:
        os.makedirs(os.path.dirname(macro.path) if macro.path and os.path.dirname(macro.path)
                    else self.folder, exist_ok=True)
        path = macro.path or os.path.join(self.folder, _safe_name(macro.group, macro.name) + self.EXT)
        macro.path = path
        macro.version = MACRO_VERSION
        with open(path, "w", encoding="utf-8") as f:
            json.dump(macro.to_dict(), f, ensure_ascii=False)
        return path

    def delete(self, macro: Macro):
        if macro.path and os.path.exists(macro.path):
            os.remove(macro.path)
        self.macros = [m for m in self.macros if m is not macro]

    def ensure_defaults(self) -> List[Macro]:
        """Создать недостающие макросы и обновить устаревшие (MACRO_VERSION)."""
        self.scan()
        by_name = {(m.group, m.name): m for m in self.macros}
        added: List[Macro] = []
        from .footprints import default_macros
        for group, name, els in default_macros():
            cur = by_name.get((group, name))
            if cur is not None and getattr(cur, "version", 1) >= MACRO_VERSION:
                continue
            m = Macro(name=name, group=group, elements=els, version=MACRO_VERSION)
            if cur is not None and cur.path:
                m.path = cur.path
            self.save(m)
            added.append(m)
        if added:
            self.scan()
        return added

    def make_macro(self, board: Board, ids: Sequence[str], name: str, group: str) -> Macro:
        els = [board.elements[i].copy() for i in ids if i in board.elements]
        return Macro(name=name, group=group, elements=els)

    def add_default(self) -> List[Macro]:
        """Стартовый набор библиотеки (макросы из каталога Sprint Layout)."""
        from .footprints import default_macros
        made: List[Macro] = []
        for group, name, els in default_macros():
            m = Macro(name=name, group=group, elements=els)
            self.save(m)
            made.append(m)
        self.scan()
        return made


def _safe_name(*parts: str) -> str:
    out = "_".join(parts)
    bad = '\\/:*?"<>|'
    return "".join(c for c in out if c not in bad).strip() or "macro"


def _sexp(text: str):
    """Разбор s-выражений KiCad в список токенов вида ('atom', 'str') и списки."""
    tokens = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
        elif ch in "()":
            tokens.append(ch)
            i += 1
        elif ch == '"':
            i += 1
            buf = []
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    buf.append(text[i + 1])
                    i += 2
                else:
                    buf.append(text[i])
                    i += 1
            i += 1
            tokens.append(("str", "".join(buf)))
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in "()":
                j += 1
            tokens.append(("atom", text[i:j]))
            i = j
    pos = [0]

    def parse():
        out = []
        while pos[0] < len(tokens):
            tok = tokens[pos[0]]
            pos[0] += 1
            if tok == "(":
                out.append(parse())
            elif tok == ")":
                return out
            else:
                out.append(tok)
        return out

    tree = parse()
    if isinstance(tree, list) and tree and isinstance(tree[0], list):
        return tree[0]
    return []


def _walk(node, kind: str):
    for item in (node if isinstance(node, list) else []):
        if isinstance(item, list) and item and isinstance(item[0], tuple) and item[0][1] == kind:
            yield item


def _num(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def footprint_from_kicad(path: str, group: str = "KiCad") -> Macro:
    """Читать посадочное место KiCad (*.kicad_mod) как макрос e-cad."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    root = _sexp(text)
    name = os.path.splitext(os.path.basename(path))[0]
    if isinstance(root, list) and root and isinstance(root[0], tuple) \
            and root[0][1] == "footprint":
        nm = next((t[1] for t in root[1:2] if isinstance(t, tuple) and t[0] == "str"), "")
        name = nm or name
    m = Macro(name=name, group=group)
    for pad in _walk(root, "pad"):
        num = next((t[1] for t in pad[1:] if isinstance(t, tuple) and t[0] == "str"), "")
        ptype = next((t[1] for t in pad[1:] if isinstance(t, tuple) and t[0] == "atom"), "smd")
        at = next(_walk(pad, "at"), None)
        size = next(_walk(pad, "size"), None)
        drill = next(_walk(pad, "drill"), None)
        shape = next((t[1] for t in pad[1:] if isinstance(t, tuple)
                      and t[0] == "atom" and t[1] in ("circle", "rect", "oval", "roundrect")),
                     "rect")
        if at is None or size is None:
            continue
        vals = [t[1] for t in at[1:] if isinstance(t, tuple)]
        x, y = _num(vals[0] if vals else 0), _num(vals[1] if len(vals) > 1 else 0)
        sw, sh = _num(size[1][1] if len(size) > 1 else 0), _num(size[2][1] if len(size) > 2 else 0)
        if ptype in ("smd", "smd_custom"):
            m.elements.append(SmdPad(layer=TOP_KEY, x=x, y=y, w=sw, h=sh,
                                     shape="roundrect" if shape == "roundrect" else "rect",
                                     mask_open=True))
        else:
            hole = 0.0
            if drill is not None:
                dv = [t[1] for t in drill[1:] if isinstance(t, tuple)]
                hole = _num(dv[0] if dv else 0)
                if len(dv) > 1:
                    hole = min(_num(dv[0]), _num(dv[1]))
            size_map = {"circle": "circle", "oval": "oval", "rect": "rect"}
            m.elements.append(Pad(layer=TOP_KEY, x=x, y=y, pad_dia=max(sw, sh),
                                  hole_dia=hole or max(sw, sh) * 0.55,
                                  shape=size_map.get(shape, "circle"),
                                  size=(sw, sh), mask_open=True, plated=True))
    for line in _walk(root, "fp_line"):
        st, en = next(_walk(line, "start"), None), next(_walk(line, "end"), None)
        if st is None or en is None:
            continue
        sv = [t[1] for t in st[1:] if isinstance(t, tuple)]
        ev = [t[1] for t in en[1:] if isinstance(t, tuple)]
        m.elements.append(Track(layer="K1", points=[(_num(sv[0]), _num(sv[1])),
                                                    (_num(ev[0]), _num(ev[1]))],
                                width=0.15))
    for circ in _walk(root, "fp_circle"):
        c, e = next(_walk(circ, "center"), None), next(_walk(circ, "end"), None)
        if c is None or e is None:
            continue
        cv = [t[1] for t in c[1:] if isinstance(t, tuple)]
        ev = [t[1] for t in e[1:] if isinstance(t, tuple)]
        m.elements.append(CircleEl(layer="K1", cx=_num(cv[0]), cy=_num(cv[1]),
                                   r=abs(_num(ev[0]) - _num(cv[0])), width=0.15))
    if not m.elements:
        raise ValueError("в файле нет посадочных мест")
    return m



WIZARD_TYPES = [
    ("sip", "Однорядный (SIP)"),
    ("dip", "Двухрядный (DIP)"),
    ("quad", "Четырёхсторонний (QUAD)"),
    ("ring", "Кольцевой"),
    ("ring2", "Двойной кольцевой"),
]


def footprint_wizard(kind: str, pads: int = 8, pitch: float = 2.54,
                     row_span: float = 7.62, pad_dia: float = 1.6,
                     hole_dia: float = 0.9, smd: bool = False,
                     smd_w: float = 0.6, smd_h: float = 1.5,
                     radius: float = 5.0, body_l: float = 9.8,
                     body_w: float = 6.0, first_pad_square: bool = True,
                     layer: str = TOP_KEY) -> List[Element]:
    """Сгенерировать посадочное место."""
    els: List[Element] = []
    if kind == "sip":
        for i in range(pads):
            x = (i - (pads - 1) / 2) * pitch
            els.append(_pad_at(x, 0.0, pad_dia, hole_dia, smd, smd_w, smd_h,
                               layer, first_pad_square and i == 0))
    elif kind == "dip":
        n = pads // 2
        for i in range(n):
            y = (i - (n - 1) / 2) * pitch
            els.append(_pad_at(-row_span / 2, y, pad_dia, hole_dia, smd, smd_w, smd_h,
                               layer, first_pad_square and i == 0))
            els.append(_pad_at(row_span / 2, y, pad_dia, hole_dia, smd, smd_w, smd_h,
                               layer, False))
    elif kind == "quad":
        per = pads // 4
        x0 = body_w / 2
        y0 = body_l / 2
        for side in range(4):
            for i in range(per):
                t = (i + 0.5) / per
                if side == 0:
                    x, y = -body_w / 2 + body_w * t, -y0
                elif side == 1:
                    x, y = body_w / 2, -body_l / 2 + body_l * t
                elif side == 2:
                    x, y = body_w / 2 - body_w * t, y0
                else:
                    x, y = -body_w / 2, body_l / 2 - body_l * t
                els.append(_pad_at(x, y, pad_dia, hole_dia, smd, smd_w, smd_h,
                                   layer, first_pad_square and side == 0 and i == 0))
    elif kind in ("ring", "ring2"):
        for i in range(pads):
            a = math.radians(360.0 * i / pads)
            x, y = radius * math.cos(a), radius * math.sin(a)
            els.append(_pad_at(x, y, pad_dia, hole_dia, smd, smd_w, smd_h, layer,
                               first_pad_square and i == 0))
        if kind == "ring2":
            r2 = radius * 0.6
            for i in range(pads):
                a = math.radians(360.0 * (i + 0.5) / pads)
                els.append(_pad_at(r2 * math.cos(a), r2 * math.sin(a), pad_dia,
                                   hole_dia, smd, smd_w, smd_h, layer, False))
    
    els.append(RectEl(layer="K1", x0=-body_w / 2, y0=-body_l / 2,
                      x1=body_w / 2, y1=body_l / 2, width=0.2))
    els.append(CircleEl(layer="K1", cx=-body_w / 2, cy=-body_l / 2, r=0.25, width=0.2))
    return els


def _pad_at(x, y, pad_dia, hole_dia, smd, smd_w, smd_h, layer, square_first):
    if smd:
        return SmdPad(layer=layer, x=x, y=y, w=smd_w, h=smd_h, mask_open=True)
    p = Pad(layer=layer, x=x, y=y, pad_dia=pad_dia, hole_dia=hole_dia, mask_open=True)
    if square_first:
        p.shape = "rect"
        p.size = (pad_dia, pad_dia)
    return p



@dataclass
class RouteParams:
    width: float = 0.4
    clearance: float = 0.3
    grid: float = 0.25
    grid_coeff: int = 1
    angles: Tuple[float, ...] = (90.0, 45.0, 0.0)


def autotrace(board: Board, conn: Connection, params: RouteParams,
              forbidden: Optional[List[Element]] = None) -> Optional[Track]:
    """Point-to-point автотрасса: Л-, Z- и обходные маршруты с одним изгибом."""
    ea, eb = board.elements.get(conn.a), board.elements.get(conn.b)
    if ea is None or eb is None:
        return None
    a, b = _anchor(ea), _anchor(eb)
    reach = params.width / 2 + params.clearance
    span_x = abs(a[0] - b[0]) + reach + 2.0
    span_y = abs(a[1] - b[1]) + reach + 2.0
    blockers = []
    for el in board.elements.values():
        if el.kind not in ("track", "pad", "smd", "circle", "poly", "rect"):
            continue
        if el.id in (conn.a, conn.b) or el.locked and el.kind not in ("track", "pad", "smd"):
            continue
        bb = el.bbox()
        if bb is not None and (bb[2] < min(a[0], b[0]) - span_x or
                               bb[0] > max(a[0], b[0]) + span_x or
                               bb[3] < min(a[1], b[1]) - span_y or
                               bb[1] > max(a[1], b[1]) + span_y):
            continue
        blockers.append(el)
    grid = max(params.grid, 0.05)
    box = board.outline_rect()

    def snap(v):
        return round(v / grid) * grid

    def free(pts) -> bool:
        for i in range(len(pts) - 1):
            for bl in blockers:
                if _seg_conflict(pts[i], pts[i + 1], bl, params.width, params.clearance):
                    return False
        return True

    def length_of(pts) -> float:
        return sum(dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))

    def clean_path(pts):
        out = [pts[0]]
        for p in pts[1:]:
            if dist(out[-1], p) > 1e-6:
                out.append(p)
        return out if len(out) >= 2 else None

    best: Optional[Tuple[float, List[Tuple[float, float]]]] = None

    def consider(pts):
        nonlocal best
        pts = clean_path(pts)
        if pts is None or not free(pts):
            return
        ln = length_of(pts)
        if best is None or ln < best[0]:
            best = (ln, pts)

    for angle in params.angles:
        for order in (0, 1):
            pts = _make_path(a, b, angle, order, snap)
            if pts is not None and len(pts) >= 2 and _inside(pts, box, reach):
                consider(pts)
    if best is not None:
        return Track(layer=conn.layer, points=best[1], width=params.width, auto=True)

    step = max(grid, 0.1)
    reach_limit = max(abs(box[2] - box[0]), abs(box[3] - box[1]), 10.0)
    steps = max(8, min(400, int(reach_limit / step)))
    for i in range(1, steps + 1):
        d = step * i
        for sign in (1, -1):
            for horiz in (True, False):
                raw = _z_path(a, b, sign * d, horiz)
                pts = [(snap(p[0]), snap(p[1])) for p in raw]
                if not _inside(pts, box, reach):
                    continue
                if consider(pts) or best is not None:
                    return Track(layer=conn.layer, points=best[1],
                                 width=params.width, auto=True)
    if best is None:
        return None
    return Track(layer=conn.layer, points=best[1], width=params.width, auto=True)


def _inside(pts, box, margin: float) -> bool:
    """Все точки маршрута внутри контура платы с запасом на ширину дорожки."""
    x0, y0, x1, y1 = box
    return all(x0 + margin <= px <= x1 - margin and y0 + margin <= py <= y1 - margin
               for px, py in pts)


def _z_path(a, b, side: float, horizontal: bool):
    """Обход: из a выходим перпендикулярно, идём вдоль, возвращаемся в b."""
    if abs(side) < 1e-9:
        return [a, b]
    if horizontal:
        return [a, (a[0], a[1] + side), (b[0], a[1] + side), b]
    return [a, (a[0] + side, a[1]), (a[0] + side, b[1]), b]


def _anchor(el: Element) -> Tuple[float, float]:
    if isinstance(el, (Pad, SmdPad)):
        return (el.x, el.y)
    if isinstance(el, (Track, PolygonEl, RectEl)):
        pts = el.outline_points()
        if pts:
            return pts[0]
    b = el.bbox()
    if b:
        return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
    return (0.0, 0.0)


def _make_path(a, b, angle: float, order: int, snap) -> Optional[List[Tuple[float, float]]]:
    import math
    r = math.radians(angle)
    ca, sa = math.cos(r), math.sin(r)

    def proj(p, along=(ca, sa), perp=(-sa, ca)):
        return (p[0] * along[0] + p[1] * along[1], p[0] * perp[0] + p[1] * perp[1])

    ua, va = proj(a)
    ub, vb = proj(b)
    if abs(va - vb) < 1e-9:
        return [(snap(a[0]), snap(a[1])), (snap(b[0]), snap(b[1]))]
    if order == 0:
        pts = [(ua, va), (ub, va), (ub, vb)]
    else:
        pts = [(ua, va), (ua, vb), (ub, vb)]

    def unproj(p):
        return (p[0] * ca + p[1] * -sa, p[0] * sa + p[1] * ca)

    out = [(snap(unproj(p)[0]), snap(unproj(p)[1])) for p in pts]
    dedup: List[Tuple[float, float]] = []
    for p in out:
        if not dedup or dist(dedup[-1], p) > 1e-6:
            dedup.append(p)
    return dedup if len(dedup) >= 2 else None


def _seg_conflict(p, q, blocker: Element, width: float, clearance: float) -> bool:
    need = width / 2 + clearance
    if isinstance(blocker, (Pad, SmdPad)):
        return pt_seg_dist((blocker.x, blocker.y), p, q) < need + _half(blocker)
    if isinstance(blocker, (Track, CircleEl, PolygonEl, RectEl)):
        half = _half(blocker)
        bb = blocker.bbox()
        if bb is not None:
            if (max(p[0], q[0]) < bb[0] - need - half or min(p[0], q[0]) > bb[2] + need + half
                    or max(p[1], q[1]) < bb[1] - need - half
                    or min(p[1], q[1]) > bb[3] + need + half):
                return False
        pts = _outline_of(blocker)
        if isinstance(blocker, Track) and len(pts) >= 2:
            for i in range(len(pts) - 1):
                if _seg_dist(p, q, pts[i], pts[i + 1]) < need + half:
                    return True
        elif len(pts) >= 2:
            for i in range(len(pts)):
                if pt_seg_dist(pts[i], p, q) < need + half:
                    return True
    return False


_OUTLINE_CACHE: Dict[int, Tuple[Element, List[Tuple[float, float]]]] = {}


def _outline_of(el: Element) -> List[Tuple[float, float]]:
    """Контур элемента с кэшем: трассировщик спрашивает одни и те же контуры."""
    key = id(el)
    hit = _OUTLINE_CACHE.get(key)
    if hit is not None and hit[0] is el:
        return hit[1]
    pts = el.outline_points()
    if len(_OUTLINE_CACHE) > 20000:
        _OUTLINE_CACHE.clear()
    _OUTLINE_CACHE[key] = (el, pts)
    return pts


def _half(el: Element) -> float:
    if isinstance(el, (Pad, SmdPad)):
        return min(el.outer() if isinstance(el, Pad) else (el.w, el.h)) / 2
    if isinstance(el, Track):
        return el.width / 2
    if isinstance(el, CircleEl):
        return 0.0 if el.filled else el.width / 2
    if isinstance(el, RectEl):
        return 0.0 if el.filled else el.width / 2
    if isinstance(el, PolygonEl):
        return el.contour / 2
    return 0.0


def _seg_dist(a, b, c, d) -> float:
    from .geom import seg_seg_dist
    return seg_seg_dist(a, b, c, d)



def auto_refdes(board: Board, kind: str = "R", start: int = 1) -> str:
    used = {c.refdes for c in board.components}
    n = start
    while f"{kind}{n}" in used:
        n += 1
    return f"{kind}{n}"


def component_bounds(board: Board, comp: Component):
    boxes = [board.elements[i].bbox() for i in comp.ids if i in board.elements]
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def assign_component(board: Board, ids: Sequence[str], refdes: str = "", value: str = "",
                     comment: str = "", side: str = "top", layer: str = TOP_KEY,
                     footprint: str = "") -> Component:
    boxes = [board.elements[i].bbox() for i in ids if i in board.elements]
    boxes = [b for b in boxes if b]
    cx = sum((b[0] + b[2]) / 2 for b in boxes) / len(boxes) if boxes else 0.0
    cy = sum((b[1] + b[3]) / 2 for b in boxes) / len(boxes) if boxes else 0.0
    comp = Component(ids=list(ids), refdes=refdes, value=value, comment=comment,
                     side=side, layer=layer, x=cx, y=cy, footprint=footprint)
    board.components.append(comp)
    return comp


def component_of(board: Board, el_id: str) -> Optional[Component]:
    for c in board.components:
        if el_id in c.ids:
            return c
    return None