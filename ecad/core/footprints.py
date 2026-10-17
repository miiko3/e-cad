"""Расширенная библиотека макросов (посадочные места из Sprint Layout)."""
from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..core.geom import MIL
from ..core.model import (Board, CircleEl, Element, Pad, PolygonEl, RectEl, SmdPad,
                           TextEl, TOP_KEY, Track)



def silk_rect(w: float, h: float, line: float = 0.2, pin1: bool = True) -> List[Element]:
    """Контур корпуса на слое маркировки + метка вывода №1."""
    els = [RectEl(layer="K1", x0=-w / 2, y0=-h / 2, x1=w / 2, y1=h / 2, width=line)]
    if pin1:
        els.append(CircleEl(layer="K1", cx=-w / 2, cy=-h / 2, r=line * 1.2, width=line))
    return els


def silk_line(x1: float, y1: float, x2: float, y2: float, line: float = 0.2) -> Track:
    return Track(layer="K1", points=[(x1, y1), (x2, y2)], width=line)


def silk_circle(x: float, y: float, r: float, line: float = 0.2) -> CircleEl:
    return CircleEl(layer="K1", cx=x, cy=y, r=r, width=line)


def silk_polygon(x: float, y: float, r: float, w: float, h: float, line: float = 0.2) -> PolygonEl:
    """Маркер поля полярности (треугольник) или скос угла."""
    return PolygonEl(layer="K1",
                     points=[(x - w / 2, y + h / 2), (x + w / 2, y + h / 2), (x, y - h / 2)],
                     contour=line)


def label(text: str, x: float = -1.6, y: float = -2.6, h: float = 1.2, th: float = 0.18,
          prefix: str = "R") -> TextEl:
    return TextEl(layer="K1", x=x, y=y, text=text, height=h, thickness=th, prefix=prefix)


def tht(x: float, y: float, dia: float = 1.6, hole: float = 0.9, square: bool = False) -> Pad:
    p = Pad(layer=TOP_KEY, x=x, y=y, pad_dia=dia, hole_dia=hole, mask_open=True,
            shape="rect" if square else "circle", size=(dia, dia))
    return p


def smd(x: float, y: float, w: float = 1.0, h: float = 1.4, shape: str = "rect") -> SmdPad:
    return SmdPad(layer=TOP_KEY, x=x, y=y, w=w, h=h, shape=shape, mask_open=True)


def dual_row(n: int, pitch: float, row_span: float, body_w: float, body_h: float,
             pad_w: float = 0.6, pad_h: float = 1.5, first_square: bool = True) -> List[Element]:
    """Двухрядный корпус (SOIC/TSSOP/SSOP/LQFP) с выводами по периметру."""
    els: List[Element] = []
    per = n // 2
    y0 = -(per - 1) / 2 * pitch
    for i in range(per):
        y = y0 + i * pitch
        sq = first_square and i == 0
        if sq:
            els.append(SmdPad(layer=TOP_KEY, x=-row_span / 2 - pad_h / 2 + pad_h / 2,
                              y=y, w=pad_h, h=pad_w, mask_open=True))
            els[-1] = SmdPad(layer=TOP_KEY, x=-row_span / 2, y=y, w=pad_h, h=pad_w,
                             mask_open=True)
            els.append(SmdPad(layer=TOP_KEY, x=row_span / 2, y=y, w=pad_h, h=pad_w,
                              mask_open=True))
        else:
            els.append(SmdPad(layer=TOP_KEY, x=-row_span / 2, y=y, w=pad_h, h=pad_w,
                              mask_open=True))
            els.append(SmdPad(layer=TOP_KEY, x=row_span / 2, y=y, w=pad_h, h=pad_w,
                              mask_open=True))
    els += silk_rect(body_w, body_h)
    return els


def quad(n: int, pitch: float, body_w: float, body_h: float, pad_w: float = 0.35,
         pad_h: float = 1.4) -> List[Element]:
    """Четырёхсторонний корпус (LQFP/TQFP/QFN)."""
    els: List[Element] = []
    per = n // 4
    x0 = -body_w / 2 + pad_h
    y0 = -body_h / 2 + pad_h
    for side in range(4):
        for i in range(per):
            t = (i + 0.5) / per
            if side == 0:
                x, y = -body_w / 2 + body_w * t, -body_h / 2
                els.append(smd(x, y, pad_w, pad_h))
            elif side == 1:
                x, y = body_w / 2, -body_h / 2 + body_h * t
                els.append(smd(x, y, pad_h, pad_w))
            elif side == 2:
                x, y = body_w / 2 - body_w * t, body_h / 2
                els.append(smd(x, y, pad_w, pad_h))
            else:
                x, y = -body_w / 2, body_h / 2 - body_h * t
                els.append(smd(x, y, pad_h, pad_w))
    els += silk_rect(body_w, body_h)
    els.append(silk_circle(-body_w / 2 + 0.6, -body_h / 2 + 0.6, 0.25, 0.2))
    return els


