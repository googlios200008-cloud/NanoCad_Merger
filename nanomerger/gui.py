"""Standalone PySide6 desktop shell. All CAD work runs off the GUI thread."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from . import __version__
from .converters import find_oda
from .discovery import scan_folder
from .errors import CancelledError, NanoMergerError
from .models import DWG_VERSIONS, MergeOptions, MergeResult, Progress, safe_stem
from .publishing import default_output_name

QT_IMPORT_ERROR: Exception | None = None
try:
    from PySide6.QtCore import QSettings, Qt, QThread, QUrl, Signal
    from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent, QIcon
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QDoubleSpinBox,
        QFileDialog,
        QFrame,
        QGridLayout,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QProgressBar,
        QPushButton,
        QScrollArea,
        QSpinBox,
        QSplitter,
        QTableWidget,
        QTableWidgetItem,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover - exercised only without GUI extra
    QT_IMPORT_ERROR = exc


def require_qt() -> None:
    if QT_IMPORT_ERROR is not None:
        from .errors import DependencyError

        raise DependencyError(
            'Для окна установите GUI-зависимость: pip install -e ".[gui]"'
        ) from QT_IMPORT_ERROR


STYLE = """
QMainWindow, QWidget#root { background: #101923; color: #e6edf3; }
QFrame#header { background: #14212d; border-bottom: 1px solid #263847; }
QFrame#panel, QFrame#card { background: #172430; border: 1px solid #2a3b4a; border-radius: 10px; }
QLabel { color: #e6edf3; background: transparent; }
QLabel#muted, QLabel#hint { color: #91a4b5; }
QLabel#title { font-size: 27px; font-weight: 700; color: #f4f8fb; }
QLabel#section { font-size: 13px; font-weight: 700; color: #43d6c5; }
QLabel#metric { font-size: 23px; font-weight: 700; color: #f4c66b; }
QLabel#ok { color: #43d6c5; }
QLabel#warn { color: #f4c66b; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTableWidget {
  background: #0e1821; color: #e6edf3; border: 1px solid #334859; border-radius: 6px;
  padding: 6px; selection-background-color: #247c78;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border: 1px solid #43d6c5; }
QComboBox QAbstractItemView { background: #172430; color: #e6edf3; selection-background-color: #247c78; }
QPushButton, QToolButton { background: #243746; color: #e6edf3; border: 1px solid #3a5264; border-radius: 6px; padding: 8px 12px; }
QPushButton:hover, QToolButton:hover { background: #304b5d; }
QPushButton:disabled, QToolButton:disabled { color: #607483; background: #192731; border-color: #263847; }
QPushButton#primary { background: #43d6c5; color: #09211f; border: none; font-size: 14px; font-weight: 700; padding: 12px; }
QPushButton#primary:hover { background: #6ce4d6; }
QPushButton#primary:disabled { background: #285e5b; color: #83a9a5; }
QPushButton#danger { color: #ffb4a9; border-color: #805047; }
QTableWidget { gridline-color: #243644; alternate-background-color: #14212b; }
QHeaderView::section { background: #203240; color: #91a4b5; border: none; padding: 8px; }
QProgressBar { background: #0e1821; border: 1px solid #334859; border-radius: 6px; height: 16px; text-align: center; color: #e6edf3; }
QProgressBar::chunk { background: #43d6c5; border-radius: 5px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: #101923; width: 10px; }
QScrollBar::handle:vertical { background: #334859; border-radius: 5px; min-height: 24px; }
QCheckBox { color: #c7d4df; spacing: 8px; }
QSplitter::handle { background: #101923; width: 8px; }
"""


if QT_IMPORT_ERROR is None:

    class MergeWorker(QThread):
        progressed = Signal(object)
        completed = Signal(object)
        failed = Signal(str, str)
        cancelled = Signal()

        def __init__(
            self,
            input_dir: Path,
            output_dir: Path,
            name: str,
            options: MergeOptions,
            oda_path: str,
            parent=None,
        ) -> None:
            super().__init__(parent)
            self.input_dir, self.output_dir, self.name = input_dir, output_dir, name
            self.options, self.oda_path = options, oda_path
            self.cancel_event = threading.Event()

        def run(self) -> None:
            from .merger import merge_folder

            try:
                result = merge_folder(
                    self.input_dir,
                    self.output_dir,
                    output_name=self.name,
                    options=self.options,
                    oda_path=self.oda_path or None,
                    progress=self.progressed.emit,
                    cancel_event=self.cancel_event,
                )
                self.completed.emit(result)
            except CancelledError:
                self.cancelled.emit()
            except NanoMergerError as exc:
                self.failed.emit(str(exc), getattr(exc, "details", ""))
            except Exception as exc:
                self.failed.emit(f"Непредвиденная ошибка: {exc}", "")

    class NanoMergerWindow(QMainWindow):
        job_finished = Signal(object)
        job_failed = Signal(str)

        def __init__(self, parent=None, oda_path: str | Path | None = None) -> None:
            super().__init__(parent)
            self.setWindowTitle(f"NanoMerger {__version__} — комплект DWG + PDF")
            self.setMinimumSize(1120, 760)
            self.resize(1280, 820)
            self.setAcceptDrops(True)
            asset = Path(__file__).parent / "assets" / "logo.svg"
            self.setWindowIcon(QIcon(str(asset)))
            self.settings = QSettings("NanoMerger", "NanoMerger")
            self.worker: MergeWorker | None = None
            self.result: MergeResult | None = None
            self._close_when_done = False
            self._build_ui()
            self._load_settings(oda_path)
            self._update_oda_status()

        def _build_ui(self) -> None:
            root = QWidget()
            root.setObjectName("root")
            self.setCentralWidget(root)
            outer = QVBoxLayout(root)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(0)
            header = QFrame()
            header.setObjectName("header")
            header.setFixedHeight(88)
            head = QHBoxLayout(header)
            head.setContentsMargins(24, 12, 24, 12)
            logo = QLabel()
            logo.setPixmap(QIcon(str(Path(__file__).parent / "assets" / "logo.svg")).pixmap(54, 54))
            head.addWidget(logo)
            titles = QVBoxLayout()
            titles.setSpacing(2)
            title = QLabel("NanoMerger")
            title.setObjectName("title")
            subtitle = QLabel("Много DWG из EPLAN → один чертёж, отдельные листы, один PDF")
            subtitle.setObjectName("muted")
            titles.addWidget(title)
            titles.addWidget(subtitle)
            head.addLayout(titles)
            head.addStretch()
            badge = QLabel("PYTHON CORE  •  ODA DWG")
            badge.setObjectName("section")
            head.addWidget(badge)
            outer.addWidget(header)

            splitter = QSplitter(Qt.Horizontal)
            splitter.setChildrenCollapsible(False)
            left_scroll = QScrollArea()
            left_scroll.setWidgetResizable(True)
            left_scroll.setMinimumWidth(370)
            left = QWidget()
            left_scroll.setWidget(left)
            form = QVBoxLayout(left)
            form.setContentsMargins(18, 18, 12, 18)
            form.setSpacing(14)

            folders = QFrame()
            folders.setObjectName("panel")
            ff = QVBoxLayout(folders)
            ff.addWidget(self._section("Папки и результат"))
            self.input_edit = QLineEdit()
            self.input_edit.setPlaceholderText("Перетащите папку с DWG сюда или выберите…")
            self.output_edit = QLineEdit()
            self.output_edit.setPlaceholderText("По умолчанию: исходная папка / result")
            self.name_edit = QLineEdit()
            self.name_edit.setPlaceholderText("Например: EPLAN_merged")
            ff.addWidget(QLabel("Исходная папка"))
            ff.addLayout(self._path_row(self.input_edit, self._browse_input))
            ff.addWidget(QLabel("Папка результата"))
            ff.addLayout(self._path_row(self.output_edit, self._browse_output))
            ff.addWidget(QLabel("Имя комплекта"))
            ff.addWidget(self.name_edit)
            form.addWidget(folders)

            oda = QFrame()
            oda.setObjectName("panel")
            of = QVBoxLayout(oda)
            of.addWidget(self._section("Конвертер DWG"))
            self.oda_edit = QLineEdit()
            self.oda_edit.setPlaceholderText("Путь к ODAFileConverter.exe")
            self.oda_edit.textChanged.connect(self._update_oda_status)
            of.addLayout(self._path_row(self.oda_edit, self._browse_oda))
            self.oda_status = QLabel()
            self.oda_status.setWordWrap(True)
            of.addWidget(self.oda_status)
            hint = QLabel("ODA устанавливается отдельно. Для DXF-демо без CAD используйте CLI.")
            hint.setObjectName("hint")
            hint.setWordWrap(True)
            of.addWidget(hint)
            form.addWidget(oda)

            placement = QFrame()
            placement.setObjectName("panel")
            pf = QVBoxLayout(placement)
            pf.addWidget(self._section("Модель и листы"))
            grid = QGridLayout()
            grid.setVerticalSpacing(8)
            self.gap_spin = QDoubleSpinBox()
            self.gap_spin.setRange(0, 100000)
            self.gap_spin.setSuffix(" мм")
            self.gap_spin.setValue(50)
            self.columns_spin = QSpinBox()
            self.columns_spin.setRange(0, 1000)
            self.columns_spin.setValue(0)
            self.margin_spin = QDoubleSpinBox()
            self.margin_spin.setRange(0, 100)
            self.margin_spin.setSuffix(" мм")
            self.margin_spin.setValue(10)
            self.paper_combo = QComboBox()
            self.paper_combo.addItems(["auto", "source", "A4", "A3", "A2", "A1", "A0"])
            for row, (label, widget) in enumerate(
                [
                    ("Зазор в модели", self.gap_spin),
                    ("Столбцов (0 = лента)", self.columns_spin),
                    ("Поля листа", self.margin_spin),
                    ("Формат листа", self.paper_combo),
                ]
            ):
                grid.addWidget(QLabel(label), row, 0)
                grid.addWidget(widget, row, 1)
            pf.addLayout(grid)
            ph = QLabel(
                "Чертежи идут слева направо по номеру в имени файла. Каждый получает отдельный лист CAD."
            )
            ph.setObjectName("hint")
            ph.setWordWrap(True)
            pf.addWidget(ph)
            form.addWidget(placement)

            output = QFrame()
            output.setObjectName("panel")
            ov = QVBoxLayout(output)
            ov.addWidget(self._section("Запись"))
            self.version_combo = QComboBox()
            self.version_combo.addItems(list(DWG_VERSIONS))
            self.version_combo.setCurrentText("R2018")
            vr = QHBoxLayout()
            vr.addWidget(QLabel("Версия DWG"))
            vr.addWidget(self.version_combo)
            ov.addLayout(vr)
            self.color_check = QCheckBox("Цветной PDF (иначе чёрная геометрия)")
            ov.addWidget(self.color_check)
            self.overwrite_check = QCheckBox("Разрешить перезапись результата")
            ov.addWidget(self.overwrite_check)
            form.addWidget(output)
            self.refresh_button = QPushButton("Обновить список файлов")
            self.refresh_button.clicked.connect(self.refresh_files)
            form.addWidget(self.refresh_button)
            form.addStretch()
            splitter.addWidget(left_scroll)

            right = QWidget()
            rf = QVBoxLayout(right)
            rf.setContentsMargins(12, 18, 18, 18)
            rf.setSpacing(12)
            cards = QHBoxLayout()
            self.count_metric, count_card = self._card("Файлов в очереди", "0")
            self.order_metric, order_card = self._card("Порядок", "по номеру")
            self.format_metric, format_card = self._card("Результат", "DWG + PDF")
            for card in (count_card, order_card, format_card):
                cards.addWidget(card)
            rf.addLayout(cards)
            queue_title = self._section("Очередь объединения")
            rf.addWidget(queue_title)
            self.table = QTableWidget(0, 4)
            self.table.setHorizontalHeaderLabels(
                ["№", "Исходный файл", "Номер в имени", "Будущий лист"]
            )
            self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
            self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
            self.table.setColumnWidth(0, 48)
            self.table.setColumnWidth(2, 120)
            self.table.setAlternatingRowColors(True)
            self.table.setEditTriggers(QTableWidget.NoEditTriggers)
            self.table.verticalHeader().setVisible(False)
            self.table.setSelectionBehavior(QTableWidget.SelectRows)
            rf.addWidget(self.table, 1)
            self.queue_hint = QLabel(
                "Выберите папку. Подпапки не сканируются; Sheet2.dwg будет раньше Sheet10.dwg."
            )
            self.queue_hint.setObjectName("hint")
            self.queue_hint.setWordWrap(True)
            rf.addWidget(self.queue_hint)
            rf.addWidget(self._section("Журнал"))
            self.log = QPlainTextEdit()
            self.log.setReadOnly(True)
            self.log.setMaximumBlockCount(1000)
            self.log.setFixedHeight(125)
            rf.addWidget(self.log)
            self.progress = QProgressBar()
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress.setFormat("%p%")
            rf.addWidget(self.progress)
            self.status = QLabel("Готов к настройке")
            self.status.setObjectName("muted")
            rf.addWidget(self.status)
            buttons = QHBoxLayout()
            self.start_button = QPushButton("Объединить DWG + PDF")
            self.start_button.setObjectName("primary")
            self.start_button.clicked.connect(self.start_job)
            self.cancel_button = QPushButton("Отменить")
            self.cancel_button.setObjectName("danger")
            self.cancel_button.setEnabled(False)
            self.cancel_button.clicked.connect(self.cancel_job)
            self.open_button = QPushButton("Открыть папку результата")
            self.open_button.setEnabled(False)
            self.open_button.clicked.connect(self.open_result)
            buttons.addWidget(self.start_button, 1)
            buttons.addWidget(self.cancel_button)
            buttons.addWidget(self.open_button)
            rf.addLayout(buttons)
            splitter.addWidget(right)
            splitter.setSizes([390, 850])
            outer.addWidget(splitter, 1)
            self.setStyleSheet(STYLE)

        def _section(self, text: str) -> QLabel:
            label = QLabel(text)
            label.setObjectName("section")
            return label

        def _card(self, title: str, value: str) -> tuple[QLabel, QFrame]:
            card = QFrame()
            card.setObjectName("card")
            layout = QVBoxLayout(card)
            caption = QLabel(title)
            caption.setObjectName("muted")
            metric = QLabel(value)
            metric.setObjectName("metric")
            layout.addWidget(caption)
            layout.addWidget(metric)
            return metric, card

        def _path_row(self, edit: QLineEdit, callback) -> QHBoxLayout:
            row = QHBoxLayout()
            button = QToolButton()
            button.setText("…")
            button.setFixedWidth(38)
            button.clicked.connect(callback)
            row.addWidget(edit, 1)
            row.addWidget(button)
            return row

        def _load_settings(self, oda_path) -> None:
            self.oda_edit.setText(
                str(oda_path) if oda_path else self.settings.value("oda_path", "")
            )
            self.gap_spin.setValue(float(self.settings.value("gap_mm", 50)))
            self.columns_spin.setValue(int(self.settings.value("columns", 0)))
            self.margin_spin.setValue(float(self.settings.value("margin_mm", 10)))
            self.paper_combo.setCurrentText(self.settings.value("paper", "auto"))
            self.version_combo.setCurrentText(self.settings.value("dwg_version", "R2018"))
            self.color_check.setChecked(self.settings.value("color_pdf", False, type=bool))
            last = self.settings.value("input_folder", "")
            if last and Path(last).is_dir():
                self.set_input_folder(last)

        def _save_settings(self) -> None:
            self.settings.setValue("oda_path", self.oda_edit.text())
            self.settings.setValue("gap_mm", self.gap_spin.value())
            self.settings.setValue("columns", self.columns_spin.value())
            self.settings.setValue("margin_mm", self.margin_spin.value())
            self.settings.setValue("paper", self.paper_combo.currentText())
            self.settings.setValue("dwg_version", self.version_combo.currentText())
            self.settings.setValue("color_pdf", self.color_check.isChecked())
            self.settings.setValue("input_folder", self.input_edit.text())

        def _update_oda_status(self) -> None:
            path = find_oda(self.oda_edit.text().strip() or None)
            if path:
                self.oda_status.setText("✓ Исполняемый файл найден")
                self.oda_status.setObjectName("ok")
                self.oda_status.setToolTip(str(path))
            else:
                self.oda_status.setText("ODA не найден — укажите путь для работы с DWG")
                self.oda_status.setObjectName("warn")
                self.oda_status.setToolTip("")
            self.oda_status.style().unpolish(self.oda_status)
            self.oda_status.style().polish(self.oda_status)

        def _browse_input(self) -> None:
            folder = QFileDialog.getExistingDirectory(
                self, "Папка с исходными DWG", self.input_edit.text()
            )
            if folder:
                self.set_input_folder(folder)

        def _browse_output(self) -> None:
            folder = QFileDialog.getExistingDirectory(
                self, "Папка результата", self.output_edit.text()
            )
            if folder:
                self.output_edit.setText(folder)

        def _browse_oda(self) -> None:
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Выберите ODAFileConverter",
                self.oda_edit.text(),
                "ODAFileConverter (ODAFileConverter*);;Все файлы (*)",
            )
            if path:
                self.oda_edit.setText(path)

        def set_input_folder(self, folder: str | Path) -> None:
            folder = Path(folder).expanduser().resolve()
            self.input_edit.setText(str(folder))
            self.output_edit.setText(str(folder / "result"))
            self.refresh_files()

        def refresh_files(self) -> None:
            folder = self.input_edit.text().strip()
            if not folder:
                return
            try:
                files, warnings = scan_folder(folder, "dwg")
            except NanoMergerError as exc:
                self.table.setRowCount(0)
                self.count_metric.setText("0")
                self.queue_hint.setText(str(exc))
                self.status.setText("Проверьте исходную папку")
                return
            self.table.setRowCount(len(files))
            self.count_metric.setText(str(len(files)))
            for row, item in enumerate(files, start=0):
                values = [
                    str(row + 1),
                    item.name,
                    str(item.number) if item.number is not None else "—",
                    f"{row + 1:04d}_{item.path.stem[:180]}",
                ]
                for column, value in enumerate(values):
                    cell = QTableWidgetItem(value)
                    if column in (0, 2):
                        cell.setTextAlignment(Qt.AlignCenter)
                    self.table.setItem(row, column, cell)
            self.name_edit.setText(default_output_name(Path(folder), files))
            self.queue_hint.setText(
                "  •  ".join(warnings)
                if warnings
                else "Порядок определён по конечному числу. Разный регистр префикса считается одной группой."
            )
            self.status.setText(f"В очереди {len(files)} файлов")

        def dragEnterEvent(self, event: QDragEnterEvent) -> None:
            if event.mimeData().hasUrls() and any(
                Path(url.toLocalFile()).is_dir() for url in event.mimeData().urls()
            ):
                event.acceptProposedAction()

        def dropEvent(self, event: QDropEvent) -> None:
            for url in event.mimeData().urls():
                path = Path(url.toLocalFile())
                if path.is_dir():
                    self.set_input_folder(path)
                    break

        def start_job(self) -> None:
            if self.worker is not None and self.worker.isRunning():
                return
            folder = Path(self.input_edit.text().strip())
            try:
                files, _ = scan_folder(folder, "dwg")
                options = MergeOptions(
                    gap_mm=self.gap_spin.value(),
                    columns=self.columns_spin.value(),
                    margin_mm=self.margin_spin.value(),
                    paper=self.paper_combo.currentText(),
                    dwg_version=self.version_combo.currentText(),
                    color_pdf=self.color_check.isChecked(),
                    overwrite=self.overwrite_check.isChecked(),
                )
            except (NanoMergerError, ValueError) as exc:
                QMessageBox.warning(self, "Проверьте параметры", str(exc))
                return
            oda_text = self.oda_edit.text().strip()
            if not find_oda(oda_text or None):
                QMessageBox.warning(
                    self,
                    "Нужен ODA File Converter",
                    "Установите ODA File Converter и укажите путь к исполняемому файлу.\n"
                    "Без него NanoMerger не может читать и записывать настоящие DWG.\n"
                    "DXF-демо доступно через CLI: nanomerger merge … --input-format dxf --output-format dxf",
                )
                return
            output = Path(self.output_edit.text().strip() or folder / "result")
            name = safe_stem(self.name_edit.text() or default_output_name(folder, files))
            self._save_settings()
            self.result = None
            self.open_button.setEnabled(False)
            self.log.clear()
            self.progress.setValue(0)
            self._set_busy(True)
            self.worker = MergeWorker(folder, output, name, options, oda_text, self)
            self.worker.progressed.connect(self._on_progress)
            self.worker.completed.connect(self._on_completed)
            self.worker.failed.connect(self._on_failed)
            self.worker.cancelled.connect(self._on_cancelled)
            self.worker.finished.connect(self._worker_done)
            self.worker.start()

        def _set_busy(self, busy: bool) -> None:
            for widget in (
                self.refresh_button,
                self.start_button,
                self.input_edit,
                self.output_edit,
                self.name_edit,
                self.oda_edit,
                self.gap_spin,
                self.columns_spin,
                self.margin_spin,
                self.paper_combo,
                self.version_combo,
                self.color_check,
                self.overwrite_check,
            ):
                widget.setEnabled(not busy)
            self.cancel_button.setEnabled(busy)
            for button in self.findChildren(QToolButton):
                button.setEnabled(not busy)

        def _on_progress(self, event: Progress) -> None:
            self.progress.setValue(round(event.fraction * 100))
            self.status.setText(event.message)
            self.log.appendPlainText(f"[{event.stage}] {event.message}")

        def _on_completed(self, result: MergeResult) -> None:
            self.result = result
            self.progress.setValue(100)
            self.open_button.setEnabled(True)
            self.status.setText(
                f"Готово: {len(result.sheets)} листов за {result.duration_seconds:.1f} с"
            )
            for warning in result.warnings:
                self.log.appendPlainText("ПРЕДУПРЕЖДЕНИЕ: " + warning)
            self.job_finished.emit(result)

        def _on_failed(self, message: str, details: str) -> None:
            self.status.setText("Ошибка — результат не опубликован")
            self.log.appendPlainText("ОШИБКА: " + message)
            if details:
                self.log.appendPlainText(details)
            self.job_failed.emit(message)
            QMessageBox.critical(
                self, "NanoMerger — ошибка", message + ("\n\n" + details if details else "")
            )

        def _on_cancelled(self) -> None:
            self.status.setText("Отменено. Исходные файлы не изменены.")
            self.progress.setValue(0)
            self.log.appendPlainText("Задача отменена пользователем.")

        def _worker_done(self) -> None:
            self._set_busy(False)
            self.cancel_button.setEnabled(False)
            if self.worker is not None:
                self.worker.deleteLater()
                self.worker = None
            if self._close_when_done:
                self.close()

        def cancel_job(self) -> None:
            if self.worker is not None and self.worker.isRunning():
                self.worker.cancel_event.set()
                self.cancel_button.setEnabled(False)
                self.status.setText("Отмена после безопасной остановки конвертера…")

        def open_result(self) -> None:
            if self.result:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.result.output_dir)))

        def closeEvent(self, event) -> None:
            if self.worker is not None and self.worker.isRunning():
                self._close_when_done = True
                self.cancel_job()
                event.ignore()
                return
            self._save_settings()
            event.accept()


def run_app(input_folder: str | Path | None = None, oda_path: str | Path | None = None) -> int:
    require_qt()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("NanoMerger")
    app.setOrganizationName("NanoMerger")
    window = NanoMergerWindow(oda_path=oda_path)
    if input_folder:
        window.set_input_folder(input_folder)
    window.show()
    return app.exec()


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="NanoMerger desktop")
    parser.add_argument("input", nargs="?", type=Path)
    parser.add_argument("--oda", type=Path)
    args = parser.parse_args()
    try:
        return run_app(args.input, args.oda)
    except NanoMergerError as exc:
        print(exc, file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    raise SystemExit(main())
