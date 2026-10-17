"""Диалоги: новая плата, свойства платы, импорт Gerber/Excellon, шаблон."""
from __future__ import annotations

import os
from typing import List, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox,
                               QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QRadioButton, QSpinBox,
                               QVBoxLayout, QWidget)

from ..core.importers import import_excellon, import_gerber
from ..core.model import ALL_LAYERS, Board, LAYER_BY_KEY
from .dialogs import BaseDialog, _form, _form_rows, _row, _spin


class NewBoardDialog(BaseDialog):
    """3 шаблона: пустое поле / плата с отступом / круглый контур."""

    def __init__(self, canvas, title: str = "Новая плата", max_board: bool = False):
        super().__init__(canvas, title, w=440)
        self.max_board = max_board
        self.g1 = QRadioButton("Пустое рабочее поле")
        self.g2 = QRadioButton("Плата заданного размера с отступом от краёв")
        self.g3 = QRadioButton("Квадратное поле с круглым контуром")
        self.g2.setChecked(True)
        bg = QButtonGroup(self)
        for b in (self.g1, self.g2, self.g3):
            bg.addButton(b)
        self.w = _spin(2, 1, 500, 5, 100)
        self.h = _spin(2, 1, 500, 5, 80)
        self.margin = _spin(2, 0, 200, 1, 10)
        self.dia = _spin(2, 5, 500, 5, 80)
        self.name = QLineEdit("Плата")
        self.max_label = QLabel("Максимальный размер рабочего поля — 500 × 500 мм.")
        self.max_label.setWordWrap(True)
        self.v.addWidget(self.g1)
        self.v.addWidget(self.g2)
        self.v.addLayout(_form(("Ширина, мм:", self.w), ("Высота, мм:", self.h)))
        self.v.addWidget(self.g3)
        self.v.addLayout(_form(("Диаметр контура, мм:", self.dia)))
        self.v.addLayout(_form(("Отступ от края поля, мм:", self.margin)))
        self.v.addLayout(_form(("Имя платы:", self.name)))
        self.v.addWidget(self.max_label)
        for b in (self.g1, self.g2, self.g3):
            b.toggled.connect(self._upd)
        self._upd()
        self.buttons("Создать")

    def _upd(self):
        rect = self.g2.isChecked()
        circle = self.g3.isChecked()
        self.w.setEnabled(rect)
        self.h.setEnabled(rect)
        self.dia.setEnabled(circle)

    def template(self) -> int:
        if self.g1.isChecked():
            return 0
        if self.g3.isChecked():
            return 2
        return 1

    def make_board(self) -> Board:
        b = Board(name=self.name.text().strip() or "Плата",
                  width=self.w.value() if self.template() != 2 else self.dia.value(),
                  height=self.h.value() if self.template() != 2 else self.dia.value(),
                  origin=(self.margin.value(), self.margin.value()),
                  outline_round=self.dia.value() if self.template() == 2 else 0.0)
        return b


class BoardPropsDialog(BaseDialog):
    def __init__(self, canvas, board: Board, parent=None):
        super().__init__(canvas, "Свойства платы", w=440)
        self.board = board
        self.w = _spin(2, 1, 500, 5, board.width)
        self.h = _spin(2, 1, 500, 5, board.height)
        self.ox = _spin(2, -500, 500, 1, board.origin[0])
        self.oy = _spin(2, -500, 500, 1, board.origin[1])
        self.name = QLineEdit(board.name)
        self.multi = QCheckBox("Многослойная (добавляются слои В1 и В2)")
        self.multi.setChecked(board.multilayer)
        note = QLabel("Допускаются только 2 или 4 медных слоя: М1+М2 либо М1+В1+В2+М2. "
                      "Произвольный набор выбрать нельзя.")
        note.setWordWrap(True)
        self.v.addLayout(_form(("Имя платы:", self.name),
                               ("Ширина поля, мм:", self.w),
                               ("Высота поля, мм:", self.h),
                               ("Начало координат X:", self.ox),
                               ("Начало координат Y:", self.oy)))
        self.v.addWidget(self.multi)
        self.v.addWidget(note)
        self.buttons("Сохранить")

    def apply(self):
        b = self.board
        b.name = self.name.text().strip() or b.name
        b.width = self.w.value()
        b.height = self.h.value()
        b.origin = (self.ox.value(), self.oy.value())
        b.multilayer = self.multi.isChecked()