def chip_2terminal(pitch: float = 1.8, body_w: float = 1.6, body_h: float = 1.0,
                   pad_w: float = 1.1, pad_h: float = 1.4, text: str = "C",
                   prefix: str = "C") -> List[Element]:
    """Двухвыводный SMD (резистор, конденсатор 0805/0603/1206)."""
    els = [smd(-pitch / 2, 0, pad_w, pad_h), smd(pitch / 2, 0, pad_w, pad_h)]
    els += silk_rect(body_w, body_h)
    els.append(label(text, -body_w / 2 - 0.2, body_h / 2 + 1.0, 1.0, 0.15, prefix))
    return els


def chip_axial(pitch: float = 10.0, dia: float = 2.4, hole: float = 0.9) -> List[Element]:
    """Выводной (THT) двухвыводный элемент: резистор/конденсатор/диод."""
    return [tht(0, 0, dia, hole, square=True), tht(pitch, 0, dia, hole),
            silk_line(1.6, -dia / 2 - 0.4, 1.6, dia / 2 + 0.4, 0.2),
            silk_line(pitch - 1.6, -dia / 2 - 0.4, pitch - 1.6, dia / 2 + 0.4, 0.2),
            label("R", -1.2, -2.6, 1.2, 0.18, "R")]


def to_header(n: int, pitch: float = 2.54, dia: float = 1.6, hole: float = 0.9,
              rect: bool = True) -> List[Element]:
    """Однорядный штырьковый разъём (SIP)."""
    els = []
    for i in range(n):
        els.append(tht(i * pitch, 0, dia, hole, square=(rect and i == 0)))
    els.append(RectEl(layer="K1", x0=-1.6, y0=-1.6, x1=(n - 1) * pitch + 1.6, y1=1.6, width=0.2))
    els.append(silk_circle(0, -1.6, 0.25, 0.2))
    els.append(label("1", -1.8, 2.0, 1.2, 0.18, "J"))
    return els


def relay_two_wire(pitch: float = 5.0) -> List[Element]:
    return [tht(0, 0, 2.0, 0.9, square=True), tht(pitch, 0, 2.0, 0.9),
            *silk_rect(pitch + 2.0, 5.0),
            label("K", -1.0, -3.4, 1.5, 0.22, "K")]



