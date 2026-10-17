"""Рендер платы в изображение / PDF / принтер (общий код для экспорта и печати)."""
from __future__ import annotations

from typing import List, Optional, Sequence

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

from ..core.model import LAYER_BY_KEY, Board, draw_sort_key


def render_image(canvas, layers: Optional[Sequence[str]] = None, dpi: int = 600,
                 grayscale: bool = False, background: str = "#ffffff",
                 border: float = 2.0, transparent: bool = False) -> QImage:
    """Отрисовать плату в QImage с заданным разрешением."""
    from .canvas import Canvas
    b = canvas.board()
    keys = list(layers or [k for k, v in b.visible.items() if v])
    box = b.outline_rect()
    w_mm = (box[2] - box[0]) + 2 * border
    h_mm = (box[3] - box[1]) + 2 * border
    px_per_mm = dpi / 25.4
    W = max(16, int(w_mm * px_per_mm))
    H = max(16, int(h_mm * px_per_mm))
    fmt = QImage.Format.Format_ARGB32 if transparent else QImage.Format.Format_RGB32
    img = QImage(W, H, fmt)
    if transparent:
        img.fill(Qt.GlobalColor.transparent)
    else:
        img.fill(QColor(background))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    from PySide6.QtCore import QPoint
    old_scale, old_off = canvas.scale, QPointF(canvas.offset)
    old_vis = dict(b.visible)
    old_colors = dict(b.colors)
    old_origin = canvas.field_origin
    canvas.field_origin = QPoint(0, 0)
    canvas.scale = px_per_mm
    canvas.offset = QPointF(box[0] - border, box[1] - border)
    for lk in b.visible:
        b.visible[lk] = lk in keys
    try:
        if not transparent:
            p.fillRect(0, 0, W, H, QColor(background))
            poly = [canvas.to_screen(pt) for pt in b.outline_points()]
            from PySide6.QtGui import QPolygonF
            p.setPen(QPen(QColor("#000000"), max(1.0, 0.2 * px_per_mm)))
            p.setBrush(QColor("#ffffff"))
            p.drawPolygon(QPolygonF(poly))
            p.setBrush(Qt.BrushStyle.NoBrush)
        for el in sorted((e for e in b.elements.values()
                          if e.kind != "conn" and e.layer in keys),
                         key=draw_sort_key):
            mir = not LAYER_BY_KEY[el.layer].top
            col = QColor(LAYER_BY_KEY[el.layer].default_color)
            if grayscale:
                col = QColor("#000000")
            canvas._draw_element(p, el, col, mir)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("#000000"), max(1.0, 0.2 * px_per_mm)))
        poly = [canvas.to_screen(pt) for pt in b.outline_points()]
        from PySide6.QtGui import QPolygonF
        p.drawPolygon(QPolygonF(poly))
    finally:
        canvas.scale, canvas.offset = old_scale, old_off
        canvas.field_origin = old_origin
        b.visible = old_vis
        b.colors = old_colors
    p.end()
    return img


def render_pdf(canvas, path: str, layers: Optional[Sequence[str]] = None,
               scale: float = 1.0):
    """Векторный PDF (через QPdfWriter) — замена EMF для конвертации."""
    from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter
    from PySide6.QtCore import QMarginsF
    b = canvas.board()
    keys = list(layers or [k for k, v in b.visible.items() if v])
    box = b.outline_rect()
    writer = QPdfWriter(path)
    writer.setResolution(1200)
    pw = int((box[2] - box[0]) * 39.37 + 20)
    ph = int((box[3] - box[1]) * 39.37 + 20)
    writer.setPageSize(QPageSize(QSizeF(max(pw, 100), max(ph, 100)), QPageSize.Unit.Point))
    writer.setPageMargins(QMarginsF(10, 10, 10, 10), QPageLayout.Unit.Point)
    p = QPainter(writer)
    p.scale(scale, scale)
    from PySide6.QtCore import QPoint
    old_scale, old_off = canvas.scale, QPointF(canvas.offset)
    old_vis = dict(b.visible)
    old_origin = canvas.field_origin
    canvas.field_origin = QPoint(0, 0)
    canvas.scale = 39.37 * scale
    canvas.offset = QPointF(box[0], box[1])
    for lk in b.visible:
        b.visible[lk] = lk in keys
    for el in sorted((e for e in b.elements.values()
                      if e.kind != "conn" and e.layer in keys),
                     key=draw_sort_key):
        mir = not LAYER_BY_KEY[el.layer].top
        canvas._draw_element(p, el, QColor(LAYER_BY_KEY[el.layer].default_color), mir)
    canvas.scale, canvas.offset = old_scale, old_off
    canvas.field_origin = old_origin
    b.visible = old_vis
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.end()
    return path


