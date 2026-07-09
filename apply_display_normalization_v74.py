#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Apply V7.4 display normalization to compact watchlist APIs."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

CONTRACT_VERSION = "2026-07-09-v7.4-display-normalization"

TARGETS: Tuple[Dict[str, Any], ...] = (
    {
        "filename": "kospi_watchlist.json",
        "table_id": "kospi_watchlist",
        "expected_rows": 30,
        "max_payload_bytes": 70000,
    },
    {
        "filename": "kosdaq_watchlist.json",
        "table_id": "kosdaq_watchlist",
        "expected_rows": 10,
        "max_payload_bytes": 50000,
    },
    {
        "filename": "us_watchlist.json",
        "table_id": "us_watchlist",
        "expected_rows": 30,
        "max_payload_bytes": 110000,
    },
)

KEYWORD_FIELDS = (
    "supply_burden_keywords",
    "수급부담키워드",
    "수급부담 키워드",
)

ALIAS_MAP = {
    "cb": "CB",
    "cb발행": "CB",
    "전환사채": "CB",
    "전환사채발행": "CB",
    "bw": "BW",
    "bw발행": "BW",
    "신주인수권부사채": "BW",
    "신주인수권부사채발행": "BW",
    "eb": "EB",
    "eb발행": "EB",
    "교환사채": "EB",
    "교환사채발행": "EB",
}

PREFERRED_ORDER = (
    "감자",
    "유상증자",
    "CB",
    "BW",
    "EB",
    "전환청구",
    "신주인수권",
    "보호예수",
    "블록딜",
    "자사주처분",
    "최대주주변경",
    "대량보유",
    "주요주주변동",
)

TOKEN_SPLIT_RE = re.compile(r"\s*(?:[,;/|]|·)\s*")
DISPLAY_MARK_RE = re.compile(r"[-_✅🟡⚪\s]+")


