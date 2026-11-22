#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Standard-library test runner for this directory. No pytest dependency.

The reproducible, durable command is, from the repository root:

    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /opt/homebrew/bin/python3 \\
        experiments/graph_language_repair/tests/adversarial/run_controls.py

(any interpreter that can import this repository works; nothing here is
tied to a specific one). It discovers every ``test_*.py`` file in this
directory -- so adding a new control file needs no edit here -- loads each
one as part of a throwaway package so ``from .conftest import ...`` resolves
exactly as it does under pytest, and calls every ``test_*`` function with
the two ``core`` callables (and, for files that need them, the three
``questions`` callables) that ``conftest.py``'s ``_core_interface()`` /
``_questions_interface()`` resolve. Prints ``PASS``/``FAIL``/``SKIP`` per
test and exits non-zero if anything failed.

If a pytest install becomes available for the interpreter running this
suite, prefer the normal way instead -- the same ``conftest.py`` and test
files work unchanged under it:

    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. <python-with-pytest> -m pytest \\
        experiments/graph_language_repair/tests/adversarial -q

This script exists because, at authoring time, no interpreter on this
machine had pytest installed (CONTROLS-STATUS.md). It is not a
pytest replacement; it is a durable, dependency-free way to execute the
exact same test functions against the real core/questions code in the
meantime.
"""

import importlib.util
import inspect
import pathlib
import sys
import traceback
import types

HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[3]
PACKAGE_NAME = "graph_language_repair_adversarial_controls_runner"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location("%s.%s" % (PACKAGE_NAME, name), HERE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main():
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(HERE)]
    sys.modules[PACKAGE_NAME] = package

    conftest = _load("conftest", "conftest.py")

    try:
        read_text, search_rows = conftest._core_interface()
    except conftest._DependencyUnavailable as exc:
        print("SKIP ALL: %s" % (exc,))
        return 0

    try:
        compile_question, execute_plan, render = conftest._questions_interface()
    except conftest._DependencyUnavailable as exc:
        print("questions interface unavailable, tests needing it will skip: %s" % (exc,))
        compile_question = execute_plan = render = None

    available = {
        "read_text": read_text,
        "search_rows": search_rows,
        "compile_question": compile_question,
        "execute_plan": execute_plan,
        "render": render,
    }

    test_files = sorted(p for p in HERE.glob("test_*.py"))
    if not test_files:
        print("no test_*.py files found in %s" % (HERE,))
        return 0

    total = failed = skipped = 0
    for path in test_files:
        module = _load(path.stem, path.name)
        for attr in sorted(vars(module)):
            if not attr.startswith("test_"):
                continue
            fn = getattr(module, attr)
            if not callable(fn):
                continue
            label = "%s.%s" % (path.stem, attr)
            params = list(inspect.signature(fn).parameters)
            missing = [p for p in params if available.get(p) is None]
            if missing:
                skipped += 1
                print("SKIP %s: needs unavailable fixture(s) %r" % (label, missing))
                continue
            total += 1
            args = [available[p] for p in params]
            try:
                fn(*args)
            except AssertionError as exc:
                failed += 1
                print("FAIL %s: %s" % (label, exc))
            except Exception:
                failed += 1
                print("ERROR %s:" % (label,))
                traceback.print_exc()
            else:
                print("PASS %s" % (label,))

    print()
    print("%d/%d passed, %d skipped" % (total - failed, total, skipped))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
