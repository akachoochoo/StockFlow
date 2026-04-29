"""Domain models for SevenSplit.

Pure domain layer: only stdlib and pydantic imports allowed (CLAUDE.md §1.1).
No DB, HTTP, datetime.now(), pandas, or adapter imports here.

All money/quantity values are Decimal (CLAUDE.md §2.1) constructed from str/int
only — never float (§2.3). All datetimes are timezone-aware UTC (§3.1).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

# ---------------------------------------------------------------------------
# Helpers (private)
# ---------------------------------------------------------------------------
_UTC_OFFSET = timedelta(0)


def _to_decimal(v: object) -> Decimal:
    """Coerce numeric-like input to Decimal, rejecting float (CLAUDE.md §2.3).

    Accepts: Decimal, int, str. Rejects: float, bool, anything else.

    Raises ValueError so that pydantic's `field_validator(mode="before")` wraps
    it into ValidationError. Operator-time type checks (e.g. ``Money * float``)
    still raise TypeError directly because they are not field validators.
    """
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool):
        raise ValueError("Cannot construct Decimal from bool")
    if isinstance(v, float):
        raise ValueError(
            "Decimal must not be constructed from float; "
            "pass Decimal or str (CLAUDE.md §2.3)"
        )
    if isinstance(v, (int, str)):
        return Decimal(v)
    raise ValueError(f"Unsupported value type for Decimal: {type(v).__name__}")


def _ensure_utc(v: datetime) -> datetime:
    """Reject naive or non-UTC datetimes (CLAUDE.md §3.1)."""
    if v.tzinfo is None:
        raise ValueError("datetime must be timezone-aware (UTC)")
    if v.utcoffset() != _UTC_OFFSET:
        raise ValueError(f"datetime must be UTC, got offset {v.utcoffset()}")
    return v


# ---------------------------------------------------------------------------
# Base classes
# ---------------------------------------------------------------------------
class DomainModel(BaseModel):
    """Base class for entity-like domain models.

    Frozen + strict + extra='forbid' so accidental field typos and silent
    coercion are impossible. Subclasses inherit this config; override only
    when there is a concrete reason.
    """

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        validate_assignment=True,
    )


class ValueObject(BaseModel):
    """Base class for value objects (equality by all fields, no identity)."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        validate_assignment=True,
    )


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class Currency(StrEnum):
    """Supported currencies. KRW for Phase 0; USD/BTC arrive in later Phases."""

    KRW = "KRW"
    USD = "USD"


class Exchange(StrEnum):
    """Supported exchanges. Phase 0 = KRX only."""

    KRX = "KRX"


class AssetClass(StrEnum):
    """Asset class. Phase 0 trades KR_ETF only; KR_STOCK kept for Phase 1+."""

    KR_STOCK = "KR_STOCK"
    KR_ETF = "KR_ETF"


class OrderSide(StrEnum):
    """Order side.

    Phase 0 only generates BUY orders. SELL is defined for future phases;
    Strategy and Orchestrator code in Phase 0 must only emit BUY (see
    docs/roadmap.md Phase 0 scope and CLAUDE.md §14).
    """

    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    """Order type.

    Per CLAUDE.md §4.2, only LIMIT (지정가) is supported. Market orders are
    forbidden because slippage is unpredictable. Even closing-price strategies
    place LIMIT orders at or near the close price.
    """

    LIMIT = "LIMIT"


class OrderStatus(StrEnum):
    """Order lifecycle status."""

    PENDING = "PENDING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"  # indeterminate (e.g. timeout) — reconciliation required


class SignalLevel(StrEnum):
    """Circuit breaker level (design doc §3.4).

    NORMAL    — proceed normally
    CAUTION   — reduce new entries (typically 50%)
    HALT      — block new entries; keep existing positions
    EMERGENCY — reduce existing positions
    """

    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    HALT = "HALT"
    EMERGENCY = "EMERGENCY"


