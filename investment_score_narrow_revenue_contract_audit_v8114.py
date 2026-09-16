#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import investment_score_dry_run_v882 as scorer

VERSION = "2026-09-16-v8.11.4-validation-fix2-dynamic-source-row-count"
V8113_VERSION = "2026-09-16-v8.11.3-validation-fix2-hard-guard-types"
V8113_RESULT_COMMIT = "c50855caf31e076b36ae83ce9f6ba760060141e4"
V8112_VERSION = "2026-09-16-v8.11.2-financial-revenue-semantic-alignment-audit"
POLICY_VERSION = "2026-09-13-v8.8.0-explicit-100-point-scoring-contract"
SOURCE_CONTRACT_VERSION = "2026-09-10-v8.5.4-investment-score-source-contract"

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

AUDITED_TARGETS = {
    "000810": "삼성화재",
    "005830": "DB손해보험",
    "029780": "삼성카드",
    "105560": "KB금융",
    "138930": "BNK금융지주",
}
EXPECTED_CURRENT_SOURCE_ACTIVE = {
    "000810", "005830", "029780", "105560",
}
EXPECTED_CURRENT_INACTIVE = {"138930"}

EXACT_ACCOUNT_ID = "ifrs-full_RevenueFromInterest"
EXACT_STATEMENT = "CIS"

EVIDENCE_TO_RAW = {
    "annual_revenue_y0": "annual_revenue_y0",
    "annual_revenue_y1": "annual_revenue_y1",
    "annual_revenue_y2": "annual_revenue_y2",
    "q2_revenue_current": "q2_current_revenue",
    "q2_revenue_previous": "q2_previous_revenue",
    "q2_revenue_yoy_pct": "q2_revenue_yoy_pct",
}

EXPECTED_SOURCE_REASONS = {
    "매출 성장과 안정성:MISSING_REVENUE_GROWTH_INPUT",
    "최근 3년 매출 성장률:MISSING_3Y_REVENUE",
    "최근 분기 실적 가속·둔화:MISSING_ACCEL_INPUT",
}

SOURCE_SCRIPT = ROOT / "investment_score_source_enricher_v854.py"
SOURCE_CACHE = ROOT / "latest/investment_score_source_cache_latest.csv"
SOURCE_RUN_LOG = ROOT / "latest/investment_score_source_run_log_latest.txt"
FIN = ROOT / "latest/financial_valuation_cache_latest.csv"
V8112_CSV = ROOT / "latest/investment_score_financial_revenue_semantic_v8112.csv"
V8112_JSON = ROOT / "latest/investment_score_financial_revenue_semantic_v8112_summary_latest.json"
V8113_JSON = ROOT / "latest/investment_score_v880_dry_run_v8113_summary_latest.json"

API_FILES = (
    ROOT / "api/two_table_v1/kospi.json",
    ROOT / "api/two_table_v1/decliners.json",
    ROOT / "api/two_table_v1/decliners24.json",
)

SHADOW_RAW = Path("/tmp/investment_score_source_cache_v8114_shadow.csv")
CONTROL_CSV = Path("/tmp/investment_score_v8114_control.csv")
CONTROL_JSON = Path("/tmp/investment_score_v8114_control.json")
CONTROL_LOG = Path("/tmp/investment_score_v8114_control.log")
CONTROL_DOC = Path("/tmp/investment_score_v8114_control.md")
SHADOW_CSV = Path("/tmp/investment_score_v8114_shadow.csv")
SHADOW_JSON = Path("/tmp/investment_score_v8114_shadow.json")
SHADOW_LOG = Path("/tmp/investment_score_v8114_shadow.log")
SHADOW_DOC = Path("/tmp/investment_score_v8114_shadow.md")

OUT_CSV = ROOT / "latest/investment_score_narrow_revenue_contract_v8114.csv"
OUT_JSON = ROOT / "latest/investment_score_narrow_revenue_contract_v8114_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_narrow_revenue_contract_v8114_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_narrow_revenue_contract_v8114.md"
PATCH_JSON = ROOT / "latest/investment_score_narrow_revenue_contract_v8114_patch_proposal.json"


def ticker(value):
    s = "".join(ch for ch in str(value or "") if ch.isdigit())
    return s.zfill(6) if s else ""


