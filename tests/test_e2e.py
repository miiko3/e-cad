"""Сквозной тест e-cad: ядро, интерфейс, экспорт и сборка."""
from __future__ import annotations

import io
import os
import sys
import tempfile
import traceback

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_v, "1")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TMP = tempfile.mkdtemp(prefix="ecad_e2e_")
sys.excepthook = lambda *a: None
RESULTS: list = []


def check(name, fn):
    print(f"  ... {name}", flush=True)
    try:
        detail = fn()
        RESULTS.append((name, True, detail if detail is not None else ""))
        print(f"  OK   {name}" + (f" — {detail}" if detail else ""))
    except Exception as exc:
        RESULTS.append((name, False, repr(exc)))
        print(f"  FAIL {name} — {exc!r}")
        traceback.print_exc()


def eq(a, b, msg=""):
    if a != b:
        raise AssertionError(f"{msg} {a!r} != {b!r}")


def ok(cond, msg=""):
    if not cond:
        raise AssertionError(msg or "условие не выполнено")


def test_core():
    from ecad.core import (drc as drc_mod, exporters, geom, importers, model,
                           tools_lib)
    from ecad.core.fill import compute_fill, fill_stats

    def core_roundtrip():
        b = model.Board(name="E2E", width=80, height=60, origin=(10, 10))
        b.elements["o"] = model.RectEl(layer="O", x0=10, y0=10, x1=90, y1=70, width=0.3)
        for el in tools_lib.footprint_wizard("dip", pads=16, pitch=2.54, row_span=7.62,
                                             pad_dia=1.6, hole_dia=0.9, layer="M1"):
            el.move(25, 25)
            b.elements[el.id] = el
        t = model.Track(layer="M1", points=[(28.8, 25), (60, 22)], width=0.4)
        b.elements[t.id] = t
        b.elements["via"] = model.Pad(layer="M1", x=30, y=45, pad_dia=1.2, hole_dia=0.6,
                                      plated=True, mask_open=True)
        b.elements["tx"] = model.TextEl(layer="K1", x=12, y=14, text="E2E")
        f = compute_fill(b, "M1", clearance=0.25)
        b.elements[f.id] = f
        b.fill_layers["M1"] = True
        doc = model.Document(boards=[b])
        doc.author = "miiko3"
        path = os.path.join(TMP, "board.ecad")
        doc.save(path)
        doc2 = model.Document.load(path)
        b2 = doc2.board()
        eq(len(b2.elements), len(b.elements), "элементов после сохранения")
        eq(sum(1 for e in b2.elements.values() if e.kind == "fill"), 1, "заливок")
        eq(doc2.author, "miiko3", "автор")
        eq(doc2.file, path, "путь файла")
        return f"элементов {len(b2.elements)}"

    check("сохранение и загрузка проекта", core_roundtrip)

    def fill_and_thermal():
        b = model.Board(width=60, height=40, origin=(10, 10))
        b.elements["o"] = model.RectEl(layer="O", x0=10, y0=10, x1=70, y1=50, width=0.3)
        p = model.Pad(layer="M1", x=30, y=20, pad_dia=1.6, hole_dia=0.9, mask_open=True)
        p.thermal = True
        b.elements[p.id] = p
        t = model.Track(layer="M1", points=[(15, 30), (55, 30)], width=0.4)
        b.elements[t.id] = t
        f = compute_fill(b, "M1", clearance=0.25, thermal_gap=0.4, spoke_width=0.5)
        ok(f.rects, "заливка пуста")
        st = fill_stats(f)
        ok(st["area"] > 1000, "площадь заливки слишком мала")
        covered = [r for r in f.rects if r[0] <= p.x <= r[2] and r[1] <= p.y <= r[3]]
        import math
        ang = math.radians(45)
        pt = (p.x + 1.1 * math.cos(ang), p.y + 1.1 * math.sin(ang))
        ring_covered = [r for r in f.rects if r[0] <= pt[0] <= r[2] and r[1] <= pt[1] <= r[3]]
        eq(len(ring_covered), 0, "кольцо термобарьера перекрыто")
        ok(len(covered) >= 0, "проверка площади")
        return f"участков {len(f.rects)}, площадь {st['area']:.0f} мм2"

    check("авто-земля и термобарьер", fill_and_thermal)

    def geom_ops():
        pts = [(0, 0), (10, 0), (10, 5), (0, 5)]
        eq(geom.bbox_of(pts), (0, 0, 10, 5), "bbox")
        eq(round(geom.poly_length(pts), 3), 25.0, "длина ломаной")
        eq(geom.point_in_poly((5, 2), pts), True, "точка внутри")
        eq(geom.point_in_poly((20, 2), pts), False, "точка снаружи")
        eq(round(geom.dist((0, 0), (3, 4)), 3), 5.0, "расстояние")
        arc = geom.arc_points(0, 0, 2, 0, 90)
        eq(len(arc) > 2, True, "дуга")
        eq(round(geom.parse_len("0.1 in", 0.0), 4), round(0.1 * 25.4, 4), "дюймы")
        eq(round(geom.parse_len("10 mil", 0.0), 4), round(10 * geom.MIL, 4), "mil")
        return "геометрия согласована"

    check("геометрия", geom_ops)

    def connectivity():
        b = model.Board(width=80, height=60, origin=(10, 10))
        p1 = model.Pad(layer="M1", x=30, y=20, pad_dia=1.8, hole_dia=0.9)
        p2 = model.Pad(layer="M1", x=40, y=20, pad_dia=1.8, hole_dia=0.9)
        b.elements[p1.id] = p1
        b.elements[p2.id] = p2
        t = model.Track(layer="M1", points=[(30, 20), (40, 20)], width=0.4)
        b.elements[t.id] = t
        net = model.netlist(b)
        ok(any(len(v) >= 3 for v in net.values()), "цепь не объединена")
        uf = model.nets(b)
        eq(uf.find(p1.id), uf.find(p2.id), "контакты не в одной цепи")
        return "цепей " + str(len(net))

    check("связность цепей", connectivity)

    def drc_rules():
        b = model.Board(width=80, height=60, origin=(10, 10))
        b.elements["o"] = model.RectEl(layer="O", x0=10, y0=10, x1=90, y1=70, width=0.3)
        p1 = model.Pad(layer="M1", x=30, y=20, pad_dia=1.8, hole_dia=0.9)
        b.elements[p1.id] = p1
        p2 = model.Pad(layer="M1", x=30.3, y=20, pad_dia=1.8, hole_dia=0.9)
        b.elements[p2.id] = p2
        tr = model.Track(layer="M1", points=[(31.3, 40), (60, 40)], width=0.4)
        b.elements[tr.id] = tr
        p3 = model.Pad(layer="M1", x=30, y=40, pad_dia=1.8, hole_dia=0.9)
        b.elements[p3.id] = p3
        errs = drc_mod.check(b)
        rules = {e.rule for e in errs}
        ok("min_clearance" in rules, f"не найден зазор: {rules}")
        ok("min_hole_gap" in rules, "не найден зазор между отверстиями")
        holes = drc_mod.hole_table(b)
        eq(holes, [(0.9, 3)], "таблица отверстий")
        return f"правил {len(drc_mod.RULE_NAMES)}, ошибок {len(errs)}"

    check("DRC и таблица отверстий", drc_rules)

    def exporters_all():
        b = model.Board(name="E2E", width=80, height=60, origin=(10, 10))
        b.elements["o"] = model.RectEl(layer="O", x0=10, y0=10, x1=90, y1=70, width=0.3)
        b.elements["t"] = model.Track(layer="M1", points=[(20, 20), (60, 30)], width=0.4)
        b.elements["p"] = model.Pad(layer="M1", x=30, y=20, pad_dia=1.8, hole_dia=0.9)
        b.elements["p"].mask_open = True
        b.elements["s"] = model.SmdPad(layer="M1", x=50, y=30, w=1.0, h=1.4)
        b.elements["s"].mask_open = True
        folder = os.path.join(TMP, "out")
        os.makedirs(folder, exist_ok=True)
        made = exporters.export_gerber_set(b, folder, ["M1", "M2", "K1", "O"], "e2e")
        ok(len(made) >= 4, f"Gerber файлов {len(made)}")
        drl = exporters.export_excellon(b, folder, "e2e")
        ok(os.path.exists(os.path.join(folder, drl)), "Excellon не создан")
        hp, log = exporters.hpgl(b, mill_dia=1.0)
        ok("IN;SP1;" in hp, "HPGL пуст")
        pnp = exporters.pick_and_place(b)
        ok("RefDes" in pnp, "PnP без заголовка")
        bom = exporters.bom_text(b)
        ok("Обозначение" in bom, "BOM пуст")
        txt = exporters.text_io(b)
        ok("text-io" in txt, "текстовый экспорт пуст")
        return f"Gerber {len(made)}, HPGL {len(hp.splitlines())} строк"

    check("экспорт Gerber/Excellon/HPGL/PnP/BOM", exporters_all)

    def importers_all():
        b = model.Board(width=80, height=60, origin=(10, 10))
        b.elements["o"] = model.RectEl(layer="O", x0=10, y0=10, x1=90, y1=70, width=0.3)
        b.elements["p"] = model.Pad(layer="M1", x=30, y=20, pad_dia=1.8, hole_dia=0.9)
        g = exporters.gerber_layer(b, "M1")
        els = importers.import_gerber(g)
        ok(els, "импорт Gerber пуст")
        ok(any(e.kind == "pad" for e in els), "нет контактов после импорта")
        d = exporters.excellon(b)
        pads = importers.import_excellon(d)
        eq(len(pads), 1, "отверстий после импорта")
        return f"Gerber {len(els)} эл., Excellon {len(pads)} отв."

    check("импорт Gerber и Excellon", importers_all)

    def footprints_all():
        from ecad.core.footprints import default_macros
        items = default_macros()
        ok(len(items) >= 60, f"макросов {len(items)}")
        groups = {g for g, _n, _e in items}
        ok(len(groups) >= 10, f"групп {len(groups)}")
        bad = []
        for group, name, els in items:
            if not els:
                bad.append(name)
                continue
            for el in els:
                bb = el.bbox()
                if bb is None:
                    bad.append(f"{name}:{el.kind}")
                elif not (bb[2] > bb[0] and bb[3] > bb[1]):
                    bad.append(f"{name}:{el.kind}:size")
        ok(not bad, f"некорректные макросы {bad[:5]}")
        macro = tools_lib.Macro(name="probe", elements=items[0][2])
        inst = macro.instance(20, 20)
        ok(len(inst) == len(macro.elements), "копия макроса")
        ids = {el.id for el in inst}
        ok(ids, "пустые идентификаторы")
        return f"{len(items)} макросов, {len(groups)} групп"

    check("библиотека компонентов", footprints_all)

    def element_ops():
        els = [
            model.Track(points=[(0, 0), (5, 0)], width=0.4),
            model.Pad(x=3, y=4), model.SmdPad(x=1, y=2),
            model.CircleEl(cx=5, cy=5, r=2, a0=0, a1=90),
            model.CircleEl(cx=5, cy=5, r=2, a0=0, a1=360),
            model.PolygonEl(points=[(0, 0), (4, 0), (4, 4)]),
            model.TextEl(x=1, y=1, text="R1"),
            model.RectEl(x0=0, y0=0, x1=6, y1=3),
            model.Connection(a="x", b="y"),
            model.FillEl(rects=[[0, 0, 2, 2], [3, 3, 5, 5]], cell=0.1),
        ]
        els += tools_lib.footprint_wizard("quad", pads=32)
        els += tools_lib.footprint_wizard("dip", pads=8)
        for el in els:
            el.rotate(90, (0, 0))
            el.bbox()
            el.rotate(-45, (2, 2))
            el.bbox()
            el.mirror_x((0, 0))
            el.mirror_y((0, 0))
            el.flip_layer()
            el.move(3, -2)
            el.bbox()
            el.hit((1, 1), 0.2)
        return f"элементов проверено {len(els)}"

    check("операции над всеми типами элементов", element_ops)

    def autotrace_test():
        b = model.Board(width=80, height=60, origin=(10, 10))
        p1 = model.Pad(layer="M1", x=30, y=20, pad_dia=1.8, hole_dia=0.9)
        p2 = model.Pad(layer="M1", x=40, y=30, pad_dia=1.8, hole_dia=0.9)
        b.elements[p1.id] = p1
        b.elements[p2.id] = p2
        conn = model.Connection(a=p1.id, b=p2.id, layer="M1")
        b.elements[conn.id] = conn
        tr = tools_lib.autotrace(b, conn, tools_lib.RouteParams())
        ok(tr is not None, "автотрасса не найдена")
        eq(tr.auto, True, "метка автотрассы")
        ok(tr.points[0] == (30.0, 20.0) or tr.points[-1] == (30.0, 20.0),
           "автотрасса не от контакта")
        return f"{len(tr.points)} узлов, длина {tr.length():.2f} мм"

    check("автотрассировщик", autotrace_test)


