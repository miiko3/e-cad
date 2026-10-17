"""Экспорт: Gerber RS-274X, Excellon, HPGL, Pick+Place, BOM, текстовый IO."""
from __future__ import annotations

import math
import os
import time
from typing import Dict, List, Optional, Sequence, Tuple

from .geom import INCH, MIL, arc_points, bbox_of, rdp
from .model import (ALL_LAYERS, BOTTOM_KEY, COPPER_KEYS, LAYER_BY_KEY, TOP_KEY,
                    Board, CircleEl, Component, Connection, Element, FillEl,
                    Pad, PolygonEl, RectEl, SmdPad, TextEl, Track, nets)

GERBER_COMPOSITION = {
    TOP_KEY: ("copper_top", "М1 — верхняя медь"),
    BOTTOM_KEY: ("copper_bottom", "М2 — нижняя медь"),
    "V1": ("copper_in1_top", "В1 — внутренняя медь"),
    "V2": ("copper_in2_bottom", "В2 — внутренняя медь"),
    "K1": ("silkscreen_top", "К1 — маркировка сверху"),
    "K2": ("silkscreen_bottom", "К2 — маркировка снизу"),
    "O": ("outline", "О — контур"),
}
MASK_TOP = ("soldermask_top", "Маска сверху")
MASK_BOTTOM = ("soldermask_bottom", "Маска снизу")
PASTE_TOP = ("paste_top", "Трафарет под пасту (SMD)")


_TRANS = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "—": "-", "–": "-", " ": "_", "№": "No.",
}


def ascii_safe(text: str) -> str:
    """Транслитерация кириллицы — файлы Gerber/Excellon должны быть в ASCII."""
    out = []
    for ch in text or "":
        low = ch.lower()
        rep = _TRANS.get(low)
        if rep is None:
            out.append(ch if ord(ch) < 128 else "_")
        else:
            out.append(rep.upper() if ch.isupper() else rep)
    return "".join(out)


def _f(v: float, digits: int = 4, commas: bool = False) -> str:
    s = f"{v:.{digits}f}"
    if commas:
        s = s.replace(".", ",")
    return s



class GerberWriter:
    def __init__(self, mirror: bool = False, header_comment: str = "e-cad"):
        self.apertures: Dict[str, float] = {}
        self.ap_list: List[Tuple[str, dict]] = []
        self.body: List[str] = []
        self.current: Optional[str] = None
        self.mirror = mirror

    def aperture(self, spec: Tuple[str, dict]) -> str:
        key = repr(spec)
        if key not in self.apertures:
            code = 10 + len(self.ap_list)
            self.apertures[key] = code
            self.ap_list.append((key, spec))
        return f"D{self.apertures[key]}"

    
    def flash(self, code: str, x: float, y: float):
        self.body.append(f"{code}*")
        self.body.append(f"X{_f(x)}Y{_f(-y)}D03*")

    def draw(self, code: str, pts: Sequence[Tuple[float, float]]):
        if len(pts) < 2:
            return
        self.body.append(f"{code}*")
        x, y = pts[0]
        self.body.append(f"X{_f(x)}Y{_f(-y)}D02*")
        for x, y in pts[1:]:
            self.body.append(f"X{_f(x)}Y{_f(-y)}D01*")

    def region(self, polys: Sequence[Sequence[Tuple[float, float]]]):
        self.body.append("G36*")
        for poly in polys:
            if len(poly) < 3:
                continue
            x, y = poly[0]
            self.body.append(f"X{_f(x)}Y{_f(-y)}D02*")
            for x, y in poly[1:]:
                self.body.append(f"X{_f(x)}Y{_f(-y)}D01*")
            self.body.append(f"X{_f(poly[0][0])}Y{_f(-poly[0][1])}D01*")
        self.body.append("G37*")

    def polarity(self, clear: bool):
        self.body.append("LPC*" if clear else "LPD*")

    def render(self, board_name: str = "") -> str:
        out: List[str] = []
        out.append(f"G04 e-cad Gerber RS-274X*")
        out.append(f"G04 {ascii_safe(board_name)}*")
        out.append(f"G04 {time.strftime('%Y-%m-%d %H:%M:%S')}*")
        out.append("%FSLAX46Y46*%")
        out.append("%MOMM*%")
        out.append("%LPD*%")
        out.append("G01*")
        for key, spec in self.ap_list:
            out.append(f"%ADD{self.apertures[key]}{spec[0]},{_ap_params(spec)}*%")
        out.extend(self.body)
        out.append("M02*")
        return "\n".join(out) + "\n"


