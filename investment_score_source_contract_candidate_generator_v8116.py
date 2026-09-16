#!/usr/bin/env python3
from __future__ import annotations

import difflib
import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "2026-09-16-v8.11.6-freeze-v8115-stage-production-candidate"
V8115_VERSION = "2026-09-16-v8.11.5-temp-source-enricher-full-refresh-regression"
V8115_RESULT_COMMIT = "c6758c8f9a269d2907ee17fb1726fb3de37362dc"
BASE_SOURCE_CONTRACT = "2026-09-10-v8.5.4-investment-score-source-contract"
CANDIDATE_SOURCE_CONTRACT = (
    "2026-09-16-v8.11.6-staged-five-financial-cis-interest-revenue-contract"
)

ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

BASE = ROOT / "investment_score_source_enricher_v854.py"
V8115 = ROOT / "latest/investment_score_temp_source_refresh_v8115_summary_latest.json"

CANDIDATE_DIR = ROOT / "staged"
CANDIDATE = CANDIDATE_DIR / "investment_score_source_enricher_v8116_candidate.py"
PATCH = CANDIDATE_DIR / "investment_score_source_enricher_v8116_candidate.patch"

OUT_JSON = ROOT / "latest/investment_score_source_contract_candidate_v8116_summary_latest.json"
OUT_LOG = ROOT / "latest/investment_score_source_contract_candidate_v8116_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_source_contract_candidate_v8116.md"

AUDITED = {"000810", "005830", "029780", "105560", "138930"}
EXPECTED_ACTIVE = {"000810", "005830", "029780", "105560"}
EXPECTED_INACTIVE = {"138930"}
EXACT_STATEMENT = "CIS"
EXACT_ACCOUNT_ID = "ifrs-full_RevenueFromInterest"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def validate_v8115():
    s = read_json(V8115)
    if s.get("version") != V8115_VERSION:
        raise RuntimeError("V8116_V8115_VERSION_MISMATCH")
    if s.get("status") != "AUDIT_ONLY":
        raise RuntimeError("V8116_V8115_STATUS_MISMATCH")
    if s.get("patch_status") != "TEMP_PATCH_EXECUTED_ONLY":
        raise RuntimeError("V8116_V8115_PATCH_STATUS_MISMATCH")
    if set(s.get("audited_scope_tickers") or []) != AUDITED:
        raise RuntimeError("V8116_V8115_AUDITED_SCOPE_CHANGED")
    if set(s.get("active_source_target_tickers") or []) != EXPECTED_ACTIVE:
        raise RuntimeError("V8116_V8115_ACTIVE_SCOPE_CHANGED")
    if set(s.get("inactive_target_tickers") or []) != EXPECTED_INACTIVE:
        raise RuntimeError("V8116_V8115_INACTIVE_SCOPE_CHANGED")

    exact = {
        "control_source_rows": 242,
        "shadow_source_rows": 242,
        "control_source_raw_ready": 222,
        "shadow_source_raw_ready": 226,
        "raw_ready_delta": 4,
        "scorer_universe_count": 221,
        "control_ready_count": 5,
        "shadow_ready_count": 8,
        "ready_delta": 3,
        "control_blocker_occurrences": 2178,
        "shadow_blocker_occurrences": 2166,
        "blocker_occurrences_reduced_by": 12,
        "non_target_score_row_changed_count": 0,
    }
    for key, expected in exact.items():
        if s.get(key) != expected:
            raise RuntimeError(
                f"V8116_V8115_EVIDENCE_CHANGED:{key}:{s.get(key)}!={expected}"
            )

    if set(s.get("newly_ready_tickers") or []) != {"000810", "005830", "105560"}:
        raise RuntimeError("V8116_V8115_NEW_READY_CHANGED")
    if s.get("lost_ready_tickers") != []:
        raise RuntimeError("V8116_V8115_READY_REGRESSION_PRESENT")

    card = (s.get("target_score_results") or {}).get("029780") or {}
    if card.get("missing_after") != [
        "수급·공시부담:SUPPLY_LIMITED_NO_POSITIVE_EVIDENCE"
    ]:
        raise RuntimeError("V8116_V8115_CARD_REMAINDER_CHANGED")

    guards = s.get("hard_guards") or {}
    false_guards = {
        "production_source_enricher_modified",
        "production_source_cache_modified",
        "production_source_run_log_modified",
        "production_financial_cache_modified",
        "production_api_modified",
        "scoring_policy_modified",
        "inactive_target_force_inserted",
        "broad_financial_sector_exception_created",
        "fuzzy_cis_revenue_match_allowed",
        "source_value_imputed",
    }
    if not all(guards.get(k) is False for k in false_guards):
        raise RuntimeError("V8116_V8115_HARD_GUARD_FALSE_SET_CHANGED")
    if guards.get("non_target_source_rows_unchanged") is not True:
        raise RuntimeError("V8116_V8115_NON_TARGET_SOURCE_DRIFT")
    if guards.get("non_target_score_rows_unchanged") is not True:
        raise RuntimeError("V8116_V8115_NON_TARGET_SCORE_DRIFT")
    if guards.get("ready_regression_count") != 0:
        raise RuntimeError("V8116_V8115_READY_REGRESSION_COUNT_CHANGED")
    return s


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"V8116_PATCH_ANCHOR_{label}:{count}")
    return text.replace(old, new, 1)


