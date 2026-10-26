"""Janela principal do instalador."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QProgressBar, QProgressDialog, QPushButton,
    QScrollArea, QSizePolicy, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget,
)

from .. import __version__, app_config, catalog, installer, selfupdate, shortcut, state
from ..catalog import Catalog, Game, Option, Version
from ..download import Downloader, DownloadCancelled, DownloadError, file_sha256
from ..project_gallery import get_project
from . import style
from .dialogs import FindGameDialog, SettingsDialog
from .tasks import run_task

ROLE_GAME = Qt.UserRole + 1
ROLE_BADGE = Qt.UserRole + 2


# --------------------------------------------------------------------------- #
# Lógica de estado (pura, testável)
# --------------------------------------------------------------------------- #
def compute_action(
    version: Optional[Version],
    rec: Optional[dict],
    zip_cached: bool = False,
    opts: Optional[list[Option]] = None,
    chosen: Optional[dict] = None,
) -> tuple[str, str]:
    """Devolve (tipo, texto do botão).
    Tipos: none | install | installed | update | switch | options."""
    if version is None or not version.available:
        return "none", "INDISPONÍVEL"
    opts = opts or []
    chosen = catalog.normalize_options(opts, chosen)
    sig = catalog.signature(version, opts, chosen)

    if rec is not None and rec.get("version_id") == version.id:
        rec_sig = rec.get("signature")
        if rec_sig is None:  # registro antigo, sem opções
            rec_sig = sig if rec.get("version") == version.version else version.version
        if rec_sig == sig:
            return "installed", "✓  INSTALADA"
        same_choices = catalog.normalize_options(opts, rec.get("options")) == chosen
        if rec.get("version") != version.version or same_choices:
            kind, text = "update", f"ATUALIZAR  →  {version.version}"
        else:
            kind, text = "options", "APLICAR OPÇÕES"
    elif rec is not None:
        kind, text = "switch", f"TROCAR PARA {version.label}"
    else:
        kind, text = "install", ("INSTALAR" if zip_cached else "BAIXAR E INSTALAR")

    if any(not c.available for _, c in catalog.selected_choices(opts, chosen)):
        return "none", "OPÇÃO AINDA INDISPONÍVEL"
    return kind, text


def _safe(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in text)


def zip_name(game: Game, v: Version) -> str:
    return _safe(f"{game.id}_{v.id}_{v.version}") + ".zip"


def addon_zip_name(game: Game, v: Version, o: Option, c) -> str:
    return _safe(f"{game.id}_{v.id}_{o.id}_{c.id}_{c.version}") + ".zip"


def pending_updates(cat: Catalog) -> list[tuple[Game, Version]]:
    out = []
    for g in cat.games:
        rec = state.get_install(g.id)
        if not rec:
            continue
        v = g.version_by_id(rec.get("version_id", ""))
        if v and compute_action(v, rec, opts=g.options_for(v), chosen=rec.get("options"))[0] == "update":
            out.append((g, v))
    return out


# --------------------------------------------------------------------------- #
# Widgets
# --------------------------------------------------------------------------- #
class GameDelegate(QStyledItemDelegate):
    H = 52

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.H)

    def paint(self, p: QPainter, option, index):
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = option.rect
        selected = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)
        if selected or hover:
            p.fillRect(r, QColor(style.CARD_HOVER if selected else style.CARD))
        icon = index.data(Qt.DecorationRole)
        if isinstance(icon, QIcon):
            icon.paint(p, QRect(r.left() + 14, r.top() + (r.height() - 32) // 2, 32, 32))
        badge = index.data(ROLE_BADGE) or ""
        right_pad = 44 if badge else 12
        text_rect = QRect(r.left() + 58, r.top(), r.width() - 58 - right_pad, r.height())
        p.setPen(QColor("#ffffff" if (selected or hover) else style.MUTED))
        f = QFont(option.font)
        f.setPointSizeF(9.5)
        p.setFont(f)
        p.drawText(text_rect, Qt.AlignVCenter | Qt.TextWordWrap, index.data(Qt.DisplayRole))
        if badge:
            color = {"update": style.ORANGE, "installed": style.GREEN}.get(badge, style.CARD_HOVER)
            sym = {"update": "⬆", "installed": "✓"}.get(badge, "")
            br = QRectF(r.right() - 34, r.top() + (r.height() - 22) / 2, 24, 22)
            path = QPainterPath()
            path.addRoundedRect(br, 6, 6)
            p.fillPath(path, QColor(color))
            p.setPen(QColor("white"))
            p.drawText(br, Qt.AlignCenter, sym)
        p.restore()


class BannerWidget(QWidget):
    """Banner do jogo (corta para preencher, como o UniformToFill do WPF) com painéis por cima."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(280)
        self._pm: Optional[QPixmap] = None
        self._offset = (0, 0)
        self.tag = QLabel("", self)
        self.tag.setAlignment(Qt.AlignCenter)
        self.actions = QWidget(self)
        self.download = QFrame(self)
        self.progress = QFrame(self)

    def set_banner(self, pm: Optional[QPixmap], offset=(0, 0)) -> None:
        self._pm, self._offset = pm, offset
        self.update()

    def resizeEvent(self, e):
        self.tag.adjustSize()
        self.tag.move(self.width() - self.tag.width() - 20, 20)
        self.actions.adjustSize()
        self.actions.move(30, self.height() - self.actions.height() - 20)
        self.download.adjustSize()
        self.download.move(30, self.height() - self.download.height() - 20)
        self.progress.layout().activate()
        self.progress.setFixedHeight(self.progress.layout().sizeHint().height())  # altura real (as 2 barras)
        self.progress.move(self.width() - self.progress.width() - 20, self.height() - self.progress.height() - 20)

    def relayout(self) -> None:
        self.resizeEvent(None)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#0b121a"))
        if self._pm is None:
            p.setPen(QColor(255, 255, 255, 80))
            f = QFont(self.font())
            f.setPointSize(20)
            f.setBold(True)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter, "STARLIGHT TRANSLATE")
        else:
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            s = self._pm.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            ex, ey = s.width() - self.width(), s.height() - self.height()
            x = max(-ex, min(0, -ex / 2 + self._offset[0]))
            y = max(-ey, min(0, -ey / 2 + self._offset[1]))
            p.setOpacity(0.8)
            p.drawPixmap(int(x), int(y), s)
            p.setOpacity(1.0)
        g = QLinearGradient(0, self.height() * 0.45, 0, self.height())
        g.setColorAt(0, QColor(11, 18, 26, 0))
        g.setColorAt(1, QColor(11, 18, 26, 210))
        p.fillRect(self.rect(), g)


