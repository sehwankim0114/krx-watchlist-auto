# V8.9.7 남은 D&A single-blocker XBRL 재탐색

- 버전: `2026-09-15-v8.9.7-refresh-single-blocker-da-xbrl`
- 대상: 현재 EXACT_DA_SOURCE 단일 blocker 8종목
- 상태: AUDIT_ONLY

## 배경

V8.9.6에서 supply 단일 blocker 8종목은 production이 180일을 요청하지만 현재 producer가 whole-market DART 조회를 90일로 제한하는 계약 충돌 때문에 `LIMITED + 없음`으로 남는 것이 확인되었다. 90일을 임의로 완전한 부재 증거로 간주하지 않고 supply 경로는 보류한다.

## 이번 감사

- V8.9.2의 검증된 DART 사업보고서 재탐색/XBRL 검사 함수를 재사용한다.
- 정정·원본 사업보고서 접수번호 후보를 모두 다시 확인한다.
- 두 승인 exact D&A fact가 모두 복구된 종목만 다음 context 감사 대상으로 넘긴다.
- partial fact, 미승인 fact, no-fact는 자동 승격하지 않는다.

## 다음 단계

`AUDIT_ALTERNATE_OFFICIAL_SOURCE_FOR_V897_PARTIAL_EXACT_CASES`
