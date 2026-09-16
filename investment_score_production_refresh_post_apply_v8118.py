#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(".")
sys.path.insert(0, str(ROOT.resolve()))

import investment_score_dry_run_v882 as scorer

VERSION = "2026-09-16-v8.11.8-production-source-refresh-post-apply-regression"
V8117_VERSION = "2026-09-16-v8.11.7-controlled-production-source-contract-apply"
V8117_RESULT_COMMIT = "c1f45f39bf27cfebb92b843fba3fef57a321efbc"
SOURCE_CONTRACT = "2026-09-16-v8.11.7-five-financial-cis-interest-revenue-contract"
SOURCE_SHA = "05df059a7574016e9cc4a418c5fba1eafa25045f70e4d423f5af99d8197309f0"
KST = ZoneInfo("Asia/Seoul")

AUDITED = {
    "000810": "삼성화재",
    "005830": "DB손해보험",
    "029780": "삼성카드",
    "105560": "KB금융",
    "138930": "BNK금융지주",
}
EXPECTED_ACTIVE = {"000810", "005830", "029780", "105560"}
EXPECTED_INACTIVE = {"138930"}
SOURCE_REASONS = {
    "매출 성장과 안정성:MISSING_REVENUE_GROWTH_INPUT",
    "최근 3년 매출 성장률:MISSING_3Y_REVENUE",
    "최근 분기 실적 가속·둔화:MISSING_ACCEL_INPUT",
}
NON_TARGET_METADATA_FIELDS = {"fetched_at_kst", "source_contract_version"}
TARGET_ALLOWED_CHANGE_FIELDS = {
    "fetched_at_kst",
    "source_contract_version",
    "annual_revenue_y0",
    "annual_revenue_y1",
    "annual_revenue_y2",
    "q2_revenue_current",
    "q2_revenue_previous",
    "q2_revenue_yoy_pct",
    "three_year_source_status",
    "quarter_source_status",
    "source_cache_status",
    "source_cache_reason",
    "quarter_acceleration_classification",
    "quarter_acceleration_policy_status",
}

BASE_SOURCE = ROOT / "latest/investment_score_source_cache_latest.csv"
BASE_LOG = ROOT / "latest/investment_score_source_run_log_latest.txt"
FIN = ROOT / "latest/financial_valuation_cache_latest.csv"
V8112_CSV = ROOT / "latest/investment_score_financial_revenue_semantic_v8112.csv"
V8117_JSON = ROOT / "latest/investment_score_source_contract_apply_v8117_summary_latest.json"
SOURCE_SCRIPT = ROOT / "investment_score_source_enricher_v854.py"

TMP = Path("/tmp/v8118")
BASE_DIR = TMP / "baseline"
REFRESH_DIR = TMP / "refresh"

CONTROL_SCORE_CSV = TMP / "control_score.csv"
CONTROL_SCORE_JSON = TMP / "control_score.json"
CONTROL_SCORE_LOG = TMP / "control_score.log"
CONTROL_SCORE_DOC = TMP / "control_score.md"
REFRESH_SCORE_CSV = TMP / "refresh_score.csv"
REFRESH_SCORE_JSON = TMP / "refresh_score.json"
REFRESH_SCORE_LOG = TMP / "refresh_score.log"
REFRESH_SCORE_DOC = TMP / "refresh_score.md"

OUT_CSV = ROOT / "latest/investment_score_production_refresh_v8118.csv"
OUT_JSON = ROOT / "latest/investment_score_production_refresh_v8118_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_production_refresh_v8118_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_production_refresh_v8118.md"


def ticker(value):
    s = "".join(ch for ch in str(value or "") if ch.isdigit())
    return s.zfill(6) if s else ""


