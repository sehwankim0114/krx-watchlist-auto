# V8.9.2 공식 DART XBRL 재시도 감사

- 버전: `2026-09-15-v8.9.2-retry-failed-official-xbrl`
- 대상: 삼익악기(002450), 한화에어로스페이스(012450), 에쓰씨엔지니어링(023960)
- 세 종목 모두 V8.9.1에서 D&A 단일 blocker이고, V8.8.5 당시 XBRL 응답은 NOT_ZIP이었다.

## 방식

- V8.8.5의 기존 접수번호를 우선 재시도한다.
- DART 공시검색에서 2025 사업보고서 후보 접수번호를 다시 수집한다.
- 각 후보에 대해 `fnlttXbrl.xml` + `reprt_code=11011`을 호출한다.
- ZIP이면 승인 exact D&A local name 존재 여부까지만 감사한다.
- ZIP이 아니면 XML `status/message`를 보존하여 013/014 등 공식 오류를 구분한다.
- 어떤 값도 V8.8.8 D&A source layer 또는 점수에 자동 승격하지 않는다.

## 다음 단계

`AUDIT_RECOVERED_XBRL_CONTEXTS_BEFORE_ANY_DA_SOURCE_PROMOTION`
