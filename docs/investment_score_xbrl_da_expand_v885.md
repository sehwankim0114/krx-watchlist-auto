# V8.8.5 원본 XBRL D&A 전체 확대 감사

- 버전: `2026-09-14-v8.8.5-expanded-xbrl-da-audit`
- 점수계약: `2026-09-13-v8.8.0-explicit-100-point-scoring-contract`
- 상태: EXPANDED_AUDIT_ONLY

## 범위

- production 고유 종목: 112
- 금융업 중립처리: 15
- 비금융 적용대상: 97
- 기존 exact D&A READY: 14
- 확대 감사 대상: 83

## 결과

- 사업보고서 확인: 73/83
- XBRL ZIP 정상 분석: 70/83
- D&A 관련 fact 존재: 61/83
- V8.8.0 승인 exact IFRS fact 추가 발견: 57/83
- 잠재 비금융 D&A 원천 READY: 71/97
- 잠재 비금융 D&A 커버리지: 73.2%

## 주의

- 이 단계는 fact 존재 여부 감사다.
- contextRef, 기간, 연결/별도, 중복값 판정을 완료하기 전에는 EBITDA 값으로 승격하지 않는다.
- 새로운 account/local-name을 자동 승인하지 않는다.
- investment_score_100 또는 production API를 변경하지 않는다.

## 다음 단계

- 승인 exact XBRL fact의 연간 값/context 추출 규칙을 검증한다.
- 검증 후 EV/EBITDA 원천을 다시 계산한다.
- 그 다음 V8.8.0 점수 dry-run을 재실행한다.
