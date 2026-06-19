#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
render_data_freshness_notice.py

KRX 공식자료 상태와 보조 현재가 상태를 읽어 최신성 안내파일을 생성한다.

핵심 원칙
- 공식 상태의 단일 기준파일은 latest/official_data_status_latest.json이다.
- 단일 기준파일이 없으면 krx_official_retry_status_latest.json을 사용한다.
- data_freshness_notice_latest.json/txt의 공식 상태 필드는 기준파일과 동일하게 유지한다.
- aux 실행에서도 공식 상태의 run_at_kst와 기준일을 임의로 바꾸지 않는다.
- 안내파일 자체 생성시각은 notice_generated_at_kst에 별도로 기록한다.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict
from urllib.parse import quote

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None


SCRIPT_VERSION = "render_data_freshness_notice.py v1.1_single_status_source"


def kst_now() -> datetime:
    if ZoneInfo is None:
        return datetime.utcnow() + timedelta(hours=9)
    return datetime.now(ZoneInfo("Asia/Seoul"))


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    return value if isinstance(value, dict) else {}


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def badge(label: str, message: str, color: str) -> str:
    label_q = quote(label.replace("-", "—"), safe="")
    message_q = quote(message.replace("-", "—"), safe="")
    return f"![{label} {message}](https://img.shields.io/badge/{label_q}-{message_q}-{color})"


def load_official_status(output_dir: Path) -> Dict[str, Any]:
    candidates = (
        output_dir / "official_data_status_latest.json",
        output_dir / "krx_official_retry_status_latest.json",
    )

    for path in candidates:
        data = read_json(path)
        if data:
            data = dict(data)
            data["_source_file"] = path.name
            return data

    return {
        "_source_file": "missing",
        "run_at_kst": None,
        "run_mode": "official",
        "final_run_mode": "official",
        "expected_official_trading_date": None,
        "status": "NO_STATUS_FILE",
        "official_status": "NO_STATUS_FILE",
        "fresh": False,
        "official_fresh": False,
        "display_label": "KRX 공식자료 상태 확인 불가",
        "warning": "KRX 공식자료 상태파일 없음",
        "kospi_actual_date": None,
        "kosdaq_actual_date": None,
        "basis_date_for_display": None,
        "same_market_date": False,
    }


def normalize_official_status(official: Dict[str, Any]) -> Dict[str, Any]:
    fresh = as_bool(
        official.get("official_fresh", official.get("fresh", False))
    )
    status = str(
        official.get("official_status")
        or official.get("status")
        or "UNKNOWN"
    )

    run_mode = str(official.get("run_mode") or "official")
    final_run_mode = str(
        official.get("final_run_mode") or run_mode
    )

    basis_date = (
        official.get("basis_date_for_display")
        or official.get("actual_min_date")
        or official.get("kospi_actual_date")
    )

    return {
        "official_status_source": official.get("_source_file", "unknown"),
        "run_at_kst": official.get("run_at_kst"),
        "run_mode": run_mode,
        "final_run_mode": final_run_mode,
        "expected_official_trading_date": official.get(
            "expected_official_trading_date"
        ),
        "status": status,
        "official_status": status,
        "fresh": fresh,
        "official_fresh": fresh,
        "display_label": str(official.get("display_label") or ""),
        "warning": str(official.get("warning") or ""),
        "reason": str(official.get("reason") or ""),
        "kospi_actual_date": official.get("kospi_actual_date"),
        "kosdaq_actual_date": official.get("kosdaq_actual_date"),
        "actual_min_date": official.get("actual_min_date"),
        "actual_max_date": official.get("actual_max_date"),
        "basis_date_for_display": basis_date,
        "same_market_date": as_bool(official.get("same_market_date")),
        "kospi_summary_rows": official.get("kospi_summary_rows", 0),
        "kosdaq_summary_rows": official.get("kosdaq_summary_rows", 0),
        "holiday_file": official.get("holiday_file"),
        "holiday_file_exists": as_bool(
            official.get("holiday_file_exists", False)
        ),
        "collector_return_code": official.get("collector_return_code"),
    }


