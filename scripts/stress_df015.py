"""Synthetic fault injection only; no socket, authentication, or real-price generation."""

import errno
import json
import queue
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from kmast.data.panel_acquisition import atomic_json
from kmast.data.paper_pilot import CONTROL_RESERVE, BoundedArchive, Budget
from kmast.data.store import digest
from tests.test_df013 import CONTEXT, frame, tick
from tests.test_df014 import collector


def run(root):
    root.mkdir(parents=True, exist_ok=True)
    results = []
    # Feed the production receive loop faster than the writer; the 257th frame
    # is counted as received, cannot fit, and must produce explicit overflow.
    c = collector(root)
    incoming, overflow = queue.Queue(maxsize=256), threading.Event()
    sent = 0

    def receive(**kwargs):
        nonlocal sent
        sent += 1
        return frame(channel="H0STASP0")

    c.read_socket(SimpleNamespace(recv=receive), threading.Event(), incoming, overflow)
    assert sent == 257 and incoming.qsize() == 256 and overflow.is_set()
    results.append(
        dict(
            case="BURST_QUEUE_256",
            received=257,
            retained_in_queue=256,
            overflow_hold=True,
            silent_drop_accepted=False,
        )
    )

    store = BoundedArchive(root / "slow-disk")
    original = store.append
    durations = []
    for i in range(8):
        start = time.perf_counter()
        # Delay the actual fsynced archive path, not a substitute in-memory store.
        time.sleep(0.02)
        original(
            frame(i, channel="H0STASP0"), replace(tick(i).receipt, sequence=i + 1), CONTEXT, ()
        )
        durations.append(time.perf_counter() - start)
    store.verify()
    results.append(
        dict(
            case="DISK_DELAY",
            injected_seconds_per_write=0.02,
            frames=8,
            max_observed_seconds=max(durations),
            mean_observed_seconds=sum(durations) / len(durations),
            real_provider_capacity=None,
        )
    )

    # 100 complete depth-10 rows, the parser's documented batch bound.
    prefix, channel, _, payload = frame(channel="H0STASP0").decode().split("|", 3)
    batch = f"{prefix}|{channel}|100|".encode() + "^".join([payload] * 100).encode()
    large = BoundedArchive(root / "large-quote")
    large.append(batch, tick().receipt, CONTEXT, ())
    large.verify()
    results.append(
        dict(
            case="DEPTH10_BATCH100",
            raw_bytes=len(batch),
            frames=1,
            normalized_rows=100,
            raw_sha256=digest(batch),
        )
    )

    full = BoundedArchive(root / "full-disk")
    with patch(
        "kmast.data.orb_observation.immutable_write",
        side_effect=OSError(errno.ENOSPC, "SYNTHETIC_FULL_DISK"),
    ):
        try:
            full.append(frame(), tick().receipt, CONTEXT, ())
            raise AssertionError("ENOSPC ignored")
        except OSError as exc:
            assert exc.errno == errno.ENOSPC
    assert full.frames == 0
    results.append(dict(case="DISK_FULL", accepted_frames=0, quality="HOLD"))

    grow = BoundedArchive(root / "metadata", total_cap=CONTROL_RESERVE + 70000)
    count = 0
    while True:
        try:
            grow.metadata(dict(origin="SYNTHETIC", padding="x" * 1024, sequence=count))
            count += 1
        except PermissionError:
            break
    assert count > 0 and grow.used < 70000
    grow.verify()
    results.append(
        dict(
            case="METADATA_GROWTH",
            complete_records=count,
            logical_bytes=grow.used,
            configured_test_bytes=70000,
            quality="HOLD",
        )
    )
    control = Budget(root / "logs")
    with patch("kmast.data.paper_pilot.CONTROL_RESERVE", 65536):
        try:
            control.reserve("CONNECT")
            raise AssertionError("control reserve ignored")
        except PermissionError:
            pass
    results.append(dict(case="CONTROL_LOG_CAP", accepted_reservations=0, quality="HOLD"))

    reconnect = root / "reconnect"
    for _ in range(2):
        Budget(reconnect).reserve("CONNECT")
    try:
        Budget(reconnect).reserve("CONNECT")
        raise AssertionError("third connection allowed")
    except PermissionError:
        pass
    assert Budget(reconnect).used["CONNECT"] == 2
    results.append(
        dict(case="RESTARTED_RECONNECT_BUDGET", attempts=2, third_denied=True, actual_connections=0)
    )

    # os._exit models a process dying without finally/flush cleanup. Complete
    # publication can reopen; interruption inside journal publication cannot.
    for partial in (False, True):
        folder = root / ("crash-partial" if partial else "crash-complete")
        code = (
            "import os; from pathlib import Path; "
            "from kmast.data.paper_pilot import BoundedArchive; "
            "from tests.test_df013 import frame,tick,CONTEXT; "
            "s=BoundedArchive(Path(" + repr(str(folder)) + ")); "
            "s.append(frame(),tick().receipt,CONTEXT,()); "
        )
        if partial:
            code += "(s.data/'observations.jsonl').write_bytes(b'{'); "
        code += "os._exit(17)"
        child = subprocess.run([sys.executable, "-c", code], capture_output=True)
        assert child.returncode == 17
        try:
            reopened = BoundedArchive(folder)
            assert not partial and reopened.frames == 1
        except ValueError:
            assert partial
        results.append(
            dict(
                case="FORCED_EXIT_PARTIAL" if partial else "FORCED_EXIT_COMPLETE",
                subprocess_exit=17,
                quality="HOLD" if partial else "INTEGRITY_ONLY_NOT_RESEARCH_PASS",
            )
        )
    # Interrupt raw publication before journal creation, retaining orphan bytes.
    orphan = root / "crash-orphan"
    store = BoundedArchive(orphan)
    raw = frame()
    folder = store.data / "segments/00000000/wire"
    folder.mkdir(parents=True)
    (folder / (digest(raw) + ".bin")).write_bytes(raw)
    try:
        BoundedArchive(orphan)
        raise AssertionError("orphan silently recovered")
    except ValueError:
        pass
    assert (folder / (digest(raw) + ".bin")).read_bytes() == raw
    results.append(dict(case="ORPHAN_RAW", bytes_preserved=True, quality="HOLD"))
    return dict(
        origin="SYNTHETIC",
        cases=results,
        real_provider_rate=None,
        raw_cap=1073741824,
        total_cap=3221225472,
        actual_market_frames=0,
    )


def main():
    root = Path("data/data-first-private-df015-stress")
    # Reruns retain the measured run rather than mutate its receipts/latencies.
    summary = root / "summary.json"
    if summary.exists():
        result = json.loads(summary.read_bytes())
    else:
        result = run(root / "run-v1")
        atomic_json(summary, result)
    atomic_json(Path("artifacts/df015/stress.json"), result)
    print(f"DF015 offline synthetic fault cases PASS: {len(result['cases'])}")


if __name__ == "__main__":
    main()