def build_candidate(base_text: str) -> str:
    text = base_text

    text = replace_once(
        text,
        'SCRIPT_VERSION = "investment_score_source_enricher_v854.py v1.0.1-transient-retention-guard"',
        'SCRIPT_VERSION = "investment_score_source_enricher_v8116_candidate.py staged-v1"',
        "SCRIPT_VERSION",
    )
    text = replace_once(
        text,
        'SOURCE_CONTRACT_VERSION = "2026-09-10-v8.5.4-investment-score-source-contract"',
        f'SOURCE_CONTRACT_VERSION = "{CANDIDATE_SOURCE_CONTRACT}"',
        "SOURCE_CONTRACT_VERSION",
    )

    anchor = 'VALID_FINANCIAL_STATUS = {"READY", "PARTIAL"}\n'
    addition = '''VALID_FINANCIAL_STATUS = {"READY", "PARTIAL"}

# V8.11.6 staged candidate: evidence-approved exact revenue semantics only.
# This is intentionally ticker-scoped and fail-closed.
FINANCIAL_REVENUE_CIS_EXACT_TICKERS = {
    "000810",
    "005830",
    "029780",
    "105560",
    "138930",
}
FINANCIAL_REVENUE_CIS_EXACT_STATEMENT = "CIS"
FINANCIAL_REVENUE_CIS_EXACT_ACCOUNT_ID = "ifrs-full_RevenueFromInterest"
'''
    text = replace_once(text, anchor, addition, "CONSTANTS")

    start = text.index("def query_multi_period(\n")
    end = text.index("\ndef select_fs_rows(", start)

    new_query = r'''def exact_cis_interest_revenue_hits(
    rows: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    return [
        dict(row)
        for row in rows
        if norm_text(row.get("sj_div")) == FINANCIAL_REVENUE_CIS_EXACT_STATEMENT
        and norm_text(row.get("account_id")) == FINANCIAL_REVENUE_CIS_EXACT_ACCOUNT_ID
    ]


def query_multi_period(
    client: OpenDartClient,
    targets: Sequence[Mapping[str, str]],
    year: int,
    report_code: str,
) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    result: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    corp_codes = [item["corp_code"] for item in targets]
    for batch_index, batch in enumerate(chunks(corp_codes, 100), start=1):
        payload = client.get_json(
            MULTI_ACCOUNT_URL,
            {
                "corp_code": ",".join(batch),
                "bsns_year": str(year),
                "reprt_code": report_code,
            },
            f"multi:{year}:{report_code}:batch{batch_index}",
        )
        items = payload.get("list") if isinstance(payload.get("list"), list) else []
        for item in items:
            corp_code = clean_corp_code(item.get("corp_code"))
            fs_div = norm_text(item.get("fs_div"))
            if corp_code and fs_div:
                result[corp_code][fs_div].append(dict(item))
        time.sleep(0.08)

    # Narrow staged extension:
    # only audited tickers receive one exact CIS interest-revenue row from
    # the official full-account endpoint. No fuzzy alias or sector-wide rule.
    for target in targets:
        ticker = clean_ticker(target.get("ticker"))
        if ticker not in FINANCIAL_REVENUE_CIS_EXACT_TICKERS:
            continue

        corp_code = clean_corp_code(target.get("corp_code"))
        fs_div = norm_text(target.get("preferred_fs_div")) or "CFS"
        if not corp_code:
            continue

        payload = client.get_json(
            FULL_ACCOUNT_URL,
            {
                "corp_code": corp_code,
                "bsns_year": str(year),
                "reprt_code": report_code,
                "fs_div": fs_div,
            },
            f"narrow-revenue:{ticker}:{year}:{report_code}:{fs_div}",
        )
        status = norm_text(payload.get("status"))
        items = payload.get("list") if isinstance(payload.get("list"), list) else []
        if status != "000":
            continue

        hits = exact_cis_interest_revenue_hits(items)
        if len(hits) != 1:
            # Fail closed: ambiguous or absent exact account is not promoted.
            continue

        selected_rows = result[corp_code][fs_div]
        preexisting = exact_cis_interest_revenue_hits(selected_rows)
        if len(preexisting) > 1:
            raise RuntimeError(
                "AMBIGUOUS_PREEXISTING_EXACT_CIS_INTEREST_REVENUE:"
                f"{ticker}:{year}:{report_code}:{len(preexisting)}"
            )
        if not preexisting:
            selected_rows.append(hits[0])

    return result

'''
    text = text[:start] + new_query + text[end + 1:]

    start = text.index("def account_values(")
    end = text.index("\ndef cumulative_value(", start)

    new_accounts = r'''def account_values(
    rows: Sequence[Mapping[str, Any]],
    ticker: str = "",
) -> Dict[str, Dict[str, Any]]:
    output: Dict[str, Dict[str, Any]] = {}
    ticker = clean_ticker(ticker)

    for key, spec in ACCOUNT_SPECS.items():
        chosen = None

        if key == "revenue" and ticker in FINANCIAL_REVENUE_CIS_EXACT_TICKERS:
            exact_hits = exact_cis_interest_revenue_hits(rows)
            if len(exact_hits) == 1:
                chosen = exact_hits[0]
            elif len(exact_hits) > 1:
                # Fail closed; never guess among duplicate exact rows.
                chosen = None
            else:
                chosen = choose_account(rows, spec)
        else:
            chosen = choose_account(rows, spec)

        if chosen is None:
            output[key] = {"found": False}
            continue

        output[key] = {
            "found": True,
            "account_nm": norm_text(chosen.get("account_nm")),
            "thstrm_amount": parse_number(chosen.get("thstrm_amount")),
            "thstrm_add_amount": parse_number(chosen.get("thstrm_add_amount")),
            "frmtrm_amount": parse_number(chosen.get("frmtrm_amount")),
            "frmtrm_add_amount": parse_number(chosen.get("frmtrm_add_amount")),
            "bfefrmtrm_amount": parse_number(chosen.get("bfefrmtrm_amount")),
        }
    return output

'''
    text = text[:start] + new_accounts + text[end + 1:]

    text = replace_once(
        text,
        "annual_accounts = account_values(annual_rows)",
        'annual_accounts = account_values(annual_rows, target["ticker"])',
        "ANNUAL_CALL",
    )
    text = replace_once(
        text,
        "period_accounts[period] = account_values(rows)",
        'period_accounts[period] = account_values(rows, target["ticker"])',
        "QUARTER_CALL",
    )

    return text


