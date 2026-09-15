# V8.9.6 투자종합점수 남은 blocker 재감사

- 버전: `2026-09-15-v8.9.6-investment-score-remaining-blocker-reaudit`
- 기준 dry-run: `2026-09-15-v8.9.5-v888-plus-v894-da-extension-dry-run`
- 비교 audit: `2026-09-15-v8.9.0-investment-score-remaining-blocker-audit`
- 상태: AUDIT_ONLY

## 목적

- V8.9.5에서 002450 삼익악기가 READY로 전환된 이후 남은 blocker를 재집계한다.
- V8.9.0 대비 002450의 exact D&A blocker 1건 외에는 blocker 집합이 변하지 않았는지 검증한다.

## 기대 변화

- READY: 41 → 42
- LIMITED: 71 → 70
- blocker occurrences: 318 → 317
- single-blocker tickers: 28 → 27
- EXACT_DA_SOURCE: 28 → 27
- EXACT_DA_SOURCE single blockers: 9 → 8
- EV/EBITDA blockers: 31 → 30

## 안전 원칙

- production score/API 변경 없음.
- scoring policy 변경 없음.
- source value 임의 대체 없음.
- V8.9.5와 V8.9.0 파일 수정 없음.
- 정책 semantic blocker는 자동 규칙 변경하지 않는다.