def _ap_params(spec: Tuple[str, dict]) -> str:
    t, p = spec
    if t == "C":
        return _f(p.get("d", 0.1), 5)
    if t == "R":
        return f"X{_f(p.get('w', 0.1))}Y{_f(p.get('h', 0.1))}"
    if t == "O":
        return f"X{_f(p.get('w', 0.1))}Y{_f(p.get('h', 0.1))}"
    if t == "P":
        return f"X{_f(p.get('d', 1.0))}X{_f(p.get('w', 0.1))}"
    return "0.1"


def _pts(el: Element) -> List[Tuple[float, float]]:
    if isinstance(el, Track):
        return [(x, y) for x, y in el.points]
    if isinstance(el, PolygonEl):
        if el.hatched:
            return [(x, y) for x, y in el.points]
        return list(el.points) + [el.points[0]] if el.points else []
    if isinstance(el, RectEl):
        pts = el.points()
        return pts + [pts[0]]
    if isinstance(el, CircleEl):
        return arc_points(el.cx, el.cy, el.r, el.a0, el.a1, 6)
    return []


def gerber_layer(board: Board, layer: str, mirror: bool = False,
                 add_outline: bool = False, open_holes: bool = True,
                 hole_center: float = 0.0, mask_tht: float = 0.15,
                 mask_smd: float = 0.1, mask_other: float = 0.0,
                 invert_mask: bool = False, outline_in_mask: bool = True,
                 mask_mode: str = "") -> str:
    """Сформировать Gerber-файл одного слоя. mask_mode: '' | 'solder' | 'paste'."""
    gw = GerberWriter(mirror)
    elements = [el for el in board.elements.values() if el.layer == layer and el.kind != "conn"]

    if mask_mode == "solder":
        _gerber_mask(gw, board, elements, layer, mask_tht, mask_smd, mask_other,
                     invert_mask, outline_in_mask)
    elif mask_mode == "paste":
        _gerber_paste(gw, elements, mask_smd)
    else:
        _gerber_copper(gw, elements, layer, open_holes, hole_center)

    if add_outline:
        for el in board.elements.values():
            if el.layer == "O" and el.kind in ("poly", "rect", "track", "circle"):
                if el.kind in ("poly", "rect"):
                    gw.region([el.points() if isinstance(el, PolygonEl) else el.points()])
                else:
                    _emit_polyline(gw, el)
    return gw.render(board.name)


def _emit_polyline(gw: GerberWriter, el: Element):
    if isinstance(el, Track):
        code = gw.aperture(("C", {"d": el.width}))
        gw.draw(code, el.points)
    elif isinstance(el, CircleEl):
        code = gw.aperture(("C", {"d": el.width}))
        gw.draw(code, arc_points(el.cx, el.cy, el.r, el.a0, el.a1, 6))
    elif isinstance(el, PolygonEl):
        code = gw.aperture(("C", {"d": el.contour}))
        gw.draw(code, el.points + [el.points[0]])
    elif isinstance(el, RectEl):
        code = gw.aperture(("C", {"d": el.width}))
        pts = el.points()
        gw.draw(code, pts + [pts[0]])


def _gerber_copper(gw: GerberWriter, elements, layer: str, open_holes: bool, hole_center: float):
    for el in elements:
        if el.kind == "fill":
            grow = (getattr(el, "cell", 0.0) or 0.0) * 0.85
            for r in el.rects:
                x0, y0, x1, y1 = r[0] - grow, r[1] - grow, r[2] + grow, r[3] + grow
                gw.region([[(x0, y0), (x1, y0), (x1, y1), (x0, y1)]])
            continue
        if isinstance(el, Pad):
            layers = el.copper_layers()
            if layer in layers and not open_holes:
                _flash_pad(gw, el)
            elif layer in layers:
                _flash_pad_ring(gw, el, hole_center)
        elif isinstance(el, SmdPad):
            if el.layer == layer:
                _flash_smd(gw, el)
        else:
            if el.negative:
                continue
            _emit_polyline(gw, el)
            if isinstance(el, (PolygonEl, RectEl, CircleEl)) and getattr(el, "filled", False):
                gw.region([_fill_poly(el)])


def _fill_poly(el: Element) -> List[Tuple[float, float]]:
    if isinstance(el, PolygonEl):
        return list(el.points)
    if isinstance(el, RectEl):
        return el.points()
    if isinstance(el, CircleEl):
        return arc_points(el.cx, el.cy, el.r, 0, 360, 8)
    return []


