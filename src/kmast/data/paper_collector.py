"""DF014 isolated PAPER public-quotation collector. Default-off, no order capabilities."""

import http.client
import json
import logging
import queue
import re
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kmast.core.config import BrokerConfig
from kmast.data.models import KST
from kmast.data.orb_observation import Context, OpeningResearch, Receipt, parse
from kmast.data.panel_acquisition import immutable_write
from kmast.data.paper_pilot import (
    AUTH_URL,
    CHANNELS,
    ENDPOINT,
    TARGETS,
    BoundedArchive,
    Budget,
    authorize,
    window,
)
from kmast.data.store import canonical, digest


def safe_code(value: Any) -> str | None:
    return (
        value if isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_-]{1,31}", value) else None
    )


def install_control_meter(protocol: Any, budget: Budget, now: Callable[[], datetime]) -> None:
    """Meter library-generated protocol Ping/Pong/Close, not only application JSON."""
    from websockets.frames import OP_CLOSE, OP_PING, OP_PONG, Frame

    original = protocol.send_frame

    def send(frame: Frame) -> None:
        if frame.opcode in {OP_CLOSE, OP_PING, OP_PONG}:
            if frame.opcode != OP_CLOSE:
                window(now())
            sequence = budget.reserve("CONTROL")
            original(frame)
            budget.result(sequence, category="SENT")
        else:
            original(frame)

    protocol.send_frame = send


def connect_paper(budget: Budget, now: Callable[[], datetime]) -> Any:
    from websockets.sync.client import ClientConnection, connect

    class MeteredConnection(ClientConnection):
        df014_control_metered = True

        def __init__(self, socket: Any, protocol: Any, **kwargs: Any):
            install_control_meter(protocol, budget, now)
            super().__init__(socket, protocol, **kwargs)

    silent = logging.Logger("kmast.df014.silent", level=logging.CRITICAL + 1)
    silent.addHandler(logging.NullHandler())
    silent.propagate = False
    return connect(
        ENDPOINT,
        proxy=None,
        compression=None,
        open_timeout=10,
        close_timeout=2,
        max_size=1024 * 1024,
        max_queue=16,
        ping_interval=None,
        ping_timeout=None,
        logger=silent,
        create_connection=MeteredConnection,
    )


