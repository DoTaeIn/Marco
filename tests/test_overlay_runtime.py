"""Applying an attached overlay in the running path (views/kgpack_ui.py, pack_model.py).

A small model is built from a temporary source tree: one graph, the Korean
language pack and the axioms of this checkout. ``build_model`` is shared with
tests/test_overlay_application.py.
"""
from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from marco.storage import overlay as ov
from marco.storage.graph_view import GraphView, OverlayAttachment, PackBase, pack_content_sha256

pytestmark = pytest.mark.language("한국어")

ROOT = Path(__file__).resolve().parents[1]
G = "graphs/graph_화분.kg"
LANGUAGE = "styles/한국어.json"
GRAPH = """# 화분 돌보기: 흙이 말랐는지 확인되면 물을 준다.
역할: 화분 돌보기
목표: 물을준다
[개념]
물을준다: "화분에 물을 줘야 해" | "물을 줄 때다"
흙이말랐다: "흙이 말랐다" | "흙이 바싹 말랐다"
[사례]
*손가락확인: "손가락으로 흙을 눌러 봤더니 말랐어" | "손가락으로 흙을 만져 봤어"
*잎시듦: "잎이 축 처졌어" | "잎이 시들었어"
[논증]
손가락확인 -증명-> 흙이말랐다
흙이말랐다 -충족-> 물을준다
[대사]
B2: 그건 화분과 상관이 없습니다.
B2_강등: 흙 상태만 봅니다.
A: 혹시 {claim} 말씀인가요?
근거없음: {claim} 는 알겠는데, 흙을 확인했는지 말씀해 주세요.
인정: {ev} 니까 {claim}.
인정_반격: {ev} 는 맞는데 {bad} 가 걸립니다.
C: {ev} 만으로는 {claim} 까지 안 됩니다.
B1: {claim} 은 알겠습니다. 흙을 확인해 주세요.
"""
WHO = dict(actor="tester", source="test", reason="an explicit test change", approved_by="owner")
SESSION = "session_overlay_1"


def build_source(root: Path) -> Path:
    """A source tree with one graph, the Korean language pack and this checkout's axioms."""
    for folder in ("graphs", "styles", "axioms"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / LANGUAGE, root / "styles")
    shutil.copy(ROOT / "axioms" / "core.json", root / "axioms")
    (root / G).write_text(GRAPH, encoding="utf-8")
    return root


def build_model(tmp: Path) -> Path:
    """The small model as a .kgpack."""
    import marco.storage.kgpack as kgpack
    root = build_source(tmp / "src")
    pack = tmp / "model.kgpack"
    kgpack.write_pack(pack, kgpack.default_file(root), root, language=LANGUAGE)
    return pack


def base_of(pack: Path):
    import marco.storage.kgpack as kgpack
    manifest, data = kgpack.read(pack)
    return manifest, data, PackBase(manifest, data), pack_content_sha256(manifest)


def checked(base):
    return lambda store: GraphView(base, store).check()


def answer(app, text, session=SESSION):
    payload = app.turn(text, session)
    a = payload.get("answer") or {}
    return a.get("answer"), (a.get("trace") or {})


