#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path
from typing import Tuple

ROOT = Path('.')
BUILD = ROOT / 'build_api_json.py'
VALIDATE = ROOT / 'validate_api_sync.py'
RULES = ROOT / 'docs' / 'stock_table_rules_latest.md'


def find_matching(text: str, open_index: int, open_char: str, close_char: str) -> int:
    depth = 0
    quote = None
    triple = False
    escaped = False
    i = open_index
    while i < len(text):
        ch = text[i]
        if quote:
            if escaped:
                escaped = False
            elif ch == '\\':
                escaped = True
            elif triple and text.startswith(quote * 3, i):
                i += 2
                quote = None
                triple = False
            elif not triple and ch == quote:
                quote = None
        else:
            if ch in ("'", '"'):
                if text.startswith(ch * 3, i):
                    quote = ch
                    triple = True
                    i += 2
                else:
                    quote = ch
            elif ch == open_char:
                depth += 1
            elif ch == close_char:
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    raise RuntimeError(f'Unmatched {open_char} at {open_index}')


def table_spec_span(text: str, table_id: str) -> Tuple[int, int]:
    idx = text.find(f'"{table_id}"')
    if idx < 0:
        raise RuntimeError(f'TableSpec not found: {table_id}')
    start = text.rfind('TableSpec(', 0, idx)
    if start < 0:
        raise RuntimeError(f'TableSpec opening not found: {table_id}')
    open_paren = start + len('TableSpec')
    end = find_matching(text, open_paren, '(', ')')
    return start, end + 1


def set_tablespec_bool(text: str, table_id: str, key: str, value: bool) -> str:
    start, end = table_spec_span(text, table_id)
    block = text[start:end]
    desired = 'True' if value else 'False'
    pattern = re.compile(rf'\b{re.escape(key)}\s*=\s*(?:True|False)')
    if pattern.search(block):
        block = pattern.sub(f'{key}={desired}', block)
    else:
        close_line_start = block.rfind('\n', 0, len(block) - 1) + 1
        closing_indent = re.match(r'\s*', block[close_line_start:]).group(0)
        insertion = f'{closing_indent}    {key}={desired},\n'
        block = block[:close_line_start] + insertion + block[close_line_start:]
    return text[:start] + block + text[end:]


def dict_span_after(text: str, marker: str) -> Tuple[int, int]:
    idx = text.find(marker)
    if idx < 0:
        raise RuntimeError(f'Dictionary marker not found: {marker}')
    open_brace = text.find('{', idx)
    end = find_matching(text, open_brace, '{', '}')
    return open_brace, end + 1


def ensure_dict_lines(text: str, marker: str, before_key: str, entries) -> str:
    start, end = dict_span_after(text, marker)
    block = text[start:end]
    missing = [(key, expr) for key, expr in entries if f'"{key}"' not in block]
    if not missing:
        return text
    before_idx = block.find(f'"{before_key}"')
    if before_idx < 0:
        raise RuntimeError(f'Key {before_key} missing after {marker}')
    line_start = block.rfind('\n', 0, before_idx) + 1
    indent = re.match(r'\s*', block[line_start:before_idx]).group(0)
    insertion = ''.join(f'{indent}"{key}": {expr},\n' for key, expr in missing)
    block = block[:line_start] + insertion + block[line_start:]
    return text[:start] + block + text[end:]


def patch_build() -> None:
    text = BUILD.read_text(encoding='utf-8')
    text = re.sub(
        r'SCRIPT_VERSION\s*=\s*"build_api_json\.py [^"]+"',
        'SCRIPT_VERSION = "build_api_json.py v4.1_strict_contract"',
        text,
        count=1,
    )
    text = re.sub(
        r'SCHEMA_VERSION\s*=\s*"[^"]+"',
        'SCHEMA_VERSION = "4.1"',
        text,
        count=1,
    )

    text = set_tablespec_bool(text, 'kospi_monthly_cycle', 'default_output', True)
    text = set_tablespec_bool(text, 'kospi_monthly_cycle', 'explicit_request_only', False)
    text = set_tablespec_bool(text, 'kospi_monthly_cycle_candidates', 'default_output', False)
    text = set_tablespec_bool(text, 'kospi_monthly_cycle_candidates', 'explicit_request_only', True)

    text = ensure_dict_lines(
        text,
        'base: Dict[str, Any] = {',
        'expected_rows',
        [
            ('default_output', 'spec.default_output'),
            ('explicit_request_only', 'spec.explicit_request_only'),
            ('presentation_policy', 'PRESENTATION_POLICY'),
            ('rules_version', 'rules.get("version")'),
            ('rules_sha256', 'rules.get("sha256")'),
        ],
    )

    start = text.find('def snapshot_payload(')
    end = text.find('def main()', start)
    if start < 0 or end < 0:
        raise RuntimeError('snapshot_payload/main boundary not found')
    segment = text[start:end]
    segment = ensure_dict_lines(
        segment,
        'return {',
        'rules',
        [
            ('rules_version', 'rules.get("version")'),
            ('rules_sha256', 'rules.get("sha256")'),
            ('presentation_policy', 'PRESENTATION_POLICY'),
        ],
    )
    text = text[:start] + segment + text[end:]

    text = ensure_dict_lines(
        text,
        'manifest_tables.append({',
        'current_basis_selected',
        [
            ('default_output', 'spec.default_output'),
            ('explicit_request_only', 'spec.explicit_request_only'),
            ('presentation_policy', 'PRESENTATION_POLICY'),
        ],
    )
    text = ensure_dict_lines(
        text,
        'rules_payload = {',
        'content_markdown',
        [('presentation_policy', 'PRESENTATION_POLICY')],
    )
    text = ensure_dict_lines(
        text,
        'status_payload = {',
        'usage_rule',
        [('presentation_policy', 'PRESENTATION_POLICY')],
    )
    text = ensure_dict_lines(
        text,
        'manifest_payload = {',
        'rules',
        [
            ('rules_version', 'rules.get("version")'),
            ('rules_sha256', 'rules.get("sha256")'),
            ('presentation_policy', 'PRESENTATION_POLICY'),
        ],
    )
    BUILD.write_text(text, encoding='utf-8')


