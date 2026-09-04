/**
 * KRX / US request-time quote + GitHub JSON proxy Worker
 *
 * Compatibility contract:
 * - GET /health
 * - GET /quotes?items=005930|KOSPI,000660|KOSPI
 * - GET /quotes?items=GOOGL|USA,AMZN|USA
 * - GET /sehwankim0114/krx-watchlist-auto/main/api/status.json
 *
 * Domestic stocks: NAVER mobile stock JSON
 * US stocks: Yahoo Finance chart JSON
 *
 * Important:
 * - US prices are regular-market prices only.
 * - After-hours prices are not reflected.
 * - Failed quotes are never replaced with fabricated prices.
 */

const SERVICE_VERSION = "1.2.0";
const BUILD_VERSION = "1.4.0-two-table-guarded-preview";
const MAX_ITEMS = 50;
const FETCH_TIMEOUT_MS = 8000;
const CONCURRENCY = 4;

const GITHUB_PROXY_PREFIX =
  "/sehwankim0114/krx-watchlist-auto/main/api/";
const GITHUB_RAW_BASE =
  "https://raw.githubusercontent.com/sehwankim0114/krx-watchlist-auto/main/api/";
const GITHUB_API_BASE =
  "https://api.github.com/repos/sehwankim0114/krx-watchlist-auto/contents/api/";
const GITHUB_PROXY_CACHE_TTL_SECONDS = 120;
const GITHUB_PROXY_PRIMARY_FETCH_TIMEOUT_MS = 6000;
const GITHUB_PROXY_FALLBACK_FETCH_TIMEOUT_MS = 6000;

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET,OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
  "Cache-Control": "no-store",
};

export default {
  async fetch(request) {
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: CORS_HEADERS,
      });
    }

    if (request.method !== "GET") {
      return jsonResponse(
        {
          status: "ERROR",
          error: "METHOD_NOT_ALLOWED",
          message: "Only GET is supported.",
        },
        405,
      );
    }

    const url = new URL(request.url);

    if (url.pathname === "/" || url.pathname === "/health") {
      return jsonResponse({
        status: "OK",
        service: "krx-live-price",
        version: SERVICE_VERSION,
        build_version: BUILD_VERSION,
        max_items: MAX_ITEMS,
        endpoints: [
          "/health",
          "/quotes?items=KEY|MARKET,...",
          `${GITHUB_PROXY_PREFIX}status.json`,
          `${GITHUB_PROXY_PREFIX}stock_table_rules.json`,
          `${GITHUB_PROXY_PREFIX}manifest.json`,
          `${GITHUB_PROXY_PREFIX}us_watchlist.json`,
          "/tables/v1/kospi?mode=preview&page=1",
          "/tables/v1/decliners?mode=preview&page=1",
          "/tables/v1/decliners24?mode=preview&page=1",
        ],
        providers: {
          KR: "NAVER_STOCK_MOBILE",
          US: "YAHOO_FINANCE_CHART",
          GITHUB_JSON_PRIMARY: "RAW_GITHUB",
          GITHUB_JSON_FALLBACK: "GITHUB_CONTENTS_API",
        },
        github_proxy_policy: {
          repository: "sehwankim0114/krx-watchlist-auto",
          branch: "main",
          api_prefix: GITHUB_PROXY_PREFIX,
          edge_cache_ttl_seconds: GITHUB_PROXY_CACHE_TTL_SECONDS,
          fallback_on_429_or_5xx: true,
          fallback_on_primary_fetch_error: true,
          primary_fetch_timeout_ms:
            GITHUB_PROXY_PRIMARY_FETCH_TIMEOUT_MS,
          fallback_fetch_timeout_ms:
            GITHUB_PROXY_FALLBACK_FETCH_TIMEOUT_MS,
          manifest_response_mode: "COMPACT_FOR_CUSTOM_GPT",
          manifest_source_preserved: true,
          manifest_freshness_merge: "status.json",
          manifest_command_route_contract_preserved: true,
          watchlist_response_mode: "COMPACT_FOR_CUSTOM_GPT",
          watchlist_rows_preserved: true,
          us_watchlist_response_mode: "COMPACT_FOR_CUSTOM_GPT",
          us_watchlist_rows_preserved: true,
          us_watchlist_values_recalculated: false,
          table_response_mode: "COMPACT_FOR_CUSTOM_GPT",
          table_rows_preserved: true,
          table_values_recalculated: false,
          compact_table_path_count: 10,
          kospi_watchlist_response_profile: "KOSPI_ACTION_V2",
          kospi_watchlist_max_bytes: 30000,
          kospi_watchlist_static_position_omitted: true,
          stock_reference_response_mode: "EXACT_TICKER_FILTER",
          stock_reference_ticker_required: true,
          stock_reference_user_holdings_stored: false,
        },
        us_price_policy: {
          price_type: "regular_market_price",
          after_hours_reflected: false,
          fallback_to_fake_price: false,
        },
        two_table_proxy: {
          version: "1",
          paths: ["/tables/v1/kospi", "/tables/v1/decliners", "/tables/v1/decliners24"],
          source_directory: "api/two_table_v1",
          default_mode: "production_requires_explicit_dataset_activation",
          preview_requires_mode_parameter: true,
          page_limit_bytes: 30000,
          page_limit_rows: 30,
          cache_mode: "NO_STORE_CONTROL_RECHECK",
          sha256_required: true,
          later_pages_require_build_id: true,
          calendar_rule: "REPOSITORY_KRX_CALENDAR_0830_KST",
          standalone_swing_table_enabled: false,
          values_recalculated: false,
        },
        generated_at: new Date().toISOString(),
      });
    }

    if (url.pathname.startsWith("/tables/")) {
      return handleTwoTableRequest(url);
    }

    if (url.pathname.startsWith(GITHUB_PROXY_PREFIX)) {
      return handleGitHubJsonProxy(request, url);
    }

    if (url.pathname !== "/quotes") {
      return jsonResponse(
        {
          status: "ERROR",
          error: "NOT_FOUND",
          message:
            "Use /health, /quotes, or the configured GitHub API proxy prefix.",
        },
        404,
      );
    }

    const rawItems = url.searchParams.get("items") || "";
    const parsed = parseItems(rawItems);

    if (parsed.error) {
      return jsonResponse(
        {
          status: "ERROR",
          error: parsed.error,
          message: parsed.message,
          requested_count: 0,
          ok_count: 0,
          failed_count: 0,
          quotes: [],
        },
        400,
      );
    }

    const requestStartedAt = new Date().toISOString();
    const quotes = await mapWithConcurrency(
      parsed.items,
      CONCURRENCY,
      fetchQuote,
    );
    const requestFinishedAt = new Date().toISOString();

    const okCount = quotes.filter((row) => row.ok).length;
    const failedCount = quotes.length - okCount;
    const status =
      failedCount === 0 ? "OK" : okCount === 0 ? "ERROR" : "PARTIAL";

    const providerSummary = {};
    for (const row of quotes) {
      const key = row.source || "NONE";
      providerSummary[key] = (providerSummary[key] || 0) + 1;
    }

    return jsonResponse({
      status,
      service: "krx-live-price",
      version: SERVICE_VERSION,
      build_version: BUILD_VERSION,
      request_started_at: requestStartedAt,
      request_finished_at: requestFinishedAt,
      generated_at: requestFinishedAt,
      requested_count: quotes.length,
      ok_count: okCount,
      failed_count: failedCount,
      provider_summary: providerSummary,
      after_hours_reflected: false,
      source_notice:
        "Domestic quotes use NAVER auxiliary data. " +
        "US quotes use Yahoo Finance chart auxiliary data. " +
        "US after-hours prices are not reflected.",
      quotes,
      failures: quotes
        .filter((row) => !row.ok)
        .map((row) => ({
          quote_key: row.quote_key,
          market: row.market,
          error_code: row.error_code,
          error: row.error,
        })),
    });
  },
};

// TWO_TABLE_GUARDED_PROXY_V852_BEGIN
// This is a transport contract. No price, score, indicator or recommendation
// is recomputed here. Shadow data can be read only with explicit mode=preview.
const TWO_TABLE_PATHS = new Map([
  ["/tables/v1/kospi", "kospi"],
  ["/tables/v1/decliners", "decliners"],
  ["/tables/v1/decliners24", "decliners24"],
]);
const TWO_TABLE_COLUMNS = ["name", "ticker", "official_close", "run", "streak",
  "range_3m", "swing", "ma", "returns", "rs_kospi_pp", "atr14", "activity",
  "analysis", "sector_theme"];
const TWO_TABLE_MAX_BYTES = 30000;
const TWO_TABLE_MAX_CONTROL_BYTES = 64000;

class TwoTableError extends Error {
  constructor(code, status = 409) {
    super(code);
    this.status = status;
  }
}

