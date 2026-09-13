#!/usr/bin/env python3
import csv
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "2026-09-13-v8.7.7-investment-score-policy-evidence-audit"
ROOT = Path(".")
KST = ZoneInfo("Asia/Seoul")

READINESS = ROOT / "latest/investment_score_readiness_latest.json"
SCORE_DOC = ROOT / "docs/scoring_system_v6.md"
OUT_JSON = ROOT / "latest/investment_score_policy_evidence_latest.json"
OUT_CSV = ROOT / "latest/investment_score_policy_evidence_components_latest.csv"
OUT_LOG = ROOT / "latest/investment_score_policy_evidence_run_log_latest.txt"
OUT_DOC = ROOT / "docs/investment_score_policy_evidence_v877.md"

ALIASES = {
    "매출 성장과 안정성": ["매출 성장", "매출성장"],
    "영업이익 성장과 흑자 여부": ["영업이익 성장", "영업이익성장"],
    "순이익 흐름": ["순이익 흐름", "순이익"],
    "영업이익률": ["영업이익률", "operating margin"],
    "ROE": ["ROE", "roe_annualized_pct"],
    "부채비율": ["부채비율", "debt ratio"],
    "영업현금흐름": ["영업현금흐름", "operating cash flow"],
    "PER": ["PER", "per_annualized"],
    "PBR": ["PBR", "pbr"],
    "EV/EBITDA": ["EV/EBITDA", "ev_ebitda"],
    "PSR 또는 대체 가치지표": ["PSR", "대체 가치지표"],
    "최근 3년 매출 성장률": ["3년 매출 성장", "최근 3년 매출"],
    "최근 3년 영업이익 성장률": ["3년 영업이익 성장", "최근 3년 영업이익"],
    "최근 분기 실적 가속·둔화": ["실적 가속", "가속·둔화", "가속/둔화"],
    "흑자 지속성과 이익 안정성": ["흑자 지속", "이익 안정성"],
    "순현금·기업가치 상태": ["순현금", "net cash"],
    "1개월 가격흐름": ["1개월 가격흐름", "1개월 수익률"],
    "3개월 가격흐름": ["3개월 가격흐름", "3개월 수익률"],
    "기간 저가·고가 대비 현재위치": ["현재위치", "position_pct"],
    "과열·급락 위험": ["과열", "급락 위험"],
    "20일 평균 거래대금과 거래량": ["20일 평균 거래대금", "거래활발"],
    "하루평균 절대등락률": ["하루평균 절대등락률", "가격탄력"],
    "수급·공시부담": ["수급·공시부담", "수급부담", "공시부담"],
}

THRESHOLD_CUES = (">=", "<=", ">", "<", "%", "~", "이상", "이하", "초과", "미만")

def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def scan_candidates():
    hits = {name: [] for name in ALIASES}
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.parts and path.parts[0] in {".git", "api", "latest", ".github"}:
            continue
        if path.name in {
            "investment_score_policy_evidence_v877.py",
            "investment_score_readiness_v871.py",
            "investment_score_readiness_v876.py",
        }:
            continue
        if path.suffix.lower() not in {".md", ".py", ".json", ".txt", ".yml", ".yaml"}:
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        for line_no, line in enumerate(lines, 1):
            text = line.strip()
            if not text:
                continue
            if not re.search(r"\d+(?:\.\d+)?\s*점", text):
                continue
            if not any(cue in text for cue in THRESHOLD_CUES):
                continue
            low = text.lower()
            for item, aliases in ALIASES.items():
                if any(alias.lower() in low for alias in aliases):
                    hits[item].append({
                        "path": path.as_posix(),
                        "line": line_no,
                        "text": text[:500],
                    })
    return hits

def market_policy():
    try:
        import market_metric_labels_enricher as module
        payload = module.policy_payload()
        return {
            "status": "READY",
            "policy_version": payload.get("policy_version"),
            "trading_activity": payload.get("trading_activity"),
            "price_elasticity": payload.get("price_elasticity"),
            "current_position": payload.get("current_position"),
        }
    except Exception as exc:
        return {"status": "IMPORT_FAILED", "error": f"{type(exc).__name__}:{exc}"}

readiness = read_json(READINESS)
if readiness.get("version") != "2026-09-12-v8.7.6-readiness-with-ocf-and-20d-elasticity":
    raise SystemExit("READINESS_VERSION_MISMATCH")

score_text = SCORE_DOC.read_text(encoding="utf-8")
required = [
    "2026-07-01-v6.0-score-policy",
    "| 없음 | 9~10점 |",
    "| 주의 | 6~8점 |",
    "| 경계 | 3~5점 |",
    "| 위험 | 0~2점 |",
    "| 85~100점 | 핵심추천 후보 |",
    "| 75~84.9점 | 추천 후보 |",
    "| 65~74.9점 | 관찰 후보 |",
    "| 55~64.9점 | 대기·중립 |",
    "| 0~54.9점 | 주의 |",
]
missing = [x for x in required if x not in score_text]
if missing:
    raise SystemExit("SCORE_POLICY_MARKER_MISSING=" + repr(missing))

hits = scan_candidates()
readiness_map = {row["item"]: row for row in readiness["components"]}
rows = []
candidate_components = []