class SignalSource(StrEnum):
    """Origin of a circuit breaker signal."""

    NULL = "NULL"  # NullSignal adapter (Phase 0)
    RULE_BASED = "RULE_BASED"  # threshold rules (Phase 2)
    AI_BASED = "AI_BASED"  # LLM evaluator (Phase 2)
    MANUAL = "MANUAL"  # operator override


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------
class Money(ValueObject):
    """Monetary amount with explicit currency (CLAUDE.md §2)."""

    amount: Decimal
    currency: Currency

    @field_validator("amount", mode="before")
    @classmethod
    def _coerce_amount(cls, v: object) -> Decimal:
        return _to_decimal(v)

    def _check_same_currency(self, other: Money) -> None:
        if self.currency is not other.currency:
            raise ValueError(
                f"Currency mismatch: {self.currency.value} vs {other.currency.value}"
            )

    def __add__(self, other: Money) -> Money:
        self._check_same_currency(other)
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check_same_currency(other)
        return Money(amount=self.amount - other.amount, currency=self.currency)

    def __mul__(self, scalar: Decimal | int) -> Money:
        if isinstance(scalar, bool):
            raise TypeError("Cannot multiply Money by bool")
        if isinstance(scalar, float):
            raise TypeError("Cannot multiply Money by float; use Decimal or int")
        if not isinstance(scalar, (Decimal, int)):
            raise TypeError(
                f"Cannot multiply Money by {type(scalar).__name__}; use Decimal or int"
            )
        return Money(amount=self.amount * Decimal(scalar), currency=self.currency)

    def __rmul__(self, scalar: Decimal | int) -> Money:
        return self.__mul__(scalar)


class Asset(DomainModel):
    """Tradable asset (stock, ETF, etc.).

    Identified by (exchange, code) pair; `fqn` exposes the canonical form.
    """

    code: str = Field(min_length=1, max_length=20)
    exchange: Exchange
    asset_class: AssetClass
    currency: Currency
    name: str = Field(min_length=1, max_length=200)
    tick_size: Decimal = Field(gt=Decimal(0))
    lot_size: Decimal = Field(default=Decimal(1), gt=Decimal(0))

    @field_validator("tick_size", "lot_size", mode="before")
    @classmethod
    def _coerce_size(cls, v: object) -> Decimal:
        return _to_decimal(v)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def fqn(self) -> str:
        """Fully qualified name: 'EXCHANGE:CODE' (e.g. 'KRX:069500')."""
        return f"{self.exchange.value}:{self.code}"


class Price(ValueObject):
    """Spot price for an asset at a given UTC instant."""

    asset: Asset
    value: Decimal = Field(gt=Decimal(0))
    timestamp: datetime

    @field_validator("value", mode="before")
    @classmethod
    def _coerce_value(cls, v: object) -> Decimal:
        return _to_decimal(v)

    @field_validator("timestamp")
    @classmethod
    def _utc_only(cls, v: datetime) -> datetime:
        return _ensure_utc(v)


class Balance(ValueObject):
    """Available trading capital."""

    cash: Money