function twoTableRequire(condition, code, status = 409) {
  if (!condition) throw new TwoTableError(code, status);
}

function parseTwoTableQuery(url) {
  const table = TWO_TABLE_PATHS.get(url.pathname);
  twoTableRequire(Boolean(table), "TWO_TABLE_NOT_FOUND", 404);
  const allowed = new Set(["page", "mode", "build_id"]);
  const seen = new Set();
  for (const [key] of url.searchParams) {
    twoTableRequire(allowed.has(key) && !seen.has(key), "TWO_TABLE_INVALID_QUERY", 400);
    seen.add(key);
  }
  const rawPage = url.searchParams.get("page") ?? "1";
  twoTableRequire(/^[1-9][0-9]{0,2}$/.test(rawPage), "TWO_TABLE_INVALID_PAGE", 400);
  const page = Number(rawPage);
  twoTableRequire(page <= 100, "TWO_TABLE_INVALID_PAGE", 400);
  const mode = url.searchParams.get("mode") ?? "production";
  twoTableRequire(["preview", "production"].includes(mode), "TWO_TABLE_INVALID_MODE", 400);
  const buildId = url.searchParams.get("build_id");
  twoTableRequire(buildId === null || /^[A-Za-z0-9:+_-]{1,128}$/.test(buildId), "TWO_TABLE_INVALID_BUILD_ID", 400);
  twoTableRequire(page === 1 || buildId !== null, "TWO_TABLE_BUILD_ID_REQUIRED_FOR_NEXT_PAGE", 400);
  return { table, page, mode, buildId };
}

async function readTwoTableSource(relativePath, maxBytes) {
  // Callers construct paths from constants and validated numeric page indexes.
  twoTableRequire(/^(?:api\/(?:status\.json|two_table_v1\/(?:manifest|(?:kospi|decliners|decliners24)\.compact\.[1-9][0-9]*)\.json)|config\/krx_market_holidays\.json)$/.test(relativePath),
    "TWO_TABLE_INTERNAL_PATH_INVALID", 500);
  const root = "sehwankim0114/krx-watchlist-auto";
  const urls = [
    `https://raw.githubusercontent.com/${root}/main/${relativePath}`,
    `https://api.github.com/repos/${root}/contents/${relativePath}?ref=main`,
  ];
  for (let attempt = 0; attempt < urls.length; attempt += 1) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch(urls[attempt], {
        signal: controller.signal,
        headers: {
          Accept: attempt ? "application/vnd.github.raw+json" : "application/json",
          "User-Agent": "krx-watchlist-two-table/1.4.0",
          "Cache-Control": "no-cache, no-store",
          "X-GitHub-Api-Version": "2022-11-28",
        },
        cf: { cacheTtl: 0, cacheEverything: false },
      });
      if (!response.ok) {
        await response.body?.cancel();
        if (attempt === 0 && shouldUseGitHubApiFallback(response.status)) continue;
        throw new TwoTableError("TWO_TABLE_SOURCE_UNAVAILABLE", 503);
      }
      const reader = response.body?.getReader();
      twoTableRequire(Boolean(reader), "TWO_TABLE_EMPTY_SOURCE", 502);
      let size = 0;
      const chunks = [];
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > maxBytes) {
          await reader.cancel();
          throw new TwoTableError("TWO_TABLE_SOURCE_TOO_LARGE", 502);
        }
        chunks.push(value);
      }
      const raw = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) { raw.set(chunk, offset); offset += chunk.byteLength; }
      let payload;
      try { payload = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw)); }
      catch { throw new TwoTableError("TWO_TABLE_SOURCE_INVALID_JSON", 502); }
      twoTableRequire(payload !== null && typeof payload === "object" && !Array.isArray(payload),
        "TWO_TABLE_SOURCE_INVALID_OBJECT", 502);
      return { raw, payload };
    } catch (error) {
      if (error instanceof TwoTableError) throw error;
      if (attempt === 1) throw new TwoTableError("TWO_TABLE_SOURCE_FETCH_FAILED", 503);
    } finally {
      clearTimeout(timeout);
      controller.abort();
    }
  }
  throw new TwoTableError("TWO_TABLE_SOURCE_UNAVAILABLE", 503);
}

function validTwoTableDate(value) {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)
    && Number.isFinite(Date.parse(`${value}T00:00:00Z`))
    && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value;
}

function expectedTwoTableDate(now, calendar) {
  const kst = new Date(now.getTime() + 9 * 3600000);
  twoTableRequire(calendar.calendar === "KRX" && calendar.year === kst.getUTCFullYear()
    && Array.isArray(calendar.holidays), "TWO_TABLE_CALENDAR_COVERAGE_MISSING", 503);
  const holidays = new Set(calendar.holidays.map(item => typeof item === "string" ? item : item?.date));
  twoTableRequire([...holidays].every(validTwoTableDate), "TWO_TABLE_CALENDAR_INVALID", 503);
  const cutoffReached = kst.getUTCHours() * 60 + kst.getUTCMinutes() >= 510;
  const cursor = new Date(Date.UTC(kst.getUTCFullYear(), kst.getUTCMonth(), kst.getUTCDate()));
  cursor.setUTCDate(cursor.getUTCDate() - (cutoffReached ? 1 : 2));
  for (let tries = 0; tries < 30; tries += 1) {
    // Do not guess holidays across an unprovided calendar year.
    twoTableRequire(cursor.getUTCFullYear() === calendar.year, "TWO_TABLE_CALENDAR_COVERAGE_MISSING", 503);
    const day = cursor.toISOString().slice(0, 10);
    if (cursor.getUTCDay() !== 0 && cursor.getUTCDay() !== 6 && !holidays.has(day)) return day;
    cursor.setUTCDate(cursor.getUTCDate() - 1);
  }
  throw new TwoTableError("TWO_TABLE_CALENDAR_INVALID", 503);
}

function verifyTwoTableControl(status, manifest, calendar, query, now = new Date()) {
  twoTableRequire(status.api_sync_ok === true && (!status.critical_errors || status.critical_errors.length === 0),
    "TWO_TABLE_SOURCE_NOT_SYNCHRONIZED");
  const gate = status.runtime_freshness_gate;
  twoTableRequire(status.official_fresh_now === true && status.safe_to_analyze_as_latest === true
    && gate?.api_sync_ok === true && gate.official_fresh_now === true && gate.safe_to_analyze_as_latest === true,
    "TWO_TABLE_OFFICIAL_DATA_NOT_FRESH");
  const expected = expectedTwoTableDate(now, calendar);
  const basis = status.confirmed_basis_date;
  const kst = new Date(now.getTime() + 9 * 3600000);
  twoTableRequire(validTwoTableDate(basis) && basis >= expected
    && basis <= kst.toISOString().slice(0, 10)
    && status.kospi_actual_date === basis && status.kosdaq_actual_date === basis,
    "TWO_TABLE_OFFICIAL_DATE_INVALID_OR_STALE");
  twoTableRequire(basis !== kst.toISOString().slice(0, 10)
    || kst.getUTCHours() * 60 + kst.getUTCMinutes() >= 930, "TWO_TABLE_TODAY_BAR_NOT_CONFIRMED");
  for (const [source, main] of [["source_build_id", "build_id"], ["source_rules_version", "rules_version"],
    ["source_rules_sha256", "rules_sha256"], ["basis_date", "confirmed_basis_date"]]) {
    twoTableRequire(typeof status[main] === "string" && status[main].length > 0
      && manifest[source] === status[main], "TWO_TABLE_SOURCE_IDENTITY_MISMATCH");
  }
  twoTableRequire(query.buildId === null || query.buildId === manifest.source_build_id, "TWO_TABLE_BUILD_CHANGED_RESTART_PAGE_1");
  twoTableRequire(manifest.standalone_swing_table_enabled === false, "TWO_TABLE_UNSUPPORTED_SWING_ACTIVATION");
  if (query.mode === "production") {
    twoTableRequire(manifest.production_activation_allowed === true && manifest.custom_gpt_route_enabled === true
      && manifest.safe_to_analyze_as_latest === true && manifest.release_stage === "PRODUCTION"
      && manifest.status === "READY", "TWO_TABLE_NOT_ACTIVATED");
  } else {
    twoTableRequire(manifest.production_activation_allowed === false && manifest.custom_gpt_route_enabled === false
      && manifest.safe_to_analyze_as_latest === false && manifest.release_stage === "SCHEDULED_SHADOW_ONLY"
      && ["SHADOW_READY", "SHADOW_STALE"].includes(manifest.status), "TWO_TABLE_PREVIEW_STAGE_MISMATCH");
  }
  twoTableRequire(typeof manifest.version === "string" && manifest.version.length > 0,
    "TWO_TABLE_CONTRACT_VERSION_MISSING");
  const entry = manifest.tables?.[query.table];
  twoTableRequire(entry && Number.isInteger(entry.row_count) && entry.row_count >= 0 && entry.row_count <= 3000
    && Array.isArray(entry.pages), "TWO_TABLE_MANIFEST_TABLE_INVALID");
  const pageCount = Math.max(1, Math.ceil(entry.row_count / 30));
  const names = Array.from({ length: pageCount }, (_, i) => `${query.table}.compact.${i + 1}.json`);
  twoTableRequire(JSON.stringify(entry.pages) === JSON.stringify(names), "TWO_TABLE_PAGE_LIST_INVALID");
  twoTableRequire(query.table !== "kospi" || entry.row_count === 30, "TWO_TABLE_KOSPI_NOT_30");
  twoTableRequire(query.page <= pageCount, "TWO_TABLE_PAGE_OUT_OF_RANGE", 400);
  const name = names[query.page - 1];
  const info = manifest.files?.[name];
  twoTableRequire(info && Number.isInteger(info.bytes) && info.bytes > 0 && info.bytes <= TWO_TABLE_MAX_BYTES
    && typeof info.sha256 === "string" && /^[a-f0-9]{64}$/.test(info.sha256), "TWO_TABLE_PAGE_INTEGRITY_MISSING");
  return { name, info, entry, pageCount, expected };
}

