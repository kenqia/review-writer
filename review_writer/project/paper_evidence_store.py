"""Cross-process transaction lock for paper-evidence mutations."""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class PaperEvidenceStoreError(ValueError):
    """A stable persistence/lock failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_THREAD_LOCK = threading.RLock()


def _validate_lock_path(project: Path) -> Path:
    root = Path(project)
    if root.is_symlink() or not root.is_dir():
        raise PaperEvidenceStoreError("PROJECT_INVALID")
    evidence = root / "01_evidence"
    if os.path.lexists(evidence) and (evidence.is_symlink() or not evidence.is_dir()):
        raise PaperEvidenceStoreError("PAPER_EVIDENCE_PATH_INVALID")
    evidence.mkdir(exist_ok=True)
    lock_path = root / ".paper_evidence.lock"
    if os.path.lexists(lock_path) and (lock_path.is_symlink() or not lock_path.is_file()):
        raise PaperEvidenceStoreError("PAPER_EVIDENCE_PATH_INVALID")
    return lock_path


@contextmanager
def project_write_lock(project: Path) -> Iterator[None]:
    """Serialize all paper-evidence read-modify-write transactions."""

    with _THREAD_LOCK:
        try:
            lock_path = _validate_lock_path(Path(project))
            with lock_path.open("a+b") as lock:
                if os.name == "nt":
                    lock.seek(0, os.SEEK_END)
                    if lock.tell() == 0:
                        lock.write(b"\0")
                        lock.flush()
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
                    try:
                        yield
                    finally:
                        lock.seek(0)
                        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                    try:
                        yield
                    finally:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        except OSError as exc:
            raise PaperEvidenceStoreError("PAPER_EVIDENCE_LOCK_FAILED") from exc