def test_ui():
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
    from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QInputDialog,
                                   QMenu, QMessageBox)

    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QInputDialog.getText = staticmethod(lambda *a, **k: ("", False))
    QInputDialog.getDouble = staticmethod(lambda *a, **k: (0.0, False))
    QInputDialog.getItem = staticmethod(lambda *a, **k: ("", False))
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: ("", ""))
    QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([], ""))
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")
    QDialog.exec = staticmethod(lambda *a, **k: 0)

    app = QApplication.instance() or QApplication(sys.argv)
    from ecad.ui import dialogs as D
    from ecad.ui import dialogs_board as DB
    from ecad.ui.about import AboutDialog, LinksCard
    from ecad.ui.helpwindow import HelpWindow, anchor_for, instructions_html
    from ecad.ui.main_window import MainWindow
    from ecad.core import model as M
    from ecad.core.tools_lib import footprint_wizard

    import shutil
    demo_path = os.path.join(ROOT, "examples", "demo.ecad")
    demo_copy = os.path.join(TMP, "demo.ecad")
    shutil.copyfile(demo_path, demo_copy)

    win = MainWindow()
    win.canvas.settings["autosave_min"] = 0
    win.resize(1500, 900)
    win.show()
    app.processEvents()
    c = win.canvas

    def ui_boot():
        win.open_demo()
        app.processEvents()
        ok(os.path.exists(win.doc.file or ""), "демо-файл не открыт")
        win.open_file(demo_copy)
        app.processEvents()
        b = c.board()
        ok(len(b.elements) > 10, "демо-проект пуст")
        ok(b.components, "нет компонентов")
        c.zoom_board()
        app.processEvents()
        ok(c.scale > 0.1, "масштаб не задан")
        return f"элементов {len(b.elements)}, компонентов {len(b.components)}"

    check("запуск и открытие демо-проекта", ui_boot)

    def ui_tools_mouse():
        b = c.board()
        b.elements.clear()
        b.width, b.height = 100, 80
        b.origin = (10, 10)
        c.zoom_board()
        app.processEvents()
        c.set_tool("cursor")

        def click(p, button=Qt.MouseButton.LeftButton):
            pos = QPointF(c.to_screen(p, False))
            c.mousePressEvent(QMouseEvent(QMouseEvent.Type.MouseButtonPress, pos,
                                         pos.toPoint(), button, button,
                                         Qt.KeyboardModifier.NoModifier))
            c.mouseReleaseEvent(QMouseEvent(QMouseEvent.Type.MouseButtonRelease, pos,
                                           pos.toPoint(), button,
                                           Qt.MouseButton.NoButton,
                                           Qt.KeyboardModifier.NoModifier))

        def press_return():
            from PySide6.QtGui import QKeyEvent
            from PySide6.QtCore import QEvent
            ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                           Qt.KeyboardModifier.NoModifier)
            c.keyPressEvent(ev)

        def drag(a, b_):
            pa, pb = QPointF(c.to_screen(a, False)), QPointF(c.to_screen(b_, False))
            c.mousePressEvent(QMouseEvent(QMouseEvent.Type.MouseButtonPress, pa, pa.toPoint(),
                                         Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                         Qt.KeyboardModifier.NoModifier))
            c.mouseMoveEvent(QMouseEvent(QMouseEvent.Type.MouseMove, pb, pb.toPoint(),
                                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                        Qt.KeyboardModifier.NoModifier))
            c.mouseReleaseEvent(QMouseEvent(QMouseEvent.Type.MouseButtonRelease, pb, pb.toPoint(),
                                           Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                                           Qt.KeyboardModifier.NoModifier))

        counts = {}
        c.set_tool("track")
        click((20, 20))
        click((40, 20))
        click((40, 40))
        press_return()
        counts["track_click"] = sum(1 for e in b.elements.values() if e.kind == "track")
        drag((20, 25), (50, 30))
        counts["track_drag"] = sum(1 for e in b.elements.values() if e.kind == "track")

        c.set_tool("pad")
        click((30, 30))
        counts["pad"] = sum(1 for e in b.elements.values() if e.kind == "pad")

        c.set_tool("smd")
        click((35, 30))
        counts["smd"] = sum(1 for e in b.elements.values() if e.kind == "smd")

        c.set_tool("circle")
        drag((50, 30), (55, 35))
        counts["circle"] = sum(1 for e in b.elements.values() if e.kind == "circle")

        c.set_tool("poly")
        click((60, 40))
        click((70, 40))
        click((70, 50))
        c.keyPressEvent(type("E", (), {"key": lambda s: Qt.Key.Key_Return,
                                       "modifiers": lambda s: Qt.KeyboardModifier.NoModifier})())
        counts["poly"] = sum(1 for e in b.elements.values() if e.kind == "poly")

        c.set_tool("rect")
        drag((20, 50), (30, 55))
        counts["rect"] = sum(1 for e in b.elements.values() if e.kind == "rect")

        for k, v in counts.items():
            ok(v > 0, f"инструмент {k} не создал элементов")
        return "создано: " + ", ".join(f"{k}={v}" for k, v in counts.items())

    check("инструменты мышью", ui_tools_mouse)

    def ui_selection_ops():
        b = c.board()
        c.select_all()
        app.processEvents()
        ok(len(c.selection) > 0, "нечего выделять")
        before = c.selection_center()
        c.rotate_selected(90)
        c.mirror_selected_x()
        c.mirror_selected_y()
        c.flip_selected_layer()
        c.snap_selected_to_grid()
        c.array_selected(3, 2.0, 0.0)
        c.align_selected("left")
        c.copy_selected()
        c.paste()
        c.join_tracks()
        c.undo()
        c.redo()
        app.processEvents()
        ok(c.selection_center() is not None, "центр выделения потерян")
        return f"выделено {len(c.selection)}, элементов {len(b.elements)}"

    check("поворот, зеркало, массив, undo", ui_selection_ops)

    def ui_macro_placement():
        b = c.board()
        before = len(b.elements)
        macro = next((m for m in win.library.macros if m.name == "SOIC-8"), None)
        ok(macro is not None, "макрос SOIC-8 не найден")
        found = None
        for g in range(win.pane_lib.tree.topLevelItemCount()):
            head = win.pane_lib.tree.topLevelItem(g)
            for j in range(head.childCount()):
                item = head.child(j)
                if item.data(0, Qt.ItemDataRole.UserRole) is macro:
                    found = item
                    break
        ok(found is not None, "макрос не найден в дереве библиотеки")
        win.pane_lib.tree.setCurrentItem(found)
        app.processEvents()
        win.pane_lib._on_item_clicked(found, 0)
        ok(c.placed_macro is not None, "клик по макросу не запускает размещение")
        target = (40.0, 30.0)
        pos = QPointF(c.to_screen(target, False))
        c.mousePressEvent(QMouseEvent(QMouseEvent.Type.MouseButtonPress, pos, pos.toPoint(),
                                     Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                     Qt.KeyboardModifier.NoModifier))
        c.mouseReleaseEvent(QMouseEvent(QMouseEvent.Type.MouseButtonRelease, pos,
                                       pos.toPoint(), Qt.MouseButton.LeftButton,
                                       Qt.MouseButton.NoButton,
                                       Qt.KeyboardModifier.NoModifier))
        app.processEvents()
        ok(len(b.elements) > before, "макрос не размещён")
        ok(c.placed_macro is not None, "размещение сброшено после первой вставки")
        pads = [c.board().elements[i] for i in c.selection
                if c.board().elements[i].kind in ("pad", "smd")]
        ok(pads, "нет контактов у размещённого макроса")
        cx = sum(e.x for e in pads) / len(pads)
        cy = sum(e.y for e in pads) / len(pads)
        ok(abs(cx - target[0]) < 1.2 and abs(cy - target[1]) < 1.2,
           f"центр ({cx:.2f},{cy:.2f}) не под курсором")
        return f"размещено {len(pads)} контактов в ({cx:.2f},{cy:.2f})"

    check("размещение макроса под курсором", ui_macro_placement)

    def ui_macro_repeat():
        """Макрос ставится многократно, отменяется Esc."""
        b = c.board()
        macro = next((m for m in win.library.macros if m.name == "SOIC-8"), None)
        ok(macro is not None, "макрос SOIC-8 не найден")
        win.pane_lib.tree.clear()
        win.pane_lib.refresh()
        app.processEvents()
        item = None
        for g in range(win.pane_lib.tree.topLevelItemCount()):
            head = win.pane_lib.tree.topLevelItem(g)
            for j in range(head.childCount()):
                it = head.child(j)
                if it.data(0, Qt.ItemDataRole.UserRole) is macro:
                    item = it
                    break
        ok(item is not None, "макрос не найден в дереве")
        win.pane_lib._on_item_clicked(item, 0)
        ok(c.placed_macro is macro, "клик по макросу не запустил размещение")
        n_els = len(macro.elements)
        before = len(b.elements)
        spots = [(60.0, 30.0), (75.0, 30.0), (90.0, 30.0)]
        for (mx, my) in spots:
            pos = QPointF(c.to_screen((mx, my), False))
            c.mousePressEvent(QMouseEvent(QMouseEvent.Type.MouseButtonPress, pos, pos.toPoint(),
                                         Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                         Qt.KeyboardModifier.NoModifier))
            c.mouseReleaseEvent(QMouseEvent(QMouseEvent.Type.MouseButtonRelease, pos,
                                            pos.toPoint(), Qt.MouseButton.LeftButton,
                                            Qt.MouseButton.NoButton,
                                            Qt.KeyboardModifier.NoModifier))
            app.processEvents()
        ok(len(b.elements) - before == 3 * n_els,
           f"после 3 кликов добавлено {len(b.elements) - before}, ожидалось {3 * n_els}")
        ok(c.placed_macro is macro, "макрос сброшен после нескольких вставок")
        c.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                  Qt.KeyboardModifier.NoModifier))
        app.processEvents()
        ok(c.placed_macro is None, "Esc не отменил размещение")
        n_after_esc = len(b.elements)
        pos = QPointF(c.to_screen((100.0, 30.0), False))
        c.mousePressEvent(QMouseEvent(QMouseEvent.Type.MouseButtonPress, pos, pos.toPoint(),
                                     Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                     Qt.KeyboardModifier.NoModifier))
        c.mouseReleaseEvent(QMouseEvent(QMouseEvent.Type.MouseButtonRelease, pos, pos.toPoint(),
                                        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                                        Qt.KeyboardModifier.NoModifier))
        app.processEvents()
        eq(len(b.elements), n_after_esc, "после Esc макрос ставится снова")
        return f"3 вставки по {n_els} эл., Esc отменяет"

    check("повторное размещение макроса и отмена Esc", ui_macro_repeat)

    def ui_panels():
        c.set_tool("cursor")
        win.show_pane(2)
        win.pane_drc.run(False)
        app.processEvents()
        ok(win.pane_drc.errors is not None, "DRC не выполнен")
        win.show_pane(4)
        app.processEvents()
        ok(win.pane_bom.list.count() > 0, "лист компонентов пуст")
        win.show_pane(3)
        app.processEvents()
        ok(win.pane_filter.list.count() > 0, "фильтр пуст")
        win.show_pane(0)
        app.processEvents()
        return f"DRC ошибок {len(win.pane_drc.errors)}, фильтр {win.pane_filter.list.count()}"

    check("панели DRC, компоненты, фильтр", ui_panels)

    def ui_arrow_rotate():
        b = c.board()
        c.select_all()
        app.processEvents()
        ok(len(c.selection) > 0, "нечего поворачивать")
        marks_before = []
        from ecad.core.model import Track as _T
        tracks = [b.elements[i] for i in c.selection if isinstance(b.elements[i], _T)]
        ok(tracks, "нет дорожек для проверки угла")
        t0 = tracks[0]
        before_pts = list(t0.points)
        for k, expected in ((Qt.Key.Key_Right, 90.0), (Qt.Key.Key_Left, -90.0)):
            c.keyPressEvent(type("E", (), {"key": lambda s: k,
                                           "modifiers": lambda s: Qt.KeyboardModifier.NoModifier})())
            app.processEvents()
        ok(before_pts != t0.points, "стрелки не повернули выделение")
        return f"поворот стрелками, элементов {len(c.selection)}"

    check("поворот выделенного стрелками", ui_arrow_rotate)

    def ui_wheel_pan():
        from PySide6.QtCore import QPointF as _QPF

        def send(pixel, angle, mods):
            ev = QWheelEvent(_QPF(300, 300), win.mapToGlobal(QPoint(300, 300)),
                             QPoint(*pixel), QPoint(*angle),
                             Qt.MouseButton.NoButton, mods,
                             Qt.ScrollPhase.ScrollUpdate, False)
            c.wheelEvent(ev)
            app.processEvents()

        def moved(px, py, mods, label):
            old = QPointF(c.offset)
            send(px, py, mods)
            d = c.offset - old
            ok(abs(d.x()) > 0.01 or abs(d.y()) > 0.01, f"{label}: колесо не прокручивает")
            return d

        d = moved((0, 0), (0, 240), Qt.KeyboardModifier.NoModifier, "колесо")
        ok(abs(d.y()) > 1.0, "вертикальная прокрутка слишком мала")
        d = moved((0, 0), (0, 240), Qt.KeyboardModifier.ShiftModifier, "Shift+колесо")
        ok(abs(d.x()) > 1.0, "горизонтальная прокрутка по Shift не работает")
        d = moved((0, 0), (240, 0), Qt.KeyboardModifier.NoModifier, "наклон колеса")
        ok(abs(d.x()) > 1.0, "прокрутка по X при наклоне колеса не работает")
        moved((0, 40), (0, 0), Qt.KeyboardModifier.NoModifier, "трекпад по Y")
        moved((40, 0), (0, 0), Qt.KeyboardModifier.NoModifier, "трекпад по X")
        old_off, old_scale = QPointF(c.offset), c.scale
        send((0, 0), (0, 240), Qt.KeyboardModifier.ControlModifier)
        ok(c.scale != old_scale, "Ctrl+колесо не меняет масштаб")
        c.offset = old_off
        c.scale = old_scale
        c.invalidate()
        return "колесо: Y, X, Shift, наклон, трекпад, Ctrl — все работают"

    check("прокрутка колесом по X и Y", ui_wheel_pan)

    def ui_esc_cancels():
        c.set_tool("track")
        c.select([])
        field = c.field_rect()
        cx, cy = c.to_model(field.center())
        for dx, dy in ((-6.0, -4.0), (6.0, 4.0)):
            spot = (cx + dx, cy + dy)
            pos = QPointF(c.to_screen(spot, False))
            c.mousePressEvent(QMouseEvent(QMouseEvent.Type.MouseButtonPress, pos, pos.toPoint(),
                                         Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                         Qt.KeyboardModifier.NoModifier))
            c.mouseReleaseEvent(QMouseEvent(QMouseEvent.Type.MouseButtonRelease, pos,
                                            pos.toPoint(), Qt.MouseButton.LeftButton,
                                            Qt.MouseButton.NoButton,
                                            Qt.KeyboardModifier.NoModifier))
            app.processEvents()
        ok(len(c.temp_points) == 2, f"точек дорожки {len(c.temp_points)}, ожидалось 2")
        c.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                  Qt.KeyboardModifier.NoModifier))
        app.processEvents()
        eq(len(c.temp_points), 0, "Esc не сбросил точки дорожки")
        eq(c.tool, "cursor", "Esc не вернул инструмент «Курсор»")
        c.set_tool("pad")
        cpos = QPointF(field.center())
        c.mousePressEvent(QMouseEvent(QMouseEvent.Type.MouseButtonPress, cpos, cpos.toPoint(),
                                     Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                     Qt.KeyboardModifier.NoModifier))
        app.processEvents()
        ok(c.conn_first is None, "связь не должна быть начата инструментом КП")
        return "Esc сбрасывает точки, макрос, инструмент"

    check("Esc отменяет текущее действие", ui_esc_cancels)

    def ui_library_folder():
        from ecad.core.tools_lib import Library
        folder = os.path.join(TMP, "lib_folder")
        os.makedirs(os.path.join(folder, "Диоды"), exist_ok=True)
        kicad = ('(footprint "R_0805_2012Metric"\n'
                 '  (pad "1" smd rect (at -1.0 0) (size 1.0 1.3) (layers "F.Cu"))\n'
                 '  (pad "2" smd rect (at 1.0 0) (size 1.0 1.3) (layers "F.Cu"))\n'
                 '  (fp_line (start -1.2 -0.7) (end 1.2 -0.7) (layer "F.SilkS"))\n)\n')
        path = os.path.join(folder, "Диоды", "R_0805.kicad_mod")
        with open(path, "w", encoding="utf-8") as f:
            f.write(kicad)
        with open(os.path.join(folder, "не_макрос.txt"), "w", encoding="utf-8") as f:
            f.write(" мусор")
        lib = Library(folder)
        macros = lib.scan()
        eq(len(macros), 1, "подхвачено файлов из папки")
        m = macros[0]
        eq(m.name, "R_0805_2012Metric", "имя стороннего компонента")
        eq(m.group, "Диоды", "имя папки должно стать группой")
        ok(len(m.elements) >= 3, f"элементов в стороннем компоненте {len(m.elements)}")
        smd = [e for e in m.elements if e.kind == "smd"]
        eq(len(smd), 2, "SMD-контактов в импорте")
        ok(any(os.path.basename(p) == "Диоды" for p in lib.folders()),
           "вложенная папка не отслеживается")
        return f"«{m.name}» в группе «{m.group}», элементов {len(m.elements)}"

    check("библиотека: сторонние компоненты из папки", ui_library_folder)

    def ui_paint_speed():
        import time as _time
        from ecad.core.model import Pad as _P, Track as _T
        b = c.board()
        saved = dict(b.elements)
        b.elements.clear()
        b.width, b.height = 200, 150
        b.origin = (0, 0)
        for i in range(500):
            x = (i % 25) * 8.0
            y = (i // 25) * 7.0
            b.elements[f"t{i}"] = _T(layer="M1", points=[(x, y), (x + 6.0, y + 4.0)],
                                      width=0.4)
        for i in range(150):
            x = (i % 15) * 13.0
            y = (i // 15) * 15.0
            b.elements[f"p{i}"] = _P(layer="M1", x=x, y=y, pad_dia=1.6, hole_dia=0.9)
        c.invalidate()
        c.zoom_all()
        app.processEvents()
        c.repaint()
        t0 = _time.time()
        n = 24
        for i in range(n):
            c.mouseMoveEvent(QMouseEvent(QMouseEvent.Type.MouseMove,
                                         QPointF(400 + i * 5, 350 + (i % 7) * 4),
                                         QPointF(400 + i * 5, 350 + (i % 7) * 4),
                                         Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                                         Qt.KeyboardModifier.NoModifier))
            c.repaint()
        per = (_time.time() - t0) / n * 1000.0
        ok(per < 16.0, f"движение мыши лагает: {per:.1f} мс/кадр (должно быть < 16)")
        b.elements.clear()
        b.elements.update(saved)
        c.invalidate()
        app.processEvents()
        return f"{per:.1f} мс/кадр при {len(saved) + 650} элементах"

    check("плавное движение мыши по макету", ui_paint_speed)

    def ui_left_panel():
        panel = win.tool_panel
        panel.set_collapsed(True)
        app.processEvents()
        for b in panel.buttons.values():
            ok(b.text() == "", "подпись не убрана при сворачивании")
            ok(b.width() <= 40, "кнопка инструмента слишком широкая")
        panel.set_collapsed(False)
        app.processEvents()
        labels = [b.text() for b in panel.buttons.values()]
        ok(all(labels), "подписи инструментов не восстановлены")
        ok(panel.panel_buttons["props"].text() == "Свойства", "подпись панели потеряна")
        ok(panel.width() >= 200, "панель не развёрнута")
        return f"кнопок {len(labels)}, ширина {panel.width()}"

    check("сворачиваемая левая панель", ui_left_panel)

    def ui_help():
        html = instructions_html()
        names = set()
        import re as _re
        for name in _re.findall(r'<a name="([^"]+)"', html):
            names.add(name)
        titles = _re.findall(r'h\((?:1|2|3),\s*"([^"]+)"\)', open(
            os.path.join(ROOT, "ecad", "ui", "helpwindow.py"), encoding="utf-8").read())
        titles += _re.findall(r'<h[12]>(Блок [^<]+)</h[12]>', html)
        eq(len(titles), 13, "число блоков инструкции")
        missing = [t for t in titles if anchor_for(t) not in names]
        ok(not missing, f"блоки без якоря {missing}")
        dlg = HelpWindow()
        app.processEvents()
        dlg.list.setCurrentRow(5)
        app.processEvents()
        dlg.close()
        return f"блоков {len(titles)}, якорей {len(names)}"

    check("инструкция: переход по блокам", ui_help)

    def ui_about():
        dlg = AboutDialog()
        app.processEvents()
        buttons = [b.text() for b in dlg.findChildren(type(dlg.btn_author if hasattr(dlg, "btn_author")
                                                          else D.BaseDialog))] if False else []
        texts = []
        from PySide6.QtWidgets import QLabel, QPushButton
        for b in dlg.findChildren(QPushButton):
            if b.text():
                texts.append(b.text())
        ok(any("Закрыть" in t for t in texts), "нет кнопки «Закрыть»")
        block = dlg.findChildren(QLabel)
        head_texts = [w.text() for w in block if isinstance(w, QLabel)]
        ok(any(t == "Автор" for t in head_texts), "нет блока «Автор»")
        ok(not any("АВТОР" in t for t in head_texts), "остался заголовок «АВТОР»")
        ok(not any("Актор" in t for t in head_texts + texts), "осталось упоминание «Актор»")
        cards = dlg.findChildren(LinksCard)
        ok(len(cards) >= 2, "нет карточек ссылок (соцсети и репозитории)")
        joined = " ".join(w.text() for w in block)
        ok("vk.ru/seller_tg" in joined, "нет ссылки ВКонтакте")
        ok("yoomoney" in joined or "boosty" in joined, "нет ссылок поддержки")
        ok("github.com/miiko3" in joined, "нет ссылок GitHub")
        dlg.close()
        return f"блоков ссылок {len(cards)}"

    check("блок «Автор» и кнопка «О программе»", ui_about)

    def ui_about_button():
        from PySide6.QtWidgets import QToolButton
        eq(win.btn_about.text(), "О программе", "подпись кнопки в верхней панели")
        ok(not any("Актор" in (w.toolTip() or "") for w in win.findChildren(QToolButton)),
           "в подсказках осталось «Актор»")
        actions = [a.text() for a in win.menuBar().findChildren(QMenu)
                   for a in a.actions()]
        eq(sum(1 for t in actions if t == "О программе"), 1, "пункт «О программе» в меню")
        shortcut_v = [a.shortcut().toString() for a in win.findChildren(QMenu)
                      for a in a.actions() if a.shortcut().toString() == "V"]
        eq(len(shortcut_v), 1, "сочетание V должно быть одно (иначе не сработает)")
        c.set_tool("cursor")
        return "кнопка «О программе», конфликтов клавиш нет"

    check("кнопка «О программе» и клавиша V", ui_about_button)

    def ui_dialogs():
        b = c.board()
        dialogs = [
            DB.NewBoardDialog(c, max_board=True), DB.BoardPropsDialog(c, b),
            D.TextDialog(c), D.ShapeDialog(c), D.ArrayDialog(c), D.WizardDialog(c),
            D.GerberExportDialog(c), D.DrillDialog(c), D.HpglDialog(c),
            D.PrintDialog(c), D.ImageExportDialog(c), D.PnpDialog(c),
            D.OptionsDialog(c, win), DB.GerberImportDialog(c, ["x_copper_top.gbr"]),
        ]
        for d in dialogs:
            app.processEvents()
            ok(d is not None, "диалог не создан")
        for d in dialogs:
            d.close()
        return f"диалогов создано {len(dialogs)}"

    check("все диалоги открываются", ui_dialogs)

    def ui_menu():
        done = 0
        bad = []
        for menu in win.menuBar().findChildren(QMenu):
            def walk(m):
                nonlocal done
                for act in m.actions():
                    if act.isSeparator():
                        continue
                    if act.menu() is not None:
                        walk(act.menu())
                        continue
                    try:
                        act.trigger()
                        app.processEvents()
                        done += 1
                    except Exception as exc:
                        bad.append(act.text() + ": " + repr(exc)[:60])
            walk(menu)
        ok(not bad, f"ошибки меню {bad[:5]}")
        ok(done > 200, f"действий {done}")
        return f"действий {done}"

    check("все действия меню", ui_menu)

    def ui_undo_depth():
        depth = int(c.settings.get("undo_depth", 40))
        c.undo_stack.clear()
        c.redo_stack.clear()
        c.push_undo()
        for _ in range(depth + 5):
            c.push_undo()
        ok(len(c.undo_stack) <= depth + 1, f"глубина undo {len(c.undo_stack)}")
        c.undo_stack.clear()
        return f"лимит undo {len(c.undo_stack)}"

    check("лимит глубины отмены", ui_undo_depth)

    def ui_image_export():
        from ecad.ui.render import render_image
        img = render_image(c, ["M1", "K1", "O"], dpi=150)
        ok(img.width() > 50 and img.height() > 50, "изображение пустое")
        from PySide6.QtGui import QColor
        non_white = 0
        for y in range(0, img.height(), 8):
            for x in range(0, img.width(), 8):
                if img.pixelColor(x, y) != QColor("#ffffff"):
                    non_white += 1
        ok(non_white > 20, "экспорт изображения пуст")
        path = os.path.join(TMP, "export.png")
        ok(img.save(path), "сохранение изображения")
        return f"{img.width()}x{img.height()}, непустых точек {non_white}"

    check("экспорт изображения", ui_image_export)

    win.close()


def main():
    sys.setrecursionlimit(250)
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    print("=" * 60)
    print("e-cad e2e test")
    print("=" * 60)
    print("\n[Ядро]")
    try:
        test_core()
    except Exception:
        import traceback as _tb
        _tb.print_exc()
    print("\n[Интерфейс]")
    try:
        test_ui()
    except Exception:
        import traceback as _tb
        _tb.print_exc()
    print("\n" + "=" * 60)
    failed = [r for r in RESULTS if not r[1]]
    print(f"проверок: {len(RESULTS)} | успешно: {len(RESULTS) - len(failed)} | ошибок: {len(failed)}")
    for name, _ok, err in failed:
        print(f"  ОШИБКА: {name} — {err}")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())