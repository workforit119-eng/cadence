import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from cadence.core import (
    CadenceError,
    DuplicateHabitError,
    Habit,
    HabitNotFoundError,
    Store,
    best_streak,
    current_streak,
    last_done,
    recent_flags,
)

T = date(2026, 9, 26)


def make_habit(days_ago):
    done = {(T - timedelta(days=d)).isoformat() for d in days_ago}
    return Habit(name="test", created=T.isoformat(), done=done)


class TestNames:
    def test_normalize_collapses_whitespace(self):
        assert normalize_name_helper("  stretch   legs ") == "stretch legs"

    @pytest.mark.parametrize(
        "bad", ["", "   ", "x" * 100, "has/slash", "émoji", "-leading-dash", "_under"]
    )
    def test_rejects_bad_names(self, bad):
        from cadence.core import normalize_name

        with pytest.raises(CadenceError):
            normalize_name(bad)

    def test_accepts_ok_names(self):
        from cadence.core import normalize_name

        assert normalize_name("a") == "a"
        assert normalize_name("Read 30 books") == "Read 30 books"
        assert normalize_name("day-one") == "day-one"
        assert normalize_name("day_one") == "day_one"


def normalize_name_helper(raw):
    from cadence.core import normalize_name

    return normalize_name(raw)


class TestCurrentStreak:
    def test_empty(self):
        assert current_streak(make_habit([]), T) == 0

    def test_includes_today(self):
        assert current_streak(make_habit({0, 1, 2}), T) == 3

    def test_today_still_open_counts_from_yesterday(self):
        assert current_streak(make_habit({1, 2}), T) == 2

    def test_gap_breaks_streak(self):
        assert current_streak(make_habit({2, 3, 4}), T) == 0

    def test_open_day_after_run_keeps_it(self):
        # yesterday + older days done, today still open: streak survives
        assert current_streak(make_habit({1, 3, 4}), T) == 1

    def test_single_day_today(self):
        assert current_streak(make_habit({0}), T) == 1


class TestBestStreak:
    def test_empty(self):
        assert best_streak(make_habit([])) == 0

    def test_single_day(self):
        assert best_streak(make_habit({5})) == 1

    def test_picks_longest_run(self):
        assert best_streak(make_habit({0, 1, 2, 10, 11})) == 3

    def test_non_adjacent(self):
        assert best_streak(make_habit({0, 2, 4})) == 1


class TestLastDone:
    def test_none(self):
        assert last_done(make_habit([])) is None

    def test_max(self):
        assert last_done(make_habit({9, 2, 4})) == T - timedelta(days=2)


class TestRecentFlags:
    def test_order_is_oldest_first(self):
        h = make_habit({0, 1, 2})
        assert recent_flags(h, T, 5) == [False, False, True, True, True]


class TestStore:
    def test_roundtrip(self, tmp_path):
        path = tmp_path / "d.json"
        store = Store.load(path)
        habit = store.add("Read books", T)
        habit.done.add((T - timedelta(days=1)).isoformat())
        store.save()

        loaded = Store.load(path)
        found = loaded.find("read books")
        assert found.name == "Read books"
        assert len(found.done) == 1
        assert (T - timedelta(days=1)).isoformat() in found.done

    def test_duplicate_rejected(self, tmp_path):
        store = Store.load(tmp_path / "d.json")
        store.add("Sleep", T)
        with pytest.raises(DuplicateHabitError):
            store.add("sleep", T)

    def test_find_missing(self, tmp_path):
        store = Store.load(tmp_path / "d.json")
        with pytest.raises(HabitNotFoundError):
            store.find("nope")

    def test_remove(self, tmp_path):
        store = Store.load(tmp_path / "d.json")
        store.add("Meditate", T)
        store.remove("meditate")
        with pytest.raises(HabitNotFoundError):
            store.find("meditate")

    def test_corrupt_file_raises(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not json", encoding="utf-8")
        with pytest.raises(CadenceError):
            Store.load(path)

    def test_saved_file_is_plain_json(self, tmp_path):
        path = tmp_path / "d.json"
        store = Store.load(path)
        store.add("Stretch", T)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["version"] == 1
        assert "Stretch" in data["habits"]
