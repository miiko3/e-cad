"""Блок «Актор» и окно «О программе»: логотип, автор, ссылки на поддержку."""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt, QSize, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from .helpwindow import APP, AUTHOR, LINKS, VERSION
from .theme import icon

# ссылки автора: соцсети и пожертвования
AUTHOR_LINKS = {
    "ВКонтакте": LINKS["ВКонтакте"],
    "ЮMoney (поддержка)": LINKS["ЮMoney"],
    "Boosty (поддержка)": LINKS["Boosty"],
}
REPO_LINKS = {
    "GitHub — репозитории": LINKS["GitHub"],
    "GitHub — e-cad (исходный код)": "https://github.com/miiko3/e-cad",
}

LINK_STYLE = "color:#7ab6ff;"
CARD_STYLE = "QFrame { background-color:#20252b; border:1px solid #39424d; border-radius:14px; }"
HEAD_STYLE = ("color:#7ab6ff; font-size: 13px; font-weight: 700; letter-spacing: 2px;")


def asset_path(*parts: str) -> str:
    """Путь к ресурсу: и в пакете, и рядом с main.py."""
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for base in (here, os.path.dirname(os.path.abspath(sys.argv[0]) if sys.argv else "")):
        if not base:
            continue
        p = os.path.join(base, *parts)
        if os.path.exists(p):
            return p
    return os.path.join(here, *parts)


def open_link(url: str):
    QDesktopServices.openUrl(QUrl(url))


class LinkLabel(QLabel):
    """Кликабельная ссылка с подсказкой."""

    def __init__(self, text: str, url: str, parent=None):
        super().__init__(text, parent)
        self.url = url
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.setStyleSheet(LINK_STYLE + "font-size: 12px; padding: 4px 0;")

    def mousePressEvent(self, ev):
        open_link(self.url)
        super().mousePressEvent(ev)


class LinksCard(QFrame):
    """Карточка со ссылками: заголовок + строки «название — адрес — Открыть»."""

    def __init__(self, title: str, links: dict, note: str = "", parent=None):
        super().__init__(parent)
        self.setStyleSheet(CARD_STYLE)
        self.title_text = title
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(6)
        head = QLabel(title)
        head.setStyleSheet(HEAD_STYLE)
        v.addWidget(head)
        for name, url in links.items():
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)
            lbl = LinkLabel(f"{name}: {url}", url)
            h.addWidget(lbl, 1)
            btn = QPushButton("Открыть")
            btn.setObjectName("Flat")
            btn.setIcon(icon("info", "#7ab6ff", 18))
            btn.setFixedWidth(96)
            btn.clicked.connect(lambda _c=False, u=url: open_link(u))
            h.addWidget(btn, 0, Qt.AlignmentFlag.AlignTop)
            v.addWidget(row)
        if note:
            n = QLabel(note)
            n.setStyleSheet("color:#8c9199; font-size: 11px;")
            n.setWordWrap(True)
            v.addWidget(n)


class ActorBlock(QFrame):
    """Блок «Актор»: автор проекта, соцсети, пожертвования и репозитории."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent; border: none;")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        head = QLabel("АКТОР")
        head.setStyleSheet(HEAD_STYLE + " font-size: 16px;")
        v.addWidget(head)
        name = QLabel(f"Автор и разработчик: {AUTHOR}")
        name.setStyleSheet("font-size: 13px; font-weight: 600;")
        v.addWidget(name)
        desc = QLabel("Проект e-cad — САПР топологии печатных плат и микроэлектроники "
                      "в стиле Material Design 3. Поддержать развитие можно по ссылкам ниже.")
        desc.setWordWrap(True)
        desc.setStyleSheet("color:#c2c7cf; font-size: 12px;")
        v.addWidget(desc)
        v.addWidget(LinksCard("АВТОР · СОЦСЕТИ И ПОДДЕРЖКА", AUTHOR_LINKS,
                              "Ссылки открываются в браузере по умолчанию."))
        v.addWidget(LinksCard("РЕПОЗИТОРИИ", REPO_LINKS,
                              "Исходный код e-cad и другие проекты автора."))


class AboutDialog(QDialog):
    """О программе: логотип, сведения и две кнопки — «Автор» и «Репозитории»."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"О программе — {APP}")
        self.setMinimumWidth(640)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(12)

        top = QHBoxLayout()
        logo = QLabel()
        p = asset_path("assets", "logo.png")
        if os.path.exists(p):
            logo.setPixmap(QPixmap(p).scaled(84, 84, Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation))
        top.addWidget(logo)
        tt = QVBoxLayout()
        t1 = QLabel(APP)
        t1.setStyleSheet("font-size: 26px; font-weight: 700; color:#7ab6ff;")
        t2 = QLabel(f"САПР топологии печатных плат · версия {VERSION}")
        t2.setStyleSheet("color:#c2c7cf; font-size: 12px;")
        t3 = QLabel("Material Design 3 · PySide6 · numpy")
        t3.setStyleSheet("color:#8c9199; font-size: 11px;")
        tt.addWidget(t1)
        tt.addWidget(t2)
        tt.addWidget(t3)
        tt.addStretch(1)
        top.addLayout(tt, 1)
        v.addLayout(top)

        info = QFrame()
        info.setStyleSheet(CARD_STYLE)
        iv = QVBoxLayout(info)
        iv.setContentsMargins(16, 12, 16, 12)
        for line in [
            "Принцип работы: схема рисуется как рисунок («Just Draw It») — без netlist и 3D.",
            "Слои: М1, К1, В1, В2, М2, К2, О — до 4 медных слоёв, две стороны маркировки.",
            "Экспорт: Gerber RS-274X, Excellon, HPGL, Pick+Place, BOM, PNG/JPG/GIF/BMP/PDF.",
            "Формат проекта: *.ecad (мультиплатный), автосохранение *.bak.",
        ]:
            lb = QLabel("• " + line)
            lb.setWordWrap(True)
            lb.setStyleSheet("color:#d9dee5; font-size: 12px;")
            iv.addWidget(lb)
        v.addWidget(info)

        # прокручиваемая область с блоком «Актор»
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(ActorBlock())
        self.scroll = scroll
        v.addWidget(scroll, 1)

        # две кнопки, как просил автор: Автор / Репозитории
        row = QHBoxLayout()
        b_author = QPushButton("Автор · ссылки")
        b_author.setObjectName("Primary")
        b_author.setIcon(icon("info", "#00325a", 18))
        b_author.clicked.connect(lambda: self._focus_links(0))
        b_repo = QPushButton("Репозитории (GitHub)")
        b_repo.setObjectName("Tonal")
        b_repo.setIcon(icon("lib", "#7ab6ff", 18))
        b_repo.clicked.connect(lambda: self._focus_links(1))
        b_help = QPushButton("Инструкция по использованию")
        b_help.setObjectName("Outline")
        b_help.clicked.connect(self._help)
        b_close = QPushButton("Закрыть")
        b_close.setObjectName("Outline")
        b_close.clicked.connect(self.accept)
        for b in (b_author, b_repo, b_help):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(b_close)
        v.addLayout(row)

        self._cards = []

    def _focus_links(self, index: int):
        """Прокрутить окно к нужному блоку ссылок (Автор / Репозитории)."""
        cards = self.findChildren(LinksCard)
        if 0 <= index < len(cards):
            self.scroll.ensureWidgetVisible(cards[index], 0, 40)
            cards[index].setToolTip("Блок " + cards[index].title_text)

    def _help(self):
        from .helpwindow import HelpWindow
        HelpWindow(self).exec()