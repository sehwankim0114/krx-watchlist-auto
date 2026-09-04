import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createHash, webcrypto } from "node:crypto";

const repo = process.argv[2];
assert.ok(repo, "Repository path is required");
const workerSource = fs.readFileSync(path.join(repo, "worker/krx-live-price-worker.js"), "utf8");
const apiManifest = JSON.parse(fs.readFileSync(path.join(repo, "api/two_table_v1/manifest.json")));
const baseline = new Map();
for (const name of ["api/status.json", "config/krx_market_holidays.json", "api/two_table_v1/manifest.json",
  ...Object.keys(apiManifest.files).map(n => `api/two_table_v1/${n}`)]) {
  baseline.set(name, fs.readFileSync(path.join(repo, name)));
}
const status = JSON.parse(baseline.get("api/status.json"));
const fixtureNow = status.runtime_freshness_gate.evaluated_at_kst;
assert.equal(status.api_sync_ok, true);
assert.equal(status.official_fresh_now, true, "Integration fixture must have freshly synchronized source data");
let cases = 0;

function setup() {
  const state = { files: new Map(baseline), calls: [], hook: null, now: fixtureNow };
  class Clock extends Date {
    constructor(...args) { super(...(args.length ? args : [state.now])); }
    static now() { return new Date(state.now).getTime(); }
  }
  const fakeFetch = async resource => {
    const u = new URL(String(resource));
    assert.ok(["raw.githubusercontent.com", "api.github.com"].includes(u.hostname));
    const name = u.hostname === "raw.githubusercontent.com"
      ? u.pathname.replace("/sehwankim0114/krx-watchlist-auto/main/", "")
      : u.pathname.replace("/repos/sehwankim0114/krx-watchlist-auto/contents/", "");
    state.calls.push({ host: u.hostname, name });
    if (state.hook) {
      const result = await state.hook({ u, name, count: state.calls.filter(c => c.name === name).length });
      if (result !== undefined) return result;
    }
    return state.files.has(name) ? new Response(state.files.get(name)) : new Response("missing", { status: 404 });
  };
  const code = workerSource.replace("export default {", "const worker = {");
  const load = new Function("fetch", "Date", "crypto", `${code}\nreturn {worker, expectedTwoTableDate, verifyTwoTableControl};`);
  const loaded = load(fakeFetch, Clock, webcrypto);
  state.request = async (suffix = "/tables/v1/kospi?mode=preview", method = "GET") => {
    const response = await loaded.worker.fetch(new Request("https://worker.invalid" + suffix, { method }));
    const raw = await response.text();
    return { response, raw, payload: raw ? JSON.parse(raw) : null };
  };
  state.calendar = loaded.expectedTwoTableDate;
  state.update = (name, callback, rehash = false) => {
    const p = JSON.parse(state.files.get(name)); callback(p);
    const bytes = Buffer.from(JSON.stringify(p)); state.files.set(name, bytes);
    if (rehash) state.update("api/two_table_v1/manifest.json", m => {
      m.files[name.replace("api/two_table_v1/", "")] = {
        bytes: bytes.length, sha256: createHash("sha256").update(bytes).digest("hex"),
      };
    });
  };
  return state;
}

async function test(name, run) {
  await run(setup()); cases += 1; console.log(`PASS ${name}`);
}
function rejected(result, code, http = 409) {
  assert.equal(result.response.status, http, result.raw);
  assert.equal(result.payload.error, code, result.raw);
  assert.deepEqual(result.payload.rows, []);
  assert.equal(result.payload.safe_to_analyze_as_latest, false);
  assert.equal(result.response.headers.get("Cache-Control"), "no-store");
}

