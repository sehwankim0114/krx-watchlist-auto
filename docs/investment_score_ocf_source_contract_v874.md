# V8.7.4 영업현금흐름 공식 원천 계약

버전: `2026-09-12-v8.7.4-audited-operating-cash-flow-source`

## 목적

투자종합점수의 영업현금흐름 4점 항목에 사용할 공식 원천만 준비한다.
이 단계에서는 점수를 계산하지 않는다.

## 직접 종목

V8.7.3 감사에서 확인된 OpenDART 전체 재무제표의
`ifrs-full_CashFlowsFromUsedInOperatingActivities` 정확 일치값만 사용한다.

## 우선주

V8.7.0 업종RS에서 이미 검증된
`UNIQUE_COMMON_SHARE_BY_EXACT_NORMALIZED_OFFICIAL_KRX_ISU_NM_STEM`
대응관계가 존재하는 경우에만 대응 보통주 발행회사의 동일 IFRS 계정을 상속한다.

종목명 유사성, ticker prefix, 임의 fuzzy mapping은 사용하지 않는다.

## 제외

DI동일·KCC처럼 기존 재무수집기에서 회사명 불일치로 제한된 종목은
이번 단계에서 강제 매칭하지 않는다.

OpenDART에서 재무제표 원천이 없는 종목도 강제 보완하지 않는다.

## 가격탄력

정책은 `최근 20거래일 하루평균 절대등락률`이지만
현재 `collect_universe.py`는 최근 3개월 구간 전체의 절대 일간수익률 평균을 계산한다.
두 계약이 일치할 때까지 투자점수 원천으로 사용하지 않는다.

## 안전장치

- investment_score_100 미계산
- 점수구간 미정 유지
- production API 미변경
