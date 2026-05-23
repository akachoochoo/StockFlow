"""Phase 1.1 — composition.asset_from_code data-driven fallback.

The hardcoded ``_ASSET_FACTORIES`` wins; codes absent there are looked up
in ``config/assets.yaml`` (path injectable for tests). A code in neither
still raises KeyError with a helpful message (회귀 invariant — preserves the
existing ``test_unknown_code_raises_key_error`` contract).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from src.cli.composition import asset_from_code, kodex200
from src.domain.models import AssetClass, Market

if TYPE_CHECKING:
    from pathlib import Path


def _write_assets(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "assets.yaml"
    path.write_text(body, encoding="utf-8")
    return path


_KAKAO = """\
version: "1.0"
assets:
  "035720":
    name: "카카오"
    market: KOSPI
    asset_class: KR_STOCK
    listed_at: 2017-07-10
"""


class TestFallback:
    def test_hardcoded_wins_without_touching_yaml(self, tmp_path: Path):
        # Even if yaml redefines 069500, the hardcoded factory is returned.
        path = _write_assets(
            tmp_path,
            'version: "1.0"\n'
            "assets:\n"
            '  "069500":\n'
            '    name: "WRONG"\n'
            "    market: KOSDAQ\n"
            "    asset_class: KR_STOCK\n"
            "    listed_at: 2099-01-01\n",
        )
        assert asset_from_code("069500", registry_path=path) == kodex200()

    def test_yaml_fallback_resolves_new_code(self, tmp_path: Path):
        path = _write_assets(tmp_path, _KAKAO)
        a = asset_from_code("035720", registry_path=path)
        assert a.code == "035720"
        assert a.name == "카카오"
        assert a.market is Market.KOSPI
        assert a.asset_class is AssetClass.KR_STOCK

    def test_unknown_code_still_raises_with_hints(self, tmp_path: Path):
        path = _write_assets(tmp_path, _KAKAO)
        with pytest.raises(KeyError) as exc:
            asset_from_code("999999", registry_path=path)
        msg = str(exc.value)
        assert "999999" in msg
        assert "069500" in msg  # hardcoded list shown
        assert "035720" in msg  # assets.yaml list shown

    def test_missing_yaml_behaves_like_hardcoded_only(self, tmp_path: Path):
        missing = tmp_path / "nope.yaml"
        with pytest.raises(KeyError):
            asset_from_code("035720", registry_path=missing)
        # hardcoded still resolves with a missing fallback file
        assert asset_from_code("069500", registry_path=missing) == kodex200()
