"""DRC — проверка условий (раздел 10 спецификации)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .geom import bbox_grow, bbox_overlap, bbox_union
from .model import (Board, CircleEl, Component, Element, FillEl, Pad, PolygonEl,
                    RectEl, SmdPad, Track, pad_layers)

DEFAULT_RULES = {
    "min_clearance": 0.25,
    "min_hole_gap": 0.3,
    "min_hole": 0.2,
    "max_hole": 5.0,
    "min_track": 0.15,
    "min_annular": 0.15,
    "min_silk": 0.15,
    "silk_over_pad": True,
    "hole_in_smd": True,
    "pad_no_mask": True,
    "mask_on_nonpad": True,
}

RULE_NAMES = {
    "min_clearance": "Минимальный зазор между проводниками",
    "min_hole_gap": "Минимальный зазор между отверстиями",
    "min_hole": "Минимальное отверстие",
    "max_hole": "Максимальное отверстие",
    "min_track": "Минимальный проводник",
    "min_annular": "Минимальный бордюр (кольцо мин.)",
    "min_silk": "Минимальная линия маркировки",
    "silk_over_pad": "Линия маркировки над контактом",
    "hole_in_smd": "Отверстие в SMD-площадке",
    "pad_no_mask": "Контактная площадка без маски",
    "mask_on_nonpad": "Маска на элементе не-КП",
}


@dataclass
class DrcError:
    rule: str
    layer: str
    ids: List[str] = field(default_factory=list)
    box: Optional[Tuple[float, float, float, float]] = None
    text: str = ""

    def layer_name(self) -> str:
        from .model import LAYER_BY_KEY
        return LAYER_BY_KEY.get(self.layer, self).short


def _bbox_touch(a, b, tol) -> bool:
    return bbox_overlap(bbox_grow(a, tol), bbox_grow(b, tol))


def check(board: Board, rules: Optional[Dict] = None, window: Optional[Tuple[float, float, float, float]] = None,
          ignore_ids: Sequence[str] = ()) -> List[DrcError]:
    r = dict(DEFAULT_RULES)
    if rules:
        r.update({k: v for k, v in rules.items() if k in DEFAULT_RULES})
    ignore = set(ignore_ids)
    errors: List[DrcError] = []

    els = [el for el in board.elements.values()
           if el.id not in ignore and el.kind not in ("conn", "fill") and not el.negative]

    def in_window(b):
        if b is None or window is None:
            return True
        return bbox_overlap(b, window)

    conductive = [el for el in els if el.kind in ("track", "pad", "smd", "circle", "poly", "rect")]
    silks = [el for el in els if el.layer in ("K1", "K2")]
    pads = [el for el in els if isinstance(el, Pad)]
    smds = [el for el in els if isinstance(el, SmdPad)]

    
    by_layer: Dict[str, List[Element]] = {}
    for el in conductive:
        for lk in pad_layers(el):
            by_layer.setdefault(lk, []).append(el)
    for lk, items in by_layer.items():
        boxes = {el.id: el.bbox() for el in items}
        n = len(items)
        for i in range(n):
            ei = items[i]
            if not in_window(boxes[ei.id]):
                continue
            for j in range(i + 1, n):
                ej = items[j]
                if _same_object(ei, ej):
                    continue
                clr = _min_clearance(ei, ej, r["min_clearance"])
                if clr is None:
                    continue
                if _bbox_touch(boxes[ei.id], boxes[ej.id], clr):
                    gap = _geom_gap(ei, ej, lk)
                    if 1e-6 < gap < clr - 1e-4:
                        errors.append(DrcError(
                            "min_clearance", lk, [ei.id, ej.id],
                            bbox_union([boxes[ei.id], boxes[ej.id]]),
                            f"Зазор {_fmt(gap)} мм < {_fmt(clr)} мм"))
    
    holes = [el for el in pads if el.hole_dia > 0]
    for i in range(len(holes)):
        for j in range(i + 1, len(holes)):
            a, b = holes[i], holes[j]
            d = math.hypot(a.x - b.x, a.y - b.y) - a.hole_dia / 2 - b.hole_dia / 2
            if d < r["min_hole_gap"] - 1e-4:
                errors.append(DrcError(
                    "min_hole_gap", "M1", [a.id, b.id],
                    bbox_union([a.bbox(), b.bbox()]),
                    f"Зазор между отверстиями {_fmt(d)} мм < {r['min_hole_gap']} мм"))
    
    for p in pads:
        if p.hole_dia <= 0:
            continue
        if p.hole_dia < r["min_hole"] - 1e-6:
            errors.append(DrcError("min_hole", "M1", [p.id], p.bbox(),
                                   f"Отверстие {_fmt(p.hole_dia)} мм < {r['min_hole']} мм"))
        if p.hole_dia > r["max_hole"] + 1e-6:
            errors.append(DrcError("max_hole", "M1", [p.id], p.bbox(),
                                   f"Отверстие {_fmt(p.hole_dia)} мм > {r['max_hole']} мм"))
    
    for t in els:
        if isinstance(t, Track) and t.width < r["min_track"] - 1e-6:
            errors.append(DrcError("min_track", t.layer, [t.id], t.bbox(),
                                   f"Дорожка {_fmt(t.width)} мм < {r['min_track']} мм"))
    
    for p in pads:
        ring = (min(p.outer()) - p.hole_dia) / 2
        if ring < r["min_annular"] - 1e-6:
            errors.append(DrcError("min_annular", "M1", [p.id], p.bbox(),
                                   f"Бордюр {_fmt(ring)} мм < {r['min_annular']} мм"))
    
    for s in silks:
        w = _silk_width(s)
        if w is not None and w < r["min_silk"] - 1e-6:
            errors.append(DrcError("min_silk", s.layer, [s.id], s.bbox(),
                                   f"Маркировка {_fmt(w)} мм < {r['min_silk']} мм"))
    
    if r["silk_over_pad"]:
        contact_boxes = []
        for el in pads + smds:
            contact_boxes.append((el.bbox(), el.id, el.layer if isinstance(el, SmdPad) else None))
        for s in silks:
            sb = s.bbox()
            if not in_window(sb):
                continue
            for cb, cid, _ in contact_boxes:
                if _bbox_touch(sb, cb, 0.0) and _silk_shape_over(s, cb):
                    errors.append(DrcError("silk_over_pad", s.layer, [s.id, cid], cb,
                                           "Линия маркировки проходит над контактом"))
                    break
    
    if r["hole_in_smd"]:
        for s in smds:
            sb = s.bbox()
            for p in pads:
                if p.hole_dia <= 0:
                    continue
                pb = (p.x - p.hole_dia / 2, p.y - p.hole_dia / 2,
                      p.x + p.hole_dia / 2, p.y + p.hole_dia / 2)
                if _bbox_touch(sb, pb, 0.0):
                    errors.append(DrcError("hole_in_smd", s.layer, [s.id, p.id], pb,
                                           "Отверстие попадает в зону SMD-площадки"))
    
    if r["pad_no_mask"]:
        for el in pads + smds:
            if not el.mask_open:
                errors.append(DrcError("pad_no_mask", el.layer, [el.id], el.bbox(),
                                       "Нет открытия окна в паяльной маске"))
    
    if r["mask_on_nonpad"]:
        for el in els:
            if el.mask_open and not isinstance(el, (Pad, SmdPad)):
                errors.append(DrcError("mask_on_nonpad", el.layer, [el.id], el.bbox(),
                                       "Маска открыта на элементе, который не является КП"))
    return errors


def _fmt(v: float) -> str:
    return f"{v:.3f}".replace(".", ",")


def _same_object(a, b) -> bool:
    if isinstance(a, Track) and isinstance(b, Track):
        return a.points == b.points and a.width == b.width
    if isinstance(a, Pad) and isinstance(b, Pad):
        return a.x == b.x and a.y == b.y
    if isinstance(a, SmdPad) and isinstance(b, SmdPad):
        return a.x == b.x and a.y == b.y
    return False


def _min_clearance(a: Element, b: Element, rule: float) -> Optional[float]:
    """Требуемый зазор: индивидуальный (по элементам) либо общий из правил."""
    if isinstance(a, FillEl) or isinstance(b, FillEl):
        return None
    if isinstance(a, Track) and a.negative:
        return None
    if not _is_copper(a) or not _is_copper(b):
        return None
    ca = getattr(a, "clearance", None)
    cb = getattr(b, "clearance", None)
    if ca is not None and cb is not None:
        return max(min(ca, cb), 0.0)
    return rule


def _is_copper(el: Element) -> bool:
    if isinstance(el, Pad):
        return True
    return el.layer in ("M1", "M2", "V1", "V2")


def _geom_gap(a: Element, b: Element, layer: str) -> float:
    """Приблизительный зазор между элементами по кромкам."""
    ba, bb = a.bbox(), b.bbox()
    if ba is None or bb is None:
        return 99.0
    dx = max(bb[0] - ba[2], ba[0] - bb[2], 0.0)
    dy = max(bb[1] - ba[3], ba[1] - bb[3], 0.0)
    box_gap = math.hypot(dx, dy)
    if isinstance(a, (Track, CircleEl, PolygonEl, RectEl)) or isinstance(b, (Track, CircleEl, PolygonEl, RectEl)):
        pa = _edge_points(a)
        pb = _edge_points(b)
        if pa and pb:
            d1 = min(_min_to_el(q, a) for q in pb)
            d2 = min(_min_to_el(q, b) for q in pa)
            best = min(d1, d2)
            if best < box_gap + 0.6:
                return max(0.0, best)
    return box_gap


def _edge_points(el: Element) -> List[Tuple[float, float]]:
    pts = el.outline_points()
    if isinstance(el, Track) and len(pts) >= 2:
        return list(pts)
    return list(pts)


def _min_to_el(p, el: Element) -> float:
    if isinstance(el, Pad):
        w, h = el.outer()
        dx = abs(p[0] - el.x) - w / 2
        dy = abs(p[1] - el.y) - h / 2
        if isinstance(el, Pad) and el.shape == "circle":
            return max(0.0, math.hypot(p[0] - el.x, p[1] - el.y) - w / 2)
        return max(0.0, math.hypot(max(dx, 0), max(dy, 0)))
    if isinstance(el, SmdPad):
        dx = abs(p[0] - el.x) - el.w / 2
        dy = abs(p[1] - el.y) - el.h / 2
        if el.shape == "circle":
            return max(0.0, math.hypot(p[0] - el.x, p[1] - el.y) - el.w / 2)
        return max(0.0, math.hypot(max(dx, 0), max(dy, 0)))
    pts = el.outline_points()
    half = 0.0
    if isinstance(el, Track):
        half = el.width / 2
    elif isinstance(el, CircleEl):
        half = 0.0 if el.filled else el.width / 2
    elif isinstance(el, PolygonEl):
        half = el.contour / 2
    elif isinstance(el, RectEl):
        half = 0.0 if el.filled else el.width / 2
    if not pts:
        return 99.0
    if isinstance(el, Track):
        d = min(_pt_seg(p, pts[i], pts[i + 1]) for i in range(len(pts) - 1))
    else:
        d = min(_pt_seg(p, pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts)))
    return max(0.0, d - half)


def _pt_seg(p, a, b) -> float:
    from .geom import pt_seg_dist
    return pt_seg_dist(p, a, b)


def _silk_width(el: Element) -> Optional[float]:
    from .model import TextEl
    if isinstance(el, (Track, CircleEl, RectEl)):
        return el.width
    if isinstance(el, PolygonEl):
        return el.contour
    if isinstance(el, TextEl):
        return el.thickness
    return None


def _silk_shape_over(silk: Element, box) -> bool:
    if isinstance(silk, PolygonEl) or isinstance(silk, RectEl) or isinstance(silk, CircleEl):
        from .geom import point_in_poly
        cx = (box[0] + box[2]) / 2
        cy = (box[1] + box[3]) / 2
        pts = silk.outline_points()
        if isinstance(silk, CircleEl):
            return math.hypot(cx - silk.cx, cy - silk.cy) <= silk.r
        if len(pts) > 2 and point_in_poly((cx, cy), pts):
            return True
        from .geom import pt_seg_dist
        for i in range(len(pts)):
            if pt_seg_dist((cx, cy), pts[i], pts[(i + 1) % len(pts)]) <= 0.05:
                return True
        return False
    if isinstance(silk, Track):
        for i in range(len(silk.points) - 1):
            if _seg_box_hits(silk.points[i], silk.points[i + 1], box, silk.width / 2):
                return True
    from .model import TextEl
    if isinstance(silk, TextEl):
        b = silk.bbox()
        if b[0] < box[2] and box[0] < b[2] and b[1] < box[3] and box[1] < b[3]:
            cx = (box[0] + box[2]) / 2
            cy = (box[1] + box[3]) / 2
            return (b[0] - 0.1 <= cx <= b[2] + 0.1) and (b[1] - 0.1 <= cy <= b[3] + 0.1)
    return False


def _seg_box_hits(p, q, box, half) -> bool:
    x0, y0, x1, y1 = box
    edges = [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)),
             ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]
    from .geom import segments_intersect
    for e1, e2 in edges:
        if segments_intersect(p, q, e1, e2):
            return True
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    from .geom import pt_seg_dist
    return pt_seg_dist((cx, cy), p, q) <= half


def hole_table(board: Board) -> List[Tuple[float, int]]:
    """Список отверстий: (диаметр, количество)."""
    counts: Dict[float, int] = {}
    for el in board.elements.values():
        if isinstance(el, Pad) and el.hole_dia > 0:
            d = round(el.hole_dia, 4)
            counts[d] = counts.get(d, 0) + 1
    return sorted(counts.items())


def total_copper(board: Board, layer: str, cell: float = 0.05) -> Dict[str, float]:
    """Площадь меди (мм²) на слое — грубо, растром."""
    from .fill import board_region_mask, element_raster
    import numpy as np
    box = bbox_grow(board.outline_rect(), 5)
    nx = int((box[2] - box[0]) / cell) + 1
    ny = int((box[3] - box[1]) / cell) + 1
    if nx * ny > 8_000_000:
        return {}
    gx = box[0] + np.arange(nx) * cell
    gy = box[1] + np.arange(ny) * cell
    mask = np.zeros((ny, nx), dtype=bool)
    for el in board.elements.values():
        layers = el.copper_layers() if isinstance(el, Pad) else [el.layer]
        if layer not in layers or el.negative or el.kind == "conn":
            continue
        r = element_raster(el, layer, (gx, gy), cell)
        if r:
            (i0, j0, i1, j1), sub = r
            mask[j0:j1, i0:i1] |= sub
    return {"area": float(mask.sum()) * cell * cell,
            "total": (board.width * board.height)}