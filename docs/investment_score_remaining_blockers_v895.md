# V8.9.5 V8.9.4 기준 남은 blocker 재감사

- 버전: `2026-09-15-v8.9.5-refresh-remaining-blocker-audit`
- 기준 dry-run: `2026-09-15-v8.9.4-extend-da-source-and-rerun-dry-run`
- READY 42 / LIMITED 70
- 상태: AUDIT_ONLY

## 목적

삼익악기 D&A 복구 후 남은 LIMITED blocker를 V8.9.0과 같은 분류기로 다시 계산한다.
source 발생 건수뿐 아니라 한 source만 해결하면 READY가 되는 single-blocker 수를 우선순위에 반영한다.

## 안전 원칙

- 점수 공식·가중치·구간 변경 없음.
- production score 기록 없음.
- 결측값 임의 대체 없음.
- 정책 semantic blocker는 자동 규칙 변경 대상에서 제외.

## 다음 단계

최우선 source group: `PRODUCTION_ANALYSIS_SUPPLY`
single-blocker 잠재 해소 종목: `8`
`AUDIT_SUPPLY_EVIDENCE_COMPLETENESS`
