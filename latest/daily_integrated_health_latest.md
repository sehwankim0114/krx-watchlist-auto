# V7.3 일일 통합 건강검사

- 검사시각(KST): 2026-08-28T20:27:27+09:00
- 최종상태: **FAIL**
- 치명 오류: 2
- 경고: 0
- 빌드 ID: `20260828T201737+0900-5a48e0891b`
- 규칙 버전: `2026-07-14-v8.0-request-time-position-alignment`

| 결과 | 검사 항목 | 설명 |
|---|---|---|
| ✅ | `required_files` | 필수 API·규칙 파일이 모두 존재합니다. |
| ✅ | `status_api_sync_ok` | api_sync_ok=true |
| ✅ | `status_official_fresh_now` | official_fresh_now=true |
| ✅ | `status_safe_to_analyze_as_latest` | safe_to_analyze_as_latest=true |
| ✅ | `validation_report` | validation_report.json 상태가 PASS입니다. |
| ✅ | `rules_sha256` | 규칙 파일 SHA-256이 status/manifest와 일치합니다. |
| ✅ | `rules_version_text` | 규칙 문서에 현재 규칙 버전이 표시됩니다. |
| ✅ | `kospi_watchlist_rows` | kospi_watchlist 행 수가 30개로 정상입니다. |
| ❌ | `kospi_watchlist_payload_size` | kospi_watchlist 응답 크기가 시장별 제한을 넘었습니다. |
| ✅ | `kospi_watchlist_build_id` | kospi_watchlist 빌드 ID가 일치하거나 상위 검증값을 사용합니다. |
| ✅ | `kospi_watchlist_rules_version` | kospi_watchlist 규칙 버전이 일치하거나 상위 검증값을 사용합니다. |
| ✅ | `kospi_watchlist_bold_ranges` | kospi_watchlist의 매수·익절 Markdown 가격범위가 모두 정상입니다. |
| ✅ | `kospi_watchlist_manifest_entry` | manifest의 kospi_watchlist 행 수와 상태가 정상입니다. |
| ✅ | `kospi_watchlist_sector_coverage` | kospi_watchlist 섹터/테마가 100% 연결됐습니다. |
| ✅ | `kospi_watchlist_sector_source` | kospi_watchlist 섹터 출처가 KRX KIND입니다. |
| ✅ | `kospi_watchlist_trading_column_label` | kospi_watchlist 거래 열 이름이 정상입니다. |
| ✅ | `kospi_watchlist_per_minute_value` | kospi_watchlist 분당거래금 필드가 모두 존재합니다. |
| ✅ | `kospi_watchlist_trading_activity` | kospi_watchlist 거래활발 등급이 전 행 정상입니다. |
| ✅ | `kospi_watchlist_price_elasticity` | kospi_watchlist 가격탄력 등급이 전 행 정상입니다. |
| ✅ | `kospi_watchlist_financial_status_coverage` | kospi_watchlist 재무수집 상태 집계가 전 행과 일치합니다. |
| ✅ | `kospi_watchlist_financial_basis_coverage` | kospi_watchlist 재무기준 연결률이 최소 기준 이상입니다. |
| ✅ | `kospi_watchlist_financial_growth_coverage` | kospi_watchlist 재무증감률 연결률이 최소 기준 이상입니다. |
| ✅ | `kospi_watchlist_valuation_coverage` | kospi_watchlist 밸류에이션 상태·기준일·PBR 연결이 정상입니다. |
| ✅ | `kospi_watchlist_per_loss_policy` | kospi_watchlist 적자기업 PER 공란 정책이 정상입니다. |
| ✅ | `kospi_watchlist_display_duplicates` | kospi_watchlist에서 알려진 중복 수급표현이 발견되지 않았습니다. |
| ✅ | `kosdaq_watchlist_rows` | kosdaq_watchlist 행 수가 10개로 정상입니다. |
| ✅ | `kosdaq_watchlist_payload_size` | kosdaq_watchlist 응답 크기가 시장별 안전 범위입니다. |
| ✅ | `kosdaq_watchlist_build_id` | kosdaq_watchlist 빌드 ID가 일치하거나 상위 검증값을 사용합니다. |
| ✅ | `kosdaq_watchlist_rules_version` | kosdaq_watchlist 규칙 버전이 일치하거나 상위 검증값을 사용합니다. |
| ✅ | `kosdaq_watchlist_bold_ranges` | kosdaq_watchlist의 매수·익절 Markdown 가격범위가 모두 정상입니다. |
| ✅ | `kosdaq_watchlist_manifest_entry` | manifest의 kosdaq_watchlist 행 수와 상태가 정상입니다. |
| ✅ | `kosdaq_watchlist_sector_coverage` | kosdaq_watchlist 섹터/테마가 100% 연결됐습니다. |
| ✅ | `kosdaq_watchlist_sector_source` | kosdaq_watchlist 섹터 출처가 KRX KIND입니다. |
| ✅ | `kosdaq_watchlist_trading_column_label` | kosdaq_watchlist 거래 열 이름이 정상입니다. |
| ✅ | `kosdaq_watchlist_per_minute_value` | kosdaq_watchlist 분당거래금 필드가 모두 존재합니다. |
| ✅ | `kosdaq_watchlist_trading_activity` | kosdaq_watchlist 거래활발 등급이 전 행 정상입니다. |
| ✅ | `kosdaq_watchlist_price_elasticity` | kosdaq_watchlist 가격탄력 등급이 전 행 정상입니다. |
| ✅ | `kosdaq_watchlist_financial_status_coverage` | kosdaq_watchlist 재무수집 상태 집계가 전 행과 일치합니다. |
| ✅ | `kosdaq_watchlist_financial_basis_coverage` | kosdaq_watchlist 재무기준 연결률이 최소 기준 이상입니다. |
| ✅ | `kosdaq_watchlist_financial_growth_coverage` | kosdaq_watchlist 재무증감률 연결률이 최소 기준 이상입니다. |
| ✅ | `kosdaq_watchlist_valuation_coverage` | kosdaq_watchlist 밸류에이션 상태·기준일·PBR 연결이 정상입니다. |
| ✅ | `kosdaq_watchlist_per_loss_policy` | kosdaq_watchlist 적자기업 PER 공란 정책이 정상입니다. |
| ✅ | `kosdaq_watchlist_display_duplicates` | kosdaq_watchlist에서 알려진 중복 수급표현이 발견되지 않았습니다. |
| ✅ | `us_watchlist_rows` | us_watchlist 행 수가 30개로 정상입니다. |
| ✅ | `us_watchlist_payload_size` | us_watchlist 응답 크기가 시장별 안전 범위입니다. |
| ✅ | `us_watchlist_build_id` | us_watchlist 빌드 ID가 일치하거나 상위 검증값을 사용합니다. |
| ✅ | `us_watchlist_rules_version` | us_watchlist 규칙 버전이 일치하거나 상위 검증값을 사용합니다. |
| ✅ | `us_watchlist_bold_ranges` | us_watchlist의 매수·익절 Markdown 가격범위가 모두 정상입니다. |
| ✅ | `us_watchlist_manifest_entry` | manifest의 us_watchlist 행 수와 상태가 정상입니다. |
| ✅ | `us_watchlist_display_duplicates` | us_watchlist에서 알려진 중복 수급표현이 발견되지 않았습니다. |
| ✅ | `krx_sector_cache` | KRX KIND 전체 섹터 캐시 행 수가 정상입니다. |
| ✅ | `price_position_v78` | 3개월 범위 이탈 위치표시가 정상입니다. |
| ✅ | `recommendation_icon_v79` | 추천 아이콘과 손실·수급 표시 순서가 정상입니다. |
| ❌ | `worker_health` | Cloudflare Worker 상태 또는 정책이 예상과 다릅니다. |
| ✅ | `worker_compact_manifest_size` | Worker 경량 매니페스트 응답 크기가 안전 범위입니다. |
| ✅ | `worker_compact_manifest_values` | 경량 매니페스트의 핵심 상태값이 정상입니다. |
| ✅ | `worker_freshness_source` | 최신성 값 출처가 확인됐습니다. |
| ✅ | `worker_kospi_watchlist` | 경량 매니페스트의 kospi_watchlist 행 수와 상태가 정상입니다. |
| ✅ | `worker_kosdaq_watchlist` | 경량 매니페스트의 kosdaq_watchlist 행 수와 상태가 정상입니다. |
| ✅ | `worker_us_watchlist` | 경량 매니페스트의 us_watchlist 행 수와 상태가 정상입니다. |
| ✅ | `worker_build_id` | Worker 경량 매니페스트 빌드 ID가 저장소와 일치합니다. |

## 판정 기준

- `PASS`: 자동 분석표 사용 가능
- `WARN`: 핵심 기능은 정상이나 표시 또는 캐시 확인 필요
- `FAIL`: 최신표 사용을 중단하고 실패 항목 수정 필요

