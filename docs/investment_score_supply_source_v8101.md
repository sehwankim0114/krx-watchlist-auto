# V8.10.1 180일 완전조회 수급 evidence source freeze

- 버전: `2026-09-15-v8.10.1-freeze-complete-supply-evidence-and-dry-run`
- 상태: `SOURCE_ONLY_READY`
- V8.10.0에서 180일 모든 구간이 완결된 23종목만 고정한다.
- DART exact stock_code issuer가 풀리지 않은 10종목은 제외한다.
- 위험공시 없음은 전 구간 완전조회일 때만 `OK/없음`으로 고정한다.
- 위험공시가 확인된 종목은 기존 supply keyword contract의 실제 level을 보존한다.
- production API 및 investment_score_100은 수정하지 않는다.
