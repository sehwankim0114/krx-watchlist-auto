# V8.7.11 독립 스윙 운영승격 직전 계약 동결

버전: `2026-09-13-v8.7.11-standalone-swing-preproduction-freeze`

상태: `FROZEN_PREPRODUCTION_READY / PRODUCTION_DISABLED`

## 목적

V8.7.6 통합 독립 스윙 source, V8.7.9 데이터품질 게이트, V8.7.10 요청시점 현재가 경로 검증까지 통과한 상태를 운영승격 직전 계약으로 동결한다.

이번 단계는 독립 스윙표를 실제 운영에 활성화하지 않는다.

## 동결되는 데이터 snapshot

기준일: `2026-09-11`

- 전체 235종목
- KOSPI 210
- KOSDAQ 25
- 1M 수익률 235/235
- 3M 수익률 235/235
- 6M 수익률 234/235
- 큰 스윙 상태 235/235
- MA5/20/60/120 전체 준비 234/235
- ATR14 209/235
- 20일 평균 일중고저폭 225/235
- KOSPI 상대강도 235/235
- KOSPI 공식 업종RS 210/210
- KOSDAQ 업종RS null 25/25
- 확정 스윙저점 손절 0/235
- 미확정 지표 임의 채움 0건

이 snapshot이 예상과 달라지면 자동 승격하지 않고 재검토한다.

## 인정된 자료 미제공

다음 결측은 오류로 보정하지 않는다.

- 6M: 상장이력 부족이면 자료 미제공
- MA: 필요한 확정 일봉 이력이 부족하면 자료 미제공
- ATR14: 공식 lookback에 0-OHLC·무거래 원천행이 포함되면 자료 미제공
- 20일 평균 일중고저폭: 최근 공식 OHLC에 0-OHLC·무거래 행이 있으면 자료 미제공
- KOSDAQ 업종RS: 현재 KOSPI-only 공식 업종RS 계약에서는 자료 미제공

결측치를 보간하거나 계산식을 완화하지 않는다.

## V8.7.9 데이터품질 증거

GitHub Actions run: `34686320783`

Artifact: `standalone-swing-promotion-gate-v879`
Artifact ID: `10295129036`
SHA256: `c520f51ab28a5d06e9453b53b1b6020215d6983d0bde07495d9e5ccaaaaa8ad3`

검증 결과:

- 미설명 MA 결측 0
- 예상 밖 6M 결측 0
- 미설명 ATR 결측 0
- 양수 OHLC 관계 오류 0
- 기타 비정상 OHLC 0
- ATR 문제행 532건은 0-OHLC·무거래형으로 설명

## V8.7.10 요청시점 현재가 증거

GitHub Actions run: `34718370007`

Artifact: `standalone-swing-request-price-path-v8710`
Artifact ID: `10305686277`
SHA256: `4dd845a83686430496aac4c07bccef29e7574428537efaa39796435c22c006c4`

검증 결과:

- 235종목 요청시점 현재가 조회
- 235/235 성공
- 커버리지 100.00%
- invalid 성공가격 0
- 정적 종가 현재가 대체 0
- 기존 `getRequestTimePrices` 재사용 가능
- 새 가격 Action 불필요

## 요청시점 현재가 계약

기존 통합 Action만 재사용한다.

- Worker: `https://krx-live-price-ksh.diaconos.workers.dev`
- operationId: `getRequestTimePrices`
- 처음 최대 10개
- 실패만 최대 5개
- 남은 실패만 최대 2개
- 최종 실패: `⚪ 현재가 확인 실패`
- official_close는 참고값이며 요청시점 현재가 대체값이 아니다.
- 정적 가격 fallback 금지
- 실제 운영 활성화 시 다시 live 검증한다.

## 계속 미확정인 지표

다음은 별도 승인 계약이 생기기 전까지 null이다.

