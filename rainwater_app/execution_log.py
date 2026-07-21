from __future__ import annotations

import logging
import queue
import re
import traceback
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock


DIAGNOSTIC_LEVEL = 5
logging.addLevelName(DIAGNOSTIC_LEVEL, "DIAGNOSTIC")

DETAIL_LEVELS = {
    "Normal": logging.INFO,
    "Detailed": logging.DEBUG,
    "Diagnostic": DIAGNOSTIC_LEVEL,
}


def normalize_log_detail(value: object) -> str:
    candidate = str(value).strip().title()
    return candidate if candidate in DETAIL_LEVELS else "Normal"


def redact_log_text(value: object, *, home: Path | None = None) -> str:
    text = str(value)
    if home is not None:
        home_text = str(home.expanduser().resolve(strict=False))
        if home_text:
            text = text.replace(home_text, "<home>")
            text = text.replace(home_text.replace("\\", "/"), "<home>")
    text = re.sub(r"(?m)\b[A-Za-z]:\\[^\r\n]+", "<private-path>", text)
    text = re.sub(r"(?m)(?<![\w:])/[^\s\r\n\"']+", "<private-path>", text)
    text = re.sub(
        r"(?i)(token|api[_-]?key|password|secret)=([^&\s]+)",
        lambda match: f"{match.group(1)}=<redacted>",
        text,
    )
    return text


@dataclass(frozen=True)
class ExecutionLogEntry:
    sequence: int
    timestamp: datetime
    level: int
    level_name: str
    category: str
    message: str
    details: str = ""

    def display_text(self, *, include_details: bool = False) -> str:
        prefix = (
            f"{self.timestamp:%H:%M:%S.%f}"[:-3]
            + f"  {self.level_name:<10} [{self.category}] "
        )
        text = prefix + self.message
        if self.details and include_details:
            indented = "\n".join(f"    {line}" for line in self.details.splitlines())
            text += f"\n{indented}"
        return text + "\n"


class _RedactingFormatter(logging.Formatter):
    def __init__(self, *, home: Path) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)-10s [%(category)s] %(message)s%(details_suffix)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self.home = home

    def format(self, record: logging.LogRecord) -> str:
        record.message = redact_log_text(record.getMessage(), home=self.home)
        record.msg = record.message
        record.args = ()
        details = redact_log_text(getattr(record, "details", ""), home=self.home)
        record.details_suffix = f"\n{details}" if details else ""
        return super().format(record)


class _RecordQueueHandler(logging.Handler):
    def __init__(self, record_queue: queue.Queue[logging.LogRecord]) -> None:
        super().__init__(level=DIAGNOSTIC_LEVEL)
        self.record_queue = record_queue

    def emit(self, record: logging.LogRecord) -> None:
        self.record_queue.put_nowait(record)


class ExecutionLogger:
    """Thread-safe structured logging with rotating files and bounded UI history."""

    def __init__(
        self,
        log_directory: Path,
        *,
        history_limit: int = 5000,
        max_file_bytes: int = 1_000_000,
        backup_count: int = 4,
    ) -> None:
        self.log_directory = log_directory
        self.log_directory.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_directory / "execution.log"
        self._record_queue: queue.Queue[logging.LogRecord] = queue.Queue()
        self._history: deque[ExecutionLogEntry] = deque(maxlen=history_limit)
        self._history_lock = Lock()
        self._sequence = 0
        self._home = Path.home()
        self._logger = logging.getLogger(f"rainwater.execution.{id(self)}")
        self._logger.setLevel(DIAGNOSTIC_LEVEL)
        self._logger.propagate = False
        self._queue_handler = _RecordQueueHandler(self._record_queue)
        self._file_handler = RotatingFileHandler(
            self.log_path,
            maxBytes=max_file_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        self._file_handler.setLevel(DIAGNOSTIC_LEVEL)
        self._file_handler.setFormatter(_RedactingFormatter(home=self._home))
        self._logger.addHandler(self._queue_handler)
        self._logger.addHandler(self._file_handler)

    def log(
        self,
        level: int,
        category: str,
        message: object,
        *,
        details: object = "",
    ) -> None:
        self._logger.log(
            level,
            redact_log_text(message, home=self._home),
            extra={
                "category": str(category).strip() or "Application",
                "details": redact_log_text(details, home=self._home),
            },
        )

    def diagnostic(self, category: str, message: object, *, details: object = "") -> None:
        self.log(DIAGNOSTIC_LEVEL, category, message, details=details)

    def debug(self, category: str, message: object, *, details: object = "") -> None:
        self.log(logging.DEBUG, category, message, details=details)

    def info(self, category: str, message: object, *, details: object = "") -> None:
        self.log(logging.INFO, category, message, details=details)

    def warning(self, category: str, message: object, *, details: object = "") -> None:
        self.log(logging.WARNING, category, message, details=details)

    def error(
        self,
        category: str,
        message: object,
        *,
        exception: BaseException | None = None,
    ) -> None:
        details = ""
        if exception is not None:
            details = "".join(
                traceback.format_exception(type(exception), exception, exception.__traceback__)
            ).rstrip()
        self.log(logging.ERROR, category, message, details=details)

    def drain(self, *, maximum: int = 500) -> list[ExecutionLogEntry]:
        entries: list[ExecutionLogEntry] = []
        for _index in range(maximum):
            try:
                record = self._record_queue.get_nowait()
            except queue.Empty:
                break
            self._sequence += 1
            entry = ExecutionLogEntry(
                sequence=self._sequence,
                timestamp=datetime.fromtimestamp(record.created),
                level=record.levelno,
                level_name=record.levelname,
                category=str(getattr(record, "category", "Application")),
                message=redact_log_text(record.getMessage(), home=self._home),
                details=redact_log_text(getattr(record, "details", ""), home=self._home),
            )
            entries.append(entry)
        if entries:
            with self._history_lock:
                self._history.extend(entries)
        return entries

    def history(self) -> list[ExecutionLogEntry]:
        with self._history_lock:
            return list(self._history)

    def clear(self) -> None:
        self.drain(maximum=100_000)
        with self._history_lock:
            self._history.clear()

    def close(self) -> None:
        self.drain(maximum=100_000)
        for handler in tuple(self._logger.handlers):
            handler.flush()
            handler.close()
            self._logger.removeHandler(handler)
