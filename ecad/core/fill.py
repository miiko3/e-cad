"""Авто-земля (металлизация): растровая заливка с зазорами и термобарьерами."""
from __future__ import annotations

import math
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

from .geom import (Raster, arc_points, bbox_grow, bbox_of, bbox_union, dilate,
                   mask_to_rects, merge_rects, polygon_fill_mask)
from .model import (Board, CircleEl, Element, FillEl, Pad, PolygonEl, RectEl,
                    SmdPad, Track, LAYER_BY_KEY)


def element_raster(el: Element, layer: str, grid: Tuple[np.ndarray, np.ndarray],
                   cell: float) -> Optional[Tuple[Tuple[int, int, int, int], np.ndarray]]:
    """Растр проводящего элемента (bbox в клетках + маска)."""
    gx, gy = grid
    mask = np.zeros((len(gy), len(gx)), dtype=bool)

    def to_px(box):
        x0, y0, x1, y1 = box
        i0 = max(0, int(math.floor((x0 - gx[0]) / cell)))
        j0 = max(0, int(math.floor((y0 - gy[0]) / cell)))
        i1 = min(len(gx), int(math.ceil((x1 - gx[0]) / cell)) + 1)
        j1 = min(len(gy), int(math.ceil((y1 - gy[0]) / cell)) + 1)
        return i0, j0, i1, j1

    if isinstance(el, Track):
        if not el.points:
            return None
        i0, j0, i1, j1 = to_px(bbox_grow(bbox_of(el.points), el.width / 2))
        sub = mask[j0:j1, i0:i1]
        X = gx[i0:i1][None, :]
        Y = gy[j0:j1][:, None]
        prev = el.points[0]
        for cur in el.points[1:]:
            ax, ay = prev
            bx, by = cur
            dx, dy = bx - ax, by - ay
            l2 = dx * dx + dy * dy
            if l2 < 1e-12:
                d = np.hypot(X - ax, Y - ay)
            else:
                t = np.clip(((X - ax) * dx + (Y - ay) * dy) / l2, 0, 1)
                d = np.hypot(X - (ax + t * dx), Y - (ay + t * dy))
            sub |= d <= el.width / 2 + cell * 0.5
            prev = cur
    elif isinstance(el, Pad):
        if layer not in el.copper_layers():
            return None
        i0, j0, i1, j1 = to_px(el.bbox())
        sub = mask[j0:j1, i0:i1]
        X = gx[i0:i1][None, :]
        Y = gy[j0:j1][:, None]
        w, h = el.outer()
        if el.shape in ("circle", "oval", "rounded"):
            dx = np.abs(X - el.x)
            dy = np.abs(Y - el.y)
            if el.shape == "circle":
                sub |= np.hypot(dx, dy) <= w / 2 + cell * 0.5
            else:
                r = min(w, h) / 2
                sub |= ((dx <= w / 2 + cell * 0.5) & (dy <= h / 2 + cell * 0.5)
                        & (np.hypot(np.maximum(dx - (w / 2 - r), 0),
                                    np.maximum(dy - (h / 2 - r), 0)) <= r + cell * 0.5))
        else:
            sub |= ((np.abs(X - el.x) <= w / 2 + cell * 0.5)
                    & (np.abs(Y - el.y) <= h / 2 + cell * 0.5))
    elif isinstance(el, SmdPad):
        if el.layer != layer:
            return None
        i0, j0, i1, j1 = to_px(el.bbox())
        sub = mask[j0:j1, i0:i1]
        X = gx[i0:i1][None, :]
        Y = gy[j0:j1][:, None]
        if el.shape == "circle":
            sub |= np.hypot(X - el.x, Y - el.y) <= el.w / 2 + cell * 0.5
        else:
            sub |= ((np.abs(X - el.x) <= el.w / 2 + cell * 0.5)
                    & (np.abs(Y - el.y) <= el.h / 2 + cell * 0.5))
    elif isinstance(el, CircleEl):
        if el.filled:
            i0, j0, i1, j1 = to_px(el.bbox())
            sub = mask[j0:j1, i0:i1]
            X = gx[i0:i1][None, :]
            Y = gy[j0:j1][:, None]
            sub |= np.hypot(X - el.cx, Y - el.cy) <= el.r + cell * 0.5
        else:
            pts = arc_points(el.cx, el.cy, el.r, el.a0, el.a1, 4)
            if len(pts) > 1:
                i0, j0, i1, j1 = to_px(bbox_grow(bbox_of(pts), el.width / 2))
                sub = mask[j0:j1, i0:i1]
                X = gx[i0:i1][None, :]
                Y = gy[j0:j1][:, None]
                prev = pts[0]
                for cur in pts[1:]:
                    ax, ay = prev
                    bx, by = cur
                    dx, dy = bx - ax, by - ay
                    l2 = dx * dx + dy * dy
                    t = 0.0 if l2 < 1e-12 else np.clip(((X - ax) * dx + (Y - ay) * dy) / l2, 0, 1)
                    d = np.hypot(X - (ax + t * dx), Y - (ay + t * dy))
                    sub |= d <= el.width / 2 + cell * 0.5
                    prev = cur
    elif isinstance(el, (PolygonEl,)):
        if el.hatched:
            pts = list(el.points)
            for i in range(len(pts)):
                a = pts[i]
                b = pts[(i + 1) % len(pts)]
                i0, j0, i1, j1 = to_px(bbox_grow((min(a[0], b[0]), min(a[1], b[1]),
                                                   max(a[0], b[0]), max(a[1], b[1])), el.contour))
                sub = mask[j0:j1, i0:i1]
                X = gx[i0:i1][None, :]
                Y = gy[j0:j1][:, None]
                ax, ay = a
                bx, by = b
                dx, dy = bx - ax, by - ay
                l2 = dx * dx + dy * dy
                t = 0.0 if l2 < 1e-12 else np.clip(((X - ax) * dx + (Y - ay) * dy) / l2, 0, 1)
                d = np.hypot(X - (ax + t * dx), Y - (ay + t * dy))
                sub |= d <= el.contour / 2 + cell * 0.5
        else:
            i0, j0, i1, j1 = to_px(el.bbox())
            sub = mask[j0:j1, i0:i1]
            sub |= polygon_fill_mask(el.points, el.bbox(), cell, (gx[i0:i1], gy[j0:j1]))
    elif isinstance(el, RectEl):
        i0, j0, i1, j1 = to_px(el.bbox())
        sub = mask[j0:j1, i0:i1]
        if el.filled:
            sub |= ((np.abs(gx[i0:i1][None, :] - (el.x0 + el.x1) / 2) <= abs(el.x1 - el.x0) / 2 + cell * 0.5)
                    & (np.abs(gy[j0:j1][:, None] - (el.y0 + el.y1) / 2) <= abs(el.y1 - el.y0) / 2 + cell * 0.5))
        else:
            X = gx[i0:i1][None, :]
            Y = gy[j0:j1][:, None]
            for a, b in ((0, 1), (1, 2), (2, 3), (3, 0)):
                pa = el.points()[a]
                pb = el.points()[b]
                ax, ay = pa
                bx, by = pb
                dx, dy = bx - ax, by - ay
                l2 = dx * dx + dy * dy
                t = 0.0 if l2 < 1e-12 else np.clip(((X - ax) * dx + (Y - ay) * dy) / l2, 0, 1)
                d = np.hypot(X - (ax + t * dx), Y - (ay + t * dy))
                sub |= d <= el.width / 2 + cell * 0.5
    elif isinstance(el, FillEl):
        i0, j0, i1, j1 = to_px(el.bbox())
        sub = mask[j0:j1, i0:i1]
        for r in el.rects:
            ii0, jj0, ii1, jj1 = to_px(tuple(r))
            a = max(i0, ii0) - i0
            b = max(j0, jj0) - j0
            c = min(i1, ii1) - i0
            d = min(j1, jj1) - j0
            if c > a and d > b:
                sub[b:d, a:c] = True
    else:
        return None
    if not mask.any():
        return None
    return (i0, j0, i1, j1), mask[j0:j1, i0:i1]


