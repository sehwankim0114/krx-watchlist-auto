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
  `${executableSource}\nreturn { compactManifestPayload, compactWatchlistPayload, compactUsWatchlistPayload, compactTablePayload, isCompactTablePath, parseStockReferenceQuery, filterStockReferencePayload, __worker_default__ };`,
);
const {
  compactManifestPayload,
  compactWatchlistPayload,
  compactUsWatchlistPayload,
  compactTablePayload,
  isCompactTablePath,
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
assert.ok(usSourceBytes > 80000, `Unexpected US source size: ${usSourceBytes}`);
assert.ok(usCompactBytes < 45000, `US compact response too large: ${usCompactBytes}`);
assert.ok(usCompactBytes < usSourceBytes / 2);

const compactTableFiles = [
  "kospi_watchlist.json",
  "kosdaq_watchlist.json",
  "kospi_1m_candidates_30.json",
  "kosdaq_1m_candidates_10.json",
  "kospi_gainers_1m.json",
  "kospi_monthly_cycle.json",
  "kospi_fx_weakness_candidates_30.json",
  "kospi_short_term_candidates_30.json",
  "kospi_candidates_30.json",
  "kosdaq_candidates_10.json",
];
const compactTablePayloads = new Map();
const compactTableSizes = new Map();

assert.equal(compactTableFiles.length, 10);
assert.equal(isCompactTablePath("market_status.json"), false);

for (const filename of compactTableFiles) {
  assert.equal(isCompactTablePath(filename), true, filename);
  const source = readApi(filename);
  const sourceBefore = JSON.stringify(source);
  const compact = compactTablePayload(source, filename);

  assert.equal(compact.table_id, source.table_id, filename);
  assert.equal(compact.status, source.status, filename);
  assert.equal(compact.build_id, source.build_id, filename);
  assert.equal(compact.rules_version, source.rules_version, filename);
  assert.equal(compact.row_count, source.row_count, filename);
  assert.equal(compact.returned_row_count, source.rows.length, filename);
  assert.equal(compact.row_count_ok, true, filename);
  assert.equal(compact.compact_response.mode, "COMPACT_FOR_CUSTOM_GPT");
  assert.equal(compact.compact_response.source_path, filename);
  assert.equal(compact.compact_response.rows_preserved, true);
  assert.equal(compact.compact_response.values_recalculated, false);
  assert.equal(JSON.stringify(source), sourceBefore, filename);

  for (let index = 0; index < compact.rows.length; index += 1) {
    const sourceRow = source.rows[index];
    const compactRow = compact.rows[index];
    assert.equal(compactRow.name, sourceRow.name, `${filename}.${index}`);
    assert.equal(compactRow.code, sourceRow.code, `${filename}.${index}`);
    for (const [key, value] of Object.entries(compactRow)) {
      assert.ok(
        Object.prototype.hasOwnProperty.call(sourceRow, key),
        `${filename}.${index}.${key}`,
      );
      assert.deepEqual(
        value,
        sourceRow[key],
        `${filename}.${index}.${key}`,
      );
    }
  }

  const compactBytes = Buffer.byteLength(JSON.stringify(compact), "utf8");
  assert.ok(
    compactBytes < 45000,
    `${filename} compact response too large: ${compactBytes}`,
  );
  compactTablePayloads.set(filename, compact);
  compactTableSizes.set(filename, compactBytes);
}

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
assert.equal(health.build_version, "1.3.7-table-response-compact");
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
assert.equal(
  health.github_proxy_policy.table_response_mode,
  "COMPACT_FOR_CUSTOM_GPT",
);
assert.equal(health.github_proxy_policy.table_rows_preserved, true);
assert.equal(health.github_proxy_policy.table_values_recalculated, false);
assert.equal(health.github_proxy_policy.compact_table_path_count, 10);

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

globalThis.fetch = async (resource) => {
  const upstreamUrl = new URL(String(resource));
  assert.match(upstreamUrl.hostname, /githubusercontent\.com$/);
  const filename = upstreamUrl.pathname.split("/").at(-1);
  assert.ok(compactTablePayloads.has(filename), filename);
  return new Response(JSON.stringify(readApi(filename), null, 2), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
};

for (const filename of compactTableFiles) {
  cachedResponse = null;
  const response = await __worker_default__.fetch(
    new Request(
      "https://krx-live-price-ksh.diaconos.workers.dev/" +
        `sehwankim0114/krx-watchlist-auto/main/api/${filename}`,
    ),
  );
  assert.equal(response.status, 200, filename);
  assert.equal(
    response.headers.get("X-GitHub-Proxy-Transform"),
    "COMPACT_TABLE_V1",
    filename,
  );
  assert.equal(
    response.headers.get("X-Compact-Table-Path"),
    filename,
  );
  assert.equal(
    response.headers.get("X-Table-Rows-Preserved"),
    "true",
  );
  assert.equal(
    response.headers.get("X-Table-Values-Recalculated"),
    "false",
  );
  assert.deepEqual(
    await response.json(),
    compactTablePayloads.get(filename),
    filename,
  );
  assert.ok(cachedResponse instanceof Response, filename);
}
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
console.log("COMPACT_TABLE_PATH_COUNT=10");
for (const filename of compactTableFiles) {
  console.log(
    `COMPACT_TABLE_BYTES=${filename}|${compactTableSizes.get(filename)}`,
  );
}
console.log("ALL_COMPACT_TABLE_RESPONSES_UNDER_45000=PASS");
console.log("COMPACT_TABLE_ROW_ORDER_PRESERVED=PASS");
console.log("COMPACT_TABLE_VALUES_RECALCULATED=false");
console.log("COMPACT_TABLE_PROXY_INTEGRATION=PASS");
console.log("WORKER_V137_VALIDATION=PASS");
