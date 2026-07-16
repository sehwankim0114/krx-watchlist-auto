# Cloudflare Worker 운영 원본

이 폴더는 Custom GPT 단일 Action 도메인의 배포 원본과 회귀검증기를 보관합니다.

- 배포 도메인: `https://krx-live-price-ksh.diaconos.workers.dev`
- 현재 배포 계약: `1.3.6-us-watchlist-compact`
- 운영 원본: `krx-live-price-worker.js`
- 회귀검증기: `validate_worker.mjs`

Worker는 요청시점 한국·미국 보조현재가와 GitHub 공개 API JSON 프록시를 한 도메인으로 제공합니다. `raw.githubusercontent.com`은 Worker 내부의 공개자료 원본 조회에만 사용하며 Custom GPT에 별도 Action 도메인으로 등록하지 않습니다.

## 검증

저장소 루트에서 다음 명령을 실행합니다.

```bash
node worker/validate_worker.mjs .
```

검증기는 다음 계약을 확인합니다.

- 13개 표 명령 경로 보존
- 관종표 47행 압축 응답과 원본 값 보존
- 미관종표 30행 압축 응답, 순서·값 보존 및 응답 크기 제한
- 보유종목 공개 참고행의 정확 티커 필터와 개인정보 비포함
- Worker 상태 응답의 배포 버전

## 배포 원칙

Cloudflare Worker 편집기에는 `krx-live-price-worker.js` 전체를 배포합니다. 배포 후 `/health`의 `build_version`이 이 문서의 현재 배포 계약과 일치하는지 확인합니다. Worker 배포 자체는 GitHub Actions가 자동으로 수행하지 않습니다.
