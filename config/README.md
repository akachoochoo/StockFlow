# config/

> 어느 파일이 현행인지 — 2026-06-12 사용성 정리 기준.

## 현행 (운영에서 사용 중)

| 파일 | 용도 |
|------|------|
| `assets.yaml` | 자산 registry (ADR 0021, 데이터 주도 종목 관리) — `composition.py` fallback 의 정본 |
| `grid-4stocks-dryrun.yaml` | DGT 4종 dry-run — `scripts/grid_4stocks_dryrun_cron.sh` 기본 config |
| `grid-095660-dryrun.yaml` | DGT 단일종목(095660) dry-run — `scripts/grid_dry_run_cron.sh` 기본 config |

## 역사적 실험 (참조 있어 보존)

Phase 0.x 실험 config. **운영에서 사용하지 않음** — 그러나 현행 코드/테스트가
경로를 참조하므로 이동하면 깨진다. 참조가 사라지는 시점에 `archive/` 로 이동.

| 파일 | 참조처 |
|------|--------|
| `strategies-0.7.1-F.yaml` | `scripts/run_phase_0_7_2_backtest.py` |
| `strategies-0.7.2-{equal,vol,inv-vol}.yaml` | phase 0.7.2 비교 스크립트 |
| `strategies-0.7.3.yaml` | `src/research/dgt/optimization/_baseline.py` + phase 1.1 스크립트 |
| `strategies-0.8.1.yaml` | `scripts/run_phase_0_8_1_backtest.py` |
| `strategies-0.9.1.yaml` / `strategies-0.9.2.yaml` | reporting 테스트 + `strategy_info.py` |
| `strategies-D.yaml` / `strategies-F.yaml` | loader 통합 테스트 + `scripts/compare_phase05.py` |

## archive/

코드/테스트/문서 어디서도 참조하지 않는 완료 실험 config. 참조 zero 확인 후
이동된 것들 — 필요 시 git history 에서 원위치 확인 가능.
