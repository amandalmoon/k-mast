import json
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from importlib.resources import files
from typing import Any, Literal, Protocol

from pydantic import SecretStr

from kmast.brokers.interfaces import OrdersBlocked
from kmast.brokers.kis.adapter import StreamState
from kmast.brokers.kis.network import DataError, KISAuth, NetworkPermit
from kmast.core.clock import Clock
from kmast.core.config import BrokerConfig
from kmast.core.enums import Environment
from kmast.data.models import KST, Observation, observation_id, utc
from kmast.data.parsers import number
from kmast.data.store import canonical, digest

WS_ENDPOINTS = {
    Environment.LIVE: "ws://ops.koreainvestment.com:21000",
    Environment.PAPER: "ws://ops.koreainvestment.com:31000",
}
WS_COLUMNS: dict[str, list[str]] = json.loads(
    files("kmast.brokers.kis").joinpath("ws_columns.json").read_text(encoding="utf-8")
)


class Socket(Protocol):
    def send(self, message: str) -> None: ...
    def recv(self, timeout: float | None = None) -> str | bytes: ...
    def close(self) -> None: ...
    def pong(self, data: bytes) -> Any: ...


def connect_socket(endpoint: str) -> Socket:
    from websockets.sync.client import connect

    return connect(endpoint, open_timeout=10, close_timeout=5, max_size=1024 * 1024, proxy=None)


def parse_frame(
    frame: str,
    received_at: datetime,
    *,
    session: str = "UNKNOWN",
    data_origin: str = "KIS_READONLY",
) -> tuple[Observation, ...]:
    parts = frame.split("|", 3)
    if len(parts) != 4 or parts[0] != "0" or parts[1] not in WS_COLUMNS:
        raise DataError("UNSUPPORTED_STREAM_FRAME")
    tr_id = parts[1]
    columns = WS_COLUMNS[tr_id]
    try:
        count = int(parts[2])
        values = parts[3].split("^")
        if not 1 <= count <= 100 or len(values) != count * len(columns):
            raise ValueError
        result: list[Observation] = []
        for offset in range(count):
            row = dict(
                zip(
                    columns,
                    values[offset * len(columns) : (offset + 1) * len(columns)],
                    strict=True,
                )
            )
            symbol = row["MKSC_SHRN_ISCD"]
            flags = [] if session == "REGULAR" else ["SESSION_UNVERIFIED"]
            if tr_id == "H0STCNT0":
                stamp = datetime.strptime(
                    row["BSOP_DATE"] + row["STCK_CNTG_HOUR"], "%Y%m%d%H%M%S"
                ).replace(tzinfo=KST)
                fields: dict[str, Any] = dict(
                    kind="TRADE", price=number(row, "STCK_PRPR"), volume=number(row, "CNTG_VOL")
                )
            else:
                # No business date in this quote payload. Receipt-day binding stays quality locked.
                stamp = datetime.strptime(
                    received_at.astimezone(KST).strftime("%Y%m%d") + row["BSOP_HOUR"],
                    "%Y%m%d%H%M%S",
                ).replace(tzinfo=KST)
                flags.append("QUOTE_DATE_INFERRED_FROM_RECEIPT")
                fields = dict(
                    kind="QUOTE",
                    bid=number(row, "BIDP1"),
                    ask=number(row, "ASKP1"),
                    bid_size=number(row, "BIDP_RSQN1"),
                    ask_size=number(row, "ASKP_RSQN1"),
                )
            source_hash = digest(canonical(row))
            quote = tr_id == "H0STASP0"
            result.append(
                Observation.model_validate(
                    dict(
                        record_id=observation_id(fields["kind"], symbol, "KRX", source_hash),
                        symbol=symbol,
                        venue="KRX",
                        session=session,
                        exchange_date=stamp.date(),
                        event_time=None if quote else utc(stamp),
                        exchange_date_basis="RECEIPT_DATE_UNVERIFIED"
                        if quote
                        else "SOURCE_BUSINESS_DATE",
                        source_time_of_day=row.get("BSOP_HOUR")
                        if quote
                        else row.get("STCK_CNTG_HOUR"),
                        received_at=utc(received_at),
                        acquired_at=utc(received_at),
                        available_at=utc(received_at),
                        availability_method="OBSERVED_LIVE",
                        availability_evidence="OBSERVED_STREAM_RECEIPT",
                        complete=True,
                        timestamp_precision="SECOND",
                        source_hash=source_hash,
                        parser_version="kis-ws-km001-1",
                        quality_flags=tuple(flags),
                        data_origin=data_origin,
                    )
                    | fields
                )
            )
        return tuple(result)
    except (ValueError, KeyError, TypeError, ArithmeticError):
        raise DataError("INVALID_STREAM_PAYLOAD") from None


