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


class SlotState(StrEnum):
    """SplitSlot state (Phase 0.5 / ADR 0002 §3.1).

    EMPTY  — no current entry; slot may carry last_exit_* history for
             reentry policy F (HybridTimeBasedReentry).
    FILLED — entry holds a SplitEntry. quantity/avg_price/split_level
             include this slot.
    """

    EMPTY = "EMPTY"
    FILLED = "FILLED"


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

    @property
    def fqn(self) -> str:
        """Fully qualified name: 'EXCHANGE:CODE' (e.g. 'KRX:069500').

        Plain property (not @computed_field) so the value is NOT included in
        ``model_dump`` / ``model_dump_json`` output. Repository adapters store
        ``asset_fqn`` as a separate column for indexed lookup, so duplicating
        it inside ``asset_json`` would cause round-trip rejection by the
        Asset model's ``extra="forbid"`` config.
        """
        return f"{self.exchange.value}:{self.code}"

    def round_to_tick(self, price: Decimal) -> Decimal:
        """Floor `price` to the nearest `tick_size` multiple.

        Used for LIMIT order pricing per CLAUDE.md §4.2: a buy LIMIT placed
        at-or-below the conceptual target is conservative — flooring to a
        valid tick guarantees the price is acceptable to the exchange.
        """
        return (price // self.tick_size) * self.tick_size


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


class SplitEntry(ValueObject):
    """A single completed split-buy record (one of N entries on a Position).

    Conceptually the "one of seven accounts" of 세븐 스플릿 modelled inside a
    single-account implementation. Per CLAUDE.md §4.4 and ADR §7.5/§7.9, only
    fully FILLED orders produce a SplitEntry; PARTIALLY_FILLED fills do NOT
    (they remain visible only via Position.pending_partial_quantity).

    Fields:
    - split_number    : 1-indexed position within the split sequence (1..7,
                        matches the upper bound of Position.split_level).
    - entry_date      : business date of the buy (no timezone — it is a market
                        local date, not a UTC instant).
    - quantity        : filled quantity (> 0).
    - entry_price     : fill price (> 0).
    - idempotency_key : the OrderRequest.idempotency_key that produced this
                        entry, linking back to the order trail.
    """

    split_number: int = Field(ge=1, le=7)
    entry_date: date
    quantity: Decimal = Field(gt=Decimal(0))
    entry_price: Decimal = Field(gt=Decimal(0))
    idempotency_key: str = Field(min_length=1, max_length=64)

    @field_validator("quantity", "entry_price", mode="before")
    @classmethod
    def _coerce_decimal(cls, v: object) -> Decimal:
        return _to_decimal(v)


class SplitSlot(ValueObject):
    """One of N split slots in a Position (Phase 0.5 / ADR 0002 §3.1).

    Represents the "one of seven accounts" of 세븐 스플릿 explicitly. Each
    slot transitions EMPTY ↔ FILLED across sell-and-reentry cycles. When a
    slot is sold, ``state`` becomes EMPTY and ``last_exit_price`` /
    ``last_exit_date`` capture the exit so a HybridTimeBasedReentry can
    decide whether to use the exit price or current market price as the
    reentry trigger anchor.

    Invariants (model_validator):
    - state == FILLED ⇔ entry is not None
    - state == FILLED ⇒ entry.split_number == slot_number
    - last_exit_date is not None ⇒ last_exit_price is not None

    sparse split_number is allowed: a Position may have slot 2 EMPTY while
    slot 3 is FILLED. The Phase 0 ``1, 2, …, split_level`` sequential
    invariant is dropped.
    """

    slot_number: int = Field(ge=1, le=7)
    state: SlotState
    entry: SplitEntry | None = None
    last_exit_price: Decimal | None = None
    last_exit_date: date | None = None

    @field_validator("last_exit_price", mode="before")
    @classmethod
    def _coerce_exit_price(cls, v: object) -> Decimal | None:
        if v is None:
            return None
        out = _to_decimal(v)
        if out <= 0:
            raise ValueError(f"last_exit_price must be > 0, got {out}")
        return out

    @model_validator(mode="after")
    def _check_consistency(self) -> SplitSlot:
        if self.state is SlotState.FILLED:
            if self.entry is None:
                raise ValueError(
                    f"FILLED slot {self.slot_number} requires entry"
                )
            if self.entry.split_number != self.slot_number:
                raise ValueError(
                    f"slot.entry.split_number ({self.entry.split_number}) "
                    f"must equal slot_number ({self.slot_number})"
                )
        elif self.entry is not None:
            raise ValueError(
                f"EMPTY slot {self.slot_number} must not carry an entry"
            )
        if self.last_exit_date is not None and self.last_exit_price is None:
            raise ValueError(
                "last_exit_date is set but last_exit_price is None"
            )
        return self

    @classmethod
    def empty(
        cls,
        slot_number: int,
        *,
        last_exit_price: Decimal | None = None,
        last_exit_date: date | None = None,
    ) -> SplitSlot:
        """Build an EMPTY slot, optionally carrying exit history."""
        return cls(
            slot_number=slot_number,
            state=SlotState.EMPTY,
            entry=None,
            last_exit_price=last_exit_price,
            last_exit_date=last_exit_date,
        )

    @classmethod
    def filled(
        cls,
        entry: SplitEntry,
        *,
        last_exit_price: Decimal | None = None,
        last_exit_date: date | None = None,
    ) -> SplitSlot:
        """Build a FILLED slot from an entry. slot_number is taken from
        entry.split_number to enforce the consistency invariant up-front.
        """
        return cls(
            slot_number=entry.split_number,
            state=SlotState.FILLED,
            entry=entry,
            last_exit_price=last_exit_price,
            last_exit_date=last_exit_date,
        )


class PositionValuation(ValueObject):
    """Mark-to-market snapshot of a single Position.

    Captures (asset, quantity, avg_price, market_price) at a moment in time
    plus the derived market_value and unrealized PnL. Per ADR §8.6 the
    quantity is the Position.quantity total — partial fills above entries
    are valued together with completed splits (option A: Position.quantity
    is the single source of truth).

    Invariants:
        - market_value.amount == quantity * market_price
        - unrealized_pnl.amount == (market_price - avg_price) * quantity
        - market_value.currency == unrealized_pnl.currency == asset.currency
        - quantity > 0  (you don't value an empty position)
    """

    asset: Asset
    quantity: Decimal = Field(gt=Decimal(0))
    avg_price: Decimal = Field(gt=Decimal(0))
    market_price: Decimal = Field(gt=Decimal(0))
    market_value: Money
    unrealized_pnl: Money
    split_level: int = Field(ge=0, le=7)

    @field_validator("quantity", "avg_price", "market_price", mode="before")
    @classmethod
    def _coerce_decimal(cls, v: object) -> Decimal:
        return _to_decimal(v)

    @model_validator(mode="after")
    def _check_invariants(self) -> PositionValuation:
        expected_market_value = self.quantity * self.market_price
        if self.market_value.amount != expected_market_value:
            raise ValueError(
                f"market_value.amount ({self.market_value.amount}) must equal "
                f"quantity * market_price ({expected_market_value})"
            )
        expected_pnl = (self.market_price - self.avg_price) * self.quantity
        if self.unrealized_pnl.amount != expected_pnl:
            raise ValueError(
                f"unrealized_pnl.amount ({self.unrealized_pnl.amount}) must "
                f"equal (market_price - avg_price) * quantity ({expected_pnl})"
            )
        if self.market_value.currency is not self.asset.currency:
            raise ValueError(
                f"market_value.currency ({self.market_value.currency.value}) "
                f"!= asset.currency ({self.asset.currency.value})"
            )
        if self.unrealized_pnl.currency is not self.asset.currency:
            raise ValueError(
                f"unrealized_pnl.currency ({self.unrealized_pnl.currency.value})"
                f" != asset.currency ({self.asset.currency.value})"
            )
        return self

    @property
    def unrealized_pnl_pct(self) -> Decimal:
        """Unrealized return percent (price-only). Excludes fees/taxes."""
        return (
            (self.market_price - self.avg_price) / self.avg_price * Decimal(100)
        )

    @classmethod
    def from_position(
        cls, position: Position, market_price: Decimal
    ) -> PositionValuation:
        """Build a valuation for `position` at `market_price`.

        The factory does the math; the model_validator double-checks.
        Caller is responsible for ensuring market_price comes from a
        trusted MarketDataPort source.
        """
        if position.quantity <= 0:
            raise ValueError(
                "Cannot value a position with non-positive quantity "
                f"({position.quantity})"
            )
        currency = position.asset.currency
        return cls(
            asset=position.asset,
            quantity=position.quantity,
            avg_price=position.avg_price,
            market_price=market_price,
            market_value=Money(
                amount=position.quantity * market_price, currency=currency
            ),
            unrealized_pnl=Money(
                amount=(market_price - position.avg_price) * position.quantity,
                currency=currency,
            ),
            split_level=position.split_level,
        )


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------
class Position(DomainModel):
    """Current holding for one asset, with per-slot state (Phase 0.5).

    Phase 0.5 (ADR 0002 §3) replaces the Phase 0 ``entries: list[SplitEntry]``
    with ``slots: list[SplitSlot]`` to support per-slot independent
    sell-and-reentry. Each slot transitions EMPTY ↔ FILLED across cycles;
    its ``last_exit_*`` history feeds HybridTimeBasedReentry.

    ``split_level`` is the count of FILLED slots — it can both increase
    (new buy) and decrease (sell). ``slots`` always holds
    ``max_split_count`` entries with ``slot_number`` 1..N (sparse
    FILLED/EMPTY pattern is allowed).

    Partial-fill policy (ADR 0002 §3.2.1):
        Phase 0.5 BLOCKS partial fills end-to-end (MockBroker enforces
        ``simulate_partial_fill_rate == 0``). The Phase 0 carry-over
        (``quantity > sum(entries)``) is dropped. This invariant is now
        an equality.

    Invariants enforced (model_validator):
        - len(slots) ∈ [1, 7]; slot_numbers are exactly 1..len(slots)
        - split_level == count(s for s in slots if s.state == FILLED)
        - quantity == sum(s.entry.quantity for FILLED slots)   (equality, no carry)
        - avg_price weighted-average matches FILLED slots when split_level > 0
        - quantity > 0 ⇒ avg_price > 0 and last_buy_at is set
        - quantity == 0 ⇒ avg_price == 0 (last_buy_at may persist as history)
    """

    asset: Asset
    quantity: Decimal
    avg_price: Decimal
    split_level: int = Field(ge=0, le=7)
    last_buy_at: datetime | None = None
    slots: list[SplitSlot]

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
        # 1. slots length and slot_number sequence
        n = len(self.slots)
        if not 1 <= n <= 7:
            raise ValueError(f"len(slots) must be in [1, 7], got {n}")
        expected = list(range(1, n + 1))
        actual = [s.slot_number for s in self.slots]
        if actual != expected:
            raise ValueError(
                f"slot_numbers must be sequential {expected}, got {actual}"
            )

        # 2. split_level == FILLED count
        filled = [s for s in self.slots if s.state is SlotState.FILLED]
        if self.split_level != len(filled):
            raise ValueError(
                f"split_level ({self.split_level}) must equal FILLED count "
                f"({len(filled)})"
            )

        # 3. quantity equals sum of FILLED slot quantities (no partial carry)
        expected_qty = sum(
            (s.entry.quantity for s in filled if s.entry is not None),
            Decimal(0),
        )
        if self.quantity != expected_qty:
            raise ValueError(
                f"quantity ({self.quantity}) must equal sum of FILLED slot "
                f"quantities ({expected_qty})"
            )

        # 4. avg_price weighted-average match (when there's any position)
        if filled:
            total_cost = sum(
                (
                    s.entry.quantity * s.entry.entry_price
                    for s in filled
                    if s.entry is not None
                ),
                Decimal(0),
            )
            expected_avg = total_cost / expected_qty
            if self.avg_price != expected_avg:
                raise ValueError(
                    f"avg_price ({self.avg_price}) must equal weighted "
                    f"average of FILLED slots ({expected_avg})"
                )

        # 5. invariants tied to quantity sign
        has_qty = self.quantity > 0
        if has_qty:
            if self.avg_price <= 0:
                raise ValueError("avg_price must be > 0 when quantity > 0")
            if self.last_buy_at is None:
                raise ValueError("last_buy_at required when quantity > 0")
        elif self.avg_price != 0:
            raise ValueError("avg_price must be 0 when quantity == 0")
        return self

    @classmethod
    def empty(cls, asset: Asset, *, max_split_count: int = 7) -> Position:
        """Construct an empty (no-position) holding with N EMPTY slots.

        Default max_split_count=7 matches the Phase 0.5 single-asset
        configuration. Phase 0.7 will plumb this through per-asset config.
        """
        if not 1 <= max_split_count <= 7:
            raise ValueError(
                f"max_split_count must be in [1, 7], got {max_split_count}"
            )
        return cls(
            asset=asset,
            quantity=Decimal(0),
            avg_price=Decimal(0),
            split_level=0,
            last_buy_at=None,
            slots=[
                SplitSlot.empty(slot_number=i)
                for i in range(1, max_split_count + 1)
            ],
        )

    # ------------------------------------------------------------------
    # Derived accessors
    # ------------------------------------------------------------------
    @property
    def max_split_count(self) -> int:
        """Number of slots configured for this Position. == len(self.slots)."""
        return len(self.slots)

    @property
    def filled_slots(self) -> list[SplitSlot]:
        """Slots in FILLED state, ordered by slot_number."""
        return [s for s in self.slots if s.state is SlotState.FILLED]

    @property
    def empty_slots(self) -> list[SplitSlot]:
        """Slots in EMPTY state, ordered by slot_number."""
        return [s for s in self.slots if s.state is SlotState.EMPTY]

    def next_empty_slot_number(self) -> int | None:
        """Smallest slot_number in EMPTY state, or None when all FILLED.

        Phase 0.5 uses this to decide which slot a new buy fills (lowest
        slot_number first — keeps the seven-account ordering deterministic).
        """
        for s in self.slots:
            if s.state is SlotState.EMPTY:
                return s.slot_number
        return None

    def get_slot(self, slot_number: int) -> SplitSlot | None:
        """Return the slot with the given slot_number, or None if out of range."""
        for s in self.slots:
            if s.slot_number == slot_number:
                return s
        return None

    def get_entry(self, slot_number: int) -> SplitEntry | None:
        """Return the SplitEntry of slot ``slot_number`` if FILLED, else None."""
        slot = self.get_slot(slot_number)
        if slot is None or slot.state is not SlotState.FILLED:
            return None
        return slot.entry

    def split_pnl(self, current_price: Decimal) -> dict[int, Decimal]:
        """Per-slot unrealized PnL in price units (FILLED slots only).

        Visualizes the seven-account view of 세븐 스플릿 within the
        single-account model. Caller passes the current spot price.
        """
        return {
            s.entry.split_number: (current_price - s.entry.entry_price)
            * s.entry.quantity
            for s in self.filled_slots
            if s.entry is not None
        }

    def split_pnl_pct(self, current_price: Decimal) -> dict[int, Decimal]:
        """Per-slot unrealized return percent (price-only, no fees)."""
        return {
            s.entry.split_number: (
                (current_price - s.entry.entry_price)
                / s.entry.entry_price
                * Decimal(100)
            )
            for s in self.filled_slots
            if s.entry is not None
        }


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


class PortfolioSnapshot(DomainModel):
    """End-of-day portfolio state for backtest/paper-trading metrics.

    Captures cash, per-position valuations, and roll-up totals at one
    moment. Per ADR §8.6 / §8.7 this is built by DailySnapshotBuilder
    after the orchestrator's decision flow completes.

    Phase 0: single currency (KRW). Phase 3+ multi-currency may extend.

    Invariants:
        - all Money fields share currency with `cash`
        - `valuations[*].asset.currency == cash.currency`
        - total_market_value == sum(v.market_value for v in valuations)
        - total_value == cash + total_market_value
        - total_cost_basis == sum(v.quantity * v.avg_price for v in valuations)
        - total_unrealized_pnl == sum(v.unrealized_pnl for v in valuations)
        - initial_capital.amount > 0  (for return calculation)
        - snapshot_at is UTC
    """

    snapshot_date: date
    snapshot_at: datetime
    initial_capital: Money
    cash: Money
    valuations: list[PositionValuation] = Field(default_factory=list)
    total_market_value: Money
    total_value: Money
    total_cost_basis: Money
    total_unrealized_pnl: Money

    @field_validator("snapshot_at")
    @classmethod
    def _utc_only(cls, v: datetime) -> datetime:
        return _ensure_utc(v)

    @model_validator(mode="after")
    def _check_invariants(self) -> PortfolioSnapshot:
        # initial_capital strictly positive (return-pct denominator)
        if self.initial_capital.amount <= 0:
            raise ValueError(
                f"initial_capital.amount must be > 0, "
                f"got {self.initial_capital.amount}"
            )

        # currency consistency: every Money + every valuation.asset must
        # match cash.currency
        currency = self.cash.currency
        for label, m in (
            ("initial_capital", self.initial_capital),
            ("total_market_value", self.total_market_value),
            ("total_value", self.total_value),
            ("total_cost_basis", self.total_cost_basis),
            ("total_unrealized_pnl", self.total_unrealized_pnl),
        ):
            if m.currency is not currency:
                raise ValueError(
                    f"{label}.currency ({m.currency.value}) != "
                    f"cash.currency ({currency.value})"
                )
        for v in self.valuations:
            if v.asset.currency is not currency:
                raise ValueError(
                    f"valuation for {v.asset.fqn} has currency "
                    f"{v.asset.currency.value}, expected {currency.value}"
                )

        # sum invariants
        expected_market_value = sum(
            (v.market_value.amount for v in self.valuations), Decimal(0)
        )
        if self.total_market_value.amount != expected_market_value:
            raise ValueError(
                f"total_market_value ({self.total_market_value.amount}) != "
                f"sum of valuations.market_value ({expected_market_value})"
            )
        expected_total_value = self.cash.amount + self.total_market_value.amount
        if self.total_value.amount != expected_total_value:
            raise ValueError(
                f"total_value ({self.total_value.amount}) != "
                f"cash + total_market_value ({expected_total_value})"
            )
        expected_cost_basis = sum(
            (v.quantity * v.avg_price for v in self.valuations), Decimal(0)
        )
        if self.total_cost_basis.amount != expected_cost_basis:
            raise ValueError(
                f"total_cost_basis ({self.total_cost_basis.amount}) != "
                f"sum of cost basis ({expected_cost_basis})"
            )
        expected_pnl = sum(
            (v.unrealized_pnl.amount for v in self.valuations), Decimal(0)
        )
        if self.total_unrealized_pnl.amount != expected_pnl:
            raise ValueError(
                f"total_unrealized_pnl ({self.total_unrealized_pnl.amount}) != "
                f"sum of valuations.unrealized_pnl ({expected_pnl})"
            )
        return self

    @property
    def total_return_pct(self) -> Decimal:
        """Total return percent vs initial_capital. Excludes deposits/withdrawals."""
        return (
            (self.total_value.amount - self.initial_capital.amount)
            / self.initial_capital.amount
            * Decimal(100)
        )

    @classmethod
    def build(
        cls,
        *,
        snapshot_date: date,
        snapshot_at: datetime,
        initial_capital: Money,
        cash: Money,
        valuations: list[PositionValuation],
    ) -> PortfolioSnapshot:
        """Build a snapshot computing totals from cash + valuations.

        Convenience factory. The model_validator double-checks the math.
        """
        currency = cash.currency
        total_market_value_amount = sum(
            (v.market_value.amount for v in valuations), Decimal(0)
        )
        total_cost_basis_amount = sum(
            (v.quantity * v.avg_price for v in valuations), Decimal(0)
        )
        total_unrealized_pnl_amount = sum(
            (v.unrealized_pnl.amount for v in valuations), Decimal(0)
        )
        return cls(
            snapshot_date=snapshot_date,
            snapshot_at=snapshot_at,
            initial_capital=initial_capital,
            cash=cash,
            valuations=valuations,
            total_market_value=Money(
                amount=total_market_value_amount, currency=currency
            ),
            total_value=Money(
                amount=cash.amount + total_market_value_amount,
                currency=currency,
            ),
            total_cost_basis=Money(
                amount=total_cost_basis_amount, currency=currency
            ),
            total_unrealized_pnl=Money(
                amount=total_unrealized_pnl_amount, currency=currency
            ),
        )
