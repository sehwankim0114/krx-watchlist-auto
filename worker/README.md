# Cloudflare Worker 운영 원본

이 폴더는 Custom GPT 단일 Action 도메인의 배포 원본과 회귀검증기를 보관합니다.

- 배포 도메인: `https://krx-live-price-ksh.diaconos.workers.dev`
- 이번 배포 대상: `1.4.0-two-table-guarded-preview` (실제 배포 여부는 `/health`로 확인)
- 운영 원본: `krx-live-price-worker.js`
- 회귀검증기: `validate_worker.mjs`
- 새 두 표 전달 검사: `validate_two_table_proxy_v852.mjs`

Worker는 요청시점 한국·미국 보조현재가와 GitHub 공개 API JSON 프록시를 한 도메인으로 제공합니다. `raw.githubusercontent.com`은 Worker 내부의 공개자료 원본 조회에만 사용하며 Custom GPT에 별도 Action 도메인으로 등록하지 않습니다.

## 기존 V1.3.9 기능 보존

- 코피표 30행을 `KOSPI_ACTION_V2` 응답 프로필로 30,000바이트 미만에 제공합니다. 중복 식별값 `code`·`quote_market`은 제외하고 `quote_key`와 KOSPI 표 식별자를 사용합니다.
- 원래 행 순서와 표시 필수값을 보존하며 API 값을 재계산하지 않습니다.
- 정적 `current_position`은 제외하고, 요청시점 현재가와 보존된 3개월 저가·고가를 이용해 응답 작성 단계에서 다시 계산합니다.
- Raw GitHub 조회 오류 또는 제한시간 초과 시 GitHub Contents API로 자동 전환합니다.
- 기본·대체 원본 조회 제한시간은 각각 6,000ms입니다.

## V1.4.0 새 두 표 전달 경로

새 `/tables/v1/kospi`, `/tables/v1/decliners`, `/tables/v1/decliners24`는 명시적인
`mode=preview`로만 준비자료를 읽습니다. 운영 활성화 전 기본 요청은 차단하며,
기존 코피표·현재가·보유종목 Action 동작을 변경하지 않습니다.

페이지별 30행·30,000바이트, SHA-256, 빌드·규칙·기준일·최신성, 전체 페이지
연속성을 검사합니다. 데이터·점수·현재가는 재계산하지 않습니다. 2페이지부터는
응답의 다음 페이지 주소에 포함된 `build_id`를 유지해야 합니다.

자세한 전환 순서는 `docs/two_table_worker_v852.md`를 따릅니다. Worker 배포만으로
GPT 새 양식이 활성화되지는 않습니다.

## 검증

저장소 루트에서 다음 명령을 실행합니다.

```bash
node worker/validate_worker.mjs .
node worker/validate_two_table_proxy_v852.mjs .
```

검증기는 다음 계약을 확인합니다.

- 13개 표 명령 경로 보존
- 관종표 47행 압축 응답과 원본 값 보존
- 미관종표 30행 압축 응답, 순서·값 보존 및 응답 크기 제한
- 코피표 30행 `KOSPI_ACTION_V2`, 표시 필수값 보존 및 30,000바이트 제한
- 코피표 정적 현재위치 제외와 V8.0 요청시점 재계산 계약
- 코피·코닥·1개월·코급·월사이클·환율약세·단상 등 10개 표 경로의 압축 응답, 행 순서·값 보존 및 45,000바이트 제한
- Raw GitHub 조회 실패 시 GitHub Contents API 대체경로 작동
- 보유종목 공개 참고행의 정확 티커 필터와 개인정보 비포함
- Worker 상태 응답의 배포 버전·압축 경로 수·KOSPI 응답 프로필

## 배포 원칙

Cloudflare Worker 편집기에는 `krx-live-price-worker.js` 전체를 배포합니다. 배포 후 `/health`의 `build_version`이 배포 대상 버전과 일치하는지 확인합니다. Worker 배포 자체는 GitHub Actions가 자동으로 수행하지 않습니다. GPT 지침·Action은 대응하는 운영 데이터 계약이 준비된 뒤 별도 교체합니다.
