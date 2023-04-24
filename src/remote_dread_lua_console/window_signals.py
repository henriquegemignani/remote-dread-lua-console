from PySide6.QtCore import Signal, QObject

class WindowSignals(QObject):                                                 
    log_for_window = Signal()
    connection_changed = Signal()