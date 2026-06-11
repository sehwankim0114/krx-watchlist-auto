# 데이터 최신성 안내

![KRX 공식판 미확정·이전기준](https://img.shields.io/badge/KRX%20%EA%B3%B5%EC%8B%9D%ED%8C%90-%EB%AF%B8%ED%99%95%EC%A0%95%C2%B7%EC%9D%B4%EC%A0%84%EA%B8%B0%EC%A4%80-orange)

**현재 표시:** 🟠 KRX 공식자료 미확정/이전 기준일 사용

## 공식 KRX 기준

- 공식판 fresh: `False`
- 공식판 status: `STALE_KRX_EMPTY_OR_DELAY`
- 표시 기준일: `2026-06-10`
- 기대 공식 기준일: `2026-06-11`
- KOSPI actual date: `2026-06-10`
- KOSDAQ actual date: `2026-06-10`
- KOSPI/KOSDAQ 기준일 일치: `True`
- 공휴일·휴장일 가능성: `True`

## 표시 규칙

- ![표시규칙 fresh=True만 최신 공식판](https://img.shields.io/badge/%ED%91%9C%EC%8B%9C%EA%B7%9C%EC%B9%99-fresh%3DTrue%EB%A7%8C%20%EC%B5%9C%EC%8B%A0%20%EA%B3%B5%EC%8B%9D%ED%8C%90-brightgreen) fresh=True일 때만 **최신 공식판**으로 표시합니다.
- ![표시규칙 fresh=False 경고](https://img.shields.io/badge/%ED%91%9C%EC%8B%9C%EA%B7%9C%EC%B9%99-fresh%3DFalse%20%EA%B2%BD%EA%B3%A0-orange) fresh=False이면 **KRX 공식자료 미확정/이전 기준일 사용** 경고를 표시합니다.
- ![표시규칙 보조판 별도생성](https://img.shields.io/badge/%ED%91%9C%EC%8B%9C%EA%B7%9C%EC%B9%99-%EB%B3%B4%EC%A1%B0%ED%8C%90%20%EB%B3%84%EB%8F%84%EC%83%9D%EC%84%B1-blue) 15:35·18:10 보조판은 공식파일을 덮어쓰지 않고 supplemented 파일만 생성합니다.
- ![표시규칙 actual last_date 기준](https://img.shields.io/badge/%ED%91%9C%EC%8B%9C%EA%B7%9C%EC%B9%99-actual%20last_date%20%EA%B8%B0%EC%A4%80-yellow) 공휴일·휴장일에는 실제 summary 파일의 last_date를 기준일로 표시합니다.

## 보조 현재가 참고판

![보조판 보조 현재가 참고판](https://img.shields.io/badge/%EB%B3%B4%EC%A1%B0%ED%8C%90-%EB%B3%B4%EC%A1%B0%20%ED%98%84%EC%9E%AC%EA%B0%80%20%EC%B0%B8%EA%B3%A0%ED%8C%90-blue)

- 보조판 status: `OK`
- 보조판 생성시각: `2026-06-12T04:14:28+09:00`
- 보조 현재가 성공/실패: `94` / `0`

> 보조 현재가는 공식 KRX 일별매매정보가 아니며, 공식자료를 대체하지 않습니다.
