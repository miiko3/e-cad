"""Геометрия, растеризация и преобразования. Единицы модели — миллиметры."""
from __future__ import annotations

import math
from typing import Iterable, List, Sequence, Tuple

import numpy as np

MM = 1.0
MIL = 0.0254
INCH = 25.4
EPS = 1e-9

Pt = Tuple[float, float]



def dist(a: Pt, b: Pt) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def dist2(a: Pt, b: Pt) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    return dx * dx + dy * dy


def seg_len(a: Pt, b: Pt) -> float:
    return dist(a, b)


def pt_seg_dist(p: Pt, a: Pt, b: Pt) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 < EPS:
        return math.hypot(p[0] - ax, p[1] - ay)
    t = ((p[0] - ax) * dx + (p[1] - ay) * dy) / l2
    t = max(0.0, min(1.0, t))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def seg_seg_dist(a: Pt, b: Pt, c: Pt, d: Pt) -> float:
    if segments_intersect(a, b, c, d):
        return 0.0
    return min(pt_seg_dist(a, c, d), pt_seg_dist(b, c, d),
               pt_seg_dist(c, a, b), pt_seg_dist(d, a, b))


def cross(o: Pt, a: Pt, b: Pt) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def segments_intersect(a: Pt, b: Pt, c: Pt, d: Pt) -> bool:
    d1, d2 = cross(c, d, a), cross(c, d, b)
    d3, d4 = cross(a, b, c), cross(a, b, d)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
        return True
    return False


def rot_pt(p: Pt, c: Pt, deg: float) -> Pt:
    r = math.radians(deg)
    ca, sa = math.cos(r), math.sin(r)
    dx, dy = p[0] - c[0], p[1] - c[1]
    return (c[0] + dx * ca - dy * sa, c[1] + dx * sa + dy * ca)


def mirror_x(p: Pt, c: Pt = (0.0, 0.0)) -> Pt:
    return (2 * c[0] - p[0], p[1])


def mirror_y(p: Pt, c: Pt = (0.0, 0.0)) -> Pt:
    return (p[0], 2 * c[1] - p[1])


def norm_angle(deg: float) -> float:
    return deg % 360.0


def poly_length(pts: Sequence[Pt]) -> float:
    return sum(dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def bbox_of(pts: Iterable[Pt]) -> Tuple[float, float, float, float]:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def bbox_union(boxes: Iterable[Tuple[float, float, float, float]],
                empty: Tuple[float, float, float, float] = None):
    boxes = [b for b in boxes if b is not None]
    if not boxes:
        return empty
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def bbox_grow(b, d: float):
    if b is None:
        return None
    return (b[0] - d, b[1] - d, b[2] + d, b[3] + d)


def bbox_overlap(a, b) -> bool:
    if a is None or b is None:
        return False
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def bbox_contains(b, p: Pt, pad: float = 0.0) -> bool:
    return (b[0] - pad) <= p[0] <= (b[2] + pad) and (b[1] - pad) <= p[1] <= (b[3] + pad)


def point_in_poly(p: Pt, poly: Sequence[Pt]) -> bool:
    x, y = p
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < xin:
                inside = not inside
    return inside


def arc_points(cx: float, cy: float, r: float, a0: float, a1: float,
               step_deg: float = 5.0) -> List[Pt]:
    """Точки дуги. Углы в градусах, против часовой стрелки."""
    span = a1 - a0
    while span <= -180.0:
        span += 360.0
    while span > 180.0:
        span -= 360.0
    n = max(2, int(abs(span) / step_deg) + 1)
    out = []
    for i in range(n + 1):
        a = math.radians(a0 + span * i / n)
        out.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return out


def arc_svg_path(cx, cy, r, a0, a1) -> str:
    span = a1 - a0
    while span <= -180.0:
        span += 360.0
    while span > 180.0:
        span -= 360.0
    x0, y0 = cx + r * math.cos(math.radians(a0)), cy + r * math.sin(math.radians(a0))
    x1, y1 = cx + r * math.cos(math.radians(a1)), cy + r * math.sin(math.radians(a1))
    large = 1 if abs(span) > 180 else 0
    sweep = 0 if span > 0 else 1
    return f"M {x0:.4f} {y0:.4f} A {r:.4f} {r:.4f} 0 {large} {sweep} {x1:.4f} {y1:.4f}"


def rdp(points: Sequence[Pt], eps: float) -> List[Pt]:
    """Упрощение Дугласа–Пекера."""
    if len(points) < 3:
        return list(points)
    dmax, idx = 0.0, 0
    a, b = points[0], points[-1]
    for i in range(1, len(points) - 1):
        d = pt_seg_dist(points[i], a, b)
        if d > dmax:
            dmax, idx = d, i
    if dmax > eps:
        left = rdp(points[:idx + 1], eps)
        right = rdp(points[idx:], eps)
        return left[:-1] + right
    return [a, b]


def offset_polyline(pts: Sequence[Pt], d: float) -> List[Pt]:
    """Грубое смещение ломаной на d (вправо по нормали сегмента)."""
    out: List[Pt] = []
    n = len(pts)
    for i in range(n):
        if i == 0:
            dx, dy = pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]
        elif i == n - 1:
            dx, dy = pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1]
        else:
            dx = pts[i + 1][0] - pts[i - 1][0]
            dy = pts[i + 1][1] - pts[i - 1][1]
        l = math.hypot(dx, dy) or 1.0
        out.append((pts[i][0] - dy / l * d, pts[i][1] + dx / l * d))
    return out


