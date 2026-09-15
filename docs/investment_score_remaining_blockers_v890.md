# V8.9.0 투자종합점수 남은 blocker 감사

- 버전: `2026-09-15-v8.9.0-investment-score-remaining-blocker-audit`
- 기준 dry-run: `2026-09-15-v8.8.9-investment-score-da-dry-run-recheck`
- 상태: AUDIT_ONLY

## 목적

V8.8.9의 LIMITED 71종목을 source gap, evidence gap, policy semantic blocker로 분해한다.

## 안전 원칙

- 점수 공식·가중치·구간 변경 없음.
- production investment_score_100 기록 없음.
- 결측값 임의 대체 없음.
- ANNUAL_OP_DENOM_NONPOSITIVE는 승인 계약을 바꾸지 않고 별도 분류만 한다.
- source 보강 우선순위는 blocker 발생 수와 single-blocker 해소 가능성을 함께 본다.

## 다음 단계

source_priority 결과를 보고 정책 변경 없이 복구 가능한 가장 영향도 높은 source group부터 별도 audit/recovery를 진행한다.
