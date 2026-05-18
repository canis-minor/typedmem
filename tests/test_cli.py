import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from typedmem.cli import _parse_since, main


def test_add_and_list_and_search(tmp_path: Path, capsys):
    db = tmp_path / "m.db"

    assert main(["--store", str(db), "add", "Today child said more milk", "--subject", "child"]) == 0
    captured = capsys.readouterr()
    assert "added" in captured.out

    assert main(["--store", str(db), "list", "--type", "observation"]) == 0
    listed = capsys.readouterr().out
    assert "milk" in listed

    assert main(["--store", str(db), "search", "milk", "--limit", "3"]) == 0
    found = capsys.readouterr().out
    assert "milk" in found


def test_force_type(tmp_path: Path, capsys):
    db = tmp_path / "m.db"
    assert main([
        "--store", str(db), "add", "ship v0.2", "--type", "goal", "--confidence", "0.9",
    ]) == 0
    out = capsys.readouterr().out
    assert "added 1 memory (goal)" in out


def test_jsonl_store_via_extension(tmp_path: Path, capsys):
    path = tmp_path / "m.jsonl"
    assert main(["--store", str(path), "add", "the sky is blue", "--type", "fact"]) == 0
    assert path.exists()
    assert main(["--store", str(path), "list"]) == 0
    out = capsys.readouterr().out
    assert "sky" in out


def test_compact_jsonl(tmp_path: Path, capsys):
    path = tmp_path / "m.jsonl"
    for v in ("tea", "coffee", "matcha"):
        main(["--store", str(path), "add", f"likes {v}", "--type", "preference", "--subject", "user"])
    capsys.readouterr()
    assert main(["--store", str(path), "compact"]) == 0
    assert "compacted" in capsys.readouterr().out
    assert path.read_text().count("\n") == 1


# ── v0.6.2: source tagging + timeline / changed-since CLI surface ───────────
def _added_id(out: str) -> str:
    # "added 1 memory (goal): <uuid>"
    return out.strip().rsplit(": ", 1)[-1]


def test_cli_add_tags_event_source_as_user(tmp_path: Path, capsys):
    db = tmp_path / "m.db"
    main(["--store", str(db), "add", "ship v0.6.2", "--type", "goal", "--subject", "rel"])
    mid = _added_id(capsys.readouterr().out)

    assert main(["--store", str(db), "history", mid, "--json"]) == 0
    events = json.loads(capsys.readouterr().out)
    assert len(events) == 1
    assert events[0]["source"] == "user"
    assert events[0]["source_name"] == "cli:add"
    assert events[0]["action"] == "added"


def test_cli_delete_tags_event_source_as_user(tmp_path: Path, capsys):
    db = tmp_path / "m.db"
    main(["--store", str(db), "add", "ephemeral", "--type", "fact"])
    mid = _added_id(capsys.readouterr().out)

    assert main(["--store", str(db), "delete", mid]) == 0
    capsys.readouterr()
    # History survives the deletion; the delete event is tagged source=user.
    assert main(["--store", str(db), "history", mid, "--json"]) == 0
    events = json.loads(capsys.readouterr().out)
    del_events = [e for e in events if e["action"] == "deleted"]
    assert del_events and del_events[0]["source"] == "user"
    assert del_events[0]["source_name"] == "cli:delete"


def test_cli_timeline_filters(tmp_path: Path, capsys):
    db = tmp_path / "m.db"
    main(["--store", str(db), "add", "alpha", "--type", "goal", "--subject", "x"])
    main(["--store", str(db), "add", "beta",  "--type", "fact", "--subject", "y"])
    capsys.readouterr()

    assert main(["--store", str(db), "timeline", "--type", "goal", "--json"]) == 0
    events = json.loads(capsys.readouterr().out)
    assert all(e["type"] == "goal" for e in events)
    assert len(events) == 1

    assert main(["--store", str(db), "timeline", "--subject", "y", "--json"]) == 0
    events = json.loads(capsys.readouterr().out)
    assert all(e["subject"] == "y" for e in events)


def test_cli_timeline_source_filter(tmp_path: Path, capsys):
    db = tmp_path / "m.db"
    main(["--store", str(db), "add", "alpha", "--type", "goal"])
    capsys.readouterr()
    # Every CLI add is tagged source=user, so source=evolver returns nothing.
    assert main(["--store", str(db), "timeline", "--source", "evolver", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert main(["--store", str(db), "timeline", "--source", "user", "--json"]) == 0
    events = json.loads(capsys.readouterr().out)
    assert events and all(e["source"] == "user" for e in events)


def test_cli_changed_since_relative_and_iso(tmp_path: Path, capsys):
    db = tmp_path / "m.db"
    main(["--store", str(db), "add", "first", "--type", "fact"])
    capsys.readouterr()

    # Relative spec: everything from the last hour
    assert main(["--store", str(db), "changed-since", "1h", "--json"]) == 0
    events = json.loads(capsys.readouterr().out)
    assert len(events) == 1

    # ISO spec in the far past
    assert main(["--store", str(db), "changed-since", "1970-01-01T00:00:00", "--json"]) == 0
    events = json.loads(capsys.readouterr().out)
    assert len(events) == 1


def test_cli_changed_since_bad_spec_exits_2(tmp_path: Path, capsys):
    db = tmp_path / "m.db"
    main(["--store", str(db), "add", "first", "--type", "fact"])
    capsys.readouterr()
    rc = main(["--store", str(db), "changed-since", "not a thing"])
    assert rc == 2


def test_parse_since_units():
    now = datetime.now(timezone.utc)
    five_min = _parse_since("5m")
    assert timedelta(minutes=4, seconds=58) < (now - five_min) < timedelta(minutes=5, seconds=2)
    one_day = _parse_since("1d")
    assert timedelta(hours=23, minutes=59) < (now - one_day) < timedelta(hours=24, minutes=1)
    iso = _parse_since("2026-05-17T12:00:00")
    assert iso == datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc)


def test_parse_since_rejects_garbage():
    with pytest.raises(ValueError):
        _parse_since("yesterday")
