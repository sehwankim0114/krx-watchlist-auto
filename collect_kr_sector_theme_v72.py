#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Collect official Korean listed-company industry/product data from KRX KIND."""

from __future__ import annotations

import argparse
import html
import io
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import requests

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

SOURCE_URL = "https://kind.krx.co.kr/corpgeneral/corpList.do"
SOURCE_PARAMS = {"method": "download", "searchType": "13"}
SOURCE_ID = "KRX_KIND_LISTED_COMPANY"
CACHE_JSON = "krx_sector_theme_latest.json"
CACHE_CSV = "krx_sector_theme_latest.csv"
RUN_LOG = "krx_sector_theme_run_log_latest.txt"
DEFAULT_MIN_ROWS = 1500
MAX_THEME_CHARS = 54


class SectorThemeError(RuntimeError):
    pass


def kst_now() -> datetime:
    if ZoneInfo is None:
        return datetime.utcnow() + timedelta(hours=9)
    return datetime.now(ZoneInfo("Asia/Seoul"))


def iso_kst() -> str:
    return kst_now().isoformat(timespec="seconds")


def clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    text = html.unescape(str(value))
    text = re.sub(r"\s+", " ", text).strip()
    if not text or text.lower() in {"nan", "none", "null", "-"}:
        return None
    return text


def normalize_code(value: Any) -> str:
    text = clean_text(value) or ""
    digits = "".join(re.findall(r"\d", text))
    return digits[-6:].zfill(6) if digits else ""


def flatten_column(value: Any) -> str:
    if isinstance(value, tuple):
        parts = [clean_text(item) for item in value]
        return " ".join(item for item in parts if item)
    return clean_text(value) or ""


def normalize_column(value: Any) -> str:
    return re.sub(r"[\s·ㆍ_/()\-]+", "", flatten_column(value)).lower()


def find_column(columns: Iterable[Any], candidates: Iterable[str]) -> Optional[Any]:
    normalized = {normalize_column(column): column for column in columns}
    for candidate in candidates:
        key = normalize_column(candidate)
        if key in normalized:
            return normalized[key]
    for candidate in candidates:
        key = normalize_column(candidate)
        for normalized_name, original in normalized.items():
            if key and key in normalized_name:
                return original
    return None


def compact_theme(value: Any) -> Optional[str]:
    text = clean_text(value)
    if not text:
        return None
    pieces = [
        re.sub(r"\s+", " ", item).strip()
        for item in re.split(r"[,;/|]+", text)
        if item and item.strip()
    ]
    compact = "·".join(pieces[:3]) if pieces else text
    if len(compact) > MAX_THEME_CHARS:
        compact = compact[: MAX_THEME_CHARS - 1].rstrip() + "…"
    return compact


def decode_candidates(content: bytes, response: requests.Response) -> List[str]:
    values: List[str] = []
    for encoding in (
        response.encoding,
        response.apparent_encoding,
        "cp949",
        "euc-kr",
        "utf-8",
    ):
        if encoding and encoding not in values:
            values.append(encoding)
    decoded: List[str] = []
    for encoding in values:
        try:
            decoded.append(content.decode(encoding))
        except Exception:
            continue
    if not decoded:
        decoded.append(content.decode("utf-8", errors="replace"))
    return decoded


def parse_official_html(content: bytes, response: requests.Response) -> pd.DataFrame:
    errors: List[str] = []
    for text in decode_candidates(content, response):
        try:
            tables = pd.read_html(io.StringIO(text), displayed_only=False)
        except Exception as exc:
            errors.append(str(exc))
            continue

        for table in tables:
            if table.empty:
                continue
            code_col = find_column(table.columns, ("종목코드", "단축코드", "stockcode"))
            sector_col = find_column(table.columns, ("업종", "업종명", "산업"))
            name_col = find_column(table.columns, ("회사명", "법인명", "종목명"))
            product_col = find_column(table.columns, ("주요제품", "주요상품", "제품"))

            if code_col is None or sector_col is None or name_col is None:
                continue

            result = pd.DataFrame(
                {
                    "code": table[code_col].map(normalize_code),
                    "name": table[name_col].map(clean_text),
                    "sector": table[sector_col].map(clean_text),
                    "theme": (
                        table[product_col].map(compact_theme)
                        if product_col is not None
                        else None
                    ),
                }
            )
            result = result[
                result["code"].str.fullmatch(r"\d{6}", na=False)
                & result["sector"].notna()
            ].copy()
            result = result.drop_duplicates("code", keep="first")
            if not result.empty:
                return result

    detail = " | ".join(errors[-3:]) if errors else "matching table not found"
    raise SectorThemeError(f"KRX KIND 표 파싱 실패: {detail}")


