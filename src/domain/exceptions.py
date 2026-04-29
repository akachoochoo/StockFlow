"""Exception hierarchy for SevenSplit domain.

See CLAUDE.md §6 for usage rules. The three top-level branches dictate caller
behavior:

- DomainError       -> normal flow; catch, record to Decision, continue
- ExternalSystemError -> external failure; retry or skip the affected asset
- IntegrityError    -> system invariant violated; STOP all trading
"""
from __future__ import annotations


class TradingSystemError(Exception):
    """Root of all SevenSplit errors. Do not raise directly; pick a subclass."""


# ---------------------------------------------------------------------------
# Domain errors — normal-flow exceptions.
# Catch at the orchestrator, log to Decision.reasoning, continue with next asset.
# ---------------------------------------------------------------------------
class DomainError(TradingSystemError):
    """Normal-flow domain exception."""


class InsufficientBalanceError(DomainError):
    """Cash balance is too low to place the requested order."""


class CapitalAllocationExceededError(DomainError):
    """Order would exceed the per-asset capital allocation cap."""


class MaxSplitReachedError(DomainError):
    """Position has already reached the maximum split level for the day."""


class InvalidPriceError(DomainError):
    """Price input is invalid (e.g. <= 0, or fails sanity check)."""


# ---------------------------------------------------------------------------
# External-system errors — retry or skip the affected asset; do not halt all.
# ---------------------------------------------------------------------------
class ExternalSystemError(TradingSystemError):
    """Failure communicating with an external system."""


class BrokerConnectionError(ExternalSystemError):
    """Broker API unreachable or returned a transport-level error."""


class BrokerOrderError(ExternalSystemError):
    """Broker rejected the order or returned a non-recoverable response."""


class MarketDataUnavailableError(ExternalSystemError):
    """Market data API failed or returned no data for the requested asset."""


class DataIntegrityError(ExternalSystemError):
    """External data violates basic integrity (e.g. high < low, negative price)."""


# ---------------------------------------------------------------------------
# Integrity errors — STOP all trading immediately.
# Never catch these silently; let them propagate to the top-level halt handler.
# ---------------------------------------------------------------------------
class IntegrityError(TradingSystemError):
    """System integrity violation. Halt all trading immediately."""


class StateMismatchError(IntegrityError):
    """DB state does not match the broker's reported state (reconciliation failed)."""


class ClockSkewError(IntegrityError):
    """System clock is out of sync (NTP drift > 1 second)."""


class ConfigurationError(IntegrityError):
    """Configuration is invalid or missing required fields."""
