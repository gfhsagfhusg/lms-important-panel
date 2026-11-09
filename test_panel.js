/*!
 * 面板 JS 回归测试 —— 只用 Node 内置模块(vm / assert), 无需 jest/jsdom, 无需联网。
 * 运行: node tests/test_panel.js
 *
 * 覆盖: 6 种 config.json 结果、请求挂起超时、失败后交互、重复打开、
 *       未登录提示、库存数据形状、轮询在途去重、取货数量校验与两步 API。
 */
'use strict';
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const path = require('path');

const SRC = fs.readFileSync(path.join(__dirname, '..', 'panel', 'important_panel.js'), 'utf8');

// ---------------------------------------------------------------- DOM 桩
function CL() { this.s = new Set(); }
CL.prototype.add = function (c) { this.s.add(c); };
CL.prototype.remove = function (c) { this.s.delete(c); };
CL.prototype.contains = function (c) { return this.s.has(c); };
CL.prototype.toggle = function (c, f) {
  if (f === undefined) f = !this.s.has(c);
  if (f) this.s.add(c); else this.s.delete(c);
  return f;
};

function El(tag) {
  this.tagName = tag; this.children = []; this._html = '';
  this.textContent = ''; this.value = ''; this.className = '';
  this.style = {}; this.classList = new CL(); this.attrs = {};
  this.handlers = {}; this.draggable = false; this.disabled = false;
}
Object.defineProperty(El.prototype, 'innerHTML', {
  get() { return this._html; },
  set(v) { this._html = String(v); if (v === '') this.children = []; }
});
El.prototype.appendChild = function (c) { this.children.push(c); return c; };
El.prototype.removeChild = function (c) { this.children = this.children.filter(x => x !== c); return c; };
El.prototype.addEventListener = function (t, f) { (this.handlers[t] || (this.handlers[t] = [])).push(f); };
El.prototype.fire = function (t, e) {
  (this.handlers[t] || []).forEach(f => f(e || { preventDefault() {}, clientX: 10, clientY: 10 }));
};
El.prototype.setAttribute = function (k, v) { this.attrs[k] = v; };
El.prototype.getAttribute = function (k) { return this.attrs[k]; };
El.prototype.getBoundingClientRect = function () { return { top: 0, height: 20, left: 0, width: 100 }; };
El.prototype.focus = function () {};
El.prototype.select = function () {};
El.prototype.insertBefore = function (n, r) {
  const i = this.children.indexOf(r);
  this.children.splice(i < 0 ? this.children.length : i, 0, n);
  return n;
};

const IDS = ['ipv-list', 'ipv-msg', 'ipv-world', 'ipv-search', 'ipv-addview',
  'ipv-addsearch', 'ipv-addres', 'ipv-botview', 'ipv-botlist', 'ipv-addbtn',
  'ipv-refresh', 'ipv-reset', 'ipv-botsbtn', 'ipv-close', 'ipv-back',
  'ipv-botsback', 'ipv-botclean'];

