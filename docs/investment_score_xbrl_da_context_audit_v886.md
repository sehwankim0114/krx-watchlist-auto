# V8.8.6 XBRL D&A value-context 감사

- 버전: `2026-09-15-v8.8.6-xbrl-da-value-context-audit`
- 점수계약: `2026-09-13-v8.8.0-explicit-100-point-scoring-contract`
- 상태: CONTEXT_AUDIT_ONLY

## 목적

- V8.8.5에서 회복한 57종목의 exact IFRS D&A fact를 contextRef 정의와 연결한다.
- 목표 연도의 약 1년 duration context 후보를 식별한다.
- 값 충돌과 dimension/context 다중성을 수치화한다.
- CFS/OFS 선택 규칙은 아직 만들지 않는다.

## annual 후보 규칙

- source cache의 deep_source_year, 없으면 annual_source_year를 목표연도로 사용한다.
- context startDate/endDate가 모두 목표연도에 속한다.
- inclusive duration이 330~370일이다.

## 금지

- context evidence를 최종 D&A 값으로 승격하지 않는다.
- consolidated/separate를 dimension 이름만 보고 임의 추정하지 않는다.
- EV/EBITDA를 다시 계산하지 않는다.
- investment_score_100 또는 production API를 변경하지 않는다.

## 다음

- 실제 dimension signature 빈도를 검토한다.
- CFS/OFS 식별이 공식적으로 가능한 context 구조만 채택한다.
- 이후에만 연간 D&A 값을 source로 승격한다.