from PySide6.QtCore import QSizeF  # noqa: E402  (используется в render_pdf)


# ------------------------------------------------------ печать на принтере
def print_board(canvas, printer, layers: Sequence[str], scale: float = 1.0,
                mirror_all: bool = False, mirror_bottom: bool = False,
                black_white: bool = False, holes: bool = False,
                outline: bool = False, negative: bool = False,
                mask: bool = False, corners: bool = False,
                corr_x: float = 1.0, corr_y: float = 1.0,
                info: bool = True):
    """Печать платы в реальном масштабе 1:1 на указанный QPrinter."""
    from PySide6.QtGui import QPageLayout
    b = canvas.board()
    box = b.outline_rect()
    res = printer.resolution()
    px_per_mm = res / 25.4 * scale
    rect = printer.pageLayout().paintRectPixels(res)
    dx_mm = max(0.0, (rect.width() - (box[2] - box[0]) * px_per_mm) / 2) / px_per_mm
    dy_mm = max(0.0, (rect.height() - (box[3] - box[1]) * px_per_mm) / 2) / px_per_mm
    off = QPointF(box[0] - dx_mm, box[1] - dy_mm)
    p = QPainter(printer)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    from PySide6.QtCore import QPoint
    old_scale, old_off = canvas.scale, QPointF(canvas.offset)
    old_vis = dict(b.visible)
    old_origin = canvas.field_origin
    canvas.field_origin = QPoint(0, 0)
    canvas.scale = px_per_mm
    canvas.offset = off
    for lk in b.visible:
        b.visible[lk] = lk in layers
    if mirror_all or mirror_bottom:
        cx = (box[0] + box[2]) / 2
        cy = (box[1] + box[3]) / 2
    for el in sorted((e for e in b.elements.values()
                      if e.kind != "conn" and el.layer in layers),
                     key=draw_sort_key):
        mir = (not LAYER_BY_KEY[el.layer].top) and (mirror_all or mirror_bottom)
        col = QColor("#000000") if black_white else QColor(LAYER_BY_KEY[el.layer].default_color)
        if mask and el.kind in ("pad", "smd"):
            col = QColor("#ffffff") if not black_white else col
        canvas._draw_element(p, el, col, mir)
    p.setBrush(Qt.BrushStyle.NoBrush)
    if outline:
        p.setPen(QPen(QColor("#000000"), 1))
        from PySide6.QtGui import QPolygonF
        p.drawPolygon(QPolygonF([canvas.to_screen(pt) for pt in b.outline_points()]))
    if corners:
        p.setPen(QPen(QColor("#000000"), 1))
        for (x, y) in b.outline_points():
            s = canvas.to_screen((x, y))
            p.drawLine(int(s.x()) - 8, int(s.y()), int(s.x()) + 8, int(s.y()))
            p.drawLine(int(s.x()), int(s.y()) - 8, int(s.x()), int(s.y()) + 8)
    if holes:
        p.setPen(QPen(QColor("#ff0000"), 1))
        from ..core.model import Pad
        for el in b.elements.values():
            if isinstance(el, Pad) and el.hole_dia > 0:
                s = canvas.to_screen((el.x, el.y))
                r = max(2.0, el.hole_dia * px_per_mm / 2)
                p.drawLine(QPointF(s.x() - r, s.y()), QPointF(s.x() + r, s.y()))
                p.drawLine(QPointF(s.x(), s.y() - r), QPointF(s.x(), s.y() + r))
                p.drawText(QPointF(s.x() + r + 2, s.y() - 2), f"Ø{el.hole_dia:g}")
    if negative:
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        p.fillRect(rect, QColor("#ffffff"))
    if info:
        import time
        p.setPen(QPen(QColor("#000000"), 1))
        p.drawText(QPointF(10, 14), f"e-cad · {b.name} · {scale * 100:.0f}% · "
                                  f"{time.strftime('%Y-%m-%d %H:%M')}")
    canvas.scale, canvas.offset = old_scale, old_off
    canvas.field_origin = old_origin
    b.visible = old_vis
    p.end()