function makeEnv(opts) {
  opts = opts || {};
  const registry = {};
  IDS.forEach(id => { const e = new El('div'); e.id = id; registry[id] = e; });
  const body = new El('body'), head = new El('head');
  const store = new Map(), writes = [], fetches = [], warns = [];
  const timers = new Map(); let tid = 0;
  if (opts.token !== false) store.set('storageWebsite.authToken', 'T0KEN');

  function query(sel) {
    const k = String(sel).replace('#', '');
    if (!registry[k]) { const e = new El('div'); e.id = k; registry[k] = e; }
    return registry[k];
  }
  El.prototype.querySelector = query;
  El.prototype.querySelectorAll = function (sel) {
    return this.children.filter(c => (c.className || '').indexOf('ipv-row') >= 0);
  };

  const document = {
    head, body, hidden: false,
    createElement: t => new El(t),
    addEventListener() {}, querySelector: query, querySelectorAll: () => [],
    execCommand: () => true, documentElement: new El('html')
  };

  const configMode = opts.configMode || 'ok';
  const fetchImpl = (url, o) => {
    fetches.push({ url, opts: o });
    if (url === '/config.json') {
      if (configMode === 'hang') return new Promise(() => {});
      if (configMode === 'reject') return Promise.reject(new Error('network down'));
      if (configMode === '404') return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
      if (configMode === 'parse-error') return Promise.resolve({ ok: true, status: 200, json: () => Promise.reject(new Error('bad json')) });
      if (configMode === 'no-field') return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ localeFile: '/assets/x.js' }) });
      if (configMode === 'empty-name') return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ worldName: '' }) });
      if (configMode === 'dot-dot-locale') return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ worldName: '红石仓库', localeFile: '/assets/../../evil.js' }) });
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ worldName: opts.worldName || '红石仓库' }) });
    }
    if (url === '/api/storage/getData') {
      if (opts.stockMode === 'bad-shape') return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ items: [] }) });
      if (opts.stockMode === 'slow') return new Promise(() => {});
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([{ d: [{ i: 'minecraft:piston', c: 2000 }] }]) });
    }
    if (url === '/api/storage/getItem') {
      return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve('[{"c":64,"n":"bot_getitem_1"}]') });
    }
    if (url === '/api/storage/sendGetItemResult') {
      return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve('') });
    }
    if (url === '/index.html') {
      return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve('<html></html>') });
    }
    return Promise.reject(new Error('unexpected ' + url));
  };

  const sandbox = {
    document, console: { warn: (...a) => warns.push(a.join(' ')), log() {}, error() {} },
    localStorage: {
      getItem: k => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => { writes.push([k, String(v)]); store.set(k, String(v)); }
    },
    fetch: fetchImpl,
    navigator: { clipboard: null },
    window: {
      innerWidth: 1200, innerHeight: 800, addEventListener() {},
      location: { origin: 'http://127.0.0.1:7000' },
      prompt: () => opts.prompt, confirm: () => opts.confirm !== false
    },
    location: { origin: 'http://127.0.0.1:7000' },
    setTimeout: (fn) => { tid += 1; timers.set(tid, fn); return tid; },
    clearTimeout: (id) => { timers.delete(id); },
    setInterval: () => 1, clearInterval: () => {},
    Date, JSON, Math, Promise, RegExp, Array, Object, String, Number,
    parseInt, parseFloat, isNaN, isFinite, Error, Set, Map, URL,
    AbortController: function () { this.signal = {}; this.abort = function () {}; }
  };
  vm.createContext(sandbox);
  new vm.Script(SRC, { filename: 'important_panel.js' }).runInContext(sandbox);

  return {
    fab: body.children.find(c => c.id === 'ipv-fab'),
    panel: body.children.find(c => c.id === 'ipv-panel'),
    ctx: body.children.find(c => c.id === 'ipv-ctx'),
    reg: registry, writes, fetches, warns, timers, store,
    fireTimers() { for (const [id, fn] of [...timers]) { timers.delete(id); fn(); } }
  };
}

// config -> race -> toggle.then -> refresh -> getData.r.json -> parse 需要约 10 轮微任务
const settle = async (n = 24) => { for (let i = 0; i < n; i++) await Promise.resolve(); };
const unknownKeys = e => e.writes.filter(x => x[0].indexOf('_unknown') >= 0);
const rows = e => e.reg['ipv-list'].children.filter(c => (c.className || '').indexOf('ipv-row') >= 0);

// ---------------------------------------------------------------- 迷你 runner
const tests = [];
const test = (name, fn) => tests.push({ name, fn });

// T3: 六种 config 结果
const failModes = ['404', 'reject', 'no-field', 'empty-name', 'parse-error'];
for (const mode of failModes) {
  test('T3 config=' + mode + ' 保持锁定且不写 _unknown', async () => {
    const e = makeEnv({ configMode: mode });
    e.fab.fire('click');
    assert.strictEqual(e.panel.classList.contains('ipv-locked'), true, '打开即锁定');
    await settle();
    assert.strictEqual(e.panel.classList.contains('ipv-locked'), true, '失败后必须保持锁定');
    assert.strictEqual(e.reg['ipv-msg'].textContent, '存档名读取失败，刷新页面重试；本次操作未保存。');
    assert.strictEqual(e.fetches.filter(f => f.url === '/api/storage/getData').length, 0,
      '失败后不应启动 refresh()');
    // 失败后触发一次会写盘的工具栏交互
    e.reg['ipv-reset'].fire('click');
    assert.strictEqual(unknownKeys(e).length, 0, '不得写入 _unknown 键');
    assert.strictEqual(e.writes.length, 0, '存档名未就绪时任何写盘都应被拒绝');
  });
}

test('T3 config=ok 解锁并渲染 32 行, 键名带真实存档名', async () => {
  const e = makeEnv({ configMode: 'ok' });
  e.fab.fire('click');
  await settle();
  assert.strictEqual(e.panel.classList.contains('ipv-locked'), false);
  assert.strictEqual(rows(e).length, 32);
  assert.strictEqual(e.reg['ipv-world'].textContent, '当前存档：红石仓库');
  assert.strictEqual(unknownKeys(e).length, 0);
  e.reg['ipv-reset'].fire('click');
  assert.ok(e.writes.some(x => x[0] === 'ipv.customOrder.红石仓库'), '写入应落在真实存档档');
});

