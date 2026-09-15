# V8.9.5 V8.8.8 + V8.9.4 D&A extension 투자종합점수 dry-run

- 버전: `2026-09-15-v8.9.5-v888-plus-v894-da-extension-dry-run`
- scorer: `2026-09-13-v8.8.2-investment-score-dry-run-gate-reconciliation` 재사용
- baseline: `2026-09-15-v8.8.9-investment-score-da-dry-run-recheck`
- 상태: DRY_RUN_ONLY

## 목적

- V8.8.8 66종목과 V8.9.4 삼익악기 1종목을 shadow raw에서만 결합한다.
- 002450의 유일한 V8.8.9 blocker였던 exact D&A 누락이 해소될 때 LIMITED → READY가 되는지 검증한다.
- 002450 이외 111종목 출력은 V8.8.9와 완전히 동일해야 한다.

## 안전 원칙

- production API와 investment_score_100을 수정하지 않는다.
- V8.8.8, V8.9.4, 원본 raw cache를 수정하지 않는다.
- V8.8.2 scorer 공식·구간·가중치·threshold를 그대로 재사용한다.
- 새 D&A ID를 승인하지 않는다.
- READY 회귀 또는 비대상 종목 변화가 있으면 실패한다.
