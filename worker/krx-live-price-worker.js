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
const BUILD_VERSION = "1.3.9-kospi-action-compact-v2";
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
        generated_at: new Date().toISOString(),
      });
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
