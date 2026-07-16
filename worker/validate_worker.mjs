import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const repo = process.argv[2];
if (!repo) {
  throw new Error("Repository path argument is required");
}

const workerPath = new URL(
  "./krx-live-price-worker.js",
  import.meta.url,
);
const workerSource = fs.readFileSync(workerPath, "utf8");
const readApi = (name) =>
  JSON.parse(fs.readFileSync(path.join(repo, "api", name), "utf8"));

const manifest = readApi("manifest.json");
const status = readApi("status.json");
const watchlist = readApi("watchlist.json");
const usWatchlist = readApi("us_watchlist.json");
const shard00 = readApi("stock_reference_shards/00.json");

const executableSource = workerSource.replace(
  "export default {",
  "const __worker_default__ = {",
);
assert.notEqual(executableSource, workerSource, "Worker export was not found");

const loadWorker = new Function(
  `${executableSource}\nreturn { compactManifestPayload, compactWatchlistPayload, compactUsWatchlistPayload, parseStockReferenceQuery, filterStockReferencePayload, __worker_default__ };`,
);
const {
  compactManifestPayload,
  compactWatchlistPayload,
  compactUsWatchlistPayload,
  parseStockReferenceQuery,
  filterStockReferencePayload,
  __worker_default__,
} = loadWorker();

const compactManifest = compactManifestPayload(manifest, status);
assert.equal(compactManifest.command_route_contract.command_count, 13);
assert.equal(compactManifest.command_route_contract.ready_count, 13);
assert.equal(
  compactManifest.command_route_contract.actual_output_available_count,
  13,
);
assert.equal(compactManifest.command_route_contract.structure_ok, true);

const compactWatchlist = compactWatchlistPayload(watchlist);
assert.equal(compactWatchlist.table_id, "watchlist");
assert.equal(compactWatchlist.row_count, 47);
assert.equal(compactWatchlist.returned_row_count, 47);
assert.equal(compactWatchlist.row_count_ok, true);
assert.equal(compactWatchlist.compact_response.rows_preserved, true);
assert.equal(compactWatchlist.compact_response.values_recalculated, false);

const usBefore = JSON.stringify(usWatchlist);
const compactUs = compactUsWatchlistPayload(usWatchlist);
assert.equal(compactUs.table_id, "us_watchlist");
assert.equal(compactUs.status, "OK");
assert.equal(compactUs.row_count, 30);
assert.equal(compactUs.returned_row_count, 30);
assert.equal(compactUs.row_count_ok, true);
assert.equal(compactUs.build_id, usWatchlist.build_id);
assert.equal(compactUs.rules_version, usWatchlist.rules_version);
assert.equal(compactUs.compact_response.mode, "COMPACT_FOR_CUSTOM_GPT");
assert.equal(compactUs.compact_response.source_row_count, 30);
assert.equal(compactUs.compact_response.rows_preserved, true);
assert.equal(compactUs.compact_response.values_recalculated, false);
assert.equal(JSON.stringify(usWatchlist), usBefore, "Source payload changed");

const allowedUsRowKeys = new Set([
  "name",
  "symbol",
  "market",
  "recommendation_display",
  "hard_red_flag",
  "supply_burden_display",
  "current_price",
  "value_buy_low",
  "value_buy_high",
  "value_buy_range_markdown",
  "target1_low",
  "target1_high",
  "first_sell_target_range_markdown",
  "low_3m",
  "high_3m",
  "position_in_3m_range_pct",
  "position_label",
  "return_1m_pct",
  "avg_volume_20d",
  "avg_trading_value_20d",
  "liquidity_label",
  "avg_daily_range_amount",
  "avg_daily_range_pct",
  "fundamentals_status",
  "return_on_equity",
  "debt_to_equity",
  "price_to_book",
  "valuation_growth",
  "earnings_event_risk",
  "next_earnings_date",
  "short_percent_float",
  "score",
  "score_recommendation_reason",
  "sector_theme",
  "warning_count",
]);

for (let index = 0; index < compactUs.rows.length; index += 1) {
  const sourceRow = usWatchlist.rows[index];
  const compactRow = compactUs.rows[index];
  assert.equal(compactRow.name, sourceRow.name);
  assert.equal(compactRow.symbol, sourceRow.symbol);
  assert.equal(compactRow.current_price, sourceRow.current_price);
  assert.equal(
    compactRow.recommendation_display,
    sourceRow.recommendation_display,
  );
  for (const [key, value] of Object.entries(compactRow)) {
    assert.ok(allowedUsRowKeys.has(key), `Unexpected US compact key: ${key}`);
    assert.notEqual(value, null, `Null US compact value: ${index}.${key}`);
    assert.deepEqual(value, sourceRow[key], `US value changed: ${index}.${key}`);
  }
}