def build_rows(frame: pd.DataFrame, generated_at: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in frame.to_dict("records"):
        code = normalize_code(item.get("code"))
        sector = clean_text(item.get("sector"))
        theme = compact_theme(item.get("theme"))
        if not code or not sector:
            continue
        sector_theme = sector if not theme else f"{sector} / {theme}"
        rows.append(
            {
                "code": code,
                "name": clean_text(item.get("name")),
                "sector": sector,
                "theme": theme,
                "sector_theme": sector_theme,
                "source": SOURCE_ID,
                "source_url": f"{SOURCE_URL}?method=download&searchType=13",
                "asof_kst": generated_at,
            }
        )
    rows.sort(key=lambda row: row["code"])
    return rows


def write_cache(output_dir: Path, rows: List[Dict[str, Any]], generated_at: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "status": "OK",
        "source": SOURCE_ID,
        "source_url": f"{SOURCE_URL}?method=download&searchType=13",
        "generated_at_kst": generated_at,
        "row_count": len(rows),
        "rows": rows,
    }
    (output_dir / CACHE_JSON).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    pd.DataFrame(rows).to_csv(
        output_dir / CACHE_CSV,
        index=False,
        encoding="utf-8-sig",
    )


def load_cache(output_dir: Path, min_rows: int) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    path = output_dir / CACHE_JSON
    if not path.exists():
        raise SectorThemeError(f"섹터 캐시 없음: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows")
    if not isinstance(rows, list) or len(rows) < min_rows:
        raise SectorThemeError(
            f"섹터 캐시 행 수 부족: {len(rows) if isinstance(rows, list) else 0}"
        )
    return rows, payload


def fetch_official(timeout: int = 45) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    generated_at = iso_kst()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/149 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,*/*",
        "Referer": "https://kind.krx.co.kr/corpgeneral/corpList.do?method=loadInitPage",
    }
    response = requests.get(
        SOURCE_URL,
        params=SOURCE_PARAMS,
        headers=headers,
        timeout=(10, timeout),
    )
    response.raise_for_status()
    frame = parse_official_html(response.content, response)
    rows = build_rows(frame, generated_at)
    meta = {
        "status": "OK",
        "source": SOURCE_ID,
        "source_url": response.url,
        "generated_at_kst": generated_at,
        "row_count": len(rows),
        "http_status": response.status_code,
    }
    return rows, meta


def collect_or_load(
    output_dir: Path,
    min_rows: int = DEFAULT_MIN_ROWS,
    refresh: bool = True,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    log_lines = [f"started_at_kst={iso_kst()}"]

    if refresh:
        try:
            rows, meta = fetch_official()
            if len(rows) < min_rows:
                raise SectorThemeError(
                    f"공식 목록 행 수 부족: {len(rows)} < {min_rows}"
                )
            write_cache(output_dir, rows, str(meta["generated_at_kst"]))
            meta["cache_mode"] = "LIVE_REFRESH"
            log_lines += [
                "status=OK",
                "cache_mode=LIVE_REFRESH",
                f"row_count={len(rows)}",
                f"source_url={meta.get('source_url')}",
            ]
        except Exception as exc:
            log_lines.append(f"live_refresh_error={type(exc).__name__}:{exc}")
            rows, cached_meta = load_cache(output_dir, min_rows)
            meta = dict(cached_meta)
            meta["cache_mode"] = "STALE_CACHE_FALLBACK"
            meta["live_refresh_error"] = f"{type(exc).__name__}: {exc}"
            log_lines += [
                "status=OK_WITH_CACHE",
                "cache_mode=STALE_CACHE_FALLBACK",
                f"row_count={len(rows)}",
            ]
    else:
        rows, meta = load_cache(output_dir, min_rows)
        meta = dict(meta)
        meta["cache_mode"] = "CACHE_ONLY"
        log_lines += [
            "status=OK",
            "cache_mode=CACHE_ONLY",
            f"row_count={len(rows)}",
        ]

    mapping = {
        normalize_code(row.get("code")): dict(row)
        for row in rows
        if normalize_code(row.get("code"))
    }
    (output_dir / RUN_LOG).write_text(
        "\n".join(log_lines) + "\n",
        encoding="utf-8",
    )
    return mapping, meta


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="latest")
    parser.add_argument("--min-rows", type=int, default=DEFAULT_MIN_ROWS)
    parser.add_argument("--cache-only", action="store_true")
    args = parser.parse_args()

    mapping, meta = collect_or_load(
        Path(args.output_dir),
        min_rows=args.min_rows,
        refresh=not args.cache_only,
    )
    print("KRX_SECTOR_THEME_V72=OK")
    print(f"ROW_COUNT={len(mapping)}")
    print(f"CACHE_MODE={meta.get('cache_mode')}")
    print(f"SOURCE={meta.get('source')}")
    print(f"GENERATED_AT_KST={meta.get('generated_at_kst')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
