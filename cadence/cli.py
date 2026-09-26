"""Command-line interface for cadence."""
from __future__ import annotations

import argparse
import io
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from . import __version__
from .core import (
    CadenceError,
    Store,
    best_streak,
    current_streak,
    default_path,
    last_done,
)

CHECK = "\u2713"  # ✓
DOT = "\u00b7"    # ·
DASH = "\u2014"   # —


def _harden_streams() -> None:
    """Make stdout/stderr encoding-tolerant so exotic console code pages
    (e.g. cp1252 on Windows) degrade to '?' instead of crashing."""
    for stream in (sys.stdout, sys.stderr):
        try:
            is_tty = stream.isatty()
        except (AttributeError, ValueError):
            is_tty = False
        try:
            if is_tty:
                stream.reconfigure(encoding="utf-8", errors="replace")
            else:
                stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, io.UnsupportedOperation):
            pass


def _parse_day(value: str, flag: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise CadenceError("%s must look like YYYY-MM-DD (got %r)" % (flag, value))


def _common_parser() -> argparse.ArgumentParser:
    # SUPPRESS defaults so the option works both before and after the
    # subcommand (on Python <=3.12 a plain default in the subparser would
    # clobber a value already parsed by the main parser).
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--file", metavar="PATH", default=argparse.SUPPRESS, help="use a specific data file")
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="print JSON instead of text")
    p.add_argument("--today", metavar="YYYY-MM-DD", default=argparse.SUPPRESS, help="pretend today is this date")
    return p


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cadence",
        description="A tiny habit tracker that keeps your streaks on your machine.",
        parents=[_common_parser()],
    )
    parser.add_argument(
        "--version", action="version", version="cadence " + __version__
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    p = sub.add_parser("add", parents=[_common_parser()], help="add a habit")
    p.add_argument("names", nargs="+", help="habit name (quote multi-word names)")

    p = sub.add_parser("done", parents=[_common_parser()], help="check a habit off")
    p.add_argument("name", help="habit name")
    p.add_argument("when", nargs="?", help="date YYYY-MM-DD (default: today)")

    p = sub.add_parser("undo", parents=[_common_parser()], help="uncheck a habit")
    p.add_argument("name", help="habit name")
    p.add_argument("when", nargs="?", help="date YYYY-MM-DD (default: today)")

    sub.add_parser("ls", parents=[_common_parser()], help="list habits with streaks")
    sub.add_parser("list", parents=[_common_parser()], help=argparse.SUPPRESS)

    sub.add_parser(
        "week", parents=[_common_parser()], help="last 7 days, all habits"
    )

    p = sub.add_parser(
        "stats", parents=[_common_parser()], help="detailed stats for one habit"
    )
    p.add_argument("name", help="habit name")

    p = sub.add_parser(
        "rm", parents=[_common_parser()], help="delete a habit and its history"
    )
    p.add_argument("name", help="habit name")
    p.add_argument("--yes", action="store_true", help="skip the confirmation prompt")

    sub.add_parser(
        "path", parents=[_common_parser()], help="print the data file path"
    )

    return parser


def _sorted_habits(store: Store) -> List:
    return sorted(store.habits.values(), key=lambda h: h.name.lower())


def _row(habit, today: date) -> Dict:
    return {
        "name": habit.name,
        "streak": current_streak(habit, today),
        "best": best_streak(habit),
        "today": habit.is_done(today),
        "total": len(habit.done),
    }


def _table(headers: List[str], rows: List[List[str]]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    all_rows = [headers] + rows
    return "\n".join(
        "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip()
        for row in all_rows
    )


def _empty_message() -> str:
    return "no habits yet — add one with: cadence add <name>"


def cmd_add(args, store: Store, today: date) -> int:
    added = [store.add(name, today) for name in args.names]
    if args.json:
        print(json.dumps([{"added": h.name} for h in added]))
        return 0
    for h in added:
        print("added %r" % h.name)
    if len(added) == 1:
        print("check it off with: cadence done %s" % added[0].name)
    return 0


def cmd_done(args, store: Store, today: date) -> int:
    when = _parse_day(args.when, "when") if args.when else today
    if when > today:
        raise CadenceError("can't check off a future date (%s)" % when.isoformat())
    habit = store.find(args.name)
    habit.done.add(when.isoformat())
    store.save()
    if args.json:
        print(json.dumps({
            "habit": habit.name,
            "date": when.isoformat(),
            "streak": current_streak(habit, today),
        }))
        return 0
    print("%s: %s %s  (streak %dd)" % (
        habit.name, CHECK, when.isoformat(), current_streak(habit, today)
    ))
    return 0


def cmd_undo(args, store: Store, today: date) -> int:
    day = _parse_day(args.when, "when") if args.when else today
    habit = store.find(args.name)
    key = day.isoformat()
    if key not in habit.done:
        raise CadenceError("%r is not checked off on %s" % (habit.name, key))
    habit.done.discard(key)
    store.save()
    if args.json:
        print(json.dumps({"habit": habit.name, "undone": key}))
        return 0
    print("%s: unchecked %s" % (habit.name, key))
    return 0


def cmd_ls(args, store: Store, today: date) -> int:
    habits = _sorted_habits(store)
    if not habits and not args.json:
        print(_empty_message())
        return 0
    rows = [_row(h, today) for h in habits]
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    table_rows = [[
        r["name"],
        "%dd" % r["streak"],
        "%dd" % r["best"],
        CHECK if r["today"] else DOT,
        str(r["total"]),
    ] for r in rows]
    print(_table(["habit", "streak", "best", "today", "total"], table_rows))
    return 0


def cmd_week(args, store: Store, today: date) -> int:
    habits = _sorted_habits(store)
    if not habits and not args.json:
        print(_empty_message())
        return 0
    days = [today - timedelta(days=6 - i) for i in range(7)]
    if args.json:
        out = [
            {
                "habit": h.name,
                "streak": current_streak(h, today),
                "days": [
                    {"date": d.isoformat(), "done": h.is_done(d)} for d in days
                ],
            }
            for h in habits
        ]
        print(json.dumps(out, indent=2))
        return 0
    name_w = max(len(h.name) for h in habits)
    header_marks = " ".join(d.strftime("%a")[0] for d in days)
    print("habit".ljust(name_w + 2) + header_marks + "  streak")
    for h in habits:
        marks = " ".join(CHECK if h.is_done(d) else DOT for d in days)
        print(h.name.ljust(name_w + 2) + marks + "  %dd" % current_streak(h, today))
    return 0


def cmd_stats(args, store: Store, today: date) -> int:
    habit = store.find(args.name)
    done30 = sum(1 for i in range(30) if habit.is_done(today - timedelta(days=i)))
    ld = last_done(habit)

    def _d(n: int) -> str:
        return "%d day%s" % (n, "" if n == 1 else "s")

    if args.json:
        print(json.dumps({
            "habit": habit.name,
            "created": habit.created,
            "current_streak": current_streak(habit, today),
            "best_streak": best_streak(habit),
            "total": len(habit.done),
            "last_done": ld.isoformat() if ld else None,
            "last_30_days_done": done30,
        }, indent=2))
        return 0
    print(habit.name)
    print("  created         %s" % habit.created)
    print("  current streak  %s" % _d(current_streak(habit, today)))
    print("  best streak     %s" % _d(best_streak(habit)))
    print("  total check-ins %s" % _d(len(habit.done)))
    print("  last done       %s" % (ld.isoformat() if ld else DASH))
    print("  last 30 days    %d/30" % done30)
    return 0


def cmd_rm(args, store: Store, today: date) -> int:
    habit = store.find(args.name)
    if not args.yes:
        try:
            answer = input(
                "delete %r and its %d check-in%s? [y/N] " % (
                    habit.name,
                    len(habit.done),
                    "" if len(habit.done) == 1 else "s",
                )
            )
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("aborted")
            return 1
    store.remove(habit.name)
    if args.json:
        print(json.dumps({"removed": habit.name}))
        return 0
    print("removed %r" % habit.name)
    return 0


def cmd_path(args, store: Store, today: date) -> int:
    print(str(store.path))
    return 0


_HANDLERS = {
    "add": cmd_add,
    "done": cmd_done,
    "undo": cmd_undo,
    "ls": cmd_ls,
    "list": cmd_ls,
    "week": cmd_week,
    "stats": cmd_stats,
    "rm": cmd_rm,
    "path": cmd_path,
}


def main(argv: Optional[List[str]] = None) -> int:
    _harden_streams()
    args = build_parser().parse_args(argv)
    # Shared options use SUPPRESS defaults, so normalize them here.
    args.file = getattr(args, "file", None)
    args.json = bool(getattr(args, "json", False))
    args.today = getattr(args, "today", None)
    try:
        today = _parse_day(args.today, "--today") if args.today else date.today()
        path = Path(args.file).expanduser() if args.file else default_path()
        store = Store.load(path)
        return _HANDLERS[args.command](args, store, today)
    except CadenceError as exc:
        print("cadence: %s" % exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