def num(value):
    try:
        if value is None or isinstance(value, bool):
            return None
        s = str(value).strip().replace(",", "")
        if s in {"", "-", "None", "null", "nan", "NaN"}:
            return None
        x = float(s)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def sha256(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def read_kv(path: Path):
    out = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def missing_items(row):
    return {x for x in str(row.get("missing_components") or "").split(";") if x}


def diff_fields(a, b):
    return sorted(
        f for f in (set(a) | set(b))
        if str(a.get(f) or "") != str(b.get(f) or "")
    )


def verify_lineage():
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", V8117_RESULT_COMMIT, "HEAD"],
        check=True,
    )

    if sha256(SOURCE_SCRIPT) != SOURCE_SHA:
        raise RuntimeError("V8118_PRODUCTION_SOURCE_HASH_CHANGED")

    text = SOURCE_SCRIPT.read_text(encoding="utf-8")
    if f'SOURCE_CONTRACT_VERSION = "{SOURCE_CONTRACT}"' not in text:
        raise RuntimeError("V8118_SOURCE_CONTRACT_CODE_MISMATCH")
    if "FINANCIAL_REVENUE_CIS_EXACT_TICKERS" not in text:
        raise RuntimeError("V8118_NARROW_SCOPE_CODE_MISSING")
    if "ifrs-full_RevenueFromInterest" not in text:
        raise RuntimeError("V8118_EXACT_ACCOUNT_CODE_MISSING")

    s = read_json(V8117_JSON)
    if s.get("version") != V8117_VERSION:
        raise RuntimeError("V8118_V8117_VERSION_MISMATCH")
    if s.get("status") != "PRODUCTION_CODE_APPLIED_SOURCE_DATA_NOT_REFRESHED":
        raise RuntimeError("V8118_V8117_STATUS_MISMATCH")
    if s.get("source_contract_version") != SOURCE_CONTRACT:
        raise RuntimeError("V8118_V8117_CONTRACT_MISMATCH")
    if set(s.get("applied_scope_tickers") or []) != set(AUDITED):
        raise RuntimeError("V8118_V8117_SCOPE_MISMATCH")
    if s.get("next_step") != "RUN_PRODUCTION_SOURCE_REFRESH_AND_POST_APPLY_REGRESSION_V8118":
        raise RuntimeError("V8118_V8117_HANDOFF_MISMATCH")


def prepare_and_refresh():
    shutil.rmtree(TMP, ignore_errors=True)
    BASE_DIR.mkdir(parents=True)
    REFRESH_DIR.mkdir(parents=True)

    shutil.copy2(BASE_SOURCE, BASE_DIR / BASE_SOURCE.name)
    shutil.copy2(BASE_LOG, BASE_DIR / BASE_LOG.name)
    shutil.copy2(FIN, REFRESH_DIR / FIN.name)
    shutil.copy2(BASE_SOURCE, REFRESH_DIR / BASE_SOURCE.name)

    cmd = [
        sys.executable,
        str(SOURCE_SCRIPT),
        "--output-dir", str(REFRESH_DIR),
        "--workers", "4",
        "--timeout", "30",
        "--max-full-account-calls", "5000",
    ]
    proc = subprocess.run(
        cmd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=os.environ.copy(),
    )
    (TMP / "refresh_stdout.txt").write_text(proc.stdout, encoding="utf-8")

    if "INVESTMENT_SCORE_SOURCE_STATUS=OK" not in proc.stdout:
        raise RuntimeError("V8118_SOURCE_REFRESH_STATUS_NOT_OK")

    refresh_log = read_kv(REFRESH_DIR / BASE_LOG.name)
    if refresh_log.get("SOURCE_RETENTION_GUARD") != "PASS":
        raise RuntimeError("V8118_RETENTION_GUARD_NOT_PASS")
    if refresh_log.get("SOURCE_CONTRACT_VERSION") != SOURCE_CONTRACT:
        raise RuntimeError("V8118_REFRESH_CONTRACT_MISMATCH")