const usSourceBytes = Buffer.byteLength(JSON.stringify(usWatchlist), "utf8");
const usCompactBytes = Buffer.byteLength(JSON.stringify(compactUs), "utf8");
assert.ok(usCompactBytes < 45000, `US compact response too large: ${usCompactBytes}`);
assert.ok(usCompactBytes < usSourceBytes);

const query = parseStockReferenceQuery(
  "stock_reference_shards/00.json",
  new URLSearchParams("ticker=005930&market=KOSPI"),
);
const filtered = filterStockReferencePayload(shard00, query);
assert.equal(filtered.status, "OK");
assert.equal(filtered.returned_row_count, 1);
assert.equal(filtered.exact_match, true);
assert.equal(filtered.contains_user_holdings, false);
assert.equal(filtered.values_recalculated, false);
assert.equal(filtered.rows[0].ticker, "005930");

const healthResponse = await __worker_default__.fetch(
  new Request("https://example.invalid/health"),
);
const health = await healthResponse.json();
assert.equal(health.status, "OK");
assert.equal(health.build_version, "1.3.6-us-watchlist-compact");
assert.equal(
  health.github_proxy_policy.us_watchlist_response_mode,
  "COMPACT_FOR_CUSTOM_GPT",
);
assert.equal(health.github_proxy_policy.us_watchlist_rows_preserved, true);
assert.equal(
  health.github_proxy_policy.us_watchlist_values_recalculated,
  false,
);
assert.equal(
  health.github_proxy_policy.stock_reference_response_mode,
  "EXACT_TICKER_FILTER",
);

const originalFetch = globalThis.fetch;
let cachedResponse = null;
globalThis.caches = {
  default: {
    match: async () => undefined,
    put: async (_key, response) => {
      cachedResponse = response;
    },
  },
};
globalThis.fetch = async (resource) => {
  assert.match(String(resource), /raw\.githubusercontent\.com/);
  assert.match(String(resource), /us_watchlist\.json$/);
  return new Response(JSON.stringify(usWatchlist, null, 2), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
};

const proxyResponse = await __worker_default__.fetch(
  new Request(
    "https://krx-live-price-ksh.diaconos.workers.dev/" +
      "sehwankim0114/krx-watchlist-auto/main/api/us_watchlist.json",
  ),
);
assert.equal(proxyResponse.status, 200);
assert.equal(
  proxyResponse.headers.get("X-GitHub-Proxy-Transform"),
  "COMPACT_US_WATCHLIST_V1",
);
assert.equal(
  proxyResponse.headers.get("X-US-Watchlist-Rows-Preserved"),
  "true",
);
assert.equal(
  proxyResponse.headers.get("X-US-Watchlist-Values-Recalculated"),
  "false",
);
const proxyUs = await proxyResponse.json();
assert.deepEqual(proxyUs, compactUs);
assert.ok(cachedResponse instanceof Response);
globalThis.fetch = originalFetch;

console.log("WORKER_JS_SYNTAX_AND_HEALTH=PASS");
console.log("MANIFEST_COMMAND_ROUTE_CONTRACT_REGRESSION=PASS");
console.log("WATCHLIST_COMPACT_REGRESSION=PASS");
console.log("STOCK_REFERENCE_FILTER_REGRESSION=PASS");
console.log("US_WATCHLIST_PROXY_INTEGRATION=PASS");
console.log("US_WATCHLIST_SOURCE_ROWS=30");
console.log("US_WATCHLIST_RETURNED_ROWS=30");
console.log("US_WATCHLIST_ROW_ORDER_PRESERVED=PASS");
console.log("US_WATCHLIST_VALUES_RECALCULATED=false");
console.log(`US_WATCHLIST_SOURCE_MINIFIED_BYTES=${usSourceBytes}`);
console.log(`US_WATCHLIST_COMPACT_BYTES=${usCompactBytes}`);
console.log("US_WATCHLIST_RESPONSE_SIZE_UNDER_45000=PASS");
console.log("WORKER_V136_VALIDATION=PASS");
