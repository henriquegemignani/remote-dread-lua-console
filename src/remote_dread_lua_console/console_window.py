from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtCore import Qt
from qasync import asyncSlot

from randovania.game_connection.executor.dread_lua_executor import DreadLuaExecutor
from randovania.game_connection.game_connection import GameConnection
from randovania.gui.generated.dread_lua_console_window_ui import Ui_DreadLuaConsoleWindow
from randovania.gui.lib import common_qt_lib


class DreadLuaConsoleWindow(QtWidgets.QMainWindow, Ui_DreadLuaConsoleWindow):
    def __init__(self, game_connection: GameConnection):
        super().__init__()
        self.setupUi(self)
        common_qt_lib.set_default_window_icon(self)

        self.game_connection = game_connection

        self._history_menu = QtWidgets.QMenu(self)
        self._copy_to_clipboard_action = self._history_menu.addAction("Copy to clipboard")

        self.history_widget.customContextMenuRequested.connect(self._on_context_menu)
        self.clear_button.clicked.connect(self.clear_log)
        self.execute_button.clicked.connect(self.execute_code)

    @asyncSlot()
    async def execute_code(self):
        executor = self.game_connection.executor
        if not isinstance(executor, DreadLuaExecutor):
            return self.add_log_entry("Current backend is not Dread Lua", color=Qt.red)

        try:
            code = self.code_edit.toPlainText()
            self.add_log_entry(code, color=Qt.green)
            result = await executor.run_lua_code(code)
            try:
                text_result = result.decode("utf-8")
            except ValueError:
                text_result = str(result)

            self.add_log_entry(text_result)

        except Exception as e:
            self.add_log_entry(str(e), color=Qt.red)

    def clear_log(self):
        self.history_widget.clear()

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
            common_qt_lib.set_clipboard(item.text())
