# V8.8.8 D&A source-only 계층 동결

- 버전: `2026-09-15-v8.8.8-freeze-xbrl-da-source-layer`
- 상태: SOURCE_ONLY_READY
- production 미적용

## 동결 규칙

- 재무제표 기준: CFS 우선, 없을 때 OFS.
- XBRL 축: ConsolidatedAndSeparateFinancialStatementsAxis.
- CFS member: ConsolidatedMember.
- OFS member: SeparateMember.
- 기존 V8.8.0 승인 exact D&A ID만 사용.
- V8.8.7 신규 XBRL 값은 두 승인 fact가 모두 유일한 52종목만 승격.
- partial one fact 4종목, member 미매칭 1종목은 승격하지 않음.
- EV/EBITDA와 investment_score_100은 이 단계에서 재계산하지 않음.

## 다음 단계

V8.8.8 source-only D&A 계층을 사용해 EV/EBITDA와 100점 점수를 다시 dry-run하고 READY/LIMITED 분포를 재검증한다.