for item in ALIASES:
    r = readiness_map[item]
    item_hits = hits[item]
    if item_hits:
        policy_status = "RAW_TO_POINT_CANDIDATE_FOUND_REVIEW_REQUIRED"
        candidate_components.append(item)
    else:
        policy_status = "NO_EXPLICIT_RAW_TO_POINT_RULE_FOUND"

    special = ""
    if item == "수급·공시부담":
        special = "V6 range only; exact point inside range not defined"
    elif item == "20일 평균 거래대금과 거래량":
        special = "market label thresholds exist; label-to-0..6 points not defined"
    elif item == "하루평균 절대등락률":
        special = "market label thresholds exist; label-to-0..4 points not defined"
    elif item == "기간 저가·고가 대비 현재위치":
        special = "market label thresholds exist; label-to-0..5 points not defined"

    rows.append({
        "area": r["area"],
        "item": item,
        "max_points": r["max_points"],
        "source_ready_count": r["source_ready_count"],
        "universe_count": r["universe_count"],
        "coverage_pct": r["coverage_pct"],
        "readiness_status": r["status"],
        "raw_to_point_policy_status": policy_status,
        "candidate_hit_count": len(item_hits),
        "special_existing_policy": special,
    })

market = market_policy()
payload = {
    "version": VERSION,
    "generated_at_kst": datetime.now(KST).isoformat(timespec="seconds"),
    "status": "AUDIT_ONLY",
    "readiness_version": readiness.get("version"),
    "basis_date": readiness.get("basis_date"),
    "component_count": len(rows),
    "components": rows,
    "raw_to_point_candidate_component_count": len(candidate_components),
    "raw_to_point_candidate_components": candidate_components,
    "raw_to_point_candidate_evidence": hits,
    "existing_policy_evidence": {
        "area_max_points": readiness.get("area_max_points"),
        "supply_score_ranges": {
            "없음": "9~10",
            "주의": "6~8",
            "경계": "3~5",
            "위험": "0~2",
            "exact_score_inside_range_defined": False,
        },
        "final_score_bands": {
            "85~100": "핵심추천 후보",
            "75~84.9": "추천 후보",
            "65~74.9": "관찰 후보",
            "55~64.9": "대기·중립",
            "0~54.9": "주의",
        },
        "market_metric_label_policy": market,
    },
    "policy_blockers": {
        "raw_value_to_points_thresholds": "NOT_DEFINED",
        "net_cash_debt_scope": "NOT_DEFINED",
        "ev_ebitda_da_policy": "NOT_DEFINED",
        "quarter_acceleration_thresholds": "NOT_DEFINED",
        "supply_exact_subscore_rule": "NOT_DEFINED",
        "market_label_to_component_points": "NOT_DEFINED",
    },
    "hard_guards": {
        "investment_score_100_calculated": False,
        "component_points_calculated": False,
        "new_thresholds_created": False,
        "production_api_changed": False,
    },
    "next_step": "REVIEW_EXISTING_POLICY_EVIDENCE_BEFORE_NEW_THRESHOLDS",
}

OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

fields = list(rows[0].keys())
with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)

log = [
    f"VERSION={VERSION}",
    f"BASIS_DATE={readiness.get('basis_date')}",
    f"COMPONENT_COUNT={len(rows)}",
    f"RAW_TO_POINT_CANDIDATE_COMPONENT_COUNT={len(candidate_components)}",
    f"MARKET_LABEL_POLICY_STATUS={market.get('status')}",
    "RAW_VALUE_TO_POINTS_THRESHOLDS=NOT_DEFINED",
    "NET_CASH_DEBT_SCOPE=NOT_DEFINED",
    "EV_EBITDA_DA_POLICY=NOT_DEFINED",
    "QUARTER_ACCELERATION_THRESHOLDS=NOT_DEFINED",
    "SUPPLY_EXACT_SUBSCORE_RULE=NOT_DEFINED",
    "MARKET_LABEL_TO_COMPONENT_POINTS=NOT_DEFINED",
    "INVESTMENT_SCORE_100_CALCULATED=false",
    "COMPONENT_POINTS_CALCULATED=false",
    "NEW_THRESHOLDS_CREATED=false",
    "PRODUCTION_DATA_CHANGED=false",
    "STATUS=OK",
]
OUT_LOG.write_text("\n".join(log) + "\n", encoding="utf-8")

OUT_DOC.write_text(
    "# V8.7.7 투자종합점수 정책 증거 감사\n\n"
    "새 점수구간을 만들지 않고 저장소 안의 기존 세부 점수화 규칙만 탐색한다.\n\n"
    "확정된 것은 V6 영역 배점, 수급 점수 범위, 최종 총점 판정구간, "
    "거래활발·가격탄력·현재위치 라벨 임계값이다.\n\n"
    "PER·PBR·ROE·부채비율·성장률 등의 원자료→점수 컷, 수급 범위 안의 정확한 점수, "
    "시장 라벨→세부 배점 매핑, EV/EBITDA D&A 범위, 순현금 부채범위, "
    "분기 가속·둔화 점수구간은 이번 감사에서 새로 만들지 않는다.\n",
    encoding="utf-8",
)

print("\n".join(log))
