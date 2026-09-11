# V8.5.7 경량 장기 일봉 원천 캐시 계약

## 목적

`latest/active_stock_long_history_260d_latest.csv`는 현재 활성 한국 주식표 API에 실제 등장하는 종목만 대상으로 최근 260개 공식 KRX 시장 거래일의 원천 일봉을 보관한다.

이 파일은 전체시장 `latest/universe_raw_history_latest.csv`를 52주 이상으로 비대하게 확장하지 않고도 이후 장기 스윙 분석에 필요한 원천 이력을 확보하기 위한 경량 캐시다.

## 대상 종목

대상 종목은 다음 두 범주의 합집합에서 현재 KRX 전체시장 이력에 존재하는 6자리 한국 종목코드만 사용한다.

1. `latest/table_route_registry_latest.json`에 등록된 활성 API 파일
2. `api/two_table_v1/kospi.json`, `decliners.json`, `decliners24.json`

활성 종목 집합이 바뀌면 캐시는 현재 집합 기준으로 다시 정리한다.

## 원천과 스키마

최근 구간은 `latest/universe_raw_history_latest.csv`를 우선 사용하고, 부족한 과거 거래일만 기존 수집기와 동일한 공식 KRX 일별 시세 API에서 보충한다.

캐시 스키마는 기존 `collect_universe.py`의 정규화 형식을 그대로 따른다.

- `date`
- `market`
- `ticker`
- `name`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `trading_value`
- `market_cap`
- `listed_shares`

최근 260개의 서로 다른 KRX 시장 거래일을 유지한다. 신규상장·거래정지 등으로 개별 종목의 실제 행 수가 260개보다 적을 수 있으며, 이 경우 없는 거래일을 임의 생성하지 않는다.

## 안전 규칙

이 캐시는 **원천자료 전용**이다.

- 업종 상대강도(RS)를 계산하지 않는다.
- 확정 스윙저점 기반 추적손절을 계산하지 않는다.
- 독립 스윙 지표를 계산하지 않는다.
- 100점 투자종합점수를 계산하지 않는다.
- 요청시점 현재가로 사용하지 않는다.
- 요청시점 현재가 조회 실패 시 이 캐시의 종가를 대체값으로 사용하지 않는다.
- 기존 현재가 최신성 규칙과 표 추천 규칙을 변경하지 않는다.

따라서 V8.5.7의 READY는 **장기 원천 일봉 캐시가 준비되었다는 뜻**이며, 미완성 투자지표가 계산 가능 또는 승인되었다는 뜻이 아니다.