def _flash_pad(gw: GerberWriter, el: Pad):
    w, h = el.outer()
    if el.shape == "circle":
        gw.flash(gw.aperture(("C", {"d": w})), el.x, el.y)
    elif el.shape == "rect":
        gw.region([[(el.x - w / 2, el.y - h / 2), (el.x + w / 2, el.y - h / 2),
                    (el.x + w / 2, el.y + h / 2), (el.x - w / 2, el.y + h / 2)]])
    else:
        gw.flash(gw.aperture(("O", {"w": w, "h": h})), el.x, el.y)


def _flash_pad_ring(gw: GerberWriter, el: Pad, hole_center: float):
    """Площадка с открытым отверстием: область минус окружность отверстия."""
    w, h = el.outer()
    hole = max(el.hole_dia, 0.05)
    outer: List[Tuple[float, float]]
    if el.shape == "rect":
        outer = [(el.x - w / 2, el.y - h / 2), (el.x + w / 2, el.y - h / 2),
                 (el.x + w / 2, el.y + h / 2), (el.x - w / 2, el.y + h / 2)]
    else:
        outer = arc_points(el.x, el.y, w / 2, 0, 360, 8)
    inner = arc_points(el.x, el.y, hole / 2, 0, 360, 8)
    gw.region([outer])
    gw.polarity(True)
    gw.flash(gw.aperture(("C", {"d": hole})), el.x, el.y)
    if hole_center > 0:
        gw.flash(gw.aperture(("C", {"d": hole_center})), el.x, el.y)
    gw.polarity(False)


def _flash_smd(gw: GerberWriter, el: SmdPad):
    if el.shape == "circle":
        gw.flash(gw.aperture(("C", {"d": el.w})), el.x, el.y)
    else:
        gw.region([[(el.x - el.w / 2, el.y - el.h / 2), (el.x + el.w / 2, el.y - el.h / 2),
                    (el.x + el.w / 2, el.y + el.h / 2), (el.x - el.w / 2, el.y + el.h / 2)]])


def _gerber_mask(gw: GerberWriter, board: Board, elements, layer: str,
                 gap_tht: float, gap_smd: float, gap_other: float,
                 invert: bool, outline_in_mask: bool):
    """Маска: контур платы (тёмное) + окна (светлое)."""
    outline = board.outline_points()
    if not outline_in_mask:
        outline = []
    if not invert:
        gw.region([outline])
        gw.polarity(True)
    else:
        gw.polarity(False)
    for el in elements:
        if isinstance(el, Pad) and layer in el.copper_layers():
            w, h = el.outer()
            gw.flash(gw.aperture(("C", {"d": w + 2 * gap_tht})), el.x, el.y)
        elif isinstance(el, SmdPad) and el.layer == layer:
            gw.region([[(el.x - el.w / 2 - gap_smd, el.y - el.h / 2 - gap_smd),
                        (el.x + el.w / 2 + gap_smd, el.y - el.h / 2 - gap_smd),
                        (el.x + el.w / 2 + gap_smd, el.y + el.h / 2 + gap_smd),
                        (el.x - el.w / 2 - gap_smd, el.y + el.h / 2 + gap_smd)]])
        elif el.mask_open and el.kind not in ("fill",):
            pts = _fill_poly(el)
            if len(pts) > 2:
                gw.region([pts])
    gw.polarity(False)


def _gerber_paste(gw: GerberWriter, elements, gap: float):
    for el in elements:
        if isinstance(el, SmdPad) and el.layer in COPPER_KEYS:
            gw.region([[(el.x - el.w / 2 - gap, el.y - el.h / 2 - gap),
                        (el.x + el.w / 2 + gap, el.y - el.h / 2 - gap),
                        (el.x + el.w / 2 + gap, el.y + el.h / 2 + gap),
                        (el.x - el.w / 2 - gap, el.y + el.h / 2 + gap)]])
    for el in elements:
        if isinstance(el, Pad) and el.plated and el.hole_dia < el.pad_dia * 0.6:
            w, h = el.outer()
            gw.flash(gw.aperture(("C", {"d": w})), el.x, el.y)


