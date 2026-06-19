#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
run_collect_universe_retry.py

기존 collect_universe.py의 분석 기능은 그대로 유지하면서,
KRX OpenAPI가 일시적으로 빈 응답을 보낼 때 같은 날짜와 시장을
총 4회 재시도하는 안전 실행기입니다.
"""

from __future__ import annotations

import time
from typing import List

import pandas as pd
import requests

import collect_universe


SCRIPT_VERSION = "run_collect_universe_retry.py v1.1"
RETRY_DELAYS_SECONDS = (0, 1, 3, 7)
RESPONSE_PREVIEW_LENGTH = 300


def safe_body_preview(text: str) -> str:
    """응답 본문을 로그에 안전하게 남길 수 있도록 정리한다."""
    preview = str(text or "")
    preview = preview.replace("\r", " ").replace("\n", " ")
    preview = " ".join(preview.split())
    return preview[:RESPONSE_PREVIEW_LENGTH]


def retry_request_krx_openapi(
    url: str,
    auth_key: str,
    bas_dd: str,
    log_lines: List[str],
    label: str,
) -> pd.DataFrame:
    """
    KRX OpenAPI를 총 4회 시도한다.

    1차는 즉시 실행하고, 실패하면 1초, 3초, 7초 후 재시도한다.
    """
    total_attempts = len(RETRY_DELAYS_SECONDS)

    for attempt, delay_seconds in enumerate(
        RETRY_DELAYS_SECONDS,
        start=1,
    ):
        if delay_seconds > 0:
            log_lines.append(
                "KRX_RETRY_WAIT "
                f"market={label} "
                f"date={bas_dd} "
                f"attempt={attempt} "
                f"seconds={delay_seconds}"
            )
            time.sleep(delay_seconds)

        try:
            response = requests.get(
                url,
                params={"basDd": bas_dd},
                headers={"AUTH_KEY": auth_key},
                timeout=40,
            )
        except Exception as exc:
            log_lines.append(
                "KRX_RETRY "
                f"market={label} "
                f"date={bas_dd} "
                f"attempt={attempt}/{total_attempts} "
                "status=REQUEST_EXCEPTION "
                "rows=0 "
                f"exception={type(exc).__name__} "
                f"message={safe_body_preview(str(exc))} "
                "result=RETRY"
            )
            continue

        status_code = response.status_code
        body_preview = safe_body_preview(response.text)

        if status_code != 200:
            log_lines.append(
                "KRX_RETRY "
                f"market={label} "
                f"date={bas_dd} "
                f"attempt={attempt}/{total_attempts} "
                f"status={status_code} "
                "rows=0 "
                f"body={body_preview} "
                "result=RETRY"
            )
            continue

        try:
            data = response.json()
        except Exception as exc:
            log_lines.append(
                "KRX_RETRY "
                f"market={label} "
                f"date={bas_dd} "
                f"attempt={attempt}/{total_attempts} "
                f"status={status_code} "
                "rows=0 "
                f"exception={type(exc).__name__} "
                f"body={body_preview} "
                "result=RETRY"
            )
            continue

        if isinstance(data, dict):
            top_keys = list(data.keys())
            rows = data.get("OutBlock_1")
        else:
            top_keys = [type(data).__name__]
            rows = None

        row_count = len(rows) if isinstance(rows, list) else 0

        if row_count > 0:
            log_lines.append(
                "KRX_RETRY "
                f"market={label} "
                f"date={bas_dd} "
                f"attempt={attempt}/{total_attempts} "
                f"status={status_code} "
                f"keys={top_keys} "
                f"rows={row_count} "
                "result=SUCCESS"
            )
            return pd.DataFrame(rows)

        log_lines.append(
            "KRX_RETRY "
            f"market={label} "
            f"date={bas_dd} "
            f"attempt={attempt}/{total_attempts} "
            f"status={status_code} "
            f"keys={top_keys} "
            "rows=0 "
            f"body={body_preview} "
            "result=EMPTY_RETRY"
        )

    log_lines.append(
        "OPENAPI_EMPTY_AFTER_RETRY "
        f"market={label} "
        f"date={bas_dd} "
        f"attempts={total_attempts}"
    )
    return pd.DataFrame()


def main() -> int:
    original_request_function = collect_universe.request_krx_openapi
    collect_universe.request_krx_openapi = retry_request_krx_openapi

    print(
        f"[KRX_RETRY_PATCH] enabled script={SCRIPT_VERSION}",
        flush=True,
    )

    try:
        result = collect_universe.main()
        return int(result or 0)
    finally:
        collect_universe.request_krx_openapi = original_request_function


if __name__ == "__main__":
    raise SystemExit(main())