def validate_source():
    base_path = BASE_DIR / BASE_SOURCE.name
    refresh_path = REFRESH_DIR / BASE_SOURCE.name

    base = {
        ticker(r.get("ticker")): r
        for r in read_csv(base_path)
        if ticker(r.get("ticker"))
    }
    new = {
        ticker(r.get("ticker")): r
        for r in read_csv(refresh_path)
        if ticker(r.get("ticker"))
    }
    if set(base) != set(new):
        raise RuntimeError("V8118_SOURCE_TARGET_UNIVERSE_CHANGED")

    base_log = read_kv(BASE_DIR / BASE_LOG.name)
    new_log = read_kv(REFRESH_DIR / BASE_LOG.name)
    if int(base_log.get("OUTPUT_ROWS") or 0) != len(base):
        raise RuntimeError("V8118_BASE_LOG_COUNT_MISMATCH")
    if int(new_log.get("OUTPUT_ROWS") or 0) != len(new):
        raise RuntimeError("V8118_NEW_LOG_COUNT_MISMATCH")

    active = set(AUDITED) & set(new)
    inactive = set(AUDITED) - active
    if active != EXPECTED_ACTIVE:
        raise RuntimeError("V8118_ACTIVE_SET_CHANGED:" + ",".join(sorted(active)))
    if inactive != EXPECTED_INACTIVE:
        raise RuntimeError("V8118_INACTIVE_SET_CHANGED:" + ",".join(sorted(inactive)))

    semantic_drift = []
    metadata_only = 0
    for code in sorted(set(base) - active):
        changed = set(diff_fields(base[code], new[code]))
        semantic = sorted(changed - NON_TARGET_METADATA_FIELDS)
        if semantic:
            semantic_drift.append(code + ":" + ",".join(semantic))
        elif changed:
            metadata_only += 1
    if semantic_drift:
        raise RuntimeError(
            "V8118_NON_TARGET_SOURCE_SEMANTIC_DRIFT:"
            + "|".join(semantic_drift[:20])
        )

    evidence = {
        ticker(r.get("ticker")): r
        for r in read_csv(V8112_CSV)
        if ticker(r.get("ticker"))
    }

    audit_rows = []
    for code in sorted(active):
        before = base[code]
        after = new[code]
        changed = set(diff_fields(before, after))
        unexpected = sorted(changed - TARGET_ALLOWED_CHANGE_FIELDS)
        if unexpected:
            raise RuntimeError(
                "V8118_TARGET_UNEXPECTED_CHANGE:"
                + code + ":" + ",".join(unexpected)
            )

        if before.get("source_cache_status") != "LIMITED_RAW_SOURCE":
            raise RuntimeError("V8118_BASE_TARGET_NOT_LIMITED:" + code)
        if after.get("source_cache_status") != "READY_RAW_SOURCE":
            raise RuntimeError("V8118_NEW_TARGET_NOT_READY:" + code)
        if after.get("three_year_source_status") != "READY":
            raise RuntimeError("V8118_3Y_NOT_READY:" + code)
        if after.get("quarter_source_status") != "READY_Q2_SOURCE":
            raise RuntimeError("V8118_Q2_NOT_READY:" + code)
        if after.get("source_contract_version") != SOURCE_CONTRACT:
            raise RuntimeError("V8118_TARGET_CONTRACT_NOT_UPDATED:" + code)

        ev = evidence.get(code)
        if ev is None:
            raise RuntimeError("V8118_V8112_EVIDENCE_MISSING:" + code)

        mapping = {
            "annual_revenue_y0": "annual_revenue_y0",
            "annual_revenue_y1": "annual_revenue_y1",
            "annual_revenue_y2": "annual_revenue_y2",
            "q2_revenue_current": "q2_current_revenue",
            "q2_revenue_previous": "q2_previous_revenue",
            "q2_revenue_yoy_pct": "q2_revenue_yoy_pct",
        }
        for raw_field, ev_field in mapping.items():
            a = num(after.get(raw_field))
            b = num(ev.get(ev_field))
            if a is None or b is None or abs(a - b) > 0.01:
                raise RuntimeError(
                    f"V8118_OFFICIAL_VALUE_MISMATCH:"
                    f"{code}:{raw_field}:{a}!={b}"
                )

        audit_rows.append({
            "ticker": code,
            "name": AUDITED[code],
            "activation": "ACTIVE_SOURCE_TARGET",
            "status_before": before.get("source_cache_status") or "",
            "status_after": after.get("source_cache_status") or "",
            "three_year_status_after": after.get("three_year_source_status") or "",
            "quarter_status_after": after.get("quarter_source_status") or "",
            "changed_fields": ";".join(sorted(changed)),
            "unexpected_change_count": 0,
            "official_values_match_v8112": "TRUE",
        })

    for code in sorted(inactive):
        audit_rows.append({
            "ticker": code,
            "name": AUDITED[code],
            "activation": "NOT_CURRENTLY_ACTIVE_TARGET",
            "status_before": "",
            "status_after": "",
            "three_year_status_after": "",
            "quarter_status_after": "",
            "changed_fields": "",
            "unexpected_change_count": 0,
            "official_values_match_v8112": "HISTORICAL_EVIDENCE_PRESERVED",
        })

    return {
        "base": base,
        "new": new,
        "base_log": base_log,
        "new_log": new_log,
        "active": active,
        "inactive": inactive,
        "metadata_only_count": metadata_only,
        "audit_rows": audit_rows,
    }


