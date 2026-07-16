# 저장소 운영 파일 분류

## 예약·운영 워크플로

- `collect-krx-watchlist.yml`: 공식 KRX 자료와 보조자료 수집
- `build_api_json.yml`: API 생성·검증·푸시
- `dart-fx-exposure-safe.yml`: DART 환율노출 안전 분석
- `v6-apply-us-sp500-production.yml`: 통합 Action 계약을 보존하고 구형 route patch 없이 미국 S&P500 운영자료 생성
- `v731-daily-integrated-health.yml`: 일일 통합 상태 점검
- `v77-runtime-freshness-gate.yml`: 요청시점 최신성 상태 갱신

위 파일은 `workflow_dispatch`도 지원하지만 예약 또는 연계 실행이 있는 운영 파일이므로 임의로 보관 폴더로 옮기지 않습니다.

## 수동 유지보수 워크플로

- `maintenance-repair.yml`: 필요한 경우에만 실행하는 복구 도구
- `safe-repository-cleanup.yml`: `--check-only` 실시간 API 검증과 미국 운영경로 검사를 포함하고 저장소를 변경하지 않는 읽기 전용 V8.2.7 감사 도구

일회성 적용 워크플로는 작업 완료 후 `.github/workflows`에서 제거하고, 필요한 기록은 `docs/workflow_archive/`에 보관합니다.

## 데이터 폴더

- `latest/`: 자동수집 원본·중간·보정 산출물
- `api/`: Custom GPT가 Worker를 통해 읽는 공개 JSON
- `latest/deprecated/`: 현재 분석에 사용하지 않는 구형 상태파일
- `docs/archive/`: 과거 문서·스키마 기록
- `docs/workflow_archive/`: 완료된 과거 GitHub Actions 기록

## 단일 운영 원본

- 주식표 규칙: `docs/stock_table_rules_latest.md`
- Custom GPT 지침: `docs/custom_gpt_instructions.md`
- 설치용 통합 Action 스키마: `docs/custom_gpt_action_schema.yaml`
- 개인정보처리방침: `docs/custom_gpt_privacy_policy.md`
- 보유종목 비저장 계약: `docs/holdings_private_runtime_contract.md`

## 단일 Worker Action

- Action 도메인: `https://krx-live-price-ksh.diaconos.workers.dev`
- 서버 개수: 1개
- `raw.githubusercontent.com` 별도 Action: 사용 금지
- 상태·규칙·본표·요청시점 가격·보유종목 공개 참고행을 통합 스키마에서 호출
- 보유종목 공개 참고행: `prefix+ticker` 필수, `market` 선택
- 사용자 보유수량·평균매수가·현금/신용 정보: Action·GitHub·API에 저장하지 않음

과거 `docs/custom_gpt_live_price_action_schema.yaml`은 활성 설치파일이 아닙니다. 원본 기록은 `docs/archive/legacy-schemas/custom_gpt_live_price_action_schema-v1.1.0.yaml`에 보관합니다.

## 현재 상태 확인

고정된 과거 버전 문구를 기준으로 삼지 않고 다음 값을 실행 시점에 확인합니다.

- `api/status.json`: `status`, `api_sync_ok`, `official_fresh_now`, `safe_to_analyze_as_latest`
- `api/manifest.json`: `build_id`, `rules_version`, `rules_sha256`, `command_route_contract`
- `api/validation_report.json`: `status`, `errors`, `warnings`
- `api/stock_reference_manifest.json`: `action_contract`, `privacy_policy`, `usage`
