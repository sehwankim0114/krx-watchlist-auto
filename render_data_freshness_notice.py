#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
render_data_freshness_notice.py

색상 배지 안내파일 생성기

생성 파일
- latest/data_freshness_notice_latest.md
- latest/data_freshness_notice_latest.txt
- latest/data_freshness_notice_latest.json

색상 방식
- GitHub Markdown에서 안정적으로 보이는 Shields.io 배지를 사용한다.
- CSV/TXT에는 색상을 넣을 수 없으므로 Markdown 안내파일에서 강조한다.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None


SCRIPT_VERSION = "render_data_freshness_notice.py v1.0_color_badge_notice"


def kst_now() -> datetime:
    if ZoneInfo is None:
        return datetime.utcnow() + timedelta(hours=9)
    return datetime.now(ZoneInfo("Asia/Seoul"))


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def badge(label: str, message: str, color: str) -> str:
    label_q = quote(label.replace("-", "—"), safe="")
    message_q = quote(message.replace("-", "—"), safe="")
    return f"![{label} {message}](https://img.shields.io/badge/{label_q}-{message_q}-{color})"


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ["true", "1", "yes", "y"]
    return bool(value)


def build_notice(output_dir: Path, mode: str) -> Dict[str, Any]:
    official = read_json(output_dir / "krx_official_retry_status_latest.json")
    aux = read_json(output_dir / "supplement_current_prices_latest.json")

    fresh = as_bool(official.get("fresh"))
    official_status = str(official.get("status") or "UNKNOWN")
    official_label = str(official.get("display_label") or "")
    warning = str(official.get("warning") or "")

    basis_date = (
        official.get("basis_date_for_display")
        or official.get("actual_min_date")
        or official.get("kospi_actual_date")
        or "확인불가"
    )

    expected_date = official.get("expected_official_trading_date") or "확인불가"
    kospi_date = official.get("kospi_actual_date") or "확인불가"
    kosdaq_date = official.get("kosdaq_actual_date") or "확인불가"
    same_market_date = official.get("same_market_date")
    holiday_possible = official.get("holiday_or_market_closure_possible")

    aux_status = str(aux.get("status") or "UNKNOWN")
    aux_run_at = aux.get("run_at_kst") or "확인불가"
    aux_ok_count = aux.get("ok_count", 0)
    aux_fail_count = aux.get("fail_count", 0)

    if fresh:
        official_badge = badge("KRX 공식판", "최신 공식판", "brightgreen")
        official_color_word = "🟢 최신 공식판"
        official_notice = "fresh=True이므로 공식판을 최신 공식판으로 표시합니다."
    else:
        official_badge = badge("KRX 공식판", "미확정·이전기준", "orange")
        official_color_word = "🟠 KRX 공식자료 미확정/이전 기준일 사용"
        official_notice = "fresh=False이므로 코피표 상단에 경고 문구를 표시해야 합니다."

    aux_badge = badge("보조판", "보조 현재가 참고판", "blue")

    if mode == "aux":
        main_badge = aux_badge
        main_notice = "15:35·18:10 보조판은 공식파일을 덮어쓰지 않고 supplemented 파일만 생성합니다."
    else:
        main_badge = official_badge
        main_notice = official_notice

    return {
        "script": SCRIPT_VERSION,
        "run_at_kst": kst_now().isoformat(timespec="seconds"),
        "mode": mode,
        "main_badge_markdown": main_badge,
        "main_notice": main_notice,
        "official_fresh": fresh,
        "official_status": official_status,
        "official_color_word": official_color_word,
        "official_label": official_label,
        "official_warning": warning,
        "official_basis_date_for_display": basis_date,
        "expected_official_trading_date": expected_date,
        "kospi_actual_date": kospi_date,
        "kosdaq_actual_date": kosdaq_date,
        "same_market_date": same_market_date,
        "holiday_or_market_closure_possible": holiday_possible,
        "aux_badge_markdown": aux_badge,
        "aux_status": aux_status,
        "aux_run_at_kst": aux_run_at,
        "aux_ok_count": aux_ok_count,
        "aux_fail_count": aux_fail_count,
    }


