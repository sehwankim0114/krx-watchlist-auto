#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
import subprocess
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_source_enricher_v854 as src

VERSION = "2026-09-21-v8.12.9-current-actionable-exact-da-single-blocker-audit"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
V8128_VERSION = "2026-09-21-v8.12.8-post-apply-current-blocker-reaudit"
V8128_RESULT_COMMIT = "282b37236be05eb7ecbc04356f8c305cc0bcccbe"
V8120_VERSION = "2026-09-17-v8.12.0-current-actionable-exact-da-official-recovery-audit"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

BLOCK_CSV = ROOT / "latest/investment_score_current_blockers_v8128.csv"
BLOCK_JSON = ROOT / "latest/investment_score_current_blockers_v8128_summary_latest.json"
V8120_JSON = ROOT / "latest/investment_score_exact_da_actionable_v8120_summary_latest.json"
FIN = ROOT / "latest/financial_valuation_cache_latest.csv"

OUT_CSV = ROOT / "latest/investment_score_exact_da_actionable_v8129.csv"
OUT_JSON = ROOT / "latest/investment_score_exact_da_actionable_v8129_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_exact_da_actionable_v8129_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_exact_da_actionable_v8129.md"

APPROVED = {
    "ifrs-full_AdjustmentsForDepreciationExpense",
    "ifrs-full_AdjustmentsForAmortisationExpense",
}

EXPECTED_ACTIONABLE = {
    "004370": "농심",
    "021240": "코웨이",
    "047810": "한국항공우주",
    "097950": "CJ제일제당",
    "214320": "이노션",
}


def ticker(value):
    s = "".join(ch for ch in str(value or "") if ch.isdigit())
    return s.zfill(6) if s else ""


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def parse_list(value):
    try:
        data = json.loads(str(value or ""))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def number(value):
    try:
        if value in (None, "", "null", "None"):
            return None
        return float(value)
    except Exception:
        return None


def exact_stats(candidates):
    grouped = defaultdict(list)
    for item in candidates:
        aid = str(item.get("account_id") or "").strip()
        if aid in APPROVED:
            grouped[aid].append(item)

    out = {}
    for aid in sorted(APPROVED):
        rows = grouped.get(aid, [])
        nums = [
            number(r.get("amount"))
            for r in rows
            if number(r.get("amount")) is not None
        ]
        out[aid] = {
            "occurrence_count": len(rows),
            "unique_numeric_values": sorted(set(nums)),
            "account_names": sorted({
                str(r.get("account_nm") or "").strip()
                for r in rows
                if str(r.get("account_nm") or "").strip()
            }),
        }
    return out


def classify(stats):
    present = {
        aid for aid, x in stats.items()
        if x["occurrence_count"] > 0
    }
    unique = {
        aid for aid, x in stats.items()
        if len(x["unique_numeric_values"]) == 1
    }
    conflict = {
        aid for aid, x in stats.items()
        if len(x["unique_numeric_values"]) > 1
    }

    if conflict:
        return "APPROVED_EXACT_VALUE_CONFLICT"
    if present == APPROVED and unique == APPROVED:
        return "BOTH_APPROVED_EXACT_UNIQUE_NUMERIC"
    if present and unique == present:
        return "PARTIAL_APPROVED_EXACT_UNIQUE_NUMERIC"
    if present:
        return "APPROVED_EXACT_PRESENT_NONUNIQUE_OR_NONNUMERIC"
    return "NO_APPROVED_EXACT"


def recovery_lane(classification, deep_status):
    if deep_status != "OK":
        return "OFFICIAL_QUERY_INCOMPLETE"
    if classification == "BOTH_APPROVED_EXACT_UNIQUE_NUMERIC":
        return "RECOVERABLE_BOTH_EXACT_SHADOW_CANDIDATE"
    if classification == "PARTIAL_APPROVED_EXACT_UNIQUE_NUMERIC":
        return "PARTIAL_ONLY_DO_NOT_PROMOTE"
    if classification == "APPROVED_EXACT_VALUE_CONFLICT":
        return "CONFLICT_FAIL_CLOSED"
    if classification == "APPROVED_EXACT_PRESENT_NONUNIQUE_OR_NONNUMERIC":
        return "NONUNIQUE_OR_NONNUMERIC_FAIL_CLOSED"
    return "NO_APPROVED_EXACT_CURRENT_OFFICIAL_PATH"