async function twoTableDigest(bytes) {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map(n => n.toString(16).padStart(2, "0")).join("");
}

async function verifyTwoTablePage(source, manifest, query, control) {
  twoTableRequire(source.raw.byteLength === control.info.bytes
    && await twoTableDigest(source.raw) === control.info.sha256, "TWO_TABLE_PAGE_CHECKSUM_MISMATCH");
  const p = source.payload;
  for (const key of ["source_build_id", "source_rules_version", "source_rules_sha256", "basis_date", "version",
    "release_stage", "production_activation_allowed", "custom_gpt_route_enabled", "safe_to_analyze_as_latest",
    "standalone_swing_table_enabled", "status"]) {
    twoTableRequire(p[key] === manifest[key], "TWO_TABLE_PAGE_IDENTITY_MISMATCH");
  }
  twoTableRequire(p.contract?.release_stage === (query.mode === "preview" ? "PREVIEW_ONLY" : "PRODUCTION")
    && p.contract.standalone_swing_table_enabled === false, "TWO_TABLE_CALCULATION_STAGE_MISMATCH");
  const expectedRows = Math.min(30, Math.max(0, control.entry.row_count - (query.page - 1) * 30));
  twoTableRequire(p.table_id === query.table && p.page === query.page && p.page_count === control.pageCount
    && p.total_rows === control.entry.row_count && Array.isArray(p.rows)
    && p.row_count === expectedRows && p.rows.length === expectedRows, "TWO_TABLE_PAGE_ROW_COUNT_MISMATCH");
  twoTableRequire(JSON.stringify(p.columns) === JSON.stringify(TWO_TABLE_COLUMNS), "TWO_TABLE_COLUMNS_MISMATCH");
  const tickers = new Set();
  for (const row of p.rows) {
    twoTableRequire(Array.isArray(row) && row.length === TWO_TABLE_COLUMNS.length
      && typeof row[0] === "string" && typeof row[1] === "string" && /^[0-9]{6}$/.test(row[1])
      && Number.isFinite(row[2]) && row[2] > 0, "TWO_TABLE_ROW_INVALID");
    twoTableRequire(!tickers.has(row[1]), "TWO_TABLE_DUPLICATE_TICKER");
    tickers.add(row[1]);
  }
  return p;
}

async function handleTwoTableRequest(url) {
  try {
    const query = parseTwoTableQuery(url);
    const [status, manifest, calendar] = await Promise.all([
      readTwoTableSource("api/status.json", TWO_TABLE_MAX_CONTROL_BYTES),
      readTwoTableSource("api/two_table_v1/manifest.json", TWO_TABLE_MAX_CONTROL_BYTES),
      readTwoTableSource("config/krx_market_holidays.json", TWO_TABLE_MAX_CONTROL_BYTES),
    ]);
    const control = verifyTwoTableControl(status.payload, manifest.payload, calendar.payload, query);
    const source = await readTwoTableSource(`api/two_table_v1/${control.name}`, TWO_TABLE_MAX_BYTES);
    const payload = await verifyTwoTablePage(source, manifest.payload, query, control);
    const [finalStatus, finalManifest, finalCalendar] = await Promise.all([
      readTwoTableSource("api/status.json", TWO_TABLE_MAX_CONTROL_BYTES),
      readTwoTableSource("api/two_table_v1/manifest.json", TWO_TABLE_MAX_CONTROL_BYTES),
      readTwoTableSource("config/krx_market_holidays.json", TWO_TABLE_MAX_CONTROL_BYTES),
    ]);
    twoTableRequire(await twoTableDigest(manifest.raw) === await twoTableDigest(finalManifest.raw),
      "TWO_TABLE_MANIFEST_CHANGED_RETRY");
    twoTableRequire(await twoTableDigest(calendar.raw) === await twoTableDigest(finalCalendar.raw),
      "TWO_TABLE_CALENDAR_CHANGED_RETRY");
    const finalControl = verifyTwoTableControl(finalStatus.payload, finalManifest.payload, finalCalendar.payload, query);
    const nextPage = query.page < control.pageCount ? query.page + 1 : null;
    const nextUrl = nextPage === null ? null : `${url.pathname}?mode=${query.mode}&page=${nextPage}`
      + `&build_id=${encodeURIComponent(manifest.payload.source_build_id)}`;
    const body = JSON.stringify({ ...payload, transport: {
      worker_build: BUILD_VERSION,
      mode: query.mode,
      expected_official_date_at_request: finalControl.expected,
      current_official_freshness_checked: true,
      source_checksum_verified: true,
      page_rows_preserved: true,
      values_recalculated: false,
      request_time_prices_applied: false,
      all_pages_required_for_complete_table: true,
      next_page: nextPage,
      next_page_url: nextUrl,
    } });
    twoTableRequire(new TextEncoder().encode(body).byteLength <= TWO_TABLE_MAX_BYTES,
      "TWO_TABLE_RESPONSE_TOO_LARGE", 502);
    return new Response(body, { headers: { ...CORS_HEADERS,
      "Content-Type": "application/json; charset=utf-8",
      "X-Two-Table-Mode": query.mode,
      "X-Two-Table-Build-Id": manifest.payload.source_build_id,
      "X-Two-Table-SHA256-Verified": "true",
    } });
  } catch (error) {
    // No upstream body, URL parameters, credentials or fabricated rows in errors.
    return jsonResponse({ status: "ERROR",
      error: error instanceof TwoTableError ? error.message : "TWO_TABLE_UNEXPECTED_ERROR",
      rows: [], safe_to_analyze_as_latest: false,
      production_activation_allowed: false,
    }, error instanceof TwoTableError ? error.status : 503);
  }
}
// TWO_TABLE_GUARDED_PROXY_V852_END

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload, null, 2), {
    status,
    headers: {
      ...CORS_HEADERS,
      "Content-Type": "application/json; charset=utf-8",
    },
  });
}


