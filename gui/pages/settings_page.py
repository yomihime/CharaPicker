from __future__ import annotations

from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal
from PyQt6.QtGui import QIntValidator
from PyQt6.QtWidgets import QFormLayout, QGridLayout, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    CheckBox,
    ComboBox,
    LineEdit,
    PasswordLineEdit,
    PushButton,
    SubtitleLabel,
    SwitchButton,
)

from res.colors import PROXY_TEST_FAILURE, PROXY_TEST_RUNNING, PROXY_TEST_SUCCESS
from utils.i18n import (
    SUPPORTED_LOCALES,
    SYSTEM_LOCALE,
    locale_name,
    locale_preference,
    set_locale_preference,
    t,
)
from utils.logging_preferences import (
    LOG_LEVEL_NAMES,
    SUPPORTED_LOG_LEVELS,
    log_level_preference,
    set_log_level_preference,
)
from utils.theme import (
    SUPPORTED_THEMES,
    THEME_NAMES,
    set_theme_preference,
    theme_preference,
)
from utils.network_middleware import (
    FIXED_CONNECTIVITY_TARGETS,
    ConnectivityTarget,
    custom_connectivity_target,
    redact_sensitive_text,
    test_connectivity,
)
from utils.proxy_preferences import (
    SUPPORTED_PROXY_SCHEMES,
    ProxySettings,
    load_proxy_settings,
    save_proxy_settings,
)


STATUS_LIGHT = chr(9679)


class ConnectivityTestWorker(QObject):
    targetResult = pyqtSignal(dict)
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, targets: list[ConnectivityTarget]) -> None:
        super().__init__()
        self.targets = targets

    def run(self) -> None:
        try:
            for target in self.targets:
                self.targetResult.emit(test_connectivity(target).to_dict())
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(redact_sensitive_text(exc))
        finally:
            self.finished.emit()


