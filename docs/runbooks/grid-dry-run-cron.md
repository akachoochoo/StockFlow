# DGT grid-dry-run Cron Setup

> **Status**: Phase 1.x DGT live promotion follow-up. ADR 0022 §12 D23 +
> cron 자동화 증분. 단일 종목 (현재 095660 디폴트) dry-run 을 매 영업일
> 1 회 자동 실행.

## 개요

`scripts/grid_dry_run_cron.sh` 는 `trading grid-dry-run` 의 cron 호출
래퍼다. 매일 한 번 실행 → 1 영업일 처리 → DB 영속 → 다음 cron 자동
이어받기. 실주문 zero (MockBroker grid 경로 D19), 시세는 KIS 모의투자
quotes (`--use-kis`) 또는 CSV (테스트).

## 사전 조건

1. **OS / Shell**: macOS 또는 Linux + bash. `mkdir` 기반 portable lock —
   `flock` 의존 zero.
2. **uv + Python 3.11+** repo 디렉토리에서 동작 (이미 `pyproject.toml` 박제).
3. **`.env` 설정** (KIS 시세 사용 시):
   - `KIS_PAPER_APPKEY` + `KIS_PAPER_APPSECRET` + `KIS_PAPER_ACCOUNT_CANO`
     (모의투자 = VTS, ADR 0012 R10 정합)
   - `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` (옵션, 미설정 시 console only)
4. **Grid config**: `config/grid-095660-dryrun.yaml` (이미 commit). 다른
   종목은 `manage_strategies.py grid-wizard` 로 생성.

## 환경변수 (모두 옵션)

| 변수 | 기본 | 설명 |
|------|------|------|
| `STOCKFLOW_ROOT` | 스크립트 부모 | repo 루트 |
| `GRID_DRYRUN_CONFIG` | `config/grid-095660-dryrun.yaml` | grid config YAML |
| `GRID_DRYRUN_DB` | `grid-dry-run.db` | SQLite DB (repo 루트 기준) |
| `GRID_DRYRUN_CAPITAL` | `10000000` | 초기 자본 (KRW) |
| `GRID_DRYRUN_LOOKBACK` | `180` | KIS lookback 일수 (ATR 14일 + 버퍼) |
| `GRID_DRYRUN_LOG_DIR` | `logs` | 로그 디렉토리 (repo 루트 기준) |
| `GRID_DRYRUN_USE_KIS` | `1` | `1`=KIS 시세, `0`=CSV |
| `GRID_DRYRUN_CSV` | (없음) | `--use-kis=0` 시 CSV (예: `095660=data/...csv`) |
| `GRID_DRYRUN_DATE` | (오늘 KST) | 강제 처리 date (YYYY-MM-DD) |

## crontab 등록

KRX 종가 ≈ 15:30 KST + KIS daily OHLCV publish 버퍼 약 30 분 → **16:00 KST**
이후 권장.

```cron
# DGT grid-dry-run — 평일 매일 16:00 KST
0 16 * * 1-5 /Users/USERNAME/workspace/StockFlow/scripts/grid_dry_run_cron.sh

# (옵션) cron 실행 실패 시 사람 이메일 — crontab 헤더에 추가
MAILTO=ops@example.com
```

`crontab -e` 로 등록. 경로는 본인 환경에 맞게 변경.

## 수동 호출 (테스트)

```bash
# 기본 KIS 시세 (env 설정 필요)
bash scripts/grid_dry_run_cron.sh

# CSV 모드 (테스트 / 휴장일 비교)
GRID_DRYRUN_USE_KIS=0 \
GRID_DRYRUN_CSV=095660=data/historical/KRX_095660_2025-2026.csv \
GRID_DRYRUN_DATE=2026-01-15 \
bash scripts/grid_dry_run_cron.sh

# 다른 종목 (예: 005930 삼성전자)
GRID_DRYRUN_CONFIG=config/grid-005930-dryrun.yaml \
GRID_DRYRUN_DB=samsung-dry-run.db \
bash scripts/grid_dry_run_cron.sh
```

## 동시 실행 방지

`logs/grid-dry-run.lock.d` 디렉토리 = lock. cron 호출 중복 시 (앞 호출
미종료) 즉시 종료 (`exit 0`, log 에 "이미 실행 중" 기록). 정상 / 비정상
종료 시 자동 해제 (`trap rmdir`).

stale lock 발생 시 (프로세스 강제 종료): `rmdir logs/grid-dry-run.lock.d`.

## 로그

- 위치: `logs/grid-dry-run-YYYY-MM-DD.log` (날짜별, append).
- 형식: 시작/종료 헤더 + CLI stdout/stderr (사람 가독 + click.echo).
- 로테이션: 별 자동화 없음. 필요 시 `logrotate` 등록 (`*.log` daily, keep 30).

## 알림 (텔레그램)

`.env` 의 `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` 설정 시 자동 발사 — CLI
가 직접 호출 (`build_notifier(os.environ)`).

알림 종류:
- **시작** (`INFO`): 종가 / 사전 결정 수 / 복원 cash / 보유 / 시세 소스
- **매수/매도** (`INFO`, per decision): side / level_index / qty / rounded_price
- **종료** (`INFO`): 결정 수 / 종료 cash / 보유
- **오류** (`ERROR`): exception 즉시 — broker/uow 닫기 후 raise

미설정 시 console fallback (root logger WARNING+ 기본 → INFO 묵음).

## 휴장일 / 거래정지일

- KIS `inquire-daily-itemchartprice` 가 거래일만 반환. 휴장일 호출 시
  bars[-1] = 직전 영업일 → CLI 가 "⚠ 대체로 직전 영업일 처리" 경고 stderr.
- 텔레그램 시작 알림은 발사 — 사람이 검토 후 무시 / 조치.
- 빈 결과 (네트워크 / API 오류) → CLI `ClickException` 발생 → 오류 알림
  발사 + exit !=0 → cron MAILTO 가 받음.

## 트러블슈팅

| 증상 | 원인 / 조치 |
|------|-----------|
| `ModuleNotFoundError: src.adapters.kis.config` | repo 루트 진입 실패. `STOCKFLOW_ROOT` 확인. |
| `Missing required KIS env var: KIS_PAPER_APPKEY` | `.env` 미설정 또는 `set -a; source .env; set +a` 실패. crontab `env` 절 추가. |
| Lock stale | `rmdir logs/grid-dry-run.lock.d` |
| 결정 0 건 매일 | grid_state 가 초기 reference 에 고착 → 가격대 진입 어려움. config k_min/k_max 검토. |
| Telegram 무전송 | `TELEGRAM_BOT_TOKEN`/`CHAT_ID` 미설정. console fallback 만 (logging 기본 WARNING+ 라 INFO 묵음). |

## 후속 (별 sub-step)

- multi-asset cron — 현재 단일 종목 한정. config 1개당 wrapper 1회 호출이
  가장 간단 (cron 라인 N개).
- 실 KIS 거래 진입 (G5) — 별 ADR, 사람+소액+차단기 단계.
- `oh-my-claudecode:schedule` 활용 — 로컬 cron 대신 OMC remote schedule.

## 참조

- `scripts/grid_dry_run_cron.sh` — 래퍼 스크립트
- `src/cli/main.py::grid_dry_run` — CLI 정본
- `config/grid-095660-dryrun.yaml` — 095660 기본 config
- ADR 0022 §12 — DGT live promotion 박제
- ADR 0012 D3 — paper-on-live + 텔레그램 알림
