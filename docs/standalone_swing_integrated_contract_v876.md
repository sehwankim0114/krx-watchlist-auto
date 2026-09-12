# V8.7.6 독립 스윙 통합 source-only 계약

버전: `2026-09-12-v8.7.6-standalone-swing-integrated-source`

상태: `SOURCE_ONLY / TABLE_DISABLED / ACTION_DISABLED`

## 목적

현재까지 검증된 독립 스윙 관련 source를 종목별 하나의 통합 객체로 결합한다.

입력:

- `latest/standalone_swing_source_latest.json`
- `latest/standalone_swing_extended_returns_latest.json`
- `latest/standalone_swing_sector_rs_latest.json`
- `latest/stock_table_metric_glossary_latest.json`

이번 단계는 새 표·Action·Worker 경로를 활성화하지 않는다.

## 통합되는 확정 항목

- 종목명·종목코드·시장·공식종가·기준일
- 1M·3M 확정 일봉 수익률
- 6M 수익률
- 큰 스윙 상태
- trough/peak 날짜
- 저점·고점 대비 현재 위치
- 5거래일 모멘텀
- MA5/20/60/120 값·방향
- 평균등락일수
- 현재 연속등락 일수·누적등락률
- KOSPI 대비 1M/3M RS
- KOSPI 종목의 공식 KRX 업종RS 1M/3M
- ATR14
- 20일 평균 일중고저폭
- 3개월 고가·저가 범위
- MA20 참고선
- 2.4 조건 일치 여부
- 핵심 용어 glossary footer

## 시장별 업종RS

KOSPI:
- V8.7.5 source 값을 사용한다.
- 현재 source 대상 KOSPI 종목은 모두 READY여야 한다.

KOSDAQ:
- 현재 공식 계약이 KOSPI 기준이므로 업종RS는 null을 유지한다.
- 새 매핑 규칙을 임의 생성하지 않는다.

## 계속 미계산

공식 계산계약 또는 원천 소스가 아직 부족한 다음 항목은 모두 null이다.

- 1W 수익률
- YTD 수익률
- 52W 수익률
- RSI
- MACD
- 투자종합점수100
- 실적전망 변화
- 확정 스윙저점 기반 추적손절

## 6M 자료 부족

6M은 기존 월 단위 수익률 계약을 확장해 계산한다.

상장 이력이 부족한 종목은 기존 source의 상태값을 그대로 유지하며 임의 보간하지 않는다.

## glossary

`latest/stock_table_metric_glossary_latest.json`의 실제 키:

`compact_footer_text`

를 사용한다.

## 안전 규칙

- `source_only=true`
- `standalone_swing_table_enabled=false`
- `action_route_enabled=false`
- `request_time_price_eligible=false`
- 기존 production 두표 JSON 수정 금지
- Worker 수정 금지
- 기존 지표 계산식 수정 금지
- 요청시점 현재가 실패 시 정적 종가 대체 금지
- 미제공 지표 임의 계산 금지
- 다열 레이아웃·최종 한글 용어 정리는 프로젝트 마지막 단계로 남긴다.