- 1W 수익률
- YTD 수익률
- 52W 수익률
- RSI
- MACD
- 투자종합점수100
- 실적전망 변화
- 확정 스윙저점 기반 추적손절

## 아직 운영 활성화하지 않는 이유

데이터 계층과 현재가 경로는 preproduction-ready이지만 다음 계약이 아직 없다.

- 최종 독립 스윙표 헤더
- 독립 스윙 명령어와 route
- 독립 스윙에서 요청현재가를 최종 표시값과 합치는 상세 표시 계약
- 1W/YTD/52W 공식 계산 계약
- RSI/MACD 공식 계산 계약
- 확정 스윙저점 손절 공식 정책
- 100점 투자점수 원자료→점수 임계값
- 실적전망 공식 source
- KOSDAQ 공식 업종RS 계약

따라서 `production_activation_allowed=false`를 유지한다.

## 금지 사항

- 새 명령어 임의 생성 금지
- 최종 헤더 임의 확정 금지
- 새 가격 Action 임의 생성 금지
- KOSDAQ 업종RS 임의 생성 금지
- RSI/MACD 관행 기본값 임의 적용 금지
- 1W/YTD/52W 기준 임의 선택 금지
- 100점 점수 임의 환산 금지
- 실적전망을 과거 성장률로 대체 금지
- MA20을 확정 손절가로 표현 금지
- 요청현재가 실패를 official_close로 대체 금지

## 다음 단계

이 동결 계약 이후에는 계산 source를 다시 흔들지 않고, 별도 단계에서 사용자 확정이 필요한 `최종 헤더·명령어·route·요청가격 표시 결합`만 설계한다.

프로젝트의 다열 레이아웃·최종 한글 용어 정리는 전체 기능 안정화 뒤 마지막 단계에서 처리한다.

## V8.7.11 r1 비활성 가드 정정

초기 V8.7.11 검증은 `docs/custom_gpt_action_schema.yaml`에
`standalone_swing_table_enabled: false`가 직접 존재한다고 잘못 가정했다.

현재 Action 스키마에는 해당 필드가 없다. 독립 스윙 비활성 상태는 다음을 함께 확인한다.

1. `latest/standalone_swing_integrated_latest.json`
   - `standalone_swing_table_enabled=false`
   - `action_route_enabled=false`
2. `docs/custom_gpt_instructions.md`
   - `독립 스윙분석표는 보류`
   - 유효 명령 수 15개 유지

Action 스키마는 `getRequestTimePrices`와 10→5→2 요청시점 현재가 계약 검증에 사용하며,
존재하지 않는 standalone 필드를 스키마에서 요구하지 않는다.

## V8.7.11 r2 구조 검증 정정

r1은 운영지침의 자연어 문장을 특정 문자열로 비교해 `INSTRUCTIONS_15_COMMAND_CONTRACT_MISSING` 오탐이 발생했다.

r2부터 명령 수와 독립 스윙 비활성 상태는 자연어 문구가 아니라 `api/manifest.json` 구조값을 검증한다.

검증 필드:

- `command_route_contract.command_count = 13`
- `command_route_contract.ready_count = 13`
- `command_route_contract.action_domain_count = 1`
- `command_route_contract.single_action_domain = https://krx-live-price-ksh.diaconos.workers.dev`
- `command_route_contract.two_table_release.core_command_count = 13`
- `command_route_contract.two_table_release.additional_command_count = 2`
- `command_route_contract.two_table_release.effective_command_count = 15`
- `command_route_contract.two_table_release.standalone_swing_table_enabled = false`

요청시점 현재가도 같은 manifest의 구조값으로 검증한다.

- `action_operation_id = getRequestTimePrices`
- `initial_batch_size = 10`
- `retry_only_failed = true`
- `retry_rounds = 2`
- `retry_batch_sizes = [5, 2]`
- 최종 실패는 white-circle 표시이며 fake/static price 대체 금지

따라서 prose 표현이나 줄바꿈 변경으로 동결 검증이 실패하지 않는다.