def board_region_mask(board: Board, layer: str, grid, cell: float) -> np.ndarray:
    """Область внутри контура платы.

    Приоритет: залитый полигон/прямоугольник на слое О → иначе габариты платы
    (прямоугольник или круг, если плата круглая).
    """
    gx, gy = grid
    mask = np.zeros((len(gy), len(gx)), dtype=bool)
    region_poly = None
    for el in board.elements.values():
        if el.layer != "O" or el.kind == "fill":
            continue
        if isinstance(el, PolygonEl) and not el.hatched and not el.negative:
            region_poly = list(el.points)
        elif isinstance(el, RectEl) and el.filled and not el.negative:
            region_poly = el.points()
    if region_poly is None:
        region_poly = board.outline_points()
    b = bbox_of(region_poly)
    i0 = max(0, int((b[0] - gx[0]) / cell))
    j0 = max(0, int((b[1] - gy[0]) / cell))
    i1 = min(len(gx), int((b[2] - gx[0]) / cell) + 1)
    j1 = min(len(gy), int((b[3] - gy[0]) / cell) + 1)
    if i1 <= i0 or j1 <= j0:
        return mask
    mask[j0:j1, i0:i1] |= polygon_fill_mask(region_poly, b, cell, (gx[i0:i1], gy[j0:j1]))
    return mask