def flatten(el, layer: str) -> List[Pt]:
    """Разложить элемент в список точек контура (для проверок)."""
    return list(getattr(el, "outline_points", lambda: [])())



class Raster:
    """Растровое поле по прямоугольнику с шагом cell (мм)."""

    def __init__(self, box: Tuple[float, float, float, float], cell: float):
        x0, y0, x1, y1 = box
        self.cell = cell
        self.x0, self.y0 = x0, y0
        self.nx = max(1, int(math.ceil((x1 - x0) / cell)))
        self.ny = max(1, int(math.ceil((y1 - y0) / cell)))
        self.mask = np.zeros((self.ny, self.nx), dtype=bool)

    
    def cx(self) -> np.ndarray:
        return self.x0 + (np.arange(self.nx) + 0.5) * self.cell

    def cy(self) -> np.ndarray:
        return self.y0 + (np.arange(self.ny) + 0.5) * self.cell

    def gx(self) -> np.ndarray:
        return self.x0 + np.arange(self.nx) * self.cell

    def gy(self) -> np.ndarray:
        return self.y0 + np.arange(self.ny) * self.cell

    def box_px(self, box) -> Tuple[int, int, int, int]:
        x0, y0, x1, y1 = box
        i0 = max(0, int(math.floor((x0 - self.x0) / self.cell)))
        j0 = max(0, int(math.floor((y0 - self.y0) / self.cell)))
        i1 = min(self.nx, int(math.ceil((x1 - self.x0) / self.cell)) + 1)
        j1 = min(self.ny, int(math.ceil((y1 - self.y0) / self.cell)) + 1)
        return i0, j0, i1, j1

    
    def line(self, a: Pt, b: Pt, width: float = 0.0):
        r = width / 2.0
        box = (min(a[0], b[0]) - r, min(a[1], b[1]) - r,
               max(a[0], b[0]) + r, max(a[1], b[1]) + r)
        i0, j0, i1, j1 = self.box_px(box)
        if i1 <= i0 or j1 <= j0:
            return
        X = self.cx()[i0:i1][None, :]
        Y = self.cy()[j0:j1][:, None]
        ax, ay = a
        bx, by = b
        dx, dy = bx - ax, by - ay
        l2 = dx * dx + dy * dy
        if l2 < EPS:
            d = np.hypot(X - ax, Y - ay)
        else:
            t = ((X - ax) * dx + (Y - ay) * dy) / l2
            t = np.clip(t, 0.0, 1.0)
            d = np.hypot(X - (ax + t * dx), Y - (ay + t * dy))
        self.mask[j0:j1, i0:i1] |= d <= r + self.cell * 0.5

    def polyline(self, pts: Sequence[Pt], width: float = 0.0, closed: bool = False):
        n = len(pts)
        for i in range(n - 1):
            self.line(pts[i], pts[i + 1], width)
        if closed and n > 2:
            self.line(pts[-1], pts[0], width)

    def circle(self, c: Pt, r: float, width: float = 0.0, fill: bool = False):
        ro = r + width / 2.0
        ri = max(0.0, r - width / 2.0)
        box = (c[0] - ro, c[1] - ro, c[0] + ro, c[1] + ro)
        i0, j0, i1, j1 = self.box_px(box)
        if i1 <= i0 or j1 <= j0:
            return
        X = self.cx()[i0:i1][None, :]
        Y = self.cy()[j0:j1][:, None]
        d = np.hypot(X - c[0], Y - c[1])
        if fill:
            self.mask[j0:j1, i0:i1] |= d <= ro + self.cell * 0.5
        else:
            self.mask[j0:j1, i0:i1] |= (d <= ro + self.cell * 0.5) & (d >= ri - self.cell * 0.5)

    def rect(self, x0: float, y0: float, x1: float, y1: float):
        i0, j0, i1, j1 = self.box_px((min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))
        self.mask[max(0, j0):j1, max(0, i0):i1] = True

    def polygon(self, poly: Sequence[Pt]):
        if len(poly) < 3:
            return
        box = bbox_of(poly)
        i0, j0, i1, j1 = self.box_px(box)
        if i1 <= i0 or j1 <= j0:
            return
        gx = self.cx()[i0:i1]
        gy = self.cy()[j0:j1]
        sub = polygon_fill_mask(poly, box, self.cell, (gx, gy))
        self.mask[j0:j1, i0:i1] |= sub

    def outline_polygon(self, poly: Sequence[Pt], width: float = 0.1):
        self.polyline(poly, width, closed=True)