class PaperCollector:
    def __init__(
        self,
        root: Path,
        config: BrokerConfig,
        approval: dict[str, Any],
        preflight: dict[str, Any],
        protocol_hash: str,
        *,
        enabled: bool = False,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        connector: Callable[[Budget, Callable[[], datetime]], Any] = connect_paper,
    ):
        self.root, self.config, self.approval, self.preflight = root, config, approval, preflight
        self.protocol_hash, self.enabled, self.now, self.connector = (
            protocol_hash,
            enabled,
            now,
            connector,
        )
        self.budget = Budget(root / "control")
        self.store = BoundedArchive(root)
        self.token: str | None = None
        self.active: set[tuple[str, str]] = set()
        self.pending: dict[tuple[str, str], str] = {}
        self.state = "OFF"
        self.filtered_sequence = dict.fromkeys(TARGETS, 0)
        opening = datetime(2026, 10, 19, 9, tzinfo=KST)
        # Static paperwork cannot certify every future VI/correction state.
        # Keep these unknown until independent, time-valid source evidence exists.
        self.engines = {
            symbol: OpeningResearch(
                Context(
                    opening.date(),
                    market,
                    opening,
                    True,
                    False,
                    False,
                    "DF014_INDEPENDENT_CALENDAR_ONLY",
                ),
                symbol,
            )
            for symbol, market in TARGETS.items()
        }
        self.ranges: dict[str, dict[str, Any]] = {symbol: {} for symbol in TARGETS}
        self.real_frames = 0
        self.total_received_frames = 0
        self.total_received_bytes = 0
        self.failures: dict[str, int] = {}
        self.generation = 0
        self.receipt_sequence = 0

    def guard(self) -> None:
        if self.config.endpoint != AUTH_URL.removesuffix("/oauth2/Approval"):
            raise PermissionError("EXACT_PAPER_AUTH_HOST_REQUIRED")
        authorize(
            self.approval,
            self.preflight,
            self.protocol_hash,
            self.now(),
            enabled=self.enabled,
            environment=self.config.environment.value,
        )

    def issue(self) -> None:
        self.guard()
        binding = dict(
            protocol_sha256=self.protocol_hash,
            approval_record_sha256=digest(canonical(self.approval)),
            human_statement_sha256=self.approval["human_approval_record"]["sha256"],
            preflight_record_sha256=digest(canonical(self.preflight)),
            human_scope_gate_passed=True,
            transport_evidence_gate_passed=True,
            clock_sync_verified=self.preflight.get("clock_sync_verified") is True,
        )
        immutable_write(self.root / "control/authorization.json", canonical(binding))
        if self.config.app_key is None or self.config.app_secret is None:
            raise PermissionError("PAPER_KEYS_UNAVAILABLE")
        sequence = self.budget.reserve("AUTH")
        self.state = "AUTH_RESERVED"
        raw = None
        connection = http.client.HTTPSConnection(
            "openapivts.koreainvestment.com", 29443, timeout=10
        )
        try:
            payload = dict(
                grant_type="client_credentials",
                appkey=self.config.app_key.get_secret_value(),
                secretkey=self.config.app_secret.get_secret_value(),
            )
            connection.request(
                "POST",
                "/oauth2/Approval",
                body=json.dumps(payload).encode(),
                headers={"content-type": "application/json"},
            )
            response = connection.getresponse()
            raw = response.read(1024 * 1024 + 1)
            if response.status != 200:
                self.budget.result(sequence, category="HTTP_DENIED", response_hash=digest(raw))
                raise PermissionError("PAPER_APPROVAL_DENIED")
            body = json.loads(raw)
            token = body.get("approval_key")
            if len(raw) > 1024 * 1024 or not isinstance(token, str) or not 16 <= len(token) <= 4096:
                raise ValueError
            self.token = token
            self.state = "APPROVED"
            self.budget.result(sequence, category="SUCCESS", response_hash=digest(raw))
        except PermissionError:
            raise
        except Exception:
            self.state = "AUTH_FAILED"
            self.budget.result(
                sequence,
                category="MALFORMED" if raw is not None else "IO_FAILED",
                response_hash=digest(raw) if raw is not None else None,
            )
            # Reservation survives even when no result was recoverable.
            raise RuntimeError("PAPER_AUTH_FAILED_INPUTS_SUPPRESSED") from None
        finally:
            connection.close()

    def send(self, socket: Any, kind: str, channel: str, symbol: str) -> None:
        self.guard()
        if (
            kind not in {"SUB", "UNSUB"}
            or channel not in CHANNELS
            or symbol not in TARGETS
            or self.token is None
        ):
            raise PermissionError("PUBLIC_SUBSCRIPTION_SCOPE_DENIED")
        sequence = self.budget.reserve(kind)
        self.pending[(channel, symbol)] = kind
        message = dict(
            header=dict(
                approval_key=self.token,
                custtype="P",
                tr_type="1" if kind == "SUB" else "0",
                **{"content-type": "utf-8"},
            ),
            body=dict(input=dict(tr_id=channel, tr_key=symbol)),
        )
        try:
            socket.send(json.dumps(message))
        except Exception:
            raise RuntimeError("SUBSCRIPTION_SEND_FAILED_INPUTS_SUPPRESSED") from None
        self.budget.result(sequence, category="SENT")

    def process(self, socket: Any, raw: bytes, receipt: Receipt) -> None:
        base: dict[str, Any] = dict(
            connection=receipt.connection,
            sequence=receipt.sequence,
            received_at=receipt.received_at.isoformat(),
            received_monotonic_ns=receipt.monotonic_ns,
            raw_sha256=digest(raw),
            bytes=len(raw),
            origin=receipt.origin,
        )
        if receipt.origin == "OBSERVED":
            try:
                window(receipt.received_at)
            except PermissionError:
                self.store.metadata(base | dict(category="OUTSIDE_WINDOW_HASH_ONLY"))
                raise PermissionError("OUTSIDE_WINDOW_FRAME_NOT_USED") from None
        if len(raw) > 1024 * 1024:
            raise RuntimeError("FRAME_LIMIT_EXCEEDED")
        secrets = tuple(
            s.get_secret_value().encode()
            for s in (self.config.app_key, self.config.app_secret)
            if s
        ) + ((self.token.encode(),) if self.token else ())
        if any(secret and secret in raw for secret in secrets):
            self.store.metadata(base | dict(category="SENSITIVE_HASH_ONLY"))
            raise RuntimeError("SENSITIVE_FRAME_WITHHELD")
        if raw.startswith(b"{"):
            try:
                body = json.loads(raw)
                header = body["header"]
                channel, symbol = header.get("tr_id"), header.get("tr_key")
                if channel == "PINGPONG":
                    if set(header) - {"tr_id", "datetime"} or set(body) - {"header"}:
                        raise ValueError
                    self.guard()
                    if getattr(socket, "df014_control_metered", False):
                        socket.pong(raw)
                    else:
                        sequence = self.budget.reserve("CONTROL")
                        socket.pong(raw)
                        self.budget.result(sequence, category="SENT")
                    category = "HEARTBEAT"
                elif channel in CHANNELS and symbol in TARGETS:
                    code = safe_code(body.get("body", {}).get("msg_cd"))
                    if body.get("body", {}).get("rt_cd") != "0":
                        self.store.metadata(
                            base
                            | dict(
                                category="SUBSCRIPTION_DENIED",
                                channel=channel,
                                symbol=symbol,
                                provider_code=code,
                            )
                        )
                        raise PermissionError("PAPER_SUBSCRIPTION_DENIED")
                    action = self.pending.pop((channel, symbol), None)
                    if action == "SUB":
                        self.active.add((channel, symbol))
                        ack_at = self.now()
                        if ack_at < receipt.received_at:
                            raise ValueError
                        self.engines[symbol].acknowledge(channel, ack_at)
                    elif action == "UNSUB":
                        self.active.discard((channel, symbol))
                        self.engines[symbol].disconnect()
                    else:
                        raise ValueError
                    self.state = "STREAMING" if len(self.active) == 4 else "SUBSCRIBING"
                    category = "SUBSCRIPTION_ACK"
                else:
                    raise ValueError
                self.store.metadata(
                    base
                    | dict(
                        category=category,
                        channel=channel,
                        symbol=symbol,
                        raw_retention="CONTROL_HASH_ONLY",
                    )
                )
                return
            except PermissionError:
                raise
            except Exception:
                self.store.metadata(base | dict(category="INVALID_CONTROL_HASH_ONLY"))
                raise RuntimeError("CONTROL_FRAME_INVALID_INPUTS_SUPPRESSED") from None
        try:
            channel = raw.split(b"|", 3)[1].decode("ascii")
            if channel not in CHANNELS:
                raise ValueError
            # Parse with a neutral known calendar first; symbol market is then
            # independently bound by the exact whitelist, not guessed from the name.
            neutral = self.engines["073240"].context
            preliminary = parse(raw, receipt, neutral)
            symbols = {tick.symbol for tick in preliminary}
            if not symbols or not symbols <= TARGETS.keys():
                raise ValueError
            if len(symbols) != 1:
                raise ValueError
            symbol = next(iter(symbols))
            context = self.engines[symbol].context
            ticks = parse(raw, receipt, context)
            parsed_at = self.now()
        except Exception:
            self.store.metadata(base | dict(category="PARSE_SCOPE_FAILED_HASH_ONLY"))
            for engine in self.engines.values():
                engine.defects.add("PARSE_OR_SCOPE_FAILURE")
            return
        self.store.append(raw, receipt, context, secrets)
        self.filtered_sequence[symbol] += 1
        local = self.filtered_sequence[symbol]
        engine = self.engines[symbol]
        if (channel, symbol) not in self.active:
            engine.defects.add("UNACKNOWLEDGED_DATA")
        if self.preflight.get("clock_sync_verified") is not True:
            engine.defects.add("CLOCK_SYNC_UNVERIFIED")
        for tick in ticks:
            view = replace(tick, receipt=replace(receipt, sequence=local))
            engine.ingest(view, validated_at=parsed_at)
        validated_at, validated_ns = self.now(), time.monotonic_ns()
        for tick in ticks:
            if tick.row_identity in engine.validated_availability:
                engine.validated_availability[tick.row_identity] = validated_at
        self.real_frames += int(receipt.origin == "OBSERVED")
        self.store.metadata(
            base
            | dict(
                category="QUOTATION",
                channel=channel,
                symbol=symbol,
                filtered_symbol_frame_sequence=local,
                parsed_at=parsed_at.isoformat(),
                validated_at=validated_at.isoformat(),
                validated_monotonic_ns=validated_ns,
                row_ids=[t.row_identity for t in ticks],
                exchange_times=[
                    t.exchange_time.isoformat() if t.exchange_time else None for t in ticks
                ],
                source_flags=[list(t.flags) for t in ticks],
                defects=sorted(engine.defects),
                source_minus_receipt_is_network_latency=False,
            )
        )
        for minutes in (5, 15):
            key = str(minutes)
            high = engine.range_high(minutes, validated_at)
            if high is not None and key not in self.ranges[symbol]:
                self.ranges[symbol][key] = dict(
                    high=str(high),
                    finalized_at=validated_at.isoformat(),
                    source_hash=ticks[-1].raw_sha256,
                )
            if key in self.ranges[symbol]:
                quote = engine.later_quote(
                    datetime.fromisoformat(self.ranges[symbol][key]["finalized_at"]), validated_at
                )
                if quote is not None:
                    self.ranges[symbol][key]["later_quote_observed"] = True
                    self.ranges[symbol][key]["quote_source_hash"] = quote.raw_sha256

    def read_socket(
        self,
        socket: Any,
        stop: threading.Event,
        incoming: queue.Queue[tuple[bytes | None, Receipt | None]],
        overflow: threading.Event,
    ) -> None:
        while not stop.is_set():
            try:
                message = socket.recv(timeout=1)
                stamp, monotonic = self.now(), time.monotonic_ns()
                self.receipt_sequence += 1
                receipt = Receipt(
                    stamp,
                    monotonic,
                    f"DF014-{self.generation}",
                    self.receipt_sequence,
                    "OBSERVED",
                )
                raw = message if isinstance(message, bytes) else message.encode("utf-8")
                self.total_received_frames += 1
                self.total_received_bytes += len(raw)
                incoming.put_nowait((raw, receipt))
            except TimeoutError:
                continue
            except queue.Full:
                overflow.set()
                return
            except Exception:
                try:
                    incoming.put_nowait((None, None))
                except queue.Full:
                    overflow.set()
                return

    def collect(self) -> dict[str, Any]:
        try:
            return self._collect()
        finally:
            self.token = None
            self.state = "STOPPED"

    def _collect(self) -> dict[str, Any]:
        self.guard()
        self.issue()
        failure = None
        while self.budget.used["CONNECT"] < 2:
            self.guard()
            sequence = self.budget.reserve("CONNECT")
            self.state = "CONNECTING"
            socket = None
            stop = threading.Event()
            incoming: queue.Queue[tuple[bytes | None, Receipt | None]] = queue.Queue(maxsize=256)
            overflow = threading.Event()
            reader = None
            try:
                socket = self.connector(self.budget, self.now)
                self.budget.result(sequence, category="SOCKET_OPEN")
                self.generation += 1
                self.receipt_sequence = 0
                self.active.clear()
                self.pending.clear()
                self.state = "SUBSCRIBING"
                self.filtered_sequence = dict.fromkeys(TARGETS, 0)
                for engine in self.engines.values():
                    if self.generation > 1:
                        engine.disconnect()
                    engine.connection = f"DF014-{self.generation}"
                    engine.last_sequence = 0
                    engine.last_frame_hash = None

                reader = threading.Thread(
                    target=self.read_socket, args=(socket, stop, incoming, overflow), daemon=True
                )
                reader.start()
                for symbol in TARGETS:
                    for channel in sorted(CHANNELS):
                        self.send(socket, "SUB", channel, symbol)
                while True:
                    local_now = self.now().astimezone(KST)
                    if (
                        local_now.strftime("%Y-%m-%d") != "2026-10-19"
                        or local_now.strftime("%H:%M:%S") >= "09:25:00"
                    ):
                        failure = "WINDOW_END"
                        break
                    if overflow.is_set():
                        raise RuntimeError("RECEIVE_QUEUE_OVERFLOW")
                    try:
                        raw, receipt = incoming.get(timeout=0.5)
                    except queue.Empty:
                        continue
                    if raw is None or receipt is None:
                        raise ConnectionError
                    self.process(socket, raw, receipt)
                # At/after end, socket teardown only; no out-of-window data subscription I/O.
                break
            except PermissionError:
                failure = "ENTITLEMENT_OR_BUDGET_STOP"
                break
            except (ConnectionError, OSError, TimeoutError):
                failure = "TRANSPORT_INTERRUPTED"
                self.state = "GAP"
                if socket is None:
                    self.budget.result(sequence, category="IO_FAILED")
                for engine in self.engines.values():
                    engine.disconnect()
            except Exception:
                failure = "TRANSPORT_INTERRUPTED" if socket is None else "INTEGRITY_STOP"
                for engine in self.engines.values():
                    engine.disconnect()
            finally:
                stop.set()
                if socket is not None:
                    try:
                        socket.close()
                    except Exception:
                        try:
                            socket.socket.close()
                        except Exception:
                            pass
                if reader is not None:
                    reader.join(timeout=3)
                    if reader.is_alive():
                        raise RuntimeError("RECEIVER_DID_NOT_STOP")
            if failure == "TRANSPORT_INTERRUPTED" and self.budget.used["CONNECT"] < 2:
                time.sleep(3.10)
            else:
                break
        self.store.verify()
        self.token = None
        self.state = "STOPPED"
        return dict(
            status="DF014_PARTIAL_STREAM_QUALITY"
            if self.real_frames
            else "DF014_PAPER_ACCESS_BLOCKED",
            reason=failure,
            actual_quote_frames=self.real_frames,
            budget=self.budget.used,
            ranges=self.ranges,
            defects={s: sorted(e.defects) for s, e in self.engines.items()},
            rvol="RVOL_NOT_READY",
            real_profit=None,
            connection_state=self.state,
            actual_total_application_frames=self.total_received_frames,
            actual_total_application_bytes=self.total_received_bytes,
        )