async function handleGitHubJsonProxy(request, url) {
  const relativePath = decodeURIComponent(
    url.pathname.slice(GITHUB_PROXY_PREFIX.length),
  );

  if (!isSafeGitHubApiPath(relativePath)) {
    return jsonResponse(
      {
        status: "ERROR",
        error: "INVALID_GITHUB_API_PATH",
        message: "Only safe JSON paths under the repository api directory are allowed.",
      },
      400,
    );
  }

  const stockReferenceQuery = parseStockReferenceQuery(
    relativePath,
    url.searchParams,
  );
  if (stockReferenceQuery?.error) {
    return jsonResponse(
      {
        status: "ERROR",
        error: stockReferenceQuery.error,
        message: stockReferenceQuery.message,
        path: relativePath,
      },
      400,
    );
  }

  const cache = caches.default;
  const cacheUrl = new URL(request.url);
  cacheUrl.search = "";
  if (stockReferenceQuery) {
    cacheUrl.searchParams.set("ticker", stockReferenceQuery.ticker);
    if (stockReferenceQuery.market) {
      cacheUrl.searchParams.set("market", stockReferenceQuery.market);
    }
  }
  cacheUrl.searchParams.set("__proxy_build", BUILD_VERSION);
  const cacheKey = new Request(cacheUrl.toString(), { method: "GET" });
  const cached = await cache.match(cacheKey);

  if (cached) {
    return withProxyHeaders(cached, {
      cacheStatus: "HIT",
      upstream: cached.headers.get("X-GitHub-Proxy-Upstream") || "CACHE",
    });
  }

  const primaryUrl = `${GITHUB_RAW_BASE}${relativePath}`;
  let upstreamResponse;
  let primaryFetchError = null;

  try {
    upstreamResponse = await fetchWithTimeout(
      primaryUrl,
      {
        headers: {
          Accept: "application/json, text/plain;q=0.9, */*;q=0.8",
          "User-Agent": "krx-watchlist-cloudflare-proxy/1.3.9",
        },
      },
      GITHUB_PROXY_PRIMARY_FETCH_TIMEOUT_MS,
    );
  } catch (error) {
    primaryFetchError =
      error instanceof Error ? error.message : String(error);
    upstreamResponse = new Response(primaryFetchError, { status: 599 });
  }
  let upstreamName = "RAW_GITHUB";

  if (shouldUseGitHubApiFallback(upstreamResponse.status)) {
    const fallbackUrl = `${GITHUB_API_BASE}${relativePath}?ref=main`;
    let fallbackResponse = null;

    try {
      fallbackResponse = await fetchWithTimeout(
        fallbackUrl,
        {
          headers: {
            Accept: "application/vnd.github.raw+json",
            "User-Agent": "krx-watchlist-cloudflare-proxy/1.3.9",
            "X-GitHub-Api-Version": "2022-11-28",
          },
        },
        GITHUB_PROXY_FALLBACK_FETCH_TIMEOUT_MS,
      );
    } catch (error) {
      const fallbackFetchError =
        error instanceof Error ? error.message : String(error);
      if (!upstreamResponse.ok) {
        upstreamResponse = new Response(
          [primaryFetchError, fallbackFetchError]
            .filter(Boolean)
            .join(" | "),
          { status: 599 },
        );
        upstreamName = "GITHUB_UPSTREAM_FETCH_ERROR";
      }
    }

    if (fallbackResponse && (fallbackResponse.ok || !upstreamResponse.ok)) {
      upstreamResponse = fallbackResponse;
      upstreamName = "GITHUB_CONTENTS_API";
    }
  }

  if (!upstreamResponse.ok) {
    const errorBody = await safeText(upstreamResponse);
    return jsonResponse(
      {
        status: "ERROR",
        error: "GITHUB_PROXY_UPSTREAM_FAILED",
        upstream_status: upstreamResponse.status,
        upstream: upstreamName,
        path: relativePath,
        message: errorBody.slice(0, 500) || "GitHub upstream request failed.",
      },
      upstreamResponse.status === 404 ? 404 : 503,
    );
  }

  let response;

  if (relativePath === "manifest.json") {
    const sourceText = await upstreamResponse.text();
    let sourcePayload;

    try {
      sourcePayload = JSON.parse(sourceText);
    } catch (error) {
      return jsonResponse(
        {
          status: "ERROR",
          error: "MANIFEST_JSON_PARSE_FAILED",
          path: relativePath,
          upstream: upstreamName,
          message:
            error instanceof Error ? error.message : String(error),
        },
        502,
      );
    }

    const statusFallback = await fetchStatusForCompactManifest();
    const compactPayload = compactManifestPayload(
      sourcePayload,
      statusFallback.payload,
    );
    const compactBody = JSON.stringify(compactPayload, null, 2);

    response = new Response(compactBody, {
      status: 200,
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": `public, max-age=${GITHUB_PROXY_CACHE_TTL_SECONDS}`,
        "X-GitHub-Proxy-Upstream": upstreamName,
        "X-GitHub-Proxy-Cache": "MISS",
        "X-GitHub-Proxy-Transform": "COMPACT_MANIFEST_V3",
        "X-Manifest-Freshness-Merge": statusFallback.source,
        "X-Manifest-Original-Bytes": String(
          new TextEncoder().encode(sourceText).length,
        ),
        "X-Manifest-Compact-Bytes": String(
          new TextEncoder().encode(compactBody).length,
        ),
      },
    });
  } else if (relativePath === "watchlist.json") {
    const sourceText = await upstreamResponse.text();
    let sourcePayload;

    try {
      sourcePayload = JSON.parse(sourceText);
    } catch (error) {
      return jsonResponse(
        {
          status: "ERROR",
          error: "WATCHLIST_JSON_PARSE_FAILED",
          path: relativePath,
          upstream: upstreamName,
          message:
            error instanceof Error ? error.message : String(error),
        },
        502,
      );
    }

    const compactPayload = compactWatchlistPayload(sourcePayload);
    const compactBody = JSON.stringify(compactPayload);

    response = new Response(compactBody, {
      status: 200,
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": `public, max-age=${GITHUB_PROXY_CACHE_TTL_SECONDS}`,
        "X-GitHub-Proxy-Upstream": upstreamName,
        "X-GitHub-Proxy-Cache": "MISS",
        "X-GitHub-Proxy-Transform": "COMPACT_WATCHLIST_V1",
        "X-Watchlist-Original-Bytes": String(
          new TextEncoder().encode(sourceText).length,
        ),
        "X-Watchlist-Compact-Bytes": String(
          new TextEncoder().encode(compactBody).length,
        ),
        "X-Watchlist-Rows-Preserved": "true",
      },
    });
  } else if (relativePath === "us_watchlist.json") {
    const sourceText = await upstreamResponse.text();
    let sourcePayload;

    try {
      sourcePayload = JSON.parse(sourceText);
    } catch (error) {
      return jsonResponse(
        {
          status: "ERROR",
          error: "US_WATCHLIST_JSON_PARSE_FAILED",
          path: relativePath,
          upstream: upstreamName,
          message:
            error instanceof Error ? error.message : String(error),
        },
        502,
      );
    }

    const compactPayload = compactUsWatchlistPayload(sourcePayload);
    const compactBody = JSON.stringify(compactPayload);

    response = new Response(compactBody, {
      status: 200,
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": `public, max-age=${GITHUB_PROXY_CACHE_TTL_SECONDS}`,
        "X-GitHub-Proxy-Upstream": upstreamName,
        "X-GitHub-Proxy-Cache": "MISS",
        "X-GitHub-Proxy-Transform": "COMPACT_US_WATCHLIST_V1",
        "X-US-Watchlist-Original-Bytes": String(
          new TextEncoder().encode(sourceText).length,
        ),
        "X-US-Watchlist-Compact-Bytes": String(
          new TextEncoder().encode(compactBody).length,
        ),
        "X-US-Watchlist-Rows-Preserved": "true",
        "X-US-Watchlist-Values-Recalculated": "false",
      },
    });
  } else if (isCompactTablePath(relativePath)) {
    const sourceText = await upstreamResponse.text();
    let sourcePayload;

    try {
      sourcePayload = JSON.parse(sourceText);
    } catch (error) {
      return jsonResponse(
        {
          status: "ERROR",
          error: "TABLE_JSON_PARSE_FAILED",
          path: relativePath,
          upstream: upstreamName,
          message:
            error instanceof Error ? error.message : String(error),
        },
        502,
      );
    }

    const compactPayload = compactTablePayload(
      sourcePayload,
      relativePath,
    );
    const compactBody = JSON.stringify(compactPayload);

    response = new Response(compactBody, {
      status: 200,
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": `public, max-age=${GITHUB_PROXY_CACHE_TTL_SECONDS}`,
        "X-GitHub-Proxy-Upstream": upstreamName,
        "X-GitHub-Proxy-Cache": "MISS",
        "X-GitHub-Proxy-Transform": "COMPACT_TABLE_V1",
        "X-Compact-Table-Path": relativePath,
        "X-Table-Original-Bytes": String(
          new TextEncoder().encode(sourceText).length,
        ),
        "X-Table-Compact-Bytes": String(
          new TextEncoder().encode(compactBody).length,
        ),
        "X-Table-Rows-Preserved": "true",
        "X-Table-Values-Recalculated": "false",
      },
    });
  } else if (stockReferenceQuery) {
    const sourceText = await upstreamResponse.text();
    let sourcePayload;

    try {
      sourcePayload = JSON.parse(sourceText);
    } catch (error) {
      return jsonResponse(
        {
          status: "ERROR",
          error: "STOCK_REFERENCE_JSON_PARSE_FAILED",
          path: relativePath,
          upstream: upstreamName,
          message:
            error instanceof Error ? error.message : String(error),
        },
        502,
      );
    }

    const filteredPayload = filterStockReferencePayload(
      sourcePayload,
      stockReferenceQuery,
    );
    const filteredBody = JSON.stringify(filteredPayload);

    response = new Response(filteredBody, {
      status: 200,
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": `public, max-age=${GITHUB_PROXY_CACHE_TTL_SECONDS}`,
        "X-GitHub-Proxy-Upstream": upstreamName,
        "X-GitHub-Proxy-Cache": "MISS",
        "X-GitHub-Proxy-Transform": "FILTER_STOCK_REFERENCE_TICKER_V1",
        "X-Stock-Reference-Original-Bytes": String(
          new TextEncoder().encode(sourceText).length,
        ),
        "X-Stock-Reference-Filtered-Bytes": String(
          new TextEncoder().encode(filteredBody).length,
        ),
        "X-Stock-Reference-Source-Rows": String(
          filteredPayload.source_row_count,
        ),
        "X-Stock-Reference-Returned-Rows": String(
          filteredPayload.returned_row_count,
        ),
        "X-Stock-Reference-Contains-User-Holdings": "false",
      },
    });
  } else {
    const body = await upstreamResponse.arrayBuffer();

    response = new Response(body, {
      status: 200,
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": `public, max-age=${GITHUB_PROXY_CACHE_TTL_SECONDS}`,
        "X-GitHub-Proxy-Upstream": upstreamName,
        "X-GitHub-Proxy-Cache": "MISS",
      },
    });
  }

  await cache.put(cacheKey, response.clone());
  return response;
}