class VersionDrawer(QFrame):
    """A 'gavetinha' de versões (V1 / V2 / V3). Só aparece para jogos com mais de uma versão."""

    selected = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("drawer")
        self.setStyleSheet(
            f"QFrame#drawer {{ background: {style.PANEL}; border: 1px solid #252a34; border-radius: 6px; }}"
            "QFrame#drawer QLabel { border: none; background: transparent; }"
            "QFrame#drawer QWidget#drawerBody { background: transparent; border: none; }"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(8)
        self.head = QPushButton()
        self.head.setCursor(Qt.PointingHandCursor)
        self.head.setFocusPolicy(Qt.NoFocus)
        self.head.setStyleSheet("QPushButton { text-align: left; background: transparent; font-size: 13px; font-weight: 700; padding: 2px 0; }"
                                "QPushButton:hover { background: transparent; color: #00bbf9; }")
        self.head.clicked.connect(self._toggle)
        lay.addWidget(self.head)
        self.body = QWidget()
        self.body.setObjectName("drawerBody")
        bl = QVBoxLayout(self.body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(8)
        self.row = QHBoxLayout()
        self.row.setSpacing(10)
        bl.addLayout(self.row)
        self.notes = QLabel()
        self.notes.setWordWrap(True)
        self.notes.setStyleSheet(f"color: {style.SOFT}; font-size: 12px;")
        bl.addWidget(self.notes)
        lay.addWidget(self.body)
        self._open = True
        self._cards: dict[str, QPushButton] = {}
        self._versions: list[Version] = []
        self._current = ""

    def set_game(self, game: Game, rec: Optional[dict], current: str) -> None:
        self._versions = game.versions
        self._current = current
        while self.row.count():
            w = self.row.takeAt(0).widget()
            if w:
                w.hide()           # some na hora (senão fica uma "borda fantasma" até o deleteLater rodar)
                w.setParent(None)
                w.deleteLater()
        self._cards.clear()
        for v in game.versions:
            tag = ""
            if not v.available:
                tag = "em breve"
            elif rec and rec.get("version_id") == v.id:
                tag = "✓ instalada" if rec.get("version") == v.version else "⬆ atualização"
            b = QPushButton(f"{v.label}\n{tag or 'v' + v.version}")
            b.setCheckable(True)
            b.setMinimumSize(120, 58)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, vid=v.id: self.selected.emit(vid))
            self.row.addWidget(b)
            self._cards[v.id] = b
        self.row.addStretch(1)
        self.mark(current, rec)

    def mark(self, current: str, rec: Optional[dict] = None) -> None:
        self._current = current
        for vid, b in self._cards.items():
            on = vid == current
            b.setChecked(on)
            installed = bool(rec and rec.get("version_id") == vid)
            border = style.GREEN if installed else (style.CYAN if on else "transparent")
            b.setStyleSheet(
                f"QPushButton {{ background: {style.CARD_HOVER if on else style.CARD}; border: 2px solid {border}; border-radius: 6px; font-size: 12px; }}"
                f"QPushButton:hover {{ background: {style.CARD_HOVER}; }}"
            )
        v = next((x for x in self._versions if x.id == current), None)
        self.notes.setText(v.notes if v and v.notes else "")
        self.notes.setVisible(bool(v and v.notes))
        self._refresh_head(v)

    def _refresh_head(self, v: Optional[Version]) -> None:
        arrow = "▾" if self._open else "▸"
        self.head.setText(f"Versão da tradução:  {v.label if v else '-'}   {arrow}")

    def _toggle(self) -> None:
        self._open = not self._open
        self.body.setVisible(self._open)
        self._refresh_head(next((x for x in self._versions if x.id == self._current), None))


class OptionsPanel(QFrame):
    """Opções da tradução: menu suspenso (ex.: Codinomes) e caixas de marcar (ex.: música)."""

    changed = Signal(dict)

    def __init__(self):
        super().__init__()
        self.setObjectName("optpanel")
        self.setStyleSheet(
            f"QFrame#optpanel {{ background: {style.PANEL}; border: 1px solid #252a34; border-radius: 6px; }}"
            "QFrame#optpanel QLabel { border: none; background: transparent; }"
        )
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(16, 12, 16, 14)
        self._lay.setSpacing(8)
        self._widgets: dict[str, QWidget] = {}
        self._opts: list[Option] = []

    def set_options(self, opts: list[Option], chosen: dict) -> None:
        self._opts = opts
        self._widgets.clear()
        while self._lay.count():
            it = self._lay.takeAt(0)
            w = it.widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
            elif it.layout():
                self._drop_layout(it.layout())
        head = QLabel("OPÇÕES DA TRADUÇÃO")
        head.setStyleSheet("color: #8c95a5; font-size: 12px; font-weight: 700;")
        self._lay.addWidget(head)
        for o in opts:
            if o.type == "checkbox":
                cb = QCheckBox(o.label)
                cb.setChecked(chosen.get(o.id) == "on")
                cb.setCursor(Qt.PointingHandCursor)
                cb.toggled.connect(self._emit)
                self._lay.addWidget(cb)
                self._widgets[o.id] = cb
            else:
                row = QHBoxLayout()
                lbl = QLabel(o.label + ":")
                lbl.setStyleSheet("font-weight: 600;")
                combo = QComboBox()
                combo.setMinimumWidth(240)
                combo.setCursor(Qt.PointingHandCursor)
                for c in o.choices:
                    combo.addItem(c.label if c.available else f"{c.label}  (em breve)", c.id)
                combo.setCurrentIndex(max(0, combo.findData(chosen.get(o.id, o.default))))
                combo.currentIndexChanged.connect(self._emit)
                row.addWidget(lbl)
                row.addWidget(combo)
                row.addStretch(1)
                self._lay.addLayout(row)
                self._widgets[o.id] = combo
            if o.note:
                n = QLabel(o.note)
                n.setWordWrap(True)
                n.setStyleSheet(f"color: {style.MUTED}; font-size: 11px; margin-left: 24px;")
                self._lay.addWidget(n)

    @staticmethod
    def _drop_layout(lay) -> None:
        while lay.count():
            w = lay.takeAt(0).widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()

    def chosen(self) -> dict:
        out = {}
        for o in self._opts:
            w = self._widgets.get(o.id)
            if isinstance(w, QCheckBox):
                out[o.id] = "on" if w.isChecked() else "off"
            elif isinstance(w, QComboBox):
                out[o.id] = str(w.currentData())
        return out

    def _emit(self, *_a) -> None:
        self.changed.emit(self.chosen())


# --------------------------------------------------------------------------- #
# Janela principal
# --------------------------------------------------------------------------- #
class MainWindow(QWidget):
    def __init__(self, cat: Catalog):
        super().__init__()
        self.setWindowTitle(f"Starlight Launcher  •  v{__version__}")
        self.setMinimumSize(1050, 740)
        self.resize(1100, 760)
        self.catalog = cat
        self._busy = False
        self._outdated_installer = False
        self._downloader: Optional[Downloader] = None
        self._queue: list[tuple[Game, Version, str]] = []
        self._update_info: Optional[selfupdate.UpdateInfo] = None
        self._prompted_updates = False
        self._current_game: Optional[Game] = None
        self._current_version_id = ""
        self._chosen: dict[str, dict] = {}  # escolhas do usuário nesta sessão, por jogo/versão

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # aviso no topo (atualização do instalador / catálogo exige instalador novo)
        self.notice = QFrame()
        self.notice.setObjectName("notice")
        self.notice.setStyleSheet(f"QFrame#notice {{ background: {style.ORANGE}; }}")
        nl = QHBoxLayout(self.notice)
        nl.setContentsMargins(16, 6, 10, 6)
        self.notice_text = QLabel()
        self.notice_text.setStyleSheet("font-weight: 700; color: white;")
        self.notice_btn = QPushButton("ATUALIZAR AGORA")
        self.notice_btn.setStyleSheet("QPushButton { background: rgba(0,0,0,0.25); color: white; padding: 6px 12px; } QPushButton:hover { background: rgba(0,0,0,0.4); }")
        self.notice_btn.clicked.connect(self._update_installer)
        nl.addWidget(self.notice_text, 1)
        nl.addWidget(self.notice_btn)
        self.notice.hide()
        outer.addWidget(self.notice)

        body = QHBoxLayout()
        body.setSpacing(0)
        outer.addLayout(body, 1)

        # barra lateral
        side = QFrame()
        side.setFixedWidth(280)
        side.setObjectName("side")
        side.setStyleSheet(f"QFrame#side {{ background: {style.SIDEBAR}; }}")
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)
        self.list = QListWidget()
        self.list.setItemDelegate(GameDelegate(self.list))
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setMouseTracking(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.currentRowChanged.connect(self._on_row)
        sl.addWidget(self.list, 1)
        foot = QHBoxLayout()
        foot.setContentsMargins(12, 8, 12, 10)
        self.btn_all = QPushButton("⬆  Atualizar tudo")
        style.style_button(self.btn_all, "orange")
        self.btn_all.clicked.connect(self._update_all)
        self.btn_all.hide()
        self.btn_cfg = QPushButton("⚙")
        self.btn_cfg.setFixedSize(36, 36)
        self.btn_cfg.setToolTip("Configurações")
        self.btn_cfg.clicked.connect(self._open_settings)
        foot.addWidget(self.btn_all, 1)
        foot.addStretch(0)
        foot.addWidget(self.btn_cfg)
        sl.addLayout(foot)
        body.addWidget(side)

        # área principal
        right = QWidget()
        right.setObjectName("rightPane")
        right.setStyleSheet("QWidget#rightPane { background: #1b2838; }")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        self.banner = BannerWidget()
        rl.addWidget(self.banner)
        self._build_banner_panels()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("innerPane")
        inner.setStyleSheet("QWidget#innerPane { background: #1b2838; }")
        il = QVBoxLayout(inner)
        il.setContentsMargins(40, 25, 40, 30)
        il.setSpacing(14)
        self.lbl_title = QLabel()
        self.lbl_title.setWordWrap(True)
        self.lbl_title.setStyleSheet("font-size: 24px; font-weight: 700;")
        il.addWidget(self.lbl_title)
        self.drawer = VersionDrawer()
        self.drawer.selected.connect(self._on_pick_version)
        il.addWidget(self.drawer)
        self.opts_panel = OptionsPanel()
        self.opts_panel.changed.connect(self._on_options_changed)
        il.addWidget(self.opts_panel)
        self.lbl_desc = QLabel()
        self.lbl_desc.setWordWrap(True)
        self.lbl_desc.setStyleSheet(f"color: {style.SOFT}; font-size: 13px;")
        il.addWidget(self.lbl_desc)

        # Galeria de capturas de tela traduzidas, carregadas do site.
        self.gallery_frame = QFrame()
        self.gallery_frame.setObjectName("projectGallery")
        self.gallery_frame.setStyleSheet(
            f"QFrame#projectGallery {{ background: {style.PANEL}; "
            "border: 1px solid #252a34; border-radius: 6px; }"
        )
        gallery_layout = QVBoxLayout(self.gallery_frame)
        gallery_layout.setContentsMargins(14, 12, 14, 12)
        gallery_layout.setSpacing(8)

        self.gallery_title = QLabel("IMAGENS DA TRADUÇÃO")
        self.gallery_title.setStyleSheet(
            "color: #8c95a5; font-size: 12px; font-weight: 700;"
        )
        gallery_layout.addWidget(self.gallery_title)

        # A galeria usa uma grade real, com imagens grandes já visíveis.
        # A rolagem fica na área principal da página, não dentro da galeria.
        self.gallery_content = QWidget()
        self.gallery_grid = QGridLayout(self.gallery_content)
        self.gallery_grid.setContentsMargins(2, 2, 2, 2)
        self.gallery_grid.setHorizontalSpacing(14)
        self.gallery_grid.setVerticalSpacing(14)
        self.gallery_grid.setColumnStretch(0, 1)
        self.gallery_grid.setColumnStretch(1, 1)
        gallery_layout.addWidget(self.gallery_content)

        self.gallery_status = QLabel("Selecione um projeto para ver as imagens.")
        self.gallery_status.setStyleSheet(
            f"color: {style.MUTED}; font-size: 11px; border: none;"
        )
        gallery_layout.addWidget(self.gallery_status)
        self.gallery_frame.hide()
        self._gallery_game_id = ""
        self._gallery_buttons = []
        self.lbl_logo = QLabel()
        self.lbl_logo.setAlignment(Qt.AlignLeft)
        il.addWidget(self.lbl_logo)
        self.credits = self._build_credits()
        il.addWidget(self.credits)
        # Último bloco informativo da página: sempre abaixo dos créditos.
        il.addSpacing(8)
        il.addWidget(self.gallery_frame)
        il.addStretch(1)
        scroll.setWidget(inner)
        rl.addWidget(scroll, 1)
        body.addWidget(right, 1)

        self.set_catalog(cat)

    # -- construção --------------------------------------------------------- #
    def _build_banner_panels(self) -> None:
        b = self.banner
        b.tag.setStyleSheet("background: #e74c3c; color: white; font-size: 12px; font-weight: 700; border-radius: 12px; padding: 5px 12px;")

        al = QHBoxLayout(b.actions)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(8)
        self.btn_main = QPushButton("INSTALAR")
        self.btn_main.setFixedSize(230, 45)
        self.btn_main.clicked.connect(self._on_main_click)
        self.btn_remove = QPushButton("DESINSTALAR")
        self.btn_remove.setFixedHeight(45)
        style.style_button(self.btn_remove, "danger")
        self.btn_remove.clicked.connect(self._on_uninstall)
        self.btn_redo = QPushButton("↻")
        self.btn_redo.setFixedSize(45, 45)
        self.btn_redo.setToolTip("Reinstalar (repara a tradução)")
        self.btn_redo.clicked.connect(self._on_reinstall)
        for w in (self.btn_main, self.btn_remove, self.btn_redo):
            al.addWidget(w)

        b.download.setObjectName("dlpanel")
        b.download.setStyleSheet("QFrame#dlpanel { background: rgba(11,18,26,0.85); border-radius: 6px; }")
        dl = QVBoxLayout(b.download)
        dl.setContentsMargins(12, 12, 12, 12)
        row = QHBoxLayout()
        self.bar = QProgressBar()
        self.bar.setFixedWidth(220)
        self.bar.setTextVisible(False)
        self.btn_pause = QPushButton("⏸")
        self.btn_pause.setFixedSize(28, 28)
        self.btn_pause.setStyleSheet("padding: 0;")
        self.btn_pause.clicked.connect(self._on_pause)
        self.btn_cancel = QPushButton("✕")
        self.btn_cancel.setFixedSize(28, 28)
        self.btn_cancel.setStyleSheet(f"padding: 0; background: {style.RED};")
        self.btn_cancel.clicked.connect(self._on_cancel)
        row.addWidget(self.bar)
        row.addWidget(self.btn_pause)
        row.addWidget(self.btn_cancel)
        dl.addLayout(row)
        self.lbl_dl = QLabel("")
        self.lbl_dl.setStyleSheet("font-size: 11px; font-weight: 600;")
        self.lbl_dl.setMinimumWidth(280)
        dl.addWidget(self.lbl_dl)
        b.download.hide()

        b.progress.setObjectName("prpanel")
        b.progress.setStyleSheet("QFrame#prpanel { background: rgba(11,18,26,0.85); border-radius: 6px; }")
        b.progress.setFixedWidth(170)
        pl = QVBoxLayout(b.progress)
        pl.setContentsMargins(12, 12, 12, 12)
        self.pct_tr, self.pct_rev = QLabel("0%"), QLabel("0%")
        self.bar_tr, self.bar_rev = QFrame(), QFrame()
        for title, pct, bar in (("Traduzido", self.pct_tr, self.bar_tr), ("Revisão", self.pct_rev, self.bar_rev)):
            head = QHBoxLayout()
            t = QLabel(title)
            t.setStyleSheet(f"color: {style.MUTED}; font-size: 11px;")
            pct.setStyleSheet(f"color: {style.CYAN}; font-size: 11px; font-weight: 700;")
            head.addWidget(t)
            head.addStretch(1)
            head.addWidget(pct)
            pl.addLayout(head)
            track = QFrame()
            track.setFixedHeight(5)
            track.setStyleSheet("QFrame { background: #1c212b; border-radius: 2px; }")
            bar.setParent(track)
            bar.setFixedHeight(5)
            bar.setStyleSheet("QFrame { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #8c52ff, stop:1 #00bbf9); border-radius: 2px; }")
            pl.addWidget(track)
            pl.addSpacing(6)

    def _build_credits(self) -> QFrame:
        f = QFrame()
        f.setStyleSheet(f"QFrame#cr {{ background: {style.PANEL}; border: 1px solid #252a34; border-radius: 6px; }}")
        f.setObjectName("cr")
        lay = QVBoxLayout(f)
        lay.setContentsMargins(16, 16, 16, 16)
        h = QLabel("CRÉDITOS DA TRADUÇÃO")
        h.setStyleSheet("color: #8c95a5; font-size: 12px; font-weight: 700;")
        lay.addWidget(h)
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        self._cr_labels = {}
        cols = [("tr", "🌎 TRADUÇÃO & REVISÃO", 0, "#ffffff"), ("de", "🎨 DESIGN GRÁFICO", 1, "#ffffff"),
                ("to", "🛠 FERRAMENTAS", 1, "#ffffff"), ("th", "⭐ AGRADECIMENTOS ESPECIAIS", 2, style.CYAN)]
        self._cr_boxes = {}
        col_layouts = [QVBoxLayout(), QVBoxLayout(), QVBoxLayout()]
        for cl in col_layouts:
            cl.setSpacing(2)
        for key, title, col, color in cols:
            t = QLabel(title)
            t.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 700; margin-top: 6px;")
            body = QLabel()
            body.setWordWrap(True)
            body.setStyleSheet(f"color: {style.SOFT}; font-size: 12px;")
            col_layouts[col].addWidget(t)
            col_layouts[col].addWidget(body)
            self._cr_labels[key] = (t, body)
        for i, cl in enumerate(col_layouts):
            cl.addStretch(1)
            grid.addLayout(cl, 0, i)
        grid.setColumnStretch(0, 14)
        grid.setColumnStretch(1, 10)
        grid.setColumnStretch(2, 13)
        lay.addLayout(grid)
        return f

    # -- catálogo ------------------------------------------------------------ #
    def set_catalog(self, cat: Catalog) -> None:
        keep = self._current_game.id if self._current_game else None
        self.catalog = cat
        self._outdated_installer = bool(cat.min_installer and selfupdate.is_newer(cat.min_installer))
        if self._outdated_installer:
            self._show_notice("Este instalador é antigo demais para as traduções mais novas. Atualize para continuar instalando.", bool(self._update_info))
        self.list.blockSignals(True)
        self.list.clear()
        for g in cat.games:
            item = QListWidgetItem(g.name)
            item.setData(ROLE_GAME, g.id)
            item.setIcon(QIcon(style.rounded_icon(style.load_pixmap(catalog.local_image(g.icon)), 32)))
            self.list.addItem(item)
        self.list.blockSignals(False)
        self._refresh_badges()
        row = next((i for i, g in enumerate(cat.games) if g.id == keep), 0)
        if cat.games:
            self.list.setCurrentRow(row)
            self._on_row(row)
        self._fetch_remote_images()

    def _fetch_remote_images(self) -> None:
        remote = {r for g in self.catalog.games for r in (g.icon, g.banner, g.logo) if r.startswith("http") and catalog.local_image(r) is None}
        if not remote:
            return

        def work(_emit):
            for r in remote:
                catalog.fetch_image(r)
            return True

        run_task(work, on_done=lambda _: self._reload_icons())

    def _reload_icons(self) -> None:
        for i, g in enumerate(self.catalog.games):
            self.list.item(i).setIcon(QIcon(style.rounded_icon(style.load_pixmap(catalog.local_image(g.icon)), 32)))
        if self._current_game:
            self._show_game(self._current_game)

    def _refresh_badges(self) -> None:
        n_upd = 0
        for i, g in enumerate(self.catalog.games):
            rec = state.get_install(g.id)
            badge = ""
            if rec:
                v = g.version_by_id(rec.get("version_id", ""))
                if v and compute_action(v, rec, opts=g.options_for(v), chosen=rec.get("options"))[0] == "update":
                    badge, n_upd = "update", n_upd + 1
                else:
                    badge = "installed"
            self.list.item(i).setData(ROLE_BADGE, badge)
        self.btn_all.setVisible(n_upd > 0)
        self.btn_all.setText(f"⬆  Atualizar tudo ({n_upd})")
        self.list.viewport().update()

    # -- seleção ------------------------------------------------------------- #
    def _on_row(self, row: int) -> None:
        if 0 <= row < len(self.catalog.games):
            g = self.catalog.games[row]
            rec = state.get_install(g.id)
            vid = (rec or {}).get("version_id") or (g.default().id if g.default() else "")
            self._current_version_id = vid
            self._show_game(g)

    def _on_pick_version(self, vid: str) -> None:
        if self._busy:
            return
        self._current_version_id = vid
        if self._current_game:
            self._show_game(self._current_game)

    def _selected_version(self) -> Optional[Version]:
        g = self._current_game
        return g.version_by_id(self._current_version_id) if g else None

    def _clear_gallery(self) -> None:
        """Remove as miniaturas da seleção anterior."""
        while self.gallery_grid.count():
            item = self.gallery_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self._gallery_buttons.clear()

    def _load_project_gallery(self, game: Game) -> None:
        """Busca as imagens do projeto sem bloquear a interface."""
        slug = getattr(game, "website_slug", "")
        self._gallery_game_id = game.id
        self._clear_gallery()

        if not slug:
            self.gallery_frame.hide()
            return

        self.gallery_frame.show()
        self.gallery_status.setText("Carregando imagens traduzidas...")

        def work(_emit):
            project = get_project(slug)
            if not project:
                return game.id, []

            from urllib.request import Request, urlopen

            downloaded = []
            for url in project.get("images", []):
                try:
                    request = Request(
                        url,
                        headers={"User-Agent": "Starlight-Translate-Instalador/2.0"},
                    )
                    with urlopen(request, timeout=10) as response:
                        data = response.read()
                    if data:
                        downloaded.append((url, data))
                except (OSError, TimeoutError, ValueError):
                    continue
            return game.id, downloaded

        def done(result):
            game_id, images = result
            # A resposta pode chegar depois que outro jogo já foi selecionado.
            if game_id != self._gallery_game_id:
                return

            if not images:
                self.gallery_status.setText(
                    "Nenhuma imagem disponível para este projeto."
                )
                return

            shown = 0
            for index, (url, data) in enumerate(images, start=1):
                pixmap = QPixmap()
                if not pixmap.loadFromData(data):
                    continue

                button = QPushButton()
                button.setMinimumSize(360, 203)
                button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                button.setMaximumHeight(225)
                button.setCursor(Qt.PointingHandCursor)
                button.setFocusPolicy(Qt.NoFocus)
                button.setIcon(QIcon(pixmap))
                button.setIconSize(QSize(344, 193))
                button.setToolTip(f"Imagem {index} — clique para ampliar")
                button.setStyleSheet(
                    "QPushButton { background: #202936; border: 1px solid #343d4b; "
                    "border-radius: 5px; padding: 4px; } "
                    f"QPushButton:hover {{ border: 1px solid {style.CYAN}; }}"
                )
                button.clicked.connect(
                    lambda checked=False, image=pixmap: self._show_gallery_image(image)
                )
                # Duas colunas: as capturas ficam grandes e visíveis sem clique.
                grid_index = len(self._gallery_buttons)
                self.gallery_grid.addWidget(button, grid_index // 2, grid_index % 2)
                self._gallery_buttons.append(button)
                shown += 1

            if shown:
                self.gallery_status.setText(
                    f"{shown} imagem(ns) traduzida(s) · clique em uma para ampliar"
                )
            else:
                self.gallery_status.setText(
                    "As imagens foram encontradas, mas não puderam ser abertas."
                )

        def fail(_error):
            if self._gallery_game_id == game.id:
                self.gallery_status.setText(
                    "Não foi possível carregar as imagens do site."
                )

        run_task(work, on_done=done, on_fail=fail)

    def _show_gallery_image(self, pixmap: QPixmap) -> None:
        """Exibe uma captura em tamanho ampliado."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Imagem da tradução")
        dialog.resize(960, 640)

        layout = QVBoxLayout(dialog)
        preview = QLabel()
        preview.setAlignment(Qt.AlignCenter)
        preview.setMinimumSize(320, 220)
        preview.setPixmap(
            pixmap.scaled(920, 570, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        layout.addWidget(preview)
        dialog.exec()

    def _show_game(self, g: Game) -> None:
        self._current_game = g
        rec = state.get_install(g.id)
        v = self._selected_version() or g.default()
        if v and v.id != self._current_version_id:
            self._current_version_id = v.id

        self.lbl_title.setText(g.name)
        self.lbl_desc.setText(g.description)
        self._load_project_gallery(g)
        self.banner.tag.setText(g.status_label)
        self.banner.tag.setStyleSheet(f"background: {g.status_color}; color: white; font-size: 12px; font-weight: 700; border-radius: 12px; padding: 5px 12px;")
        self.banner.set_banner(style.load_pixmap(catalog.local_image(g.banner)), g.banner_offset)

        logo = style.load_pixmap(catalog.local_image(g.logo)) if g.has_credits else None
        if logo:
            self.lbl_logo.setPixmap(logo.scaledToHeight(120, Qt.SmoothTransformation))
            self.lbl_logo.show()
        else:
            self.lbl_logo.hide()

        self.credits.setVisible(g.has_credits)
        for key, items in (("tr", g.credits_translation), ("de", g.credits_design), ("to", g.credits_tools), ("th", g.credits_thanks)):
            t, body = self._cr_labels[key]
            t.setVisible(bool(items))
            body.setVisible(bool(items))
            body.setText("\n".join(items))

        self.pct_tr.setText(f"{round(g.pct_translated * 100)}%")
        self.pct_rev.setText(f"{round(g.pct_reviewed * 100)}%")
        self.bar_tr.setFixedWidth(int(146 * g.pct_translated))
        self.bar_rev.setFixedWidth(int(146 * g.pct_reviewed))

        multi = len(g.versions) > 1
        self.drawer.setVisible(multi)
        if multi:
            self.drawer.set_game(g, rec, self._current_version_id)

        opts = g.options_for(v)
        self.opts_panel.setVisible(bool(opts))
        if opts:
            self.opts_panel.blockSignals(True)
            self.opts_panel.set_options(opts, self._chosen_for(g, v, rec))
            self.opts_panel.blockSignals(False)

        self._refresh_buttons()
        self.banner.relayout()

    def _chosen_for(self, g: Game, v: Optional[Version], rec: Optional[dict] = None) -> dict:
        """Escolhas atuais: o que o usuário mexeu > o que está instalado > padrões."""
        if v is None:
            return {}
        opts = g.options_for(v)
        key = f"{g.id}/{v.id}"
        if key in self._chosen:
            return catalog.normalize_options(opts, self._chosen[key])
        rec = rec if rec is not None else state.get_install(g.id)
        base = rec.get("options") if rec and rec.get("version_id") == v.id else None
        return catalog.normalize_options(opts, base)

    def _on_options_changed(self, chosen: dict) -> None:
        g, v = self._current_game, self._selected_version()
        if g and v:
            self._chosen[f"{g.id}/{v.id}"] = chosen
            self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        g, v = self._current_game, self._selected_version()
        if not g:
            return
        rec = state.get_install(g.id)
        cached = bool(v and (state.download_dir() / zip_name(g, v)).exists())
        kind, text = compute_action(v, rec, cached, g.options_for(v), self._chosen_for(g, v, rec))
        if self._outdated_installer and kind not in ("none", "installed"):
            kind, text = "none", "ATUALIZE O INSTALADOR"
        self.btn_main.setText(text)
        role = {"install": "primary", "installed": "", "update": "orange", "switch": "blue", "options": "blue"}.get(kind, "")
        style.style_button(self.btn_main, role)
        self.btn_main.setEnabled(kind in ("install", "update", "switch", "options") and not self._busy)
        self.btn_remove.setVisible(rec is not None)
        self.btn_remove.setEnabled(not self._busy)
        self.btn_redo.setVisible(rec is not None and kind == "installed")
        self.btn_redo.setEnabled(not self._busy)
        self.banner.actions.setVisible(not self._busy)
        self.banner.actions.adjustSize()
        self.banner.relayout()
        if len(g.versions) > 1:
            self.drawer.mark(self._current_version_id, rec)

    # -- ações ---------------------------------------------------------------- #
    def _on_main_click(self) -> None:
        g, v = self._current_game, self._selected_version()
        if not g or not v:
            return
        rec = state.get_install(g.id)
        chosen = self._chosen_for(g, v, rec)
        kind, _ = compute_action(v, rec, opts=g.options_for(v), chosen=chosen)
        if kind in ("install", "update", "switch", "options"):
            self._queue = [(g, v, kind, chosen)]
            self._run_next()

    def _on_reinstall(self) -> None:
        g, v = self._current_game, self._selected_version()
        if g and v and QMessageBox.question(self, "Reinstalar", "Remover e instalar novamente esta tradução?") == QMessageBox.Yes:
            self._queue = [(g, v, "reinstall", self._chosen_for(g, v))]
            self._run_next()

    def _on_uninstall(self) -> None:
        g = self._current_game
        rec = state.get_install(g.id) if g else None
        if not g or not rec:
            return
        if QMessageBox.question(self, "Desinstalar", f"Remover a tradução de\n{g.name}\ne restaurar os arquivos originais?") != QMessageBox.Yes:
            return
        folder = Path(rec["path"])
        self._set_busy(True, "Removendo tradução...")
        self.bar.setRange(0, 0)
        self.btn_pause.hide()
        self.btn_cancel.hide()

        def work(emit):
            return installer.uninstall(folder, progress=lambda i, n, rel: emit((i, n)))

        def done(res):
            state.forget_install(g.id)
            self._set_busy(False)
            msg = "Tradução desinstalada e arquivos originais restaurados."
            if res.skipped_changed:
                msg += f"\n\n{len(res.skipped_changed)} arquivo(s) foram atualizados pela Steam/outro programa depois da instalação e foram mantidos como estão."
            QMessageBox.information(self, "Desinstalação", msg)
            self._after_change()

        def fail(e):
            self._set_busy(False)
            QMessageBox.warning(self, "Erro ao desinstalar", installer.friendly_exception(e))
            self._after_change()

        run_task(work, done, fail)

    def _update_all(self) -> None:
        self._queue = [
            (g, v, "update", catalog.normalize_options(g.options_for(v), (state.get_install(g.id) or {}).get("options")))
            for g, v in pending_updates(self.catalog)
        ]
        self._run_next()

    # -- pipeline: baixar -> (remover antiga) -> instalar ---------------------- #
    def _run_next(self) -> None:
        if self._busy or not self._queue:
            return
        g, v, kind, chosen = self._queue.pop(0)
        rec = state.get_install(g.id)
        folder: Optional[Path] = Path(rec["path"]) if rec else None
        if folder is None:
            dlg = FindGameDialog(g, self)
            if dlg.exec() != QDialog.Accepted or dlg.folder is None:
                self._queue.clear()
                return
            folder = dlg.folder
        self._start_job(g, v, folder, chosen)

    def _start_job(self, g: Game, v: Version, folder: Path, chosen: Optional[dict] = None) -> None:
        opts = g.options_for(v)
        chosen = catalog.normalize_options(opts, chosen)
        sig = catalog.signature(v, opts, chosen)
        # pacotes: tradução base + um .zip extra para cada opção escolhida que tenha pacote
        pkgs = [(v.url, v.sha256, v.size, state.download_dir() / zip_name(g, v))]
        for o, c in catalog.selected_choices(opts, chosen):
            if c.has_pkg:
                pkgs.append((c.url, c.sha256, c.size, state.download_dir() / addon_zip_name(g, v, o, c)))
        had_record = state.get_install(g.id) is not None
        self._downloader = Downloader()
        dl = self._downloader
        self._set_busy(True, f"Preparando {g.name}...")
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.btn_pause.show()
        self.btn_pause.setText("⏸")
        self.btn_cancel.show()

        def reusable(url, sha, size, zp: Path) -> bool:
            if not zp.exists():
                return False
            if sha:
                return file_sha256(zp) == sha
            return size > 0 and zp.stat().st_size == size

        def work(emit):
            for n, (url, sha, size, zp) in enumerate(pkgs, 1):
                if not reusable(url, sha, size, zp):
                    dl.download(url, zp, lambda d, t, n=n: emit(("dl", d, t, n, len(pkgs))), sha)
            emit(("stage", "Instalando..."))
            if installer.has_translation(folder):
                installer.uninstall(folder)
            installer.install(
                folder, [p[3] for p in pkgs], g.id, v.id, v.version,
                progress=lambda i, n, rel: emit(("inst", i, n)), options=chosen, signature=sig,
            )
            return True

        def progress(data):
            if data[0] == "dl":
                _, d, t, n, total_pkgs = data
                part = f" (arquivo {n}/{total_pkgs})" if total_pkgs > 1 else ""
                mb = d / 1024 / 1024
                if t > 0:
                    self.bar.setRange(0, 100)
                    self.bar.setValue(int(d * 100 / t))
                    self.lbl_dl.setText(f"{'Pausado' if dl.paused else 'Baixando'}{part}...  {int(d * 100 / t)}%  ({mb:.0f} / {t / 1024 / 1024:.0f} MB)")
                else:
                    self.bar.setRange(0, 0)
                    self.lbl_dl.setText(f"Baixando{part}...  {mb:.0f} MB")
            elif data[0] == "stage":
                self.btn_pause.hide()
                self.btn_cancel.hide()  # a partir daqui não dá para cancelar sem deixar o jogo sem tradução
                self.bar.setRange(0, 100)
                self.lbl_dl.setText(data[1])
            elif data[0] == "inst":
                _, i, n = data
                self.bar.setValue(int(i * 100 / max(n, 1)))
                self.lbl_dl.setText(f"Instalando arquivos...  {i}/{n}")
            self.banner.relayout()

        def done(_):
            state.set_install(g.id, folder, v.id, v.version, chosen, sig)
            for *_x, zp in pkgs:
                try:
                    zp.unlink()
                except OSError:
                    pass
            self._set_busy(False)
            self._after_change()
            if not self._queue:
                QMessageBox.information(self, "Pronto!", f"{g.name}\nTradução {v.label} (v{v.version}) instalada com sucesso!")
            self._run_next()

        def fail(e):
            self._set_busy(False)
            self._queue.clear()
            self._after_change()
            if isinstance(e, DownloadCancelled):
                return
            msg = installer.friendly_exception(e) if not isinstance(e, DownloadError) else str(e)
            if had_record and not installer.has_translation(folder):
                msg += "\n\nA tradução anterior foi removida durante a troca; instale novamente quando quiser."
                state.forget_install(g.id)
            QMessageBox.warning(self, "Não foi possível concluir", msg)

        run_task(work, done, fail, progress)

    def _on_pause(self) -> None:
        if self._downloader:
            if self._downloader.paused:
                self._downloader.resume()
                self.btn_pause.setText("⏸")
            else:
                self._downloader.pause()
                self.btn_pause.setText("▶")

    def _on_cancel(self) -> None:
        if self._downloader:
            self._downloader.cancel()
            self.lbl_dl.setText("Cancelando...")

    def _set_busy(self, busy: bool, text: str = "") -> None:
        self._busy = busy
        self.list.setEnabled(not busy)
        self.drawer.setEnabled(not busy)
        self.opts_panel.setEnabled(not busy)
        self.btn_all.setEnabled(not busy)
        self.banner.download.setVisible(busy)
        if busy:
            self.lbl_dl.setText(text)
        self.banner.actions.setVisible(not busy)
        self.banner.relayout()
        if not busy:
            self._refresh_buttons()

    def _after_change(self) -> None:
        self._refresh_badges()
        if self._current_game:
            rec = state.get_install(self._current_game.id)
            if rec:
                self._current_version_id = rec.get("version_id", self._current_version_id)
            self._show_game(self._current_game)

    # -- atualizações --------------------------------------------------------- #
    def offer_shortcut(self) -> None:
        """Na primeira abertura (só no executável), oferece criar atalho."""
        s = state.load_settings()
        if not shortcut.can_offer() or s.get("shortcut_offered"):
            return
        s["shortcut_offered"] = True
        state.save_settings(s)
        if QMessageBox.question(self, "Atalho", "Criar um atalho do Starlight Translate no menu e na área de trabalho,\npara abrir mais fácil da próxima vez?") == QMessageBox.Yes:
            made = shortcut.create()
            if not made:
                QMessageBox.information(self, "Atalho", "Não consegui criar o atalho, mas você pode continuar usando o arquivo baixado normalmente.")

    def start_background_checks(self) -> None:
        s = state.load_settings()
        if s.get("check_installer_updates", True):
            run_task(lambda _e: selfupdate.check(), on_done=self._on_installer_update)
        self._prompt_translation_updates()

    def _prompt_translation_updates(self) -> None:
        if self._prompted_updates or not state.load_settings().get("check_translation_updates", True):
            return
        self._prompted_updates = True
        ups = pending_updates(self.catalog)
        if not ups:
            return
        lines = "\n".join(f"• {g.name}  →  {v.label} (v{v.version})" for g, v in ups)
        box = QMessageBox(self)
        box.setWindowTitle("Atualizações disponíveis")
        box.setText(f"Há {len(ups)} tradução(ões) com versão nova:\n\n{lines}")
        yes = box.addButton("Atualizar tudo", QMessageBox.AcceptRole)
        box.addButton("Depois", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is yes:
            self._update_all()

    def _on_installer_update(self, info: Optional[selfupdate.UpdateInfo]) -> None:
        self._update_info = info
        if info:
            self._show_notice(f"Nova versão do instalador disponível: v{info.version}", True)

    def _show_notice(self, text: str, can_update: bool) -> None:
        self.notice_text.setText(text)
        self.notice_btn.setVisible(can_update)
        self.notice.show()

    def _update_installer(self) -> None:
        info = self._update_info
        if not info:
            return
        if not selfupdate.can_self_replace():
            QMessageBox.information(self, "Atualização", f"Baixe a v{info.version} em:\nhttps://github.com/{app_config.INSTALLER_REPO}/releases/latest")
            return
        dlg = QProgressDialog(f"Baixando instalador v{info.version}...", "Cancelar", 0, 100, self)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dl = Downloader()
        dlg.canceled.connect(dl.cancel)

        def work(emit):
            return selfupdate.download_update(info, lambda d, t: emit((d, t)), dl)

        def prog(data):
            d, t = data
            if t > 0:
                dlg.setValue(int(d * 100 / t))

        def done(new_file):
            dlg.close()
            try:
                selfupdate.apply_and_restart(new_file)
            except OSError as e:
                QMessageBox.warning(self, "Atualização", f"Não consegui trocar o executável: {e}")

        def fail(e):
            dlg.close()
            if not isinstance(e, DownloadCancelled):
                QMessageBox.warning(self, "Atualização", str(e))

        run_task(work, done, fail, prog)

    def _open_settings(self) -> None:
        info = f"catálogo: {self.catalog.source}" + (f" ({self.catalog.updated})" if self.catalog.updated else "")
        SettingsDialog(self, info).exec()
        self._refresh_buttons()

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self.banner.relayout)

    def closeEvent(self, e):
        if self._busy and self._downloader:
            self._downloader.cancel()
        super().closeEvent(e)
