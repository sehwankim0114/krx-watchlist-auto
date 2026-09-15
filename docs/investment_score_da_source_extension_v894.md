# V8.9.4 V8.9.3 검증 D&A source extension 동결

- 버전: `2026-09-15-v8.9.4-freeze-v893-da-source-extension`
- 상태: SOURCE_EXTENSION_ONLY_READY
- base V8.8.8은 변경하지 않음

## 동결 대상

- 002450 삼익악기
- 2025 CFS
- V8.9.3에서 depreciation/amortisation 각각 단일 값 확인
- value/context conflict 없음

## 안전 원칙

- V8.8.8 66종목 source layer는 수정하지 않는다.
- production API와 investment_score_100을 수정하지 않는다.
- 새 D&A ID를 승인하지 않는다.
- 누락 D&A를 0으로 간주하지 않는다.
- 우선주 issuer mapping을 새로 만들지 않는다.

## 다음 단계

V8.9.5에서 V8.8.8 66종목 + V8.9.4 1종목을 shadow raw에만 합쳐 기존 V8.8.2 scorer로 투자종합점수를 dry-run 재검증한다.
