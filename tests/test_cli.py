import json

from ar_llm_eval.cli import main


def test_validate_and_list(capsys):
    assert main(["validate"]) == 0
    assert "0 reference failures" in capsys.readouterr().out
    assert main(["list"]) == 0
    assert "dialect_writing" in capsys.readouterr().out


def test_run_and_board(tmp_path, capsys):
    assert main(["run", "--model", "mock:oracle", "--out", str(tmp_path / "r"), "-q", "--dialect", "gulf"]) == 0
    out = capsys.readouterr().out
    assert "DEMO" in out and "overall 100.0" in out
    data = json.loads(next((tmp_path / "r").glob("*.json")).read_text(encoding="utf-8"))
    assert set(data["summary"]["dialects"]) == {"gulf"}
    assert main(["board", str(tmp_path / "r"), "--out", str(tmp_path / "b.html")]) == 0
    assert (tmp_path / "b.html").read_text(encoding="utf-8").startswith("<!doctype html>")


def test_demo(tmp_path):
    assert main(["demo", "--out", str(tmp_path)]) == 0
    assert (tmp_path / "leaderboard.html").exists()
    assert len(list((tmp_path / "results").glob("*.json"))) == 6


def test_grade(capsys):
    assert main(["grade", "uae-001", "سبع إمارات"]) == 0
    assert json.loads(capsys.readouterr().out)["score"] == 1


def test_bad_model_returns_2(capsys):
    assert main(["run", "--model", "nope"]) == 2
