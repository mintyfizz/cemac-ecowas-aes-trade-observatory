const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const chartSource = fs.readFileSync(path.join(root, 'static/js/charts.js'), 'utf8');

function render(rows, legacyScopeTotal) {
  const element = { innerHTML: '' };
  const context = vm.createContext({
    window: {},
    document: { getElementById: id => id === 'partner-bars' ? element : null },
  });
  vm.runInContext(chartSource, context);
  // The legacy scope argument reproduces the original whole-bloc threshold bug.
  context.renderPartnerBars(rows, legacyScopeTotal);
  return element.innerHTML;
}

function row(exports, imports) {
  return { counterpart_code: 'TEST', counterpart_name: 'Test fixture',
    exports_billions_usd: exports, imports_billions_usd: imports,
    share_of_world_total_pct: 1 };
}

function widths(html, side) {
  return [...html.matchAll(new RegExp(`class="dbar-${side}-fill" style="width:([^%]+)%"`, 'g'))]
    .map(match => Number(match[1]));
}

test('real ECOWAS 2024 UAE deficit remains visible regardless of whole-bloc size', () => {
  const partners = JSON.parse(fs.readFileSync(path.join(root, 'static/data/bloc_trade_partners.json')));
  const uae = partners.find(r => r.analytical_bloc_code === 'ECOWAS' && r.year === 2024 && r.counterpart_code === 'ARE');
  assert.ok(uae, 'preserved source-backed regression row exists');
  const html = render([uae], 220.336110296);
  assert.match(html, /class="dbar-bal deficit">-\$0\.12B</);
  assert.match(html, /balance -\$123,818,716\.00/);
  assert.doesNotMatch(html, /≈0/);
  assert.equal(html, render([uae], 1));
});

test('small positive and negative balances retain their sign and amount', () => {
  assert.match(render([row(0.001, 0)]), /class="dbar-bal surplus">\+\$1,000,000</);
  assert.match(render([row(0, 0.000001)]), /class="dbar-bal deficit">-\$1,000</);
});

test('reported zero flows draw no bars and an exact zero balance', () => {
  const html = render([row(0, 0)]);
  assert.deepEqual(widths(html, 'imp'), [0]);
  assert.deepEqual(widths(html, 'exp'), [0]);
  assert.match(html, /class="dbar-bal balanced">\$0</);
  assert.doesNotMatch(html, /NaN|Infinity/);
});

test('missing flows stay unavailable and cannot produce a known balance', () => {
  for (const missing of [null, undefined, '', NaN]) {
    const html = render([row(2, missing)]);
    assert.match(html, /class="dbar-imp-val">--</);
    assert.match(html, /class="dbar-bal balanced">unavailable</);
    assert.match(html, /imports unavailable/);
    assert.match(html, /balance unavailable/);
    assert.deepEqual(widths(html, 'imp'), [0]);
    assert.deepEqual(widths(html, 'exp'), [100]);
  }
});

test('small flow bars stay proportional rather than acquiring a minimum width', () => {
  const html = render([row(100, 0), row(0.1, null)]);
  assert.deepEqual(widths(html, 'exp'), [100, 0.1]);
  assert.deepEqual(widths(html, 'imp'), [0, 0]);
});
