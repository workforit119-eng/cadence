"""Data model and streak logic for cadence."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

SCHEMA_VERSION = 1

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _\-]{0,63}$")
_MAX_NAME_LEN = 64


class CadenceError(Exception):
    """User-facing error with a short, printable message."""


class HabitNotFoundError(CadenceError):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__("habit not found: %r" % name)


class DuplicateHabitError(CadenceError):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__("habit already exists: %r" % name)


def normalize_name(raw: str) -> str:
    """Trim/collapse whitespace and validate a habit name."""
    name = " ".join(raw.split())
    if not name or len(name) > _MAX_NAME_LEN or not _NAME_RE.match(name):
        raise CadenceError(
            "habit names must be 1-%d characters: letters, numbers, spaces, '-' and '_'"
            % _MAX_NAME_LEN
        )
    return name


@dataclass
class Habit:
    name: str
    created: str  # ISO date (YYYY-MM-DD)
    done: set = field(default_factory=set)  # ISO dates the habit was checked off

    def is_done(self, day: date) -> bool:
        return day.isoformat() in self.done


@dataclass
class Store:
    habits: Dict[str, Habit]
    path: Path

    @classmethod
    def load(cls, path: Path) -> "Store":
        if not path.exists():
            return cls({}, path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CadenceError("could not read data file %s: %s" % (path, exc))
        habits: Dict[str, Habit] = {}
        for name, h in data.get("habits", {}).items():
            habits[name] = Habit(
                name=name,
                created=h.get("created", ""),
                done=set(h.get("done", [])),
            )
        return cls(habits, path)

    def save(self) -> None:
        payload = {
            "version": SCHEMA_VERSION,
            "habits": {
                name: {"created": habit.created, "done": sorted(habit.done)}
                for name, habit in sorted(self.habits.items())
            },
        }
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.parent / (self.path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(self.path)

    def find(self, name: str) -> Habit:
        """Case-insensitive exact-name lookup."""
        key = name.strip().lower()
        for habit in self.habits.values():
            if habit.name.lower() == key:
                return habit
        raise HabitNotFoundError(name)

    def add(self, raw_name: str, today: date) -> Habit:
        name = normalize_name(raw_name)
        try:
            self.find(name)
        except HabitNotFoundError:
            pass
        else:
            raise DuplicateHabitError(name)
        habit = Habit(name=name, created=today.isoformat())
        self.habits[name] = habit
        self.save()
        return habit

    def remove(self, raw_name: str) -> Habit:
        habit = self.find(raw_name)
        del self.habits[habit.name]
        self.save()
        return habit


def current_streak(habit: Habit, today: date) -> int:
    """Consecutive done-days ending today (or yesterday if today is still open)."""
    day = today if habit.is_done(today) else today - timedelta(days=1)
    streak = 0
    while habit.is_done(day):
        streak += 1
        day -= timedelta(days=1)
    return streak


def best_streak(habit: Habit) -> int:
    """Longest run of consecutive done-days ever recorded."""
    if not habit.done:
        return 0
    days = sorted(date.fromisoformat(d) for d in habit.done)
    best = run = 1
    for prev, cur in zip(days, days[1:]):
        run = run + 1 if (cur - prev).days == 1 else 1
        best = max(best, run)
    return best


def last_done(habit: Habit) -> Optional[date]:
    if not habit.done:
        return None
    return max(date.fromisoformat(d) for d in habit.done)


def recent_flags(habit: Habit, today: date, n: int = 7) -> List[bool]:
    """Oldest-first completion flags for the last n days (ending today)."""
    return [habit.is_done(today - timedelta(days=n - 1 - i)) for i in range(n)]


def default_path() -> Path:
    """Where cadence keeps its data: $CADENCE_FILE, else the platform data dir."""
    env = os.environ.get("CADENCE_FILE")
    if env:
        return Path(env).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return base / "cadence" / "cadence.json"