def files_of(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


@pytest.fixture
def model(tmp_path):
    pack = build_model(tmp_path)
    manifest, data, base, sha = base_of(pack)
    store = ov.OverlayStore.create(tmp_path / "model.overlay", base_sha256=sha, base_build_id="b-1",
                                   format_version="kgpack")
    yield {"pack": pack, "base": base, "sha": sha, "store": store, "data": data, "tmp": tmp_path}
    store.close()


def app_with(model, overlay=True, folder="work"):
    from views.kgpack_ui import AppState
    attachment = OverlayAttachment(model["tmp"] / "model.overlay", base_sha256=model["sha"]) if overlay else None
    return AppState(model["pack"], overlay_root=model["tmp"] / folder, graph_overlay=attachment)


QUESTIONS = ["손가락으로 흙을 눌러 봤더니 말랐어", "잎이 축 처졌어", "서우는 도아보다 키가 크다. 도아는 라온보다 키가 크다.",
             "서우와 라온 중 누가 더 커?", "오늘 날씨 어때"]


def test_without_an_overlay_nothing_of_it_runs(model, monkeypatch):
    from views.kgpack_ui import AppState

    def never(*_a, **_k):
        raise AssertionError("an overlay code path ran without an overlay")
    monkeypatch.setattr(AppState, "_sync_graph_overlay", never)
    monkeypatch.setattr(AppState, "_overlay_origins", never)
    monkeypatch.setattr(AppState, "_saved_reasoning_state", never)
    app = app_with(model, overlay=False)
    for text in QUESTIONS:
        answer(app, text)
    assert app.graph_overlay is None and app._graph_texts == {}
    for name, body in files_of(app.overlay).items():
        if name.endswith(".kg"):
            assert body == model["data"][name]


def test_an_overlay_with_no_changes_writes_the_same_bytes_and_answers_the_same(model):
    plain, attached = app_with(model, overlay=False, folder="a"), app_with(model, overlay=True, folder="b")
    for text in QUESTIONS:
        assert answer(plain, text) == answer(attached, text)
    assert files_of(plain.overlay).keys() == files_of(attached.overlay).keys()
    assert {k: v for k, v in files_of(plain.overlay).items() if not k.startswith(".")} == \
        {k: v for k, v in files_of(attached.overlay).items() if not k.startswith(".")}
    assert attached._graph_texts == {}
    assert plain.overlay != attached.overlay      # an attached overlay gets its own working folder


def test_a_commit_rewrites_the_graph_file_at_the_next_turn_and_undo_restores_the_pack_bytes(model):
    store, base = model["store"], model["base"]
    app = app_with(model)
    answer(app, "잎이 축 처졌어")
    file = app.overlay / G
    assert file.read_bytes() == model["data"][G]
    seq, change = store.commit([ov.add_edge(G, "잎시듦", "증명", "흙이말랐다", revision=0)], check=checked(base), **WHO)
    assert file.read_bytes() == model["data"][G]           # nothing moves until the next turn
    text, trace = answer(app, "잎이 축 처졌어")
    assert file.read_bytes() == GraphView(base, store).text(G).encode()
    assert trace["origins"]["edges"][0][:3] == ["잎시듦", "증명", "흙이말랐다"]
    assert trace["origins"]["edges"][0][3]["change_id"] == change
    store.undo(seq, **WHO)
    answer(app, "잎이 축 처졌어")
    assert file.read_bytes() == model["data"][G] and app._graph_texts == {}


def test_graph_selection_sees_an_added_node(model):
    store, base = model["store"], model["base"]
    app = app_with(model)
    _, before = answer(app, "화분 분갈이")
    assert before["route"]["selected"] is None and before["route"]["candidates"][0][1] < 0.45
    store.commit([ov.add_node(G, "분갈이", revision=0, data={"layer": "사례", "examples": ["분갈이 해야 하나",
                                                                                      "화분 분갈이"]}),
                  ov.add_edge(G, "분갈이", "증명", "흙이말랐다", revision=0)], check=checked(base), **WHO)
    text, after = answer(app, "화분 분갈이")
    assert after["route"]["selected"] == G and after["verdict"] == "인정" and "분갈이" in text
    assert any(entry["path"] == G and "분갈이" in entry["examples"] for entry in app.manager["nodes"])
    assert after["origins"]["nodes"].get("분갈이", {}).get("kind") == "overlay"


def test_open_contexts_are_rederived_only_when_the_overlay_moves(model):
    store, base = model["store"], model["base"]
    app = app_with(model)
    answer(app, "서우는 도아보다 키가 크다. 도아는 라온보다 키가 크다.")
    context = app.reasoning_contexts[SESSION]
    answer(app, "서우와 라온 중 누가 더 커?")
    assert app.reasoning_contexts[SESSION] is context
    store.commit([ov.add_edge(G, "잎시듦", "증명", "흙이말랐다", revision=0)], check=checked(base), **WHO)
    assert answer(app, "서우와 라온 중 누가 더 커?")[0] == "서우입니다."
    fresh = app.reasoning_contexts[SESSION]
    assert fresh is not context and fresh.observations == context.observations


def test_a_saved_replay_is_kept_without_changes_and_dropped_with_them(model):
    app = app_with(model)
    saved = {"schema": "reasoning-context-v10", "observations": ["x"], "replay": {"facts": []}}
    assert app._saved_reasoning_state(saved) is saved
    model["store"].commit([ov.add_edge(G, "잎시듦", "증명", "흙이말랐다", revision=0)], **WHO)
    answer(app, "잎이 축 처졌어")
    assert "replay" not in app._saved_reasoning_state(saved) and "replay" in saved


def test_an_overlay_for_another_base_is_refused(model, tmp_path):
    from views.kgpack_ui import AppState
    other = tmp_path / "other.overlay"
    ov.OverlayStore.create(other, base_sha256="ef" * 32, base_build_id="x", format_version="kgpack").close()
    attachment = OverlayAttachment(other, base_sha256="ef" * 32)
    with pytest.raises(ov.OverlayBaseMismatch):
        AppState(model["pack"], overlay_root=tmp_path / "w", graph_overlay=attachment)
    with pytest.raises(ov.OverlayBaseMismatch):
        OverlayAttachment(other, base_sha256=model["sha"])


def test_export_with_an_attached_overlay_is_refused(model, tmp_path):
    app = app_with(model)
    with pytest.raises(ValueError, match="overlay"):
        app.export_pack(tmp_path / "out.kgpack")
    assert not (tmp_path / "out.kgpack").exists()