def write_notice_files(output_dir: Path, notice: Dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    md_lines = [
        "# 데이터 최신성 안내",
        "",
        str(notice["main_badge_markdown"]),
        "",
        f"**현재 표시:** {notice['official_color_word']}",
        "",
        "## 공식 KRX 기준",
        "",
        f"- 공식판 fresh: `{notice['official_fresh']}`",
        f"- 공식판 status: `{notice['official_status']}`",
        f"- 표시 기준일: `{notice['official_basis_date_for_display']}`",
        f"- 기대 공식 기준일: `{notice['expected_official_trading_date']}`",
        f"- KOSPI actual date: `{notice['kospi_actual_date']}`",
        f"- KOSDAQ actual date: `{notice['kosdaq_actual_date']}`",
        f"- KOSPI/KOSDAQ 기준일 일치: `{notice['same_market_date']}`",
        f"- 공휴일·휴장일 가능성: `{notice['holiday_or_market_closure_possible']}`",
        "",
        "## 표시 규칙",
        "",
        f"- {badge('표시규칙', 'fresh=True만 최신 공식판', 'brightgreen')} fresh=True일 때만 **최신 공식판**으로 표시합니다.",
        f"- {badge('표시규칙', 'fresh=False 경고', 'orange')} fresh=False이면 **KRX 공식자료 미확정/이전 기준일 사용** 경고를 표시합니다.",
        f"- {badge('표시규칙', '보조판 별도생성', 'blue')} 15:35·18:10 보조판은 공식파일을 덮어쓰지 않고 supplemented 파일만 생성합니다.",
        f"- {badge('표시규칙', 'actual last_date 기준', 'yellow')} 공휴일·휴장일에는 실제 summary 파일의 last_date를 기준일로 표시합니다.",
        "",
        "## 보조 현재가 참고판",
        "",
        str(notice["aux_badge_markdown"]),
        "",
        f"- 보조판 status: `{notice['aux_status']}`",
        f"- 보조판 생성시각: `{notice['aux_run_at_kst']}`",
        f"- 보조 현재가 성공/실패: `{notice['aux_ok_count']}` / `{notice['aux_fail_count']}`",
        "",
        "> 보조 현재가는 공식 KRX 일별매매정보가 아니며, 공식자료를 대체하지 않습니다.",
        "",
    ]

    txt_lines = [
        f"script={notice['script']}",
        f"run_at_kst={notice['run_at_kst']}",
        f"mode={notice['mode']}",
        f"official_fresh={notice['official_fresh']}",
        f"official_status={notice['official_status']}",
        f"official_color_word={notice['official_color_word']}",
        f"official_warning={notice['official_warning']}",
        f"official_basis_date_for_display={notice['official_basis_date_for_display']}",
        f"expected_official_trading_date={notice['expected_official_trading_date']}",
        f"kospi_actual_date={notice['kospi_actual_date']}",
        f"kosdaq_actual_date={notice['kosdaq_actual_date']}",
        f"same_market_date={notice['same_market_date']}",
        f"holiday_or_market_closure_possible={notice['holiday_or_market_closure_possible']}",
        f"aux_status={notice['aux_status']}",
        f"aux_run_at_kst={notice['aux_run_at_kst']}",
        f"aux_ok_count={notice['aux_ok_count']}",
        f"aux_fail_count={notice['aux_fail_count']}",
    ]

    (output_dir / "data_freshness_notice_latest.md").write_text(
        "\n".join(md_lines),
        encoding="utf-8",
    )

    (output_dir / "data_freshness_notice_latest.txt").write_text(
        "\n".join(txt_lines) + "\n",
        encoding="utf-8",
    )

    (output_dir / "data_freshness_notice_latest.json").write_text(
        json.dumps(notice, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="latest")
    parser.add_argument("--mode", default="official", choices=["official", "aux"])
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
