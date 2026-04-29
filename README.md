# SevenSplit

세븐 스플릿 + AI 차단기 기반 멀티 자산 자동매매 시스템.

> **경고**: 실계좌가 연결될 자동매매 시스템입니다.
> 코드 수정 전 [`CLAUDE.md`](./CLAUDE.md)와 [`docs/roadmap.md`](./docs/roadmap.md)를 반드시 읽으세요.

## 현재 단계

**Phase 0** — 종이 거래 시뮬레이터 (Mock 환경, 실 API 미연결).

상세는 [`docs/roadmap.md`](./docs/roadmap.md) 참조.

## 설계 문서

- [멀티 자산 자동매매 시스템 설계](./docs/multi-asset-trading-system-design.md)
- [개발 규칙 (CLAUDE.md)](./CLAUDE.md)

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
```

## 아키텍처

Clean Architecture (Hexagonal). 자세한 의존성 규칙은 `CLAUDE.md` 1장 참조.

```
src/
├── domain/         # 도메인 모델, 전략 (외부 의존 금지)
├── ports/          # Port (Protocol) 정의
├── use_cases/      # Use Case (Orchestrator)
├── adapters/       # 외부 시스템 어댑터
└── infrastructure/ # DB, 로깅, 알림
```