async function fetchStatusForCompactManifest() {
  const relativePath = "status.json";
  const primaryUrl = `${GITHUB_RAW_BASE}${relativePath}`;

  try {
    let response = await fetchWithTimeout(
      primaryUrl,
      {
        headers: {
          Accept: "application/json, text/plain;q=0.9, */*;q=0.8",
          "User-Agent": "krx-watchlist-cloudflare-proxy/1.3.2",
        },
      },
      GITHUB_PROXY_PRIMARY_FETCH_TIMEOUT_MS,
    );
    let source = "RAW_GITHUB_STATUS";

    if (shouldUseGitHubApiFallback(response.status)) {
      const fallbackUrl = `${GITHUB_API_BASE}${relativePath}?ref=main`;
      const fallbackResponse = await fetchWithTimeout(
        fallbackUrl,
        {
          headers: {
            Accept: "application/vnd.github.raw+json",
            "User-Agent": "krx-watchlist-cloudflare-proxy/1.3.2",
            "X-GitHub-Api-Version": "2022-11-28",
          },
        },
        GITHUB_PROXY_FALLBACK_FETCH_TIMEOUT_MS,
      );

      if (fallbackResponse.ok || !response.ok) {
        response = fallbackResponse;
        source = "GITHUB_CONTENTS_API_STATUS";
      }
    }

    if (!response.ok) {
      return {
        payload: null,
        source: `STATUS_UNAVAILABLE_${response.status}`,
      };
    }

    const text = await response.text();
    return {
      payload: JSON.parse(text),
      source,
    };
  } catch (error) {
    return {
      payload: null,
      source: "STATUS_FETCH_OR_PARSE_FAILED",
    };
  }
}

function firstDefined(...values) {
  for (const value of values) {
    if (value !== undefined && value !== null) {
      return value;
    }
  }
  return null;
}

function compactManifestPayload(source, statusSource = null) {
  const manifest = source && typeof source === "object" ? source : {};
  const status =
    statusSource && typeof statusSource === "object"
      ? statusSource
      : {};

  const compact = {
    schema_version: manifest.schema_version ?? null,
    manifest_mode: "COMPACT_FOR_CUSTOM_GPT",
    manifest_transform_version: "1.1",
    build_id: firstDefined(
      manifest.build_id,
      status.build_id,
      null,
    ),
    generated_at_kst: firstDefined(
      manifest.generated_at_kst,
      status.generated_at_kst,
      null,
    ),
    source_commit_sha: firstDefined(
      manifest.source_commit_sha,
      status.source_commit_sha,
      null,
    ),
    status: firstDefined(
      manifest.status,
      status.status,
      null,
    ),
    api_sync_ok: firstDefined(
      manifest.api_sync_ok,
      status.api_sync_ok,
      null,
    ),
    official_fresh_now: firstDefined(
      manifest.official_fresh_now,
      status.official_fresh_now,
      null,
    ),
    safe_to_analyze_as_latest: firstDefined(
      manifest.safe_to_analyze_as_latest,
      status.safe_to_analyze_as_latest,
      null,
    ),
    freshness_value_source:
      manifest.official_fresh_now !== undefined &&
      manifest.official_fresh_now !== null
        ? "manifest.json"
        : status.official_fresh_now !== undefined &&
            status.official_fresh_now !== null
          ? "status.json"
          : "unavailable",
    rules_version: firstDefined(
      manifest.rules_version,
      manifest.rules?.version,
      status.rules_version,
      null,
    ),
    rules_sha256: firstDefined(
      manifest.rules_sha256,
      manifest.rules?.sha256,
      status.rules_sha256,
      null,
    ),
    rules: compactObject(manifest.rules, [
      "source_file",
      "version",
      "sha256",
    ]),
    presentation_policy: compactObject(
      manifest.presentation_policy,
      [
        "default_output_mode",
        "separate_recommendation_table_default",
        "recommendation_markings_embedded_in_main_table",
        "duplicate_rows_across_main_and_shortlist_tables",
        "current_price_column_label",
        "price_range_markdown_required",
        "bold_price_ranges",
        "kr_sector_theme_source",
        "kr_sector_theme_missing_display",
        "kr_average_volume_per_minute_value_column_label",
        "kr_regular_session_minutes",
        "us_table_omit_kr_market_metadata_by_default",
      ],
    ),
    request_time_price_policy: compactObject(
      manifest.request_time_price_policy,
      [
        "enabled",
        "mode",
        "lookup_scope",
        "action_operation_id",
        "health_operation_id",
        "api_base_url",
        "max_batch_size",
        "preserve_official_history",
        "allow_last_confirmed_official_when_delayed",
        "failed_quote_behavior",
      ],
    ),
    tables: Array.isArray(manifest.tables)
      ? manifest.tables.map(compactManifestTable)
      : [],
    snapshots: Array.isArray(manifest.snapshots)
      ? manifest.snapshots.map(compactManifestSnapshot)
      : [],
    command_route_summary:
      manifest.command_route_summary ?? null,
    command_route_contract:
      manifest.command_route_contract ?? null,
    control_files: Array.isArray(manifest.control_files)
      ? manifest.control_files
      : [],
    final_display_contract: compactNestedFeature(
      manifest.final_display_contract,
    ),
    kr_sector_theme: compactNestedFeature(manifest.kr_sector_theme),
  };

  compact.table_count = compact.tables.length;
  compact.snapshot_count = compact.snapshots.length;
  compact.required_table_failures = compact.tables
    .filter((item) => item.required && item.status !== "OK")
    .map((item) => item.table_id);
  compact.structure_ok = compact.required_table_failures.length === 0;
  compact.compact_manifest_bytes = new TextEncoder().encode(
    JSON.stringify(compact),
  ).length;

  return compact;
}

function compactManifestTable(item) {
  const table = item && typeof item === "object" ? item : {};

  return {
    table_id: table.table_id ?? null,
    display_name: table.display_name ?? null,
    api_file: table.api_file ?? null,
    status: table.status ?? null,
    row_count: table.row_count ?? null,
    required: table.required ?? false,
    default_output: table.default_output ?? false,
    explicit_request_only: table.explicit_request_only ?? false,
    current_basis_selected: table.current_basis_selected ?? false,
    display_contract_version:
      table.display_contract_version ?? null,
    sector_theme_available:
      table.sector_theme_available ?? null,
    sector_theme_coverage_pct:
      table.sector_theme_coverage_pct ?? null,
    sector_theme_source:
      table.sector_theme_source ?? null,
  };
}

function compactManifestSnapshot(item) {
  const snapshot = item && typeof item === "object" ? item : {};

  return {
    snapshot_id: snapshot.snapshot_id ?? null,
    display_name: snapshot.display_name ?? null,
    api_file: snapshot.api_file ?? null,
    status: snapshot.status ?? null,
  };
}

function compactWatchlistPayload(source) {
  const watchlist = source && typeof source === "object" ? source : {};
  const rows = Array.isArray(watchlist.rows) ? watchlist.rows : [];

  const compact = compactObject(watchlist, [
    "schema_version",
    "table_id",
    "display_name",
    "status",
    "row_count",
    "row_count_ok",
    "build_id",
    "generated_at_kst",
    "source_commit_sha",
    "rules_version",
    "safe_to_analyze_as_latest",
    "current_basis_selected",
    "current_price_basis",
    "analysis_latest_status",
    "stale_analysis_warning",
    "request_time_price_policy",
  ]) || {};

  compact.compact_response = {
    mode: "COMPACT_FOR_CUSTOM_GPT",
    transform_version: "1.0",
    source_row_count: watchlist.row_count ?? rows.length,
    rows_preserved: true,
    values_recalculated: false,
  };
  compact.rows = rows.map(compactWatchlistRow);
  compact.row_count = watchlist.row_count ?? compact.rows.length;
  compact.returned_row_count = compact.rows.length;
  compact.row_count_ok = compact.row_count === compact.returned_row_count;

  return compact;
}

