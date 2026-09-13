# V8.8.3 EV/EBITDA D&A exact account ID 감사

- 버전: `2026-09-13-v8.8.3-da-exact-id-audit`
- 기준 점수계약: `2026-09-13-v8.8.0-explicit-100-point-scoring-contract`
- 상태: AUDIT_ONLY
- 목적: 현재 raw candidate에서 실제 D&A account_id 분포를 확인한다.
- 이 단계에서는 새 account_id를 승인하지 않는다.
- production API 및 investment_score_100을 변경하지 않는다.

## 현재 계약상 승인된 D&A ID

- `ifrs-full_AdjustmentsForAmortisationExpense`
- `ifrs-full_AdjustmentsForDepreciationExpense`

## 적용 현황

- production 종목: 112
- 금융업 중립처리: 15
- 비금융 적용대상: 97
- 승인 exact ID READY: 14
- 미승인 candidate ID 존재: 1
- D&A candidate 없음: 72
- raw source unavailable: 10
- 승인 exact ID 값 충돌: 0

## 후보 account_id 상위 빈도

| account_id | 분류 | 종목수 | raw건수 | 대표 account_nm |
|---|---|---:|---:|---|
| `ifrs-full_AdjustmentsForDepreciationExpense` | APPROVED_V880 | 18 | 18 | 감가상각비, 감가상각비에 대한 조정, 유형자산감가상각비 |
| `ifrs-full_AdjustmentsForAmortisationExpense` | APPROVED_V880 | 13 | 13 | 무형자산상각비 |
| `dart_AdjustmentsForDepreciationRightofuseAssets` | DART_STANDARD_UNAPPROVED | 3 | 3 | 사용권자산감가상각비, 사용권자산상각비 |
| `dart_AdjustmentsForDepreciationInvestmentProperty` | DART_STANDARD_UNAPPROVED | 2 | 2 | 투자부동산감가상각비 |
| `ifrs-full_AdjustmentsForDepreciationAndAmortisationExpense` | IFRS_STANDARD_UNAPPROVED | 2 | 2 | 감가상각비, 감가상각비 및 상각비 |
| `-표준계정코드 미사용-` | CUSTOM_OR_UNSTANDARDIZED | 1 | 1 | 사용권자산감가상각비 |
| `dart_AdjustmentsForDepreciationLeasedAssets` | DART_STANDARD_UNAPPROVED | 1 | 1 | 운용리스자산 감가상각비 |
| `ifrs-full_DepreciationAndAmortisationExpense` | IFRS_STANDARD_UNAPPROVED | 1 | 1 | 감가상각비 |
| `ifrs-full_DepreciationExpense` | IFRS_STANDARD_UNAPPROVED | 1 | 1 | 감가상각비 |

## 판정 규칙

- APPROVED_V880: 기존 V8.8.0 계약에 이미 포함된 exact IFRS ID.
- IFRS_STANDARD_UNAPPROVED: ifrs-full_ 형식이지만 아직 점수계약에는 미승인.
- DART_STANDARD_UNAPPROVED: dart_ 형식이지만 아직 점수계약에는 미승인.
- CUSTOM_OR_UNSTANDARDIZED: 회사별 확장 또는 비표준 ID 가능성이 있어 자동 승인 금지.

## 다음 단계

반복 빈도와 account_nm을 검토해 공식 표준 ID인지 검증한 뒤, 명시적 계약 변경이 필요한 경우에만 별도 단계에서 승인한다.
