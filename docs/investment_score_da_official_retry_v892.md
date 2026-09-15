# V8.9.2 공식 DART/XBRL D&A 재조회 감사

- 버전: `2026-09-15-v8.9.2-official-dart-xbrl-da-retry`
- 상태: AUDIT_ONLY
- 대상: V8.9.1의 공식 재조회 lane 11종목

## 변경점

- NO_CORP_CODE 종목은 DART 공식 corpCode.xml에서 고유번호를 복구한다.
- 우선주를 포함해 DART corpCode.xml의 정확한 stock_code 매칭만 사용하며, 미매칭 발행사는 별도 issuer mapping 감사로 넘긴다.
- NOT_ZIP 종목은 최신 정정 접수번호 하나에 고정하지 않고 사업보고서 후보를 최신순으로 검사한다.
- 실제 XBRL ZIP을 반환하는 접수번호가 발견되면 그 원본에서 승인 exact D&A fact 존재 여부만 감사한다.

## 안전 원칙

- 새 D&A account ID를 승인하지 않는다.
- partial fact를 0으로 보완하지 않는다.
- production API와 investment_score_100을 수정하지 않는다.
- V8.8.8 source layer를 수정하지 않는다.
- 승인 exact fact가 발견돼도 CFS/OFS context/value uniqueness 검증 전 자동 승격하지 않는다.

## 다음 단계

승인 exact fact가 복구된 종목만 별도 CFS/OFS context/value uniqueness 감사로 넘긴다.
