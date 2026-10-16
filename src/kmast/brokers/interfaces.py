from typing import Protocol

from kmast.core.config import require_order_permission


class ReadBroker(Protocol):
    def read(self, operation: str) -> dict[str, str]: ...


class OrdersBlocked:
    def submit_order(self) -> None:
        require_order_permission()

    def cancel_order(self) -> None:
        require_order_permission()


class MockBroker(OrdersBlocked):
    """Offline fixtures only; does not simulate exchange fills or accounting."""

    def read(self, operation: str) -> dict[str, str]:
        if operation not in {"quote", "balance"}:
            raise ValueError("unknown read operation")
        return {"operation": operation, "source": "SYNTHETIC_MOCK", "status": "OK"}
