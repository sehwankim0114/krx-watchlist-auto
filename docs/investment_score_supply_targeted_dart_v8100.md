# V8.10.0 종목별 DART 180일 수급·공시 completeness 감사

- 버전: `2026-09-15-v8.10.0-targeted-dart-supply-completeness-audit`
- 기준 blocker audit: `2026-09-15-v8.9.6-investment-score-remaining-blocker-reaudit`
- 기존 supply 정책: `2026-07-01-v6.0-supply-status-separated`
- 상태: AUDIT_ONLY

## 목적

- V8.9.6의 PRODUCTION_ANALYSIS_SUPPLY blocker 33종목을 감사한다.
- whole-market 90일 상한 대신 종목별 DART corp_code 조회를 사용한다.
- 180일을 90일 이하 구간으로 나눠 각 구간의 모든 페이지를 확인한다.
- 모든 구간이 완결된 경우에만 위험 공시 '없음'을 complete evidence 후보로 분류한다.

## 판정

- COMPLETE_180D_POSITIVE_BURDEN: 180일 완전조회 + 기존 위험 키워드 공시 있음.
- COMPLETE_180D_NO_POSITIVE_BURDEN: 180일 완전조회 + 기존 위험 키워드 공시 없음.
- TARGETED_DART_180D_INCOMPLETE: 일부 구간/페이지 실패. 없음으로 판정 금지.
- CORP_CODE_EXACT_STOCK_UNRESOLVED: exact stock_code로 issuer가 유일하게 확인되지 않음.

## 안전 원칙

- production API와 investment_score_100을 수정하지 않는다.
- scoring/supply 정책을 바꾸지 않는다.
- corp_code는 DART exact stock_code만 사용하며 issuer mapping을 추정하지 않는다.
- 불완전 조회를 '없음'으로 처리하지 않는다.
- 이번 단계는 source overlay 후보만 만든다.
