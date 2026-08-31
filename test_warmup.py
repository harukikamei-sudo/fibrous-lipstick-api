"""Tests for extract_lab startup warmup.

These tests avoid importing the real extract_lab module so they do not depend
on machine-specific import time or optional native dependency load costs.
"""

import logging
import sys
import types

import app


class ListHandler(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.records = []

    def emit(self, record):
        self.records.append(record)


def test_warmup_imports_and_caches_extract_lab():
    print("Test 1: warmup imports and caches extract_lab")
    calls = []
    fake_module = types.SimpleNamespace(name="fake_extract_lab")
    original_importer = app._import_extract_lab
    original_module = app._EXTRACT_LAB_MODULE

    def fake_importer():
        calls.append("import")
        return fake_module

    try:
        app._EXTRACT_LAB_MODULE = None
        app._import_extract_lab = fake_importer

        app.warmup_extract_lab()

        assert calls == ["import"]
        assert app._EXTRACT_LAB_MODULE is fake_module
        assert app._el() is fake_module
        assert calls == ["import"]
    finally:
        app._import_extract_lab = original_importer
        app._EXTRACT_LAB_MODULE = original_module

    print("  OK")


def test_warmup_failure_logs_and_keeps_lazy_fallback():
    print("Test 2: warmup failure logs and keeps lazy fallback")
    calls = []
    fake_module = types.SimpleNamespace(name="fake_extract_lab_after_failure")
    handler = ListHandler()
    app_logger = logging.getLogger(app.__name__)
    original_level = app_logger.level
    original_importer = app._import_extract_lab
    original_module = app._EXTRACT_LAB_MODULE

    def flaky_importer():
        calls.append("import")
        if len(calls) == 1:
            raise RuntimeError("synthetic import failure")
        return fake_module

    try:
        app._EXTRACT_LAB_MODULE = None
        app._import_extract_lab = flaky_importer
        app_logger.addHandler(handler)
        app_logger.setLevel(logging.ERROR)

        app.warmup_extract_lab()

        assert calls == ["import"]
        assert app._EXTRACT_LAB_MODULE is None
        assert any(
            "falling back to lazy import" in record.getMessage()
            for record in handler.records
        )
        assert any(record.exc_info for record in handler.records)

        assert app._el() is fake_module
        assert calls == ["import", "import"]
        assert app._EXTRACT_LAB_MODULE is fake_module
    finally:
        app_logger.removeHandler(handler)
        app_logger.setLevel(original_level)
        app._import_extract_lab = original_importer
        app._EXTRACT_LAB_MODULE = original_module

    print("  OK")


def test_startup_hook_runs_warmup_synchronously():
    print("Test 3: startup hook runs warmup synchronously")
    calls = []
    original_warmup = app.warmup_extract_lab

    def fake_warmup():
        calls.append("warmup")

    try:
        app.warmup_extract_lab = fake_warmup
        handlers = [
            handler for handler in app.app.router.on_startup
            if getattr(handler, "__name__", "") == "_warmup_extract_lab_on_startup"
        ]

        assert len(handlers) == 1
        assert handlers[0]() is None
        assert calls == ["warmup"]
    finally:
        app.warmup_extract_lab = original_warmup

    print("  OK")


def main():
    test_warmup_imports_and_caches_extract_lab()
    test_warmup_failure_logs_and_keeps_lazy_fallback()
    test_startup_hook_runs_warmup_synchronously()
    print("PASS: 全テスト通過")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"FAIL: {e}")
        sys.exit(1)
