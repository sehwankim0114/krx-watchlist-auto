# KRX 관종표 자동 수집 키트

## 목적

이 키트는 관심종목 47개의 최근 3개월 가격·거래량·거래대금·기초 수급 데이터를 자동 수집하여 ChatGPT 관종표 작성에 사용할 CSV/XLSX를 만듭니다.

## 포함 파일

- `watchlist.csv` : 관심종목 47개 목록
- `collect_watchlist.py` : 수집/요약 메인 프로그램
- `requirements.txt` : 필요한 Python 패키지
- `.env.template` : 환경설정 예시
- `install_windows.bat` : Windows 설치용
- `run_collect.bat` : Windows 수동 실행용
- `create_windows_task.ps1` : Windows 작업 스케줄러 등록용
- `.github/workflows/collect-krx-watchlist.yml` : GitHub Actions 자동실행용

## 1. Windows PC에서 쓰는 방법

1. 압축을 `C:\krx_watchlist_auto` 같은 폴더에 풉니다.
2. `install_windows.bat`를 더블클릭합니다.
3. 설치가 끝나면 `run_collect.bat`를 더블클릭합니다.
4. 결과는 `outputs` 폴더에 생성됩니다.

주요 결과 파일:

- `outputs/watchlist_summary_latest.csv`
- `outputs/watchlist_latest.xlsx`
- `outputs/raw_history_latest.csv`
- `outputs/run_log_latest.txt`

## 2. 매일 자동 실행 등록

PowerShell을 관리자 권한으로 열고 아래 명령을 실행합니다.

```powershell
cd C:\krx_watchlist_auto
powershell -ExecutionPolicy Bypass -File .\create_windows_task.ps1
```

등록 후 매주 월~금 오후 4:45에 자동 수집합니다.

## 3. GitHub Actions로 완전 자동화하는 방법

이 방식은 ChatGPT가 웹에서 직접 읽을 수 있는 CSV URL을 만들기 위한 방식입니다.

1. GitHub에서 새 저장소를 만듭니다.
2. 이 키트의 모든 파일을 저장소에 업로드합니다.
3. 저장소는 공개 Public으로 설정합니다.
4. Actions 탭에서 `collect-krx-watchlist` 워크플로를 수동 실행합니다.
5. 실행 후 아래 파일이 생깁니다.

```text
latest/watchlist_summary_latest.csv
latest/raw_history_latest.csv
```

ChatGPT에 아래 형식의 Raw URL을 알려주면 됩니다.

```text
https://raw.githubusercontent.com/깃허브아이디/저장소명/main/latest/watchlist_summary_latest.csv
```

그다음부터는 “관종표 작성 시 이 URL을 먼저 읽어라”라고 설정하면, 매번 파일을 직접 올리지 않아도 됩니다.

## 4. KRX OPEN API 인증키

KRX 공식 OPEN API 인증키를 받으면 `.env`의 `KRX_AUTH_KEY=` 뒤에 넣어두세요. 현재 버전은 pykrx/KRX CSV-OTP/yfinance를 사용하며, KRX OPEN API 개발 명세서의 실제 엔드포인트를 확인한 뒤 공식 API 직접호출 모드로 확장할 수 있습니다.

## 5. 주의사항

- pykrx와 KRX CSV-OTP는 KRX 화면/세션/접속정책 변경에 영향을 받을 수 있습니다.
- GitHub Actions는 해외 서버에서 KRX에 접속하므로 간혹 실패할 수 있습니다.
- 실패하면 `latest/run_log_latest.txt` 또는 `outputs/run_log_latest.txt`를 확인하세요.
- 투자판단은 자동 수집값만으로 하지 말고, DART/KIND/공시/뉴스/실적 검증을 함께 해야 합니다.
