# 주식분석표 자동화 프로젝트 대화 이력과 남은 작업

최종 검토: 2026-10-18 KST. 아래 순서는 공유 대화의 첫 메시지 시각 기준이다. 동일한 공유 링크 1개는 중복 제거하여 27개 대화를 정리했다.

공유 페이지의 대화 텍스트를 검토했다. 일부 플러그인 실행 결과는 공유 페이지에서 가려져 있고 대화에서 참조한 첨부파일 원문은 공유되지 않았다. 이력상의 완료 주장은 현재 GitHub 파일·Actions·Worker 상태로 따로 검증해야 한다.

## 대화 순서

| 시작일(UTC) | 공유 대화 | 확인한 핵심 |
|---|---|---|
| 2026-06-13 | [#16 0모든표항목 업뎃 및 보완](https://chatgpt.com/share/6ad33658-2bd0-83ee-bda6-42feb232720c) | 국내 표 기본 항목과 초보자 설명 요구 |
| 2026-06-15 | [#18 1기업표형식,규칙,항목업뎃용](https://chatgpt.com/share/6ad33699-5d5c-83e8-8a1e-51f6e84cd35d) | 기업표 형식과 항목 규칙 |
| 2026-06-16 | [#19 S&P500 자동분석기](https://chatgpt.com/share/6ad336a7-a734-83ee-8f50-635ed83f22c6) | 미국 관심종목 표 요구 |
| 2026-06-16 | [#20 github&커스텀 규칙업뎃용](https://chatgpt.com/share/6ad336dc-c200-83ec-b71c-aea0e762932b) | GitHub 원천과 Custom GPT 규칙 연결 |
| 2026-06-16 | [#17 2표 규칙과 업데이트](https://chatgpt.com/share/6ad3366d-bd94-83ee-9594-0aca0eeb489d) | 표별 규칙과 출력 구조 |
| 2026-06-20 | [#15 E3GitHub자동업뎃,설명,규칙최대](https://chatgpt.com/share/6ad33637-f32c-83ec-b7bc-7b8928486c7e) | 설명서는 요청 시 제공; 표 자동화와 규칙 확장 |
| 2026-07-01 | [#14 4GitHub자동화창이어대규모업](https://chatgpt.com/share/6ad3361c-a6dc-83ee-bd23-56047f50d2df) | GitHub 자동화와 미국 표 경로 |
| 2026-07-03 | [#13 4-1GitHub 오류 해결](https://chatgpt.com/share/6ad335f8-064c-83ec-8970-c40a22bae6ca) | 공식 상태·신선도 동기화와 요청 시점 시세 |
| 2026-07-14 | [#10 4-2GitHub 오류 해결](https://chatgpt.com/share/6ad3354f-3c48-83ee-8c6f-2738354225bb) | 단일 Worker 도메인·Action 응답 경량화·V8.5.3 15명령 |
| 2026-08-07 | [#22 코피표 최신 개선형](https://chatgpt.com/share/6ad33707-eca4-83ec-ad9e-83e19dfd846d) | 코피표 출력 개선 |
| 2026-08-10 | [#21 종목 분석 및 수급위험](https://chatgpt.com/share/6ad33701-de34-83e8-a1e8-aa1b1c67abff) | 수급·위험 표기 보완 |
| 2026-08-10 | [#23 종목 분석 및 추세](https://chatgpt.com/share/6ad33733-3934-83ee-ae70-f56a8b09f9c2) | 스윙 추세 분석 |
| 2026-08-11 | [#24 코피 하락반등표 분석](https://chatgpt.com/share/6ad33755-05dc-83ec-a10d-1ce444b4c5dc) | 하락·반등 후보 분석 |
| 2026-08-12 | [#25 하락 반등후보 선별](https://chatgpt.com/share/6ad3376e-85a0-83ee-8409-39e2dbe9066b) | 후보 선별; 예약 반등 알림 삭제 요청 |
| 2026-08-13 | [#26 코스피 연속하락표 생성](https://chatgpt.com/share/6ad3377b-6644-83ee-bb3e-fa251e71c93b) | 연속하락 표 요구 |
| 2026-08-18 | [#27 연속하락&코피표 양식교정](https://chatgpt.com/share/6ad337b0-73a8-83ee-9931-43a6b7fd09b8) | 2칸 출력과 매수가격 제거 |
| 2026-08-27 | [#12 연속하락표 제공](https://chatgpt.com/share/6ad33599-4d10-83ec-8e84-556382708f88) | 연속하락 표 실제 제공 |
| 2026-08-31 | [#11 종목 스윙 추세 분석](https://chatgpt.com/share/6ad3358b-07dc-83ee-99cf-aa770a05505e) | 스윙 추세 설명 |
| 2026-09-04 | [#7 4-3GitHub 오류 해결](https://chatgpt.com/share/6ad33442-9bb4-83e8-917f-66d5c25a825d) | Custom GPT 2칸 형식; 4칸·영문 코드 한글화는 후순위 |
| 2026-09-09 | [#9 주식표 규칙 적용](https://chatgpt.com/share/6ad33529-56bc-83e8-9bd5-3f023e6b806f) | 15명령, 호가 재시도 10→5→2초, 신선도 실패 시 중단 |
| 2026-09-10 | [#8 주식표 설명서](https://chatgpt.com/share/6ad33519-da08-83ee-b755-60cbccc08514) | 8개 항목 설명서와 명령 시 제공 |
| 2026-09-10 | [#6 4-4GitHub 오류 해결](https://chatgpt.com/share/6ad33426-4a18-83ec-8c54-d7ca76f48cb0) | V8.7 공식 KRX 업종 RS |
| 2026-09-11 | [#5 4-4-1cloud flare업뎃](https://chatgpt.com/share/6ad33401-2118-83e8-bd59-4bcae9067155) | Cloudflare·GPT 계약 동기화 |
| 2026-09-15 | [#3 4-5GitHub 오류 해결](https://chatgpt.com/share/6ad333c5-3934-83e8-b160-980c10eb8a2c) | 100점 점수 원천과 검증 보강 |
| 2026-09-15 | [#4 4-4-2cloud flare업뎃](https://chatgpt.com/share/6ad333e6-5100-83ec-b157-5b69f8e26f3f) | V8.7 Worker·GPT; 코피표 E2E 통과, 연속하락표 표시 재시험 필요 |
| 2026-09-21 | [#2 4-6GitHub 오류 해결](https://chatgpt.com/share/6ad3339f-f680-83ec-893c-8c9c29424109) | 100점 점수 원천 추가·재검증 |
| 2026-09-22 | [#1 4-7GitHub 오류해결](https://chatgpt.com/share/6ad2a933-6c20-83e8-9db9-5065b577384e) | V8.19.8A 점수 시험과 007700 일회성 원천 보강 |

## 결정된 사용 규칙

- GitHub에서 생성한 API와 규칙을 정본으로 사용한다. Custom GPT는 현재 API 상태·신선도·표 데이터를 확인하고 표시한다.
- 표는 현재 2칸 형식을 유지한다. 설명서는 요청 명령에만 제공한다. 매수가격 항목은 제거되었다.
- 15개 명령 경로, 요청 시점 호가 확인, 재시도 10→5→2초, 신선도 실패 시 표 중단을 지킨다. 값이 없으면 과거 가격·확률·점수·전망·손절가를 추측하지 않는다.
- 취소된 예약 반등 알림은 재생성하지 않는다. 4칸 재설계와 영문 스윙 코드 한글화는 사용자가 다른 개선 뒤로 미뤘다.
- 100점 점수는 V8.8.0 승인 계약의 독립 지표이며 옛 점수를 100점으로 환산하지 않는다. 원천 결측 종목의 총점은 null이다.

## 2026-10-18 현재 검증해야 할 완료 조건

1. **데이터 배포:** GitHub API 빌드·동기화·건강검사와 Worker의 동일 빌드 ID·규칙 SHA·15열 표를 매일 검증한다. V8.7 KRX 업종 RS는 현재 배포 경로에 연결되어 있다.
2. **100점 점수:** 과거 V8.19.8A 시험은 2026-09-24 시점 198종목 중 READY 23, LIMITED 175였다. 현행 API의 유니버스와 원천 시점이 바뀌었으므로 이 숫자를 현재 상태로 사용하지 않는다. `audit_current_score_readiness.py`가 현행 표를 다시 시험 계산하여 `latest/investment_score_current_readiness_latest.json`에 준비 상태만 기록한다. 원천 날짜 일치, READY/LIMITED, 점수 분포, 업종 편향, 기존 등급 충돌, GPT 화면 E2E를 확인하기 전에는 production 점수를 내보내지 않는다.
3. **실적전망 변화:** 검증된 전망 원천과 비교 기간·결측 규칙이 아직 production에 연결되지 않았다. 출처가 마련될 때까지 null 유지.
4. **확정 스윙 저점 손절가:** 별도 정책은 `FROZEN_POLICY_ONLY`이고 손절가가 null이다. MA20 참조선과 확정 손절가를 혼동하지 않는다.
5. **Custom GPT 화면:** 2026-09-16 `코피표`의 30행 화면 확인은 통과했다. 이전 `연속하락표` 확인에서는 거래활발·탄력·가격구간의 표현이 계약과 달랐다. 이후 지침은 바뀌었지만 `연속하락표`와 `2.4연속하락표`의 최종 화면 재시험 증거가 없다. GPT 편집기 지침·Action 스키마 설치 상태와 화면 출력은 계정에서 확인해야 한다.
6. **007700 일회성 보강:** 당시 F&F홀딩스 원천 보강 실행은 현재 표 유니버스와 맞는지 먼저 검사한다. 종료된 일회성 재실행 경로를 무작정 되살리지 않는다.

## 실행 순서

현행 API 기준 점수 준비도 자동 감사 → 결측 원천과 날짜 동기화 → 점수 분포·업종 편향 및 등급 충돌 검증 → 별도 production 활성화 → 전망·손절 원천 계약 확정 → Custom GPT 실제 화면 E2E → 보류된 표현 정리와 워크플로 정리.

이 문서는 이력과 작업 상태를 기록한다. 상태의 최종 판정은 각 시점의 GitHub Actions·API·Worker·Custom GPT 화면 검사에 따른다.

## 2026-10-18 10:51 KST 실행 검증

- [PR #15](https://github.com/sehwankim0114/krx-watchlist-auto/pull/15): 현행 표 유니버스의 100점 점수 준비도 자동 감사와 27개 공유 대화의 시간순 기록.
- [PR #16](https://github.com/sehwankim0114/krx-watchlist-auto/pull/16): 공식 260거래일 캐시에서 현재 기준일의 20거래일 가격탄력을 재계산. 56종목 모두 2026-10-16 기준 원천 준비.
- [PR #17](https://github.com/sehwankim0114/krx-watchlist-auto/pull/17): 밸류에이션 가격 입력 날짜를 점수 감사에 추가.
- [PR #18](https://github.com/sehwankim0114/krx-watchlist-auto/pull/18), [#19](https://github.com/sehwankim0114/krx-watchlist-auto/pull/19): 캐시 재사용 시 재무 보고서 원문은 유지하고 시가총액·주식수·PER·PBR·가격 기준일만 현재 공식 KRX 데이터로 재계산. 공식 수집 회귀 검사 2건 통과.
- [PR #20](https://github.com/sehwankim0114/krx-watchlist-auto/pull/20), [#21](https://github.com/sehwankim0114/krx-watchlist-auto/pull/21): 공식 수집과 API 쓰기 작업을 직렬화하고, 대기한 API 빌드는 시작 시 최신 main을 읽도록 수정. 적자 기업의 계약상 PER null 예외를 점수 감사에 반영.
- [최종 API 빌드](https://github.com/sehwankim0114/krx-watchlist-auto/actions/runs/39087856941), [공식 수집](https://github.com/sehwankim0114/krx-watchlist-auto/actions/runs/39080034683), [통합 건강검사](https://github.com/sehwankim0114/krx-watchlist-auto/actions/runs/39087969042) 모두 성공. 건강 보고서는 PASS, critical 0, warning 0.
- [점수 준비도](https://github.com/sehwankim0114/krx-watchlist-auto/blob/main/latest/investment_score_current_readiness_latest.json): 빌드 `20261018T105009+0900-404b13f580`, 기준일 2026-10-16, 유니버스 56종목, 입력 완비 8, LIMITED 48. 입력 완비 8개 모두 가격탄력 및 밸류에이션 날짜가 현재 기준일과 일치한다. 이 수치는 시험 계산이며 production 점수 공개 승인이 아니다.
- [Cloudflare Worker](https://krx-live-price-ksh.diaconos.workers.dev/tables/v1/kospi?page=1)의 `kospi` 30행, `decliners` 27행, `decliners24` 1행은 모두 READY/PRODUCTION, 15열, 동일 빌드 ID와 규칙 SHA를 반환했다.

### 다음 결측 해소 순서

1. 현행 56종목 기준 영업현금흐름 결측 34건의 공식 OpenDART 계정·법인 식별을 재검증한다. 기존 2026-09-24 OCF 캐시는 과거 유니버스 156종목용이므로 그대로 현행 전체로 간주하지 않는다.
2. EV/EBITDA의 정확한 감가상각·상각비 원천 결측 29건과 수급 근거 제한 14건을 각각 공식 원천 및 충돌 검사로 보완한다. 임의 값 대체는 금지한다.
3. 나머지 재무·3년 성장·분기 가속 결측을 검증한 뒤 READY/LIMITED 분포, 점수 극단치, 업종 편향, 기존 등급과의 충돌을 재감사한다.
4. 검증된 원천과 GPT 실제 화면 확인 후에만 별도 production 점수 활성화를 검토한다. 실적전망 변화와 확정 손절가도 각각 원천·날짜·결측 계약이 성립하기 전까지 null로 둔다.
5. 계정의 Custom GPT 편집기에는 현재 도구로 접근할 수 없으므로 `연속하락표`·`2.4연속하락표`의 실제 화면 E2E는 아직 미완료다.

## 2026-10-18 13:43 KST 추가 검증

- [PR #22](https://github.com/sehwankim0114/krx-watchlist-auto/pull/22), [#23](https://github.com/sehwankim0114/krx-watchlist-auto/pull/23): 현행 유니버스와 2025년 연차보고서의 법인·CFS/OFS 범위가 일치하는 정확한 영업현금흐름 32건을 검증하고 source 캐시에 승격했다. READY 8→10, 영업현금흐름 결측 34→5. 매주 원천 재검증을 예약했다.
- [PR #24](https://github.com/sehwankim0114/krx-watchlist-auto/pull/24): 연차보고서 연도가 바뀌면 기존 OCF를 조용히 재사용하지 않도록 현행 점수 감사와 주간 원천 워크플로에 차단 검사를 추가했다. 현재 불일치 0건.
- [PR #25](https://github.com/sehwankim0114/krx-watchlist-auto/pull/25): 과거 공식 XBRL에서 검증된 정확한 감가상각·상각비 2025년 원천을 현재 연도·CFS/OFS가 일치하는 5종목의 점수 감사용 임시 원천에만 연결했다. 4종목이 새로 READY가 됐다. 기존 READY 점수·비대상 종목 변화를 차단한다. production source 캐시와 API 점수는 수정하지 않았다.
- [최신 API 빌드](https://github.com/sehwankim0114/krx-watchlist-auto/actions/runs/39097965397), [통합 건강검사](https://github.com/sehwankim0114/krx-watchlist-auto/actions/runs/39098067792) 성공. 빌드 ID `20261018T134215+0900-775ebe52be`, 기준일 2026-10-16, 건강 PASS·critical 0·warning 0. Cloudflare Worker의 `kospi` 30행, `decliners` 27행, `decliners24` 1행도 같은 빌드 ID·규칙 SHA·READY 상태를 반환했다.
- [현행 점수 준비도](https://github.com/sehwankim0114/krx-watchlist-auto/blob/main/latest/investment_score_current_readiness_latest.json): 56종목 중 READY 14, LIMITED 42. 남은 최상위 결측은 정확한 EV/EBITDA D&A 25건, 수급 근거 LIMITED 14건, 전년 영업이익이 0 이하인 분기 가속 9건이다. 이 수치는 production 점수 공개가 아닌 시험 계산이다.

### 현재 남은 게이트

1. 남은 정확한 D&A 25건 및 수급 14건은 검증 가능한 공식 원천·기간 계약으로만 복구한다. 과거 조사에서 원천 부재로 판정한 종목과 새 유니버스를 구분하고, 결측을 0으로 대체하지 않는다.
2. 재무·성장·가속 결측과 업종 편향, 점수 분포, 기존 등급 충돌을 재검증한 다음 별도 production 점수 활성화를 검토한다. 현행 42개 LIMITED 종목의 총점은 null을 유지한다.
3. 실적전망 변화와 확정 손절가는 유효한 원천·계산 계약이 아직 없어 null이다. Custom GPT 계정 편집기 설치 상태와 `연속하락표`·`2.4연속하락표` 실제 화면은 현재 접근 권한으로 확인할 수 없어 최종 E2E 미완료다.
