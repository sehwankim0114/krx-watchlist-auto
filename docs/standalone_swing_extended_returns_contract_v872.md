# V8.7.2 독립 스윙 6개월 수익률 source-only 계약

버전: `2026-09-12-v8.7.2-standalone-swing-6m-return-source`

상태: `SOURCE_ONLY / TABLE_DISABLED`

## 목적

독립 종목 스윙추세분석의 가격성과 항목 중, 기존 생산 지표 계약을 그대로 확장할 수 있는 `6M` 수익률만 source-only 데이터로 계산한다.

새 표·Action·Worker 경로는 활성화하지 않는다.

## 6M 계산 근거

현재 `stock_table_metrics_v850.py`의 공식 계약은 수익률 기준을 다음과 같이 정의한다.

`CALENDAR_MONTHS_FIRST_MARKET_SESSION_ON_OR_AFTER`

같은 `period_return()` 함수가 이미 production 1M/3M 계산에 사용되며 `months` 인수를 받는다.

V8.7.2에서는 먼저 현재 production 코피표 30종목의 1M/3M 값을 이 함수로 다시 계산하여 `30/30` 정확 일치를 강제한다. 이 회귀 게이트를 통과한 경우에만 동일 함수에 `months=6`을 전달한다.

따라서 6M은 새로운 수익률 공식을 발명한 것이 아니라 기존 월 단위 수익률 계약의 기간 확장이다.

## V8.6.2 증거

기준일 2026-09-11, 활성종목 235개 기준:

- 1W 7일 달력 기준: 235/235 ready
- 1W 5거래일 기준: 235/235 ready
- 두 1W 후보 시작일: 235/235 동일
- 6M 달력월 기준: 234/235 ready
- YTD: 234/235 ready
- 52W 달력 364일 기준: 233/235 ready
- 52W 252거래일 기준: 233/235 ready
- 52W 두 후보: 비교 가능한 233/233에서 시작일이 모두 다름
- 2026-09-11 기준 52W 달력 시작일은 2025-09-12, 252거래일 시작일은 2025-08-29로 14일 차이

## 이번 단계에서 계산하는 값

- 6M 수익률
- 6M 기준 시작 거래일
- 6M 상태

자료 부족 종목은 `CALENDAR_HISTORY_SHORT`로 남긴다.

현재 예상되는 6M 자료 부족 종목:

- 439960 코스모로보틱스 — history 시작 2026-05-11

## 계속 미계산

다음은 최종 기준계약이 없으므로 계속 `null`이다.

- 1W
- YTD
- 52W

특히 52W는 달력 52주와 252거래일 방식이 실제로 14일 차이를 보였으므로 임의 선택하지 않는다.

또한 다음 항목도 이번 단계에서 계산하지 않는다.

- RSI
- MACD
- 투자종합점수100
- 실적전망 변화
- 확정 스윙저점 손절

## 안전 규칙

- `source_only=true`
- `standalone_swing_table_enabled=false`
- `request_time_price_eligible=false`
- 기존 production JSON 수정 금지
- Worker 수정 금지
- `stock_table_metrics_v850.py` 수정 금지
- 요청시점 가격 대체 금지
- 기존 1M/3M production 회귀 30/30 불일치 시 게시 금지
