import logging
import threading

from rainwater_app.execution_log import (
    DIAGNOSTIC_LEVEL,
    ExecutionLogger,
    normalize_log_detail,
    redact_log_text,
)


def test_log_detail_normalization() -> None:
    assert normalize_log_detail("detailed") == "Detailed"
    assert normalize_log_detail("DIAGNOSTIC") == "Diagnostic"
    assert normalize_log_detail("unknown") == "Normal"


def test_log_redaction_removes_paths_and_secrets(tmp_path) -> None:
    text = redact_log_text(
        f"token=abc api_key=xyz Opened {tmp_path / 'private' / 'project.db'}"
    )

    assert str(tmp_path) not in text
    assert "abc" not in text
    assert "xyz" not in text
    assert "<redacted>" in text


def test_execution_logger_captures_levels_details_and_bounded_history(tmp_path) -> None:
    logger = ExecutionLogger(tmp_path, history_limit=2)
    logger.diagnostic("Analysis", "diagnostic event", details="internal detail")
    logger.debug("Analysis", "detailed event")
    logger.info("Analysis", "normal event")

    entries = logger.drain()

    assert [entry.level for entry in entries] == [DIAGNOSTIC_LEVEL, logging.DEBUG, logging.INFO]
    assert [entry.message for entry in logger.history()] == ["detailed event", "normal event"]
    assert "internal detail" not in entries[0].display_text()
    assert "internal detail" in entries[0].display_text(include_details=True)
    logger.close()


def test_execution_logger_accepts_records_from_worker_threads(tmp_path) -> None:
    logger = ExecutionLogger(tmp_path)

    worker = threading.Thread(
        target=lambda: logger.info("Worker", "background work completed")
    )
    worker.start()
    worker.join()

    entries = logger.drain()

    assert len(entries) == 1
    assert entries[0].category == "Worker"
    assert entries[0].message == "background work completed"
    logger.close()


def test_execution_logger_rotates_files(tmp_path) -> None:
    logger = ExecutionLogger(tmp_path, max_file_bytes=160, backup_count=2)
    for index in range(20):
        logger.info("Rotation", f"Log message {index} with enough text to rotate the file")
    logger.close()

    assert (tmp_path / "execution.log").is_file()
    assert list(tmp_path.glob("execution.log.*"))