def default_macros() -> List[Tuple[str, str, List[Element]]]:
    """(группа, имя, элементы) — стартовый набор библиотеки."""
    out: List[Tuple[str, str, List[Element]]] = []

    
    for code, bw, bh, pw, ph, pitch in (("0603", 1.6, 0.8, 0.9, 0.95, 1.5),
                                         ("0805", 2.0, 1.25, 1.0, 1.4, 1.9),
                                         ("1206", 3.2, 1.6, 1.2, 1.8, 3.0),
                                         ("2010", 5.0, 2.5, 1.4, 2.2, 4.2)):
        out.append(("Резисторы", f"Резистор {code} SMD",
                    chip_2terminal(pitch, bw, bh, pw, ph, "R", "R")))
    out.append(("Резисторы", "Резистор выводной 0,25 Вт", chip_axial()))
    out.append(("Резисторы", "Резистор подстроечный 3296W",
                [tht(0, 0, 1.8, 0.9), tht(2.54, 0, 1.8, 0.9), tht(5.08, 0, 1.8, 0.9),
                 *silk_rect(7.0, 4.5), label("R", -1.0, -3.2, 1.4, 0.2, "R")]))
    out.append(("Резисторы", "Резистор сети (SOIC-9, 4 резистора)",
                dual_row(8, 1.27, 5.4, 6.0, 4.0) + [label("RN", -1.4, -3.6, 1.2, 0.18, "RN")]))

    
    for code, bw, bh, pw, ph, pitch in (("0603", 1.6, 0.8, 0.9, 0.95, 1.5),
                                         ("0805", 2.0, 1.25, 1.0, 1.4, 1.9),
                                         ("1206", 3.2, 1.6, 1.2, 1.8, 3.0)):
        out.append(("Конденсаторы", f"Конденсатор {code} SMD",
                    chip_2terminal(pitch, bw, bh, pw, ph, "C", "C")))
    out.append(("Конденсаторы", "Конденсатор выводной (радиальный)",
                [tht(0, 0, 1.6, 0.8, square=True), tht(2.54, 0, 1.6, 0.8),
                 *silk_rect(2.2, 5.0), label("C", -1.0, 3.2, 1.4, 0.2, "C")]))
    out.append(("Конденсаторы", "Электролит SMD 6,3×5,4",
                [smd(-1.2, 0, 1.2, 1.6), smd(1.2, 0, 1.2, 1.6),
                 RectEl(layer="K1", x0=-2.4, y0=-2.0, x1=2.4, y1=2.0, width=0.2),
                 silk_line(1.8, -1.6, 1.8, 1.6, 0.25),
                 label("C", -1.0, 2.6, 1.3, 0.2, "C")]))
    out.append(("Конденсаторы", "Тантал SMD (A-case)",
                [smd(-1.0, 0, 1.2, 1.4), smd(1.0, 0, 1.2, 1.4),
                 silk_polygon(1.9, 0, 0.6, 0.9, 0.9, 0.2),
                 label("C", -1.0, 1.6, 1.1, 0.16, "C")]))
    out.append(("Конденсаторы", "Конденсатор переменный (триммер)",
                [tht(0, 0, 1.8, 0.9), tht(2.54, 0, 1.8, 0.9), tht(5.08, 0, 1.8, 0.9),
                 *silk_rect(7.2, 6.0), label("C", -1.0, -3.8, 1.4, 0.2, "C")]))

    
    out.append(("Диоды", "Диод выводной 1N4007 (DO-41)",
                chip_axial(10.0, 2.7, 1.0) + [silk_line(1.4, -1.9, 1.4, 1.9, 0.25)]))
    out.append(("Диоды", "Диод Шоттки SMD (SOD-123)",
                [smd(-1.65, 0, 1.0, 1.2), smd(1.65, 0, 1.0, 1.2),
                 RectEl(layer="K1", x0=-2.6, y0=-0.7, x1=2.6, y1=0.7, width=0.2),
                 silk_line(2.0, -0.45, 2.0, 0.45, 0.25),
                 label("D", -1.2, 1.4, 1.2, 0.18, "D")]))
    out.append(("Диоды", "Светодиод 5 мм (через отверстие)",
                [tht(0, 0, 2.0, 1.0, square=True), tht(2.54, 0, 2.0, 1.0),
                 CircleEl(layer="K1", cx=1.27, cy=1.9, r=1.7, width=0.2),
                 label("D", 0.4, -2.6, 1.3, 0.2, "D")]))
    out.append(("Диоды", "Светодиод SMD 0805",
                [smd(-0.95, 0, 1.0, 1.3), smd(0.95, 0, 1.0, 1.3),
                 RectEl(layer="K1", x0=-1.5, y0=-0.6, x1=1.5, y1=0.6, width=0.2),
                 label("D", -1.0, 1.3, 1.0, 0.16, "D")]))
    out.append(("Диоды", "Стабилитрон SMD BZT52",
                [smd(-0.95, 0, 1.0, 1.3), smd(0.95, 0, 1.0, 1.3),
                 RectEl(layer="K1", x0=-1.5, y0=-0.6, x1=1.5, y1=0.6, width=0.2),
                 label("D", -1.0, 1.3, 1.0, 0.16, "D")]))

    
    out.append(("Транзисторы", "SOT-23-3",
                [smd(-0.95, -1.0, 1.0, 0.8), smd(0.95, -1.0, 1.0, 0.8), smd(0, 1.0, 1.0, 0.8),
                 RectEl(layer="K1", x0=-1.6, y0=-1.6, x1=1.6, y1=1.6, width=0.2),
                 label("Q", -1.2, 2.0, 1.2, 0.18, "Q")]))
    out.append(("Транзисторы", "TO-92 (BC547)",
                [tht(0, 0, 1.6, 0.8, square=True), tht(2.54, 0, 1.6, 0.8), tht(1.27, 2.54, 1.6, 0.8),
                 CircleEl(layer="K1", cx=1.27, cy=1.1, r=1.6, width=0.2),
                 label("Q", -1.0, -2.4, 1.3, 0.2, "Q")]))
    out.append(("Транзисторы", "SOT-223-4",
                [smd(-2.3, -1.3, 1.2, 1.6), smd(0, -1.3, 1.2, 1.6), smd(2.3, -1.3, 1.2, 1.6),
                 RectEl(layer="K1", x0=-3.4, y0=0.2, x1=3.4, y1=1.6, width=0.3),
                 label("Q", -1.0, 2.2, 1.3, 0.2, "Q")]))
    out.append(("Транзисторы", "TO-220 (с радиатором)",
                [tht(0, 0, 2.2, 1.2, square=True), tht(2.54, 0, 2.2, 1.2), tht(5.08, 0, 2.2, 1.2),
                 RectEl(layer="K1", x0=-3.5, y0=-6.5, x1=8.5, y1=4.0, width=0.25),
                 label("Q", -1.0, -7.6, 1.6, 0.22, "Q")]))

    
    for name, n, pitch, span, bw, bh in (
            ("SOIC-8", 8, 1.27, 5.4, 6.0, 4.9),
            ("SOIC-14", 14, 1.27, 5.4, 6.0, 8.9),
            ("SOIC-16", 16, 1.27, 5.4, 6.0, 9.9),
            ("SOIC-20", 20, 1.27, 5.4, 6.0, 12.9),
            ("SOIC-28", 28, 1.27, 5.4, 6.0, 17.9)):
        els = dual_row(n, pitch, span, bw, bh)
        els.append(label("U", -bw / 2 - 0.2, bh / 2 + 1.0, 1.3, 0.2, "U"))
        out.append(("Корпуса", name, els))
    for name, n, pitch, span, bw, bh in (
            ("TSSOP-20", 20, 0.65, 4.4, 4.4, 6.4),
            ("SSOP-28", 28, 0.65, 4.4, 4.4, 8.8),
            ("MSOP-8", 8, 0.65, 4.4, 3.2, 3.0)):
        els = dual_row(n, pitch, span, bw, bh, pad_w=0.4, pad_h=1.2)
        els.append(label("U", -bw / 2, bh / 2 + 0.8, 1.1, 0.16, "U"))
        out.append(("Корпуса", name, els))
    for name, n, pitch, body in (("LQFP-32", 32, 0.8, 7.0), ("TQFP-44", 44, 0.8, 7.0),
                                 ("LQFP-64", 64, 0.5, 10.0), ("TQFP-100", 100, 0.5, 14.0)):
        els = quad(n, pitch, body, body)
        els.append(label("U", -body / 2, body / 2 + 1.2, 1.4, 0.22, "U"))
        out.append(("Корпуса", name, els))
    out.append(("Корпуса", "QFN-24 (4×4 мм)",
                quad(24, 0.5, 4.0, 4.0, pad_w=0.25, pad_h=0.8) +
                [label("U", -1.6, 2.6, 1.0, 0.15, "U")]))
    out.append(("Корпуса", "SOP-8", dual_row(8, 1.27, 5.4, 5.3, 5.3, 0.6, 1.5) +
                [label("U", -2.6, 3.4, 1.2, 0.2, "U")]))
    out.append(("Корпуса", "DIP-8",
                [tht(-4.0, y, 1.6, 0.9, square=(i == 0)) for i, y in
                 enumerate([-1.5 + i * 2.54 for i in range(4)])] +
                [tht(4.0, y, 1.6, 0.9) for i, y in
                 enumerate([-1.5 + i * 2.54 for i in range(4)])] +
                silk_rect(6.0, 8.8, 0.2) + [label("U", -1.2, -6.0, 1.4, 0.2, "U")]))
    out.append(("Корпуса", "DIP-14",
                [tht(-4.0, y, 1.6, 0.9, square=(i == 0)) for i, y in
                 enumerate([-6.35 + i * 2.54 for i in range(7)])] +
                [tht(4.0, y, 1.6, 0.9) for i, y in
                 enumerate([-6.35 + i * 2.54 for i in range(7)])] +
                silk_rect(6.0, 19.8, 0.2) + [label("U", -1.2, -11.0, 1.4, 0.2, "U")]))
    out.append(("Корпуса", "DIP-16",
                [tht(-4.0, y, 1.6, 0.9, square=(i == 0)) for i, y in
                 enumerate([-7.62 + i * 2.54 for i in range(8)])] +
                [tht(4.0, y, 1.6, 0.9) for i, y in
                 enumerate([-7.62 + i * 2.54 for i in range(8)])] +
                silk_rect(6.0, 20.3, 0.2) + [label("U", -1.2, -12.0, 1.4, 0.2, "U")]))
    out.append(("Корпуса", "PLCC-20 (J-выводы)",
                [SmdPad(layer=TOP_KEY,
                        x=(-1 if i < 5 else 1) * (3.5 + 0.0),
                        y=-3.0 + (i % 5) * 1.5, w=1.4, h=0.5, mask_open=True)
                 for i in range(20)] +
                silk_rect(5.0, 5.0, 0.2) + [silk_circle(-1.6, -1.6, 0.3, 0.2),
                                              label("U", -1.2, 3.4, 1.2, 0.2, "U")]))

    
    out.append(("Индуктивности", "Индуктивность SMD 0805",
                chip_2terminal(1.9, 2.0, 1.25, 1.0, 1.4, "L", "L")))
    out.append(("Индуктивности", "Индуктивность выводная",
                chip_axial(7.5, 4.0, 1.0) + [label("L", -1.2, -3.4, 1.5, 0.2, "L")]))
    out.append(("Индуктивности", "Дроссель SMD 4×4×3",
                [smd(-2.2, -1.8, 1.2, 1.2), smd(0, -1.8, 1.2, 1.2), smd(2.2, -1.8, 1.2, 1.2),
                 smd(-2.2, 1.8, 1.2, 1.2), smd(0, 1.8, 1.2, 1.2), smd(2.2, 1.8, 1.2, 1.2),
                 RectEl(layer="K1", x0=-3.2, y0=-2.8, x1=3.2, y1=2.8, width=0.2),
                 label("L", -1.2, 3.4, 1.4, 0.22, "L")]))
    out.append(("Индуктивности", "Общее сечение трансформатора",
                [tht(0, 0, 1.8, 0.9), tht(0, 3.0, 1.8, 0.9), tht(6.0, 0, 1.8, 0.9),
                 tht(6.0, 3.0, 1.8, 0.9),
                 *silk_rect(8.0, 5.0), label("T", -1.0, 5.6, 1.5, 0.22, "T")]))

    
    out.append(("Кварцы", "Кварц HC-49/S (4 pads)",
                [tht(-2.4, -1.4, 1.6, 0.9, square=True), tht(2.4, -1.4, 1.6, 0.9),
                 tht(-2.4, 1.4, 1.6, 0.9), tht(2.4, 1.4, 1.6, 0.9),
                 RectEl(layer="K1", x0=-3.6, y0=-2.4, x1=3.6, y1=2.4, width=0.2),
                 silk_circle(-2.6, -1.6, 0.3, 0.2),
                 label("X", -1.0, 3.0, 1.4, 0.2, "X")]))
    out.append(("Кварцы", "Кварц SMD 3225 (4 pads)",
                [smd(-1.1, -0.85, 1.2, 1.0), smd(1.1, -0.85, 1.2, 1.0),
                 smd(-1.1, 0.85, 1.2, 1.0), smd(1.1, 0.85, 1.2, 1.0),
                 RectEl(layer="K1", x0=-1.9, y0=-1.2, x1=1.9, y1=1.2, width=0.18),
                 label("X", -1.0, 1.8, 1.0, 0.15, "X")]))
    out.append(("Кварцы", "Керамический резонатор SMD (3 pads)",
                [smd(-0.95, 0, 1.2, 1.1), smd(0.95, -0.9, 1.2, 1.1), smd(0.95, 0.9, 1.2, 1.1),
                 RectEl(layer="K1", x0=-1.7, y0=-1.2, x1=1.7, y1=1.2, width=0.18),
                 label("X", -1.0, 1.6, 1.0, 0.15, "X")]))
    out.append(("Кнопки", "Кнопка тактовая 6×6×4 (4 вывода)",
                [tht(-3.0, -3.0, 1.6, 0.9), tht(3.0, -3.0, 1.6, 0.9),
                 tht(-3.0, 3.0, 1.6, 0.9), tht(3.0, 3.0, 1.6, 0.9),
                 RectEl(layer="K1", x0=-4.5, y0=-4.5, x1=4.5, y1=4.5, width=0.25),
                 RectEl(layer="K1", x0=-2.2, y0=-2.2, x1=2.2, y1=2.2, width=0.2),
                 label("SW", 0.4, 5.2, 1.4, 0.2, "SW")]))
    out.append(("Кнопки", "Кнопка SMD 3×4 (2 вывода)",
                [smd(-1.2, 0, 1.2, 1.6), smd(1.2, 0, 1.2, 1.6),
                 RectEl(layer="K1", x0=-2.4, y0=-1.8, x1=2.4, y1=1.8, width=0.2),
                 label("SW", -1.0, 2.4, 1.1, 0.16, "SW")]))

    
    for n in (2, 3, 4, 5, 6, 8, 10):
        out.append(("Разъёмы", f"Разъём штырьковый {n} контактов", to_header(n)))
    out.append(("Разъёмы", "Разъём USB-A (SMD)",
                [smd(-4.5, y, 2.4, 1.2) for y in (-2.5, 0, 2.5)] +
                [smd(4.5, y, 2.4, 1.2) for y in (-2.5, 0, 2.5)] +
                [tht(-4.2, -4.0, 1.6, 0.9), tht(4.2, -4.0, 1.6, 0.9)] +
                [RectEl(layer="K1", x0=-6.5, y0=-3.6, x1=6.5, y1=3.6, width=0.25),
                 label("J", -5.0, 4.4, 1.6, 0.22, "J")]))
    out.append(("Разъёмы", "Разъём питания 2 контакта",
                relay_two_wire(5.0)))
    out.append(("Разъёмы", "Клемма винтовая 2 контакта",
                [tht(0, 0, 2.4, 1.2, square=True), tht(5.08, 0, 2.4, 1.2),
                 RectEl(layer="K1", x0=-1.8, y0=-2.2, x1=6.8, y1=2.2, width=0.25),
                 label("X", -1.0, 3.0, 1.4, 0.22, "X")]))
    out.append(("Разъёмы", "Держатель батарейки CR2032",
                [tht(-3.5, 0, 1.8, 0.9, square=True), tht(3.5, 0, 1.8, 0.9),
                 CircleEl(layer="K1", cx=0, cy=0, r=5.0, width=0.25),
                 silk_circle(2.2, 0, 0.4, 0.2),
                 label("BT", -1.6, 6.0, 1.5, 0.22, "BT")]))

    
    out.append(("Прочее", "Силовой MOSFET SO-8",
                dual_row(8, 1.27, 5.4, 5.0, 6.0) +
                [RectEl(layer="K1", x0=-2.5, y0=-3.0, x1=2.5, y1=-1.6, width=0.2),
                 label("Q", -2.6, 3.6, 1.3, 0.2, "Q")]))
    out.append(("Прочее", "Драйвер двигателя DRV8833 (WSON)",
                [smd(-1.3, -1.5, 0.8, 0.4), smd(0, -1.5, 0.8, 0.4),
                 smd(1.3, -1.5, 0.8, 0.4), smd(-1.3, 0, 0.8, 0.4),
                 smd(0, 0, 0.8, 0.4), smd(1.3, 0, 0.8, 0.4),
                 smd(-1.3, 1.5, 0.8, 0.4), smd(0, 1.5, 0.8, 0.4),
                 smd(1.3, 1.5, 0.8, 0.4),
                 RectEl(layer="K1", x0=-2.2, y0=-2.2, x1=2.2, y1=2.2, width=0.15),
                 label("U", -1.6, 2.8, 1.0, 0.15, "U")]))
    out.append(("Прочее", "Модуль ESP-WROOM-32 (38 выводов)",
                [smd(-9.0, -9.0 + i * 1.27, 1.4, 0.6) for i in range(16)] +
                [smd(9.0, -9.0 + i * 1.27, 1.4, 0.6) for i in range(16)] +
                [smd(-6.0 + i * 1.27, -10.5, 0.6, 1.4) for i in range(6)] +
                [RectEl(layer="K1", x0=-10.5, y0=-10.5, x1=10.5, y1=10.5, width=0.25),
                 label("U", -8.0, 12.0, 2.0, 0.3, "U")]))
    out.append(("Прочее", "Плата-адаптер под модуль (2 отверстия)",
                [tht(0, 0, 3.0, 2.2, square=True), tht(20, 0, 3.0, 2.2),
                 RectEl(layer="O", x0=-4, y0=-4, x1=24, y1=4, width=0.3),
                 label("P", -3.0, 6.0, 2.0, 0.3, "P")]))
    return out