def main():
    for path in (BASE, V8115):
        if not path.is_file():
            raise RuntimeError("V8116_MISSING_INPUT:" + str(path))

    v8115 = validate_v8115()

    base_text = BASE.read_text(encoding="utf-8")
    if f'SOURCE_CONTRACT_VERSION = "{BASE_SOURCE_CONTRACT}"' not in base_text:
        raise RuntimeError("V8116_BASE_SOURCE_CONTRACT_CHANGED")
    if '"statement": "IS"' not in base_text:
        raise RuntimeError("V8116_BASE_REVENUE_STATEMENT_CHANGED")
    if '"이자수익"' not in base_text:
        raise RuntimeError("V8116_BASE_INTEREST_EXCLUSION_CHANGED")

    candidate_text = build_candidate(base_text)

    CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
    CANDIDATE.write_text(candidate_text, encoding="utf-8")

    diff = "".join(
        difflib.unified_diff(
            base_text.splitlines(keepends=True),
            candidate_text.splitlines(keepends=True),
            fromfile=str(BASE),
            tofile=str(CANDIDATE),
        )
    )
    PATCH.write_text(diff, encoding="utf-8")

    if not diff:
        raise RuntimeError("V8116_EMPTY_PATCH")
    if "ifrs-full_RevenueFromInterest" not in candidate_text:
        raise RuntimeError("V8116_EXACT_ACCOUNT_MISSING")
    if "FINANCIAL_REVENUE_CIS_EXACT_TICKERS" not in candidate_text:
        raise RuntimeError("V8116_TICKER_SCOPE_MISSING")

    summary = {
        "version": VERSION,
        "v8115_version": V8115_VERSION,
        "v8115_result_commit": V8115_RESULT_COMMIT,
        "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
        "status": "STAGED_CANDIDATE_ONLY",
        "base_source_contract_version": BASE_SOURCE_CONTRACT,
        "candidate_source_contract_version": CANDIDATE_SOURCE_CONTRACT,
        "base_source_sha256": sha256(BASE),
        "candidate_source_sha256": sha256(CANDIDATE),
        "patch_sha256": sha256(PATCH),
        "audited_scope_tickers": sorted(AUDITED),
        "v8115_frozen_evidence": {
            "source_rows": v8115["control_source_rows"],
            "raw_ready_before": v8115["control_source_raw_ready"],
            "raw_ready_after": v8115["shadow_source_raw_ready"],
            "raw_ready_delta": v8115["raw_ready_delta"],
            "scorer_universe_count": v8115["scorer_universe_count"],
            "ready_before": v8115["control_ready_count"],
            "ready_after": v8115["shadow_ready_count"],
            "ready_delta": v8115["ready_delta"],
            "blockers_before": v8115["control_blocker_occurrences"],
            "blockers_after": v8115["shadow_blocker_occurrences"],
            "blockers_reduced_by": v8115["blocker_occurrences_reduced_by"],
            "newly_ready_tickers": v8115["newly_ready_tickers"],
        },
        "candidate_contract": {
            "account_key": "revenue",
            "statement": EXACT_STATEMENT,
            "account_id": EXACT_ACCOUNT_ID,
            "selection_rule": "EXACT_ID_UNIQUE_ONLY",
            "ticker_scope": sorted(AUDITED),
            "inactive_ticker_force_insert": False,
            "fallback_for_no_exact_hit": "UNCHANGED_V854_REVENUE_LOGIC",
            "duplicate_exact_hit_policy": "FAIL_CLOSED_NO_SELECTION",
            "full_account_fetch_scope": (
                "AUDITED_TICKERS_PRESENT_IN_CURRENT_TARGETS_ONLY"
            ),
        },
        "hard_guards": {
            "production_source_enricher_modified": False,
            "production_source_cache_modified": False,
            "production_api_modified": False,
            "scoring_policy_modified": False,
            "broad_financial_sector_rule_created": False,
            "new_fuzzy_alias_created": False,
            "inactive_target_force_inserted": False,
            "source_value_imputed": False,
        },
        "next_step": (
            "STAGED_PRODUCTION_PATCH_READY_FOR_CONTROLLED_APPLY_V8117"
        ),
    }

    OUT_JSON.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    OUT_LOG.write_text(
        "\n".join([
            f"VERSION={VERSION}",
            "STATUS=STAGED_CANDIDATE_ONLY",
            f"V8115_RESULT_COMMIT={V8115_RESULT_COMMIT}",
            "V8115_EVIDENCE_FROZEN=true",
            "AUDITED_SCOPE=5",
            "EXACT_STATEMENT=CIS",
            f"EXACT_ACCOUNT_ID={EXACT_ACCOUNT_ID}",
            "SELECTION_RULE=EXACT_ID_UNIQUE_ONLY",
            "DUPLICATE_POLICY=FAIL_CLOSED_NO_SELECTION",
            "FALLBACK=UNCHANGED_V854_REVENUE_LOGIC",
            "PRODUCTION_SOURCE_ENRICHER_MODIFIED=false",
            "PRODUCTION_SOURCE_CACHE_MODIFIED=false",
            "PRODUCTION_API_MODIFIED=false",
            "SCORING_POLICY_MODIFIED=false",
            "STATUS_OK=true",
        ]) + "\n",
        encoding="utf-8",
    )

    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text(
        "\n".join([
            "# V8.11.6 staged source-contract candidate",
            "",
            f"- Version: `{VERSION}`",
            f"- Frozen V8.11.5 result commit: `{V8115_RESULT_COMMIT}`",
            "- Production `investment_score_source_enricher_v854.py` is unchanged.",
            "- Candidate is generated as a separate staged file.",
            "- Scope is exactly five audited tickers.",
            f"- Exact selector: `{EXACT_STATEMENT}` / `{EXACT_ACCOUNT_ID}`.",
            "- Duplicate exact rows fail closed.",
            "- No exact hit falls back to unchanged V8.5.4 revenue selection.",
            "- Non-audited tickers always use unchanged V8.5.4 logic.",
            "",
            "## Frozen V8.11.5 proof",
            "",
            "- Source RAW ready: 222 → 226 (+4).",
            "- Scorer READY: 5 → 8 (+3).",
            "- Blockers: 2178 → 2166 (-12).",
            "- Non-target source/score drift: 0.",
            "",
        ]),
        encoding="utf-8",
    )

    print("V8116_CANDIDATE_GENERATION=PASS")


if __name__ == "__main__":
    main()
