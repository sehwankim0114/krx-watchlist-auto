
# KRX 공식 데이터 최신성 판정 기준

이 문서는 `krx-watchlist-auto` 저장소에서 어떤 상태파일을 우선 확인해야 하는지 정리한 운영 기준입니다.

## 1. 판정 우선순위

| 우선순위 | 파일 | 용도 |
|---:|---|---|
| 1 | `latest/official_data_status_latest.json` | 공식 KRX 시세의 기대 거래일·실제 거래일·FRESH 여부를 판정하는 최우선 파일 |
| 2 | `latest/krx_official_retry_status_latest.json` | 공식 수집 재시도 횟수와 최종 결과 확인 |
| 3 | `latest/data_freshness_notice_latest.md` | 사람이 읽기 쉬운 최신성 요약 |
| 4 | `latest/run_log_latest.txt` | 관종표 원자료 수집 결과와 종목별 상태 확인 |
| 5 | `latest/data_status_latest.json` | 시장폭·지수·버블 위험 상태 확인. 공식 시세 최신성의 최우선 파일은 아님 |

`latest/deprecated/` 아래 파일은 과거 기록 보존용이며 판정에 사용하지 않습니다.

## 2. 주요 상태의 의미

- `FRESH`: 기대 공식 거래일과 실제 공식 데이터 기준일이 일치합니다.
- `STALE_KRX_EMPTY_OR_DELAY`: KRX 공식 데이터가 아직 비어 있거나 기대 거래일까지 올라오지 않았습니다.
- `OK_NEW_CONFIRMED_TRADING_DAY`: 시장 상태 분석기가 새 거래일 자료를 확인했습니다.
- `aux`: 공식 데이터 전체 재수집 없이 보조 현재가와 표시용 파일을 갱신한 실행입니다.

## 3. 자동 실행 시각(KST)

- 월~금 08:10
- 월~토 08:40
- 월~토 09:10
- 월~토 09:40
- 월~토 15:35
- 매일 18:10

오전 08:30 이전에는 공식 데이터 게시가 끝나지 않을 수 있으므로,
08:40·09:10·09:40 실행이 지연 게시를 재확인합니다.

## 4. 정상 여부 확인 순서

1. `official_data_status_latest.json`의 `expected_official_trading_date`와 실제 KOSPI·KOSDAQ 날짜를 비교합니다.
2. `official_fresh`가 `true`인지 확인합니다.
3. `collector_return_code`가 `0`인지 확인합니다.
4. `krx_official_retry_status_latest.json`에서 최종 시도 결과를 확인합니다.
5. `run_log_latest.txt`에서 종목 수와 실패 종목을 확인합니다.
6. 보조 현재가는 `supplement_current_prices_run_log_latest.txt`에서 별도로 확인합니다.

## 5. 구형 파일 방지 규칙

다음 파일이 `latest/` 루트에 다시 생기면 자동 검증을 실패시켜야 합니다.

- `latest/krx_latest_retry_status_latest.json`
- `latest/krx_latest_retry_status_latest.txt`

해당 파일은 반드시 `latest/deprecated/` 아래에만 보관합니다.

## 6. GitHub Actions 런타임

워크플로는 다음 메이저 버전을 사용합니다.

- `actions/checkout@v6`
- `actions/setup-python@v6`

Python 버전은 재현성을 위해 각 워크플로에서 명시적으로 고정합니다.
