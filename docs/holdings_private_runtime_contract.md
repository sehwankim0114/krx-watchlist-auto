# 보유종목표 개인정보 비저장 런타임 계약

`holdings_private_runtime_contract v1.1.0-exact-ticker-filter-v824`

## 목적

보유종목표는 사용자가 현재 대화에서 제공한 보유수량·평균매수가·현금/신용 구분과 공개 시장 참고자료를 결합해 응답 시점에 계산한다.

## 절대 저장하지 않는 정보

- 보유수량
- 평균매수가
- 매입원가
- 평가금액
- 평가손익
- 계좌번호와 증권사 계좌 식별정보
- 신용융자 금액과 담보비율 등 개인 계좌 수치

위 정보는 공개 GitHub 저장소, `latest/`, `api/`, 실행로그, 시험 증빙에 기록하지 않는다.

## 공개 API에 저장 가능한 정보

- 종목코드와 종목명
- 시장 구분
- 공개 현재가·기준일
- 가치매수 참고구간과 목표가 참고값
- 3개월 저가·고가·현재위치 계산용 공개 수치
- 공개 재무·수급·유동성·가격탄력 자료

## 요청 처리 순서

1. 현재 메시지에서 보유 종목코드, 수량, 평균매수가, 현금/신용 구분을 읽는다.
2. `getHoldingsReferenceManifest`를 호출해 개인정보 비저장 정책과 정확 종목 조회 계약을 확인한다.
3. 종목별로 `getStockReferenceShard`를 `prefix`, `ticker`, `market`과 함께 호출한다.
   - `prefix`: 6자리 종목코드의 앞 두 자리
   - `ticker`: 정확한 6자리 종목코드 전체
   - `market`: 확인된 경우 `KOSPI` 또는 `KOSDAQ`
4. `getStockReferenceShard`를 `prefix`만으로 호출하지 않는다.
5. 응답의 `status=OK`, `exact_match=true`, `returned_row_count=1`, `contains_user_holdings=false`를 확인한다.
6. 종목코드와 시장이 정확히 일치하는 공개 참고행 한 개만 사용한다.
7. 동일 종목의 현금과 신용은 합치지 않고 별도 행으로 계산한다.
8. 신용행은 추가 신용매수 금지와 비중축소 기준을 더 엄격하게 적용한다.
9. 계산 결과는 응답에만 표시하고 저장소에는 저장하지 않는다.

## Action 응답 계약

- 단일 Action 도메인: `https://krx-live-price-ksh.diaconos.workers.dev`
- 공개 참고자료 operationId: `getStockReferenceShard`
- 필수 인수: `prefix`, `ticker`
- 선택 인수: `market`
- `prefix` 단독 호출: 금지
- 기대 반환 행 수: 정확히 1행
- 사용자 보유정보 포함 여부: 항상 `false`

## 상태명

경로 등록부에서는 이 방식을 `READY_PRIVATE_RUNTIME`으로 표시한다. 이는 정적 `api/holdings.json`에 개인 보유내역을 저장했다는 뜻이 아니다.
