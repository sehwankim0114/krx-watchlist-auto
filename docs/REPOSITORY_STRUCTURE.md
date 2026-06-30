# 저장소 운영 파일 분류

## 자동 실행 핵심

- `collect-krx-watchlist.yml`: 공식자료·보조 현재가 수집
- `build_api_json.yml`: API 생성·검증·푸시
- `dart-fx-exposure-safe.yml`: 예약 DART 환율노출 분석

## 수동 실행 보조

다음 파일은 수동 실행용이며 예약 실행되지 않습니다.

- `dart-fx-exposure.yml`
- `apply-custom-gpt-v5-hardening.yml`
- `maintenance-repair.yml`
- `fix-rules-version-contract.yml`
- `safe-repository-cleanup.yml`

수동 보조 워크플로는 장애 복구 기록이므로 삭제하지 않고 보존합니다.
평상시에는 실행할 필요가 없습니다.

## 데이터 폴더

- `latest/`: 자동수집 원본·중간·보정 산출물
- `api/`: Custom GPT가 읽는 공개 JSON
- `latest/deprecated/`: 사용 금지된 구형 상태파일 격리소
- `docs/archive/`: 과거 설명·유지보수 기록

## 단일 원본

- 주식표 규칙: `docs/stock_table_rules_latest.md`
- Custom GPT 지침: `docs/custom_gpt_instructions.md`
- Actions 스키마: `docs/custom_gpt_action_schema.yaml`
- 개인정보처리방침: `docs/custom_gpt_privacy_policy.md`
