"""Read-only checks for the Action, instruction and generated route contract."""
import argparse
import json
from pathlib import Path

import yaml

from table_command_routes_v82 import ACTION_OPERATION_IDS
from two_table_release_v853 import (
    VERSION, INSTRUCTIONS_VERSION, SCHEMA_VERSION, DISPLAY, command_routes,
    validate_bundle,
)


def validate(repo):
    repo = Path(repo)
    schema = yaml.safe_load((repo / "docs/custom_gpt_action_schema.yaml").read_text())
    assert schema["openapi"] == "3.1.0"
    assert str(schema["info"]["version"]) == SCHEMA_VERSION
    assert schema["servers"] == [{"url": "https://krx-live-price-ksh.diaconos.workers.dev"}]
    operations = {}
    for path, entry in schema["paths"].items():
        for method, op in entry.items():
            if not isinstance(op, dict) or "operationId" not in op:
                continue
            assert method == "get", "Read-only Action methods required"
            assert op["operationId"] not in operations
            operations[op["operationId"]] = (path, op)
            for key in ("summary", "description"):
                assert len(op.get(key, "")) <= 300, (op["operationId"], key)
            for param in op.get("parameters", []):
                assert len(param.get("description", "")) <= 700
    assert set(operations) == ACTION_OPERATION_IDS
    path, op = operations["getKospiWatchlist"]
    assert path == "/tables/v1/{table}"
    params = {p["name"]: p for p in op["parameters"]}
    assert set(params) == {"table", "page", "build_id"}
    assert params["table"]["required"] is True
    assert params["table"]["in"] == "path"
    assert params["table"]["schema"]["enum"] == ["kospi", "decliners", "decliners24"]
    assert op["responses"]["200"]["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/TwoTablePage"}
    assert "/sehwankim0114/krx-watchlist-auto/main/api/kospi_watchlist.json" not in schema["paths"]
    text = (repo / "docs/custom_gpt_instructions.md").read_text()
    assert len(text) <= 8000, len(text)
    for token in (INSTRUCTIONS_VERSION, VERSION, "table=kospi", "table=decliners", "table=decliners24",
                  "source_build_id", "page_count", "total_rows", "구형 점수를 환산", "독립 스윙분석표는 보류",
                  "추천 아이콘은 각 본표 행 전체에서 정확히 1개만 사용한다.",
                  "getStockReferenceShard를 prefix만으로 호출하지 않는다."):
        assert token in text, token
    manifest = json.loads((repo / "api/manifest.json").read_text())
    extension = manifest["command_route_contract"]["two_table_release"]
    assert extension["routes"] == command_routes()
    assert extension["effective_command_count"] == 15
    assert extension["additional_command_count"] == 2
    rule = json.loads((repo / "api/stock_table_rules.json").read_text())
    assert VERSION in json.dumps(rule, ensure_ascii=False)
    bundle = validate_bundle(repo / "api/two_table_v1", repo)
    response_schema = schema["components"]["schemas"]["TwoTablePage"]
    # Check our specific compact-array schema without an extra CI dependency.
    row_schema = response_schema["properties"]["rows"]["items"]
    assert row_schema == {"type": "array", "minItems": 14, "maxItems": 14, "items": {}}
    assert response_schema["properties"]["transport"]["properties"]["mode"]["enum"] == ["production"]
    checked = 0
    for name in bundle["files"]:
        if ".compact." not in name:
            continue
        payload = json.loads((repo / "api/two_table_v1" / name).read_text())
        assert payload["display_contract"] == DISPLAY
        # Only production READY responses are Action output; stale bundles are
        # structurally valid publications but the Worker must refuse them.
        if bundle["status"] == "READY":
            sample = {**payload, "transport": {"mode": "production", "next_page_url": None}}
            assert set(response_schema["required"]).issubset(sample)
            assert sample["status"] == "READY"
            assert all(isinstance(row, list) and len(row) == 14 for row in sample["rows"])
            assert isinstance(sample["source_build_id"], str)
            assert isinstance(sample["page"], int) and not isinstance(sample["page"], bool)
        assert len(payload["headers"]) == 19
        checked += 1
    print("V853_CLIENT_CONTRACT=PASS")
    print("V853_ACTION_OPERATION_COUNT=30")
    print("V853_EFFECTIVE_COMMAND_COUNT=15")
    print("V853_INSTRUCTIONS_CHARACTERS=" + str(len(text)))
    print("V853_TYPED_COMPACT_PAGES=" + str(checked))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent)
    validate(parser.parse_args().repo)
