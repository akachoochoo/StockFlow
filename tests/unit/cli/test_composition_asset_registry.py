"""Phase 1.1 — composition.asset_from_code reads config/assets.yaml (단일 정본).

ADR 0021 §7.1: 하드코딩 ``_ASSET_FACTORIES`` 제거 후 모든 코드(Phase 0 박제
9 종 포함)는 assets.yaml 에서 로드된다. ``registry_path`` 로 비표준 경로를
주입할 수 있고, 미존재 코드는 KeyError. (박제 9 종의 정확값 회귀 잠금은
``test_composition.py`` 의 ``*_registered`` 테스트가 담당.)
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from src.cli.composition import asset_from_code
from src.domain.models import AssetClass, Market

if TYPE_CHECKING:
    from pathlib import Path

_KAKAO = """\
version: "1.0"
assets:
  "035720":
    name: "카카오"
    market: KOSPI
    asset_class: KR_STOCK
    listed_at: 2017-07-10
"""


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "assets.yaml"
    p.write_text(body, encoding="utf-8")
    return p


class TestRegistryPathOverride:
    def test_custom_path_resolves(self, tmp_path: Path):
        a = asset_from_code("035720", registry_path=_write(tmp_path, _KAKAO))
        assert a.code == "035720"
        assert a.name == "카카오"
        assert a.market is Market.KOSPI
        assert a.asset_class is AssetClass.KR_STOCK

    def test_unknown_in_custom_path_raises(self, tmp_path: Path):
        path = _write(tmp_path, _KAKAO)
        with pytest.raises(KeyError) as exc:
            asset_from_code("999999", registry_path=path)
        msg = str(exc.value)
        assert "999999" in msg
        assert "035720" in msg  # available codes listed in the message

    def test_missing_path_raises(self, tmp_path: Path):
        # 069500 은 더 이상 하드코딩이 아님 — 빈/없는 레지스트리면 KeyError.
        with pytest.raises(KeyError):
            asset_from_code("069500", registry_path=tmp_path / "nope.yaml")


class TestDefaultPath:
    def test_default_resolves_enshrined_asset(self):
        # 박제 종목이 기본 config/assets.yaml 에서 해석됨 (단일 정본 통합).
        a = asset_from_code("069500")
        assert a.name == "KODEX 200"
        assert a.asset_class is AssetClass.KR_ETF
        assert str(a.tick_size) == "5"
