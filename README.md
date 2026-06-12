# StockFlow

KR 주식 자동매매 시스템 — DGT(Dynamic Grid Trading) 기반, KIS(한국투자증권) API 연동.

> **경고**: 실계좌가 연결되는 자동매매 시스템입니다.
> 코드 수정 전 [`CLAUDE.md`](./CLAUDE.md)를 반드시 읽으세요.

## 현재 단계 (2026-06-12)

**Phase 1.x — 분봉(1m) 일괄 전환** ([ADR 0023](./docs/decisions/0023-phase-1.x-minute-bar-conversion.md), 2026-05-30 박제)

- backtest / dry-run / live 전부 분봉 기준으로 전환 중. 진행 = KIS 분봉 수집기(cron 운영 중) + 분봉 grid backtest 엔진.
- **일봉 인프라 = 코드 보존 + 운영 동결** — `live` / `grid-live` / `grid-dry-run` 커맨드는 `ALLOW_DAILY_LIVE=1` 없이 실행 불가 (ADR 0023 D5/D17).
- **세븐스플릿(분할매수) 전략 = 동결, DGT-only** (ADR 0023). split 코드는 보존 invariant (ADR 0004 §7.4.2).
- Phase 0 ~ 0.11.k (백테스트/연구) + Phase 1.1 (KIS 연동, ADR 0019~0021) 완료.

정본: [`CLAUDE.md`](./CLAUDE.md) §14 + [`docs/decisions/`](./docs/decisions/) ADR + [`docs/roadmap.md`](./docs/roadmap.md) (phase 인덱스).

## 처음 쓰는 사람용

1. **셋업 + 일상 사용**: [`docs/usage-phase-1.1.md`](./docs/usage-phase-1.1.md) — KIS 키 발급, `.env` 작성, dry-run 실행, 전략/종목 설정
2. **백테스트 입문**: [`docs/backtest-guide.md`](./docs/backtest-guide.md) — 분할매수 vs DGT
3. **운영 runbook**: [`docs/runbooks/`](./docs/runbooks/) — grid dry-run cron / grid-live 운영 / 긴급 변경 절차

```bash
cp .env.example .env        # 키 입력 (모의투자 KIS_PAPER_* 부터)
uv run trading kis-check --code 069500   # 연결 확인
uv run trading --help                    # 커맨드 목록
```

## 설계 문서

- [멀티 자산 자동매매 시스템 설계](./docs/multi-asset-trading-system-design.md)
- [개발 규칙 (CLAUDE.md)](./CLAUDE.md) — 아키텍처 / 돈·시간·주문 규칙 / 안전장치
- [의사결정 기록 (ADR)](./docs/decisions/) / [회고](./docs/retrospectives/)

## 기술 스택

- Python 3.11+
- 패키지 관리: `uv`
- 검증: `pydantic` v2
- CLI: `click`
- 테스트: `pytest` + `pytest-cov`
- 타입/린트: `mypy` + `ruff`
- DB: SQLite (stdlib)

## 개발 환경 셋업

```bash
# uv 설치 (https://docs.astral.sh/uv/)
uv sync --extra dev

# 테스트
uv run pytest

# 타입 체크
uv run mypy src

# 린트
uv run ruff check src tests

# 네임스페이스 검사 (research 5th ring 격리)
bash scripts/check_namespace.sh
```

## 아키텍처

Clean Architecture (Hexagonal) + research 5th ring. 자세한 의존성 규칙은 `CLAUDE.md` 1장 참조.

```
src/
├── domain/         # 도메인 모델, 전략 (외부 의존 금지)
├── ports/          # Port (Protocol) 정의
├── use_cases/      # Use Case (Orchestrator)
├── application/    # 백테스트 runner, 메트릭, 스냅샷
├── adapters/       # 외부 시스템 어댑터 (KIS / mock / telegram / reporting)
├── infrastructure/ # DB, 로깅
├── cli/            # click CLI (composition root)
└── research/       # 5th ring — 실험/박제 격리 (inner ring 에서 import 금지)
```
