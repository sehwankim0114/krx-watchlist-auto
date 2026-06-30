# KRX Watchlist Auto 사용법

## 현재 운영 구조

이 저장소는 다음 순서로 작동합니다.

1. `.github/workflows/collect-krx-watchlist.yml`이 공식 KRX 자료와 보조 현재가를 수집합니다.
2. 수집 결과는 `latest/`에 저장됩니다.
3. `.github/workflows/build_api_json.yml`이 `api/` JSON을 생성합니다.
4. `validate_api_sync.py`가 최신성·규칙 버전·행 수·단일표 정책을 검증합니다.
5. Custom GPT는 `api/status.json`과 `api/stock_table_rules.json`을 먼저 확인한 뒤 요청한 본표 API를 읽습니다.

## 현재 규칙

- 규칙 버전: `2026-06-30-v5-strict-contract`
- 기본 출력: 한 요청당 본표 하나
- 코피표: 후보 30개 본표 하나
- 코닥표: 후보 10개 본표 하나
- 추천 종목은 본표 안에서 표시
- 별도 핵심추천표는 사용자가 명시적으로 요청한 경우에만 작성
- Knowledge 파일은 사용하지 않음
- Custom GPT Actions 인증: 없음(None)

## 핵심 운영 파일

- 자동수집: `.github/workflows/collect-krx-watchlist.yml`
- API 생성: `.github/workflows/build_api_json.yml`
- API 생성기: `build_api_json.py`
- API 검증기: `validate_api_sync.py`
- 최신 규칙: `docs/stock_table_rules_latest.md`
- Custom GPT 지침: `docs/custom_gpt_instructions.md`
- Custom GPT Actions: `docs/custom_gpt_action_schema.yaml`
- 개인정보처리방침: `docs/custom_gpt_privacy_policy.md`

## 삭제하거나 합치면 안 되는 파일

다음 파일들은 역할이 다르므로 그대로 둡니다.

- `latest/*_latest.*`
- `latest/*_current_basis_latest.*`
- `latest/*_supplemented_latest.*`
- 날짜별 `raw_history_*.csv`
- 날짜별 `watchlist_summary_*.csv`
- `latest/deprecated/`
- 추천 7개·5개 내부 CSV

## 정상 확인 기준

`api/status.json`에서 다음 값이 정상이어야 합니다.

- `status=READY`
- `api_sync_ok=true`
- `official_fresh_now=true`
- `safe_to_analyze_as_latest=true`
- `rules_version=2026-06-30-v5-strict-contract`

`api/validation_report.json`은 `status=PASS`여야 합니다.

## 주의

- `latest/deprecated/`의 파일은 현재 분석에 사용하지 않습니다.
- 일회성 유지보수 워크플로는 수동 실행 전용이며 자동으로 실행되지 않습니다.
- 투자판단은 자동수집 자료만으로 확정하지 말고 공시·뉴스·실적을 함께 확인합니다.