class DisplayNormalizationError(RuntimeError):
    pass


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise DisplayNormalizationError(f"필수 API 누락: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise DisplayNormalizationError(f"JSON 읽기 실패: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DisplayNormalizationError(f"JSON 최상위 객체 오류: {path}")
    return value


def write_json(path: Path, payload: Mapping[str, Any]) -> int:
    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def normalize_alias_key(token: str) -> str:
    return re.sub(r"[\s._-]+", "", token).lower()


def tokenize_keywords(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw_tokens: List[str] = []
        for item in value:
            raw_tokens.extend(tokenize_keywords(item))
        return raw_tokens

    text = clean_text(value)
    if not text:
        return []

    # Also split common duplicated display forms such as CB/CB발행.
    return [
        token.strip()
        for token in TOKEN_SPLIT_RE.split(text)
        if token and token.strip()
    ]


def canonical_keyword(token: str) -> Optional[str]:
    cleaned = token.strip()
    if not cleaned:
        return None
    return ALIAS_MAP.get(normalize_alias_key(cleaned), cleaned)


def normalize_keywords(value: Any) -> List[str]:
    normalized: List[str] = []
    seen = set()

    for token in tokenize_keywords(value):
        canonical = canonical_keyword(token)
        if not canonical:
            continue
        key = normalize_alias_key(canonical)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(canonical)

    order_map = {value: index for index, value in enumerate(PREFERRED_ORDER)}
    indexed = list(enumerate(normalized))
    indexed.sort(
        key=lambda item: (
            order_map.get(item[1], len(PREFERRED_ORDER)),
            item[0],
        )
    )
    return [value for _, value in indexed]


def get_keywords(row: Mapping[str, Any]) -> Tuple[Optional[str], List[str]]:
    for field in KEYWORD_FIELDS:
        if field in row:
            return field, normalize_keywords(row.get(field))
    return None, []


def recommendation_icon(row: Mapping[str, Any]) -> str:
    current = clean_text(row.get("recommendation_display")) or ""
    if "✅" in current:
        return "✅"
    if "🟡" in current:
        return "🟡"
    if "⚪" in current:
        return "⚪"
    # Default compact candidate rows that are not priority picks are watch items.
    return "🟡"


def canonical_recommendation_display(row: Mapping[str, Any]) -> str:
    name = (
        clean_text(row.get("name"))
        or clean_text(row.get("종목명"))
        or DISPLAY_MARK_RE.sub(
            "",
            clean_text(row.get("recommendation_display")) or "",
        ).strip()
        or "종목명 미제공"
    )
    operating_loss = bool(row.get("operating_loss"))
    supply_burden = bool(row.get("supply_burden"))
    left = "-" if operating_loss else ""
    icon = recommendation_icon(row)
    right = "_" if supply_burden else ""
    return f"{left}{icon}{right} {name}"


def supply_display(row: Mapping[str, Any], keywords: Sequence[str]) -> str:
    level = clean_text(row.get("supply_burden_level"))
    burden = bool(row.get("supply_burden"))
    if not burden:
        return "없음"

    normalized_level = level if level and level != "없음" else "주의"
    if not keywords:
        return normalized_level
    return f"{normalized_level} · {'·'.join(keywords)}"


def ensure_column(payload: MutableMapping[str, Any], field: str) -> None:
    columns = payload.get("columns")
    if isinstance(columns, list) and field not in columns:
        columns.append(field)


def patch_row(row: MutableMapping[str, Any]) -> Dict[str, Any]:
    original_display = clean_text(row.get("recommendation_display"))
    normalized_display = canonical_recommendation_display(row)
    row["recommendation_display"] = normalized_display

    field, keywords = get_keywords(row)
    if field is None:
        # Keep the compact contract uniform even when a market has no keywords.
        field = "supply_burden_keywords"

    normalized_keyword_text = ",".join(keywords) if keywords else None
    row[field] = normalized_keyword_text
    if field != "supply_burden_keywords":
        row["supply_burden_keywords"] = normalized_keyword_text

    row["supply_burden_display"] = supply_display(row, keywords)

    return {
        "recommendation_changed": original_display != normalized_display,
        "keyword_count": len(keywords),
        "keywords": keywords,
    }


def update_output_contract(payload: MutableMapping[str, Any]) -> None:
    contract = payload.get("output_contract")
    if not isinstance(contract, dict):
        contract = {}
        payload["output_contract"] = contract

    contract.update(
        {
            "version": CONTRACT_VERSION,
            "recommendation_column_label": "추천/종목",
            "recommendation_display_field": "recommendation_display",
            "show_rank_numbers_default": False,
            "rank_field_use": "sorting_only",
            "do_not_prefix_rank_to_recommendation": True,
            "loss_marker_position": "left_of_recommendation_icon",
            "supply_marker_position": "right_of_recommendation_icon",
            "supply_burden_display_field": "supply_burden_display",
            "supply_burden_keywords_field": "supply_burden_keywords",
            "supply_keyword_separator": "·",
            "supply_keyword_alias_policy": {
                "CB발행": "CB",
                "BW발행": "BW",
                "EB발행": "EB",
                "duplicate_aliases": "remove_preserve_meaning",
            },
        }
    )

    preferred = payload.get("preferred_column_labels")
    if not isinstance(preferred, dict):
        preferred = {}
        payload["preferred_column_labels"] = preferred
    preferred["recommendation"] = "추천/종목"
    preferred["supply_burden"] = "수급부담"


def update_presentation_policy(payload: MutableMapping[str, Any]) -> None:
    policy = payload.get("presentation_policy")
    if not isinstance(policy, dict):
        policy = {}
        payload["presentation_policy"] = policy

    policy.update(
        {
            "recommendation_column_label": "추천/종목",
            "show_rank_numbers_default": False,
            "rank_field_use": "sorting_only",
            "supply_keyword_alias_deduplication": True,
            "supply_keyword_display_separator": "·",
        }
    )


def apply_one(api_dir: Path, target: Mapping[str, Any]) -> Dict[str, Any]:
    path = api_dir / str(target["filename"])
    payload = read_json(path)
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise DisplayNormalizationError(f"{path}: rows 형식 오류")

    expected_rows = int(target["expected_rows"])
    if len(rows) != expected_rows:
        raise DisplayNormalizationError(
            f"{path}: 행 수 불일치 {len(rows)} != {expected_rows}"
        )

    recommendation_changes = 0
    normalized_keyword_rows = 0
    duplicate_aliases_remaining: List[Dict[str, Any]] = []

    for index, raw in enumerate(rows, start=1):
        if not isinstance(raw, MutableMapping):
            raise DisplayNormalizationError(f"{path}: {index}행 객체 형식 오류")
        stats = patch_row(raw)
        recommendation_changes += int(stats["recommendation_changed"])
        normalized_keyword_rows += int(bool(stats["keywords"]))

        text = clean_text(raw.get("supply_burden_keywords")) or ""
        if re.search(r"(?i)(?:CB,CB발행|BW,BW발행|EB,EB발행)", text):
            duplicate_aliases_remaining.append(
                {"row": index, "value": text}
            )

    if duplicate_aliases_remaining:
        raise DisplayNormalizationError(
            f"{path}: 중복 별칭 잔존 {duplicate_aliases_remaining}"
        )

    ensure_column(payload, "supply_burden_display")
    ensure_column(payload, "supply_burden_keywords")
    update_output_contract(payload)
    update_presentation_policy(payload)

    payload["display_contract_version"] = CONTRACT_VERSION
    payload["display_normalization"] = {
        "version": CONTRACT_VERSION,
        "status": "OK",
        "rank_numbers_default": False,
        "rank_preserved_for_sorting": True,
        "recommendation_display_changes": recommendation_changes,
        "normalized_keyword_rows": normalized_keyword_rows,
        "supply_aliases_deduplicated": True,
    }

    max_bytes = int(target["max_payload_bytes"])
    payload["payload_size_limit_bytes"] = max_bytes
    compact_policy = payload.get("compact_response_policy")
    if isinstance(compact_policy, dict):
        compact_policy["display_normalization_version"] = CONTRACT_VERSION
        compact_policy["max_payload_bytes"] = max_bytes

    size = write_json(path, payload)
    payload["payload_size_bytes"] = size
    size = write_json(path, payload)

    if size > max_bytes:
        raise DisplayNormalizationError(
            f"{path}: 응답 크기 초과 {size} > {max_bytes}"
        )

    return {
        "table_id": target["table_id"],
        "api_file": f"api/{target['filename']}",
        "row_count": len(rows),
        "recommendation_display_changes": recommendation_changes,
        "normalized_keyword_rows": normalized_keyword_rows,
        "payload_size_bytes": size,
        "payload_size_limit_bytes": max_bytes,
    }


def update_manifest_status(
    api_dir: Path,
    entries: Sequence[Mapping[str, Any]],
) -> None:
    entry_map = {str(item["table_id"]): item for item in entries}

    manifest_path = api_dir / "manifest.json"
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        tables = manifest.get("tables")
        if isinstance(tables, list):
            for item in tables:
                if not isinstance(item, MutableMapping):
                    continue
                table_id = str(item.get("table_id") or "")
                if table_id in entry_map:
                    item.update(
                        {
                            "display_contract_version": CONTRACT_VERSION,
                            "rank_numbers_default": False,
                            "display_normalization_status": "OK",
                        }
                    )

        manifest["display_normalization"] = {
            "version": CONTRACT_VERSION,
            "status": "OK",
            "show_rank_numbers_default": False,
            "rank_field_use": "sorting_only",
            "supply_aliases_deduplicated": True,
            "entries": list(entries),
        }
        write_json(manifest_path, manifest)

    status_path = api_dir / "status.json"
    if status_path.exists():
        status = read_json(status_path)
        status["display_normalization"] = {
            "version": CONTRACT_VERSION,
            "status": "OK",
            "show_rank_numbers_default": False,
            "supply_aliases_deduplicated": True,
        }
        policy = status.get("presentation_policy")
        if not isinstance(policy, dict):
            policy = {}
            status["presentation_policy"] = policy
        policy.update(
            {
                "recommendation_column_label": "추천/종목",
                "show_rank_numbers_default": False,
                "rank_field_use": "sorting_only",
                "supply_keyword_alias_deduplication": True,
                "supply_keyword_display_separator": "·",
            }
        )
        write_json(status_path, status)


def apply_display_normalization(api_dir: Path) -> List[Dict[str, Any]]:
    entries = [apply_one(api_dir, target) for target in TARGETS]
    update_manifest_status(api_dir, entries)
    return entries


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-dir", default="api")
    args = parser.parse_args()

    entries = apply_display_normalization(Path(args.api_dir))
    print("DISPLAY_NORMALIZATION_V74=PASS")
    for item in entries:
        print(
            f"{item['table_id']}="
            f"{item['row_count']}:"
            f"{item['payload_size_bytes']}/"
            f"{item['payload_size_limit_bytes']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