class KISStream(OrdersBlocked):
    def __init__(
        self,
        config: BrokerConfig,
        permit: NetworkPermit,
        auth: KISAuth,
        clock: Clock,
        max_subscriptions: int,
        heartbeat_timeout: timedelta,
        connector: Callable[[str], Socket] = connect_socket,
        snapshot_provider: Callable[[tuple[str, ...]], tuple[Observation, ...]] | None = None,
    ) -> None:
        if not 1 <= max_subscriptions <= 100 or heartbeat_timeout <= timedelta(0):
            raise ValueError("explicit subscription budget and health interval required")
        self.config, self.permit, self.auth, self.clock = config, permit, auth, clock
        self.maximum, self.health_timeout, self.connector = (
            max_subscriptions,
            heartbeat_timeout,
            connector,
        )
        self.snapshot_provider = snapshot_provider
        self.state = StreamState()
        self.socket: Socket | None = None
        self.approval: SecretStr | None = None
        self.desired: set[tuple[str, str]] = set()
        self.active: set[tuple[str, str]] = set()
        self.pending_unsubscribe: set[tuple[str, str]] = set()
        self.last_received: datetime | None = None
        self.gaps: list[dict[str, str | int]] = []
        self.synced_symbols: set[str] = set()

    def plan(self, held_symbols: tuple[str, ...], candidates: tuple[str, ...]) -> tuple[str, ...]:
        allowed = set(self.permit.policy.symbols)
        if not set(held_symbols) <= allowed:
            raise PermissionError(
                "held symbols outside scope; monitoring cannot be silently dropped"
            )
        ordered = list(dict.fromkeys((*held_symbols, *candidates)))
        if not set(ordered) <= allowed or len(set(held_symbols)) * 2 > self.maximum:
            raise PermissionError("subscription budget cannot monitor holdings")
        return tuple(ordered[: self.maximum // 2])

    def connect(self) -> None:
        self.permit.consume()
        self.approval = self.auth.approval(self.config)
        try:
            self.socket = self.connector(WS_ENDPOINTS[self.config.environment])
            self.state = self.state.reconnect()
            self.last_received = self.clock.now()
            self.active.clear()
            self.pending_unsubscribe.clear()
            self.synced_symbols.clear()
            for tr_id, symbol in sorted(self.desired):
                self._send(tr_id, symbol, "1")
        except Exception:
            self.disconnect()
            raise DataError("STREAM_CONNECTION_FAILED") from None

    def _send(self, tr_id: str, symbol: str, action: Literal["0", "1"]) -> None:
        if self.socket is None or self.approval is None:
            raise DataError("STREAM_DISCONNECTED")
        message = {
            "header": {
                "approval_key": self.approval.get_secret_value(),
                "custtype": "P",
                "tr_type": action,
                "content-type": "utf-8",
            },
            "body": {"input": {"tr_id": tr_id, "tr_key": symbol}},
        }
        try:
            self.socket.send(json.dumps(message))
        except Exception:
            self.disconnect()
            raise DataError("STREAM_SEND_FAILED") from None

    def subscribe(self, tr_id: str, symbol: str) -> None:
        if tr_id not in WS_COLUMNS or symbol not in self.permit.policy.symbols:
            raise PermissionError("stream capability denied")
        key = (tr_id, symbol)
        if key in self.desired:
            return
        if len(self.desired) >= self.maximum:
            raise PermissionError("subscription budget exhausted")
        self.desired.add(key)
        self.state = StreamState(state="SYNCING", generation=self.state.generation)
        if self.socket:
            self._send(tr_id, symbol, "1")

    def unsubscribe(self, tr_id: str, symbol: str) -> None:
        key = (tr_id, symbol)
        if key not in self.desired:
            return
        if self.socket:
            self._send(tr_id, symbol, "0")
            self.pending_unsubscribe.add(key)
        self.desired.discard(key)
        self.active.discard(key)
        self.synced_symbols.discard(symbol)
        self.state = StreamState(state="SYNCING", generation=self.state.generation)

    def mark_synced(self, generation: int, snapshots: tuple[Observation, ...]) -> None:
        if generation != self.state.generation or self.active != self.desired or not self.desired:
            raise ValueError("subscriptions not acknowledged or stale sync generation")
        for snapshot in snapshots:
            snapshot.require_strategy_input(self.clock.now())
            if (
                snapshot.event_time is None
                or self.clock.now() - snapshot.event_time > self.health_timeout
            ):
                raise ValueError("snapshot source time is missing or stale")
            if snapshot.received_at < (self.last_received or self.clock.now()):
                raise ValueError("snapshot predates current stream receipt")
        symbols = {s.symbol for s in snapshots if s.kind == "QUOTE" and s.venue == "KRX"}
        if symbols != {symbol for _, symbol in self.desired}:
            raise ValueError("fresh quote snapshots required for every subscription symbol")
        self.synced_symbols = symbols
        self.state = self.state.mark_ready(generation)

    def healthy(self) -> bool:
        return bool(
            self.state.state == "READY"
            and self.last_received is not None
            and self.clock.now() - self.last_received <= self.health_timeout
        )

    def receive(self) -> tuple[Observation, ...]:
        if self.socket is None:
            raise DataError("STREAM_DISCONNECTED")
        try:
            message = self.socket.recv(timeout=self.health_timeout.total_seconds())
            text = message.decode("utf-8") if isinstance(message, bytes) else message
            if text.startswith("{"):
                response = json.loads(text)
                header = response["header"]
                if header["tr_id"] == "PINGPONG":
                    self.socket.pong(text.encode())
                else:
                    key = (header["tr_id"], header["tr_key"])
                    if response["body"]["rt_cd"] != "0":
                        raise DataError("SUBSCRIPTION_REJECTED")
                    if key in self.pending_unsubscribe:
                        self.pending_unsubscribe.discard(key)
                    elif key in self.desired:
                        self.active.add(key)
                    else:
                        raise DataError("UNEXPECTED_SUBSCRIPTION_ACK")
                self.last_received = self.clock.now()
                return ()
            observations = parse_frame(text, self.clock.now())
            if any((text.split("|", 3)[1], r.symbol) not in self.active for r in observations):
                raise DataError("UNSUBSCRIBED_DATA")
            self.last_received = self.clock.now()
            if not self.healthy():
                observations = tuple(
                    Observation.model_validate(
                        r.model_dump()
                        | {"quality_flags": (*r.quality_flags, "STREAM_NOT_SYNCHRONIZED")}
                    )
                    for r in observations
                )
            return observations
        except Exception:
            self.disconnect()
            raise DataError("STREAM_RECEIVE_FAILED") from None

    def disconnect(self) -> None:
        self.gaps.append(
            {
                "generation": self.state.generation,
                "detected_at": self.clock.now().isoformat(),
                "reason": "DISCONNECTED_OR_INVALID_DATA",
            }
        )
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
        self.socket = None
        self.approval = None
        self.active.clear()
        self.synced_symbols.clear()
        self.state = StreamState(state="GAP", generation=self.state.generation)

    def collect(
        self, count: int, reconnect_attempts: int = 2, sleep: Callable[[float], None] = time.sleep
    ) -> tuple[Observation, ...]:
        if not 1 <= count <= 100 or not 0 <= reconnect_attempts <= 3:
            raise ValueError("bounded stream collection required")
        result: list[Observation] = []
        remaining = reconnect_attempts
        for _ in range(count):
            try:
                if self.socket is None:
                    self.connect()
                result.extend(self.receive())
                if (
                    self.state.state == "SYNCING"
                    and self.desired
                    and self.active == self.desired
                    and self.snapshot_provider is not None
                ):
                    symbols = tuple(sorted({symbol for _, symbol in self.desired}))
                    snapshots = self.snapshot_provider(symbols)
                    self.mark_synced(self.state.generation, snapshots)
            except DataError:
                if remaining == 0:
                    raise
                remaining -= 1
                sleep(float(2 ** (reconnect_attempts - remaining)))
                self.connect()
        return tuple(result)
