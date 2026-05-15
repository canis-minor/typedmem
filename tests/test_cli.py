from pathlib import Path

from typed_memory.cli import main


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
