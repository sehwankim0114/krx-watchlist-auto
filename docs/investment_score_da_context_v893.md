# V8.9.3 V8.9.2 복구 exact D&A context 감사

- 버전: `2026-09-15-v8.9.3-v892-exact-context-audit`
- 상태: AUDIT_ONLY
- 대상: V8.9.2 승인 exact fact 복구 4종목

## 감사 계약

- V8.8.7의 CFS/OFS 선택 및 XBRL context/value uniqueness 로직을 그대로 재사용한다.
- CFS/OFS basis가 기존 raw source에 없으면 추정하지 않는다.
- target year는 V8.9.2에서 실제 선택된 공식 사업보고서 명칭에서 우선 확인한다.
- 승인 exact depreciation/amortisation이 각각 하나의 값으로 선택될 때만 source promotion candidate로 표시한다.
- candidate 표시는 자동 승격이 아니다.

## 안전 원칙

- production API와 투자종합점수를 수정하지 않는다.
- V8.8.8 source layer와 V8.9.2 evidence를 수정하지 않는다.
- 새 D&A ID를 승인하지 않는다.
- 누락 D&A를 0으로 간주하지 않는다.
- CFS/OFS 구분을 추정하지 않는다.
- 신규 우선주 issuer mapping을 만들지 않는다.

## 다음 단계

BOTH_FACTS_UNIQUE 후보가 있으면 별도 source-only freeze 후 점수 dry-run을 재검증한다.