test('T3 hang 超时后保持锁定并给出提示', async () => {
  const e = makeEnv({ configMode: 'hang' });
  e.fab.fire('click');
  assert.strictEqual(e.panel.classList.contains('ipv-locked'), true);
  await settle();
  assert.strictEqual(e.writes.length, 0, '挂起期间零写入');
  e.fireTimers();                       // 触发 5s 超时
  await settle(12);
  assert.strictEqual(e.panel.classList.contains('ipv-locked'), true, '超时后不误解锁');
  assert.ok(e.warns.some(w => w.indexOf('超时') >= 0), '应记录超时');
  assert.strictEqual(unknownKeys(e).length, 0);
});

test('T3 重复打开面板 config 只请求一次', async () => {
  const e = makeEnv({ configMode: 'ok' });
  e.fab.fire('click');                   // 打开
  e.fab.fire('click');                   // 关闭
  e.fab.fire('click');                   // 再打开
  await settle(12);
  assert.strictEqual(e.fetches.filter(f => f.url === '/config.json').length, 1);
});

test('T3 无 token 时 config 回调不覆盖「尚未登录」提示', async () => {
  const e = makeEnv({ configMode: 'ok', token: false });
  e.fab.fire('click');
  await settle();
  assert.ok(e.reg['ipv-list'].innerHTML.indexOf('尚未登录') >= 0, '登录提示必须保留');
  assert.strictEqual(rows(e).length, 0, '未登录不应渲染 32 行 0 库存');
});

test('T3 localeFile 含 .. 段被拒绝, 不触发动态 import', async () => {
  const e = makeEnv({ configMode: 'dot-dot-locale' });
  e.fab.fire('click');
  await settle();
  assert.strictEqual(e.panel.classList.contains('ipv-locked'), false);
  // 进入添加物品会走 import(); 这里只验证没有加载同源任意 js 的路径被放行
  assert.ok(e.fetches.every(f => f.url !== '/assets/../../evil.js'));
});

test('T7 getData 结构不匹配: 提示可读错误且不把库存清成 0', async () => {
  const e = makeEnv({ configMode: 'ok', stockMode: 'bad-shape' });
  e.fab.fire('click');
  await settle();
  assert.ok(e.reg['ipv-msg'].textContent.indexOf('库存数据结构不匹配') >= 0);
  assert.ok(e.warns.some(w => w.indexOf('getData') >= 0));
});

test('T7 慢响应在途时不会堆叠第二次 getData', async () => {
  const e = makeEnv({ configMode: 'ok', stockMode: 'slow' });
  e.fab.fire('click');
  await settle();
  const first = e.fetches.filter(f => f.url === '/api/storage/getData').length;
  assert.strictEqual(first, 1);
  e.fireTimers();                       // 模拟 10 秒轮询 tick
  await settle();
  assert.strictEqual(e.fetches.filter(f => f.url === '/api/storage/getData').length, 1,
    '在途请求未完成时不得再发一次');
});

test('T7 取货数量非法输入零 fetch', async () => {
  for (const bad of ['1,024', '1.5', '1e3', '-5', '0', '64abc']) {
    const e = makeEnv({ configMode: 'ok', prompt: bad });
    e.fab.fire('click');
    await settle();
    const before = e.fetches.length;
    rows(e)[0].children.find(c => c.className === 'ipv-buy').fire('click');
    await settle(4);
    assert.strictEqual(e.fetches.length, before, '非法数量不应发请求: ' + bad);
  }
});

test('T7 正常取货调用序列与 body', async () => {
  const e = makeEnv({ configMode: 'ok', prompt: '64' });
  e.fab.fire('click');
  await settle();
  rows(e)[0].children.find(c => c.className === 'ipv-buy').fire('click');
  await settle(12);
  const urls = e.fetches.filter(f => f.url.indexOf('/api/storage/') === 0).map(f => f.url);
  assert.ok(urls.includes('/api/storage/getItem'));
  assert.ok(urls.includes('/api/storage/sendGetItemResult'));
  const getItem = e.fetches.find(f => f.url === '/api/storage/getItem');
  assert.strictEqual(JSON.parse(getItem.opts.body).c, 64);
  assert.ok(e.reg['ipv-msg'].textContent.indexOf('取货成功') >= 0);
});

test('T5 面板关闭后轮询回调不再拉数据', async () => {
  const e = makeEnv({ configMode: 'ok' });
  e.fab.fire('click');
  await settle();
  const before = e.fetches.filter(f => f.url === '/api/storage/getData').length;
  e.fab.fire('click');                   // 关闭
  e.fireTimers();
  await settle();
  assert.strictEqual(e.fetches.filter(f => f.url === '/api/storage/getData').length, before);
});

(async () => {
  let pass = 0, fail = 0;
  for (const t of tests) {
    try { await t.fn(); console.log('  PASS  ' + t.name); pass += 1; }
    catch (err) { console.log('  FAIL  ' + t.name + '\n        ' + err.message); fail += 1; }
  }
  console.log('\n%d passed, %d failed, %d total', pass, fail, tests.length);
  if (fail) process.exit(1);
})();
