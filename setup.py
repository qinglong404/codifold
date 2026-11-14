"""Bundle runtime resources without duplicating them in the source tree."""
from pathlib import Path
import shutil

from setuptools import setup
from setuptools.command.build_py import build_py

ROOT = Path(__file__).resolve().parent


class BuildPy(build_py):
    def run(self):
        super().run()
        destination = Path(self.build_lib) / "codifold" / "_resources"
        if destination.exists():
            shutil.rmtree(destination)
        for relative in ("frontend/dist", "examples"):
            shutil.copytree(
                ROOT / relative, destination / relative,
                ignore=shutil.ignore_patterns(
                    "__pycache__", "*.pyc", "*.pyo", ".codifold", "*.db", "*.sqlite*"),
            )
        guides = destination / "docs"
        guides.mkdir(parents=True)
        for source in (ROOT / "docs").glob("*.md"):
            shutil.copy2(source, guides / source.name)
        shutil.copy2(ROOT / "frontend" / "THIRD_PARTY_NOTICES.md", destination)


setup(cmdclass={"build_py": BuildPy})