def patch_validator() -> None:
    text = VALIDATE.read_text(encoding='utf-8')
    text = re.sub(
        r'SCRIPT_VERSION\s*=\s*"validate_api_sync\.py [^"]+"',
        'SCRIPT_VERSION = "validate_api_sync.py v1.2_strict_contract"',
        text,
        count=1,
    )
    marker = '# STRICT_CONTRACT_V5_BEGIN'
    if marker not in text:
        anchor = '    expected_required = status.get("required_table_count") if status else None'
        if anchor not in text:
            raise RuntimeError('Validator anchor not found')
        block = r'''
    # STRICT_CONTRACT_V5_BEGIN
    if status_policy.get("recommendation_markings_embedded_in_main_table") is not True:
        errors.append("recommendation markings must be embedded in main table")

    rules_version = rules.get("rules_version")
    strict_tables = {}
    for item in manifest_tables:
        if not isinstance(item, dict) or not item.get("api_file"):
            continue
        path = Path(item["api_file"])
        if path.parts and path.parts[0] == api.name:
            path = api.parent / path
        elif not path.is_absolute():
            path = api / path.name
        payload = read_json(path)
        if not payload:
            continue
        table_id = item.get("table_id")
        strict_tables[table_id] = (item, payload)
        if payload.get("rules_version") != rules_version:
            errors.append(f"{table_id}: top-level rules_version mismatch")
        if payload.get("rules_sha256") != rules_hash:
            errors.append(f"{table_id}: top-level rules_sha256 mismatch")
        if payload.get("presentation_policy") != status_policy:
            errors.append(f"{table_id}: presentation_policy mismatch")
        if payload.get("default_output") != item.get("default_output"):
            errors.append(f"{table_id}: default_output mismatch")
        if payload.get("explicit_request_only") != item.get("explicit_request_only"):
            errors.append(f"{table_id}: explicit_request_only mismatch")

    core = strict_tables.get("kospi_monthly_cycle")
    full = strict_tables.get("kospi_monthly_cycle_candidates")
    if core:
        item, payload = core
        if item.get("default_output") is not True or payload.get("default_output") is not True:
            errors.append("kospi_monthly_cycle must be default")
        if item.get("explicit_request_only") is not False or payload.get("explicit_request_only") is not False:
            errors.append("kospi_monthly_cycle explicit flag invalid")
    if full:
        item, payload = full
        if item.get("default_output") is not False or payload.get("default_output") is not False:
            errors.append("kospi_monthly_cycle_candidates must not be default")
        if item.get("explicit_request_only") is not True or payload.get("explicit_request_only") is not True:
            errors.append("kospi_monthly_cycle_candidates must be explicit-only")

    expected_safe = bool(
        status
        and status.get("api_sync_ok")
        and status.get("official_fresh_now")
        and not status.get("critical_errors")
    )
    if status and bool(status.get("safe_to_analyze_as_latest")) != expected_safe:
        errors.append("safe_to_analyze_as_latest strict-gate mismatch")
    # STRICT_CONTRACT_V5_END

'''
        text = text.replace(anchor, block + anchor)
    VALIDATE.write_text(text, encoding='utf-8')


def patch_rules() -> None:
    text = RULES.read_text(encoding='utf-8')
    text = re.sub(
        r'(규칙 버전\s*[:：]\s*)[0-9A-Za-z._-]+',
        r'\g<1>2026-06-30-v5-strict-contract',
        text,
        count=1,
    )
    marker = '## v5 엄격 계약 보강'
    if marker not in text:
        text = text.rstrip() + '''

---

## v5 엄격 계약 보강

- `api_sync_ok=false` 또는 `critical_errors` 존재 시 표를 만들지 않는다.
- `official_fresh_now=true`, `safe_to_analyze_as_latest=false` 조합도 표 작성을 중단한다.
- 공식자료 지연은 API 동기화가 정상이고 `confirmed_basis_date`가 있을 때만 제한 분석한다.
- 모든 본표 JSON은 최상위에 `rules_version`, `rules_sha256`,
  `presentation_policy`, `default_output`, `explicit_request_only`를 포함한다.
- `kospi_monthly_cycle`은 기본 월사이클표다.
- `kospi_monthly_cycle_candidates`는 내부 저장용이며
  `default_output=false`, `explicit_request_only=true`로 고정한다.
'''
    RULES.write_text(text.rstrip() + '\n', encoding='utf-8')


def main() -> int:
    for path in (BUILD, VALIDATE, RULES):
        if not path.exists():
            raise FileNotFoundError(path)
    patch_build()
    patch_validator()
    patch_rules()
    print('PATCH_V5_STRICT_CONTRACT=APPLIED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