function compactWatchlistRow(value) {
  const row = compactObject(value, [
    "name",
    "ticker",
    "country",
    "currency",
    "exchange",
    "last_date",
    "current_close",
    "split_buy_low_ref",
    "split_buy_high_ref",
    "target1_ref",
    "avg_daily_move_abs",
    "avg_daily_move_pct",
    "low_3m_intraday",
    "high_3m_intraday",
    "range_3m_pct",
    "position_in_3m_range_pct",
    "last_volume",
    "avg20_trading_value",
    "low_liquidity",
    "operating_profit",
    "operating_loss_flag",
    "financial_data_status",
    "revenue_yoy_pct",
    "operating_profit_yoy_pct",
    "operating_margin_pct",
    "debt_ratio_pct",
    "roe_annualized_pct",
    "earnings_trend",
    "per_annualized",
    "pbr",
    "valuation_data_status",
    "supply_check_status",
    "supply_burden_detected",
    "supply_burden_level",
    "supply_burden_keywords",
  ]) || {};

  for (const key of Object.keys(row)) {
    if (row[key] === null || row[key] === undefined) {
      delete row[key];
    }
  }

  return row;
}

function compactUsWatchlistPayload(source) {
  const watchlist = source && typeof source === "object" ? source : {};
  const rows = Array.isArray(watchlist.rows) ? watchlist.rows : [];

  const compact = compactObject(watchlist, [
    "schema_version",
    "table_id",
    "display_name",
    "status",
    "row_count",
    "row_count_ok",
    "build_id",
    "generated_at_kst",
    "source_commit_sha",
    "rules_version",
    "rules_sha256",
    "current_basis_selected",
    "current_price_basis",
    "data_date_min",
    "data_date_max",
    "request_time_price_policy",
  ]) || {};

  compact.compact_response = {
    mode: "COMPACT_FOR_CUSTOM_GPT",
    transform_version: "1.0",
    source_row_count: watchlist.row_count ?? rows.length,
    rows_preserved: true,
    values_recalculated: false,
  };
  compact.rows = rows.map(compactUsWatchlistRow);
  compact.row_count = watchlist.row_count ?? compact.rows.length;
  compact.returned_row_count = compact.rows.length;
  compact.row_count_ok = compact.row_count === compact.returned_row_count;

  return compact;
}

function compactUsWatchlistRow(value) {
  const row = compactObject(value, [
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
  ]) || {};

  for (const key of Object.keys(row)) {
    if (row[key] === null || row[key] === undefined) {
      delete row[key];
    }
  }

  return row;
}

const COMPACT_TABLE_TOP_LEVEL_KEYS = [
  "schema_version",
  "table_id",
  "display_name",
  "status",
  "row_count",
  "row_count_ok",
  "expected_rows",
  "build_id",
  "generated_at_kst",
  "source_commit_sha",
  "rules_version",
  "rules_sha256",
  "safe_to_analyze_as_latest",
  "current_basis_selected",
  "current_price_basis",
  "data_date_min",
  "data_date_max",
  "candidate_analysis_date",
  "analysis_latest_status",
  "stale_analysis_warning",
  "request_time_price_policy",
  "official_data",
];

const COMPACT_LIGHT_MARKET_ROW_KEYS = [
  "rank",
  "name",
  "code",
  "quote_key",
  "quote_market",
  "static_price",
  "recommendation_display",
  "operating_loss",
  "supply_burden",
  "supply_burden_display",
  "value_buy_range_markdown",
  "first_sell_target_range_markdown",
  "low_3m",
  "high_3m",
  "return_1m_pct",
  "avg_volume",
  "avg_trading_value_per_minute_display",
  "trading_activity",
  "price_elasticity",
  "current_position",
  "avg_daily_move",
  "earnings_trend",
  "operating_profit_yoy_pct",
  "revenue_yoy_pct",
  "per_annualized",
  "pbr",
  "score",
  "score_reason",
  "sector_theme",
  "supply_check_status",
  "supply_burden_level",
];

// KOSPI has 30 Korean-language rows. Keep every field required to render the
// production table, while dropping duplicate flags already represented by
// recommendation_display and supply_burden_display. Static current_position
// is omitted because V8.0 requires recalculation from the request-time price
// and the preserved 3-month low/high. code duplicates quote_key, and
// quote_market duplicates this KOSPI-only table's market identity, so both are
// omitted from the compact response. The request-time policy and official
// freshness objects are obtained from their dedicated Actions.
const COMPACT_KOSPI_WATCHLIST_TOP_LEVEL_KEYS =
  COMPACT_TABLE_TOP_LEVEL_KEYS.filter(
    (key) => ![
      "request_time_price_policy",
      "official_data",
    ].includes(key),
  );

const COMPACT_KOSPI_WATCHLIST_ROW_KEYS =
  COMPACT_LIGHT_MARKET_ROW_KEYS.filter(
    (key) => ![
      "rank",
      "code",
      "quote_market",
      "operating_loss",
      "supply_burden",
      "current_position",
      "supply_check_status",
      "supply_burden_level",
    ].includes(key),
  );

const COMPACT_ONE_MONTH_ROW_KEYS = [
  "rank",
  "name",
  "code",
  "market",
  "asof_date",
  "close",
  "buy_range",
  "sell_range",
  "low_1m",
  "high_1m",
  "return_1m_pct",
  "return_3m_pct",
  "avg_volume",
  "avg_trading_value",
  "avg_daily_move_text",
  "liquidity_flag",
  "position_in_1m_range_pct",
  "current_position_period",
  "overheat_flag",
  "score",
  "one_month_market_score",
  "one_month_market_reason",
  "recommend_flag",
  "reason",
];

const COMPACT_ENRICHED_MARKET_ROW_KEYS = [
  "rank",
  "name",
  "code",
  "market",
  "asof_date",
  "close",
  "buy_range",
  "sell_range",
  "low_3m",
  "high_3m",
  "return_1m_pct",
  "return_3m_pct",
  "return_5d_pct",
  "avg_volume",
  "avg_trading_value",
  "avg_daily_move_text",
  "avg_wave_days",
  "liquidity_flag",
  "current_position",
  "position_in_3m_range_pct",
  "overheat_flag",
  "score",
  "short_term_score",
  "final_score",
  "recommend_flag",
  "reason",
  "fx_benefit_structure",
  "fx_proxy_score",
  "import_cost_risk",
  "financial_data_status",
  "revenue_yoy_pct",
  "operating_profit_yoy_pct",
  "net_income_yoy_pct",
  "operating_margin_pct",
  "operating_loss_flag",
  "roe_annualized_pct",
  "per_annualized",
  "pbr",
  "debt_ratio_pct",
  "earnings_trend",
  "supply_check_status",
  "supply_burden_detected",
  "supply_burden_level",
  "supply_burden_keywords",
];

const COMPACT_MONTHLY_CYCLE_ROW_KEYS = [
  "rank",
  "name",
  "code",
  "market",
  "close",
  "buy_range",
  "sell_range",
  "low_6m",
  "high_6m",
  "avg_trading_value",
  "avg_daily_move_text",
  "liquidity_flag",
  "position_in_6m_range_pct",
  "cycle_count_6m",
  "avg_cycle_days",
  "avg_swing_pct",
  "latest_position",
  "cycle_marker",
  "status_flag",
  "reason",
  "financial_data_status",
  "revenue_yoy_pct",
  "operating_profit_yoy_pct",
  "net_income_yoy_pct",
  "operating_margin_pct",
  "operating_loss_flag",
  "roe_annualized_pct",
  "per_annualized",
  "pbr",
  "debt_ratio_pct",
  "earnings_trend",
  "supply_check_status",
  "supply_burden_detected",
  "supply_burden_level",
];

const COMPACT_TABLE_PROFILES = {
  "kospi_watchlist.json": COMPACT_KOSPI_WATCHLIST_ROW_KEYS,
  "kosdaq_watchlist.json": COMPACT_LIGHT_MARKET_ROW_KEYS,
  "kospi_1m_candidates_30.json": COMPACT_ONE_MONTH_ROW_KEYS,
  "kosdaq_1m_candidates_10.json": COMPACT_ONE_MONTH_ROW_KEYS,
  "kospi_gainers_1m.json": COMPACT_ENRICHED_MARKET_ROW_KEYS,
  "kospi_monthly_cycle.json": COMPACT_MONTHLY_CYCLE_ROW_KEYS,
  "kospi_fx_weakness_candidates_30.json":
    COMPACT_ENRICHED_MARKET_ROW_KEYS,
  "kospi_short_term_candidates_30.json":
    COMPACT_ENRICHED_MARKET_ROW_KEYS,
  "kospi_candidates_30.json": COMPACT_ENRICHED_MARKET_ROW_KEYS,
  "kosdaq_candidates_10.json": COMPACT_ENRICHED_MARKET_ROW_KEYS,
};

function isCompactTablePath(relativePath) {
  return Object.prototype.hasOwnProperty.call(
    COMPACT_TABLE_PROFILES,
    relativePath,
  );
}

