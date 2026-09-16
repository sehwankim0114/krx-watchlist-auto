#!/usr/bin/env python3
from __future__ import annotations

import sys
from typing import Any, Dict, List, Mapping, Sequence

import investment_score_source_enricher_v854 as base

PATCH_VERSION = "2026-09-16-v8.11.5-temp-narrow-cis-interest-revenue"
AUDITED_TICKERS = {
    "000810",
    "005830",
    "029780",
    "105560",
    "138930",
}
EXACT_STATEMENT = "CIS"
EXACT_ACCOUNT_ID = "ifrs-full_RevenueFromInterest"

_original_query_multi_period = base.query_multi_period
_original_choose_account = base.choose_account


def _exact_cis_interest_hits(rows: Sequence[Mapping[str, Any]]):
    return [
        row
        for row in rows
        if base.norm_text(row.get("sj_div")) == EXACT_STATEMENT
        and base.norm_text(row.get("account_id")) == EXACT_ACCOUNT_ID
    ]


def patched_query_multi_period(
    client,
    targets: Sequence[Mapping[str, str]],
    year: int,
    report_code: str,
):
    result = _original_query_multi_period(
        client,
        targets,
        year,
        report_code,
    )

    for target in targets:
        code = base.clean_ticker(target.get("ticker"))
        if code not in AUDITED_TICKERS:
            continue

        corp_code = base.clean_corp_code(target.get("corp_code"))
        fs_div = base.norm_text(target.get("preferred_fs_div")) or "CFS"
        if not corp_code:
            continue

        payload = client.get_json(
            base.FULL_ACCOUNT_URL,
            {
                "corp_code": corp_code,
                "bsns_year": str(year),
                "reprt_code": report_code,
                "fs_div": fs_div,
            },
            f"v8115-full-revenue:{code}:{year}:{report_code}:{fs_div}",
        )
        status = base.norm_text(payload.get("status"))
        rows = payload.get("list")
        if status != "000" or not isinstance(rows, list):
            print(
                f"V8115_EXACT_REVENUE_FETCH={code}:{year}:"
                f"{report_code}:{fs_div}:STATUS_{status or 'EMPTY'}"
            )
            continue

        hits = _exact_cis_interest_hits(rows)
        if len(hits) != 1:
            print(
                f"V8115_EXACT_REVENUE_FETCH={code}:{year}:"
                f"{report_code}:{fs_div}:HITS_{len(hits)}"
            )
            continue

        corp_map = result.setdefault(corp_code, {})
        selected_rows = corp_map.setdefault(fs_div, [])

        preexisting = _exact_cis_interest_hits(selected_rows)
        if len(preexisting) > 1:
            raise RuntimeError(
                f"V8115_PREEXISTING_EXACT_ID_AMBIGUOUS:"
                f"{code}:{year}:{report_code}:{len(preexisting)}"
            )
        if not preexisting:
            selected_rows.append(dict(hits[0]))

        print(
            f"V8115_EXACT_REVENUE_FETCH={code}:{year}:"
            f"{report_code}:{fs_div}:UNIQUE_1"
        )

    return result


def patched_choose_account(
    rows: Sequence[Mapping[str, Any]],
    spec: Mapping[str, Any],
):
    # Only revenue selection receives the narrow audited extension.
    if spec is base.ACCOUNT_SPECS["revenue"]:
        hits = _exact_cis_interest_hits(rows)
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            return None

    return _original_choose_account(rows, spec)


base.query_multi_period = patched_query_multi_period
base.choose_account = patched_choose_account


if __name__ == "__main__":
    raise SystemExit(base.main())
