import asyncio
import functools
import logging
import logging.config
import sys
import time
import traceback

import qasync
from PySide6 import QtWidgets

from remote_dread_lua_console.console_window import ConsoleWindow

logger = logging.getLogger(__name__)


def display_exception(val: Exception):
    if not isinstance(val, KeyboardInterrupt):
        logger.exception("unhandled exception", exc_info=val)

        box = QtWidgets.QMessageBox(
            QtWidgets.QMessageBox.Critical,
            "An exception was raised",
            ("An unhandled Exception occurred:\n{}\n\n"
             "When reporting, make sure to paste the entire contents of the following box."
             "\nIt has already be copied to your clipboard."
             ).format(val),
            QtWidgets.QMessageBox.Ok,
        )

        detailed_exception = "".join(traceback.format_exception(val))
        box.setDetailedText(detailed_exception)

        # Expand the detailed text
        for button in box.buttons():
            if box.buttonRole(button) == QtWidgets.QMessageBox.ActionRole:
                button.click()
                break

        box_layout: QtWidgets.QGridLayout = box.layout()
        box_layout.addItem(
            QtWidgets.QSpacerItem(600, 0, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding),
            box_layout.rowCount(), 0, 1, box_layout.columnCount(),
        )
        box.exec()


def catch_exceptions(t, val, tb):
    display_exception(val)


def catch_exceptions_async(loop, context):
    if 'future' in context:
        future: asyncio.Future = context['future']
        logger.exception(context["message"], exc_info=future.exception())
    elif 'exception' in context:
        logger.exception(context["message"], exc_info=context['exception'])
    else:
        logger.critical(str(context))


async def qt_main():
    def close_future(_future, _loop):
        _loop.call_later(10, _future.cancel)
        _future.cancel()

    loop = asyncio.get_event_loop()
    sys.excepthook = catch_exceptions
    loop.set_exception_handler(catch_exceptions_async)
    future = asyncio.Future()

    app = QtWidgets.QApplication.instance()
    if hasattr(app, "aboutToQuit"):
        getattr(app, "aboutToQuit").connect(
            functools.partial(close_future, future, loop)
        )

    console = ConsoleWindow()
    console.show()

    await future
    return True


def main():
    try:
        logging.Formatter.converter = time.gmtime
        logging.config.dictConfig({
            'version': 1,
            'formatters': {
                'default': {
                    'format': '[%(asctime)s] [%(levelname)s] [%(name)s] %(funcName)s: %(message)s',
                }
            },
            'handlers': {
                'default': {
                    'level': "DEBUG",
                    'formatter': 'default',
                    'class': 'logging.StreamHandler',
                    'stream': 'ext://sys.stdout',  # Default is stderr
                },
            },
            'loggers': {
                'LuaExecutor': {
                    'level': 'DEBUG',
                },
                'qasync': {
                    'level': 'INFO',
                },
            },
            'root': {
                'level': "DEBUG",
                'handlers': ["default"],
            },
        })
        qasync.run(qt_main())
    except asyncio.exceptions.CancelledError:
        sys.exit(0)


if __name__ == '__main__':
    main()