class SettingsPage(QWidget):
    languageChanged = pyqtSignal(str)
    themeChanged = pyqtSignal(str)
    logLevelChanged = pyqtSignal(str)
    proxyChanged = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsPage")
        self._language_values = [SYSTEM_LOCALE, *SUPPORTED_LOCALES]
        self._loading_language = False
        self._theme_values = list(SUPPORTED_THEMES)
        self._loading_theme = False
        self._log_level_values = list(SUPPORTED_LOG_LEVELS)
        self._loading_log_level = False
        self._proxy_scheme_values = list(SUPPORTED_PROXY_SCHEMES)
        self._loading_proxy = False
        self._test_thread: QThread | None = None
        self._test_worker: ConnectivityTestWorker | None = None
        self._connectivity_status_labels: dict[str, tuple[BodyLabel, CaptionLabel]] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)
        root.addWidget(SubtitleLabel(t("settings.title"), self))

        card = CardWidget(self)
        card.setBorderRadius(8)
        form = QFormLayout(card)
        form.setContentsMargins(20, 18, 20, 20)
        form.setSpacing(12)

        self.language_combo = ComboBox(card)
        self._load_language_options()

        self.theme_combo = ComboBox(card)
        self._load_theme_options()

        self.log_level_combo = ComboBox(card)
        self._load_log_level_options()

        form.addRow(t("settings.field.language"), self.language_combo)
        form.addRow(t("settings.field.theme"), self.theme_combo)
        form.addRow(t("settings.field.logLevel"), self.log_level_combo)
        root.addWidget(card)

        proxy_card = CardWidget(self)
        proxy_card.setBorderRadius(8)
        proxy_grid = QGridLayout(proxy_card)
        proxy_grid.setContentsMargins(20, 18, 20, 20)
        proxy_grid.setHorizontalSpacing(14)
        proxy_grid.setVerticalSpacing(12)

        self.proxy_enabled = SwitchButton(proxy_card)
        self.proxy_scheme_combo = ComboBox(proxy_card)
        self._load_proxy_scheme_options()

        self.proxy_remote_dns = CheckBox(t("settings.proxy.remoteDns"), proxy_card)
        self.proxy_host = LineEdit(proxy_card)
        self.proxy_host.setPlaceholderText(t("settings.proxy.host.placeholder"))
        self.proxy_port = LineEdit(proxy_card)
        self.proxy_port.setPlaceholderText(t("settings.proxy.port.placeholder"))
        self.proxy_port.setValidator(QIntValidator(1, 65535, self.proxy_port))
        self.proxy_username = LineEdit(proxy_card)
        self.proxy_username.setPlaceholderText(t("settings.proxy.username.placeholder"))
        self.proxy_password = PasswordLineEdit(proxy_card)
        self.proxy_password.setPlaceholderText(t("settings.proxy.password.placeholder"))
        self.proxy_custom_url = LineEdit(proxy_card)
        self.proxy_custom_url.setPlaceholderText(t("settings.proxy.customUrl.placeholder"))
        self.proxy_save_button = PushButton(t("settings.proxy.save"), proxy_card)
        self.proxy_test_fixed_button = PushButton(t("settings.proxy.test.fixed"), proxy_card)
        self.proxy_test_custom_button = PushButton(t("settings.proxy.test.custom"), proxy_card)

        enable_row = QHBoxLayout()
        enable_row.setSpacing(10)
        enable_row.addWidget(self.proxy_enabled)
        enable_row.addWidget(BodyLabel(t("settings.proxy.enable"), proxy_card))
        enable_row.addStretch(1)

        proxy_grid.addWidget(BodyLabel(t("settings.field.proxy"), proxy_card), 0, 0)
        proxy_grid.addLayout(enable_row, 0, 1, 1, 3)
        proxy_grid.addWidget(BodyLabel(t("settings.proxy.scheme"), proxy_card), 1, 0)
        proxy_grid.addWidget(self.proxy_scheme_combo, 1, 1)
        proxy_grid.addWidget(self.proxy_remote_dns, 1, 2, 1, 2)
        proxy_grid.addWidget(BodyLabel(t("settings.proxy.host"), proxy_card), 2, 0)
        proxy_grid.addWidget(self.proxy_host, 2, 1)
        proxy_grid.addWidget(BodyLabel(t("settings.proxy.port"), proxy_card), 2, 2)
        proxy_grid.addWidget(self.proxy_port, 2, 3)
        proxy_grid.addWidget(BodyLabel(t("settings.proxy.username"), proxy_card), 3, 0)
        proxy_grid.addWidget(self.proxy_username, 3, 1)
        proxy_grid.addWidget(BodyLabel(t("settings.proxy.password"), proxy_card), 3, 2)
        proxy_grid.addWidget(self.proxy_password, 3, 3)
        proxy_grid.addWidget(BodyLabel(t("settings.proxy.customUrl"), proxy_card), 4, 0)
        proxy_grid.addWidget(self.proxy_custom_url, 4, 1, 1, 3)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        action_row.addWidget(self.proxy_save_button)
        action_row.addWidget(self.proxy_test_fixed_button)
        action_row.addWidget(self.proxy_test_custom_button)
        action_row.addStretch(1)
        proxy_grid.addLayout(action_row, 5, 1, 1, 3)

        hint_label = CaptionLabel(t("settings.proxy.localStorageHint"), proxy_card)
        hint_label.setWordWrap(True)
        proxy_grid.addWidget(hint_label, 6, 0, 1, 4)

        proxy_grid.addWidget(BodyLabel(t("settings.proxy.test.title"), proxy_card), 7, 0)
        status_row = 8
        for target in FIXED_CONNECTIVITY_TARGETS:
            self._add_connectivity_status_row(proxy_grid, proxy_card, status_row, target)
            status_row += 1
        self._add_connectivity_status_row(
            proxy_grid,
            proxy_card,
            status_row,
            ConnectivityTarget("custom", t("settings.proxy.test.customTarget"), ""),
        )

        proxy_grid.setColumnStretch(0, 0)
        proxy_grid.setColumnStretch(1, 2)
        proxy_grid.setColumnStretch(2, 0)
        proxy_grid.setColumnStretch(3, 2)
        root.addWidget(proxy_card)
        root.addStretch(1)

        self.language_combo.currentIndexChanged.connect(self._change_language)
        self.theme_combo.currentIndexChanged.connect(self._change_theme)
        self.log_level_combo.currentIndexChanged.connect(self._change_log_level)
        self.proxy_scheme_combo.currentIndexChanged.connect(self._update_proxy_remote_dns_state)
        self.proxy_save_button.clicked.connect(self._save_proxy_settings)
        self.proxy_test_fixed_button.clicked.connect(self._start_fixed_connectivity_test)
        self.proxy_test_custom_button.clicked.connect(self._start_custom_connectivity_test)
        self._load_proxy_options()

    def _load_language_options(self) -> None:
        self._loading_language = True
        self.language_combo.clear()
        for locale in self._language_values:
            self.language_combo.addItem(locale_name(locale))

        preference = locale_preference()
        index = self._language_values.index(preference) if preference in self._language_values else 0
        self.language_combo.setCurrentIndex(index)
        self._loading_language = False

    def _change_language(self) -> None:
        if self._loading_language:
            return
        index = self.language_combo.currentIndex()
        if not 0 <= index < len(self._language_values):
            return
        locale = self._language_values[index]
        set_locale_preference(locale)
        self.languageChanged.emit(locale)

    def _load_theme_options(self) -> None:
        self._loading_theme = True
        self.theme_combo.clear()
        for theme in self._theme_values:
            self.theme_combo.addItem(t(THEME_NAMES[theme]))

        preference = theme_preference()
        index = self._theme_values.index(preference) if preference in self._theme_values else 0
        self.theme_combo.setCurrentIndex(index)
        self._loading_theme = False

    def _change_theme(self) -> None:
        if self._loading_theme:
            return
        index = self.theme_combo.currentIndex()
        if not 0 <= index < len(self._theme_values):
            return
        theme = self._theme_values[index]
        set_theme_preference(theme)
        self.themeChanged.emit(theme)

    def _load_log_level_options(self) -> None:
        self._loading_log_level = True
        self.log_level_combo.clear()
        for level in self._log_level_values:
            self.log_level_combo.addItem(t(LOG_LEVEL_NAMES[level]))

        preference = log_level_preference()
        index = self._log_level_values.index(preference) if preference in self._log_level_values else 1
        self.log_level_combo.setCurrentIndex(index)
        self._loading_log_level = False

    def _change_log_level(self) -> None:
        if self._loading_log_level:
            return
        index = self.log_level_combo.currentIndex()
        if not 0 <= index < len(self._log_level_values):
            return
        level = self._log_level_values[index]
        set_log_level_preference(level)
        self.logLevelChanged.emit(level)

    def _load_proxy_scheme_options(self) -> None:
        self.proxy_scheme_combo.clear()
        for scheme in self._proxy_scheme_values:
            self.proxy_scheme_combo.addItem(t(f"settings.proxy.scheme.{scheme}"))

    def _load_proxy_options(self) -> None:
        self._loading_proxy = True
        settings = load_proxy_settings()
        self.proxy_enabled.setChecked(settings.enabled)
        index = (
            self._proxy_scheme_values.index(settings.scheme)
            if settings.scheme in self._proxy_scheme_values
            else 0
        )
        self.proxy_scheme_combo.setCurrentIndex(index)
        self.proxy_remote_dns.setChecked(settings.remote_dns)
        self.proxy_host.setText(settings.host)
        self.proxy_port.setText(str(settings.port) if settings.port else "")
        self.proxy_username.setText(settings.username)
        self.proxy_password.setText(settings.password)
        self.proxy_custom_url.setText(settings.custom_test_url)
        self._loading_proxy = False
        self._update_proxy_remote_dns_state()

    def _current_proxy_scheme(self) -> str:
        index = self.proxy_scheme_combo.currentIndex()
        if 0 <= index < len(self._proxy_scheme_values):
            return self._proxy_scheme_values[index]
        return self._proxy_scheme_values[0]

    def _collect_proxy_settings(self) -> ProxySettings:
        try:
            port = int(self.proxy_port.text().strip())
        except ValueError:
            port = 0
        return ProxySettings(
            enabled=self.proxy_enabled.isChecked(),
            scheme=self._current_proxy_scheme(),  # type: ignore[arg-type]
            remote_dns=self.proxy_remote_dns.isChecked(),
            host=self.proxy_host.text().strip(),
            port=port,
            username=self.proxy_username.text().strip(),
            password=self.proxy_password.text(),
            custom_test_url=self.proxy_custom_url.text().strip(),
        )

    def _save_proxy_settings(self, _checked: bool = False, *, show_feedback: bool = True) -> None:
        if self._loading_proxy:
            return
        save_proxy_settings(self._collect_proxy_settings())
        self._load_proxy_options()
        if show_feedback:
            self.proxyChanged.emit()

    def _update_proxy_remote_dns_state(self) -> None:
        self.proxy_remote_dns.setEnabled(self._current_proxy_scheme() == "socks5")

    def _add_connectivity_status_row(
        self,
        layout: QGridLayout,
        parent: QWidget,
        row: int,
        target: ConnectivityTarget,
    ) -> None:
        name_label = CaptionLabel(target.label, parent)
        light_label = BodyLabel("", parent)
        light_label.setFixedWidth(18)
        light_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_label = CaptionLabel(t("settings.proxy.test.status.idle"), parent)
        status_label.setWordWrap(True)
        layout.addWidget(name_label, row, 0)
        layout.addWidget(light_label, row, 1, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(status_label, row, 2, 1, 2)
        self._connectivity_status_labels[target.target_id] = (light_label, status_label)

    def _start_fixed_connectivity_test(self, _checked: bool = False) -> None:
        self._start_connectivity_test(list(FIXED_CONNECTIVITY_TARGETS))

    def _start_custom_connectivity_test(self, _checked: bool = False) -> None:
        target = custom_connectivity_target(
            self.proxy_custom_url.text().strip() or ProxySettings().custom_test_url
        )
        self._start_connectivity_test([target])

    def _start_connectivity_test(self, targets: list[ConnectivityTarget]) -> None:
        if self._test_thread is not None:
            return
        self._save_proxy_settings(show_feedback=False)
        for target in targets:
            self._set_connectivity_status(target.target_id, "running")
        self._set_proxy_test_running(True)

        thread = QThread(self)
        worker = ConnectivityTestWorker(targets)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.targetResult.connect(self._handle_connectivity_result)
        worker.failed.connect(self._handle_connectivity_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_connectivity_worker)
        self._test_thread = thread
        self._test_worker = worker
        thread.start()

    def _set_proxy_test_running(self, running: bool) -> None:
        self.proxy_save_button.setEnabled(not running)
        self.proxy_test_fixed_button.setEnabled(not running)
        self.proxy_test_custom_button.setEnabled(not running)

    def _clear_connectivity_worker(self) -> None:
        self._test_thread = None
        self._test_worker = None
        self._set_proxy_test_running(False)

    def _handle_connectivity_result(self, payload: dict) -> None:
        target_id = str(payload.get("target_id", ""))
        ok = bool(payload.get("ok"))
        status_code = payload.get("status_code")
        elapsed_ms = int(payload.get("elapsed_ms") or 0)
        error = str(payload.get("error") or "")
        if ok:
            text = t("settings.proxy.test.status.success", elapsed_ms=elapsed_ms)
            self._set_connectivity_status(target_id, "success", text)
        elif isinstance(status_code, int):
            text = t("settings.proxy.test.status.httpFailure", status_code=status_code)
            self._set_connectivity_status(target_id, "failure", text)
        else:
            text = t("settings.proxy.test.status.failure", error=error)
            self._set_connectivity_status(target_id, "failure", text)

    def _handle_connectivity_failed(self, error: str) -> None:
        for target_id, (_light_label, status_label) in self._connectivity_status_labels.items():
            if status_label.text() == t("settings.proxy.test.status.running"):
                self._set_connectivity_status(
                    target_id,
                    "failure",
                    t("settings.proxy.test.status.failure", error=error),
                )

    def _set_connectivity_status(
        self,
        target_id: str,
        state: str,
        text: str | None = None,
    ) -> None:
        labels = self._connectivity_status_labels.get(target_id)
        if labels is None:
            return
        light_label, status_label = labels
        if state == "success":
            light_label.setText(STATUS_LIGHT)
            light_label.setStyleSheet(f"color: {PROXY_TEST_SUCCESS};")
        elif state == "failure":
            light_label.setText(STATUS_LIGHT)
            light_label.setStyleSheet(f"color: {PROXY_TEST_FAILURE};")
        elif state == "running":
            light_label.setText(STATUS_LIGHT)
            light_label.setStyleSheet(f"color: {PROXY_TEST_RUNNING};")
            text = t("settings.proxy.test.status.running")
        else:
            light_label.setText("")
            light_label.setStyleSheet("")
            text = t("settings.proxy.test.status.idle")
        status_label.setText(text or t("settings.proxy.test.status.idle"))
