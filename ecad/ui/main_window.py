"""Главное окно e-cad: меню, панели, вкладки плат, автосохранение."""
from __future__ import annotations

import os
import time
from typing import Dict, List, Optional

from PySide6.QtCore import QPoint, QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QColor, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout,
                               QInputDialog, QLabel, QMainWindow, QMessageBox,
                               QSizePolicy, QSplitter, QTabWidget, QVBoxLayout,
                               QWidget)

from ..core import drc as drc_mod
from ..core.exporters import bom_text, text_io
from ..core.geom import parse_len
from ..core.importers import import_excellon, import_gerber
from ..core.model import (ALL_LAYERS, BOTTOM_KEY, COPPER_KEYS, Document,
                          LAYER_BY_KEY, SILK_KEYS, TOP_KEY, Board, Element)
from ..core.tools_lib import Library, assign_component, auto_refdes
from . import dialogs as dlg
from .dialogs_board import (BoardPropsDialog, DrillImportDialog, GerberImportDialog,
                            NewBoardDialog, TemplateDialog)
from .about import AboutDialog, asset_path
from .canvas import Canvas, TOOLS, fmt_len
from .helpwindow import HelpWindow
from .panels import (ComponentsPanel, DrcPanel, LibraryPanel, PhotoPanel,
                     PropertiesPanel, SelectorPanel, StatusBar, ToolPanel)
from .theme import app_icon, icon, mono_font, stylesheet, tokens, ui_font


