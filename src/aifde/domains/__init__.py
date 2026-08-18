"""First-party Domain Packs used by Shipyard build and evaluation examples."""

from .base import DomainAdapter, DomainCapture, DomainCompiler
from aifde.platform.domain_pack import DomainPack
from .software_delivery import SoftwareDeliveryDomain
from .supplier_delay import SupplierDelayDomain


class DomainAdapterRegistry:
    """Explicit registry that prevents an unknown pack from silently falling back."""

    def __init__(self, adapters: tuple[DomainAdapter, ...] | None = None) -> None:
        values = adapters or (SupplierDelayDomain(), SoftwareDeliveryDomain())
        self._adapters = {adapter.pack.pack_id: adapter for adapter in values}
        if len(self._adapters) != len(values):
            raise ValueError("domain pack ids must be unique")

    def get(self, pack_id: str) -> DomainAdapter:
        if not isinstance(pack_id, str) or not pack_id.strip():
            raise ValueError("domain_pack_id must not be empty")
        try:
            return self._adapters[pack_id.strip()]
        except KeyError as exc:
            raise KeyError(f"unknown domain pack: {pack_id}") from exc

    def list(self) -> tuple[DomainPack, ...]:
        return tuple(self._adapters[key].pack for key in sorted(self._adapters))


__all__ = [
    "DomainAdapter",
    "DomainAdapterRegistry",
    "DomainCapture",
    "DomainCompiler",
    "SoftwareDeliveryDomain",
    "SupplierDelayDomain",
]