function compactTablePayload(source, relativePath) {
  const table = source && typeof source === "object" ? source : {};
  const rows = Array.isArray(table.rows) ? table.rows : [];
  const rowKeys = COMPACT_TABLE_PROFILES[relativePath] || [];
  const topLevelKeys = relativePath === "kospi_watchlist.json"
    ? COMPACT_KOSPI_WATCHLIST_TOP_LEVEL_KEYS
    : COMPACT_TABLE_TOP_LEVEL_KEYS;
  const compact = compactObject(
    table,
    topLevelKeys,
  ) || {};

  compact.compact_response = {
    mode: "COMPACT_FOR_CUSTOM_GPT",
    transform_version:
      relativePath === "kospi_watchlist.json" ? "1.2" : "1.0",
    source_path: relativePath,
    source_row_count: table.row_count ?? rows.length,
    rows_preserved: true,
    values_recalculated: false,
  };
  if (relativePath === "kospi_watchlist.json") {
    compact.compact_response.response_profile = "KOSPI_ACTION_V2";
  }
  compact.rows = rows.map((row) => compactTableRow(row, rowKeys));
  compact.row_count = table.row_count ?? compact.rows.length;
  compact.returned_row_count = compact.rows.length;
  compact.row_count_ok =
    compact.row_count === compact.returned_row_count;

  return compact;
}

function compactTableRow(value, allowedKeys) {
  const row = compactObject(value, allowedKeys) || {};

  for (const key of Object.keys(row)) {
    if (row[key] === null || row[key] === undefined) {
      delete row[key];
    }
  }

  return row;
}

function parseStockReferenceQuery(relativePath, searchParams) {
  const match = /^stock_reference_shards\/([0-9]{2})\.json$/.exec(
    relativePath,
  );
  if (!match) {
    return null;
  }

  const prefix = match[1];
  const ticker = String(searchParams.get("ticker") || "").trim();
  if (!ticker) {
    return {
      error: "STOCK_REFERENCE_TICKER_REQUIRED",
      message:
        "ticker query parameter is required for stock-reference shard lookup.",
    };
  }
  if (!/^[0-9]{6}$/.test(ticker)) {
    return {
      error: "INVALID_STOCK_REFERENCE_TICKER",
      message: "ticker must be a six-digit Korean stock code.",
    };
  }
  if (!ticker.startsWith(prefix)) {
    return {
      error: "STOCK_REFERENCE_PREFIX_MISMATCH",
      message: "prefix must match the first two digits of ticker.",
    };
  }

  const rawMarket = String(searchParams.get("market") || "")
    .trim()
    .toUpperCase();
  if (rawMarket && !["KOSPI", "KOSDAQ"].includes(rawMarket)) {
    return {
      error: "INVALID_STOCK_REFERENCE_MARKET",
      message: "market must be KOSPI or KOSDAQ when provided.",
    };
  }

  return {
    prefix,
    ticker,
    market: rawMarket || null,
  };
}

function filterStockReferencePayload(source, query) {
  const payload = source && typeof source === "object" ? source : {};
  const sourceRows = Array.isArray(payload.rows) ? payload.rows : [];
  const rows = sourceRows.filter((row) => {
    if (!row || typeof row !== "object") {
      return false;
    }
    if (String(row.ticker || "") !== query.ticker) {
      return false;
    }
    return !query.market || String(row.market || "") === query.market;
  });

  return {
    schema_version: payload.schema_version ?? null,
    status:
      rows.length === 1
        ? "OK"
        : rows.length === 0
          ? "NOT_FOUND"
          : "AMBIGUOUS",
    policy_version: payload.policy_version ?? null,
    script_version: payload.script_version ?? null,
    generated_at_kst: payload.generated_at_kst ?? null,
    privacy_mode: payload.privacy_mode ?? "PUBLIC_REFERENCE_ONLY",
    contains_user_holdings: false,
    prefix: query.prefix,
    requested_ticker: query.ticker,
    requested_market: query.market,
    source_row_count: payload.row_count ?? sourceRows.length,
    returned_row_count: rows.length,
    exact_match: rows.length === 1,
    values_recalculated: false,
    rows,
  };
}

function compactNestedFeature(value) {
  if (!value || typeof value !== "object") {
    return null;
  }

  const result = compactObject(value, [
    "version",
    "status",
    "source",
    "source_url",
    "generated_at_kst",
    "cache_mode",
    "regular_session_minutes",
    "column_label",
    "current_price_column_label",
    "bold_price_ranges_required",
    "us_metadata_omits_kr_market_rows_by_default",
    "sector_theme_do_not_invent",
  ]);

  if (Array.isArray(value.entries)) {
    result.entries = value.entries.map((entry) =>
      compactObject(entry, [
        "table_id",
        "filename",
        "api_file",
        "market_scope",
        "row_count",
        "sector_theme_matched",
        "sector_theme_coverage_pct",
        "payload_size_bytes",
      ]),
    );
  }

  return result;
}

function compactObject(value, allowedKeys) {
  if (!value || typeof value !== "object") {
    return null;
  }

  const result = {};
  for (const key of allowedKeys) {
    if (Object.prototype.hasOwnProperty.call(value, key)) {
      result[key] = value[key];
    }
  }
  return result;
}

function isSafeGitHubApiPath(relativePath) {
  if (!relativePath || relativePath.includes("..") || relativePath.startsWith("/")) {
    return false;
  }

  if (!/^[A-Za-z0-9_./-]+\.json$/.test(relativePath)) {
    return false;
  }

  if (relativePath.startsWith("stock_reference_shards/")) {
    return /^stock_reference_shards\/[0-9]{2}\.json$/.test(relativePath);
  }

  return !relativePath.includes("/");
}

function shouldUseGitHubApiFallback(status) {
  return status === 403 || status === 429 || status >= 500;
}

async function fetchWithTimeout(resource, options, timeoutMs) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    return await fetch(resource, {
      ...options,
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timeout);
  }
}

async function safeText(response) {
  try {
    return await response.text();
  } catch (_) {
    return "";
  }
}

