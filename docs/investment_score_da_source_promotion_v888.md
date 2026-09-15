# V8.8.8 source-only D&A 승격 계약

- 버전: `2026-09-15-v8.8.8-source-only-da-promotion`
- 상태: `READY_SOURCE_ONLY`
- 목적: V8.8.7에서 검증된 D&A 값을 production과 분리된 source-only 층으로 고정한다.

## 승격 조건

- V8.8.0에서 승인된 정확한 두 IFRS 계정 ID만 사용한다.
- 기존 재무정책과 동일한 CFS/OFS member를 사용한다.
- 감가상각과 무형자산상각 값이 각각 유일하고 두 fact가 모두 있어야 한다.
- 값/context 충돌이 없고 단위가 KRW이어야 한다.

## 결과

- 57개 중 52개만 source-only D&A READY로 승격한다.
- partial one fact 4개와 matching FS member가 없는 1개는 보류한다.

## 이번 단계에서 하지 않는 것

- 기존 V8.8.3의 14개 exact-ready와 병합하지 않는다.
- production source cache를 수정하지 않는다.
- EV/EBITDA를 재계산하지 않는다.
- 100점 투자점수를 기록하지 않는다.
- 새로운 D&A 계정 ID를 승인하지 않는다.

## 다음 단계

- V8.8.9에서 기존 raw D&A와 V8.8.8 source-only D&A의 병합 우선순위를 dry-run으로 검증한다.
- production 반영은 별도 승인 단계까지 금지한다.