def compute_fill(board: Board, layer: str, clearance: float = 0.25,
                 thermal_gap: float = 0.4, spoke_width: float = 0.5,
                 spoke_dirs: Tuple[bool, bool, bool, bool] = (True, True, True, True),
                 per_element_clearance: bool = False,
                 progress=None) -> FillEl:
    """Построить элемент металлизации для слоя."""
    t0 = time.time()
    
    boxes = []
    outline_pts = board.outline_points()
    boxes.append(bbox_of(outline_pts))
    for el in board.elements.values():
        b = el.bbox()
        if b and el.kind != "fill":
            boxes.append(b)
    region = bbox_union(boxes, board.outline_rect())
    margin = max(2.0, clearance * 4)
    region = bbox_grow(region, margin)
    region = (max(region[0], board.outline_rect()[0] - margin), max(region[1], board.outline_rect()[1] - margin),
              min(region[2], board.outline_rect()[2] + margin), min(region[3], board.outline_rect()[3] + margin))
    cell = max(0.02, min(0.1, clearance / 2.0))
    nx = int((region[2] - region[0]) / cell) + 2
    ny = int((region[3] - region[1]) / cell) + 2
    if nx * ny > 40_000_000:
        cell *= math.sqrt(nx * ny / 40_000_000)
        nx = int((region[2] - region[0]) / cell) + 2
        ny = int((region[3] - region[1]) / cell) + 2
    gx = region[0] + np.arange(nx) * cell
    gy = region[1] + np.arange(ny) * cell
    grid = (gx, gy)

    region_mask = board_region_mask(board, layer, grid, cell)
    if not region_mask.any():
        return FillEl(layer=layer, rects=[])

    keep = np.zeros((ny, nx), dtype=bool)     
    max_clr = clearance

    conducts = [el for el in board.elements.values()
                if el.kind in ("track", "pad", "smd", "circle", "poly", "rect")
                and not el.negative and el.layer != "O"]
    negs = [el for el in board.elements.values() if el.negative and el.kind != "conn"]

    total = max(1, len(conducts) + len(negs))
    done = 0
    for el in conducts:
        if isinstance(el, Pad):
            layers = el.copper_layers()
        else:
            layers = [el.layer]
        if layer not in layers:
            done += 1
            continue
        clr = clearance
        if per_element_clearance:
            clr = getattr(el, "clearance", clearance) or clearance
            clr = max(0.0, clr)
        r = element_raster(el, layer, grid, cell)
        if r:
            (i0, j0, i1, j1), sub = r
            view = keep[j0:j1, i0:i1]
            if clr > 1e-6:
                rclr = int(round(clr / cell))
                view |= dilate(sub, rclr)
            else:
                view |= sub
        max_clr = max(max_clr, clr)
        done += 1
        if progress and done % 20 == 0:
            progress(done, total)

    cut = np.zeros((ny, nx), dtype=bool)      
    for el in negs:
        layers = el.copper_layers() if isinstance(el, Pad) else [el.layer]
        if layer not in layers:
            continue
        r = element_raster(el, layer, grid, cell)
        if r:
            (i0, j0, i1, j1), sub = r
            cut[j0:j1, i0:i1] |= sub

    fill = region_mask & ~keep & ~cut

    
    spokes = np.zeros((ny, nx), dtype=bool)
    for el in conducts:
        if isinstance(el, Track):
            continue
        th = getattr(el, 'thermal', False)
        if isinstance(el, Pad) and el.thermal_layers:
            th = bool(el.thermal_layers.get(layer, el.thermal))
        if not th:
            continue
        r = element_raster(el, layer, grid, cell)
        if not r:
            continue
        (i0, j0, i1, j1), sub = r
        gap_r = max(1, int(round(thermal_gap / cell)))
        ring = dilate(sub, gap_r) & ~sub
        fill[j0:j1, i0:i1] &= ~ring
        cx, cy = el.x, el.y
        w, h = el.outer() if isinstance(el, Pad) else (el.w, el.h)
        sw = max(cell * 1.2, spoke_width)
        dirs = spoke_dirs
        rad = max(w, h) / 2 + thermal_gap + sw
        if dirs[0]:
            spokes |= _band(grid, (cx - rad, cy - sw / 2), (cx, cy + sw / 2))
        if dirs[1]:
            spokes |= _band(grid, (cx, cy - sw / 2), (cx + rad, cy + sw / 2))
        if dirs[2]:
            spokes |= _band(grid, (cx - sw / 2, cy - rad), (cx + sw / 2, cy))
        if dirs[3]:
            spokes |= _band(grid, (cx - sw / 2, cy), (cx + sw / 2, cy + rad))
    fill |= spokes & region_mask

    rects = mask_to_rects(fill, gx, gy)
    rects = [r for r in rects if (r[2] - r[0]) > cell * 1.2 and (r[3] - r[1]) > cell * 1.2]
    if progress:
        progress(total, total)
    el_fill = FillEl(layer=layer, rects=[list(r) for r in rects])
    el_fill.no_drc = True
    el_fill.cell = cell
    return el_fill


def _band(grid, a, b) -> np.ndarray:
    gx, gy = grid
    x0, y0 = a
    x1, y1 = b
    i0 = max(0, int((x0 - gx[0]) / (gx[1] - gx[0] if len(gx) > 1 else 1)))
    i1 = min(len(gx), int((x1 - gx[0]) / (gx[1] - gx[0] if len(gx) > 1 else 1)) + 1)
    j0 = max(0, int((y0 - gy[0]) / (gy[1] - gy[0] if len(gy) > 1 else 1)))
    j1 = min(len(gy), int((y1 - gy[0]) / (gy[1] - gy[0] if len(gy) > 1 else 1)) + 1)
    out = np.zeros((len(gy), len(gx)), dtype=bool)
    if i1 > i0 and j1 > j0:
        out[j0:j1, i0:i1] = True
    return out


def fill_stats(el: FillEl) -> Dict[str, float]:
    area = sum((r[2] - r[0]) * (r[3] - r[1]) for r in el.rects)
    return {"rects": len(el.rects), "area": area}