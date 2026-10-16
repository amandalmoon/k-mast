import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from kmast.data.store import canonical, digest
from kmast.execution.events import EVENT_ADAPTER, Event
from kmast.execution.ledger import assert_integrity, reduce_event
from kmast.execution.models import ExecutionState


class WriterLease:
    """OS-held lock across processes on this host; no distributed lease or expiry takeover."""

    def __init__(self, account_ref: str) -> None:
        directory = Path(tempfile.gettempdir()) / "kmast-mock-writer-locks"
        directory.mkdir(exist_ok=True)
        path = directory / (hashlib.sha256(account_ref.encode()).hexdigest() + ".lock")
        self.file = path.open("a+b")
        self.file.seek(0, os.SEEK_END)
        if self.file.tell() == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("mock account already has a writer") from None

    def close(self) -> None:
        if self.file.closed:
            return
        self.file.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        self.file.close()


class Journal:
    def __init__(self, path: Path, initial: ExecutionState) -> None:
        self.lease = WriterLease(initial.account_ref)
        self.closed = False
        self.path = path
        self.fault_hook: Callable[[], None] | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(path, timeout=0, isolation_level=None)
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS meta (id INTEGER PRIMARY KEY CHECK(id=1), "
                "initial TEXT NOT NULL, hash TEXT NOT NULL)"
            )
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, "
                "event_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL, "
                "prev_hash TEXT NOT NULL, hash TEXT NOT NULL, state_hash TEXT NOT NULL)"
            )
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS checkpoint (id INTEGER PRIMARY KEY CHECK(id=1), "
                "seq INTEGER NOT NULL, state TEXT NOT NULL, hash TEXT NOT NULL)"
            )
            genesis = canonical(initial.model_dump(mode="json")).decode()
            self.db.execute(
                "INSERT OR IGNORE INTO meta VALUES (1,?,?)", (genesis, digest(genesis.encode()))
            )
            stored, initial_hash = self.db.execute(
                "SELECT initial,hash FROM meta WHERE id=1"
            ).fetchone()
            if digest(stored.encode()) != initial_hash or json.loads(stored) != json.loads(genesis):
                raise ValueError("journal genesis/config mismatch")
            self.initial = initial
            self.state, self.head = self.replay()
        except Exception:
            if hasattr(self, "db"):
                self.db.close()
            self.lease.close()
            raise

    def replay(self) -> tuple[ExecutionState, str]:
        state = self.initial
        head = digest(canonical(state.model_dump(mode="json")))
        for seq, event_id, payload, prev_hash, event_hash, state_hash in self.db.execute(
            "SELECT seq,event_id,payload,prev_hash,hash,state_hash FROM events ORDER BY seq"
        ):
            if (
                seq != state.sequence + 1
                or prev_hash != head
                or digest((head + payload).encode()) != event_hash
            ):
                raise ValueError("journal chain corruption")
            event = EVENT_ADAPTER.validate_json(payload)
            if event.event_id != event_id:
                raise ValueError("journal event identity corruption")
            state = reduce_event(state, event)
            if digest(canonical(state.model_dump(mode="json"))) != state_hash:
                raise ValueError("replayed state hash mismatch")
            head = event_hash
        checkpoint = self.db.execute("SELECT seq,state,hash FROM checkpoint WHERE id=1").fetchone()
        if checkpoint:
            seq, encoded, saved_hash = checkpoint
            if (
                seq != state.sequence
                or digest(encoded.encode()) != saved_hash
                or json.loads(encoded) != state.model_dump(mode="json")
            ):
                raise ValueError("checkpoint corruption")
        elif state.sequence:
            raise ValueError("journal checkpoint missing")
        assert_integrity(state)
        return state, head

    def commit(self, event: Event) -> ExecutionState:
        if self.closed:
            raise RuntimeError("writer is closed")
        payload = canonical(EVENT_ADAPTER.dump_python(event, mode="json")).decode()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            old = self.db.execute(
                "SELECT payload FROM events WHERE event_id=?", (event.event_id,)
            ).fetchone()
            if old:
                if old[0] != payload:
                    raise ValueError("event id reused with different payload")
                self.db.execute("ROLLBACK")
                return self.state
            updated = reduce_event(self.state, event)
            encoded = canonical(updated.model_dump(mode="json")).decode()
            state_hash = digest(encoded.encode())
            head = digest((self.head + payload).encode())
            self.db.execute(
                "INSERT INTO events VALUES (?,?,?,?,?,?)",
                (updated.sequence, event.event_id, payload, self.head, head, state_hash),
            )
            self.db.execute(
                "INSERT OR REPLACE INTO checkpoint VALUES (1,?,?,?)",
                (updated.sequence, encoded, state_hash),
            )
            if self.fault_hook:
                self.fault_hook()
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        self.state, self.head = updated, head
        return updated

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.db.close()
            self.lease.close()
