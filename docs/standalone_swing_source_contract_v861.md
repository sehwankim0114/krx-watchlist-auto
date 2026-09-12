# V8.6.1 독립 종목 스윙추세분석 source-only 계약

버전: `2026-09-11-v8.6.1-standalone-swing-source-cache`

상태: `SOURCE_ONLY / TABLE_DISABLED`

## 목적

독립 종목 스윙추세분석표를 활성화하기 전에, 이미 검증된 확정 일봉 지표만 종목별 source cache로 고정한다.

이번 단계는 새 표나 새 Action을 만들지 않는다. 기존 코피표·연속하락표의 계산식·행 구조·Worker 경로도 바꾸지 않는다.

## 입력

- `latest/active_stock_long_history_260d_latest.csv`
- `latest/active_stock_long_history_260d_meta_latest.json`
- `latest/official_index_history_latest.csv`
- `api/two_table_v1/kospi.json`
- `stock_table_metrics_v850.py`

## 계산 가능한 항목

기존 `stock_table_metrics_v850.py`의 검증된 함수를 그대로 재사용한다.

- 평균등락일수
- 현재 연속등락 방향·일수·누적등락률
- MA5/20/60/120 값·5거래일 방향
- 1M/3M 확정 일봉 수익률
- KOSPI 대비 1M/3M RS(%p)
- ATR14
- 20일 평균 일중고저폭
- 3개월 저가·고가·현재 위치
- 큰 스윙 상태
- 스윙 trough/peak 날짜
- 저점/고점 대비 등락률
- 5거래일 모멘텀
- MA20 참고선
- 기존 2.4 조건 일치 여부

스윙은 미래 예측이 아니라 확정 일봉의 과거 상태 분류다.

## 이번 단계에서 계산하지 않는 항목

다음은 공식 계산계약 또는 소스가 없으므로 `null`을 유지한다.

- RSI
- MACD
- 1주 수익률
- 6개월 수익률
- YTD
- 52주 수익률
- 업종 RS
- 확정 스윙저점 기반 추적손절
- 투자종합점수100
- 실적전망 변화

RSI14, MACD 12/26/9 같은 관행값을 임의 채택하지 않는다.

## 업종 RS 상태

V8.6.0 공식 지수 구성종목 probe는 GitHub Actions 환경에서 `pykrx 1.2.8`의 KRX 로그인이 없어 `LIMITED_INDEX_LIST_EMPTY`로 종료했다.

공개 KRX OpenAPI 서비스 목록에서 지수 구성종목 멤버십 API가 확인되지 않았고, KRX는 구성종목 상세를 지수정보상품으로 별도 안내한다.

따라서 업종명을 문자열 유사도로 KRX 업종지수에 붙이거나, 같은 업종 종목 평균을 업종지수처럼 대체하지 않는다.

## 회귀 게이트

현재 운영 코피표 30종목에 대해 아래 값은 source cache 재계산값과 정확히 같아야 한다.

- official_close
- run
- streak
- ma
- returns
- rs_kospi_pp
- atr14
- avg_daily_range_20_pct
- range_3m
- swing
- trailing_reference
- matches_decliners_24

30/30 정확 일치가 아니면 캐시를 게시하지 않는다.

## 안전 규칙

- `standalone_swing_table_enabled=false`
- `request_time_price_eligible=false`
- 요청시점 현재가를 이 source cache에 저장하지 않는다.
- 요청시점 가격 실패를 정적 종가로 대체하지 않는다.
- 확정 스윙저점 손절은 계속 `null`.
- MA20은 `REFERENCE_ONLY_NOT_ORDER`.
- 기존 계산식을 수정하지 않는다.
- 기존 두표 production JSON을 수정하지 않는다.
- 최종 다열 레이아웃·한글 용어 정리는 마지막 단계로 남긴다.
