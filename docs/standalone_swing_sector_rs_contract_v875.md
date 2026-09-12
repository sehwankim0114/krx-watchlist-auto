# V8.7.5 독립 스윙 업종RS source-only 계약

버전: `2026-09-12-v8.7.5-standalone-swing-sector-rs-source`

상태: `SOURCE_ONLY / TABLE_DISABLED`

## 목적
V8.7.4에서 검증된 공식 KRX 업종RS 확장 결과를 독립 스윙분석용 source cache로 저장한다.

## 검증 근거
- 전체 독립 스윙 source 235종목
- KOSPI 210종목 / KOSDAQ 25종목
- KOSPI 공식 업종 매핑 210/210
- KOSPI 업종RS 1M/3M 계산 210/210
- 기존 production 고유종목 112
- production 업종RS 회귀 112/112 정확 일치
- 업종지수 history 오류 0

## KOSPI
기존 V8.7.0과 동일한 `sector_rs_source_v870.py`의 공식 KRX 소스·매핑 로직만 재사용한다.

업종RS = 종목 기간수익률 - 같은 기간 공식 KRX 업종지수 수익률(%p)

요청시점 현재가로 재계산하지 않는다.

## KOSDAQ
현재 계약은 KOSPI 공식 업종지수 계약이므로 KOSDAQ 25종목에는 새 규칙을 만들지 않는다.

- status=`NOT_SUPPORTED_CURRENT_CONTRACT`
- 업종RS 1M/3M=null
- missing_reason=`CURRENT_OFFICIAL_SECTOR_RS_CONTRACT_IS_KOSPI_ONLY`

## 회귀 게이트
현재 production 업종RS의 benchmark ticker/name과 1M/3M 값을 전부 다시 계산해 완전 일치해야 source cache를 게시한다.

## glossary
실제 키 `compact_footer_text`를 사용한다.

## 안전 규칙
- source_only=true
- standalone_swing_table_enabled=false
- request_time_price_eligible=false
- KOSDAQ 업종 매핑 임의 생성 금지
- production JSON 변경 금지
- Worker 변경 금지
- 기존 지표 계산식 변경 금지
- 정적 종가로 요청현재가 대체 금지
