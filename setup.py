from pathlib import Path

from pyqt_distutils.build_ui import build_ui
from setuptools import setup
from setuptools.command.egg_info import egg_info


class GenerateTemplateCommand(egg_info):
    """
    Generate script templates code before building the package.
    """

    def run(self):
        if Path(__file__).parent.joinpath("ui_files").is_dir():
            self.run_command('build_ui')
        return egg_info.run(self)


setup(
    cmdclass={
        "build_ui": build_ui,
        'egg_info': GenerateTemplateCommand,
    },
)
