# V8.8.9 V8.8.8 D&A source 반영 투자종합점수 dry-run 재검증

- 버전: `2026-09-15-v8.8.9-investment-score-da-dry-run-recheck`
- 점수정책: `2026-09-13-v8.8.0-explicit-100-point-scoring-contract`
- 재사용 scorer: `2026-09-13-v8.8.2-investment-score-dry-run-gate-reconciliation`
- D&A source: `2026-09-15-v8.8.8-freeze-xbrl-da-source-layer`
- 상태: DRY_RUN_ONLY

## 원칙

- V8.8.2의 23개 component 공식·구간·가중치를 그대로 재사용한다.
- V8.8.8에서 검증된 exact D&A 66종목만 shadow raw에 반영한다.
- production API에는 쓰지 않는다.
- investment_score_100 production 필드에는 쓰지 않는다.
- 새 D&A ID를 승인하지 않는다.
- 기존 READY 종목의 점수가 달라지면 실패 처리한다.
- 기존 READY가 LIMITED로 후퇴하면 실패 처리한다.

## 다음 단계

READY/LIMITED 변화와 EV/EBITDA blocker 감소량, 남은 결측 사유를 검토한 뒤 production 활성화 여부가 아니라 남은 blocker 해소 순서를 결정한다.
