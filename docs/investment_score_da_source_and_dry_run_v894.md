# V8.9.4 삼익악기 D&A source-only 승격 + 점수 dry-run

- 버전: `2026-09-15-v8.9.4-extend-da-source-and-rerun-dry-run`
- production 미적용

## source-only 확장

- V8.8.8 66종목을 변경하지 않고 V8.9.4 파생 계층을 새로 생성한다.
- V8.9.3에서 검증된 삼익악기(002450)만 추가한다.
- 새 source-only 계층은 67종목이다.

## 점수 재검증

- V8.8.2 scorer의 공식·가중치·구간을 그대로 재사용한다.
- 비교 기준은 V8.8.9 READY 41 / LIMITED 71이다.
- 기존 READY 41종목의 점수가 하나라도 바뀌면 실패한다.
- 삼익악기 외 다른 종목이 새 READY가 되면 실패한다.
- 삼익악기가 READY가 아니어도 실패한다.

## 다음 단계

V8.9.4 결과를 기준으로 남은 LIMITED blocker 감사를 새로 계산하고 정책 변경 없이 복구 가능한 다음 source group을 선택한다.