class GerberImportDialog(BaseDialog):
    """Импорт Gerber RS-274X по слоям + сверловка Excellon."""

    def __init__(self, canvas, paths: Sequence[str], parent=None):
        super().__init__(canvas, "Импорт файлов Gerber", w=560)
        self.canvas = canvas
        self.paths = list(paths)
        self.list = QListWidget()
        for lk in ALL_LAYERS:
            it = QListWidgetItem(f"{lk} — {LAYER_BY_KEY[lk].name}")
            it.setData(Qt.ItemDataRole.UserRole, lk)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Unchecked)
            self.list.addItem(it)
        self.detected = {}
        self._detect()
        self.drill = QLineEdit()
        self.drill_b = QPushButton("Выбрать файл сверловки…")
        self.drill_b.clicked.connect(self._pick_drill)
        self.drill_unit = QComboBox()
        self.drill_unit.addItems(["Авто", "мм", "дюймы"])
        self.drill_int = QSpinBox(); self.drill_int.setRange(1, 6); self.drill_int.setValue(3)
        self.drill_dec = QSpinBox(); self.drill_dec.setRange(0, 6); self.drill_dec.setValue(3)
        self.drill_side = QComboBox()
        self.drill_side.addItems(["Сторона 1 (верх)", "Сторона 2 (низ)"])
        self.format_mode = QComboBox()
        self.format_mode.addItems(["Новая плата", "Текущая плата"])
        self.new_board = QGroupBox("Размеры новой платы")
        nf = QFormLayout(self.new_board)
        self.nb_w = _spin(2, 1, 500, 5, 100)
        self.nb_h = _spin(2, 1, 500, 5, 100)
        self.nb_margin = _spin(2, 0, 100, 1, 10)
        nf.addRow("Ширина, мм:", self.nb_w)
        nf.addRow("Высота, мм:", self.nb_h)
        nf.addRow("Отступ, мм:", self.nb_margin)
        self.optimize = QCheckBox("Оптимизировать проводники (склейка сегментов)")
        self.optimize.setChecked(True)
        self.autovias = QCheckBox("Автоматически создавать переходные отверстия")
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.v.addWidget(QLabel("Выберите, в какой слой импортировать каждый файл:"))
        self.v.addWidget(self.list, 1)
        self.v.addWidget(QLabel(f"Обнаружено файлов: {len(self.paths)}. "
                                f"Определено автоматически: {len(self.detected)}"))
        self.v.addLayout(_form(("Формат поля:", self.format_mode),
                               ("Данные отверстий (Excellon):", _row(self.drill, self.drill_b)),
                               ("Единицы сверловки:", self.drill_unit),
                               ("Целых/дробных:", _row(self.drill_int, self.drill_dec)),
                               ("Сторона сверловки:", self.drill_side)))
        self.v.addWidget(self.new_board)
        self.v.addWidget(self.optimize)
        self.v.addWidget(self.autovias)
        self.v.addWidget(self.status)
        bb = QDialogButtonBox()
        b1 = QPushButton("Импортировать")
        b1.setObjectName("Primary")
        b1.clicked.connect(self.run)
        b2 = QPushButton("Закрыть")
        b2.clicked.connect(self.reject)
        bb.addButton(b1, QDialogButtonBox.ButtonRole.ActionRole)
        bb.addButton(b2, QDialogButtonBox.ButtonRole.RejectRole)
        self.v.addWidget(bb)

    def _detect(self):
        guess = {"copper_top": "M1", "copper_bottom": "M2", "silkscreen_top": "K1",
                 "silkscreen_bottom": "K2", "outline": "O", "soldermask": None,
                 "paste": None, "copper_in": None, "drill": None}
        for p in self.paths:
            base = os.path.basename(p).lower()
            for key, lk in guess.items():
                if key in base and lk:
                    self.detected[p] = lk
                    for i in range(self.list.count()):
                        it = self.list.item(i)
                        if it.data(Qt.ItemDataRole.UserRole) == lk:
                            it.setCheckState(Qt.CheckState.Checked)
                    break

    def _pick_drill(self):
        path, _ = QFileDialog.getOpenFileName(self, "Файл сверловки Excellon", "",
                                              "Excellon (*.drl *.txt);;Все файлы (*)")
        if path:
            self.drill.setText(path)

    def run(self):
        mapping = {}
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                lk = it.data(Qt.ItemDataRole.UserRole)
                mapping[lk] = it
        
        els_by_layer = {}
        log = []
        lks = [it.data(Qt.ItemDataRole.UserRole) for it in mapping.values()]
        for idx, p in enumerate(self.paths):
            lk = self.detected.get(p) or (lks[idx] if idx < len(lks) else "M1")
            try:
                with open(p, "r", encoding="ascii", errors="ignore") as f:
                    text = f.read()
                els = import_gerber(text, lk)
                els_by_layer.setdefault(lk, []).extend(els)
                log.append(f"{os.path.basename(p)} → слой {lk}: {len(els)} элементов")
            except Exception as e:
                log.append(f"{os.path.basename(p)}: ошибка {e}")
        drill_pads = []
        if self.drill.text():
            try:
                with open(self.drill.text(), "r", encoding="ascii", errors="ignore") as f:
                    unit = {0: "", 1: "mm", 2: "inch"}[self.drill_unit.currentIndex()]
                    pads = import_excellon(f.read(), unit_hint=unit,
                                           side="top" if self.drill_side.currentIndex() == 0 else "bottom")
                drill_pads.extend(pads)
                log.append(f"Сверловка: {len(pads)} отверстий")
            except Exception as e:
                log.append(f"Сверловка: ошибка {e}")
        if not els_by_layer and not drill_pads:
            self.status.setText("Нечего импортировать: отметьте слои и выберите файлы.")
            return
        if self.format_mode.currentIndex() == 0:
            b = Board(name="Импорт", width=self.nb_w.value(), height=self.nb_h.value(),
                      origin=(self.nb_margin.value(), self.nb_margin.value()))
            self.canvas.doc.boards.append(b)
            self.canvas.doc.active = len(self.canvas.doc.boards) - 1
        else:
            b = self.canvas.board()
        self.canvas.push_undo()
        for lk, els in els_by_layer.items():
            for el in els:
                b.elements[el.id] = el
        for p in drill_pads:
            p.layers = [lk for lk in ("M1", "M2", "V1", "V2")]
            b.elements[p.id] = p
        self.canvas.touch()
        self.canvas.invalidate()
        self.canvas.zoom_all()
        self.status.setText("Импорт завершён:\n" + "\n".join(log) +
                            ("\n\nВнимание: полигоны и текст в Gerber импортируются "
                             "некорректно — их следует удалить и нарисовать заново."
                             if any(el.kind in ("poly", "text") for els in els_by_layer.values()
                                    for el in els) else ""))


