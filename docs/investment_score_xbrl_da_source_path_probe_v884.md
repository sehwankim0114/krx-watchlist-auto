# V8.8.4 원본 XBRL D&A source-path probe

- 버전: `2026-09-13-v8.8.4-xbrl-da-source-path-probe`
- 상태: PROBE_ONLY
- 대상: V8.8.3의 비금융 NO_DA_CANDIDATE 종목 중 업종별 최대 12개 표본
- 목적: fnlttSinglAcntAll에서 잡히지 않은 D&A fact가 원본 XBRL에 존재하는지 확인
- 점수정책, production API, investment_score_100은 변경하지 않음

## 판정

- 3개 이상 표본에서 추가 D&A fact 확인: 원본 XBRL 추출 경로 확대 검토
- 0개: 이 경로는 blocker 해소용으로 부적합
- 1~2개: 제한적 효과로 보고 추가 표본감사 후 결정