def export_gerber_set(board: Board, folder: str, layers: Sequence[str],
                      base_name: str = "", mirror: Tuple[str, ...] = (),
                      add_outline: bool = False, open_holes: bool = True,
                      hole_center: float = 0.0, mask_tht: float = 0.15,
                      mask_smd: float = 0.1, mask_other: float = 0.0,
                      invert_mask: bool = False, solder_mask: bool = True,
                      paste_mask: bool = True, composition: Optional[Dict[str, tuple]] = None,
                      log=None) -> List[str]:
    """Создать набор Gerber-файлов по слоям. Возвращает список имён файлов."""
    comp = dict(GERBER_COMPOSITION)
    if composition:
        comp.update(composition)
    made: List[str] = []

    def save(fn: str, text: str, note: str = ""):
        with open(os.path.join(folder, fn), "w", encoding="ascii") as f:
            f.write(text)
        made.append(fn)
        if log:
            log(f"  {fn} — {note or str(len(text.splitlines())) + ' строк'}")

    for lk in layers:
        name = comp.get(lk, (lk.lower(), lk))[0]
        try:
            text = gerber_layer(board, lk, mirror=lk in mirror, add_outline=add_outline,
                                open_holes=open_holes, hole_center=hole_center)
            save(f"{base_name}_{name}.gbr", text, comp.get(lk, (lk,))[1])
        except Exception as e:  
            if log:
                log(f"  ошибка слоя {lk}: {e}")

    if solder_mask:
        for side, lk in (("top", TOP_KEY), ("bottom", BOTTOM_KEY)):
            try:
                text = gerber_layer(board, lk, mask_mode="solder", mask_tht=mask_tht,
                                    mask_smd=mask_smd, mask_other=mask_other,
                                    invert_mask=invert_mask)
                save(f"{base_name}_{'soldermask_' + side}.gbr", text, f"маска {side}")
            except Exception as e:  
                if log:
                    log(f"  ошибка маски {side}: {e}")

    if paste_mask:
        try:
            text = gerber_layer(board, TOP_KEY, mask_mode="paste", mask_smd=mask_smd)
            save(f"{base_name}_paste_top.gbr", text, "трафарет под пасту (SMD)")
        except Exception as e:  
            if log:
                log(f"  ошибка пасты: {e}")
    return made



def excellon(board: Board, side: str = "top", only_plated: bool = True,
             unit: str = "mm", int_digits: int = 3, dec_digits: int = 3,
             strip_zeros: bool = False, comma: bool = False,
             sort_by_dia: bool = True, metal_separate: bool = True,
             m71: bool = False, g90: bool = False, comments: bool = True,
             mirror: Optional[bool] = None) -> str:
    holes: List[Tuple[float, float, float]] = []
    metal: List[Tuple[float, float, float]] = []
    for el in board.elements.values():
        if not isinstance(el, Pad) or el.hole_dia <= 0:
            continue
        (metal if el.plated else holes).append((el.x, el.y, el.hole_dia))

    if metal_separate:
        groups = [("PTH", sorted(metal, key=lambda h: -h[2]))]
        groups.append(("NPTH", sorted(holes, key=lambda h: -h[2])))
    else:
        groups = [("ALL", sorted(metal + holes, key=lambda h: -h[2]))]

    out: List[str] = []
    out: List[str] = []
    if comments:
        out.append("M48")
        out.append(f"; e-cad {time.strftime('%Y-%m-%d %H:%M:%S')}")
    out.append(("METRIC,LZ" if unit == "mm" else "INCH,LZ") if not m71
               else ("METRIC,TZ" if unit == "mm" else "INCH,TZ"))
    if g90:
        out.append("; G90")
    tools: Dict[float, int] = {}

    def tool_code(dia: float) -> str:
        d = round(dia, 4)
        if d not in tools:
            tools[d] = len(tools) + 1
            out.append(f"T{tools[d]:02d}C{d:.3f}")
        return f"T{tools[d]:02d}"

    for gname, items in groups:
        if not items:
            continue
        if metal_separate and comments:
            out.append(f"; ---- {gname} ----")
        cur_tool = None
        for x, y, d in items:
            tc = tool_code(d)
            if tc != cur_tool:
                out.append(tc)
                cur_tool = tc
            out.append("X" + _coord(x, int_digits, dec_digits, unit, strip_zeros) +
                       "Y" + _coord(y, int_digits, dec_digits, unit, strip_zeros))
    out.append("M30")
    return "\n".join(out) + "\n"


def _coord(v: float, idig: int, ddig: int, unit: str, strip: bool = False) -> str:
    val = v if unit == "mm" else v / INCH
    neg = val < 0
    s = f"{abs(val):.{ddig}f}".replace(".", "")
    if not strip:
        s = s.zfill(idig + ddig)
    return ("-" + s) if neg else s