def run_scorer(raw_path, out_csv, out_json, out_log, out_doc, version):
    old = {
        "VERSION": scorer.VERSION,
        "RAW": scorer.RAW,
        "OUT_CSV": scorer.OUT_CSV,
        "OUT_JSON": scorer.OUT_JSON,
        "OUT_LOG": scorer.OUT_LOG,
        "OUT_DOC": scorer.OUT_DOC,
    }
    try:
        scorer.VERSION = version
        scorer.RAW = raw_path
        scorer.OUT_CSV = out_csv
        scorer.OUT_JSON = out_json
        scorer.OUT_LOG = out_log
        scorer.OUT_DOC = out_doc
        rc = scorer.main()
    finally:
        for key, value in old.items():
            setattr(scorer, key, value)
    if rc not in (None, 0):
        raise RuntimeError(f"V8118_SCORER_FAILED:{version}:{rc}")


def validate_scores(source_info):
    base_path = BASE_DIR / BASE_SOURCE.name
    new_path = REFRESH_DIR / BASE_SOURCE.name

    run_scorer(
        base_path,
        CONTROL_SCORE_CSV, CONTROL_SCORE_JSON, CONTROL_SCORE_LOG, CONTROL_SCORE_DOC,
        "2026-09-16-v8.11.8-control",
    )
    run_scorer(
        new_path,
        REFRESH_SCORE_CSV, REFRESH_SCORE_JSON, REFRESH_SCORE_LOG, REFRESH_SCORE_DOC,
        VERSION,
    )

    control = {
        ticker(r.get("ticker")): r
        for r in read_csv(CONTROL_SCORE_CSV)
        if ticker(r.get("ticker"))
    }
    refreshed = {
        ticker(r.get("ticker")): r
        for r in read_csv(REFRESH_SCORE_CSV)
        if ticker(r.get("ticker"))
    }
    if set(control) != set(refreshed):
        raise RuntimeError("V8118_SCORER_UNIVERSE_CHANGED")

    active = source_info["active"] & set(control)
    if active != EXPECTED_ACTIVE:
        raise RuntimeError("V8118_SCORER_ACTIVE_SET_CHANGED")

    non_target = [
        code for code in sorted(control)
        if code not in active and control[code] != refreshed[code]
    ]
    if non_target:
        raise RuntimeError("V8118_NON_TARGET_SCORE_DRIFT:" + ",".join(non_target[:30]))

    target_results = {}
    for code in sorted(active):
        before = missing_items(control[code])
        after = missing_items(refreshed[code])
        if not SOURCE_REASONS <= before:
            raise RuntimeError("V8118_EXPECTED_SOURCE_BLOCKERS_ABSENT:" + code)
        expected_after = before - SOURCE_REASONS
        if after != expected_after:
            raise RuntimeError(
                "V8118_TARGET_AFTER_MISMATCH:"
                + code + ":EXPECTED=" + "|".join(sorted(expected_after))
                + ":ACTUAL=" + "|".join(sorted(after))
            )
        target_results[code] = {
            "status_before": control[code].get("score_status") or "",
            "status_after": refreshed[code].get("score_status") or "",
            "missing_before": sorted(before),
            "missing_after": sorted(after),
            "resolved_source_blockers": 3,
        }

    old_ready = {c for c, r in control.items() if r.get("score_status") == "READY"}
    new_ready = {c for c, r in refreshed.items() if r.get("score_status") == "READY"}
    lost = sorted(old_ready - new_ready)
    if lost:
        raise RuntimeError("V8118_READY_REGRESSION:" + ",".join(lost))

    newly = sorted(new_ready - old_ready)
    if set(newly) != {"000810", "005830", "105560"}:
        raise RuntimeError("V8118_NEW_READY_SET_CHANGED:" + ",".join(newly))

    if target_results["029780"]["missing_after"] != [
        "수급·공시부담:SUPPLY_LIMITED_NO_POSITIVE_EVIDENCE"
    ]:
        raise RuntimeError("V8118_SAMSUNG_CARD_REMAINDER_CHANGED")

    b0 = sum(
        len(missing_items(r)) for r in control.values()
        if r.get("score_status") == "LIMITED"
    )
    b1 = sum(
        len(missing_items(r)) for r in refreshed.values()
        if r.get("score_status") == "LIMITED"
    )
    if b0 - b1 != 12:
        raise RuntimeError(f"V8118_BLOCKER_REDUCTION_NOT_12:{b0}->{b1}")

    return {
        "scorer_universe_count": len(control),
        "control_ready_count": len(old_ready),
        "refreshed_ready_count": len(new_ready),
        "ready_delta": len(new_ready) - len(old_ready),
        "newly_ready_tickers": newly,
        "lost_ready_tickers": lost,
        "control_blocker_occurrences": b0,
        "refreshed_blocker_occurrences": b1,
        "blocker_occurrences_reduced_by": b0 - b1,
        "non_target_score_row_changed_count": 0,
        "target_score_results": target_results,
    }


