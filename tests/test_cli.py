import json

from cadence.cli import main


def run(capsys, tmp_path, *argv):
    code = main(["--file", str(tmp_path / "c.json"), *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


class TestAddAndList:
    def test_add_and_ls(self, capsys, tmp_path):
        code, out, err = run(capsys, tmp_path, "add", "Stretch", "Read")
        assert code == 0
        assert "'Stretch'" in out and "'Read'" in out

        code, out, err = run(capsys, tmp_path, "ls")
        assert code == 0
        assert "Read" in out and "Stretch" in out

    def test_duplicate_add_fails(self, capsys, tmp_path):
        run(capsys, tmp_path, "add", "Sleep")
        code, out, err = run(capsys, tmp_path, "add", "sleep")
        assert code == 1
        assert "already exists" in err

    def test_ls_empty(self, capsys, tmp_path):
        code, out, err = run(capsys, tmp_path, "ls")
        assert code == 0
        assert "no habits yet" in out

    def test_ls_json(self, capsys, tmp_path):
        run(capsys, tmp_path, "add", "Stretch")
        code, out, err = run(capsys, tmp_path, "ls", "--json")
        assert code == 0
        rows = json.loads(out)
        assert rows[0]["name"] == "Stretch"
        assert rows[0]["streak"] == 0


class TestDoneAndStreaks:
    def test_streak_grows_over_days(self, capsys, tmp_path):
        run(capsys, tmp_path, "add", "Stretch")
        code, out, err = run(capsys, tmp_path, "--today", "2026-09-25", "done", "Stretch", "2026-09-23")
        assert code == 0
        code, out, err = run(capsys, tmp_path, "--today", "2026-09-26", "done", "Stretch", "2026-09-24")
        assert code == 0
        code, out, err = run(capsys, tmp_path, "--today", "2026-09-26", "done", "Stretch", "2026-09-25")
        assert code == 0
        assert "streak 3d" in out

    def test_future_date_rejected(self, capsys, tmp_path):
        run(capsys, tmp_path, "add", "Stretch")
        code, out, err = run(capsys, tmp_path, "--today", "2026-09-26", "done", "Stretch", "2026-09-27")
        assert code == 1
        assert "future date" in err

    def test_bad_date_rejected(self, capsys, tmp_path):
        run(capsys, tmp_path, "add", "Stretch")
        code, out, err = run(capsys, tmp_path, "done", "Stretch", "yesterday")
        assert code == 1
        assert "YYYY-MM-DD" in err

    def test_done_unknown_habit(self, capsys, tmp_path):
        code, out, err = run(capsys, tmp_path, "done", "Ghost")
        assert code == 1
        assert "not found" in err

    def test_undo_roundtrip(self, capsys, tmp_path):
        run(capsys, tmp_path, "add", "Stretch")
        run(capsys, tmp_path, "--today", "2026-09-26", "done", "Stretch")
        code, out, err = run(capsys, tmp_path, "--today", "2026-09-26", "undo", "Stretch")
        assert code == 0
        assert "unchecked" in out

        code, out, err = run(capsys, tmp_path, "--today", "2026-09-26", "undo", "Stretch")
        assert code == 1
        assert "not checked off" in err

    def test_done_json(self, capsys, tmp_path):
        run(capsys, tmp_path, "add", "Stretch")
        code, out, err = run(capsys, tmp_path, "--today", "2026-09-26", "done", "Stretch", "--json")
        assert code == 0
        data = json.loads(out)
        assert data["habit"] == "Stretch"
        assert data["streak"] == 1


class TestWeekStatsRm:
    def test_week_shows_marks(self, capsys, tmp_path):
        run(capsys, tmp_path, "add", "Stretch")
        run(capsys, tmp_path, "--today", "2026-09-26", "done", "Stretch", "2026-09-25")
        code, out, err = run(capsys, tmp_path, "--today", "2026-09-26", "week")
        assert code == 0
        assert "Stretch" in out
        assert "\u2713" in out and "\u00b7" in out

    def test_stats(self, capsys, tmp_path):
        run(capsys, tmp_path, "add", "Stretch")
        run(capsys, tmp_path, "--today", "2026-09-26", "done", "Stretch", "2026-09-24")
        run(capsys, tmp_path, "--today", "2026-09-26", "done", "Stretch", "2026-09-25")
        code, out, err = run(capsys, tmp_path, "--today", "2026-09-26", "stats", "Stretch")
        assert code == 0
        assert "current streak  2 days" in out
        assert "total check-ins 2 days" in out
        assert "last done       2026-09-25" in out

    def test_stats_json(self, capsys, tmp_path):
        run(capsys, tmp_path, "add", "Stretch")
        code, out, err = run(capsys, tmp_path, "--today", "2026-09-26", "stats", "Stretch", "--json")
        assert code == 0
        data = json.loads(out)
        assert data["habit"] == "Stretch"
        assert data["last_done"] is None

    def test_rm_with_yes(self, capsys, tmp_path):
        run(capsys, tmp_path, "add", "Stretch")
        code, out, err = run(capsys, tmp_path, "rm", "Stretch", "--yes")
        assert code == 0
        code, out, err = run(capsys, tmp_path, "ls", "--json")
        assert json.loads(out) == []

    def test_rm_declined(self, capsys, tmp_path, monkeypatch):
        run(capsys, tmp_path, "add", "Stretch")
        monkeypatch.setattr("builtins.input", lambda *a: "n")
        code, out, err = run(capsys, tmp_path, "rm", "Stretch")
        assert code == 1
        assert "aborted" in out

    def test_path_command(self, capsys, tmp_path):
        code, out, err = run(capsys, tmp_path, "path")
        assert code == 0
        assert out.strip().endswith("c.json")


class TestVersionAndHelp:
    def test_version(self, capsys):
        import pytest

        with pytest.raises(SystemExit) as excinfo:
            main(["--version"])
        assert excinfo.value.code == 0

    def test_no_command_fails(self, capsys, tmp_path):
        import pytest

        with pytest.raises(SystemExit) as excinfo:
            main(["--file", str(tmp_path / "c.json")])
        assert excinfo.value.code == 2


class TestEncodingResilience:
    def test_cp1252_stdout_does_not_crash(self, tmp_path, monkeypatch):
        import io
        import sys

        code = main(["--file", str(tmp_path / "c.json"), "add", "Stretch"])
        assert code == 0

        buf = io.BytesIO()
        fake_out = io.TextIOWrapper(buf, encoding="cp1252", errors="strict")
        monkeypatch.setattr(sys, "stdout", fake_out)
        code = main(["--file", str(tmp_path / "c.json"), "--today", "2026-09-26", "done", "Stretch"])
        fake_out.flush()
        assert code == 0
        # must be valid cp1252 bytes (no UnicodeEncodeError, no mojibake)
        buf.getvalue().decode("cp1252")
