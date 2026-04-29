"""Tests for src.domain.exceptions hierarchy."""
from __future__ import annotations

import pytest

from src.domain.exceptions import (
    BrokerConnectionError,
    BrokerOrderError,
    CapitalAllocationExceededError,
    ClockSkewError,
    ConfigurationError,
    DataIntegrityError,
    DomainError,
    ExternalSystemError,
    InsufficientBalanceError,
    IntegrityError,
    InvalidPriceError,
    MarketDataUnavailableError,
    MaxSplitReachedError,
    StateMismatchError,
    TradingSystemError,
)


class TestRootHierarchy:
    def test_trading_system_error_is_exception(self):
        assert issubclass(TradingSystemError, Exception)

    @pytest.mark.parametrize(
        "cls",
        [DomainError, ExternalSystemError, IntegrityError],
    )
    def test_top_level_branches_inherit_root(self, cls):
        assert issubclass(cls, TradingSystemError)


class TestDomainErrorBranch:
    @pytest.mark.parametrize(
        "cls",
        [
            InsufficientBalanceError,
            CapitalAllocationExceededError,
            MaxSplitReachedError,
            InvalidPriceError,
        ],
    )
    def test_subclass_inherits_domain_error(self, cls):
        assert issubclass(cls, DomainError)
        assert issubclass(cls, TradingSystemError)

    def test_can_be_caught_at_branch_level(self):
        with pytest.raises(DomainError):
            raise InsufficientBalanceError("not enough cash")


class TestExternalSystemErrorBranch:
    @pytest.mark.parametrize(
        "cls",
        [
            BrokerConnectionError,
            BrokerOrderError,
            MarketDataUnavailableError,
            DataIntegrityError,
        ],
    )
    def test_subclass_inherits_external_system_error(self, cls):
        assert issubclass(cls, ExternalSystemError)
        assert issubclass(cls, TradingSystemError)

    def test_can_be_caught_at_branch_level(self):
        with pytest.raises(ExternalSystemError):
            raise BrokerConnectionError("network down")


class TestIntegrityErrorBranch:
    @pytest.mark.parametrize(
        "cls",
        [StateMismatchError, ClockSkewError, ConfigurationError],
    )
    def test_subclass_inherits_integrity_error(self, cls):
        assert issubclass(cls, IntegrityError)
        assert issubclass(cls, TradingSystemError)

    def test_can_be_caught_at_branch_level(self):
        with pytest.raises(IntegrityError):
            raise StateMismatchError("DB != broker")


class TestBranchesAreDisjoint:
    """Domain / External / Integrity must not be cross-inherited."""

    def test_domain_is_not_external(self):
        assert not issubclass(DomainError, ExternalSystemError)
        assert not issubclass(ExternalSystemError, DomainError)

    def test_domain_is_not_integrity(self):
        assert not issubclass(DomainError, IntegrityError)
        assert not issubclass(IntegrityError, DomainError)

    def test_external_is_not_integrity(self):
        assert not issubclass(ExternalSystemError, IntegrityError)
        assert not issubclass(IntegrityError, ExternalSystemError)
