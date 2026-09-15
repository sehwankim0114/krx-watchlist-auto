# V8.10.1 수급 source-only freeze + 격리 dry-run

- 버전: `2026-09-15-v8.10.1-freeze-complete-supply-evidence-and-dry-run`
- 기준선: `2026-09-15-v8.9.5-v888-plus-v894-da-extension-dry-run`
- V8.10.0 180일 완전조회 23종목만 shadow supply source로 사용한다.
- 먼저 현재 입력으로 V8.9.5 결과 112행을 정확히 재현한 뒤에만 overlay를 적용한다.
- corp_code exact stock이 풀리지 않은 10종목은 그대로 LIMITED로 유지한다.
- V8.9.9 earnings-trend shadow fix는 일부러 합치지 않아 수급 효과만 격리한다.
- production API와 investment_score_100은 수정하지 않는다.

- READY: 42 → 50
- LIMITED: 70 → 62
- 수급 blocker: 33 → 10
- 새 READY: 003280, 063160, 066570, 071840, 081000, 086280, 100250, 286940
