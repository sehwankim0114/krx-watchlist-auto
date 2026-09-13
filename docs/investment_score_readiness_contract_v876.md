# V8.7.6 투자종합점수 계산준비도 계약

버전: `2026-09-12-v8.7.6-readiness-with-ocf-and-20d-elasticity`

## 이번 반영

- 영업현금흐름 공식 원천: 109/112
- 최근 20거래일 하루평균 절대등락률: 112/112
- SOURCE_NOT_CONNECTED 세부항목: 0개

## 계속 금지

- investment_score_100 계산
- 세부 원자료→점수 구간 임의 생성
- 순현금 부채범위 임의 확정
- EV/EBITDA D&A 정책 임의 확정
- 분기 가속·둔화 구간 임의 확정
- 수급 세부점수 규칙 임의 생성

이 단계는 새 원천을 readiness에 반영하는 감사 단계이며 production API를 변경하지 않는다.
