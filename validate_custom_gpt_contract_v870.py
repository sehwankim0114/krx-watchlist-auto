"""Check that the published V8.7 bundle still matches the Custom GPT source files."""

import argparse
import json
from pathlib import Path

import yaml

from sector_rs_source_v870 import NEW_COLUMNS
from table_command_routes_v82 import ACTION_OPERATION_IDS, WORKER_ORIGIN
from two_table_release_v870 import (
    DISPLAY,
    SCHEMA_VERSION,
    VERSION,
    glossary_contract,
    validate_bundle,
)


def require(condition, label):
    if not condition:
        raise ValueError("V870_GPT_CONTRACT_" + label)


def validate(repo):
    repo = Path(repo)
    schema = yaml.safe_load(
        (repo / "docs/custom_gpt_action_schema.yaml").read_text(encoding="utf-8")
    )
    require(schema.get("openapi") == "3.1.0", "OPENAPI_VERSION")
    require(str(schema["info"]["version"]) == SCHEMA_VERSION, "SCHEMA_VERSION")
    require(schema["servers"] == [{"url": WORKER_ORIGIN}], "ACTION_DOMAIN")

    operations = {}
    for path, entry in schema["paths"].items():
        for method, action in entry.items():
            if not isinstance(action, dict) or "operationId" not in action:
                continue
            operation_id = action["operationId"]
            require(method == "get", "READ_ONLY_ACTION")
            require(operation_id not in operations, "DUPLICATE_OPERATION")
            operations[operation_id] = (path, action)
    require(set(operations) == ACTION_OPERATION_IDS, "ACTION_OPERATION_SET")

    path, action = operations["getKospiWatchlist"]
    require(path == "/tables/v1/{table}", "TWO_TABLE_PATH")
    params = {p["name"]: p for p in action["parameters"]}
    require(set(params) == {"table", "page", "build_id"}, "TWO_TABLE_PARAMS")
    require(
        params["table"]["schema"]["enum"] == ["kospi", "decliners", "decliners24"],
        "TABLE_ENUM",
    )
    require(
        action["responses"]["200"]["content"]["application/json"]["schema"]
        == {"$ref": "#/components/schemas/TwoTablePage"},
        "TWO_TABLE_RESPONSE",
    )
    page_schema = schema["components"]["schemas"]["TwoTablePage"]
    row_schema = page_schema["properties"]["rows"]["items"]
    # The Action parser accepts the older shape; GPT instructions reject it.
    require(row_schema["minItems"] == 14 and row_schema["maxItems"] == 15, "ROW_SCHEMA")
    require(
        page_schema["properties"]["transport"]["properties"]["mode"]["enum"]
        == ["production"],
        "PRODUCTION_TRANSPORT",
    )

    instructions = (repo / "docs/custom_gpt_instructions.md").read_text(
        encoding="utf-8"
    )
    require(len(instructions) <= 8000, "INSTRUCTIONS_TOO_LONG")
    for token in (
        VERSION,
        "15개 묶음열",
        "14열 V1은 계약 불일치로 중단",
        "rs_sector_pp",
        "source_build_id",
        "source_rules_sha256",
        "getKospiWatchlist(table=kospi)",
        "table=decliners",
        "table=decliners24",
        "metric_glossary_footer",
        "가격만으로 ✅ 승격하지 않는다",
        "현재가",
    ):
        require(token in instructions, "INSTRUCTIONS_MISSING:" + token)

    api_manifest = json.loads(
        (repo / "api/manifest.json").read_text(encoding="utf-8")
    )
    routes = api_manifest["command_route_contract"]["two_table_release"]
    require(routes["effective_command_count"] == 15, "COMMAND_COUNT")
    require(routes["additional_command_count"] == 2, "ADDITIONAL_COMMAND_COUNT")

    status = json.loads((repo / "api/status.json").read_text(encoding="utf-8"))
    bundle = validate_bundle(repo / "api/two_table_v1", repo)
    glossary = glossary_contract(repo)
    require(bundle["version"] == VERSION, "BUNDLE_VERSION")
    checked = 0
    for table in ("kospi", "decliners", "decliners24"):
        pages = bundle["tables"][table]["pages"]
        require(bool(pages), "MISSING_PAGE:" + table)
        for name in pages:
            payload = json.loads(
                (repo / "api/two_table_v1" / name).read_text(encoding="utf-8")
            )
            require(payload["table_id"] == table, "TABLE_ID:" + name)
            require(payload["columns"] == NEW_COLUMNS, "COLUMNS:" + name)
            require(
                all(len(row) == len(NEW_COLUMNS) for row in payload["rows"]),
                "ROW_WIDTH:" + name,
            )
            require(payload["display_contract"] == DISPLAY, "DISPLAY:" + name)
            require(
                payload["source_build_id"] == status["build_id"],
                "SOURCE_BUILD:" + name,
            )
            require(
                payload["source_rules_sha256"] == status["rules_sha256"],
                "RULES_HASH:" + name,
            )
            require(
                payload["metric_glossary_version"] == glossary["version"]
                and payload["metric_glossary_footer"] == glossary["footer"],
                "GLOSSARY:" + name,
            )
            if payload["status"] == "READY":
                response = {
                    **payload,
                    "transport": {"mode": "production", "next_page_url": None},
                }
                require(
                    set(page_schema["required"]).issubset(response),
                    "ACTION_FIELDS:" + name,
                )
            checked += 1

    print("V870_GPT_CONTRACT=PASS")
    print("V870_GPT_ACTION_OPERATION_COUNT=" + str(len(operations)))
    print("V870_GPT_INSTRUCTIONS_CHARACTERS=" + str(len(instructions)))
    print("V870_GPT_COMPACT_PAGES=" + str(checked))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent)
    validate(parser.parse_args().repo)