def polygon_fill_mask(poly: Sequence[Pt], box, cell: float, grid: Tuple[np.ndarray, np.ndarray]) -> np.ndarray:
    """Быстрая заливка полигона по готовой сетке (even-odd), без объекта Raster."""
    gx, gy = grid
    x0, y0, x1, y1 = box
    P = np.asarray(poly, dtype=float)
    if len(P) < 3:
        return np.zeros((len(gy), len(gx)), dtype=bool)
    inside = np.zeros((len(gy), len(gx)), dtype=bool)
    px, py = P[:, 0], P[:, 1]
    qx, qy = np.roll(px, -1), np.roll(py, -1)
    for r, yy in enumerate(gy):
        cond = (py > yy) != (qy > yy)
        if not cond.any():
            continue
        dy = np.where(np.abs(qy - py) < EPS, EPS, qy - py)
        xs = np.sort((qx - px)[cond] * (yy - py[cond]) / dy[cond] + px[cond])
        for k in range(0, len(xs) - 1, 2):
            i_l = int(np.searchsorted(gx, xs[k], side="left"))
            i_r = int(np.searchsorted(gx, xs[k + 1], side="right"))
            if i_r > i_l:
                inside[r, i_l:i_r] = True
    return inside


def dilate(mask: np.ndarray, radius_cells: float) -> np.ndarray:
    """Расширение маски (чамферное приближение евклидова расстояния).

    Маска расширяется с рамкой, чтобы пиксели у края окна тоже учитывались.
    """
    if radius_cells <= 0 or not mask.any():
        return mask.copy()
    pad = int(math.ceil(radius_cells)) + 2
    m = np.pad(mask, pad, mode="edge")
    d = np.where(m, 0.0, 1e6).astype(np.float32)
    it = max(2, int(math.ceil(radius_cells)) + 1)
    s1 = 1.0
    s2 = 1.41421356
    for _ in range(it):
        n = d.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                w = s2 if (dx and dy) else s1
                shifted = np.roll(np.roll(d, dy, axis=0), dx, axis=1)
                np.minimum(n, shifted + w, out=n)
        d = n
    return (d <= radius_cells + 0.35)[pad:-pad, pad:-pad]


def mask_to_rects(mask: np.ndarray, gx: np.ndarray, gy: np.ndarray,
                  min_area: int = 1) -> List[Tuple[float, float, float, float]]:
    """Жадное разбиение битовой маски на прямоугольники (для полигонов заливки)."""
    m = mask
    if not m.any():
        return []
    ny, nx = m.shape
    rects: List[Tuple[float, float, float, float]] = []
    used = np.zeros_like(m)
    h, w = gy[1] - gy[0] if len(gy) > 1 else 1.0, gx[1] - gx[0] if len(gx) > 1 else 1.0
    for j in range(ny):
        i = 0
        row = m[j]
        while i < nx:
            if not row[i] or used[j, i]:
                i += 1
                continue
            i2 = i
            while i2 + 1 < nx and row[i2 + 1] and not used[j, i2 + 1]:
                i2 += 1
            j2 = j
            while (j2 + 1 < ny and m[j2 + 1, i:i2 + 1].all()
                   and not used[j2 + 1, i:i2 + 1].any()):
                j2 += 1
            used[j:j2 + 1, i:i2 + 1] = True
            rects.append((gx[i], gy[j], gx[i2 + 1] if i2 + 1 < len(gx) else gx[i2] + w,
                          gy[j2 + 1] if j2 + 1 < len(gy) else gy[j2] + h))
            i = i2 + 1
    return rects


def merge_rects(rects: List[Tuple[float, float, float, float]],
                gap: float = 0.0) -> List[Tuple[float, float, float, float]]:
    """Слияние прямоугольников, перекрывающихся или соприкасающихся."""
    items = [list(r) for r in rects]
    changed = True
    while changed:
        changed = False
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                if (a[0] - gap <= b[2] and b[0] - gap <= a[2]
                        and a[1] - gap <= b[3] and b[1] - gap <= a[3]):
                    items[i] = [min(a[0], b[0]), min(a[1], b[1]),
                                max(a[2], b[2]), max(a[3], b[3])]
                    items.pop(j)
                    changed = True
                    break
            if changed:
                break
    return [tuple(r) for r in items]


def fmt_mm(v: float, digits: int = 3) -> str:
    return f"{v:.{digits}f}"


def mm_to_str(v: float, digits: int = 4, commas: bool = False) -> str:
    s = f"{v:.{digits}f}"
    if commas:
        s = s.replace(".", ",")
    return s


def parse_len(text: str, default: float = 0.0) -> float:
    text = (text or "").strip().replace(",", ".")
    if not text:
        return default
    m = text.lower()
    mult = 1.0
    for suffix, k in (("mm", 1.0), ("мм", 1.0), ("mil", MIL), ("mil.", MIL),
                       ("тыс.дюйма", MIL), ("in", INCH), ("дюйм", INCH),
                       ("μm", 0.001), ("um", 0.001)):
        if m.endswith(suffix):
            m = m[: -len(suffix)].strip()
            mult = k
            break
    try:
        return float(m) * mult
    except ValueError:
        return default