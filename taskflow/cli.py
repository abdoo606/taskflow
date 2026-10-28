"""Command line interface. Thin adapter: parse -> call store -> render."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from .models import Priority, Status, Task
from .store import TaskStore, default_db_path

BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"
RED, YELLOW, GREEN = "\033[31m", "\033[33m", "\033[32m"
ICONS = {Status.TODO: "[ ]", Status.DOING: "[~]", Status.DONE: "[x]"}


def _human_due(due: str | None) -> str:
    """Render a due date as a short, human-friendly label."""
    if not due:
        return "-"
    try:
        target = datetime.strptime(due, "%Y-%m-%d").date()
    except ValueError:
        return due
    delta = (target - date.today()).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    if delta == -1:
        return "yesterday"
    if delta < 0:
        return f"{-delta}d late"
    return f"in {delta}d"


def _colorize(task: Task) -> str:
    if task.is_overdue:
        return RED
    if task.priority is Priority.HIGH:
        return YELLOW
    if task.status is Status.DONE:
        return GREEN
    return ""


def render_table(tasks: list[Task], *, use_color: bool = True) -> str:
    if not tasks:
        return "no tasks - add one with: taskflow add \"my task\""
    widths = (4, 7, 9, 40, 12, 12)
    header = ("ID", "STATUS", "PRIORITY", "TITLE", "DUE", "TAGS")
    lines = [DIM + "  ".join(h.ljust(w) for h, w in zip(header, widths)) + RESET]
    for t in tasks:
        cells = (
            str(t.id),
            ICONS[t.status],
            t.priority.value,
            t.title[:40],
            _human_due(t.due),
            ",".join(t.tags)[:12],
        )
        row = "  ".join(c.ljust(w) for c, w in zip(cells, widths))
        color = _colorize(t) if use_color else ""
        lines.append(f"{color}{row}{RESET if color else ''}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="taskflow", description="A tiny CLI task manager.")
    p.add_argument("--db", default=str(default_db_path()), help="path to the sqlite database")
    p.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("add", help="create a task")
    a.add_argument("title")
    a.add_argument("-p", "--priority", default="medium", choices=[x.value for x in Priority])
    a.add_argument("-t", "--tag", action="append", default=[])
    a.add_argument("-d", "--due", help="due date (YYYY-MM-DD) or +N for N days from today")

    ls = sub.add_parser("list", help="list tasks")
    ls.add_argument("-s", "--status", choices=[x.value for x in Status])
    ls.add_argument("-t", "--tag")
    ls.add_argument("-q", "--search")
    ls.add_argument("--overdue", action="store_true")
    ls.add_argument("--json", action="store_true")

    d = sub.add_parser("done", help="mark a task as done")
    d.add_argument("id", type=int)
    s = sub.add_parser("start", help="mark a task as in progress")
    s.add_argument("id", type=int)
    r = sub.add_parser("rm", help="delete a task")
    r.add_argument("id", type=int)

    sub.add_parser("stats", help="show a summary")

    e = sub.add_parser("export", help="export tasks")
    e.add_argument("--format", choices=["json", "csv"], default="json")
    e.add_argument("-o", "--output")
    return p


def _parse_due(raw: str | None) -> str | None:
    if not raw:
        return None
    if raw.startswith("+"):
        days = int(raw[1:])
        return (date.today() + timedelta(days=days)).isoformat()
    return datetime.strptime(raw, "%Y-%m-%d").date().isoformat()


def run(argv: list[str] | None = None, store_factory=TaskStore) -> int:
    args = build_parser().parse_args(argv)
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)

    with store_factory(args.db) as store:
        if args.command == "add":
            try:
                task = Task(
                    title=args.title,
                    priority=Priority.parse(args.priority),
                    tags=tuple(dict.fromkeys(args.tag)),
                    due=_parse_due(args.due),
                )
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            store.add(task)
            print(f"added #{task.id}: {task.title}")

        elif args.command == "list":
            tasks = (
                store.overdue()
                if args.overdue
                else store.list(
                    status=Status(args.status) if args.status else None,
                    tag=args.tag,
                    search=args.search,
                )
            )
            if args.json:
                print(json.dumps([t.to_dict() for t in tasks], default=str, indent=2))
            else:
                print(render_table(tasks, use_color=not args.no_color and sys.stdout.isatty()))

        elif args.command in {"done", "start"}:
            status = Status.DONE if args.command == "done" else Status.DOING
            if store.update_status(args.id, status):
                print(f"task #{args.id} -> {status.value}")
            else:
                print(f"error: no task with id {args.id}", file=sys.stderr)
                return 1

        elif args.command == "rm":
            if store.delete(args.id):
                print(f"deleted #{args.id}")
            else:
                print(f"error: no task with id {args.id}", file=sys.stderr)
                return 1

        elif args.command == "stats":
            counts = store.counts_by_status()
            total = sum(counts.values())
            done = counts.get("done", 0)
            pct = (done / total * 100) if total else 0.0
            print(f"total    : {total}")
            for st in Status:
                print(f"{st.value:<9}: {counts.get(st.value, 0)}")
            print(f"overdue  : {len(store.overdue())}")
            print(f"progress : {pct:.0f}%  {'#' * int(pct // 5):<20}|")

        elif args.command == "export":
            tasks = store.list()
            payload = [t.to_dict() for t in tasks]
            if args.output:
                out = Path(args.output)
                with out.open("w", newline="", encoding="utf-8") as fh:
                    if args.format == "json":
                        json.dump(payload, fh, indent=2, default=str)
                    else:
                        writer = csv.DictWriter(fh, fieldnames=list(payload[0]) if payload else ["id"],
                                                extrasaction="ignore")
                        writer.writeheader()
                        writer.writerows(payload)
                print(f"exported {len(tasks)} tasks -> {out}")
            elif args.format == "json":
                print(json.dumps(payload, indent=2, default=str))
            else:
                fields = list(tasks[0].to_dict()) if tasks else ["id"]
                writer = csv.DictWriter(sys.stdout, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(t.to_dict() for t in tasks)
    return 0


def main() -> None:
    raise SystemExit(run())
