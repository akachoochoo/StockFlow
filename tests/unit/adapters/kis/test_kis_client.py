"""Unit tests for src.adapters.kis._client — KISClient (Phase 1.1 Stage 2.3).

Uses a fake ``HttpClient`` (records calls, returns canned responses) + fixed
``clock`` + no-op ``sleep`` — **zero real network**.

Coverage:
- TR_ID paper conversion (T/J/C → V in PAPER mode; F 시세 unchanged).
- Header construction (authorization Bearer / appkey / custtype / tr_id).
- Throttle: sequential calls respect min-interval (sleep called with positive).
- rt_cd != "0" → KISApiError (no secret in message).
- Non-2xx HTTP → KISApiError (no secret in message).
- No automatic retry — exactly 1 HTTP call per request().
- REAL mode: TR_ID unchanged.

Function names carry ``kis_client_`` (Stage gate selector).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from src.adapters.kis._client import KISApiError, KISClient
from src.adapters.kis._http import HttpResponse
from src.adapters.kis.config import KISConfig, TradingMode

if TYPE_CHECKING:
    from collections.abc import Mapping

# ---------------------------------------------------------------------------
# Sentinel secrets — must never appear in error messages.
# ---------------------------------------------------------------------------
_APPKEY = "PKabcdefghijklmnop1234567890"
_APPSECRET = "SECRETsupersecretappsecretvalue=="
_ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.SECRETTOKEN.sig"

_T0 = datetime(2026, 5, 22, 9, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _paper_config() -> KISConfig:
    return KISConfig(
        mode=TradingMode.PAPER,
        base_url="https://openapivts.koreainvestment.com:29443",
        appkey=_APPKEY,
        appsecret=_APPSECRET,
        cano="50012345",
        acnt_prdt_cd="01",
    )


def _real_config() -> KISConfig:
    return KISConfig(
        mode=TradingMode.REAL,
        base_url="https://openapi.koreainvestment.com:9443",
        appkey=_APPKEY,
        appsecret=_APPSECRET,
        cano="50012345",
        acnt_prdt_cd="01",
    )


def _ok_body() -> dict[str, object]:
    """Minimal success envelope."""
    return {"rt_cd": "0", "msg_cd": "MCA00000", "msg1": "정상처리"}


class _FakeAuth:
    """Returns a fixed token; never issues network calls."""

    def get_token(self) -> str:
        return _ACCESS_TOKEN


class _FakeHttp:
    """Records GET/POST calls; pops queued responses."""

    def __init__(self, responses: list[HttpResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str],
        headers: Mapping[str, str],
        timeout: float = 10.0,
    ) -> HttpResponse:
        self.calls.append(
            {"method": "GET", "url": url, "params": dict(params), "headers": dict(headers)}
        )
        return self._responses.pop(0)

    def post(
        self,
        url: str,
        *,
        json: Mapping[str, object],
        headers: Mapping[str, str],
        timeout: float = 10.0,
    ) -> HttpResponse:
        self.calls.append(
            {"method": "POST", "url": url, "json": dict(json), "headers": dict(headers)}
        )
        return self._responses.pop(0)


class _FixedClock:
    """Returns a fixed UTC time (no advancing; throttle arithmetic uses delta)."""

    def __init__(self, t: datetime) -> None:
        self._t = t

    def __call__(self) -> datetime:
        return self._t


class _AdvancingClock:
    """Advances by ``step`` on every call."""

    def __init__(self, start: datetime, step: timedelta) -> None:
        self._t = start
        self._step = step

    def __call__(self) -> datetime:
        t = self._t
        self._t += self._step
        return t


def _make_client(
    config: KISConfig,
    http: _FakeHttp,
    *,
    clock_t: datetime = _T0,
    sleep_calls: list[float] | None = None,
) -> KISClient:
    captured: list[float] = [] if sleep_calls is None else sleep_calls

    def _sleep(s: float) -> None:
        captured.append(s)

    return KISClient(
        config=config,
        http=http,
        auth=_FakeAuth(),
        clock=_FixedClock(clock_t),
        sleep=_sleep,
    )


# ---------------------------------------------------------------------------
# TR_ID conversion
# ---------------------------------------------------------------------------
class TestKisClientTrIdConversion:
    def test_kis_client_paper_trid_T_converted_to_V(self) -> None:
        http = _FakeHttp([HttpResponse(status_code=200, body=_ok_body())])
        client = _make_client(_paper_config(), http)
        client.request("GET", "/some/path", tr_id="TTTC8434R", params={})
        sent_tr_id = http.calls[0]["headers"]["tr_id"]  # type: ignore[index]
        assert sent_tr_id == "VTTC8434R"

    def test_kis_client_paper_trid_J_converted_to_V(self) -> None:
        http = _FakeHttp([HttpResponse(status_code=200, body=_ok_body())])
        client = _make_client(_paper_config(), http)
        client.request("GET", "/some/path", tr_id="JTTC0012U", params={})
        sent_tr_id = http.calls[0]["headers"]["tr_id"]  # type: ignore[index]
        assert sent_tr_id == "VTTC0012U"

    def test_kis_client_paper_trid_C_converted_to_V(self) -> None:
        http = _FakeHttp([HttpResponse(status_code=200, body=_ok_body())])
        client = _make_client(_paper_config(), http)
        client.request("GET", "/some/path", tr_id="CTTC0001U", params={})
        sent_tr_id = http.calls[0]["headers"]["tr_id"]  # type: ignore[index]
        assert sent_tr_id == "VTTC0001U"

    def test_kis_client_paper_trid_F_unchanged(self) -> None:
        """F... 시세 TR_ID is identical for 실/모의 — must NOT be converted."""
        http = _FakeHttp([HttpResponse(status_code=200, body=_ok_body())])
        client = _make_client(_paper_config(), http)
        client.request("GET", "/some/path", tr_id="FHKST01010100", params={})
        sent_tr_id = http.calls[0]["headers"]["tr_id"]  # type: ignore[index]
        assert sent_tr_id == "FHKST01010100"

    def test_kis_client_real_mode_trid_T_unchanged(self) -> None:
        """REAL mode: TR_IDs must never be converted."""
        http = _FakeHttp([HttpResponse(status_code=200, body=_ok_body())])
        client = _make_client(_real_config(), http)
        client.request("GET", "/some/path", tr_id="TTTC8434R", params={})
        sent_tr_id = http.calls[0]["headers"]["tr_id"]  # type: ignore[index]
        assert sent_tr_id == "TTTC8434R"

    def test_kis_client_balance_paper_tr_id_becomes_V(self) -> None:
        """End-to-end: TTTC8434R → VTTC8434R in PAPER (ADR 0020 §2.1)."""
        http = _FakeHttp([HttpResponse(status_code=200, body=_ok_body())])
        client = _make_client(_paper_config(), http)
        client.request("GET", "/path", tr_id="TTTC8434R", params={})
        assert http.calls[0]["headers"]["tr_id"] == "VTTC8434R"  # type: ignore[index]


# ---------------------------------------------------------------------------
# Header construction
# ---------------------------------------------------------------------------
class TestKisClientHeaders:
    def test_kis_client_header_authorization_bearer(self) -> None:
        http = _FakeHttp([HttpResponse(status_code=200, body=_ok_body())])
        client = _make_client(_paper_config(), http)
        client.request("GET", "/path", tr_id="FHKST01010100", params={})
        auth_header = http.calls[0]["headers"]["authorization"]  # type: ignore[index]
        assert auth_header == f"Bearer {_ACCESS_TOKEN}"

    def test_kis_client_header_appkey_present(self) -> None:
        http = _FakeHttp([HttpResponse(status_code=200, body=_ok_body())])
        client = _make_client(_paper_config(), http)
        client.request("GET", "/path", tr_id="FHKST01010100", params={})
        assert http.calls[0]["headers"]["appkey"] == _APPKEY  # type: ignore[index]

    def test_kis_client_header_custtype_is_P(self) -> None:
        http = _FakeHttp([HttpResponse(status_code=200, body=_ok_body())])
        client = _make_client(_paper_config(), http)
        client.request("GET", "/path", tr_id="FHKST01010100", params={})
        assert http.calls[0]["headers"]["custtype"] == "P"  # type: ignore[index]

    def test_kis_client_header_tr_id_reflects_conversion(self) -> None:
        http = _FakeHttp([HttpResponse(status_code=200, body=_ok_body())])
        client = _make_client(_paper_config(), http)
        client.request("GET", "/path", tr_id="TTTC8434R", params={})
        assert http.calls[0]["headers"]["tr_id"] == "VTTC8434R"  # type: ignore[index]

    def test_kis_client_header_content_type_json(self) -> None:
        http = _FakeHttp([HttpResponse(status_code=200, body=_ok_body())])
        client = _make_client(_paper_config(), http)
        client.request("GET", "/path", tr_id="FHKST01010100", params={})
        assert http.calls[0]["headers"]["content-type"] == "application/json"  # type: ignore[index]


# ---------------------------------------------------------------------------
# Throttle
# ---------------------------------------------------------------------------
class TestKisClientThrottle:
    def test_kis_client_throttle_first_call_no_sleep(self) -> None:
        sleep_calls: list[float] = []
        http = _FakeHttp([HttpResponse(status_code=200, body=_ok_body())])
        client = KISClient(
            config=_paper_config(),
            http=http,
            auth=_FakeAuth(),
            clock=_FixedClock(_T0),
            sleep=lambda s: sleep_calls.append(s),
        )
        client.request("GET", "/path", tr_id="FHKST01010100", params={})
        # First call: no sleep.
        assert sleep_calls == []

    def test_kis_client_throttle_second_call_within_interval_sleeps(self) -> None:
        """Paper mode min-interval = 0.5s. If 0.1s elapsed → sleep ~0.4s."""
        sleep_calls: list[float] = []
        # Clock advances 0.1s per call (simulates 0.1s elapsed between calls).
        clock = _AdvancingClock(_T0, timedelta(seconds=0.1))
        http = _FakeHttp(
            [
                HttpResponse(status_code=200, body=_ok_body()),
                HttpResponse(status_code=200, body=_ok_body()),
            ]
        )
        client = KISClient(
            config=_paper_config(),
            http=http,
            auth=_FakeAuth(),
            clock=clock,
            sleep=lambda s: sleep_calls.append(s),
        )
        client.request("GET", "/path", tr_id="FHKST01010100", params={})
        client.request("GET", "/path", tr_id="FHKST01010100", params={})
        # Second call should have triggered sleep.
        assert len(sleep_calls) == 1
        assert sleep_calls[0] > 0

    def test_kis_client_throttle_real_mode_faster_interval(self) -> None:
        """REAL mode min-interval = 0.05s (20/s). Paper = 0.5s (2/s)."""
        sleep_calls: list[float] = []
        # Advance 0.02s between calls — within real interval (0.05s).
        clock = _AdvancingClock(_T0, timedelta(seconds=0.02))
        http = _FakeHttp(
            [
                HttpResponse(status_code=200, body=_ok_body()),
                HttpResponse(status_code=200, body=_ok_body()),
            ]
        )
        client = KISClient(
            config=_real_config(),
            http=http,
            auth=_FakeAuth(),
            clock=clock,
            sleep=lambda s: sleep_calls.append(s),
        )
        client.request("GET", "/path", tr_id="FHKST01010100", params={})
        client.request("GET", "/path", tr_id="FHKST01010100", params={})
        assert len(sleep_calls) == 1
        assert sleep_calls[0] > 0


# ---------------------------------------------------------------------------
# Error handling — no retry
# ---------------------------------------------------------------------------
class TestKisClientErrors:
    def test_kis_client_non_2xx_raises_api_error(self) -> None:
        http = _FakeHttp(
            [HttpResponse(status_code=403, body={"rt_cd": "1", "msg_cd": "EGW00133"})]
        )
        client = _make_client(_paper_config(), http)
        with pytest.raises(KISApiError):
            client.request("GET", "/path", tr_id="FHKST01010100", params={})

    def test_kis_client_rt_cd_nonzero_raises_api_error(self) -> None:
        http = _FakeHttp(
            [HttpResponse(status_code=200, body={"rt_cd": "1", "msg_cd": "EGW00201", "msg1": "유량초과"})]
        )
        client = _make_client(_paper_config(), http)
        with pytest.raises(KISApiError):
            client.request("GET", "/path", tr_id="FHKST01010100", params={})

    def test_kis_client_no_retry_exactly_one_http_call(self) -> None:
        """ADR 0012 §1.6 #1: 자동 재시도 zero — exactly 1 HTTP call on error."""
        http = _FakeHttp(
            [HttpResponse(status_code=503, body={"rt_cd": "1", "msg_cd": "EGW00999"})]
        )
        client = _make_client(_paper_config(), http)
        with pytest.raises(KISApiError):
            client.request("GET", "/path", tr_id="FHKST01010100", params={})
        assert len(http.calls) == 1

    def test_kis_client_no_retry_on_rt_cd_failure_exactly_one_call(self) -> None:
        http = _FakeHttp(
            [HttpResponse(status_code=200, body={"rt_cd": "7", "msg_cd": "EGW00100", "msg1": "x"})]
        )
        client = _make_client(_paper_config(), http)
        with pytest.raises(KISApiError):
            client.request("GET", "/path", tr_id="FHKST01010100", params={})
        assert len(http.calls) == 1

    def test_kis_client_error_message_excludes_appsecret(self) -> None:
        """R10: appsecret must never appear in error text (CLAUDE.md §8.3)."""
        http = _FakeHttp(
            [HttpResponse(status_code=403, body={"rt_cd": "1", "msg_cd": "EGW00133"})]
        )
        client = _make_client(_paper_config(), http)
        with pytest.raises(KISApiError) as exc_info:
            client.request("GET", "/path", tr_id="FHKST01010100", params={})
        assert _APPSECRET not in str(exc_info.value)
        assert _ACCESS_TOKEN not in str(exc_info.value)

    def test_kis_client_rt_cd_error_excludes_appsecret(self) -> None:
        http = _FakeHttp(
            [HttpResponse(status_code=200, body={"rt_cd": "1", "msg_cd": "EGW00201", "msg1": "유량"})]
        )
        client = _make_client(_paper_config(), http)
        with pytest.raises(KISApiError) as exc_info:
            client.request("GET", "/path", tr_id="FHKST01010100", params={})
        assert _APPSECRET not in str(exc_info.value)
        assert _APPKEY not in str(exc_info.value)

    def test_kis_client_success_returns_body_dict(self) -> None:
        body = {"rt_cd": "0", "msg_cd": "MCA00000", "msg1": "ok", "output": {"stck_prpr": "75000"}}
        http = _FakeHttp([HttpResponse(status_code=200, body=body)])
        client = _make_client(_paper_config(), http)
        result = client.request("GET", "/path", tr_id="FHKST01010100", params={})
        assert result["rt_cd"] == "0"
        assert "output" in result
