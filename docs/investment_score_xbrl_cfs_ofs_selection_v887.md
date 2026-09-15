# V8.8.7 XBRL CFS/OFS 선택 감사

- 버전: `2026-09-15-v8.8.7-xbrl-cfs-ofs-selection-audit`
- 상태: SELECTION_AUDIT_ONLY

## 기존 정책

- `연결재무제표(CFS)를 우선하고, 없을 때만 개별재무제표(OFS)를 쓴다.`

## XBRL 축 대응 검증

- CFS ↔ `ConsolidatedAndSeparateFinancialStatementsAxis=ConsolidatedMember`
- OFS ↔ `ConsolidatedAndSeparateFinancialStatementsAxis=SeparateMember`
- 목표연도 source와 동일한 fs_div를 우선 대조한다.

## 이번 단계에서 하지 않는 것

- 선택된 D&A 값을 production source로 승격하지 않는다.
- EV/EBITDA를 재계산하지 않는다.
- 100점 점수를 기록하지 않는다.
- 새로운 D&A 계정 ID를 승인하지 않는다.

## 다음 단계 조건

- source fs_div 불일치가 없어야 한다.
- 선택한 member 안에서 depreciation/amortisation 각각 값이 유일해야 한다.
- 두 exact fact가 모두 존재하는 종목만 source-only 승격 후보로 본다.
