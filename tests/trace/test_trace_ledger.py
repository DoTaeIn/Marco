"""L1.2: the append-only ledger: ids, the DAG rule, corrections, state changes, a truncated line."""
import json

import pytest

from marco.trace import ledger as ledger_module
from marco.trace.ledger import Ledger, LedgerError, from_env, read
from marco.trace.schema import SchemaError

RT = {"build": "test", "pack": None}


def _input(book, trace=None):
    return book.append("input_received", trace or book.new_trace_id(), epistemic_status="reported",
                       payload={"text": "x", "sha256": "0"}, runtime=RT)


def _child(book, parents, kind="rule_applied", **fields):
    fields.setdefault("payload", {"operator": "op"})
    return book.append(kind, book.new_trace_id(), parent_ids=parents, runtime=RT, **fields)


def _lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_default_directory_is_logs_and_the_environment_overrides(tmp_path, monkeypatch):
    monkeypatch.delenv("MARCO_TRACE_DIR", raising=False)
    assert Ledger(name="x").path == ledger_module.ROOT / "logs" / "x.jsonl"
    assert from_env() is None                       # recording is off unless named
    monkeypatch.setenv("MARCO_TRACE_DIR", str(tmp_path))
    assert Ledger(name="x").path == tmp_path / "x.jsonl"
    assert from_env("y").path == tmp_path / "y.jsonl"
    assert not (tmp_path / "y.jsonl").exists()      # nothing is written before the first event


def test_the_default_file_is_named_by_date(tmp_path):
    assert Ledger(tmp_path).path.name.endswith(".jsonl") and Ledger(tmp_path).path.name[:4].isdigit()


def test_one_event_per_line_and_every_line_validates(tmp_path):
    book = Ledger(tmp_path, "one")
    first = _input(book)
    _child(book, [first["event_id"]])
    rows = _lines(book.path)
    assert [r["event_id"] for r in rows] == [e["event_id"] for e in book.events]
    assert rows[0]["schema"] == "marco-event-v1" and rows[1]["parent_ids"] == [first["event_id"]]


def test_ids_are_unique_within_a_process():
    ids = [ledger_module.new_id("evt_") for _ in range(20000)]
    assert len(set(ids)) == len(ids)
    assert all(i.startswith("evt_") and len(i) == 30 for i in ids)
    assert ledger_module.new_id("trace_").startswith("trace_")


def test_ids_are_unique_across_appends_to_the_same_file(tmp_path):
    a = Ledger(tmp_path, "shared")
    for _ in range(30):
        _input(a)
    a.close()
    b = Ledger(tmp_path, "shared")                  # another writer, later
    assert len(b.events) == 30
    earlier = b.events[0]["event_id"]
    for _ in range(30):
        _child(b, [earlier])                        # may rest on an event another writer wrote
    events, problems = read(b.path)
    assert len(events) == 60 and problems == []
    assert len({e["event_id"] for e in events}) == 60


def test_an_id_the_ledger_already_holds_is_refused(tmp_path):
    book = Ledger(tmp_path, "dup")
    first = _input(book)
    with pytest.raises(LedgerError, match="duplicate"):
        book.append("input_received", book.new_trace_id(), event_id=first["event_id"],
                    payload={"text": "x", "sha256": "0"}, runtime=RT)


def test_a_parent_must_be_an_earlier_event_of_the_same_ledger(tmp_path):
    book = Ledger(tmp_path, "dag")
    other = Ledger(tmp_path, "elsewhere")
    foreign = _input(other)
    _input(book)
    size = book.path.stat().st_size
    with pytest.raises(LedgerError) as caught:
        _child(book, [foreign["event_id"]])
    assert caught.value.field == "parent_ids"
    assert book.path.stat().st_size == size         # nothing was written


def test_a_cycle_attempt_is_refused_on_append(tmp_path):
    book = Ledger(tmp_path, "cycle")
    root = _input(book)
    planned_b, planned_c = book.new_event_id(), book.new_event_id()
    # b -> c -> b: b names c before c exists, so b is refused and the cycle never closes
    with pytest.raises(LedgerError, match="not an earlier event"):
        _child(book, [root["event_id"], planned_c], event_id=planned_b)
    c = _child(book, [root["event_id"]], event_id=planned_c)
    b = _child(book, [c["event_id"]], event_id=planned_b)
    assert [e["event_id"] for e in book.events] == [root["event_id"], planned_c, planned_b]
    with pytest.raises(SchemaError):                # its own parent
        _child(book, [b["event_id"], "evt_SELF"], event_id="evt_SELF")


def test_a_cycle_or_a_forward_reference_in_a_file_is_refused_on_read(tmp_path):
    book = Ledger(tmp_path, "cycle-file")
    root = _input(book)
    a = _child(book, [root["event_id"]])
    b = _child(book, [a["event_id"]])
    rows = _lines(book.path)
    rows[1]["parent_ids"] = [b["event_id"]]         # a <- b <- a
    forged = tmp_path / "forged.jsonl"
    forged.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    with pytest.raises(LedgerError) as caught:
        read(forged)
    assert caught.value.line == 2 and caught.value.field == "parent_ids"
    with pytest.raises(LedgerError):
        Ledger(tmp_path, "forged")
    rows = _lines(book.path)
    rows.append(rows[1])                            # the same event twice
    doubled = tmp_path / "doubled.jsonl"
    doubled.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    with pytest.raises(LedgerError, match="duplicate"):
        read(doubled)