def export_excellon(board: Board, folder: str, base_name: str = "", **kw) -> str:
    text = excellon(board, **kw)
    fn = f"{base_name}_drill.{'txt' if kw.get('unit', 'mm') == 'mm' else 'txt'}"
    with open(os.path.join(folder, fn), "w", encoding="ascii") as f:
        f.write(text)
    return fn



def hpgl(board: Board, mill_dia: float = 1.0, side: str = "top",
         drill_kerf: bool = False, passes: int = 1, overlap: float = 50.0,
         holes_mode: str = "all_one", contour: bool = True,
         marks: int = 2, marks_dist: float = 3.0, text_mode: str = "contour",
         selected: Optional[Sequence[str]] = None, min_feed: bool = False,
         scale_0025: bool = False) -> Tuple[str, List[str]]:
    unit = 400.0 if scale_0025 else 1015.0 / 25.4 / 10.0  
    scale = 40.0 if scale_0025 else 1000.0 / 25.4
    ops: List[str] = []
    log: List[str] = []

    def P(x, y):
        return f"PU{int(round(x * scale))},{int(round(y * scale))};"

    def to_px(x, y):
        return P(x, y)

    unit = 400.0 if scale_0025 else 1015.0 / 25.4 / 10.0  
    scale = 40.0 if scale_0025 else 1000.0 / 25.4
    ops: List[str] = []
    log: List[str] = []

    def to_px(x, y):
        return f"PU{int(round(x * scale))},{int(round(y * scale))};"

    ops.append("IN;SP1;")
    copper_layers = [TOP_KEY] if side == "top" else [BOTTOM_KEY]
    elements = [el for el in board.elements.values()
                if el.layer in copper_layers and el.kind != "conn" and not el.negative]
    if selected:
        elements = [el for el in elements if el.id in set(selected)]

    
    ops.append(f"SP{mill_dia:g};")
    log.append(f"РР·РѕР»РёСЂСѓСЋС‰РёРµ РґРѕСЂРѕР¶РєРё: С„СЂРµР·Р° {mill_dia:g} РјРј, {side}")
    for el in elements:
        w = _el_width(el)
        if w >= mill_dia * 0.999:
            continue
        if isinstance(el, Track):
            ops.append(to_px(*el.points[0]))
            ops.append("PD;")
            for p in el.points[1:]:
                ops.append(to_px(*p))
            ops.append("PU;")
        elif isinstance(el, FillEl):
            for r in el.rects:
                ops.append(to_px(r[0], r[1]))
                ops.append("PD;")
                ops.append(to_px(r[2], r[1]))
                ops.append(to_px(r[2], r[3]))
                ops.append(to_px(r[0], r[3]))
                ops.append(to_px(r[0], r[1]))
                ops.append("PU;")
    
    holes = [(el.x, el.y, el.hole_dia) for el in board.elements.values()
             if isinstance(el, Pad) and el.hole_dia > 0]
    if holes_mode == "all_one":
        log.append("Отверстия: фрезеровать одной фрезой (CI)")
        ops.append(f"CI{mill_dia:g};")
        ops.append(";")
    elif holes_mode == "one_dia":
        dia = holes[0][2] if holes else 0.8
        ops.append(f"PD{dia:g};")
        log.append(f"Сверлить PD {dia:g} мм")
    else:
        log.append("Сверлить PD требуемыми диаметрами")
        seen = set()
        for x, y, d in sorted(holes, key=lambda h: -h[2]):
            if round(d, 4) in seen:
                continue
            seen.add(round(d, 4))
            ops.append(f"PD{d:g};")
    for x, y, d in holes:
        ops.append(to_px(x, y))
        ops.append("PD;" if holes_mode != "all_one" else "CI;")
        ops.append(to_px(x, y))
        ops.append("PU;")
    
    if contour:
        pts = board.outline_points()
        ops.append("SP1;")
        ops.append(to_px(*pts[0]))
        ops.append("PD;")
        for p in pts[1:]:
            ops.append(to_px(*p))
        ops.append(to_px(*pts[0]))
        ops.append("PU;")
        log.append("Контур платы фрезеруется по слою О (по центру)")
    
    if marks:
        b = board.outline_rect()
        xs = [b[0] + marks_dist, b[2] - marks_dist]
        ys = [b[1] + marks_dist, b[3] - marks_dist]
        pts = [(xs[0], ys[0]), (xs[1], ys[1]), (b[0] + b[2]) / 2, (b[3] + ys[0]) / 2]
        pts = pts[:marks]
        ops.append("PD0.8;")
        for x, y in pts:
            ops.append(to_px(x, y))
            ops.append("PU;")
        log.append(f"Реперные метки: {marks} шт., отступ {marks_dist} мм")
    ops.append("PU;SP0;")
    return "\n".join(ops) + "\n", log