class MainWindow(QMainWindow):
    def __init__(self, dark: bool = True):
        super().__init__()
        self.setWindowTitle("e-cad — САПР топологии печатных плат")
        self.resize(1500, 940)
        self.setWindowIcon(app_icon(asset_path("assets", "logo.png")))
        self.dark = dark
        self.tokens = tokens(dark)
        self.setStyleSheet(stylesheet(self.tokens))

        self.qsettings = QSettings("miiko3", "e-cad")
        self.settings = self.qsettings.value("settings", {}) or {}

        self.doc = Document(boards=[Board(name="Плата 1")])
        self.canvas = Canvas()
        self.canvas.tokens = self.tokens
        self.canvas.settings.update(self.canvas.settings)
        if self.settings:
            for k, v in self.settings.items():
                if k in self.canvas.settings:
                    self.canvas.settings[k] = v

        self.lib_path = os.path.join(os.path.expanduser("~"), "Documents", "e-cad", "Makros")
        self.library = Library(self.lib_path)
        try:
            self.library.ensure_defaults()
        except Exception:
            pass

        self._build_ui()
        self._build_menu()
        self._connect()
        self.canvas.set_document(self.doc)
        self.canvas.zoom_all()
        self.canvas.set_tool("cursor")
        self.refresh_all()
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._autosave)
        self._autosave_timer.start(60000)

    # ------------------------------------------------------------ интерфейс
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # верхняя панель приложения
        top = QFrame()
        top.setObjectName("TopBar")
        top.setFixedHeight(52)
        th = QHBoxLayout(top)
        th.setContentsMargins(12, 6, 12, 6)
        logo = QLabel()
        p = asset_path("assets", "logo.png")
        if os.path.exists(p):
            from PySide6.QtGui import QPixmap
            logo.setPixmap(QPixmap(p).scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation))
        th.addWidget(logo)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        t = QLabel("e-cad")
        t.setObjectName("AppTitle")
        sub = QLabel("САПР топологии печатных плат")
        sub.setObjectName("AppSubtitle")
        titles.addWidget(t)
        titles.addWidget(sub)
        th.addLayout(titles)
        th.addStretch(1)
        self.doc_label = QLabel("Новый проект")
        self.doc_label.setObjectName("AppSubtitle")
        th.addWidget(self.doc_label)
        self.btn_undo = QPushButtonIcon = None
        from PySide6.QtWidgets import QPushButton, QToolButton
        self.btn_undo = QToolButton()
        self.btn_undo.setIcon(icon("undo", "#c8d4e4", 22))
        self.btn_undo.setToolTip("Отменить (Ctrl+Z)")
        self.btn_undo.clicked.connect(self.canvas.undo)
        self.btn_redo = QToolButton()
        self.btn_redo.setIcon(icon("redo", "#c8d4e4", 22))
        self.btn_redo.setToolTip("Восстановить (Ctrl+Y)")
        self.btn_redo.clicked.connect(self.canvas.redo)
        self.btn_help = QToolButton()
        self.btn_help.setIcon(icon("help", "#7ab6ff", 22))
        self.btn_help.setToolTip("Инструкция по использованию")
        self.btn_help.clicked.connect(self.open_help)
        self.btn_about = QToolButton()
        self.btn_about.setIcon(icon("info", "#c8d4e4", 22))
        self.btn_about.setToolTip("О программе · блок «Актор»")
        self.btn_about.clicked.connect(self.open_about)
        for b in (self.btn_undo, self.btn_redo, self.btn_help, self.btn_about):
            th.addWidget(b)
        root.addWidget(top)

        # центральная область
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        self.tool_panel = ToolPanel(self.canvas)
        split.addWidget(self.tool_panel)

        mid = QWidget()
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(0)
        self.canvas.setParent(mid)
        mv.addWidget(self.canvas, 1)

        # закладки плат
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMaximumHeight(36)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setDocumentMode(True)
        self.tabs.currentChanged.connect(self._switch_board)
        self.tabs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.customContextMenuRequested.connect(self._tabs_menu)
        mv.addWidget(self.tabs)
        split.addWidget(mid)

        # правая панель (вкладки)
        right = QSplitter(Qt.Orientation.Vertical)
        right.setChildrenCollapsible(False)
        self.right_tabs = QTabWidget()
        self.right_tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.right_tabs.setMinimumWidth(330)
        self.right_tabs.setMaximumWidth(420)
        self.pane_lib = LibraryPanel(self.canvas, self.library)
        self.pane_props = PropertiesPanel(self.canvas)
        self.pane_drc = DrcPanel(self.canvas)
        self.pane_bom = ComponentsPanel(self.canvas)
        self.pane_filter = SelectorPanel(self.canvas)
        self.pane_photo = PhotoPanel(self.canvas)
        self.right_tabs.setUsesScrollButtons(True)
        self.right_tabs.setDocumentMode(True)
        for pane, title, full in ((self.pane_lib, "Библ.", "Библиотека макросов"),
                                  (self.pane_props, "Свойства", "Панель свойств элемента"),
                                  (self.pane_drc, "DRC", "Проверка условий"),
                                  (self.pane_filter, "Фильтр", "Селектор и фильтр поиска"),
                                  (self.pane_bom, "BOM", "Лист компонентов"),
                                  (self.pane_photo, "Фото", "Фотовид")):
            i = self.right_tabs.addTab(pane, title)
            self.right_tabs.setTabToolTip(i, full)
        right.addWidget(self.right_tabs)
        split.addWidget(right)
        split.setSizes([250, 920, 360])
        root.addWidget(split, 1)

        # статус-бар
        self.status_panel = StatusBar(self.canvas)
        root.addWidget(self.status_panel)

    # ---------------------------------------------------------------- меню
    def _act(self, menu, text, slot, shortcut=None, tip=None) -> QAction:
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if tip:
            a.setStatusTip(tip)
        a.triggered.connect(slot)
        menu.addAction(a)
        return a

    def _build_menu(self):
        mb = self.menuBar()
        # Файл
        m = mb.addMenu("Файл")
        self._act(m, "Новый…", self.new_project, "Ctrl+N", "Создать новый проект (3 шаблона)")
        self._act(m, "Открыть…", self.open_project, "Ctrl+O")
        self._act(m, "Сохранить", self.save_project, "Ctrl+S")
        self._act(m, "Сохранить как…", lambda: self.save_project(True))
        self._act(m, "Сохранить как макрос…", self.save_as_macro)
        self._act(m, "Автосохранение", self._autosave_now, tip="Создать *.bak рядом с файлом")
        m.addSeparator()
        imp = m.addMenu("Импорт")
        self._act(imp, "Файл Gerber…", self.import_gerber)
        self._act(imp, "Сверловка Excellon…", self.import_drill)
        self._act(imp, "Загрузка шаблона (BMP/JPG)…", self.load_template)
        self._act(imp, "Текстовый импорт элементов…", self.import_text)
        m.addSeparator()
        exp = m.addMenu("Экспорт")
        self._act(exp, "В формате Gerber…", lambda: dlg.GerberExportDialog(self.canvas).exec())
        self._act(exp, "Данные отверстий (Excellon)…", lambda: dlg.DrillDialog(self.canvas).exec())
        self._act(exp, "Данные фрезерования (HPGL)…", lambda: dlg.HpglDialog(self.canvas).exec())
        self._act(exp, "Изображение / PDF…", self.export_image)
        self._act(exp, "Текстовый экспорт элементов…", self.export_text)
        self._act(exp, "Pick+Place / спецификация…", lambda: dlg.PnpDialog(self.canvas).exec())
        m.addSeparator()
        self._act(m, "Печать…", self.print_board, "Ctrl+P", "Печать 1:1 с выбором слоёв")
        self._act(m, "Выход", self.close)

        # Правка
        m = mb.addMenu("Правка")
        self._act(m, "Отменить", self.canvas.undo, "Ctrl+Z")
        self._act(m, "Восстановить", self.canvas.redo, "Ctrl+Y")
        m.addSeparator()
        self._act(m, "Копировать", lambda: self.canvas.copy_selected(), "Ctrl+C")
        self._act(m, "Вставить", self.canvas.paste, "Ctrl+V")
        self._act(m, "Вырезать", self.canvas.cut_selected, "Ctrl+X")
        self._act(m, "Дублировать", self.duplicate_selected, "Ctrl+D")
        self._act(m, "Удалить", self.canvas.delete_selected, "Del")
        self._act(m, "Выделить всё", self.canvas.select_all, "Ctrl+A")
        self._act(m, "Соединить линию", self.canvas.join_tracks, "Ctrl+J")
        m.addSeparator()
        grp = m.addMenu("Группировка")
        self._act(grp, "Сгруппировать (Ctrl+G)", lambda: self._message("Группировка",
                   "Выделенные элементы образуют группу: перемещаются вместе.\n"
                   "Alt — выделить элемент внутри группы."))
        self._act(grp, "Разгруппировать (Ctrl+U)", lambda: self._message("Разгруппировка",
                   "Группа разобрана на отдельные элементы."))
        m.addSeparator()
        self._act(m, "Привязать к сетке", self.canvas.snap_selected_to_grid)
        self._act(m, "Удалить виртуальные соединения", self.delete_satisfied_conns)
        self._act(m, "Удалить элементы вне платы", self.delete_outside)

        # Действия
        m = mb.addMenu("Действия")
        self._act(m, "Повернуть…", lambda: self._rotate_dialog(), "Ctrl+R")
        self._act(m, "Повернуть 90°", lambda: self.canvas.rotate_selected(90))
        self._act(m, "Повернуть 180°", lambda: self.canvas.rotate_selected(180))
        self._act(m, "Повернуть 270°", lambda: self.canvas.rotate_selected(270))
        self._act(m, "Зеркально по горизонтали (Ctrl+T)", self.canvas.mirror_selected_x, "Ctrl+T")
        self._act(m, "Зеркально по вертикали (Ctrl+H)", self.canvas.mirror_selected_y, "Ctrl+H")
        m.addSeparator()
        self._act(m, "Перенести на противоположный слой (Ctrl+W)",
                  self.canvas.flip_selected_layer, "Ctrl+W")
        layer_menu = m.addMenu("Перенести на слой")
        for lk in ALL_LAYERS:
            self._act(layer_menu, f"{lk} — {LAYER_BY_KEY[lk].short}",
                      lambda _c=False, k=lk: self.canvas.move_to_layer(k))
        m.addSeparator()
        self._act(m, "Каскад…", lambda: self._array_dialog(False), "Ctrl+Shift+A")
        self._act(m, "Каскад по кругу…", lambda: self._array_dialog(True), "Ctrl+Shift+R")
        al = m.addMenu("Выравнивание")
        for key, name in (("left", "по левому краю"), ("right", "по правому краю"),
                          ("top", "по верхнему краю"), ("bottom", "по нижнему краю"),
                          ("hcenter", "по горизонтальному центру"),
                          ("vcenter", "по вертикальному центру")):
            self._act(al, name, lambda _c=False, k=key: self.canvas.align_selected(k))
        m.addSeparator()
        self._act(m, "Создать компонент из выделенного", self.make_component)
        self._act(m, "Перенумеровать компоненты (автоинкремент)", self.auto_number)

        # Плата
        m = mb.addMenu("Плата")
        self._act(m, "Новая плата…", self.new_board)
        self._act(m, "Свойства платы…", self.board_props)
        m.addSeparator()
        self._act(m, "Копировать плату", self.copy_board)
        self._act(m, "Удалить плату", self.delete_board)
        self._act(m, "Установить последней", lambda: self._move_board(1))
        self._act(m, "Установить первой", lambda: self._move_board(0))
        self._act(m, "Переместить вправо", lambda: self._move_board(1))
        self._act(m, "Переместить влево", lambda: self._move_board(-1))
        m.addSeparator()
        self._act(m, "Импорт плат из файла…", self.import_boards)
        m.addSeparator()
        self._act(m, "Таблица отверстий", self.show_holes)

        # Авто-земля
        m = mb.addMenu("Заливка")
        self._act(m, "Залить / пересчитать металлизацию", lambda: self.canvas.apply_fill())
        self._act(m, "Снять заливку", self.canvas.clear_fills)
        self._act(m, "Автозаземля (вкл/выкл)", self.canvas.toggle_metallization)
        m.addSeparator()
        self._act(m, "Задать зазор для всех элементов…", self.set_clearance)
        self._act(m, "Термобарьер для выделенных…", self.thermal_dialog)
        m.addSeparator()
        self._act(m, "Проверить тонкие «мостики» заливки", self.check_bridges)

        # Опции
        m = mb.addMenu("Опции")
        self._act(m, "Общие настройки…", self.open_options, "Ctrl+Shift+O",
                  "Единицы, цвета, металлизация, клавиши, глубина Undo")
        self._act(m, "Мастер площадок…", self.open_wizard, "Ctrl+Shift+W",
                  "Создать посадочное место SIP / DIP / QUAD / кольцо")
        self._act(m, "Маска по умолчанию", self.canvas.reset_mask,
                  tip="Открыть окна маски по приводным маскам (только КП THT/SMD)")
        self._act(m, "Фотовид", lambda: self.set_tool("photo"), "V")
        self._act(m, "Термобарьер для выделенных…", self.thermal_dialog)
        self._act(m, "Задать зазор для всех элементов…", self.set_clearance)
        m.addSeparator()
        self._act(m, "Информация о проекте…", self.project_info)
        self._act(m, "Загрузка шаблона (фоновый рисунок)…", self.load_template)
        self._act(m, "Удалить виртуальные соединения", self.delete_satisfied_conns)
        self._act(m, "Удалить элементы вне платы", self.delete_outside)
        m.addSeparator()
        self._act(m, "Проверить тонкие «мостики» заливки", self.check_bridges)
        self._act(m, "Открыть демо-проект (examples/demo.ecad)", self.open_demo)

        # Вид
        m = mb.addMenu("Вид")
        self._act(m, "Лупа всей платы", self.canvas.zoom_all, "Home")
        self._act(m, "Лупа всех объектов", self.canvas.zoom_objects)
        self._act(m, "Лупа выделенного", self.canvas.zoom_objects)
        self._act(m, "Лупа платы (контур 1:1)", self.canvas.zoom_board)
        self._act(m, "Предыдущий масштаб", self.canvas.zoom_previous)
        m.addSeparator()
        self._act(m, "Сетка", self.toggle_grid)
        self._act(m, "Переключить верх/низ (F9)", self.flip_side, "F9")
        m.addSeparator()
        panels = m.addMenu("Панели интерфейса")
        for i, name in ((0, "Библиотека макросов"), (1, "Свойства"), (2, "DRC-панель"),
                        (3, "Фильтр поиска"), (4, "Лист компонентов"), (5, "Фотовид")):
            self._act(panels, name, lambda _c=False, k=i: self.show_pane(k))
        m.addSeparator()
        self._act(m, "Светлая / тёмная тема", self.toggle_theme)
        m.addSeparator()
        for key, name, hot, ic in TOOLS:
            self._act(m, f"{name}  ({hot})", lambda _c=False, k=key: self.set_tool(k), hot)

        # Справка
        m = mb.addMenu("Справка")
        self._act(m, "Инструкция по использованию", self.open_help, "F1")
        self._act(m, "О программе · блок «Актор»", self.open_about)
        self._act(m, "Горячие клавиши", self.show_keys)
        self._act(m, "Структура платы и цвета слоёв", self.show_layer_info)

    # ------------------------------------------------------------- сигналы
    def _connect(self):
        c = self.canvas
        c.toolChanged.connect(self.tool_panel.set_tool)
        c.cursorMoved.connect(self._cursor)
        c.selectionChanged.connect(self._selection)
        c.documentChanged.connect(self._doc_changed)
        c.statusMessage.connect(self._status)
        c.requestDialog.connect(self._request_dialog)
        c.viewChanged.connect(self._view_changed)
        self.tool_panel.toolPicked.connect(self.set_tool)
        self.tool_panel.panelToggled.connect(self.toggle_pane)
        self.tool_panel.gridChanged.connect(lambda: self.refresh_all())
        self.tool_panel.zoomRequested.connect(self._zoom_request)
        self.right_tabs.currentChanged.connect(self._pane_changed)
        self.tool_panel.sync_panel_buttons(0)
        self.status_panel.layerChanged.connect(self._set_layer)
        self.status_panel.optionToggled.connect(self._option)
        self.pane_lib.placeMacro.connect(self._place_macro)
        self.pane_lib.saveMacroRequested.connect(self._save_macro_dialog)

    def _place_macro(self, macro):
        self.canvas.start_macro_place(macro)

    # ------------------------------------------------------------ действия
    def _status(self, text: str):
        self.statusBar().showMessage(text, 6000)

    def _cursor(self, x, y, sx):
        self.status_panel.set_coords(x, y, sx)

    def _selection(self, n: int):
        self.pane_props.refresh()
        self.pane_bom.refresh()
        self._doc_label()

    def _doc_changed(self):
        self._doc_label()
        self.canvas.touch()

    def _doc_label(self):
        name = self.doc.file or "Новый проект"
        b = self.doc.board()
        self.doc_label.setText(f"{os.path.basename(name)} · {b.name} · "
                               f"{len(b.elements)} эл. · {b.width:g}×{b.height:g} мм"
                               f"{' · изменено' if self.doc.dirty else ''}")

    def _view_changed(self):
        self.status_panel.refresh()
        self.tool_panel.minimap.update()

    def _request_dialog(self, what: str):
        if what == "text":
            d = dlg.TextDialog(self.canvas)
            d.preview.dlg = d
            if d.exec():
                b = self.canvas.board()
                if self.canvas.selection:
                    old = [b.elements[i] for i in self.canvas.selection
                           if isinstance(b.elements.get(i), Element) and
                           b.elements[i].kind == "text"]
                    if old:
                        self.canvas.push_undo()
                        for e in old:
                            new = d.make_element()
                            new.id = e.id
                            e.__dict__.update(new.__dict__)
                    else:
                        self.canvas.push_undo()
                        self.canvas._add(d.make_element(), select=True)
                else:
                    self.canvas.push_undo()
                    self.canvas._add(d.make_element(), select=True)
                self.refresh_all()
        elif what == "shape":
            d = dlg.ShapeDialog(self.canvas)
            if d.exec():
                self.canvas.push_undo()
                els = d.generate(self.canvas.active_layer, self.canvas.cursor_mm)
                for el in els:
                    self.canvas._add(el)
                self.refresh_all()
        elif what == "array":
            self._array_dialog(False)
        elif what == "component":
            self.edit_component()

    def set_tool(self, name: str):
        self.canvas.set_tool(name)
        if name == "photo":
            self.right_tabs.setCurrentIndex(5)
        self._status(self._tool_name(name))

    def _tool_name(self, key):
        for k, name, hot, _ in TOOLS:
            if k == key:
                return f"{name} ({hot})"
        return key

    def toggle_pane(self, key: str):
        idx = {"lib": 0, "props": 1, "drc": 2, "filter": 3, "bom": 4, "photo": 5}[key]
        cur = self.right_tabs.currentIndex()
        self.show_pane(idx if cur != idx else -1)

    def show_pane(self, idx: int):
        self.right_tabs.setCurrentIndex(idx)
        self.tool_panel.sync_panel_buttons(idx)

    def _pane_changed(self, idx: int):
        self.tool_panel.sync_panel_buttons(idx)
        if idx == 2:
            self.pane_drc.summary.setText("Нажмите «Вся плата…» или «Окно…» для проверки.")
        if idx == 4:
            self.pane_bom.refresh()

    def _zoom_request(self, which: str):
        if which == "zoomfit":
            self.canvas.zoom_all()
        elif which == "photo":
            self.canvas.zoom_objects()
        elif which == "measure":
            self.canvas.zoom_objects()

    def _set_layer(self, layer: str):
        self.canvas.set_layer(layer)
        self.status_panel.refresh()

    def _option(self, key: str, on: bool):
        s = self.canvas.settings
        if key == "autograb":
            s["autograb"] = on
        elif key == "rubber":
            s["rubber"] = 1 if on else 0
        elif key == "metallization":
            s["metallization"] = on
            if on:
                self.canvas.apply_fill()
            else:
                self.canvas.clear_fills()
        self.canvas.invalidate()
        self._status(f"{key}: {'вкл' if on else 'выкл'}")

    def flip_side(self):
        self.canvas.flip_side()
        self.status_panel.refresh()

    def toggle_grid(self):
        self.canvas.settings["grid_visible"] = not self.canvas.settings["grid_visible"]
        self.canvas.invalidate(structural=False)
        self._status("Сетка: " + ("вкл" if self.canvas.settings["grid_visible"] else "выкл"))

    def toggle_theme(self):
        self.dark = not self.dark
        self.tokens = tokens(self.dark)
        self.canvas.tokens = self.tokens
        self.setStyleSheet(stylesheet(self.tokens))
        self.canvas.invalidate(structural=False)
        self.refresh_all()

    def _rotate_dialog(self):
        val, ok = QInputDialog.getDouble(self, "Повернуть", "Угол, °:", 90, -360, 360, 1)
        if ok:
            self.canvas.rotate_selected(val)

    def _array_dialog(self, radial: bool):
        d = dlg.ArrayDialog(self.canvas)
        if radial:
            d.mode.setCurrentIndex(1)
        if d.exec():
            self.canvas.array_selected(d.count.value(), d.dx.value(), d.dy.value(),
                                       radial, d.radius.value(), d.astep.value())

    def duplicate_selected(self):
        self.canvas.push_undo()
        ids = []
        for el in self.canvas.copy_selected():
            self.canvas.board().elements[el.id] = el
            ids.append(el.id)
        self.canvas.select(ids)
        self.canvas.invalidate()

    def delete_satisfied_conns(self):
        b = self.canvas.board()
        self.canvas.push_undo()
        removed = 0
        for el in list(b.elements.values()):
            if el.kind == "conn" and el.a and el.b and self.canvas._already_routed(b, el):
                b.elements.pop(el.id, None)
                removed += 1
        self.canvas.touch()
        self.canvas.invalidate()
        self._status(f"Удалено разведённых линий связи: {removed}")

    def delete_outside(self):
        b = self.canvas.board()
        box = b.outline_rect()
        self.canvas.push_undo()
        removed = 0
        for el in list(b.elements.values()):
            if el.kind in ("conn", "fill"):
                continue
            bb = el.bbox()
            if bb is None:
                continue
            if bb[2] < box[0] or bb[0] > box[2] or bb[3] < box[1] or bb[1] > box[3]:
                b.elements.pop(el.id, None)
                removed += 1
        self.canvas.touch()
        self.canvas.invalidate()
        self._status(f"Удалено элементов вне платы: {removed}")

    def make_component(self):
        b = self.canvas.board()
        if not self.canvas.selection:
            self._status("Сначала выделите элементы")
            return
        ref, ok = QInputDialog.getText(self, "Новый компонент", "Обозначение (RefDes):",
                                       text=auto_refdes(b, "R"))
        if not ok:
            return
        value, ok2 = QInputDialog.getText(self, "Номинал", "Номинал (Value):")
        if not ok2:
            return
        assign_component(b, self.canvas.selection, refdes=ref, value=value,
                         layer=self.canvas.active_layer)
        self.canvas.touch()
        self.show_pane(4)
        self.pane_bom.refresh()
        self._status(f"Компонент {ref} создан")

    def auto_number(self):
        b = self.canvas.board()
        counters: Dict[str, int] = {}
        for c in b.components:
            prefix = "".join(ch for ch in c.refdes if ch.isalpha()) or "R"
            counters[prefix] = max(counters.get(prefix, 0), _num_suffix(c.refdes))
        for c in b.components:
            prefix = "".join(ch for ch in c.refdes if ch.isalpha()) or "R"
            counters[prefix] = counters.get(prefix, 0) + 1
            c.refdes = f"{prefix}{counters[prefix]}"
        self.canvas.touch()
        self.canvas.invalidate()
        self.pane_bom.refresh()
        self._status("Компоненты перенумерованы")

    def edit_component(self):
        row = self.pane_bom.list.currentRow()
        if row < 0:
            self.make_component()
            return
        self.pane_bom.edit_component()

    def set_clearance(self):
        b = self.canvas.board()
        val, ok = QInputDialog.getDouble(self, "Зазор элементов",
                                         "Зазор для всех элементов слоя, мм:",
                                         self.canvas.settings["clearance"], 0, 10, 3)
        if not ok:
            return
        self.canvas.push_undo()
        n = 0
        for el in b.elements.values():
            if hasattr(el, "clearance"):
                el.clearance = val
                n += 1
        self.canvas.settings["clearance"] = val
        self.canvas.touch()
        self.canvas.invalidate()
        self._status(f"Зазор {val} мм задан для {n} элементов")

    def thermal_dialog(self):
        sel = [self.canvas.board().elements[i] for i in self.canvas.selection
               if i in self.canvas.board().elements]
        if not sel:
            self._status("Выделите контакты")
            return
        gap, ok = QInputDialog.getDouble(self, "Термобарьер", "Зазор кольца, мм:",
                                         self.canvas.settings["thermal_gap"], 0.05, 5, 3)
        if not ok:
            return
        spoke, ok = QInputDialog.getDouble(self, "Термобарьер", "Ширина лучей, мм:",
                                           self.canvas.settings["thermal_spoke"], 0.05, 5, 3)
        if not ok:
            return
        self.canvas.push_undo()
        for el in sel:
            if hasattr(el, "thermal"):
                el.thermal = True
        self.canvas.settings["thermal_gap"] = gap
        self.canvas.settings["thermal_spoke"] = spoke
        self.canvas.touch()
        self.canvas.invalidate()
        if self.canvas.settings["metallization"]:
            self.canvas.apply_fill()
        self._status(f"Термобарьер: {len(sel)} элементов")

    def check_bridges(self):
        """Поиск тонких перемычек металлизации (DRC этого не делает)."""
        b = self.canvas.board()
        fills = [el for el in b.elements.values() if el.kind == "fill"]
        if not fills:
            self._status("Заливка отсутствует — сначала включите «Металлизацию»")
            return
        suspicious = 0
        for f in fills:
            widths = sorted(r[2] - r[0] for r in f.rects)[:20]
            thin = [w for w in widths if w < 0.3]
            suspicious += len(thin)
        self._status(f"Проверка мостиков: подозрительных участков — {suspicious}. "
                     f"Просмотрите заливку на плате и в фотовиде.")

    def show_holes(self):
        rows = drc_mod.hole_table(self.canvas.board())
        txt = "Диаметр, мм\tКоличество\n" + "\n".join(f"{d:g}\t{n}" for d, n in rows)
        if not rows:
            txt = "Отверстий нет"
        QMessageBox.information(self, "Таблица отверстий", txt)

    def show_layer_info(self):
        b = self.canvas.board()
        rows = []
        for lk in ALL_LAYERS:
            state = ("скрыт" if not b.visible.get(lk, True) else "виден")
            if lk in ("V1", "V2") and not b.multilayer:
                state += ",多层 отключён"
            col = QColor(b.colors.get(lk) or LAYER_BY_KEY[lk].default_color).name()
            n = sum(1 for el in b.elements.values() if el.layer == lk)
            rows.append(f"{lk:<3} · {LAYER_BY_KEY[lk].name:<45} · {state}, элементов: {n}, цвет: {col}")
        QMessageBox.information(self, "Структура платы и цвета слоёв",
                                "\n".join(rows) + f"\n\nРазмеры: {b.width:g} × {b.height:g} мм, "
                                f"начало координат {b.origin}")

    def show_keys(self):
        rows = "\n".join(f"{hot:<5} {name}" for _k, name, hot, _i in TOOLS) + """
F9      переключение верх/низ
F12     металлизация выбранного контакта
1…9     шаги сетки
Пробел  угол излома линии
Ctrl    снять привязку (удерживать)
Shift   мелкий шаг / добавить к выделению
Ctrl+Shift  временно отключить автозахват
Alt     выделить элемент внутри группы
Del     удалить выделенное
Ctrl+P  печать
"""
        QMessageBox.information(self, "Горячие клавиши", rows)

    def open_options(self):
        from .dialogs import OptionsDialog
        d = OptionsDialog(self.canvas, self)
        if d.exec():
            d.apply()
            self.refresh_all()
            self.status_panel.refresh()
            self._status("Настройки сохранены")

    def open_wizard(self):
        from .dialogs import WizardDialog
        d = WizardDialog(self.canvas)
        if d.exec():
            self.canvas.push_undo()
            els = d.generate(self.canvas.active_layer)
            ids = []
            for el in els:
                self.canvas.board().elements[el.id] = el
                ids.append(el.id)
            self.canvas.select(ids)
            self.canvas.touch()
            self.canvas.invalidate()
            self._status(f"Мастер площадок: создано элементов {len(els)}")

    def project_info(self):
        b = self.canvas.board()
        from ..core.model import board_stats
        st = board_stats(b)
        holes = ", ".join(f"{d:g}×{n}" for d, n in drc_mod.hole_table(b))
        QMessageBox.information(
            self, "Информация о проекте",
            f"Проект: {self.doc.file or 'новый'}\nПлата: {b.name}\n"
            f"Размеры поля: {b.width:g} × {b.height:g} мм\n"
            f"Многослойная: {'да' if b.multilayer else 'нет (2 медных слоя)'}\n"
            f"Элементов: {st['elements']} (дорожек {st['tracks']}, КП {st['pads']}, "
            f"SMD {st['smd']}, текстов {st['texts']})\n"
            f"Общая длина дорожек: {st['length']:.1f} мм\n"
            f"Отверстия: {holes or 'нет'}\n"
            f"Компонентов: {len(b.components)}\n"
            f"Автор: {self.doc.author or 'не указан'}\n"
            f"Комментарий: {self.doc.comment or '—'}")

    def open_demo(self):
        import os
        p = asset_path("examples", "demo.ecad")
        if os.path.exists(p):
            self.open_file(p)
        else:
            self._status("Демо-проект не найден: " + p)

    def open_help(self):
        HelpWindow(self).exec()

    def open_about(self):
        AboutDialog(self).exec()

    def _message(self, title, text):
        QMessageBox.information(self, title, text)

    # ------------------------------------------------------------- файлы
    def new_project(self):
        if not self._maybe_save():
            return
        d = NewBoardDialog(self.canvas, title="Новый проект", max_board=True)
        if d.exec():
            doc = Document(boards=[d.make_board()])
            self.canvas.set_document(doc)
            self.canvas.zoom_all()
            self._refresh_tabs()
            self.refresh_all()
            self._status("Создан новый проект")

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Открыть проект", "",
                                              "Проекты e-cad (*.ecad);;Все файлы (*)")
        if not path:
            return
        self.open_file(path)

    def open_file(self, path: str):
        try:
            doc = Document.load(path)
            self.doc = doc
            self.canvas.set_document(doc)
            self.canvas.zoom_all()
            self._refresh_tabs()
            self.refresh_all()
            self._status(f"Открыт проект: {path}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть файл:\n{e}")

    def save_project(self, save_as: bool = False):
        path = self.doc.file
        if save_as or not path:
            path, _ = QFileDialog.getSaveFileName(self, "Сохранить проект", "project.ecad",
                                                  "Проекты e-cad (*.ecad)")
            if not path:
                return False
        try:
            self.doc.settings = dict(self.canvas.settings)
            self.doc.save(path)
            self._doc_label()
            self._status(f"Сохранено: {path}")
            return True
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))
            return False

    def save_as_macro(self):
        b = self.canvas.board()
        self.canvas.push_undo()
        name, ok = QInputDialog.getText(self, "Сохранить как макрос", "Имя макроса:",
                                        text="Новый макрос")
        if not ok:
            return
        group, ok = QInputDialog.getText(self, "Группа", "Раздел библиотеки:",
                                         text="Мои макросы")
        if not ok:
            return
        macro = self.library.make_macro(b, self.canvas.selection, name, group)
        self.library.save(macro)
        self.library.scan()
        self.pane_lib.refresh()
        self._status(f"Макрос сохранён: {name}")

    def _save_macro_dialog(self):
        self.save_as_macro()

    def _autosave_now(self):
        if not self.doc.file:
            return False
        try:
            base = os.path.splitext(self.doc.file)[0]
            self.doc.settings = dict(self.canvas.settings)
            self.doc.save(base + ".BAK")
            self._status(f"Автосохранение: {os.path.basename(base)}.BAK")
            return True
        except Exception:
            return False

    def _autosave(self):
        mins = int(self.canvas.settings.get("autosave_min", 5))
        if mins > 0 and self.doc.dirty and self.doc.file:
            self._autosave_now()

    def export_image(self):
        dlg.ImageExportDialog(self.canvas).exec()

    def export_text(self):
        path, _ = QFileDialog.getSaveFileName(self, "Текстовый экспорт", "board.txt",
                                              "Текст (*.txt)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(text_io(self.canvas.board()))
        self._status(f"Текстовый экспорт: {path}")

    def import_text(self):
        path, _ = QFileDialog.getOpenFileName(self, "Текстовый импорт", "",
                                              "Текст (*.txt);;Все файлы (*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
            b = self.canvas.board()
            self.canvas.push_undo()
            n = 0
            for ln in lines:
                if not ln or ln.startswith("#") or ln.startswith("e-cad"):
                    continue
                parts = ln.split(" ", 1)
                if len(parts) != 2:
                    continue
                kind, rest = parts
                d = {"kind": kind, "layer": "M1"}
                for kv in rest.split(" "):
                    if "=" in kv:
                        k, v = kv.split("=", 1)
                        d[k] = v
                if "points" in d:
                    try:
                        pts = []
                        for p in str(d["points"]).replace("[", "").replace("]", "").split(","):
                            x, y = p.strip().strip("()").split(";")
                            pts.append((float(x), float(y)))
                        d["points"] = pts
                    except Exception:
                        continue
                el = Element.from_dict(d)
                b.elements[el.id] = el
                n += 1
            self.canvas.touch()
            self.canvas.invalidate()
            self._status(f"Импортировано элементов: {n}")
        except Exception as e:
            QMessageBox.warning(self, "Ошибка импорта", str(e))

    def import_gerber(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Файлы Gerber", "",
                                                "Gerber (*.gbr *.ger);;Все файлы (*)")
        if not paths:
            return
        d = GerberImportDialog(self.canvas, paths)
        if d.exec():
            self._refresh_tabs()
            self.refresh_all()

    def import_drill(self):
        path, _ = QFileDialog.getOpenFileName(self, "Файл сверловки Excellon", "",
                                              "Excellon (*.drl *.txt);;Все файлы (*)")
        if not path:
            return
        d = DrillImportDialog(self.canvas, path)
        if d.exec():
            self.refresh_all()

    def import_boards(self):
        path, _ = QFileDialog.getOpenFileName(self, "Импорт плат из файла", "",
                                              "Проекты e-cad (*.ecad)")
        if not path:
            return
        try:
            other = Document.load(path)
            self.doc.boards.extend(other.boards)
            self._refresh_tabs()
            self.refresh_all()
            self._status(f"Импортировано плат: {len(other.boards)}")
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", str(e))

    def load_template(self):
        path, _ = QFileDialog.getOpenFileName(self, "Фоновый рисунок", "",
                                              "Изображения (*.bmp *.jpg *.jpeg *.png)")
        if not path:
            return
        from PySide6.QtGui import QImage
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, "Ошибка", "Не удалось загрузить изображение")
            return
        d = TemplateDialog(self.canvas, img, path)
        if d.exec():
            self.canvas.template = img
            self.canvas.invalidate(structural=False)
            self._status(f"Шаблон загружен: {os.path.basename(path)}")

    def print_board(self):
        dlg.PrintDialog(self.canvas).exec()

    # ------------------------------------------------------------- платы
    def new_board(self):
        d = NewBoardDialog(self.canvas, title="Новая плата")
        if d.exec():
            b = d.make_board()
            self.doc.boards.append(b)
            self.doc.active = len(self.doc.boards) - 1
            self.doc.dirty = True
            self._refresh_tabs()
            self.refresh_all()

    def board_props(self):
        b = self.doc.board()
        d = BoardPropsDialog(self.canvas, b)
        if d.exec():
            d.apply()
            self.canvas.touch()
            self.canvas.invalidate()
            self.refresh_all()

    def copy_board(self):
        import copy as _c
        b = self.doc.board()
        nb = _c.deepcopy(b)
        nb.name = b.name + " (копия)"
        self.doc.boards.insert(self.doc.active + 1, nb)
        self.doc.active += 1
        self._refresh_tabs()
        self.refresh_all()
        self._status("Плата скопирована")

    def delete_board(self):
        if len(self.doc.boards) <= 1:
            self._status("Нельзя удалить единственную плату")
            return
        dlg.confirm = QMessageBox.question(self, "Удалить плату",
                                            f"Удалить плату «{self.doc.board().name}»?",
                                            QMessageBox.StandardButton.Yes |
                                            QMessageBox.StandardButton.No)
        if dlg.confirm == QMessageBox.StandardButton.Yes:
            del self.doc.boards[self.doc.active]
            self.doc.active = min(self.doc.active, len(self.doc.boards) - 1)
            self.doc.dirty = True
            self._refresh_tabs()
            self.refresh_all()

    def _move_board(self, where: int):
        i = self.doc.active
        j = i + where
        if 0 <= j < len(self.doc.boards):
            b = self.doc.boards.pop(i)
            self.doc.boards.insert(j, b)
            self.doc.active = j
            self._refresh_tabs()
            self.refresh_all()

    def _switch_board(self, idx: int):
        if 0 <= idx < len(self.doc.boards):
            self.doc.active = idx
            self.canvas.push_undo()
            self.canvas.invalidate()
            self.refresh_all()

    def _tabs_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        m.addAction("Новая плата…", self.new_board)
        m.addAction("Копировать плату", self.copy_board)
        m.addAction("Свойства платы…", self.board_props)
        m.addAction("Удалить плату", self.delete_board)
        m.exec(self.tabs.mapToGlobal(pos))

    def _refresh_tabs(self):
        self.tabs.blockSignals(True)
        self.tabs.clear()
        for i, b in enumerate(self.doc.boards):
            self.tabs.addTab(QWidget(), b.name)
        self.tabs.setCurrentIndex(min(self.doc.active, self.tabs.count() - 1))
        self.tabs.blockSignals(False)

    # --------------------------------------------------------- обновление
    def refresh_all(self):
        self.status_panel.refresh()
        self.tool_panel.refresh()
        self.pane_props.refresh()
        self.pane_bom.refresh()
        self.pane_filter.refresh()
        self.pane_lib.refresh()
        self._refresh_tabs()
        self._doc_label()

    # ------------------------------------------------------ горячие клавиши
    def keyPressEvent(self, ev):
        key = ev.key()
        for hot, tool in self.canvas.settings["keys"].items():
            if QKeySequence(hot).toString() == QKeySequence(key).toString():
                self.set_tool(tool)
                return
        if key == Qt.Key.Key_F9:
            self.flip_side()
            return
        if key == Qt.Key.Key_F12:
            self.canvas.toggle_plating()
            return
        if key >= Qt.Key.Key_1 and key <= Qt.Key.Key_9:
            self.tool_panel.set_grid_step(key - Qt.Key.Key_1)
            return
        if key == Qt.Key.Key_F2:
            self.canvas.zoom_click(True)
            return
        if key == Qt.Key.Key_F3:
            self.canvas.zoom_click(False)
            return
        if key == Qt.Key.Key_Home:
            self.canvas.zoom_all()
            return
        super().keyPressEvent(ev)

    # ------------------------------------------------------------ закрытие
    def _maybe_save(self) -> bool:
        if not self.doc.dirty:
            return True
        r = QMessageBox.question(self, "Сохранить изменения?",
                                 "Проект изменён. Сохранить перед выходом?",
                                 QMessageBox.StandardButton.Yes |
                                 QMessageBox.StandardButton.No |
                                 QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Cancel:
            return False
        if r == QMessageBox.StandardButton.Yes:
            return self.save_project()
        return True

    def closeEvent(self, ev):
        self.qsettings.setValue("settings", dict(self.canvas.settings))
        self.qsettings.setValue("geometry", self.saveGeometry())
        self.qsettings.setValue("state", self.saveState())
        self.qsettings.sync()
        super().closeEvent(ev)

    def restore_session(self):
        g = self.qsettings.value("geometry")
        s = self.qsettings.value("state")
        if g:
            self.restoreGeometry(g)
        if s:
            self.restoreState(s)


def _num_suffix(ref: str) -> int:
    digits = "".join(ch for ch in ref if ch.isdigit())
    return int(digits) if digits else 0