def test_a_correction_is_a_new_event_and_a_withdrawal_never_an_edit(tmp_path):
    book = Ledger(tmp_path, "correct")
    root = _input(book)
    old = book.state_changed(book.new_trace_id(), "Minsu apples", "count", 5, 3, root["event_id"], runtime=RT)
    before = book.path.read_bytes()
    fix = _input(book)
    new, gone = book.correct(old["event_id"], "state_changed", fix["trace_id"], parent_ids=[fix["event_id"]],
                             subject="Minsu apples", runtime=RT,
                             payload={"field": "count", "before": 5, "after": 4, "cause": fix["event_id"]})
    assert book.path.read_bytes().startswith(before)            # history untouched
    assert new["supersedes"] == old["event_id"]
    assert gone["kind"] == "conclusion_withdrawn" and gone["payload"]["withdrawn"] == old["event_id"]
    assert gone["payload"]["superseded_by"] == new["event_id"] and gone["parent_ids"] == [new["event_id"]]
    assert gone["epistemic_status"] == "withdrawn"
    assert book.is_withdrawn(old["event_id"]) and not book.is_withdrawn(new["event_id"])
    assert not book.is_withdrawn(old["event_id"], before=book.position(gone["event_id"]))
    with pytest.raises(LedgerError, match="already superseded"):
        book.append("state_changed", fix["trace_id"], supersedes=old["event_id"], parent_ids=[fix["event_id"]],
                    runtime=RT, payload={"field": "count", "before": 5, "after": 2, "cause": fix["event_id"]})
    with pytest.raises(LedgerError, match="already withdrawn"):
        book.withdraw(old["event_id"], fix["trace_id"], parent_ids=[fix["event_id"]], reason="again", runtime=RT)
    events, _ = read(book.path)
    assert [e["kind"] for e in events][-2:] == ["state_changed", "conclusion_withdrawn"]


def test_a_state_change_carries_before_after_and_a_cause_that_exists(tmp_path):
    book = Ledger(tmp_path, "state")
    root = _input(book)
    event = book.state_changed(root["trace_id"], "Jiyeon apples", "count", 2, 4, root["event_id"], runtime=RT)
    assert {k: event["payload"][k] for k in ("before", "after", "cause")} == {
        "before": 2, "after": 4, "cause": root["event_id"]}
    assert event["parent_ids"] == [root["event_id"]]
    with pytest.raises(SchemaError) as caught:
        book.append("state_changed", root["trace_id"], parent_ids=[root["event_id"]], runtime=RT,
                    payload={"field": "count", "before": 2, "after": 4})
    assert caught.value.field == "payload.cause"
    with pytest.raises(LedgerError) as caught:
        book.append("state_changed", root["trace_id"], parent_ids=[root["event_id"]], runtime=RT,
                    payload={"field": "count", "before": 2, "after": 4, "cause": "evt_NOWHERE"})
    assert caught.value.field == "payload.cause"


def test_the_reader_tolerates_a_truncated_last_line_and_reports_it(tmp_path):
    book = Ledger(tmp_path, "cut")
    root = _input(book)
    for _ in range(2):
        _child(book, [root["event_id"]])
    book.close()
    whole = book.path.read_bytes()
    line = (json.dumps(_lines(book.path)[1]) + "\n").encode()
    book.path.write_bytes(whole + line[: len(line) // 2])      # a writer died mid-line
    events, problems = read(book.path)
    assert len(events) == 3
    assert [p["problem"] for p in problems] == ["truncated_last_line"] and problems[0]["line"] == 4

    again = Ledger(tmp_path, "cut")                             # the next writer
    assert [p["problem"] for p in again.problems] == ["truncated_last_line"]
    after = _child(again, [root["event_id"]])
    events, problems = read(again.path)
    kinds = [e["kind"] for e in events]
    assert kinds == ["input_received", "rule_applied", "rule_applied", "error", "rule_applied"]
    declared = events[3]
    assert declared["payload"]["problem"] == "truncated_line" and declared["payload"]["line"] == 4
    assert events[-1]["event_id"] == after["event_id"]
    assert [p["problem"] for p in problems] == ["truncated_line_declared"]
    assert again.path.read_bytes().startswith(whole + line[: len(line) // 2] + b"\n")   # nothing rewritten


def test_an_unreadable_line_elsewhere_is_an_error(tmp_path):
    book = Ledger(tmp_path, "bad")
    root = _input(book)
    _child(book, [root["event_id"]])
    book.close()
    rows = book.path.read_bytes().split(b"\n")
    book.path.write_bytes(rows[0] + b"\n{not json\n" + rows[1] + b"\n")
    with pytest.raises(LedgerError) as caught:
        read(book.path)
    assert caught.value.line == 2


def test_an_unterminated_complete_last_line_is_kept_and_ended_by_the_next_writer(tmp_path):
    book = Ledger(tmp_path, "open")
    root = _input(book)
    book.close()
    book.path.write_bytes(book.path.read_bytes().rstrip(b"\n"))
    events, problems = read(book.path)
    assert len(events) == 1 and problems[0]["problem"] == "unterminated_last_line"
    again = Ledger(tmp_path, "open")
    _child(again, [root["event_id"]])
    events, problems = read(again.path)
    assert len(events) == 2 and problems == []
