"""The app's Training mode runs its own copy of the rules, tested against answer
keys made from this engine (scripts/export_training_fixtures.py). If a rule here
changes, this test fails until the keys are made again, and then the app's own
tests fail until its copy is fixed too.
"""
import importlib.util
import os

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SCRIPT = os.path.join(ROOT, "scripts", "export_training_fixtures.py")


def _load_script():
    spec = importlib.util.spec_from_file_location("export_training_fixtures", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_app_answer_keys_are_current():
    script = _load_script()
    out_dir = os.path.abspath(script.DEFAULT_OUT)
    if not os.path.isdir(out_dir):
        pytest.skip(f"the app is not checked out next to the server ({out_dir})")
    for name, text in script.build().items():
        with open(os.path.join(out_dir, name), encoding="utf-8") as fh:
            saved = fh.read()
        assert saved == text, (
            f"{name} is out of date: the game rules changed. Run "
            "`.venv/bin/python scripts/export_training_fixtures.py`, then fix the app's copy "
            "until its training tests pass."
        )
