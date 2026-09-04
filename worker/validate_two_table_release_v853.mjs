// Exercise the unchanged deployed V1.4.0 source against actual production data.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { webcrypto } from 'node:crypto';

const repo = process.argv[2]; assert.ok(repo);
const read = n => fs.readFileSync(path.join(repo, n));
const status = JSON.parse(read('api/status.json'));
const manifest = JSON.parse(read('api/two_table_v1/manifest.json'));
assert.equal(manifest.version, '2026-09-04-v8.5.3-two-table-layout-release');
assert.equal(manifest.status, 'READY', 'Use fresh source data for production integration tests');
const baseline = new Map(['api/status.json', 'api/two_table_v1/manifest.json', 'config/krx_market_holidays.json',
  ...Object.keys(manifest.files).map(n => 'api/two_table_v1/' + n)].map(n => [n, read(n)]));
const source = read('worker/krx-live-price-worker.js').toString();
const load = new Function('fetch', 'Date', 'crypto', source.replace('export default {', 'const worker = {') + '\nreturn worker;');
let count = 0;
function setup() {
  const files = new Map(baseline);
  class Clock extends Date {
    constructor(...a) { super(...(a.length ? a : [status.runtime_freshness_gate.evaluated_at_kst])); }
    static now() { return new Clock().getTime(); }
  }
  const worker = load(async input => {
    const u = new URL(String(input));
    assert.ok(['raw.githubusercontent.com', 'api.github.com'].includes(u.hostname));
    const n = u.pathname.replace(u.hostname === 'raw.githubusercontent.com'
      ? '/sehwankim0114/krx-watchlist-auto/main/' : '/repos/sehwankim0114/krx-watchlist-auto/contents/', '');
    return new Response(files.get(n) || '{}', { status: files.has(n) ? 200 : 404 });
  }, Clock, webcrypto);
  return { files, async get(url) {
    const r = await worker.fetch(new Request('https://worker.invalid' + url));
    const raw = await r.text(); return { response: r, raw, body: JSON.parse(raw) };
  }, update(n, cb) {
    const p = JSON.parse(files.get(n)); cb(p); files.set(n, Buffer.from(JSON.stringify(p)));
  } };
}
async function test(name, fn) { await fn(setup()); count++; console.log('PASS ' + name); }
function rejected(r, code, http = 409) {
  assert.equal(r.response.status, http, r.raw); assert.equal(r.body.error, code, r.raw);
  assert.deepEqual(r.body.rows, []); assert.equal(r.body.safe_to_analyze_as_latest, false);
}
await test('all real production pages exact and complete, no Worker recalculation', async s => {
  for (const table of ['kospi', 'decliners', 'decliners24']) {
    let next = '/tables/v1/' + table; const collected = [];
    for (const name of manifest.tables[table].pages) {
      const r = await s.get(next);
      assert.equal(r.response.status, 200, r.raw);
      assert.ok(Buffer.byteLength(r.raw) <= 30000);
      assert.equal(r.response.headers.get('Cache-Control'), 'no-store');
      assert.equal(r.body.transport.mode, 'production');
      assert.equal(r.body.transport.values_recalculated, false);
      const { transport, ...original } = r.body;
      assert.deepEqual(original, JSON.parse(read('api/two_table_v1/' + name)));
      assert.equal(original.display_contract.coverage, 'PARTIAL_DECLARED');
      assert.equal(original.production_activation_allowed, true);
      collected.push(...r.body.rows); next = transport.next_page_url;
      if (next) assert.equal(new URL(next, 'https://worker.invalid').searchParams.get('build_id'), manifest.source_build_id);
    }
    assert.equal(next, null);
    assert.equal(collected.length, manifest.tables[table].row_count);
    assert.equal(new Set(collected.map(r => r[1])).size, collected.length);
    console.log('V853_PRODUCTION_ROWS=' + table + ':' + collected.length);
  }
});
await test('page two requires pinned build', async s => {
  rejected(await s.get('/tables/v1/decliners?page=2'), 'TWO_TABLE_BUILD_ID_REQUIRED_FOR_NEXT_PAGE', 400);
});
await test('wrong build never mixes pages', async s => {
  rejected(await s.get('/tables/v1/decliners?page=2&build_id=obsolete-build'), 'TWO_TABLE_BUILD_CHANGED_RESTART_PAGE_1');
});
await test('stale source blocks production', async s => {
  s.update('api/status.json', p => { p.official_fresh_now = false; });
  rejected(await s.get('/tables/v1/kospi'), 'TWO_TABLE_OFFICIAL_DATA_NOT_FRESH');
});
await test('unsynchronized source blocks production', async s => {
  s.update('api/status.json', p => { p.api_sync_ok = false; });
  rejected(await s.get('/tables/v1/kospi'), 'TWO_TABLE_SOURCE_NOT_SYNCHRONIZED');
});
await test('source build mismatch blocks production', async s => {
  s.update('api/two_table_v1/manifest.json', p => { p.source_build_id = 'wrong'; });
  rejected(await s.get('/tables/v1/kospi'), 'TWO_TABLE_SOURCE_IDENTITY_MISMATCH');
});
await test('inactive gate never produces rows', async s => {
  s.update('api/two_table_v1/manifest.json', p => { p.production_activation_allowed = false; });
  rejected(await s.get('/tables/v1/kospi'), 'TWO_TABLE_NOT_ACTIVATED');
});
await test('real source checksum required', async s => {
  const n = 'api/two_table_v1/kospi.compact.1.json';
  s.files.set(n, Buffer.concat([s.files.get(n), Buffer.from(' ')]));
  rejected(await s.get('/tables/v1/kospi'), 'TWO_TABLE_PAGE_CHECKSUM_MISMATCH');
});
console.log('V853_PRODUCTION_WORKER_TESTS=' + count);
console.log('V853_UNCHANGED_WORKER_PRODUCTION_INTEGRATION=PASS');