def num(value):
    try:
        s = str(value or "").strip().replace(",", "")
        if s in {"", "-", "None", "null", "nan", "NaN"}:
            return None
        return float(s)
    except Exception:
        return None


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_csv_with_fields(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        return list(r), list(r.fieldnames or [])


def write_csv(path: Path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def sha256(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def missing_items(row):
    return {
        x for x in str(row.get("missing_components") or "").split(";")
        if x
    }


def parse_log(path: Path):
    out = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def current_production_tickers():
    all_codes = set()
    per_table = {}
    for path in API_FILES:
        payload = read_json(path)
        rows = payload.get("rows") or []
        codes = {
            ticker(r.get("ticker"))
            for r in rows
            if ticker(r.get("ticker"))
        }
        per_table[path.stem] = sorted(codes)
        all_codes |= codes
    return all_codes, per_table


def validate_static_scope():
    text = SOURCE_SCRIPT.read_text(encoding="utf-8")
    if (
        'SOURCE_CONTRACT_VERSION = '
        '"2026-09-10-v8.5.4-investment-score-source-contract"'
        not in text
    ):
        raise RuntimeError("V8114_SOURCE_CONTRACT_VERSION_CHANGED")
    if '"statement": "IS"' not in text:
        raise RuntimeError("V8114_REVENUE_BASE_STATEMENT_CHANGED")
    if '"이자수익"' not in text:
        raise RuntimeError("V8114_INTEREST_REVENUE_EXCLUSION_MISSING")
    if "def choose_account(" not in text or "def account_values(" not in text:
        raise RuntimeError("V8114_ACCOUNT_SELECTION_FUNCTIONS_MISSING")

    patch = {
        "status": "PROPOSAL_ONLY",
        "base_source_script": str(SOURCE_SCRIPT),
        "base_source_script_sha256": sha256(SOURCE_SCRIPT),
        "base_source_contract_version": SOURCE_CONTRACT_VERSION,
        "audited_contract_scope": {
            "tickers": sorted(AUDITED_TARGETS),
            "account_key": "revenue",
            "statement": EXACT_STATEMENT,
            "account_id": EXACT_ACCOUNT_ID,
            "selection_rule": "EXACT_ID_UNIQUE_ONLY",
            "fallback_for_all_other_tickers": "UNCHANGED_V854_CHOOSE_ACCOUNT",
        },
        "activation_rule": (
            "RULE_REMAINS_DEFINED_FOR_ALL_FIVE; "
            "IT_EXECUTES_ONLY_WHEN_THE_AUDITED_TICKER_IS_IN_THE_CURRENT_SOURCE_TARGET_UNIVERSE"
        ),
        "automatic_apply": False,
        "production_mutation": False,
    }
    PATCH_JSON.write_text(
        json.dumps(patch, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def validate_historical_evidence():
    s13 = read_json(V8113_JSON)
    if s13.get("version") != V8113_VERSION:
        raise RuntimeError("V8114_V8113_VERSION_MISMATCH")
    if s13.get("status") != "DRY_RUN_ONLY":
        raise RuntimeError("V8114_V8113_STATUS_MISMATCH")
    r13 = s13.get("v8113_shadow_recheck") or {}
    if int(r13.get("after_ready_count") or 0) != 61:
        raise RuntimeError("V8114_V8113_READY_NOT_61")
    if int(r13.get("after_blocker_occurrences") or 0) != 261:
        raise RuntimeError("V8114_V8113_BLOCKERS_NOT_261")
    if int(r13.get("after_source_cache_blockers") or 0) != 39:
        raise RuntimeError("V8114_V8113_SOURCE_BLOCKERS_NOT_39")
    if set(r13.get("newly_ready_tickers") or []) != set(AUDITED_TARGETS):
        raise RuntimeError("V8114_V8113_AUDITED_SET_CHANGED")
    if r13.get("non_target_score_row_changed_count") != 0:
        raise RuntimeError("V8114_V8113_NON_TARGET_DRIFT_PRESENT")

    s12 = read_json(V8112_JSON)
    if s12.get("version") != V8112_VERSION:
        raise RuntimeError("V8114_V8112_VERSION_MISMATCH")
    if s12.get("status") != "AUDIT_ONLY":
        raise RuntimeError("V8114_V8112_STATUS_MISMATCH")
    if s12.get("candidate_statement") != EXACT_STATEMENT:
        raise RuntimeError("V8114_V8112_STATEMENT_CHANGED")
    if s12.get("candidate_account_id") != EXACT_ACCOUNT_ID:
        raise RuntimeError("V8114_V8112_ACCOUNT_CHANGED")
    if s12.get("all_five_financial_cache_exact_match") is not True:
        raise RuntimeError("V8114_V8112_NOT_ALL_FIVE_MATCHED")
    if int(s12.get("fully_aligned_count") or 0) != 5:
        raise RuntimeError("V8114_V8112_ALIGNED_COUNT_NOT_5")
    if int(s12.get("mismatch_count") or 0) != 0:
        raise RuntimeError("V8114_V8112_MISMATCH_PRESENT")
    if s12.get("automatic_semantic_extension", {}).get("approved") is not False:
        raise RuntimeError("V8114_V8112_AUTO_APPROVAL_CHANGED")

    evidence = {
        ticker(r.get("ticker")): r
        for r in read_csv(V8112_CSV)
        if ticker(r.get("ticker"))
    }
    if set(evidence) != set(AUDITED_TARGETS):
        raise RuntimeError("V8114_V8112_EVIDENCE_SET_CHANGED")

    for code, row in evidence.items():
        if (
            row.get("classification")
            != "EXACT_CIS_INTEREST_REVENUE_ALIGNED_WITH_FINANCIAL_CACHE"
        ):
            raise RuntimeError("V8114_EVIDENCE_CLASS_CHANGED:" + code)
        if row.get("candidate_statement") != EXACT_STATEMENT:
            raise RuntimeError("V8114_EVIDENCE_STATEMENT_CHANGED:" + code)
        if row.get("candidate_account_id") != EXACT_ACCOUNT_ID:
            raise RuntimeError("V8114_EVIDENCE_ACCOUNT_CHANGED:" + code)
        for evidence_field in EVIDENCE_TO_RAW.values():
            if num(row.get(evidence_field)) is None:
                raise RuntimeError(
                    f"V8114_HISTORICAL_EVIDENCE_VALUE_MISSING:"
                    f"{code}:{evidence_field}"
                )
    return evidence


def classify_current_scope(evidence):
    source_rows = {
        ticker(r.get("ticker")): r
        for r in read_csv(SOURCE_CACHE)
        if ticker(r.get("ticker"))
    }
    fin_rows = {
        ticker(r.get("ticker")): r
        for r in read_csv(FIN)
        if ticker(r.get("ticker"))
    }
    prod_tickers, per_table = current_production_tickers()

    source_active = set(AUDITED_TARGETS) & set(source_rows)
    source_inactive = set(AUDITED_TARGETS) - source_active
    fin_active = set(AUDITED_TARGETS) & set(fin_rows)
    prod_active = set(AUDITED_TARGETS) & prod_tickers

    if source_active != EXPECTED_CURRENT_SOURCE_ACTIVE:
        raise RuntimeError(
            "V8114_CURRENT_SOURCE_ACTIVE_SET_CHANGED:"
            + ",".join(sorted(source_active))
        )
    if source_inactive != EXPECTED_CURRENT_INACTIVE:
        raise RuntimeError(
            "V8114_CURRENT_INACTIVE_SET_CHANGED:"
            + ",".join(sorted(source_inactive))
        )
    if not source_active <= fin_active:
        raise RuntimeError(
            "V8114_SOURCE_ACTIVE_WITHOUT_FIN:"
            + ",".join(sorted(source_active - fin_active))
        )

    for code in sorted(source_inactive):
        if code in fin_rows:
            raise RuntimeError("V8114_INACTIVE_STILL_IN_FIN:" + code)
        if code in prod_tickers:
            raise RuntimeError("V8114_INACTIVE_STILL_IN_PRODUCTION:" + code)

    for code in sorted(source_active):
        ev = evidence[code]
        fin = fin_rows[code]
        for ev_field, fin_field in (
            ("financial_cache_revenue", "revenue"),
            ("financial_cache_previous_revenue", "previous_revenue"),
            ("financial_cache_revenue_yoy_pct", "revenue_yoy_pct"),
        ):
            a = num(ev.get(ev_field))
            b = num(fin.get(fin_field))
            if a is None or b is None or abs(a - b) > 0.01:
                raise RuntimeError(
                    f"V8114_CURRENT_FIN_DRIFT:"
                    f"{code}:{ev_field}->{fin_field}:{a}!={b}"
                )

    inactive_evidence = {
        code: {
            "name": AUDITED_TARGETS[code],
            "classification": "NOT_CURRENTLY_ACTIVE_TARGET",
            "historical_semantic_evidence_preserved": True,
            "current_financial_cache_present": code in fin_rows,
            "current_source_cache_present": code in source_rows,
            "current_production_present": code in prod_tickers,
            "reason": "DYNAMIC_TABLE_TARGET_UNIVERSE_ABSENCE",
        }
        for code in sorted(source_inactive)
    }

    return {
        "source_rows": source_rows,
        "source_active": source_active,
        "source_inactive": source_inactive,
        "fin_active": fin_active,
        "prod_active": prod_active,
        "per_table": per_table,
        "inactive_evidence": inactive_evidence,
    }


def build_shadow_raw(evidence, scope):
    rows, fields = read_csv_with_fields(SOURCE_CACHE)
    source_map = {ticker(r.get("ticker")): r for r in rows}
    audit_rows = []

    for code in sorted(scope["source_active"]):
        original = source_map[code]
        if original.get("source_contract_version") != SOURCE_CONTRACT_VERSION:
            raise RuntimeError("V8114_SOURCE_CONTRACT_ROW_CHANGED:" + code)
        if original.get("source_cache_status") != "LIMITED_RAW_SOURCE":
            raise RuntimeError(
                f"V8114_ACTIVE_TARGET_NOT_LIMITED:"
                f"{code}:{original.get('source_cache_status')}"
            )
        reason = str(original.get("source_cache_reason") or "")
        if "3Y_ANNUAL_LIMITED" not in reason or "QUARTER_LIMITED" not in reason:
            raise RuntimeError("V8114_ACTIVE_SOURCE_REASON_CHANGED:" + code)

        patched = dict(original)
        changed_fields = []
        for raw_field, evidence_field in EVIDENCE_TO_RAW.items():
            if num(original.get(raw_field)) is not None:
                raise RuntimeError(
                    f"V8114_EXPECTED_REVENUE_FIELD_NOT_EMPTY:"
                    f"{code}:{raw_field}"
                )
            value = evidence[code][evidence_field]
            if num(value) is None:
                raise RuntimeError(
                    f"V8114_EVIDENCE_VALUE_MISSING:"
                    f"{code}:{evidence_field}"
                )
            patched[raw_field] = value
            changed_fields.append(raw_field)

        for field in fields:
            if field in EVIDENCE_TO_RAW:
                continue
            if patched.get(field) != original.get(field):
                raise RuntimeError(
                    f"V8114_NON_REVENUE_FIELD_CHANGED:{code}:{field}"
                )

        source_map[code] = patched
        audit_rows.append({
            "ticker": code,
            "name": AUDITED_TARGETS[code],
            "current_activation": "ACTIVE_SOURCE_TARGET",
            "baseline_source_cache_status": original.get("source_cache_status") or "",
            "baseline_source_cache_reason": original.get("source_cache_reason") or "",
            "candidate_statement": EXACT_STATEMENT,
            "candidate_account_id": EXACT_ACCOUNT_ID,
            "changed_field_count": len(changed_fields),
            "changed_fields": ";".join(changed_fields),
            "non_revenue_field_change_count": 0,
        })

    for code in sorted(scope["source_inactive"]):
        audit_rows.append({
            "ticker": code,
            "name": AUDITED_TARGETS[code],
            "current_activation": "NOT_CURRENTLY_ACTIVE_TARGET",
            "baseline_source_cache_status": "",
            "baseline_source_cache_reason": "",
            "candidate_statement": EXACT_STATEMENT,
            "candidate_account_id": EXACT_ACCOUNT_ID,
            "changed_field_count": 0,
            "changed_fields": "",
            "non_revenue_field_change_count": 0,
        })

    patched_rows = [source_map[ticker(r.get("ticker"))] for r in rows]
    write_csv(SHADOW_RAW, patched_rows, fields)
    return rows, audit_rows


def run_scorer(raw_path, out_csv, out_json, out_log, out_doc, version):
    old_version = scorer.VERSION
    old_raw = scorer.RAW
    old_out_csv = scorer.OUT_CSV
    old_out_json = scorer.OUT_JSON
    old_out_log = scorer.OUT_LOG
    old_out_doc = scorer.OUT_DOC
    try:
        scorer.VERSION = version
        scorer.RAW = raw_path
        scorer.OUT_CSV = out_csv
        scorer.OUT_JSON = out_json
        scorer.OUT_LOG = out_log
        scorer.OUT_DOC = out_doc
        rc = scorer.main()
    finally:
        scorer.VERSION = old_version
        scorer.RAW = old_raw
        scorer.OUT_CSV = old_out_csv
        scorer.OUT_JSON = old_out_json
        scorer.OUT_LOG = old_out_log
        scorer.OUT_DOC = old_out_doc
    if rc not in (None, 0):
        raise RuntimeError(f"V8114_SCORER_FAILED:{version}:{rc}")


def run_current_regression(evidence, scope):
    source_rows, audit_rows = build_shadow_raw(evidence, scope)

    run_scorer(
        SOURCE_CACHE,
        CONTROL_CSV,
        CONTROL_JSON,
        CONTROL_LOG,
        CONTROL_DOC,
        "2026-09-16-v8.11.4-current-universe-control",
    )
    run_scorer(
        SHADOW_RAW,
        SHADOW_CSV,
        SHADOW_JSON,
        SHADOW_LOG,
        SHADOW_DOC,
        VERSION,
    )

    control_rows = read_csv(CONTROL_CSV)
    shadow_rows = read_csv(SHADOW_CSV)
    control = {ticker(r.get("ticker")): r for r in control_rows}
    shadow = {ticker(r.get("ticker")): r for r in shadow_rows}

    if len(control) < 112:
        raise RuntimeError(
            f"V8114_CURRENT_SCORER_UNIVERSE_TOO_SMALL:{len(control)}"
        )
    if len(control) != len(shadow) or set(control) != set(shadow):
        raise RuntimeError("V8114_CONTROL_SHADOW_UNIVERSE_MISMATCH")

    scorer_active = set(AUDITED_TARGETS) & set(control)
    scorer_inactive = set(AUDITED_TARGETS) - scorer_active

    if not scorer_active <= scope["source_active"]:
        raise RuntimeError(
            "V8114_SCORER_ACTIVE_WITHOUT_SOURCE:"
            + ",".join(sorted(scorer_active - scope["source_active"]))
        )

    non_active_diffs = [
        code for code in sorted(control)
        if code not in scorer_active and control[code] != shadow[code]
    ]
    if non_active_diffs:
        raise RuntimeError(
            "V8114_NON_ACTIVE_SCORE_DRIFT:"
            + ",".join(non_active_diffs[:30])
        )

    old_ready = {
        c for c, r in control.items()
        if r.get("score_status") == "READY"
    }
    new_ready = {
        c for c, r in shadow.items()
        if r.get("score_status") == "READY"
    }
    lost_ready = sorted(old_ready - new_ready)
    if lost_ready:
        raise RuntimeError(
            "V8114_READY_REGRESSION:" + ",".join(lost_ready)
        )

    target_results = {}
    expected_reduction = 0

    for code in sorted(scorer_active):
        before = missing_items(control[code])
        after = missing_items(shadow[code])

        if not EXPECTED_SOURCE_REASONS <= before:
            raise RuntimeError(
                "V8114_EXPECTED_SOURCE_REASON_ABSENT:"
                + code + ":"
                + "|".join(sorted(EXPECTED_SOURCE_REASONS - before))
            )

        expected_after = before - EXPECTED_SOURCE_REASONS
        if after != expected_after:
            raise RuntimeError(
                "V8114_TARGET_AFTER_SET_MISMATCH:"
                + code
                + ":EXPECTED="
                + "|".join(sorted(expected_after))
                + ":ACTUAL="
                + "|".join(sorted(after))
            )

        expected_reduction += 3
        target_results[code] = {
            "name": AUDITED_TARGETS[code],
            "current_activation": "ACTIVE_SCORER_TARGET",
            "status_before": control[code].get("score_status") or "",
            "status_after": shadow[code].get("score_status") or "",
            "missing_before": sorted(before),
            "missing_after": sorted(after),
            "resolved_source_reasons": sorted(EXPECTED_SOURCE_REASONS),
            "resolved_blocker_count": 3,
        }

    for code in sorted(scorer_inactive):
        target_results[code] = {
            "name": AUDITED_TARGETS[code],
            "current_activation": (
                "ACTIVE_SOURCE_BUT_NOT_CURRENT_SCORER"
                if code in scope["source_active"]
                else "NOT_CURRENTLY_ACTIVE_TARGET"
            ),
            "historical_semantic_evidence_preserved": True,
            "current_score_row_present": False,
        }

    control_blockers = sum(
        len(missing_items(r))
        for r in control.values()
        if r.get("score_status") == "LIMITED"
    )
    shadow_blockers = sum(
        len(missing_items(r))
        for r in shadow.values()
        if r.get("score_status") == "LIMITED"
    )
    actual_reduction = control_blockers - shadow_blockers

    if actual_reduction != expected_reduction:
        raise RuntimeError(
            f"V8114_BLOCKER_REDUCTION_MISMATCH:"
            f"{actual_reduction}!={expected_reduction}"
        )

    newly_ready = sorted(new_ready - old_ready)
    expected_newly_ready = sorted(
        code
        for code in scorer_active
        if not (missing_items(control[code]) - EXPECTED_SOURCE_REASONS)
    )
    if newly_ready != expected_newly_ready:
        raise RuntimeError(
            "V8114_NEWLY_READY_SET_MISMATCH:"
            + ",".join(newly_ready)
        )

    source_log = parse_log(SOURCE_RUN_LOG)
    current_source_rows = len(source_rows)
    if int(source_log.get("OUTPUT_ROWS") or 0) != current_source_rows:
        raise RuntimeError("V8114_SOURCE_CACHE_LOG_ROW_MISMATCH")

    summary = {
        "version": VERSION,
        "v8113_version": V8113_VERSION,
        "v8113_result_commit": V8113_RESULT_COMMIT,
        "v8112_version": V8112_VERSION,
        "policy_version": POLICY_VERSION,
        "source_contract_version": SOURCE_CONTRACT_VERSION,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "AUDIT_ONLY",
        "patch_status": "PROPOSAL_ONLY_NOT_APPLIED",
        "audited_contract_scope_count": 5,
        "audited_contract_scope_tickers": sorted(AUDITED_TARGETS),
        "current_source_active_count": len(scope["source_active"]),
        "current_source_active_tickers": sorted(scope["source_active"]),
        "current_inactive_count": len(scope["source_inactive"]),
        "current_inactive_tickers": sorted(scope["source_inactive"]),
        "current_inactive_evidence": scope["inactive_evidence"],
        "current_production_active_tickers": sorted(scope["prod_active"]),
        "current_scorer_active_count": len(scorer_active),
        "current_scorer_active_tickers": sorted(scorer_active),
        "current_scorer_inactive_tickers": sorted(scorer_inactive),
        "current_source_cache_rows": current_source_rows,
        "current_source_log_targets": int(source_log.get("TARGETS") or 0),
        "current_source_log_raw_ready": int(
            source_log.get("RAW_SOURCE_READY") or 0
        ),
        "current_scorer_universe_count": len(control),
        "control_ready_count": len(old_ready),
        "shadow_ready_count": len(new_ready),
        "ready_delta": len(new_ready) - len(old_ready),
        "newly_ready_tickers": newly_ready,
        "lost_ready_tickers": lost_ready,
        "control_blocker_occurrences": control_blockers,
        "shadow_blocker_occurrences": shadow_blockers,
        "blocker_occurrences_reduced_by": actual_reduction,
        "expected_active_score_blockers_resolved": expected_reduction,
        "current_source_rows_patched_in_shadow": len(scope["source_active"]),
        "current_source_revenue_fields_patched_in_shadow": (
            6 * len(scope["source_active"])
        ),
        "target_results": target_results,
        "non_active_score_row_changed_count": len(non_active_diffs),
        "source_row_audit": audit_rows,
        "proposed_contract": {
            "scope_tickers": sorted(AUDITED_TARGETS),
            "account_key": "revenue",
            "statement": EXACT_STATEMENT,
            "account_id": EXACT_ACCOUNT_ID,
            "selection_rule": "EXACT_ID_UNIQUE_ONLY",
            "activation_rule": (
                "ONLY_WHEN_AUDITED_TICKER_IS_IN_CURRENT_SOURCE_TARGET_UNIVERSE"
            ),
            "all_other_tickers": "UNCHANGED_V854_LOGIC",
        },
        "hard_guards": {
            "production_api_changed": False,
            "production_investment_score_written": False,
            "source_enricher_changed": False,
            "production_source_cache_mutated": False,
            "financial_cache_mutated": False,
            "scoring_policy_changed": False,
            "broad_financial_sector_exception_created": False,
            "fuzzy_cis_revenue_match_allowed": False,
            "inactive_target_force_inserted": False,
            "source_value_imputed": False,
            "non_active_score_rows_unchanged": True,
            "ready_regression_count": 0,
        },
        "next_step": (
            "APPLY_NARROW_PATCH_TO_TEMP_SOURCE_ENRICHER_"
            "AND_RUN_FULL_CURRENT_SOURCE_REFRESH_REGRESSION"
        ),
    }

    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_csv(OUT_CSV, audit_rows, list(audit_rows[0].keys()))

    OUT_LOG.write_text(
        "\n".join([
            f"VERSION={VERSION}",
            "STATUS=AUDIT_ONLY",
            "PATCH_STATUS=PROPOSAL_ONLY_NOT_APPLIED",
            "AUDITED_CONTRACT_SCOPE=5",
            f"CURRENT_SOURCE_ACTIVE={len(scope['source_active'])}",
            "CURRENT_SOURCE_ACTIVE_TICKERS="
            + ",".join(sorted(scope["source_active"])),
            f"CURRENT_INACTIVE={len(scope['source_inactive'])}",
            "CURRENT_INACTIVE_TICKERS="
            + ",".join(sorted(scope["source_inactive"])),
            f"CURRENT_SCORER_UNIVERSE={len(control)}",
            f"CURRENT_SCORER_ACTIVE={len(scorer_active)}",
            "CURRENT_SCORER_ACTIVE_TICKERS="
            + ",".join(sorted(scorer_active)),
            f"CONTROL_READY={len(old_ready)}",
            f"SHADOW_READY={len(new_ready)}",
            f"READY_DELTA={len(new_ready)-len(old_ready)}",
            f"CONTROL_BLOCKERS={control_blockers}",
            f"SHADOW_BLOCKERS={shadow_blockers}",
            f"BLOCKER_REDUCED_BY={actual_reduction}",
            f"EXPECTED_ACTIVE_SCORE_BLOCKERS_RESOLVED={expected_reduction}",
            "NON_ACTIVE_SCORE_ROWS_UNCHANGED=true",
            "READY_REGRESSION_COUNT=0",
            "INACTIVE_TARGET_FORCE_INSERTED=false",
            "SOURCE_ENRICHER_CHANGED=false",
            "PRODUCTION_SOURCE_CACHE_MUTATED=false",
            "STATUS_OK=true",
            "NEXT_STEP=APPLY_NARROW_PATCH_TO_TEMP_SOURCE_ENRICHER_"
            "AND_RUN_FULL_CURRENT_SOURCE_REFRESH_REGRESSION",
        ]) + "\n",
        encoding="utf-8",
    )

    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text(
        "\n".join([
            "# V8.11.4 narrow financial revenue contract audit",
            "",
            f"- Version: `{VERSION}`",
            "- Historical contract evidence remains fixed for all five audited tickers.",
            "- Current execution scope is dynamic and follows the current source target universe.",
            "- BNK금융지주 is preserved as historical evidence but is not force-inserted while inactive.",
            "- Production source enricher/cache/scoring policy remain unchanged.",
            f"- Current source-active audited tickers: {', '.join(sorted(scope['source_active']))}",
            f"- Current scorer-active audited tickers: {', '.join(sorted(scorer_active))}",
            f"- Current scorer universe: {len(control)}",
            f"- Blockers: {control_blockers} → {shadow_blockers}",
            f"- READY: {len(old_ready)} → {len(new_ready)}",
            "",
        ]),
        encoding="utf-8",
    )


def main():
    for path in (
        SOURCE_SCRIPT,
        SOURCE_CACHE,
        SOURCE_RUN_LOG,
        FIN,
        V8112_CSV,
        V8112_JSON,
        V8113_JSON,
        *API_FILES,
    ):
        if not path.is_file():
            raise RuntimeError("V8114_MISSING_INPUT:" + str(path))

    validate_static_scope()
    evidence = validate_historical_evidence()
    scope = classify_current_scope(evidence)
    run_current_regression(evidence, scope)
    print("V8114_DYNAMIC_ACTIVE_SCOPE_AUDIT=PASS")


if __name__ == "__main__":
    main()

