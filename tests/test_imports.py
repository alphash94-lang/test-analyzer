from __future__ import annotations

import importlib
import pkgutil

import app
import scripts


def test_all_application_modules_import() -> None:
    module_names = [
        module_info.name
        for module_info in pkgutil.walk_packages(app.__path__, prefix="app.")
    ]

    for module_name in module_names:
        importlib.import_module(module_name)


def test_all_script_modules_import() -> None:
    module_names = [
        module_info.name
        for module_info in pkgutil.walk_packages(
            scripts.__path__,
            prefix="scripts.",
        )
    ]

    for module_name in module_names:
        importlib.import_module(module_name)