class DrillImportDialog(BaseDialog):
    def __init__(self, canvas, path: str, parent=None):
        super().__init__(canvas, "Импорт сверловки Excellon", w=460)
        self.path = path
        self.unit = QComboBox()
        self.unit.addItems(["Авто", "мм", "дюймы"])
        self.side = QComboBox()
        self.side.addItems(["Сторона 1 (верх)", "Сторона 2 (низ, зеркально)"])
        self.int_d = QSpinBox(); self.int_d.setRange(1, 6); self.int_d.setValue(3)
        self.dec_d = QSpinBox(); self.dec_d.setRange(0, 6); self.dec_d.setValue(3)
        self.as_pads = QCheckBox("Создать переходные отверстия с металлизацией")
        self.as_pads.setChecked(True)
        self.v.addWidget(QLabel(f"Файл: {os.path.basename(path)}"))
        self.v.addLayout(_form(("Единицы:", self.unit),
                               ("Сторона:", self.side),
                               ("Целых/дробных:", _row(self.int_d, self.dec_d))))
        self.v.addWidget(self.as_pads)
        self.buttons("Импортировать")

    def accept(self):
        try:
            with open(self.path, "r", encoding="ascii", errors="ignore") as f:
                text = f.read()
            unit = {0: "", 1: "mm", 2: "inch"}[self.unit.currentIndex()]
            pads = import_excellon(text, unit_hint=unit,
                                   side="top" if self.side.currentIndex() == 0 else "bottom")
            if not pads:
                QMessageBox.warning(self, "Импорт", "Отверстия не распознаны. "
                                                  "Проверьте формат чисел (целых/дробных).")
                return
            b = self.canvas.board()
            self.canvas.push_undo()
            for p in pads:
                b.elements[p.id] = p
            self.canvas.touch()
            self.canvas.invalidate()
            self.canvas.statusMessage.emit(f"Импортировано отверстий: {len(pads)}")
            super().accept()
        except Exception as e:
            QMessageBox.warning(self, "Ошибка импорта", str(e))


class TemplateDialog(BaseDialog):
    """Фоновый рисунок (шаблон) с настройкой разрешения и смещения."""

    def __init__(self, canvas, img: QImage, path: str, parent=None):
        super().__init__(canvas, "Загрузка шаблона (фоновый рисунок)", w=520)
        self.img = img
        self.path = path
        self.dpi = QSpinBox()
        self.dpi.setRange(20, 2400)
        self.dpi.setValue(300)
        self.dx = _spin(2, -200, 200, 0.5, 0)
        self.dy = _spin(2, -200, 200, 0.5, 0)
        self.ch_opacity = QCheckBox("Полупрозрачно (скрывать прочие элементы — «Эксклюзив»)")
        self.ch_show = QCheckBox("Показывать шаблон")
        self.ch_show.setChecked(True)
        size_lbl = QLabel(f"Размер изображения: {img.width()} × {img.height()} px")
        self.dpi.valueChanged.connect(lambda _v: size_lbl.setText(
            f"Размер изображения: {img.width()} × {img.height()} px "
            f"({img.width() / self.dpi.value() * 25.4:.1f} × "
            f"{img.height() / self.dpi.value() * 25.4:.1f} мм)"))
        self.v.addWidget(QLabel(f"Файл: {os.path.basename(path)}"))
        self.v.addWidget(size_lbl)
        self.v.addLayout(_form(("Разрешение, dpi:", self.dpi),
                               ("Смещение X, мм:", self.dx),
                               ("Смещение Y, мм:", self.dy)))
        self.v.addWidget(self.ch_show)
        self.v.addWidget(self.ch_opacity)
        self.v.addWidget(QLabel("Рекомендуется 300–600 dpi и ч/б изображение для копий платы."))
        self.buttons("Загрузить")

    def accept(self):
        self.canvas.template = self.img if self.ch_show.isChecked() else None
        self.canvas.template_dpi = self.dpi.value()
        self.canvas.template_offset = (self.dx.value(), self.dy.value())
        self.canvas.invalidate(structural=False)
        super().accept()