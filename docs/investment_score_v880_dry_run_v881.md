# V8.8.1 투자종합점수 dry-run

버전: `2026-09-13-v8.8.1-investment-score-dry-run`

V8.8.0 승인 계약을 production에 쓰지 않고 현재 production 112종목에 시험 계산한다.

## 안전장치

- LIMITED 종목은 score_total=null
- supply_status가 OK가 아니면 수급점수 확정 금지
- EV/EBITDA·순현금은 정확한 원천만 사용
- legacy_market_score 재환산 금지
- api/two_table_v1 변경 금지

## 다음 단계

READY/LIMITED 비율, 점수분포, 결측 사유, 금융업 중립처리를 검토한 뒤 production 활성화 여부를 판단한다.
