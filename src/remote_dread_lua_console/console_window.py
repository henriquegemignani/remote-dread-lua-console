from pathlib import Path

from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtCore import Qt
from qasync import asyncSlot

from remote_dread_lua_console.generated.console_window_ui import Ui_ConsoleWindow
from remote_dread_lua_console.lua_executor import LuaExecutor
from PySide6.QtCore import Slot

last_ip_file = Path(__file__).parent.joinpath("last_ip.txt")


def set_clipboard(text: str):
    QtWidgets.QApplication.clipboard().setText(text)


class ConsoleWindow(QtWidgets.QMainWindow, Ui_ConsoleWindow):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        try:
            ip = last_ip_file.read_text("utf-8")
        except FileNotFoundError:
            ip = ""

        self.executor = LuaExecutor(ip)
        self.executor.window_signals.log_for_window.connect(self.add_log_entries)
        self.executor.window_signals.connection_changed.connect(self.update_is_connected)
        self.ip_edit.setText(ip)
        self.update_is_connected()

        self._history_menu = QtWidgets.QMenu(self)
        self._copy_to_clipboard_action = self._history_menu.addAction("Copy to clipboard")

        self.history_widget.customContextMenuRequested.connect(self._on_context_menu)
        self.clear_button.clicked.connect(self.clear_log)
        self.connect_button.clicked.connect(self.toggle_connect_state)
        self.execute_button.clicked.connect(self.execute_code)
        self.execute_button.setEnabled(False)
        self.ip_edit.textChanged.connect(self._update_ip)

    @asyncSlot()
    async def execute_code(self):
        executor = self.executor

        try:
            code = self.code_edit.toPlainText()
            self.add_log_entry(code, color=Qt.darkGreen)
            await executor.run_lua_code(code)
        except Exception as e:
            self.add_log_entry(str(e), color=Qt.red)

    def clear_log(self):
        self.history_widget.clear()

    @Slot()
    def add_log_entries(self):
        scrollbar = self.history_widget.verticalScrollBar()
        autoscroll = scrollbar.value() == scrollbar.maximum()
        self.history_widget.addItems(self.executor.pending_messages)
        self.executor.pending_messages.clear()
        if autoscroll:
            self.history_widget.scrollToBottom()

    def add_log_entry(self, message: str, color: Qt.GlobalColor | None = None):
        scrollbar = self.history_widget.verticalScrollBar()
        autoscroll = scrollbar.value() == scrollbar.maximum()

        self.history_widget.addItem(message)
        if color is not None:
            item: QtWidgets.QListWidgetItem = self.history_widget.item(self.history_widget.count() - 1)
            item.setForeground(color)

        if autoscroll:
            self.history_widget.scrollToBottom()

    def _on_context_menu(self, pos: QtCore.QPoint):
        item: QtWidgets.QListWidgetItem = self.history_widget.itemAt(pos)
        if item is None:
            return

        result = self._history_menu.exec_(QtGui.QCursor.pos())
        if result is self._copy_to_clipboard_action:
            set_clipboard(item.text())

    @Slot()
    def update_is_connected(self):
        if self.executor.is_connected():
            msg = "Connected"
            btn_label = "Disconnect"
            last_ip_file.write_text(self.executor.ip)
            self.execute_button.setEnabled(True)
        else:
            msg = "Disconnected"
            btn_label = "Connect"
            self.execute_button.setEnabled(False)

        self.connected_label.setText(msg)
        self.connect_button.setText(btn_label)

    def _update_ip(self):
        self.executor.ip = self.ip_edit.text().strip()

    @asyncSlot()
    async def toggle_connect_state(self):
        executor = self.executor
        try:
            if not executor.is_connected():
                self.add_log_entry(f"Connecting to {executor.ip}", color=Qt.blue)
                await executor.connect_or_raise()
                self.add_log_entry(f"Connected to {executor.ip}", color=Qt.blue)
            else:
                executor.disconnect()

        except Exception as e:
            self.add_log_entry(str(e), color=Qt.red)
