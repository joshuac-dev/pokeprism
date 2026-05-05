"""Import smoke tests for the live simulation stack.

These tests catch hard import errors (missing symbols, bad lazy imports, etc.)
that would otherwise only appear at runtime when a simulation starts.
Each test imports the module directly so the failure is traceable to the source.
"""

import importlib


def _import(name: str):
    """Import a module by dotted name; raise ImportError on failure."""
    return importlib.import_module(name)


def test_import_engine_runner():
    _import("app.engine.runner")


def test_import_engine_transitions():
    _import("app.engine.transitions")


def test_import_engine_effects_attacks():
    _import("app.engine.effects.attacks")


def test_import_engine_effects_abilities():
    _import("app.engine.effects.abilities")


def test_import_engine_effects_trainers():
    _import("app.engine.effects.trainers")


def test_import_engine_effects_energies():
    _import("app.engine.effects.energies")


def test_import_engine_batch():
    _import("app.engine.batch")


def test_import_tasks_simulation():
    _import("app.tasks.simulation")


def test_no_lazy_card_registry_import_in_attacks():
    """Ensure attacks.py does not use the invalid lazy import pattern."""
    import ast
    import pathlib

    src = pathlib.Path("app/engine/effects/attacks.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            # ast.ImportFrom has module attribute; ast.Import has names
            if isinstance(node, ast.ImportFrom) and node.module == "app.cards.loader":
                for alias in node.names:
                    assert alias.name != "card_registry", (
                        f"Invalid lazy import 'from app.cards.loader import card_registry' "
                        f"at line {node.lineno} in attacks.py — use "
                        f"'from app.cards import registry as card_registry' at module level."
                    )


def test_no_lazy_card_registry_import_in_trainers():
    """Ensure trainers.py does not use the invalid lazy import pattern."""
    import ast
    import pathlib

    src = pathlib.Path("app/engine/effects/trainers.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "app.cards.loader":
            for alias in node.names:
                assert alias.name != "card_registry", (
                    f"Invalid lazy import 'from app.cards.loader import card_registry' "
                    f"at line {node.lineno} in trainers.py — use "
                    f"'from app.cards import registry as card_registry' at module level."
                )