await test("health advertises guarded routes without activating them", async s => {
  const r = await s.request("/health");
  assert.equal(r.payload.build_version, "1.4.0-two-table-guarded-preview");
  assert.equal(r.payload.two_table_proxy.paths.length, 3);
  assert.equal(r.payload.two_table_proxy.standalone_swing_table_enabled, false);
  assert.equal(s.calls.length, 0);
});
await test("default production requests reject inactive datasets", async s => {
  rejected(await s.request("/tables/v1/kospi"), "TWO_TABLE_NOT_ACTIVATED");
  assert.ok(!s.calls.some(c => c.name.includes(".compact.")));
});
await test("all real pages preserve exact arrays and complete row coverage", async s => {
  for (const table of ["kospi", "decliners", "decliners24"]) {
    const entry = apiManifest.tables[table]; const collected = [];
    let next = `/tables/v1/${table}?mode=preview&page=1`;
    for (const name of entry.pages) {
      const r = await s.request(next);
      assert.equal(r.response.status, 200, r.raw);
      assert.ok(Buffer.byteLength(r.raw) <= 30000);
      assert.equal(r.response.headers.get("Cache-Control"), "no-store");
      const source = JSON.parse(baseline.get("api/two_table_v1/" + name));
      const { transport, ...original } = r.payload;
      assert.deepEqual(original, source);
      assert.equal(transport.values_recalculated, false);
      assert.equal(transport.request_time_prices_applied, false);
      assert.equal(r.payload.production_activation_allowed, false);
      assert.equal(r.payload.safe_to_analyze_as_latest, false);
      collected.push(...r.payload.rows);
      next = transport.next_page_url;
    }
    assert.equal(next, null);
    assert.equal(collected.length, entry.row_count);
    assert.equal(new Set(collected.map(r => r[1])).size, collected.length);
    console.log(`V852_COMPLETE_ROWS=${table}|${collected.length}`);
  }
});
await test("invalid and duplicate query fields rejected before fetching", async s => {
  for (const q of ["page=0", "page=-1", "page=1.5", "page=01", "page=101", "page=1&page=2", "mode=preview&mode=production", "url=https://evil.invalid", "build_id=", "mode=auto"]) {
    const r = await s.request("/tables/v1/kospi?" + q);
    assert.equal(r.response.status, 400, q);
  }
  assert.equal(s.calls.length, 0);
});
await test("unknown table and standalone swing are not routes", async s => {
  for (const name of ["swing", "../status", "kospi.json", "kospi/extra"]) {
    assert.equal((await s.request("/tables/v1/" + name)).response.status, 404);
  }
  assert.equal(s.calls.length, 0);
});
await test("raw nested path cannot bypass guarded route", async s => {
  const r = await s.request("/sehwankim0114/krx-watchlist-auto/main/api/two_table_v1/kospi.json");
  assert.equal(r.response.status, 400);
  assert.equal(s.calls.length, 0);
});
await test("later pages require explicit source build pin", async s => {
  rejected(await s.request("/tables/v1/decliners?mode=preview&page=2"), "TWO_TABLE_BUILD_ID_REQUIRED_FOR_NEXT_PAGE", 400);
  assert.equal(s.calls.length, 0);
});
await test("out of range pages rejected", async s => {
  rejected(await s.request(`/tables/v1/kospi?mode=preview&page=2&build_id=${encodeURIComponent(apiManifest.source_build_id)}`),
    "TWO_TABLE_PAGE_OUT_OF_RANGE", 400);
});
await test("old pinned build cannot mix consecutive pages", async s => {
  rejected(await s.request("/tables/v1/decliners?mode=preview&page=2&build_id=old-build"), "TWO_TABLE_BUILD_CHANGED_RESTART_PAGE_1");
});
await test("all three source freshness gates required", async s => {
  s.update("api/status.json", p => { p.safe_to_analyze_as_latest = false; });
  rejected(await s.request(), "TWO_TABLE_OFFICIAL_DATA_NOT_FRESH");
});
await test("nested runtime freshness gate also required", async s => {
  s.update("api/status.json", p => { p.runtime_freshness_gate.official_fresh_now = false; });
  rejected(await s.request(), "TWO_TABLE_OFFICIAL_DATA_NOT_FRESH");
});
await test("critical upstream error blocks transport", async s => {
  s.update("api/status.json", p => { p.critical_errors = ["fixture"]; });
  rejected(await s.request(), "TWO_TABLE_SOURCE_NOT_SYNCHRONIZED");
});
await test("stale dates rejected even when stored booleans falsely say fresh", async s => {
  s.now = "2026-09-08T10:00:00+09:00";
  rejected(await s.request(), "TWO_TABLE_OFFICIAL_DATE_INVALID_OR_STALE");
});
await test("unprovided future-year calendar fails closed", async s => {
  s.now = "2027-01-05T10:00:00+09:00";
  rejected(await s.request(), "TWO_TABLE_CALENDAR_COVERAGE_MISSING", 503);
});
await test("repository 08:30, weekend and holiday rules", async s => {
  const calendar = JSON.parse(baseline.get("config/krx_market_holidays.json"));
  for (const [when, expected] of [
    ["2026-09-04T08:29:59+09:00", "2026-09-02"],
    ["2026-09-04T08:30:00+09:00", "2026-09-03"],
    ["2026-09-05T10:00:00+09:00", "2026-09-04"],
    ["2026-09-07T10:00:00+09:00", "2026-09-04"],
    ["2026-09-28T10:00:00+09:00", "2026-09-23"],
  ]) assert.equal(s.calendar(new Date(when), calendar), expected);
});
await test("missing calendar never defaults to weekdays", async s => {
  s.files.delete("config/krx_market_holidays.json");
  rejected(await s.request(), "TWO_TABLE_SOURCE_UNAVAILABLE", 503);
});
await test("build and rule mismatch rejected", async s => {
  s.update("api/two_table_v1/manifest.json", p => { p.source_rules_sha256 = "wrong"; });
  rejected(await s.request(), "TWO_TABLE_SOURCE_IDENTITY_MISMATCH");
});
await test("page bytes must match manifest SHA256", async s => {
  s.files.set("api/two_table_v1/kospi.compact.1.json", Buffer.concat([s.files.get("api/two_table_v1/kospi.compact.1.json"), Buffer.from(" ")]));
  rejected(await s.request(), "TWO_TABLE_PAGE_CHECKSUM_MISMATCH");
});
await test("semantic identity checked even with matching checksum", async s => {
  s.update("api/two_table_v1/kospi.compact.1.json", p => { p.source_build_id = "wrong"; }, true);
  rejected(await s.request(), "TWO_TABLE_PAGE_IDENTITY_MISMATCH");
});
await test("incomplete rows rejected even with matching checksum", async s => {
  s.update("api/two_table_v1/kospi.compact.1.json", p => { p.rows.pop(); p.row_count -= 1; }, true);
  rejected(await s.request(), "TWO_TABLE_PAGE_ROW_COUNT_MISMATCH");
});
await test("duplicate exact tickers rejected even with matching checksum", async s => {
  s.update("api/two_table_v1/kospi.compact.1.json", p => { p.rows[1][1] = p.rows[0][1]; }, true);
  rejected(await s.request(), "TWO_TABLE_DUPLICATE_TICKER");
});
await test("column mapping cannot silently change", async s => {
  s.update("api/two_table_v1/kospi.compact.1.json", p => { p.columns.reverse(); }, true);
  rejected(await s.request(), "TWO_TABLE_COLUMNS_MISMATCH");
});
await test("manifest cannot redirect fetch to arbitrary file", async s => {
  s.update("api/two_table_v1/manifest.json", p => { p.tables.kospi.pages = ["../../secret.json"]; });
  rejected(await s.request(), "TWO_TABLE_PAGE_LIST_INVALID");
});
await test("manifest change during fetch prevents mixed snapshots", async s => {
  s.hook = ({ name, count }) => {
    if (name === "api/two_table_v1/manifest.json" && count === 2) s.update(name, p => { p.version += "-changed"; });
  };
  rejected(await s.request(), "TWO_TABLE_MANIFEST_CHANGED_RETRY");
});
await test("status change during fetch cannot return stale rows", async s => {
  s.hook = ({ name, count }) => {
    if (name === "api/status.json" && count === 2) s.update(name, p => { p.build_id += "-changed"; });
  };
  rejected(await s.request(), "TWO_TABLE_SOURCE_IDENTITY_MISMATCH");
});
await test("calendar change during fetch forces retry", async s => {
  s.hook = ({ name, count }) => {
    if (name === "config/krx_market_holidays.json" && count === 2) s.update(name, p => { p.updated_at = "changed"; });
  };
  rejected(await s.request(), "TWO_TABLE_CALENDAR_CHANGED_RETRY");
});
await test("primary network error uses configured GitHub fallback", async s => {
  s.hook = ({ u }) => { if (u.hostname === "raw.githubusercontent.com") throw new Error("simulated timeout"); };
  const r = await s.request(); assert.equal(r.response.status, 200, r.raw);
  assert.equal(s.calls.filter(c => c.host === "api.github.com").length, 7);
});
await test("primary 503 uses configured GitHub fallback", async s => {
  s.hook = ({ u }) => u.hostname === "raw.githubusercontent.com" ? new Response("busy", { status: 503 }) : undefined;
  assert.equal((await s.request()).response.status, 200);
});
await test("all upstream fetch failures return no rows or error-body leakage", async s => {
  s.hook = () => { throw new Error("sensitive upstream text"); };
  const r = await s.request(); rejected(r, "TWO_TABLE_SOURCE_FETCH_FAILED", 503);
  assert.ok(!r.raw.includes("sensitive"));
});
await test("malformed JSON blocks without using old cached table", async s => {
  s.files.set("api/status.json", Buffer.from("not JSON"));
  rejected(await s.request(), "TWO_TABLE_SOURCE_INVALID_JSON", 502);
});
await test("oversized upstream body is bounded before parsing", async s => {
  s.files.set("api/two_table_v1/kospi.compact.1.json", Buffer.alloc(30001, "x"));
  rejected(await s.request(), "TWO_TABLE_SOURCE_TOO_LARGE", 502);
});
await test("final response size includes added transport metadata", async s => {
  const name = "api/two_table_v1/kospi.compact.1.json";
  s.update(name, p => { p.padding = ""; p.padding = "x".repeat(29990 - Buffer.byteLength(JSON.stringify(p))); }, true);
  rejected(await s.request(), "TWO_TABLE_RESPONSE_TOO_LARGE", 502);
});
await test("unsupported HTTP methods still reject", async s => {
  assert.equal((await s.request("/tables/v1/kospi?mode=preview", "POST")).response.status, 405);
  assert.equal(s.calls.length, 0);
});
await test("partial activation cannot bypass calculation preview contract", async s => {
  const activate = p => Object.assign(p, { production_activation_allowed: true, custom_gpt_route_enabled: true,
    safe_to_analyze_as_latest: true, release_stage: "PRODUCTION", status: "READY" });
  s.update("api/two_table_v1/manifest.json", activate);
  s.update("api/two_table_v1/kospi.compact.1.json", activate, true);
  rejected(await s.request("/tables/v1/kospi"), "TWO_TABLE_CALCULATION_STAGE_MISMATCH");
});
await test("only fully explicit synthetic activation enables production mode", async s => {
  const activate = p => Object.assign(p, { production_activation_allowed: true, custom_gpt_route_enabled: true,
    safe_to_analyze_as_latest: true, release_stage: "PRODUCTION", status: "READY" });
  s.update("api/two_table_v1/manifest.json", activate);
  s.update("api/two_table_v1/kospi.compact.1.json", p => {
    activate(p); p.contract.release_stage = "PRODUCTION";
  }, true);
  const r = await s.request("/tables/v1/kospi");
  assert.equal(r.response.status, 200, r.raw);
  assert.equal(r.payload.transport.mode, "production");
  assert.equal(r.payload.safe_to_analyze_as_latest, true);
  assert.equal(apiManifest.production_activation_allowed, false, "Real dataset was never activated");
});
await test("zero matches return one explicit empty page", async s => {
  s.update("api/two_table_v1/manifest.json", p => { p.tables.decliners24.row_count = 0; });
  s.update("api/two_table_v1/decliners24.compact.1.json", p => { p.rows = []; p.row_count = 0; p.total_rows = 0; }, true);
  const r = await s.request("/tables/v1/decliners24?mode=preview");
  assert.equal(r.response.status, 200, r.raw);
  assert.deepEqual(r.payload.rows, []);
  assert.equal(r.payload.transport.next_page_url, null);
});

console.log(`V852_WORKER_GUARD_TEST_COUNT=${cases}`);
console.log("V852_TWO_TABLE_WORKER_CONTRACT=PASS");
console.log("V852_ALL_PAGES_UNDER_30000=PASS");
console.log("V852_NO_PRODUCTION_ACTIVATION=PASS");
console.log("V852_EXISTING_RAW_NESTED_PATH_BLOCKED=PASS");
