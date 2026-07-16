# KRX Watchlist Auto 사용법

## 현재 운영 구조

1. `.github/workflows/collect-krx-watchlist.yml`이 공식 KRX 자료와 보조자료를 수집합니다.
2. 수집 결과는 `latest/`에 저장됩니다.
3. `.github/workflows/build_api_json.yml`이 Custom GPT용 `api/` JSON을 생성하고 검증합니다.
4. `validate_api_sync.py`가 최신성·규칙·행 수·단일표·단일 Action 계약을 검증합니다.
5. Custom GPT는 아래 Worker 하나를 통해 상태·규칙·본표·요청시점 보조현재가를 조회합니다.

```text
https://krx-live-price-ksh.diaconos.workers.dev
```

## 현재 규칙 확인 방법

규칙 버전을 README의 고정 문자열로 판단하지 않습니다. 매 요청과 점검에서 다음 파일의 값을 서로 대조합니다.

- `api/status.json`의 `rules_version`, `rules_sha256`, `build_id`
- `api/manifest.json`의 `rules_version`, `rules_sha256`, `build_id`
- `api/stock_table_rules.json`의 `rules_version`, `rules_sha256`, `build_id`

세 파일의 값이 일치하고 `api_sync_ok=true`, `api/validation_report.json`의 `status=PASS`일 때 구조 검증을 통과한 것으로 봅니다.

## Custom GPT 운영 원칙

- 설치용 Action 스키마: `docs/custom_gpt_action_schema.yaml`
- Action 도메인: Worker 주소 한 개
- `raw.githubusercontent.com`을 별도 Action으로 등록하지 않음
- Action 인증: 없음(None)
- Knowledge 사용 안 함
- 기본 출력: 요청한 본표 한 개
- 코피표: 코스피 분석 후보 30개
- 코닥표: 코스닥 분석 후보 10개
- 미관종표: S&P500 기반 미국 분석 후보 30개
- 요청시점 현재가: 처음 10개씩, 실패만 5개씩, 남은 실패는 2개씩 재시도
- 보유종목표: 개인 보유정보를 Action·GitHub·API에 저장하지 않고 응답 시점에만 계산

## 13개 표 명령

- 관종표
- 분석표
- 코피표
- 코피표1개월
- 코닥표
- 코닥표1개월
- 코급표
- 월사이클표
- 단상표
- 환율약세표
- 시장상태표
- 보유종목표
- 미관종표

명령별 실제 operationId와 상태는 `api/manifest.json`의 `command_route_contract`를 확인합니다.

## 핵심 운영 파일

- 자동수집: `.github/workflows/collect-krx-watchlist.yml`
- API 생성: `.github/workflows/build_api_json.yml`
- API 생성기: `build_api_json.py`
- API 검증기: `validate_api_sync.py`
- 최신 규칙: `docs/stock_table_rules_latest.md`
- Custom GPT 지침: `docs/custom_gpt_instructions.md`
- 통합 Action 스키마: `docs/custom_gpt_action_schema.yaml`
- 개인정보처리방침: `docs/custom_gpt_privacy_policy.md`
- 보유종목 비저장 계약: `docs/holdings_private_runtime_contract.md`

## 정상 확인 기준

- `api/status.json`: `status=READY`
- `api/status.json`: `api_sync_ok=true`
- `api/validation_report.json`: `status=PASS`
- 상태·매니페스트·규칙의 `build_id` 일치
- 상태·매니페스트·규칙의 `rules_version`, `rules_sha256` 일치
- 통합 Action 스키마의 서버가 Worker 한 개
- Action operationId 30개가 모두 고유
- `raw.githubusercontent.com` Action 없음
- 13개 명령 경로 준비·출력 가능
- 보유종목 공개 참고행은 `prefix+ticker`와 선택 `market`으로 정확히 1행 조회

`official_fresh_now=false`는 공식자료 게시 지연일 수 있습니다. 이 경우 `api_sync_ok=true`라면 직전 확정자료로 제한 분석하며 최신자료라고 표현하지 않습니다.

## 보존과 정리 원칙

- `latest/`와 `api/`의 역할이 다른 파일을 임의로 합치거나 삭제하지 않습니다.
- 일회성 적용 워크플로는 작업 완료 후 `.github/workflows`에서 제거합니다.
- 완료된 과거 워크플로는 `docs/workflow_archive/`에서 기록으로만 보존합니다.
- 과거 별도 요청시점 가격 스키마는 `docs/archive/legacy-schemas/`에서 기록으로만 보존하며 별도 Action으로 설치하지 않습니다.
- `safe-repository-cleanup.yml`은 읽기 전용 감사 워크플로이며 저장소 파일을 변경하지 않습니다.
