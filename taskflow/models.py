"""Domain models. Kept free of I/O so they are trivial to unit-test."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def utcnow() -> str:
    """Timestamps are stored as ISO-8601 UTC strings - sortable and portable."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Status(str, Enum):
    TODO = "todo"
    DOING = "doing"
    DONE = "done"

    @classmethod
    def parse(cls, raw: str) -> "Status":
        try:
            return cls(raw.strip().lower())
        except ValueError as exc:
            valid = ", ".join(s.value for s in cls)
            raise ValueError(f"invalid status {raw!r}; choose one of: {valid}") from exc


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def weight(self) -> int:
        return {"low": 1, "medium": 2, "high": 3}[self.value]

    @classmethod
    def parse(cls, raw: str) -> "Priority":
        try:
            return cls(raw.strip().lower())
        except ValueError as exc:
            valid = ", ".join(p.value for p in cls)
            raise ValueError(f"invalid priority {raw!r}; choose one of: {valid}") from exc


@dataclass(slots=True)
class Task:
    title: str
    priority: Priority = Priority.MEDIUM
    status: Status = Status.TODO
    tags: tuple[str, ...] = ()
    due: str | None = None
    id: int | None = None
    created_at: str = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("title must not be empty")
        if len(self.title) > 200:
            raise ValueError("title must be 200 characters or fewer")

    @property
    def is_overdue(self) -> bool:
        if not self.due or self.status is Status.DONE:
            return False
        return self.due < datetime.now(timezone.utc).date().isoformat()

    def to_dict(self) -> dict[str, object]:
        """Slots-based dataclasses have no __dict__, so serialisation is explicit."""
        return {
            "id": self.id,
            "title": self.title,
            "priority": self.priority.value,
            "status": self.status.value,
            "tags": list(self.tags),
            "due": self.due,
            "created_at": self.created_at,
            "overdue": self.is_overdue,
        }

    def sort_key(self) -> tuple[int, str, int]:
        """High priority first, then soonest due date, then oldest id."""
        return (-self.priority.weight, self.due or "9999-12-31", self.id or 0)