function withProxyHeaders(response, { cacheStatus, upstream }) {
  const headers = new Headers(response.headers);
  headers.set("Access-Control-Allow-Origin", "*");
  headers.set("X-GitHub-Proxy-Cache", cacheStatus);
  headers.set("X-GitHub-Proxy-Upstream", upstream);

  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function parseItems(rawItems) {
  if (!rawItems.trim()) {
    return {
      error: "ITEMS_REQUIRED",
      message: "items query parameter is required.",
    };
  }

  const items = [];
  const seen = new Set();

  for (const rawPart of rawItems.split(",")) {
    const part = rawPart.trim();
    if (!part) continue;

    const separatorIndex = part.indexOf("|");
    const rawKey =
      separatorIndex >= 0 ? part.slice(0, separatorIndex) : part;
    const rawMarket =
      separatorIndex >= 0 ? part.slice(separatorIndex + 1) : "";

    const quoteKey = normalizeQuoteKey(rawKey);
    const market = normalizeMarket(rawMarket, quoteKey);

    if (!quoteKey) continue;

    const dedupeKey = `${quoteKey}|${market}`;
    if (seen.has(dedupeKey)) continue;
    seen.add(dedupeKey);

    items.push({
      input: part,
      quote_key: quoteKey,
      market,
    });
  }

  if (items.length === 0) {
    return {
      error: "NO_VALID_ITEMS",
      message: "No valid quote keys were provided.",
    };
  }

  if (items.length > MAX_ITEMS) {
    return {
      error: "TOO_MANY_ITEMS",
      message: `A maximum of ${MAX_ITEMS} items is allowed.`,
    };
  }

  return { items };
}

function normalizeQuoteKey(value) {
  return String(value || "").trim().toUpperCase();
}

function normalizeMarket(value, quoteKey) {
  const market = String(value || "").trim().toUpperCase();

  if (
    ["USA", "US", "NASDAQ", "NYSE", "AMEX", "NYSEARCA"].includes(
      market,
    )
  ) {
    return "USA";
  }

  if (["KOSPI", "KS", "KRX"].includes(market)) {
    return "KOSPI";
  }

  if (["KOSDAQ", "KQ"].includes(market)) {
    return "KOSDAQ";
  }

  return /^\d{6}$/.test(quoteKey) ? "KOSPI" : "USA";
}

async function fetchQuote(item) {
  try {
    if (item.market === "USA") {
      return await fetchUsQuote(item);
    }
    return await fetchKrQuote(item);
  } catch (error) {
    return failedQuote(
      item,
      "UNHANDLED_PROVIDER_ERROR",
      error instanceof Error ? error.message : String(error),
    );
  }
}

async function fetchKrQuote(item) {
  const code = item.quote_key.replace(/\D/g, "").slice(-6).padStart(6, "0");
  if (!/^\d{6}$/.test(code)) {
    return failedQuote(
      item,
      "INVALID_KR_CODE",
      "Korean stock code must be six digits.",
    );
  }

  const endpoint =
    `https://m.stock.naver.com/api/stock/${encodeURIComponent(code)}/basic`;

  let payload;
  try {
    payload = await fetchJson(endpoint, {
      headers: providerHeaders("https://m.stock.naver.com/"),
    });
  } catch (error) {
    return failedQuote(
      item,
      "NAVER_FETCH_FAILED",
      error instanceof Error ? error.message : String(error),
      "NAVER_STOCK_MOBILE",
    );
  }

  const currentPrice = parseNumber(
    payload.closePrice ??
      payload.now ??
      payload.currentPrice ??
      payload.current_price,
  );

  if (!Number.isFinite(currentPrice)) {
    return failedQuote(
      item,
      "NAVER_PRICE_MISSING",
      "NAVER response did not contain a usable price.",
      "NAVER_STOCK_MOBILE",
    );
  }

  const tradedAt =
    payload.localTradedAt ??
    payload.tradedAt ??
    payload.updatedAt ??
    payload.updated_at ??
    null;

  const marketStatus =
    payload.marketStatus ??
    payload.marketStatusType ??
    payload.market_status ??
    "UNKNOWN";

  return successfulQuote(item, {
    quoteKey: code,
    ticker: null,
    code,
    currentPrice,
    currency: "KRW",
    source: "NAVER_STOCK_MOBILE",
    sourceKind: "unofficial_auxiliary",
    providerTicker: code,
    priceTime: tradedAt,
    priceTimestamp: null,
    marketStatus,
    sessionStatus: marketStatus,
    exchange: item.market,
    previousClose: parseNumber(
      payload.previousClosePrice ??
        payload.previousClose ??
        payload.previous_close,
    ),
  });
}

async function fetchUsQuote(item) {
  const yahooTicker = normalizeYahooTicker(item.quote_key);
  const endpoint =
    `https://query1.finance.yahoo.com/v8/finance/chart/` +
    `${encodeURIComponent(yahooTicker)}` +
    `?interval=1m&range=5d&includePrePost=true&events=div%2Csplits`;

  let payload;
  try {
    payload = await fetchJson(endpoint, {
      headers: providerHeaders("https://finance.yahoo.com/"),
    });
  } catch (error) {
    return failedQuote(
      item,
      "YAHOO_FETCH_FAILED",
      error instanceof Error ? error.message : String(error),
      "YAHOO_FINANCE_CHART",
      yahooTicker,
    );
  }

  const chart = payload?.chart;
  if (chart?.error) {
    return failedQuote(
      item,
      "YAHOO_PROVIDER_ERROR",
      String(chart.error.description || chart.error.code || "Unknown error"),
      "YAHOO_FINANCE_CHART",
      yahooTicker,
    );
  }

  const result = Array.isArray(chart?.result) ? chart.result[0] : null;
  const meta = result?.meta || {};

  let currentPrice = parseNumber(meta.regularMarketPrice);
  let priceTimestamp = parseInteger(meta.regularMarketTime);

  if (!Number.isFinite(currentPrice)) {
    const fallback = lastFiniteChartPrice(result);
    currentPrice = fallback.price;
    priceTimestamp = fallback.timestamp;
  }

  if (!Number.isFinite(currentPrice)) {
    return failedQuote(
      item,
      "YAHOO_PRICE_MISSING",
      "Yahoo response did not contain a usable regular-market price.",
      "YAHOO_FINANCE_CHART",
      yahooTicker,
    );
  }

  const marketStatus = inferUsMarketStatus(meta);
  const priceTime =
    Number.isFinite(priceTimestamp) && priceTimestamp > 0
      ? new Date(priceTimestamp * 1000).toISOString()
      : null;

  return successfulQuote(item, {
    quoteKey: item.quote_key,
    ticker: item.quote_key,
    code: null,
    currentPrice,
    currency: meta.currency || "USD",
    source: "YAHOO_FINANCE_CHART",
    sourceKind: "unofficial_auxiliary",
    providerTicker: yahooTicker,
    priceTime,
    priceTimestamp,
    marketStatus,
    sessionStatus: marketStatus,
    exchange:
      meta.fullExchangeName ??
      meta.exchangeName ??
      meta.exchangeTimezoneName ??
      "USA",
    previousClose: parseNumber(
      meta.previousClose ?? meta.chartPreviousClose,
    ),
  });
}

function successfulQuote(item, details) {
  return {
    input: item.input,
    quote_key: details.quoteKey,
    ticker: details.ticker,
    symbol: details.ticker,
    code: details.code,
    market: item.market,
    status: "OK",
    ok: true,
    current_price: details.currentPrice,
    price: details.currentPrice,
    currency: details.currency,
    source: details.source,
    price_source: details.source,
    source_kind: details.sourceKind,
    provider_ticker: details.providerTicker,
    price_time: details.priceTime,
    traded_at: details.priceTime,
    price_as_of: details.priceTime,
    price_timestamp: details.priceTimestamp,
    market_status: details.marketStatus,
    session_status: details.sessionStatus,
    exchange: details.exchange,
    previous_close: details.previousClose,
    after_hours_reflected: false,
    is_after_hours: false,
    error_code: null,
    error: null,
  };
}

function failedQuote(
  item,
  errorCode,
  errorMessage,
  source = null,
  providerTicker = null,
) {
  return {
    input: item.input,
    quote_key: item.quote_key,
    ticker: item.market === "USA" ? item.quote_key : null,
    symbol: item.market === "USA" ? item.quote_key : null,
    code: item.market === "USA" ? null : item.quote_key,
    market: item.market,
    status: "ERROR",
    ok: false,
    current_price: null,
    price: null,
    currency: item.market === "USA" ? "USD" : "KRW",
    source,
    price_source: source,
    source_kind: "unofficial_auxiliary",
    provider_ticker: providerTicker,
    price_time: null,
    traded_at: null,
    price_as_of: null,
    price_timestamp: null,
    market_status: "UNKNOWN",
    session_status: "UNKNOWN",
    exchange: item.market,
    previous_close: null,
    after_hours_reflected: false,
    is_after_hours: false,
    error_code: errorCode,
    error: errorMessage,
  };
}

function normalizeYahooTicker(ticker) {
  return String(ticker || "")
    .trim()
    .toUpperCase()
    .replace(/\./g, "-");
}

function lastFiniteChartPrice(result) {
  const timestamps = Array.isArray(result?.timestamp)
    ? result.timestamp
    : [];
  const closes = result?.indicators?.quote?.[0]?.close;
  if (!Array.isArray(closes)) {
    return { price: null, timestamp: null };
  }

  for (let index = closes.length - 1; index >= 0; index -= 1) {
    const price = parseNumber(closes[index]);
    if (Number.isFinite(price)) {
      return {
        price,
        timestamp: parseInteger(timestamps[index]),
      };
    }
  }

  return { price: null, timestamp: null };
}

function inferUsMarketStatus(meta) {
  const now = Math.floor(Date.now() / 1000);
  const regular = meta?.currentTradingPeriod?.regular;

  if (
    Number.isFinite(regular?.start) &&
    Number.isFinite(regular?.end) &&
    now >= regular.start &&
    now <= regular.end
  ) {
    return "OPEN";
  }

  return "CLOSE";
}

function parseNumber(value) {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }

  if (value === null || value === undefined) {
    return null;
  }

  const normalized = String(value)
    .replace(/,/g, "")
    .replace(/[^\d.+-]/g, "")
    .trim();

  if (!normalized) return null;

  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

function parseInteger(value) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  return Number.isFinite(parsed) ? parsed : null;
}

function providerHeaders(referer) {
  return {
    Accept: "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
    Referer: referer,
    "User-Agent":
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " +
      "AppleWebKit/537.36 (KHTML, like Gecko) " +
      "Chrome/149.0.0.0 Safari/537.36",
  };
}

async function fetchJson(url, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(
    () => controller.abort("provider timeout"),
    FETCH_TIMEOUT_MS,
  );

  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
      redirect: "follow",
      cf: {
        cacheTtl: 15,
        cacheEverything: true,
      },
    });

    if (!response.ok) {
      throw new Error(
        `HTTP ${response.status} ${response.statusText || ""}`.trim(),
      );
    }

    return await response.json();
  } finally {
    clearTimeout(timeout);
  }
}

async function mapWithConcurrency(items, concurrency, mapper) {
  const results = new Array(items.length);
  let nextIndex = 0;

  async function worker() {
    while (true) {
      const index = nextIndex;
      nextIndex += 1;

      if (index >= items.length) return;

      results[index] = await mapper(items[index], index);
    }
  }

  const workerCount = Math.max(
    1,
    Math.min(concurrency, items.length),
  );

  await Promise.all(
    Array.from({ length: workerCount }, () => worker()),
  );

  return results;
}