def refuse_concurrent_drift():
    subprocess.run(["git", "fetch", "origin", "main"], check=True)
    protected = {
        "investment_score_source_enricher_v854.py",
        "investment_score_dry_run_v882.py",
        "config/investment_score_policy_v880.json",
        "latest/financial_valuation_cache_latest.csv",
        "latest/investment_score_source_cache_latest.csv",
        "latest/investment_score_source_run_log_latest.txt",
        "latest/investment_score_source_contract_apply_v8117_summary_latest.json",
    }
    upstream = set(
        subprocess.check_output(
            ["git", "diff", "--name-only", "HEAD..origin/main"],
            text=True,
        ).splitlines()
    )
    dangerous = sorted(
        p for p in upstream
        if p in protected or p.startswith("api/two_table_v1/")
    )
    if dangerous:
        raise RuntimeError(
            "V8118_CONCURRENT_PROTECTED_DRIFT:" + ",".join(dangerous)
        )


def apply_and_write(source_info, scores):
    refuse_concurrent_drift()

    shutil.copy2(REFRESH_DIR / BASE_SOURCE.name, BASE_SOURCE)
    shutil.copy2(REFRESH_DIR / BASE_LOG.name, BASE_LOG)

    summary = {
        "version": VERSION,
        "v8117_version": V8117_VERSION,
        "v8117_result_commit": V8117_RESULT_COMMIT,
        "source_contract_version": SOURCE_CONTRACT,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "PRODUCTION_SOURCE_REFRESH_APPLIED_POST_REGRESSION_PASS",
        "audited_scope_tickers": sorted(AUDITED),
        "active_source_target_tickers": sorted(source_info["active"]),
        "inactive_target_tickers": sorted(source_info["inactive"]),
        "baseline_source_rows": len(source_info["base"]),
        "refreshed_source_rows": len(source_info["new"]),
        "baseline_raw_ready": int(source_info["base_log"].get("RAW_SOURCE_READY") or 0),
        "refreshed_raw_ready": int(source_info["new_log"].get("RAW_SOURCE_READY") or 0),
        "raw_ready_delta": (
            int(source_info["new_log"].get("RAW_SOURCE_READY") or 0)
            - int(source_info["base_log"].get("RAW_SOURCE_READY") or 0)
        ),
        "non_target_source_semantic_drift_count": 0,
        "non_target_metadata_only_change_count": source_info["metadata_only_count"],
        "target_source_audit": source_info["audit_rows"],
        **scores,
        "hard_guards": {
            "production_source_code_modified_in_v8118": False,
            "production_source_cache_modified": True,
            "production_source_run_log_modified": True,
            "production_financial_cache_modified": False,
            "production_api_modified": False,
            "scoring_policy_modified": False,
            "non_target_source_semantics_unchanged": True,
            "non_target_score_rows_unchanged": True,
            "ready_regression_count": 0,
            "source_value_imputed": False,
            "inactive_target_force_inserted": False,
        },
        "next_step": "VERIFY_POST_COMMIT_SOURCE_CONTRACT_STATE_AND_RESUME_BLOCKER_AUDIT",
    }

    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_csv(OUT_CSV, source_info["audit_rows"], list(source_info["audit_rows"][0].keys()))

    OUT_LOG.write_text(
        "\n".join([
            f"VERSION={VERSION}",
            "STATUS=PRODUCTION_SOURCE_REFRESH_APPLIED_POST_REGRESSION_PASS",
            f"SOURCE_CONTRACT_VERSION={SOURCE_CONTRACT}",
            f"BASELINE_SOURCE_ROWS={summary['baseline_source_rows']}",
            f"REFRESHED_SOURCE_ROWS={summary['refreshed_source_rows']}",
            f"BASELINE_RAW_READY={summary['baseline_raw_ready']}",
            f"REFRESHED_RAW_READY={summary['refreshed_raw_ready']}",
            f"RAW_READY_DELTA={summary['raw_ready_delta']}",
            f"SCORER_UNIVERSE={scores['scorer_universe_count']}",
            f"CONTROL_READY={scores['control_ready_count']}",
            f"REFRESHED_READY={scores['refreshed_ready_count']}",
            f"READY_DELTA={scores['ready_delta']}",
            "NEWLY_READY_TICKERS=" + ",".join(scores["newly_ready_tickers"]),
            f"CONTROL_BLOCKERS={scores['control_blocker_occurrences']}",
            f"REFRESHED_BLOCKERS={scores['refreshed_blocker_occurrences']}",
            f"BLOCKER_REDUCED_BY={scores['blocker_occurrences_reduced_by']}",
            "NON_TARGET_SOURCE_SEMANTIC_DRIFT_COUNT=0",
            "NON_TARGET_SCORE_ROW_CHANGED_COUNT=0",
            "READY_REGRESSION_COUNT=0",
            "PRODUCTION_SOURCE_CACHE_MODIFIED=true",
            "PRODUCTION_SOURCE_RUN_LOG_MODIFIED=true",
            "PRODUCTION_API_MODIFIED=false",
            "SCORING_POLICY_MODIFIED=false",
            "STATUS_OK=true",
            "NEXT_STEP=VERIFY_POST_COMMIT_SOURCE_CONTRACT_STATE_AND_RESUME_BLOCKER_AUDIT",
        ]) + "\n",
        encoding="utf-8",
    )

    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text(
        "\n".join([
            "# V8.11.8 production source refresh post-apply regression",
            "",
            f"- Version: `{VERSION}`",
            "- Production V8.11.7 source code was first executed into a temporary output directory.",
            "- Source and scorer regression guards passed before production source cache replacement.",
            "- Non-target source semantic drift: 0.",
            "- Non-target scorer drift: 0.",
            "- READY regression: 0.",
            "- Production API, financial cache, source code, and scoring policy were not modified in this step.",
            "",
            "## Next",
            "",
            "`VERIFY_POST_COMMIT_SOURCE_CONTRACT_STATE_AND_RESUME_BLOCKER_AUDIT`",
            "",
        ]),
        encoding="utf-8",
    )


def main():
    for path in (BASE_SOURCE, BASE_LOG, FIN, V8112_CSV, V8117_JSON, SOURCE_SCRIPT):
        if not path.is_file():
            raise RuntimeError("V8118_MISSING_INPUT:" + str(path))

    verify_lineage()
    prepare_and_refresh()
    source_info = validate_source()
    scores = validate_scores(source_info)
    apply_and_write(source_info, scores)

    print("V8118_PRODUCTION_REFRESH_POST_APPLY=PASS")


if __name__ == "__main__":
    main()
