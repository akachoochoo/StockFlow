"""Backtest reporting adapters (Phase 0.10 — ADR 0006 §4 / §6 / §7).

Hexagonal adapters for the reporting layer:
- ``renderers/`` — StrategyRenderer 구현체 (SevenSplit / Default, ADR §4.3)
- ``renderer_registry.py`` — strategy_id → renderer mapping (ADR §4.4)
- ``chart.py`` (TBD sub-step 0.10.d) — mplfinance 차트 (ADR §6)
- ``html_writer.py`` (TBD sub-step 0.10.d) — stdlib f-string HTML 출력 (ADR §7)

코어 리포팅 (`src/application/reporting/`) 은 Port (`src/ports/strategy_renderer.py`)
만 의존 — strategy 무지.
"""
