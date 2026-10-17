"""РРјРїРѕСЂС‚ Gerber RS-274X Рё Excellon, Р·Р°РіСЂСѓР·РєР° С„РѕРЅРѕРІРѕРіРѕ С€Р°Р±Р»РѕРЅР°."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .geom import INCH, arc_points
from .model import (Board, CircleEl, Element, Pad, PolygonEl, RectEl, SmdPad,
                    TOP_KEY, Track)


@dataclass
class Aperture:
    code: int
    kind: str
    params: Dict[str, float] = field(default_factory=dict)

    @property
    def w(self) -> float:
        return self.params.get("w", self.params.get("d", 0.1))

    @property
    def h(self) -> float:
        return self.params.get("h", self.params.get("d", 0.1))

    @property
    def d(self) -> float:
        return self.params.get("d", 0.1)


class GerberImportError(Exception):
    pass


def _parse_coord(tok: str, fmt_dec: int, unit: str) -> float:
    """Разбор координаты с фиксированным форматом (X46 → 4 целых, 6 дробных)."""
    tok = tok.strip()
    if not tok:
        return 0.0
    sign = -1.0 if tok.startswith("-") else 1.0
    tok = tok.lstrip("+-")
    if "." in tok:
        val = float(tok)
    elif fmt_dec > 0 and len(tok) > fmt_dec:
        val = float(tok[:-fmt_dec] + "." + tok[-fmt_dec:])
    else:
        val = float(tok) / (10 ** fmt_dec) if fmt_dec > 0 else float(tok)
    return sign * (val if unit == "mm" else val * INCH)


_AP_RE = re.compile(r"%ADD(\d+)([A-Za-z_$.][A-Za-z0-9_$.\-]*),?([^*]*)\*%")
_FS_RE = re.compile(r"%FSLAX(\d)(\d)Y(\d)(\d)\*%")
_MO_RE = re.compile(r"%MO(MM|IN)\*%")


def import_gerber(text: str, layer: str = TOP_KEY) -> List[Element]:
    """Разобрать Gerber RS-274X в элементы e-cad (упрощённо, без G36/G37)."""
    lines = text.splitlines()
    unit = "mm"
    fmt_int, fmt_dec = 4, 6
    aps: Dict[int, Aperture] = {}
    out: List[Element] = []
    x = y = 0.0
    cur_ap: Optional[Aperture] = None
    clear = False
    start: Optional[Tuple[float, float]] = None
    pts: List[Tuple[float, float]] = []
    region = False

    def flush():
        nonlocal pts, start
        if len(pts) > 1:
            out.append(Track(layer=layer, points=list(pts), width=cur_ap.w if cur_ap else 0.1,
                             negative=clear))
        elif len(pts) == 1 and cur_ap and cur_ap.d > 0.05:
            out.append(Pad(layer=layer, x=pts[0][0], y=pts[0][1],
                           pad_dia=max(cur_ap.d, 0.6), hole_dia=0.0))
        pts = []
        start = None

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("%FS"):
            m = _FS_RE.search(line)
            if m:
                fmt_int, fmt_dec = int(m.group(1)), int(m.group(2))
            continue
        if line.startswith("%MO"):
            m = _MO_RE.search(line)
            if m:
                unit = "mm" if m.group(1) == "MM" else "inch"
            continue
        if line.startswith("%AD"):
            m = _AP_RE.search(line)
            if m:
                code = int(m.group(1))
                shape = m.group(2)
                args = [a for a in m.group(3).split("X") if a.strip()]
                p: Dict[str, float] = {}
                try:
                    if shape.startswith("C"):
                        p["d"] = _parse_coord(args[0], fmt_dec, unit) if args else 0.1
                    elif shape.startswith("R"):
                        p["w"] = _parse_coord(args[0], fmt_dec, unit) if args else 0.1
                        p["h"] = _parse_coord(args[1], fmt_dec, unit) if len(args) > 1 else p.get("w", 0.1)
                    elif shape.startswith("O") or shape.startswith("P"):
                        p["w"] = _parse_coord(args[0], fmt_dec, unit) if args else 0.1
                        p["h"] = _parse_coord(args[1], fmt_dec, unit) if len(args) > 1 else p.get("w", 0.1)
                    else:
                        p["d"] = _parse_coord(args[0], fmt_dec, unit) if args else 0.1
                except ValueError:
                    p["d"] = 0.1
                aps[code] = Aperture(code, shape[0], p)
            continue
        if line.startswith("G04") or line.startswith("G4") or line.startswith("M02") or line.startswith("M2"):
            continue
        if line.startswith("G36"):
            region = True
            flush()
            start = (x, y)
            pts = [(x, y)]
            continue
        if line.startswith("G37"):
            flush()
            region = False
            continue
        if line.startswith("LP"):
            clear = "C" in line.upper()
            continue
        if line.startswith("G01") or line.startswith("G02") or line.startswith("G03"):
            continue
        if line.startswith("G54") or line.startswith("G55") or line.startswith("G70") or line.startswith("G71"):
            continue
        
        for token in re.findall(r"D(\d+)", line):
            code = int(token)
            if code >= 10:
                cur_ap = aps.get(code)
                if pts:
                    flush()
                    if start is None:
                        start = (x, y)
                continue
            if code in (1, 2, 3):
                m = re.search(r"X(-?\d+)", line)
                if m:
                    x = _parse_coord(m.group(1), fmt_dec, unit)
                m = re.search(r"Y(-?\d+)", line)
                if m:
                    y = -_parse_coord(m.group(1), fmt_dec, unit)
                if code == 1:
                    pts.append((x, y))
                elif code == 2:
                    if pts:
                        flush()
                    start = (x, y)
                elif code == 3:
                    if cur_ap and cur_ap.kind in ("C", "O", "P"):
                        if cur_ap.kind == "C":
                            out.append(Pad(layer=layer, x=x, y=y, pad_dia=cur_ap.d,
                                           hole_dia=0.0))
                        else:
                            out.append(SmdPad(layer=layer, x=x, y=y, w=cur_ap.w, h=cur_ap.h))
                    elif cur_ap:
                        out.append(Pad(layer=layer, x=x, y=y, pad_dia=cur_ap.d, hole_dia=0.0))
        if "X" in line or "Y" in line:
            m = re.search(r"X(-?\d+)", line)
            if m:
                x = _parse_coord(m.group(1), fmt_dec, unit)
            m = re.search(r"Y(-?\d+)", line)
            if m:
                y = -_parse_coord(m.group(1), fmt_dec, unit)
    flush()
    if region and len(pts) > 2:
        out.append(PolygonEl(layer=layer, points=pts))
    return out


def _num_simple(tok: str, unit: str, fmt: Tuple[int, int]) -> float:
    return _parse_coord(tok, fmt[1], unit)



def import_excellon(text: str, unit_hint: str = "", side: str = "top",
                    plate: Optional[Board] = None, auto_vias: bool = False) -> List[Pad]:
    """Разобрать файл сверловки Excellon → контакты-переходные отверстия."""
    lines = text.splitlines()
    unit = unit_hint
    fmt = (3, 3)
    tool: Optional[float] = None
    tools: Dict[str, float] = {}
    out: List[Pad] = []
    metric_header = False

    def parse_coord(tok: str) -> float:
        sign = -1 if tok.startswith("-") else 1
        tok = tok.lstrip("+-")
        if "." in tok:
            val = float(tok)
        else:
            i, f = fmt
            if len(tok) >= i:
                val = float(tok[:-i] + "." + tok[-i:]) if i > 0 else float(tok)
            else:
                val = float(tok) / (10 ** i)
        return sign * val

    for raw in lines:
        line = raw.split(";")[0].strip()
        if not line:
            continue
        up = line.upper()
        if up.startswith("METRIC"):
            unit = "mm"
            metric_header = True
            continue
        if up.startswith("INCH"):
            unit = "inch"
            continue
        if up.startswith("M48") or up.startswith("M95") or up.startswith("M30"):
            continue
        m = re.match(r"^T(\d+)C([\d.]+)", up)
        if m:
            tools[m.group(1)] = float(m.group(2))
            tool = float(m.group(2))
            continue
        m = re.match(r"^T(\d+)$", up)
        if m:
            tool = tools.get(m.group(1))
            continue
        m = re.search(r"X(-?[\d.]+)\s*Y(-?[\d.]+)", up)
        if m and tool is not None:
            x = parse_coord(m.group(1))
            y = parse_coord(m.group(2))
            if unit == "inch":
                x *= INCH
                y *= INCH
            dia = tool
            out.append(Pad(layer=TOP_KEY if side == "top" else "M2", x=x, y=-y,
                           pad_dia=max(dia + 0.6, 1.0), hole_dia=dia, plated=True))
    if unit is None:
        raise GerberImportError("Не удалось определить единицы файла сверловки")
    return out



def load_template_image(path: str, dpi: Optional[int] = None):
    from PySide6.QtGui import QImage
    img = QImage(path)
    if img.isNull():
        raise GerberImportError("Не удалось загрузить изображение")
    return img


def guess_dpi(img, width_mm: float = 0.0) -> int:
    if width_mm > 0 and img.width() > 0:
        return int(round(img.width() / (width_mm / 25.4)))
    return 300