def build_notice(output_dir: Path, mode: str) -> Dict[str, Any]:
    official_raw = load_official_status(output_dir)
    official = normalize_official_status(official_raw)
    aux = read_json(output_dir / "supplement_current_prices_latest.json")

    if official["official_fresh"]:
        official_badge = badge("KRX 공식판", "최신 공식판", "brightgreen")
        official_color_word = "최신 공식판"
        official_notice = "공식 KRX 자료가 기대 거래일까지 갱신되었습니다."
    else:
        official_badge = badge("KRX 공식판", "미확정·이전기준", "orange")
        official_color_word = "KRX 공식자료 미확정/이전 기준일 사용"
        official_notice = (
            "공식 KRX 자료가 기대 거래일보다 오래되었거나 상태 확인이 필요합니다."
        )

    aux_badge = badge("보조판", "보조 현재가 참고판", "blue")
    main_badge = aux_badge if mode == "aux" else official_badge
    main_notice = (
        "보조 현재가는 공식자료를 덮어쓰지 않으며 참고용으로만 사용합니다."
        if mode == "aux"
        else official_notice
    )

    notice: Dict[str, Any] = {
        "script": SCRIPT_VERSION,
        "notice_generated_at_kst": kst_now().isoformat(timespec="seconds"),
        "mode": mode,
        "main_badge_markdown": main_badge,
        "main_notice": main_notice,
        "official_color_word": official_color_word,
        "official_badge_markdown": official_badge,
        "aux_badge_markdown": aux_badge,
        **official,
        "aux_status": str(aux.get("status") or "UNKNOWN"),
        "aux_run_at_kst": aux.get("run_at_kst"),
        "aux_ok_count": int(aux.get("ok_count") or 0),
        "aux_fail_count": int(aux.get("fail_count") or 0),
    }

    return notice


def notice_to_text(notice: Dict[str, Any]) -> str:
    keys = (
        "script",
        "notice_generated_at_kst",
        "mode",
        "official_status_source",
        "run_at_kst",
        "run_mode",
        "final_run_mode",
        "expected_official_trading_date",
        "status",
        "official_status",
        "fresh",
        "official_fresh",
        "display_label",
        "official_color_word",
        "warning",
        "reason",
        "kospi_actual_date",
        "kosdaq_actual_date",
        "actual_min_date",
        "actual_max_date",
        "basis_date_for_display",
        "same_market_date",
        "kospi_summary_rows",
        "kosdaq_summary_rows",
        "holiday_file",
        "holiday_file_exists",
        "collector_return_code",
        "aux_status",
        "aux_run_at_kst",
        "aux_ok_count",
        "aux_fail_count",
    )
    return "\n".join(f"{key}={notice.get(key)}" for key in keys) + "\n"


def notice_to_markdown(notice: Dict[str, Any]) -> str:
    lines = [
        "# 데이터 최신성 안내",
        "",
        str(notice["main_badge_markdown"]),
        "",
        f"**현재 표시:** {notice['official_color_word']}",
        "",
        "## 공식 KRX 기준",
        "",
        f"- 공식 상태 기준파일: `{notice['official_status_source']}`",
        f"- 공식 실행시각: `{notice['run_at_kst']}`",
        f"- 실행 모드: `{notice['run_mode']}`",
        f"- 최종 실행 모드: `{notice['final_run_mode']}`",
        f"- 공식판 fresh: `{notice['official_fresh']}`",
        f"- 공식판 status: `{notice['official_status']}`",
        f"- 기대 공식 기준일: `{notice['expected_official_trading_date']}`",
        f"- KOSPI actual date: `{notice['kospi_actual_date']}`",
        f"- KOSDAQ actual date: `{notice['kosdaq_actual_date']}`",
        f"- 표시 기준일: `{notice['basis_date_for_display']}`",
        f"- KOSPI/KOSDAQ 기준일 일치: `{notice['same_market_date']}`",
        "",
        "## 보조 현재가 참고판",
        "",
        str(notice["aux_badge_markdown"]),
        "",
        f"- 보조판 status: `{notice['aux_status']}`",
        f"- 보조판 생성시각: `{notice['aux_run_at_kst']}`",
        f"- 성공/실패: `{notice['aux_ok_count']}` / `{notice['aux_fail_count']}`",
        "",
        "> 보조 현재가는 공식 KRX 일별매매정보가 아니며 공식자료를 대체하지 않습니다.",
        "",
    ]
    return "\n".join(lines)


def atomic_write(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def write_notice_files(output_dir: Path, notice: Dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    atomic_write(
        output_dir / "data_freshness_notice_latest.json",
        json.dumps(notice, ensure_ascii=False, indent=2) + "\n",
    )
    atomic_write(
        output_dir / "data_freshness_notice_latest.txt",
        notice_to_text(notice),
    )
    atomic_write(
        output_dir / "data_freshness_notice_latest.md",
        notice_to_markdown(notice),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="latest")
    parser.add_argument(
        "--mode",
        default="official",
        choices=("official", "aux"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    notice = build_notice(output_dir, args.mode)
    write_notice_files(output_dir, notice)
    print(json.dumps(notice, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
