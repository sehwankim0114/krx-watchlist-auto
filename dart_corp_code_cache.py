#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
dart_corp_code_cache.py v1.0

목적
- OpenDART corpCode.xml을 다운로드한다.
- DART 고유번호 corp_code와 KRX 종목코드 stock_code를 매칭한다.
- latest/dart_corp_code_cache_latest.csv 파일을 생성한다.
- dart_fx_exposure_kospi.py가 종목코드가 아니라 올바른 corp_code로 공시를 조회할 수 있게 준비한다.

생성 파일
- latest/dart_corp_code_cache_latest.csv
- latest/dart_corp_code_cache_run_log_latest.txt
"""

import argparse
import csv
import io
import os
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    import requests
except Exception as e:
    print(f"IMPORT_ERROR requests: {type(e).__name__}: {e}", file=sys.stderr)
    raise


DART_CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"


def now_kst_text() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%dT%H:%M:%S%z")


def normalize_stock_code(value: str) -> str:
    value = "" if value is None else str(value).strip()
    value = value.replace(".0", "")
    if not value:
        return ""
    if value.isdigit():
        return value.zfill(6)
    return value


def normalize_text(value: str) -> str:
    return "" if value is None else str(value).strip()


def download_corp_code_zip(api_key: str, timeout: int = 30, retry: int = 3, sleep_seconds: float = 1.0) -> bytes:
    last_error = None

    for attempt in range(1, retry + 1):
        try:
            resp = requests.get(
                DART_CORP_CODE_URL,
                params={"crtfc_key": api_key},
                timeout=timeout,
            )

            # OpenDART 오류가 XML/text로 오는 경우가 있어 content-type만 믿지 않는다.
            content = resp.content or b""

            if resp.status_code != 200:
                last_error = f"HTTP_{resp.status_code}"
                time.sleep(sleep_seconds)
                continue

            # 정상은 zip 파일이다.
            if content[:2] == b"PK":
                return content

            text = content.decode("utf-8", errors="replace")[:500]
            last_error = f"NOT_ZIP_RESPONSE:{text}"
            time.sleep(sleep_seconds)

        except Exception as e:
            last_error = f"{type(e).__name__}:{e}"
            time.sleep(sleep_seconds)

    raise RuntimeError(f"DART corpCode.xml download failed after {retry} attempts: {last_error}")


def parse_corp_code_zip(zip_bytes: bytes) -> list[dict]:
    rows = []

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        xml_name = None

        for name in names:
            if name.lower().endswith(".xml"):
                xml_name = name
                break

        if not xml_name:
            raise RuntimeError(f"No XML file in downloaded zip: {names}")

        xml_bytes = zf.read(xml_name)

    root = ET.fromstring(xml_bytes)

    for item in root.findall(".//list"):
        corp_code = normalize_text(item.findtext("corp_code"))
        corp_name = normalize_text(item.findtext("corp_name"))
        stock_code = normalize_stock_code(item.findtext("stock_code"))
        modify_date = normalize_text(item.findtext("modify_date"))

        if not corp_code:
            continue

        rows.append(
            {
                "corp_code": corp_code,
                "corp_name": corp_name,
                "stock_code": stock_code,
                "modify_date": modify_date,
                "has_stock_code": "Y" if stock_code else "N",
            }
        )

    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "corp_code",
        "corp_name",
        "stock_code",
        "modify_date",
        "has_stock_code",
    ]

    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_log(
    path: Path,
    *,
    status: str,
    output_dir: Path,
    total_rows: int,
    listed_rows: int,
    duplicate_stock_codes: int,
    error: str = "",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    text = (
        "script=dart_corp_code_cache.py v1.0\n"
        f"run_at_kst={now_kst_text()}\n"
        f"status={status}\n"
        f"output_dir={output_dir}\n"
        f"total_rows={total_rows}\n"
        f"listed_rows={listed_rows}\n"
        f"duplicate_stock_codes={duplicate_stock_codes}\n"
        f"output=dart_corp_code_cache_latest.csv\n"
        f"error={error}\n"
    )

    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="latest")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--retry", type=int, default=3)
    parser.add_argument("--sleep-seconds", type=float, default=1.0)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_csv = output_dir / "dart_corp_code_cache_latest.csv"
    output_log = output_dir / "dart_corp_code_cache_run_log_latest.txt"

    api_key = os.getenv("DART_API_KEY", "").strip()
    if not api_key:
        write_log(
            output_log,
            status="ERROR_DART_API_KEY_MISSING",
            output_dir=output_dir,
            total_rows=0,
            listed_rows=0,
            duplicate_stock_codes=0,
            error="DART_API_KEY environment variable is missing",
        )
        return 2

    try:
        zip_bytes = download_corp_code_zip(
            api_key,
            timeout=args.timeout,
            retry=args.retry,
            sleep_seconds=args.sleep_seconds,
        )

        rows = parse_corp_code_zip(zip_bytes)

        listed = [r for r in rows if r.get("stock_code")]
        stock_codes = [r["stock_code"] for r in listed]
        duplicate_stock_codes = len(stock_codes) - len(set(stock_codes))

        # 정렬: 상장 종목 우선, 종목코드 순, 회사명 순
        rows.sort(key=lambda r: (r.get("has_stock_code") != "Y", r.get("stock_code", ""), r.get("corp_name", "")))

        write_csv(rows, output_csv)

        status = "OK" if len(listed) >= 2500 else "WARN_LISTED_ROWS_LOW"

        write_log(
            output_log,
            status=status,
            output_dir=output_dir,
            total_rows=len(rows),
            listed_rows=len(listed),
            duplicate_stock_codes=duplicate_stock_codes,
            error="",
        )

        print(f"status={status}")
        print(f"total_rows={len(rows)}")
        print(f"listed_rows={len(listed)}")
        print(f"duplicate_stock_codes={duplicate_stock_codes}")
        print(f"output={output_csv}")

        return 0 if status == "OK" else 1

    except Exception as e:
        write_log(
            output_log,
            status="ERROR",
            output_dir=output_dir,
            total_rows=0,
            listed_rows=0,
            duplicate_stock_codes=0,
            error=f"{type(e).__name__}: {e}",
        )
        print(f"ERROR {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
