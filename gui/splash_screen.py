from __future__ import annotations

import logging
from collections.abc import Callable

from PyQt6.QtCore import QEasingCurve, QObject, QPointF, QPropertyAnimation, QSize, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)
try:
    from qfluentwidgets import isDarkTheme
except ImportError:
    isDarkTheme = None

from gui.main_window import MainWindow
from res.colors import (
    SPLASH_DARK_CARD_BACKGROUND,
    SPLASH_DARK_CARD_BORDER,
    SPLASH_DARK_PROGRESS_BACKGROUND,
    SPLASH_DARK_PROGRESS_CHUNK,
    SPLASH_DARK_STATUS_TEXT,
    SPLASH_DARK_SUBTITLE_TEXT,
    SPLASH_DARK_TITLE_TEXT,
    SPLASH_LIGHT_CARD_BACKGROUND,
    SPLASH_LIGHT_CARD_BORDER,
    SPLASH_LIGHT_PROGRESS_BACKGROUND,
    SPLASH_LIGHT_PROGRESS_CHUNK,
    SPLASH_LIGHT_STATUS_TEXT,
    SPLASH_LIGHT_SUBTITLE_TEXT,
    SPLASH_LIGHT_TITLE_TEXT,
    SPLASH_LOADER_ARC_DARK_RGB,
    SPLASH_LOADER_ARC_LIGHT_RGB,
    SPLASH_LOADER_TRACK_DARK_RGBA,
    SPLASH_LOADER_TRACK_LIGHT_RGBA,
)
from utils.i18n import t
from utils.startup_middleware import StartupWarmupSnapshot, warmup_startup_context


LOGGER = logging.getLogger(__name__)


class OrbitLoader(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(74, 74)
        self._angle = 0
        self._track_color = QColor(*SPLASH_LOADER_TRACK_LIGHT_RGBA)
        self._arc_color = QColor(*SPLASH_LOADER_ARC_LIGHT_RGB)

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._rotate)
        self._timer.start()

    def set_dark_mode(self, enabled: bool) -> None:
        self._track_color = QColor(
            *(SPLASH_LOADER_TRACK_DARK_RGBA if enabled else SPLASH_LOADER_TRACK_LIGHT_RGBA)
        )
        self._arc_color = QColor(
            *(SPLASH_LOADER_ARC_DARK_RGB if enabled else SPLASH_LOADER_ARC_LIGHT_RGB)
        )
        self.update()

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        center = QPointF(self.width() / 2, self.height() / 2)
        radius = 26

        painter.setPen(QPen(self._track_color, 3))
        painter.drawEllipse(center, radius, radius)

        painter.translate(center)
        painter.rotate(self._angle)

        for index, alpha in enumerate((255, 168, 86)):
            painter.save()
            painter.rotate(index * 34)
            color = QColor(self._arc_color)
            color.setAlpha(alpha)
            painter.setPen(QPen(color, 4, Qt.PenStyle.SolidLine))
            painter.drawArc(-radius, -radius, radius * 2, radius * 2, 22 * 16, 54 * 16)
            painter.restore()

    def _rotate(self) -> None:
        self._angle = (self._angle + 4) % 360
        self.update()


