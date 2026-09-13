# V8.7.13 독립 스윙 요청시점 현재가 표시 결합 계약 동결

버전: `2026-09-13-v8.7.13-standalone-swing-display-merge-freeze`

상태: `FROZEN_PREPRODUCTION_READY / PRODUCTION_DISABLED`

## 목적

V8.7.12에서 실제 235종목을 대상으로 검증한 요청시점 현재가 overlay 방식을 독립 스윙 preproduction 계약으로 동결한다.

이번 단계에서도 새 독립 스윙 명령어, Action route, 최종 헤더, 추천 규칙을 활성화하지 않는다.

## V8.7.12 검증 증거

- GitHub Actions run: `34741483044`
- job: `103681809815`
- Artifact ID: `10312955901`
- Artifact SHA256: `ac6667c33c41bba84f90b692ce371cada7841bd63f6fd175294919139c16e597`
- 실행 head SHA: `926cf65c6284ba69115a5861bf5aa2303f85f516`

결과:

- source 235종목
- 요청시점 현재가 235/235 성공
- 요청현재가 실패 0
- 3개월 범위위치 계산 가능 213
- 범위위치 계산 불가 22
- 범위 아래 0 / 범위 안 213 / 범위 위 0
- 정적 종가 fallback 0
- 확정 지표 mutation 0
- 0~100 clamp 없음
- repository·production·Worker 변경 없음

## 동결하는 요청현재가 규칙

현재가 조회는 기존 `getRequestTimePrices`만 재사용한다.

- 처음 최대 10개
- 실패한 종목만 최대 5개
- 남은 실패만 최대 2개
- 최종 실패는 `⚪ 현재가 확인 실패`
- official_close는 참고값
- 요청현재가 실패를 official_close로 대체하지 않음

## 현재위치 결합

요청시점 위치는 확정 일봉의 3개월 저·고가만 사용한다.

`(요청현재가 - 3개월저가) / (3개월고가 - 3개월저가) × 100`

- 결과를 0~100으로 잘라내지 않는다.
- 0 미만이면 공식 범위 아래임을 그대로 보존한다.
- 100 초과면 공식 범위 위임을 그대로 보존한다.
- 3개월 저·고가가 없거나 사용할 수 없으면 `자료 미제공`.
- 정적 `range_3m.position_pct`를 요청시점 위치로 복사하지 않는다.

## 현재가 차이 아이콘

official_close 대비 요청가격 절대 차이율:

- 0.5% 미만: 표시 없음
- 0.5% 이상 1.5% 미만: 🟦
- 1.5% 이상 3.0% 미만: 🟠
- 3.0% 이상: 🔴
- 요청현재가 최종 실패: ⚪

이 아이콘은 추천 아이콘이 아니다.

## 요청가격으로 다시 계산하지 않는 확정 지표

다음은 확정 일봉 지표이며 요청현재가 overlay로 재계산하지 않는다.

- 1M·3M·6M 수익률
- 큰 스윙 상태·저점/고점 anchor
- MA5/20/60/120
- 평균등락일수
- 현재 연속등락
- KOSPI RS
- 업종RS
- ATR14
- 20일 평균 일중고저폭
- 확정 3개월 저·고가
- MA20 참고선
- 미확정 pending metrics

## 22종목 범위위치 자료 미제공

V8.7.12 기준 22종목은 요청현재가는 정상 조회됐으나 통합 source의 `range_3m.low/high`가 null이라 요청시점 범위위치를 계산하지 않았다.

이 경우 새 범위를 추정하거나 다른 가격 source로 보정하지 않는다. `자료 미제공`으로 표시한다.

## 이번 동결로 해결되는 blocker

`REQUEST_TIME_DISPLAY_MERGE_CONTRACT_NOT_FROZEN_FOR_STANDALONE`

## 아직 남은 blocker

- `NO_FINAL_STANDALONE_TABLE_HEADER_CONTRACT`
- `NO_STANDALONE_COMMAND_OR_ROUTE_CONTRACT`
- `1W_YTD_52W_FORMULAS_NOT_APPROVED`
- `RSI_MACD_FORMULAS_NOT_APPROVED`
- `CONFIRMED_SWING_LOW_STOP_POLICY_NOT_DEFINED`
- `INVESTMENT_SCORE_THRESHOLDS_NOT_DEFINED`
- `EARNINGS_OUTLOOK_SOURCE_NOT_CONNECTED`
- `KOSDAQ_OFFICIAL_SECTOR_RS_CONTRACT_NOT_DEFINED`

## 아직 확정하지 않는 표시

- 최종 현재위치 한글 라벨 구간
- 가치매수·익절 가격구간
- 최종 추천 아이콘
- 최종 독립 스윙표 헤더
- 독립 스윙 명령어
- Action route

프로젝트의 최종 다열 레이아웃·한글 용어 정리는 전체 기능 안정화 뒤 마지막 단계에서 처리한다.
