# -*- coding: utf-8 -*-
"""pytest 가 tests/ 밑에서도 루트 모듈을 찾게 한다.

이 저장소의 모듈은 평평하다 — `import engine` 처럼 부른다. 시험을 tests/ 로
옮기면 pytest 가 tests/ 만 경로에 넣어서 그 부름이 전부 깨진다. 이 파일이
루트에 있으면 pytest 가 루트를 경로에 올린다.

파일을 폴더로 나누면서 부름을 하나도 안 고치려고 이 자리를 쓴다. 모듈을
패키지로 바꾸는 것은 부름 47곳을 다 손대는 일이라 따로 할 일이다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


import pytest

# What the engine writes while it runs goes to a folder of this run, so a run on this machine
# never changes what a test reads. Set before any test imports the engine.
import tempfile
os.environ.setdefault("MARCO_STATE_DIR", tempfile.mkdtemp(prefix="marco-state-"))


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "language(name): run this test with that language pack selected, "
                   "exactly as NAI_LANGUAGE=<name> selects it outside tests")


@pytest.fixture(autouse=True)
def _selected_language(request, monkeypatch):
    """A test of one language's behaviour names that language.

    The default pack is whatever ``default_model_language`` declares; a test
    written in Korean must not depend on Korean happening to be the default.
    """
    marker = request.node.get_closest_marker("language")
    if marker is not None:
        monkeypatch.setenv("NAI_LANGUAGE", marker.args[0])
    yield