class SplashScreen(QWidget):
    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.SplashScreen)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(420, 310)
        self._dark_mode = self._detect_dark_mode()

        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0)
        self.setGraphicsEffect(self._opacity)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        card = QFrame(self)
        card.setObjectName("splashCard")
        root.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(34, 30, 34, 30)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.loader = OrbitLoader(card)
        self.loader.set_dark_mode(self._dark_mode)
        layout.addWidget(self.loader, 0, Qt.AlignmentFlag.AlignHCenter)

        title = QLabel("CharaPicker", card)
        title.setObjectName("splashTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel(t("startup.subtitle"), card)
        subtitle.setObjectName("splashSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        layout.addSpacing(8)

        self.status_label = QLabel(t("startup.status.boot"), card)
        self.status_label.setObjectName("splashStatus")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        self.progress = QProgressBar(card)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.setStyleSheet(self._style_sheet())

    def _style_sheet(self) -> str:
        if self._dark_mode:
            return f"""
            #splashCard {{
                background: {SPLASH_DARK_CARD_BACKGROUND};
                border: 1px solid {SPLASH_DARK_CARD_BORDER};
                border-radius: 18px;
            }}

            #splashTitle {{
                color: {SPLASH_DARK_TITLE_TEXT};
                font-size: 28px;
                font-weight: 650;
            }}

            #splashSubtitle {{
                color: {SPLASH_DARK_SUBTITLE_TEXT};
                font-size: 13px;
            }}

            #splashStatus {{
                color: {SPLASH_DARK_STATUS_TEXT};
                font-size: 13px;
            }}

            QProgressBar {{
                height: 5px;
                border: none;
                border-radius: 3px;
                background: {SPLASH_DARK_PROGRESS_BACKGROUND};
            }}

            QProgressBar::chunk {{
                border-radius: 3px;
                background: {SPLASH_DARK_PROGRESS_CHUNK};
            }}
            """

        return f"""
            #splashCard {{
                background: {SPLASH_LIGHT_CARD_BACKGROUND};
                border: 1px solid {SPLASH_LIGHT_CARD_BORDER};
                border-radius: 18px;
            }}

            #splashTitle {{
                color: {SPLASH_LIGHT_TITLE_TEXT};
                font-size: 28px;
                font-weight: 650;
            }}

            #splashSubtitle {{
                color: {SPLASH_LIGHT_SUBTITLE_TEXT};
                font-size: 13px;
            }}

            #splashStatus {{
                color: {SPLASH_LIGHT_STATUS_TEXT};
                font-size: 13px;
            }}

            QProgressBar {{
                height: 5px;
                border: none;
                border-radius: 3px;
                background: {SPLASH_LIGHT_PROGRESS_BACKGROUND};
            }}

            QProgressBar::chunk {{
                border-radius: 3px;
                background: {SPLASH_LIGHT_PROGRESS_CHUNK};
            }}
            """

    def _detect_dark_mode(self) -> bool:
        if isDarkTheme is not None:
            try:
                return isDarkTheme()
            except Exception:
                pass

        window_color = QApplication.palette().window().color()
        return window_color.lightness() < 128

    def showEvent(self, event) -> None:  # type: ignore[override]
        self._center_on_screen()
        super().showEvent(event)
        self._fade_to(1.0, 360)

    def set_step(self, message: str, progress: int) -> None:
        self.status_label.setText(message)
        self.progress.setValue(progress)

    def finish(self, on_finished: Callable[[], None]) -> None:
        self.progress.setValue(100)
        self.status_label.setText(t("startup.status.ready"))
        animation = self._fade_to(0.0, 260)
        animation.finished.connect(self.close)
        animation.finished.connect(lambda: QTimer.singleShot(0, on_finished))

    def _center_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geometry = screen.availableGeometry()
        self.move(geometry.center() - self.rect().center())

    def _fade_to(self, opacity: float, duration: int) -> QPropertyAnimation:
        animation = QPropertyAnimation(self._opacity, b"opacity", self)
        animation.setDuration(duration)
        animation.setStartValue(self._opacity.opacity())
        animation.setEndValue(opacity)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        return animation


class StartupController(QObject):
    MAIN_WINDOW_SIZE = QSize(1180, 760)

    def __init__(self) -> None:
        super().__init__()
        self.splash = SplashScreen()
        self.window: MainWindow | None = None
        self._startup_snapshot: StartupWarmupSnapshot | None = None
        self._warmup_thread: QThread | None = None
        self._warmup_worker: StartupWarmupWorker | None = None

    def start(self) -> None:
        LOGGER.info("Startup splash sequence started")
        self.splash.show()
        self.splash.set_step(t("startup.status.boot"), 12)
        QTimer.singleShot(180, self._start_warmup)

    def _start_warmup(self) -> None:
        if self._warmup_thread is not None:
            return
        LOGGER.info("Startup warmup thread starting")
        self._warmup_thread = QThread(self)
        self._warmup_worker = StartupWarmupWorker()
        self._warmup_worker.moveToThread(self._warmup_thread)
        self._warmup_thread.started.connect(self._warmup_worker.run)
        self._warmup_worker.progressChanged.connect(self._apply_warmup_progress)
        self._warmup_worker.succeeded.connect(self._finish_warmup)
        self._warmup_worker.failed.connect(self._handle_warmup_failure)
        self._warmup_worker.finished.connect(self._warmup_thread.quit)
        self._warmup_worker.finished.connect(self._warmup_worker.deleteLater)
        self._warmup_thread.finished.connect(self._warmup_thread.deleteLater)
        self._warmup_thread.finished.connect(self._clear_warmup_worker)
        self._warmup_thread.start()

    def _apply_warmup_progress(self, message_key: str, progress: int) -> None:
        self.splash.set_step(t(message_key), progress)

    def _finish_warmup(self, snapshot: StartupWarmupSnapshot) -> None:
        self._startup_snapshot = snapshot
        self._create_main_window()
        self.splash.finish(self._show_main_window)

    def _handle_warmup_failure(self, error: str) -> None:
        LOGGER.warning("Startup warmup failed; fallback to direct startup. error=%s", error)
        self._startup_snapshot = None
        self._create_main_window()
        self.splash.finish(self._show_main_window)

    def _clear_warmup_worker(self) -> None:
        self._warmup_thread = None
        self._warmup_worker = None

    def _create_main_window(self) -> None:
        LOGGER.info("Creating main window during startup")
        self.window = MainWindow(self._startup_snapshot)

    def _show_main_window(self) -> None:
        if self.window is None:
            LOGGER.info("Main window was not pre-created; creating before show")
            self.window = MainWindow(self._startup_snapshot)
        self.window.resize(self.MAIN_WINDOW_SIZE)
        self._center_main_window()
        QApplication.instance().setQuitOnLastWindowClosed(True)
        self.window.showNormal()
        LOGGER.info("Main window shown")

    def _center_main_window(self) -> None:
        if self.window is None:
            return
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geometry = screen.availableGeometry()
        frame = self.window.frameGeometry()
        frame.moveCenter(geometry.center())
        self.window.move(frame.topLeft())


class StartupWarmupWorker(QObject):
    progressChanged = pyqtSignal(str, int)
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    def run(self) -> None:
        try:
            snapshot = warmup_startup_context(progress=self.progressChanged.emit)
        except Exception as exc:
            LOGGER.warning("Startup warmup worker failed", exc_info=True)
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit(snapshot)
        finally:
            self.finished.emit()
