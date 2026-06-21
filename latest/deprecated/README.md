
# Deprecated KRX status files

이 폴더의 파일은 과거 자동화에서 생성된 기록 보존용 파일입니다.

## 사용 금지 파일

- `krx_latest_retry_status_latest.json`
- `krx_latest_retry_status_latest.txt`

위 파일은 2026년 6월 10일 이전 구조의 구형 상태파일이며,
현재 데이터 최신성 판정에 사용하면 안 됩니다.

## 현재 사용해야 할 파일

1. 기계 판정의 최우선 기준: `../official_data_status_latest.json`
2. 공식 수집 재시도 결과: `../krx_official_retry_status_latest.json`
3. 사람이 읽는 최신성 안내: `../data_freshness_notice_latest.md`
4. 시장·버블 위험 상태: `../data_status_latest.json`
   - 이 파일은 공식 시세 최신성의 최우선 판정 파일이 아닙니다.

자동화와 커스텀 GPT는 이 폴더의 파일을 검색·판정 근거에서 제외해야 합니다.