class OHLCV(ValueObject):
    """Daily Open/High/Low/Close/Volume bar.

    `trade_date` is the local market business date (no timezone) since trading
    days are a market concept, not a UTC instant. Adapters convert market-local
    dates to UTC instants when needed (e.g. for the `as_of` parameter on
    intraday queries).

    Integrity invariants enforced here implement CLAUDE.md §5.1: high >= low,
    open and close in [low, high]. Volume may be 0 (e.g. trading halt day).
    """

    asset: Asset
    trade_date: date
    open: Decimal = Field(gt=Decimal(0))
    high: Decimal = Field(gt=Decimal(0))
    low: Decimal = Field(gt=Decimal(0))
    close: Decimal = Field(gt=Decimal(0))
    volume: Decimal = Field(ge=Decimal(0))

    @field_validator("open", "high", "low", "close", "volume", mode="before")
    @classmethod
    def _coerce_decimal(cls, v: object) -> Decimal:
        return _to_decimal(v)

    @model_validator(mode="after")
    def _check_ohlc_consistency(self) -> OHLCV:
        if self.high < self.low:
            raise ValueError(f"high ({self.high}) < low ({self.low})")
        if not (self.low <= self.open <= self.high):
            raise ValueError(
                f"open ({self.open}) outside [low={self.low}, high={self.high}]"
            )
        if not (self.low <= self.close <= self.high):
            raise ValueError(
                f"close ({self.close}) outside [low={self.low}, high={self.high}]"
            )
        return self


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------
class Position(DomainModel):
    """Current holding for one asset.

    `split_level` tracks how many split-buys have *fully* completed (0 = no
    completed splits, 1~7 = 1st through 7th split filled). Per CLAUDE.md §4.4,
    only fully filled orders increment split_level; partial fills do NOT.

    Therefore the invariant `quantity > 0 -> split_level >= 1` does NOT hold:
    a position may have quantity > 0 with split_level == 0 if it consists
    entirely of partial fills that have not yet reached a full split.
    """

    asset: Asset
    quantity: Decimal
    avg_price: Decimal
    split_level: int = Field(ge=0, le=7)
    last_buy_at: datetime | None = None

    @field_validator("quantity", "avg_price", mode="before")
    @classmethod
    def _coerce_decimal(cls, v: object) -> Decimal:
        return _to_decimal(v)

    @field_validator("quantity")
    @classmethod
    def _non_negative_qty(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError(f"quantity must be >= 0, got {v}")
        return v

    @field_validator("avg_price")
    @classmethod
    def _non_negative_avg(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError(f"avg_price must be >= 0, got {v}")
        return v

    @field_validator("last_buy_at")
    @classmethod
    def _utc_only(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        return _ensure_utc(v)

    @model_validator(mode="after")
    def _check_consistency(self) -> Position:
        has_qty = self.quantity > 0
        if has_qty:
            if self.avg_price <= 0:
                raise ValueError("avg_price must be > 0 when quantity > 0")
            if self.last_buy_at is None:
                raise ValueError("last_buy_at required when quantity > 0")
        else:
            if self.split_level != 0:
                raise ValueError("split_level must be 0 when quantity == 0")
            if self.avg_price != 0:
                raise ValueError("avg_price must be 0 when quantity == 0")
        return self

    @classmethod
    def empty(cls, asset: Asset) -> Position:
        """Construct an empty (no-position) holding for the given asset."""
        return cls(
            asset=asset,
            quantity=Decimal(0),
            avg_price=Decimal(0),
            split_level=0,
            last_buy_at=None,
        )


class OrderRequest(DomainModel):
    """Order submission to the broker. CLAUDE.md §4.1 requires idempotency_key."""

    idempotency_key: str = Field(min_length=1, max_length=64)
    asset: Asset
    side: OrderSide
    order_type: OrderType
    quantity: Decimal = Field(gt=Decimal(0))
    target_price: Decimal = Field(gt=Decimal(0))

    @field_validator("quantity", "target_price", mode="before")
    @classmethod
    def _coerce_decimal(cls, v: object) -> Decimal:
        return _to_decimal(v)


class OrderResult(DomainModel):
    """Broker response for an OrderRequest.

    `idempotency_key` matches the request. `asset` is the same asset as the
    originating OrderRequest; carrying it on the result avoids round-trips
    through a request-side store when the orchestrator updates positions.
    `broker_order_id` may be None when the order is rejected before reaching
    the broker. `status == UNKNOWN` indicates indeterminate state (e.g.
    timeout) — reconciliation required (CLAUDE.md §4.3).
    """

    idempotency_key: str = Field(min_length=1, max_length=64)
    asset: Asset
    broker_order_id: str | None
    status: OrderStatus
    filled_quantity: Decimal
    filled_price: Decimal | None
    submitted_at: datetime
    filled_at: datetime | None

    @field_validator("filled_quantity", mode="before")
    @classmethod
    def _coerce_filled_qty(cls, v: object) -> Decimal:
        return _to_decimal(v)

    @field_validator("filled_price", mode="before")
    @classmethod
    def _coerce_filled_price(cls, v: object) -> Decimal | None:
        if v is None:
            return None
        return _to_decimal(v)

    @field_validator("filled_quantity")
    @classmethod
    def _non_negative_filled(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError(f"filled_quantity must be >= 0, got {v}")
        return v

    @field_validator("filled_price")
    @classmethod
    def _positive_filled_price(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v <= 0:
            raise ValueError(f"filled_price must be > 0 when present, got {v}")
        return v

    @field_validator("submitted_at")
    @classmethod
    def _submitted_utc(cls, v: datetime) -> datetime:
        return _ensure_utc(v)

    @field_validator("filled_at")
    @classmethod
    def _filled_utc(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        return _ensure_utc(v)


class Order(DomainModel):
    """Persistent order record (request + lifecycle state).

    Stored in the `orders` table (CLAUDE.md §3.3). Combines OrderRequest input
    fields with OrderResult lifecycle fields so that a single row captures the
    whole order. Use `from_request_result` to construct from the two pieces.
    """

    idempotency_key: str = Field(min_length=1, max_length=64)
    asset: Asset
    side: OrderSide
    order_type: OrderType
    quantity: Decimal = Field(gt=Decimal(0))
    target_price: Decimal = Field(gt=Decimal(0))
    status: OrderStatus
    broker_order_id: str | None
    filled_quantity: Decimal
    filled_price: Decimal | None
    submitted_at: datetime
    filled_at: datetime | None

    @field_validator(
        "quantity",
        "target_price",
        "filled_quantity",
        mode="before",
    )
    @classmethod
    def _coerce_decimal(cls, v: object) -> Decimal:
        return _to_decimal(v)

    @field_validator("filled_price", mode="before")
    @classmethod
    def _coerce_filled_price(cls, v: object) -> Decimal | None:
        if v is None:
            return None
        return _to_decimal(v)

    @field_validator("filled_quantity")
    @classmethod
    def _non_negative_filled(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError(f"filled_quantity must be >= 0, got {v}")
        return v

    @field_validator("filled_price")
    @classmethod
    def _positive_filled_price(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v <= 0:
            raise ValueError(f"filled_price must be > 0 when present, got {v}")
        return v

    @field_validator("submitted_at")
    @classmethod
    def _submitted_utc(cls, v: datetime) -> datetime:
        return _ensure_utc(v)

    @field_validator("filled_at")
    @classmethod
    def _filled_utc(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        return _ensure_utc(v)

    @model_validator(mode="after")
    def _check_status_consistency(self) -> Order:
        if self.status == OrderStatus.FILLED:
            if self.broker_order_id is None:
                raise ValueError("FILLED order requires broker_order_id")
            if self.filled_at is None:
                raise ValueError("FILLED order requires filled_at")
            if self.filled_price is None:
                raise ValueError("FILLED order requires filled_price")
            if self.filled_quantity != self.quantity:
                raise ValueError(
                    f"FILLED order: filled_quantity ({self.filled_quantity}) "
                    f"!= quantity ({self.quantity})"
                )
        elif self.status == OrderStatus.PARTIALLY_FILLED:
            if self.broker_order_id is None:
                raise ValueError("PARTIALLY_FILLED order requires broker_order_id")
            if self.filled_quantity <= 0:
                raise ValueError("PARTIALLY_FILLED requires filled_quantity > 0")
            if self.filled_quantity >= self.quantity:
                raise ValueError(
                    "PARTIALLY_FILLED filled_quantity must be < quantity"
                )
        elif self.status == OrderStatus.PENDING:
            if self.filled_quantity != 0:
                raise ValueError("PENDING order requires filled_quantity == 0")
        return self

    @classmethod
    def from_request_result(cls, request: OrderRequest, result: OrderResult) -> Order:
        if request.idempotency_key != result.idempotency_key:
            raise ValueError(
                "idempotency_key mismatch: "
                f"request={request.idempotency_key}, result={result.idempotency_key}"
            )
        if request.asset != result.asset:
            raise ValueError(
                "asset mismatch: "
                f"request={request.asset.fqn}, result={result.asset.fqn}"
            )
        return cls(
            idempotency_key=request.idempotency_key,
            asset=request.asset,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            target_price=request.target_price,
            status=result.status,
            broker_order_id=result.broker_order_id,
            filled_quantity=result.filled_quantity,
            filled_price=result.filled_price,
            submitted_at=result.submitted_at,
            filled_at=result.filled_at,
        )


class Decision(DomainModel):
    """Daily decision log entry (CLAUDE.md §8.1).

    `reasoning` MUST contain every input value that contributed to the decision,
    so the decision can be replayed/debugged six months later. Values are
    stringified for stable JSON storage; richer types come at adapter boundary.
    """

    timestamp: datetime
    asset: Asset
    action: str = Field(min_length=1, max_length=100)
    reasoning: dict[str, str]
    resulting_order_id: str | None = None

    @field_validator("timestamp")
    @classmethod
    def _utc_only(cls, v: datetime) -> datetime:
        return _ensure_utc(v)


class CircuitBreakerSignal(DomainModel):
    """Circuit breaker decision for one asset class at one point in time.

    Per design doc §3.4, the decision aggregates rule-based and AI judgments
    when present; the stricter level wins. Phase 0 only uses NullSignal which
    always returns level=NORMAL, source=NULL with no triggers.

    Fields:
    - level         : computed severity (NORMAL/CAUTION/HALT/EMERGENCY)
    - source        : where the decision came from (NULL/RULE/AI/MANUAL)
    - asset_class   : which asset class this signal applies to
    - evaluated_at  : UTC; when the signal was computed
    - triggered_by  : list of rule/input names that contributed (may be empty)
    - reasoning     : input values used (stringified for JSON storage)
    - valid_until   : UTC; instant after which this signal must be re-evaluated
    """

    level: SignalLevel
    source: SignalSource
    asset_class: AssetClass
    evaluated_at: datetime
    triggered_by: list[str]
    reasoning: dict[str, str]
    valid_until: datetime

    @field_validator("evaluated_at", "valid_until")
    @classmethod
    def _utc_only(cls, v: datetime) -> datetime:
        return _ensure_utc(v)

    @model_validator(mode="after")
    def _check_validity_window(self) -> CircuitBreakerSignal:
        if self.valid_until <= self.evaluated_at:
            raise ValueError(
                f"valid_until ({self.valid_until}) must be > "
                f"evaluated_at ({self.evaluated_at})"
            )
        return self
