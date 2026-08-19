"""Launcher for the canonical, guarded ferrite/Zener batch updater."""

from pathlib import Path
import runpy


CANONICAL_UPDATER = (
    Path(__file__).resolve().parents[2]
    / "PL Magnetics Ferrite"
    / "Tools"
    / "bulk_add_ferrite_and_zener_symbols.py"
)

if not CANONICAL_UPDATER.is_file():
    raise FileNotFoundError(CANONICAL_UPDATER)

runpy.run_path(str(CANONICAL_UPDATER), run_name="__main__")