def _el_width(el: Element) -> float:
    if isinstance(el, Track):
        return el.width
    if isinstance(el, CircleEl):
        return el.r * 2 if el.filled else el.width
    if isinstance(el, (PolygonEl, RectEl, FillEl)):
        return 1e9
    return 0.0



DEFAULT_PNP_COLUMNS = [
    ("RefDes", "refdes"), ("Value", "value"), ("Comment", "comment"),
    ("Footprint", "footprint"), ("Layer", "side"),
    ("Center-X(mm)", "x"), ("Center-Y(mm)", "y"), ("Rotation", "rot"),
]


def pick_and_place(board: Board, columns: Optional[Sequence[Tuple[str, str]]] = None,
                   separator: str = "\t", decimals: int = 3,
                   rot_prefix: str = "R", units: str = "mm") -> str:
    cols = list(columns or DEFAULT_PNP_COLUMNS)
    lines = ["# e-cad Pick+Place", f"# Плата: {board.name}", f"# Единицы: {units}"]
    header = []
    for title, key in cols:
        if key in ("x", "y") and units == "mil":
            header.append(f"{title}(mil)")
        else:
            header.append(title)
    lines.append(separator.join(header))
    for c in board.components:
        if not c.refdes and not c.ids:
            continue
        vals = []
        for _title, key in cols:
            v = _pnp_value(board, c, key, units, decimals, rot_prefix)
            vals.append(str(v))
        lines.append(separator.join(vals))
    return "\n".join(lines) + "\n"


def _pnp_value(board: Board, c: Component, key: str, units: str, dec: int, rot_prefix: str):
    if key == "x":
        return _num(c.x, units, dec)
    if key == "y":
        return _num(c.y, units, dec)
    if key == "rot":
        r = c.rotation % 360
        if c.side == "bottom":
            r = (360 - r) % 360
        return f"{rot_prefix}{r:g}" if rot_prefix else f"{r:g}"
    if key == "side":
        return "Top" if c.side == "top" else "Bottom"
    return getattr(c, key, "") or ""


def _num(v: float, units: str, dec: int) -> str:
    if units == "mil":
        return f"{v / MIL:.{dec}f}"
    return f"{v:.{dec}f}"


def bom_table(board: Board, columns: Sequence[str] = ("refdes", "value", "footprint", "comment", "side")) -> Tuple[List[str], List[List[str]]]:
    head = []
    for c in columns:
        head.append({"refdes": "Обозначение", "value": "Номинал", "footprint": "Корпус",
                     "comment": "Комментарий", "side": "Сторона", "count": "Кол-во",
                     "pads": "Выводов"}.get(c, c))
    rows = []
    for c in board.components:
        row = []
        for k in columns:
            if k == "pads":
                row.append(str(len(c.ids)))
            else:
                row.append(str(getattr(c, k, "") or ""))
        rows.append(row)
    return head, rows


def bom_text(board: Board) -> str:
    head, rows = bom_table(board)
    lines = [f"Спецификация (BOM) — {board.name}", "\t".join(head)]
    for r in rows:
        lines.append("\t".join(r))
    return "\n".join(lines) + "\n"



def text_io(board: Board) -> str:
    out = [f"e-cad text-io 1.0", f"board {board.name}", f"size {board.width} {board.height}"]
    for el in board.elements.values():
        if el.kind == "conn":
            continue
        parts = [el.kind, el.layer]
        for k, v in el.to_dict().items():
            if k in ("kind", "layer"):
                continue
            parts.append(f"{k}={v}")
        out.append(" ".join(parts))
    return "\n".join(out) + "\n"


def ipc_name(kind: str, pitch: float, lead_w: float, body_l: float,
             body_t: float, height: float = 0.0) -> str:
    return (f"{kind}_{int(round(pitch * 100)):04d}_W{int(round(lead_w * 100)):02d}"
            f"_L{int(round(body_l * 100)):04d}_T{int(round(body_t * 100)):03d}"
            + (f"_H{int(round(height * 100)):04d}" if height else ""))