def main():
    api_key = os.environ.get("DART_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("V8129_DART_API_KEY_MISSING")

    for path in (BLOCK_CSV, BLOCK_JSON, V8120_JSON, FIN):
        if not path.is_file():
            raise RuntimeError("V8129_MISSING_INPUT:" + str(path))

    subprocess.run(
        ["git", "merge-base", "--is-ancestor", V8128_RESULT_COMMIT, "HEAD"],
        check=True,
    )

    s8128 = read_json(BLOCK_JSON)
    if s8128.get("version") != V8128_VERSION:
        raise RuntimeError("V8129_V8128_VERSION_MISMATCH")
    if s8128.get("status") != "AUDIT_ONLY_POST_ELASTICITY_PROMOTION":
        raise RuntimeError("V8129_V8128_STATUS_MISMATCH")
    if s8128.get("policy_version") != POLICY_VERSION:
        raise RuntimeError("V8129_POLICY_VERSION_MISMATCH")
    if s8128.get("next_actionable_source_group") != "EXACT_DA_SOURCE":
        raise RuntimeError("V8129_NEXT_GROUP_NOT_EXACT_DA")
    if int(s8128.get("next_actionable_single_blocker_count") or 0) != 5:
        raise RuntimeError("V8129_ACTIONABLE_COUNT_NOT_5")
    if set(s8128.get("next_actionable_tickers") or []) != set(EXPECTED_ACTIONABLE):
        raise RuntimeError("V8129_ACTIONABLE_SET_MISMATCH")
    if s8128.get("next_step") != "AUDIT_CURRENT_ACTIONABLE_EXACT_DA_SINGLE_BLOCKERS_V8129":
        raise RuntimeError("V8129_PREDECESSOR_NEXT_STEP_MISMATCH")

    exhausted = set(
        ((s8128.get("known_exhausted_evidence") or {}).get(
            "exact_da_exhausted_union_tickers"
        ) or [])
    )
    if len(exhausted) != 27:
        raise RuntimeError(f"V8129_EXHAUSTED_UNION_NOT_27:{len(exhausted)}")
    if set(EXPECTED_ACTIONABLE) & exhausted:
        raise RuntimeError(
            "V8129_ACTIONABLE_OVERLAPS_EXHAUSTED:"
            + ",".join(sorted(set(EXPECTED_ACTIONABLE) & exhausted))
        )

    s8120 = read_json(V8120_JSON)
    if s8120.get("version") != V8120_VERSION:
        raise RuntimeError("V8129_V8120_VERSION_MISMATCH")
    prior_v8120_exhausted = set(s8120.get("no_approved_exact_tickers") or [])
    if len(prior_v8120_exhausted) != 17:
        raise RuntimeError("V8129_V8120_EXHAUSTED_NOT_17")
    if set(EXPECTED_ACTIONABLE) & prior_v8120_exhausted:
        raise RuntimeError("V8129_TARGET_ALREADY_EXHAUSTED_IN_V8120")

    block_rows = read_csv(BLOCK_CSV)
    actionable_rows = {
        ticker(r.get("ticker")): r
        for r in block_rows
        if r.get("source_group") == "EXACT_DA_SOURCE"
        and str(r.get("single_blocker_ticker") or "").upper() == "TRUE"
        and r.get("recovery_status") == "ACTIONABLE_SINGLE_BLOCKER_REAUDIT"
    }
    if set(actionable_rows) != set(EXPECTED_ACTIONABLE):
        raise RuntimeError(
            "V8129_BLOCK_CSV_ACTIONABLE_SET_MISMATCH:"
            + ",".join(sorted(actionable_rows))
        )

    for code, expected_name in EXPECTED_ACTIONABLE.items():
        if actionable_rows[code].get("name") != expected_name:
            raise RuntimeError(
                f"V8129_TARGET_NAME_MISMATCH:{code}:"
                + str(actionable_rows[code].get("name"))
            )
        if actionable_rows[code].get("blocker_reason") not in {
            "EV/EBITDA:EV_EBITDA_INPUT:OK:NO_EXACT_CANDIDATE",
            "EV/EBITDA:EV_EBITDA_INPUT:EMPTY_AS_ZERO:NO_EXACT_CANDIDATE",
        }:
            raise RuntimeError(
                "V8129_UNEXPECTED_EXACT_DA_BLOCKER_REASON:"
                + code + ":" + str(actionable_rows[code].get("blocker_reason"))
            )

    financial_df = src.read_csv(FIN)
    all_targets = src.load_targets(financial_df)
    dominant_year, dominant_code = src.dominant_period(all_targets)
    annual_year = dominant_year - 1
    target_map = {t["ticker"]: t for t in all_targets}

    client = src.OpenDartClient(api_key, timeout=30)

    out_rows = []
    class_counts = Counter()
    lane_counts = Counter()
    recoverable = []
    partial = []
    no_exact = []
    incomplete = []
    conflict = []
    missing_target = []

    for code in sorted(EXPECTED_ACTIONABLE):
        target = target_map.get(code)
        if not target:
            missing_target.append(code)
            continue

        fresh = src.fetch_deep_one(client, target, annual_year)
        candidates = parse_list(fresh.get("da_json"))
        stats = exact_stats(candidates)
        classification = classify(stats)
        lane = recovery_lane(classification, str(fresh.get("status") or ""))

        dep = stats["ifrs-full_AdjustmentsForDepreciationExpense"]
        amo = stats["ifrs-full_AdjustmentsForAmortisationExpense"]

        out_rows.append({
            "ticker": code,
            "name": EXPECTED_ACTIONABLE[code],
            "corp_code": target.get("corp_code") or "",
            "preferred_fs_div": target.get("preferred_fs_div") or "",
            "dominant_financial_period": f"{dominant_year}_{dominant_code}",
            "annual_source_year": annual_year,
            "fresh_deep_status": fresh.get("status") or "",
            "fresh_deep_fs_div": fresh.get("fs_div") or "",
            "fresh_deep_message": fresh.get("message") or "",
            "fresh_exact_classification": classification,
            "recovery_lane": lane,
            "approved_depreciation_occurrences": dep["occurrence_count"],
            "approved_depreciation_values_json": json.dumps(
                dep["unique_numeric_values"],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "approved_amortisation_occurrences": amo["occurrence_count"],
            "approved_amortisation_values_json": json.dumps(
                amo["unique_numeric_values"],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "fresh_exact_stats_json": json.dumps(
                stats,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "fresh_da_candidates_json": json.dumps(
                candidates,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        })

        class_counts[classification] += 1
        lane_counts[lane] += 1
        if lane == "RECOVERABLE_BOTH_EXACT_SHADOW_CANDIDATE":
            recoverable.append(code)
        elif lane == "PARTIAL_ONLY_DO_NOT_PROMOTE":
            partial.append(code)
        elif lane == "NO_APPROVED_EXACT_CURRENT_OFFICIAL_PATH":
            no_exact.append(code)
        elif lane == "OFFICIAL_QUERY_INCOMPLETE":
            incomplete.append(code)
        elif lane in {
            "CONFLICT_FAIL_CLOSED",
            "NONUNIQUE_OR_NONNUMERIC_FAIL_CLOSED",
        }:
            conflict.append(code)

        time.sleep(0.20)

    if missing_target:
        raise RuntimeError(
            "V8129_CURRENT_TARGET_MAPPING_MISSING:" + ",".join(sorted(missing_target))
        )
    if len(out_rows) != 5:
        raise RuntimeError(f"V8129_OUTPUT_COUNT_NOT_5:{len(out_rows)}")
    if incomplete:
        raise RuntimeError(
            "V8129_OFFICIAL_QUERY_INCOMPLETE:" + ",".join(sorted(incomplete))
        )
    if int(client.attempted) != 5 or int(client.successful) != 5:
        raise RuntimeError(
            f"V8129_OPENDART_REQUEST_COUNT_BAD:{client.attempted}:{client.successful}"
        )
    if client.transport_failures or client.dart_status_failures:
        raise RuntimeError("V8129_OPENDART_FAILURE_PRESENT")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    fields = list(out_rows[0].keys())
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(out_rows)

    if partial or conflict:
        next_step = "REVIEW_EXACT_DA_AMBIGUITY_BEFORE_CONTINUING"
    elif recoverable:
        next_step = "FREEZE_RECOVERABLE_EXACT_DA_AND_SHADOW_SCORE_V8130"
    else:
        next_step = "AUDIT_CURRENT_ACTIONABLE_OCF_SINGLE_BLOCKERS_V8130"

    summary = {
        "version": VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "AUDIT_ONLY_CURRENT_ACTIONABLE_EXACT_DA",
        "policy_version": POLICY_VERSION,
        "v8128_version": V8128_VERSION,
        "v8128_result_commit": V8128_RESULT_COMMIT,
        "v8120_version": V8120_VERSION,
        "approved_exact_account_ids": sorted(APPROVED),
        "target_count": len(EXPECTED_ACTIONABLE),
        "target_tickers": sorted(EXPECTED_ACTIONABLE),
        "target_names": [EXPECTED_ACTIONABLE[x] for x in sorted(EXPECTED_ACTIONABLE)],
        "prior_exhausted_not_requeried_count": len(exhausted),
        "prior_exhausted_not_requeried_tickers": sorted(exhausted),
        "dominant_financial_period": f"{dominant_year}_{dominant_code}",
        "annual_source_year": annual_year,
        "current_target_available_count": 5,
        "current_target_missing_count": 0,
        "current_target_missing_tickers": [],
        "classification_counts": dict(class_counts),
        "recovery_lane_counts": dict(lane_counts),
        "both_approved_exact_recoverable_count": len(recoverable),
        "both_approved_exact_recoverable_tickers": sorted(recoverable),
        "partial_only_count": len(partial),
        "partial_only_tickers": sorted(partial),
        "no_approved_exact_count": len(no_exact),
        "no_approved_exact_tickers": sorted(no_exact),
        "newly_exhausted_no_approved_exact_count": len(no_exact),
        "newly_exhausted_no_approved_exact_tickers": sorted(no_exact),
        "official_query_incomplete_count": 0,
        "official_query_incomplete_tickers": [],
        "conflict_or_nonunique_count": len(conflict),
        "conflict_or_nonunique_tickers": sorted(conflict),
        "opendart_attempted_requests": client.attempted,
        "opendart_successful_requests": client.successful,
        "opendart_transport_failure_count": 0,
        "opendart_dart_status_failure_count": 0,
        "hard_guards": {
            "production_source_cache_modified": False,
            "production_source_run_log_modified": False,
            "production_financial_cache_modified": False,
            "production_price_elasticity_cache_modified": False,
            "production_ocf_cache_modified": False,
            "production_api_modified": False,
            "production_investment_score_written": False,
            "scoring_policy_modified": False,
            "source_value_imputed": False,
            "new_da_account_id_approved": False,
            "prior_exhausted_lane_requeried": False,
            "source_promoted": False,
        },
        "next_step": next_step,
    }

    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    OUT_LOG.write_text(
        "\n".join([
            f"VERSION={VERSION}",
            "STATUS=AUDIT_ONLY_CURRENT_ACTIONABLE_EXACT_DA",
            "TARGET_COUNT=5",
            "TARGET_AVAILABLE=5",
            "TARGET_MISSING=0",
            f"BOTH_APPROVED_EXACT_RECOVERABLE={len(recoverable)}",
            f"PARTIAL_ONLY={len(partial)}",
            f"NO_APPROVED_EXACT={len(no_exact)}",
            "OFFICIAL_QUERY_INCOMPLETE=0",
            f"CONFLICT_OR_NONUNIQUE={len(conflict)}",
            f"OPENDART_ATTEMPTED={client.attempted}",
            f"OPENDART_SUCCESSFUL={client.successful}",
            "OPENDART_TRANSPORT_FAILURES=0",
            "OPENDART_STATUS_FAILURES=0",
            "PRIOR_EXHAUSTED_LANE_REQUERIED=false",
            "SOURCE_PROMOTED=false",
            "SCORING_POLICY_MODIFIED=false",
            "STATUS_OK=true",
            f"NEXT_STEP={next_step}",
        ]) + "\n",
        encoding="utf-8",
    )

    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text(
        "\n".join([
            "# V8.12.9 current actionable exact D&A single-blocker audit",
            "",
            "- Targets: 5 current actionable EXACT_DA_SOURCE single blockers from V8.12.8.",
            f"- Prior exhausted exact-D&A targets not re-queried: {len(exhausted)}.",
            f"- Both approved exact recoverable: {len(recoverable)}.",
            f"- Partial only: {len(partial)}.",
            f"- No approved exact: {len(no_exact)}.",
            f"- Conflict/nonunique: {len(conflict)}.",
            "",
            "## Contract",
            "",
            "- Only the two already-approved D&A account IDs are accepted.",
            "- Missing D&A is never treated as zero.",
            "- Partial exact evidence is not promoted.",
            "- Conflict/nonunique evidence fails closed.",
            "- Any incomplete official query fails the workflow before commit.",
            "- This step is AUDIT_ONLY and does not mutate production data.",
            "",
            f"Next: `{next_step}`",
            "",
        ]),
        encoding="utf-8",
    )

    print("V8129_CURRENT_ACTIONABLE_EXACT_DA_AUDIT=PASS")


if __name__ == "__main__":
    main()
