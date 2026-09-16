#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

BASE_PATH = Path("investment_score_source_enricher_v854.py")
CANDIDATE_PATH = Path("staged/investment_score_source_enricher_v8116_candidate.py")
SUMMARY = Path(
    "latest/investment_score_source_contract_candidate_v8116_summary_latest.json"
)

AUDITED = "000810"
NON_AUDITED = "005930"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("MODULE_SPEC_FAILED:" + str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def row(
    sj_div,
    account_id,
    account_nm,
    amount,
    add=None,
    prev=None,
    prev_add=None,
    prev2=None,
):
    return {
        "sj_div": sj_div,
        "account_id": account_id,
        "account_nm": account_nm,
        "thstrm_amount": str(amount),
        "thstrm_add_amount": str(add if add is not None else amount),
        "frmtrm_amount": str(prev if prev is not None else amount - 10),
        "frmtrm_add_amount": str(
            prev_add
            if prev_add is not None
            else (prev if prev is not None else amount - 10)
        ),
        "bfefrmtrm_amount": str(
            prev2 if prev2 is not None else amount - 20
        ),
    }


class FakeClient:
    def __init__(self, full_rows_by_corp):
        self.full_rows_by_corp = full_rows_by_corp
        self.calls = []

    def get_json(self, url, params, label):
        self.calls.append((url, dict(params), label))
        if "fnlttMultiAcnt" in url:
            items = []
            for corp in str(params.get("corp_code", "")).split(","):
                if not corp:
                    continue
                items.append({
                    "corp_code": corp,
                    "fs_div": "CFS",
                    **row(
                        "IS",
                        "ifrs-full_Revenue",
                        "매출액",
                        100,
                        100,
                        90,
                        90,
                        80,
                    ),
                })
            return {"status": "000", "list": items}

        corp = str(params.get("corp_code", ""))
        return {
            "status": "000",
            "list": self.full_rows_by_corp.get(corp, []),
        }


def main():
    base = load_module(BASE_PATH, "base_v854_for_v8116_test")
    cand = load_module(CANDIDATE_PATH, "candidate_v8116_test")

    is_revenue = row(
        "IS",
        "ifrs-full_Revenue",
        "매출액",
        100,
        100,
        90,
        90,
        80,
    )
    cis_interest = row(
        "CIS",
        "ifrs-full_RevenueFromInterest",
        "이자수익",
        200,
        200,
        180,
        180,
        160,
    )
    op = row(
        "IS",
        "ifrs-full_ProfitLossFromOperatingActivities",
        "영업이익",
        30,
        30,
        20,
        20,
        10,
    )

    audited = cand.account_values(
        [is_revenue, cis_interest, op],
        AUDITED,
    )
    assert audited["revenue"]["found"] is True
    assert audited["revenue"]["account_nm"] == "이자수익"
    assert audited["revenue"]["thstrm_amount"] == 200.0

    non_audited = cand.account_values(
        [is_revenue, cis_interest, op],
        NON_AUDITED,
    )
    assert non_audited["revenue"]["found"] is True
    assert non_audited["revenue"]["account_nm"] == "매출액"
    assert non_audited["revenue"]["thstrm_amount"] == 100.0

    duplicate = dict(cis_interest)
    duplicate["account_nm"] = "이자수익_중복"
    dup = cand.account_values(
        [is_revenue, cis_interest, duplicate, op],
        AUDITED,
    )
    assert dup["revenue"]["found"] is False

    fallback = cand.account_values([is_revenue, op], AUDITED)
    base_fallback = base.account_values([is_revenue, op])
    assert fallback["revenue"] == base_fallback["revenue"]

    assert audited["operating_profit"]["account_nm"] == "영업이익"
    assert audited["operating_profit"]["thstrm_amount"] == 30.0

    full_rows = {
        "00000001": [dict(cis_interest)],
        "00000002": [dict(cis_interest)],
    }
    client = FakeClient(full_rows)
    targets = [
        {
            "ticker": AUDITED,
            "corp_code": "00000001",
            "preferred_fs_div": "CFS",
        },
        {
            "ticker": NON_AUDITED,
            "corp_code": "00000002",
            "preferred_fs_div": "CFS",
        },
    ]
    result = cand.query_multi_period(client, targets, 2025, "11011")

    full_calls = [
        call for call in client.calls
        if "fnlttSinglAcntAll" in call[0]
    ]
    assert len(full_calls) == 1
    assert full_calls[0][1]["corp_code"] == "00000001"

    audited_rows = result["00000001"]["CFS"]
    non_audited_rows = result["00000002"]["CFS"]
    assert len(cand.exact_cis_interest_revenue_hits(audited_rows)) == 1
    assert len(cand.exact_cis_interest_revenue_hits(non_audited_rows)) == 0

    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    assert s["status"] == "STAGED_CANDIDATE_ONLY"
    assert s["candidate_contract"]["selection_rule"] == "EXACT_ID_UNIQUE_ONLY"
    assert s["candidate_contract"]["duplicate_exact_hit_policy"] == (
        "FAIL_CLOSED_NO_SELECTION"
    )
    assert s["hard_guards"]["production_source_enricher_modified"] is False

    print("V8116_DETERMINISTIC_CONTRACT_TESTS=PASS")


if __name__ == "__main__":
    main()
