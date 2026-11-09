/*!
 * 重要物品专栏 (Important Items Panel) v1.1.0
 * 为 Carpet-LMS-Addition 仓储网站提供「重要物品」侧栏:
 *   - 按红石机器用量预排序的物品清单, 可拖动/搜索/增删/高亮(按存档记忆)
 *   - 库存每 10 秒刷新, 低于一箱(1728)标红
 *   - 一键取货: 复用网站登录态调用 /api/storage/getItem + sendGetItemResult
 * 适配: Carpet-LMS-Addition v1.15.0 (Minecraft Java 26.1.2)
 * 安装: 由 install.py 自动注入到 customStorageWebsite/index.html
 * 许可: MIT (见仓库 LICENSE)
 */
(function () {
  'use strict';
  var LS_TOKEN = 'storageWebsite.authToken'; // LMS v1.15.0 原站的登录 token 键名
  var ONE_STACK = 1728; // 缺货阈值: 一箱(27x64)。可按需修改。
  var CONFIG_TIMEOUT_MS = 5000; // config.json 超时: 防止请求挂起时面板永久锁定
  var COLORS = [
    'white', 'orange', 'magenta', 'light_blue', 'yellow', 'lime', 'pink', 'gray',
    'light_gray', 'cyan', 'purple', 'blue', 'brown', 'green', 'red', 'black'
  ];
  var RANKING = [
    { zh: '黏液块', ids: ['minecraft:slime_block'] },
    { zh: '活塞', ids: ['minecraft:piston'] },
    { zh: '侦测器', ids: ['minecraft:observer'] },
    { zh: '红石块', ids: ['minecraft:redstone_block'] },
    { zh: '箱子', ids: ['minecraft:chest'] },
    { zh: '蜂蜜块', ids: ['minecraft:honey_block'] },
    { zh: '漏斗', ids: ['minecraft:hopper'] },
    { zh: '红石火把', ids: ['minecraft:redstone_torch', 'minecraft:redstone_wall_torch'] },
    { zh: '粘性活塞', ids: ['minecraft:sticky_piston'] },
    { zh: '潜影盒', ids: ['minecraft:shulker_box'].concat(COLORS.map(function (c) { return 'minecraft:' + c + '_shulker_box'; })) },
    { zh: 'TNT', ids: ['minecraft:tnt'] },
    { zh: '木桶', ids: ['minecraft:barrel'] },
    { zh: '充能铁轨', ids: ['minecraft:powered_rail'] },
    { zh: '目标块', ids: ['minecraft:target'] },
    { zh: '投掷器', ids: ['minecraft:dropper'] },
    { zh: '音符盒', ids: ['minecraft:note_block'] },
    { zh: '激活铁轨', ids: ['minecraft:activator_rail'] },
    { zh: '探测铁轨', ids: ['minecraft:detector_rail'] },
    { zh: '发射器', ids: ['minecraft:dispenser'] },
    { zh: '铁轨', ids: ['minecraft:rail'] },
    { zh: '石质按钮', ids: ['minecraft:stone_button'] },
    { zh: '红石灯', ids: ['minecraft:redstone_lamp'] },
    { zh: '中继器', ids: ['minecraft:repeater'] },
    { zh: '比较器', ids: ['minecraft:comparator'] },
    { zh: '绊线钩', ids: ['minecraft:tripwire_hook'] },
    { zh: '红石粉', ids: ['minecraft:redstone', 'minecraft:redstone_wire'] },
    { zh: '末影箱', ids: ['minecraft:ender_chest'] },
    { zh: '拉杆', ids: ['minecraft:lever'] },
    { zh: '合成器', ids: ['minecraft:crafter'] },
    { zh: '压力板', ids: [
      'minecraft:oak_pressure_plate', 'minecraft:birch_pressure_plate',
      'minecraft:cherry_pressure_plate', 'minecraft:pale_oak_pressure_plate',
      'minecraft:stone_pressure_plate', 'minecraft:polished_blackstone_pressure_plate',
      'minecraft:light_weighted_pressure_plate', 'minecraft:heavy_weighted_pressure_plate'
    ] },
    { zh: '铜灯', ids: [
      'minecraft:copper_bulb', 'minecraft:exposed_copper_bulb',
      'minecraft:weathered_copper_bulb', 'minecraft:oxidized_copper_bulb',
      'minecraft:waxed_copper_bulb', 'minecraft:waxed_exposed_copper_bulb',
      'minecraft:waxed_weathered_copper_bulb', 'minecraft:waxed_oxidized_copper_bulb'
    ] },
    { zh: '木按钮', ids: ['minecraft:oak_button', 'minecraft:birch_button', 'minecraft:polished_blackstone_button'] }
  ];
  var P = 'ipv.';
  function lsKey(suffix) { return P + suffix + '.' + (worldName || '_unknown'); }
  function lsGet(k, d) { try { return JSON.parse(localStorage.getItem(k) || d); } catch (e) { return JSON.parse(d); } }
  // 数据层守卫: worldName 未就绪时拒绝一切写盘, 从根上杜绝 ipv.*._unknown 串档。
  // 返回是否真的写入; 调用方据此决定是否显示「操作成功」文案。
  function lsSet(k, v) {
    if (!worldName) return false;
    try { localStorage.setItem(k, JSON.stringify(v)); return true; } catch (e) { return false; }
  }

  function norm(id) { return id.indexOf(':') >= 0 ? id : 'minecraft:' + id; }
  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function fmt(n) { return (n || 0).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ','); }
  function token() { try { return localStorage.getItem(LS_TOKEN) || ''; } catch (e) { return ''; } }

  var css = [
    '#ipv-fab{position:fixed;right:0;top:42%;z-index:2147483000;padding:10px 8px;border:none;border-radius:8px 0 0 8px;',
    'background:linear-gradient(180deg,#ff9d2e,#f4741f);color:#fff;font-size:13px;font-weight:700;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.25);}',
    '#ipv-mask{display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:2147482999;} #ipv-mask.open{display:block;}',
    '#ipv-panel{position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);width:min(960px,94vw);height:88vh;z-index:2147483001;',
    'background:#fff;border-radius:14px;box-shadow:0 12px 48px rgba(0,0,0,.35);display:none;flex-direction:column;',
    'font-family:system-ui,-apple-system,"Microsoft YaHei",sans-serif;overflow:hidden;}',
    '#ipv-panel.open{display:flex;}',
    '#ipv-head{padding:14px 18px;background:#f4741f;color:#fff;flex:0 0 auto;position:relative;}',
    '#ipv-head h3{margin:0;font-size:18px;} #ipv-head .sub{font-size:12px;opacity:.92;margin-top:3px;}',
    '#ipv-close{position:absolute;top:10px;right:12px;border:none;background:rgba(255,255,255,.25);color:#fff;width:28px;height:28px;border-radius:6px;cursor:pointer;font-size:15px;}',
    '#ipv-tools{display:flex;gap:6px;margin-top:10px;flex-wrap:wrap;}',
    '#ipv-tools button{border:none;background:rgba(255,255,255,.25);color:#fff;padding:5px 11px;border-radius:6px;cursor:pointer;font-size:12px;}',
    '#ipv-tools button.ipv-addbtn{background:#fff;color:#e05d00;font-weight:700;}',
    '#ipv-search{flex:1;min-width:180px;border:none;border-radius:6px;padding:6px 10px;font-size:13px;outline:none;}',
    '#ipv-body{flex:1;display:flex;min-height:0;position:relative;}',
    '#ipv-list{flex:1;overflow-y:auto;padding:10px;}',
    '.ipv-row{display:flex;align-items:center;gap:6px;padding:8px 10px;border-radius:8px;margin-bottom:5px;border:1px solid #eee;background:#fafafa;}',
    '.ipv-row.low{background:#ffe1e1;border-color:#f3b0b0;}',
    '.ipv-row.hl{background:#fff7e0;border-color:#f2c14e;box-shadow:inset 4px 0 0 #f2a71b;}',
    '.ipv-row.draggable{cursor:grab;}',
    '.ipv-row.dragging{opacity:.45;outline:2px dashed #f4741f;}',
    '.ipv-handle{flex:0 0 auto;color:#bbb;font-size:14px;user-select:none;cursor:grab;padding:0 2px;}',
    '.ipv-rank{width:24px;text-align:center;font-weight:700;color:#888;font-size:13px;flex:0 0 auto;}',
    '.ipv-name{flex:1 1 auto;min-width:0;} .ipv-name b{font-size:14px;display:block;}',
    '.ipv-name span{font-size:11px;color:#999;display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    '.ipv-stock{flex:0 0 auto;font-size:13px;font-weight:700;text-align:right;min-width:80px;}',
    '.ipv-row.low .ipv-stock{color:#c62828;}',
    '.ipv-buy{flex:0 0 auto;border:none;background:#f4741f;color:#fff;padding:5px 11px;border-radius:6px;cursor:pointer;font-size:12px;}',
    '.ipv-buy:disabled{background:#ccc;cursor:not-allowed;}',
    '.ipv-msg{font-size:12px;padding:6px 12px;color:#555;white-space:pre-wrap;border-top:1px solid #eee;flex:0 0 auto;min-height:28px;}',
    '.ipv-empty{color:#999;font-size:13px;text-align:center;padding:18px 0;}',
    '#ipv-addview{display:none;flex:1;flex-direction:column;min-height:0;}',
    '#ipv-addbar{display:flex;gap:6px;padding:10px;align-items:center;}',
    '#ipv-addbar button{border:none;background:#eee;color:#444;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:13px;}',
    '#ipv-addsearch{flex:1;border:1px solid #ddd;border-radius:6px;padding:7px 11px;font-size:14px;outline:none;}',
    '#ipv-addres{flex:1;overflow-y:auto;padding:0 10px 10px;}',
    '.ipv-arow{display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:8px;margin-bottom:4px;border:1px solid #eee;background:#fafafa;cursor:pointer;}',
    '.ipv-arow:hover{background:#fff3e5;border-color:#f2b56a;}',
    '.ipv-arow b{font-size:14px;flex:0 0 auto;} .ipv-arow span{font-size:11px;color:#999;flex:1 1 auto;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}',
    '.ipv-arow .ipv-added{color:#2e7d32;font-weight:700;font-size:12px;flex:0 0 auto;}',
    '.ipv-arow .ipv-plus{color:#f4741f;font-weight:700;font-size:13px;flex:0 0 auto;}',
    '#ipv-botview{display:none;flex:1;flex-direction:column;min-height:0;}',
    '#ipv-botbar{display:flex;gap:8px;padding:10px;align-items:center;flex-wrap:wrap;}',
    '#ipv-botbar button{border:none;background:#eee;color:#444;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:13px;}',
    '#ipv-botbar .ipv-bothint{font-size:12px;color:#777;line-height:1.5;}',
    '#ipv-botlist{flex:1;overflow-y:auto;padding:0 10px 10px;}',
    '.ipv-botrow{display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:8px;margin-bottom:5px;border:1px solid #eee;background:#fafafa;flex-wrap:wrap;}',
    '.ipv-botrow.new{border-color:#f2b56a;background:#fff7ee;}',
    '.ipv-botname{font-family:ui-monospace,Consolas,monospace;font-size:13px;font-weight:700;color:#333;}',
    '.ipv-botwhat{font-size:13px;color:#444;flex:1 1 160px;min-width:120px;}',
    '.ipv-bottime{font-size:11px;color:#999;}',
    '.ipv-botrow button{border:1px solid #f0b878;background:#fff;color:#c25a00;padding:4px 9px;border-radius:6px;cursor:pointer;font-size:12px;}',
    '.ipv-botrow button:hover{background:#fff2e2;}',
    '#ipv-ctx{position:fixed;z-index:2147483002;display:none;flex-direction:column;background:#fff;border:1px solid #ddd;border-radius:8px;box-shadow:0 6px 24px rgba(0,0,0,.25);padding:4px;min-width:130px;}',
    '#ipv-ctx button{border:none;background:none;text-align:left;padding:8px 12px;border-radius:6px;cursor:pointer;font-size:13px;color:#333;}',
    '#ipv-ctx button:hover{background:#f5f5f5;} #ipv-ctx button.danger{color:#c62828;}',
    '#ipv-panel.ipv-locked #ipv-body,',
    '#ipv-panel.ipv-locked #ipv-tools button:not(#ipv-close),',
    '#ipv-panel.ipv-locked #ipv-tools input{opacity:.55;pointer-events:none;}'
  ].join('');
  var style = document.createElement('style'); style.textContent = css; document.head.appendChild(style);

  var fab = document.createElement('button'); fab.id = 'ipv-fab'; fab.textContent = '⭐ 重要物品';
  var mask = document.createElement('div'); mask.id = 'ipv-mask';
  var panel = document.createElement('div'); panel.id = 'ipv-panel';
  panel.innerHTML =
    '<div id="ipv-head"><h3>⭐ 重要物品专栏</h3><div class="sub" id="ipv-world">当前存档：…</div>' +
    '<div id="ipv-tools"><input id="ipv-search" type="search" placeholder="搜索物品（中文名或 id）…">' +
    '<button id="ipv-addbtn" class="ipv-addbtn">＋ 添加物品</button>' +
    '<button id="ipv-refresh">刷新库存</button><button id="ipv-reset">默认排序</button>' +
    '<button id="ipv-botsbtn">🧰 找回</button>' +
    '<button id="ipv-close">✕</button></div></div>' +
    '<div id="ipv-body"><div id="ipv-list"></div>' +
    '<div id="ipv-addview"><div id="ipv-addbar"><button id="ipv-back">← 返回专栏</button>' +
    '<input id="ipv-addsearch" type="search" placeholder="搜索现版本全部物品（中文名或 id），点击结果直接添加…"></div>' +
    '<div id="ipv-addres"></div></div>' +
    '<div id="ipv-botview"><div id="ipv-botbar"><button id="ipv-botsback">← 返回专栏</button>' +
    '<button id="ipv-botclean">复制「全部倒出来」命令</button>' +
    '<div class="ipv-bothint">取货假人取完就下线，物品存在它身上不会丢。点下面对应的按钮复制命令，粘到游戏聊天框回车即可。<br>' +
    '批量回收：<b>/cleanGetItemBot clean 1000</b> 会把所有「身上还有物品」的假人召到你身边，把东西丢在你脚下。</div></div>' +
    '<div id="ipv-botlist"></div></div></div>' +
    '<div class="ipv-msg" id="ipv-msg"></div>';
  document.body.appendChild(fab); document.body.appendChild(mask); document.body.appendChild(panel);
  var listEl = panel.querySelector('#ipv-list'), msgEl = panel.querySelector('#ipv-msg'),
    worldEl = panel.querySelector('#ipv-world'), searchEl = panel.querySelector('#ipv-search'),
    addView = panel.querySelector('#ipv-addview'), addSearch = panel.querySelector('#ipv-addsearch'),
    addRes = panel.querySelector('#ipv-addres'),
    botView = panel.querySelector('#ipv-botview'), botList = panel.querySelector('#ipv-botlist');
  // 存档 / 数据
  var worldName = null, localeFile = null, stocks = {};
  var allItems = null, itemsError = false, lastNewBot = null;
  // UI 模式
  var addMode = false, botMode = false, ctxItem = null;
  // 请求 / 计时
  var worldInFlight = null, dataInFlight = false;
  var timer = null, lastRender = null, lastFetch = 0, searchTimer = null, addTimer = null;

  var ctx = document.createElement('div'); ctx.id = 'ipv-ctx'; document.body.appendChild(ctx);
  function hideCtx() { ctx.style.display = 'none'; }
  document.addEventListener('click', hideCtx);
  document.addEventListener('scroll', hideCtx, true);
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') { hideCtx(); if (addMode) exitAdd(); } });
  function showCtx(x, y, item) {
    ctxItem = item;
    var hl = isHl(item.zh);
    ctx.innerHTML = '';
    var bh = document.createElement('button');
    bh.textContent = hl ? '☆ 取消高亮' : '⭐ 开启高亮';
    bh.addEventListener('click', function () { if (toggleHl(ctxItem.zh)) render(); hideCtx(); });
    var bd = document.createElement('button');
    bd.textContent = '🗑 删除物品'; bd.className = 'danger';
    bd.addEventListener('click', function () { removeItem(ctxItem); hideCtx(); });
    ctx.appendChild(bh); ctx.appendChild(bd);
    ctx.style.display = 'flex';
    var mw = 150, mh = 90;
    ctx.style.left = Math.min(x, window.innerWidth - mw - 8) + 'px';
    ctx.style.top = Math.min(y, window.innerHeight - mh - 8) + 'px';
  }

  function lsList(suffix) { return lsGet(lsKey(suffix), '[]'); }
  function isHl(zh) { return lsList('highlights').indexOf(zh) >= 0; }
  function toggleHl(zh) {
    var a = lsList('highlights'), i = a.indexOf(zh);
    if (i >= 0) a.splice(i, 1); else a.push(zh);
    if (!lsSet(lsKey('highlights'), a)) { showWorldError(); return false; }
    return true;
  }
  function currentItems() {
    var deleted = lsList('deleted'), customs = lsList('customItems');
    var byZh = {};
    RANKING.forEach(function (it) { if (deleted.indexOf(it.zh) < 0) byZh[it.zh] = it; });
    customs.forEach(function (c) { if (!byZh[c.zh]) byZh[c.zh] = { zh: c.zh, ids: [c.id], custom: true }; });
    return byZh;
  }
  function orderedRanking() {
    var byZh = currentItems();
    var out = [];
    lsList('customOrder').forEach(function (zh) { if (byZh[zh]) { out.push(byZh[zh]); delete byZh[zh]; } });
    Object.keys(byZh).forEach(function (zh) { out.push(byZh[zh]); });
    return out;
  }
  function stockOf(item) {
    var t = 0; item.ids.forEach(function (id) { t += stocks[id] || 0; });
    return t;
  }
  // 取货时用库存最多的那个变体; render() 与 syncStocks() 共用同一口径。
  function bestIdOf(item) {
    var total = stockOf(item), bestId = null, best = -1;
    item.ids.forEach(function (id) { var v = stocks[id] || 0; if (v > best) { best = v; bestId = id; } });
    return { total: total, bestId: bestId };
  }

  // UI 层: 存档名读取失败时的统一反馈。数据层守卫只负责拒绝写盘,
  // 提示集中在这里, 避免把 DOM 职责塞进 lsSet()。
  function showWorldError() {
    worldEl.textContent = '当前存档：读取失败';
    msgEl.textContent = '存档名读取失败，刷新页面重试；本次操作未保存。';
  }
  function setLocked(locked) { panel.classList.toggle('ipv-locked', locked); }
  function showLoginHint() {
    lastRender = null;
    listEl.innerHTML = '<div class="ipv-msg">尚未登录：请先在主页面登录（游戏名 + 密码），登录后本栏自动可用。</div>';
  }

  function toggle(open) {
    panel.classList.toggle('open', open); mask.classList.toggle('open', open);
    if (!open) { setLocked(false); stopTimer(); exitAdd(); exitBots(); return; }
    setLocked(true);   // 存档名没回来之前禁用交互, 免得写到 _unknown 的键上
    loadWorld().then(function () {
      // 面板可能在请求期间被关掉: 不解锁、不刷新、也不启动轮询
      if (!panel.classList.contains('open')) return;
      if (!worldName) { showWorldError(); return; }  // 保持锁定, 且不 refresh/startTimer
      setLocked(false);
      lastRender = null;   // 换存档后渲染签名缓存必须失效
      refresh(); startTimer();
    });
  }
  fab.addEventListener('click', function () { toggle(!panel.classList.contains('open')); });
  mask.addEventListener('click', function () { toggle(false); });
  panel.querySelector('#ipv-close').addEventListener('click', function () { toggle(false); });
  panel.querySelector('#ipv-refresh').addEventListener('click', refresh);
  panel.querySelector('#ipv-reset').addEventListener('click', function () {
    if (!lsSet(lsKey('customOrder'), [])) { showWorldError(); return; }
    searchEl.value = ''; render();
    msgEl.textContent = '已恢复默认排序（按机器用量从高到低）。';
  });
  searchEl.addEventListener('input', function () { clearTimeout(searchTimer); searchTimer = setTimeout(render, 120); });
  panel.querySelector('#ipv-addbtn').addEventListener('click', enterAdd);
  panel.querySelector('#ipv-back').addEventListener('click', exitAdd);
  addSearch.addEventListener('input', function () { clearTimeout(addTimer); addTimer = setTimeout(renderAdd, 120); });
  panel.querySelector('#ipv-botsbtn').addEventListener('click', function () { botMode ? exitBots() : enterBots(); });
  panel.querySelector('#ipv-botsback').addEventListener('click', exitBots);
  panel.querySelector('#ipv-botclean').addEventListener('click', function () {
    copyText('/cleanGetItemBot clean 1000', '已复制 /cleanGetItemBot clean 1000，粘到游戏聊天框回车即可。');
  });

  function startTimer() {
    stopTimer();
    timer = setInterval(function () {
      // 面板已关闭就不再拉数据(关闭动作可能发生在请求飞行期间)
      if (!panel.classList.contains('open')) return;
      // 后台标签页降频: 面板开着但没在看时, 每分钟最多拉一次(减少服务端仓库扫描)
      if (document.hidden && Date.now() - lastFetch < 60000) return;
      refresh();
    }, 10000);
  }
  function stopTimer() { if (timer) { clearInterval(timer); timer = null; } }
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden && panel.classList.contains('open') && !addMode && !botMode) refresh();
  });

  // 只接受「本站根路径下的 .js」: 拦掉 //evil.com/x.js 这种协议相对地址
  function isSameOriginPath(u) {
    if (!/^\/(?!\/)[A-Za-z0-9._\/-]+\.js$/.test(u)) return false;
    var segs = u.slice(0, -3).split('/');
    for (var i = 0; i < segs.length; i++) {
      if (segs[i] === '.' || segs[i] === '..') return false;
    }
    try { return new URL(u, location.origin).origin === location.origin; } catch (e) { return false; }
  }
  function loadWorld() {
    if (worldInFlight) return worldInFlight;   // 合并并发请求; 完成后清空, 下次打开重新读(换存档也能跟上)
    var ctrl = (typeof AbortController === 'function') ? new AbortController() : null;
    var opts = { cache: 'no-store' };
    if (ctrl) opts.signal = ctrl.signal;
    var expired = false, timer = null;
    var timeout = new Promise(function (resolve) {
      timer = setTimeout(function () { resolve('timeout'); }, CONFIG_TIMEOUT_MS);
    });
    var request = fetch('/config.json', opts)
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (c) {
        if (expired) return;
        worldName = (c && c.worldName) ? c.worldName : null;
        var lf = (c && c.localeFile) || '';
        localeFile = isSameOriginPath(lf) ? lf : null;
        if (!worldName) return;              // 保持锁定态, 不渲染 0 库存
        worldEl.textContent = '当前存档：' + worldName;
        lastRender = null;                   // 换存档后渲染签名缓存必须失效
        render(); renderAdd();
      })
      .catch(function (e) {
        if (expired) return;
        worldName = null; localeFile = null;
        console.warn('[重要物品] 读取 config.json 失败:', e && e.message ? e.message : e);
      });
    worldInFlight = Promise.race([request, timeout]).then(function (r) {
      clearTimeout(timer);
      if (r === 'timeout') {
        expired = true;
        if (ctrl) ctrl.abort();
        worldName = null; localeFile = null;
        console.warn('[重要物品] 读取 config.json 超时');
      }
      worldInFlight = null;
    });
    return worldInFlight;
  }

  // 中文物品库: install.py 会在 config.json 写入 localeFile(随 jar 版本自动匹配);
  // 手动安装时回退: 从 index.html 引用的入口 chunk 里嗅探 zh_cn-*.js。都失败则显示物品 id。
  function importLocale(url) {
    return import(url).then(function (m) {
      var map = m && (m.default || m);
      if (map && typeof map === 'object' && Object.keys(map).length >= 100) return map;
      throw new Error('not a locale map: ' + url);
    });
  }
  function loadAllItems() {
    if (allItems) return Promise.resolve(allItems);
    var attempt = localeFile
      ? importLocale(localeFile)
      : fetch('/index.html', { cache: 'no-store' }).then(function (r) { return r.text(); }).then(function (html) {
          var m = html.match(/assets\/zh_cn-[A-Za-z0-9._-]+\.js/);
          if (!m) throw new Error('locale chunk not found in index.html');
          return importLocale('/' + m[0]);
        });
    return Promise.resolve(attempt).then(function (map) {
      allItems = Object.keys(map).map(function (k) { return { id: 'minecraft:' + k, zh: map[k] }; });
      itemsError = false;
      return allItems;
    }).catch(function () {
      allItems = null;      // 保持 null: 下次进入「添加物品」还能重试
      itemsError = true;
      return [];
    });
  }

  function enterAdd() {
    addMode = true; botMode = false; botView.style.display = 'none';
    addView.style.display = 'flex'; listEl.style.display = 'none';
    msgEl.textContent = '输入关键字搜索现版本全部物品，点击结果行即加入专栏；右键专栏物品可高亮/删除。';
    loadAllItems().then(function () { addSearch.focus(); renderAdd(); });
    renderAdd();
  }
  function exitAdd() {
    addMode = false; addView.style.display = 'none'; listEl.style.display = botMode ? 'none' : 'block';
    if (!botMode) render();
  }

  function botLog() { return lsList('bots'); }
  function saveBotLog(a) { return lsSet(lsKey('bots'), a.slice(0, 60)); }
  function copyText(text, okMsg) {
    function done() { msgEl.textContent = okMsg; }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, function () { fallback(); });
    } else { fallback(); }
    function fallback() {
      var ta = document.createElement('textarea');
      ta.value = text; ta.style.position = 'fixed'; ta.style.left = '-9999px';
      document.body.appendChild(ta); ta.select();
      try { if (document.execCommand('copy')) done(); else throw new Error('copy-failed'); } catch (e) { msgEl.textContent = '复制失败，请手动输入：' + text; }
      document.body.removeChild(ta);
    }
  }
  function enterBots() {
    botMode = true; addMode = false; addView.style.display = 'none';
    botView.style.display = 'flex'; listEl.style.display = 'none';
    renderBots();
  }
  function exitBots() {
    if (!botMode) return;
    botMode = false; botView.style.display = 'none'; listEl.style.display = 'block';
    render();
  }
  function renderBots() {
    if (!botMode) return;
    var a = botLog();
    botList.innerHTML = '';
    if (!a.length) {
      botList.innerHTML = '<div class="ipv-empty">这里还没有记录。每取一次货，就会把那个假人的名字记下来（只存在你自己的浏览器里）。</div>';
      return;
    }
    a.forEach(function (e, i) {
      var row = document.createElement('div');
      row.className = 'ipv-botrow' + (lastNewBot && e.n === lastNewBot ? ' new' : '');
      var when = e.t ? new Date(e.t) : null;
      row.innerHTML =
        '<span class="ipv-botname">' + esc(e.n) + '</span>' +
        '<span class="ipv-botwhat">' + esc(e.zh || '') + ' × ' + fmt(e.c) + '</span>' +
        '<span class="ipv-bottime">' + (when ? esc(when.toLocaleString()) : '') + '</span>';
      var b1 = document.createElement('button'); b1.textContent = '复制 [↑] 召唤';
      b1.addEventListener('click', function () { copyText('/player ' + e.n + ' spawn', '已复制 /player ' + e.n + ' spawn，游戏里回车，假人就会上线。'); });
      var b2 = document.createElement('button'); b2.textContent = '复制 [O] 开背包';
      b2.addEventListener('click', function () { copyText('/player ' + e.n + ' inventory', '已复制 /player ' + e.n + ' inventory（假人在线时才能打开背包）。'); });
      var b3 = document.createElement('button'); b3.textContent = '复制 [↓] 下线';
      b3.addEventListener('click', function () { copyText('/player ' + e.n + ' kill', '已复制 /player ' + e.n + ' kill。注意：kill 会让它原地死亡掉落物品。'); });
      row.appendChild(b1); row.appendChild(b2); row.appendChild(b3);
      botList.appendChild(row);
    });
  }
  function renderAdd() {
    if (!addMode) return;
    if (!allItems) {
      if (itemsError) {
        addRes.innerHTML = '<div class="ipv-empty">物品库加载失败。<button id="ipv-retry" style="margin-left:8px;cursor:pointer">重试</button></div>';
        var rb = addRes.querySelector('#ipv-retry');
        if (rb) rb.addEventListener('click', function () { itemsError = false; loadAllItems().then(renderAdd); });
      } else {
        addRes.innerHTML = '<div class="ipv-empty">物品库加载中…</div>';
      }
      return;
    }
    var q = (addSearch.value || '').trim().toLowerCase();
    var added = {};
    orderedRanking().forEach(function (it) { added[it.zh] = true; });
    var res = allItems.filter(function (it) {
      if (!q) return false;
      return it.zh.toLowerCase().indexOf(q) >= 0 || it.id.toLowerCase().indexOf(q) >= 0;
    });
    var cap = res.slice(0, 60), html = '';
    if (!q) html = '<div class="ipv-empty">输入关键字开始搜索（共 ' + allItems.length + ' 种物品）</div>';
    else if (!res.length) html = '<div class="ipv-empty">没有匹配「' + esc(q) + '」的物品</div>';
    addRes.innerHTML = html;
    cap.forEach(function (it) {
      var row = document.createElement('div'); row.className = 'ipv-arow';
      var isIn = !!added[it.zh];
      row.innerHTML = '<b>' + esc(it.zh) + '</b><span>' + esc(it.id) + '</span>' +
        (isIn ? '<i class="ipv-added">已在专栏</i>' : '<i class="ipv-plus">＋ 添加</i>');
      if (!isIn) row.addEventListener('click', function () { addItem(it); });
      addRes.appendChild(row);
    });
    if (res.length > 60) {
      var note = document.createElement('div'); note.className = 'ipv-empty';
      note.textContent = '还有 ' + (res.length - 60) + ' 个结果，请输入更精确的关键字';
      addRes.appendChild(note);
    }
  }
  function addItem(it) {
    if (!worldName) { showWorldError(); return; }
    var customs = lsList('customItems');
    var exists = orderedRanking().some(function (x) { return x.zh === it.zh || x.ids.indexOf(it.id) >= 0; });
    if (exists) { msgEl.textContent = '「' + it.zh + '」已在专栏中。'; return; }
    customs.push({ zh: it.zh, id: it.id });
    var order = lsList('customOrder'); order.push(it.zh);
    if (!lsSet(lsKey('customItems'), customs) || !lsSet(lsKey('customOrder'), order)) {
      showWorldError(); return;
    }
    renderAdd(); render();
    msgEl.textContent = '已添加「' + it.zh + '」（' + it.id + '）到专栏末尾，返回后可拖动调整位置。';
  }
  function removeItem(item) {
    if (!worldName) { showWorldError(); return; }
    var writes = [
      [lsKey('customItems'), item.custom
        ? lsList('customItems').filter(function (c) { return c.zh !== item.zh; })
        : lsList('customItems')],
      [lsKey('deleted'), item.custom
        ? lsList('deleted')
        : lsList('deleted').concat([item.zh])],
      [lsKey('customOrder'), lsList('customOrder').filter(function (zh) { return zh !== item.zh; })],
      [lsKey('highlights'), lsList('highlights').filter(function (zh) { return zh !== item.zh; })]
    ];
    for (var i = 0; i < writes.length; i++) {
      if (!lsSet(writes[i][0], writes[i][1])) { showWorldError(); return; }
    }
    render();
    msgEl.textContent = '已删除「' + item.zh + '」。「默认排序」不会恢复删除项；如需找回默认物品，可用 ＋添加物品 搜索添加。';
  }

  function render() {
    if (addMode || botMode) return;
    if (!token()) { showLoginHint(); return; }  // 没登录就别画 32 行 0 库存
    var q = (searchEl.value || '').trim().toLowerCase();
    var hl = lsList('highlights');               // 每次渲染只读一次 localStorage，不再逐行 isHl()
    var list = orderedRanking().filter(function (it) {
      if (!q) return true;
      if (it.zh.toLowerCase().indexOf(q) >= 0) return true;
      for (var i = 0; i < it.ids.length; i++) if (it.ids[i].toLowerCase().indexOf(q) >= 0) return true;
      return false;
    });
    // 排序/搜索/高亮都没变时只同步数字：避免每次刷新重建整张表（闪烁、打断拖动、白费 DOM 操作）
    var sig = (worldName || '_unknown') + '#' + q + '#' + hl.join('|') + '#'
      + list.map(function (it) { return it.zh; }).join('|');
    if (list.length && lastRender && lastRender.sig === sig && lastRender.rows.length === list.length) {
      syncStocks(lastRender.rows, list);
      renderMsg(list.length, q);
      return;
    }
    listEl.innerHTML = '';
    lastRender = null;
    if (!list.length) {
      listEl.innerHTML = '<div class="ipv-empty">' + (q ? '没有匹配「' + esc(q) + '」的物品' : '专栏为空：点击右上 ＋添加物品 加入物品') + '</div>';
      return;
    }
    var rows = [];
    list.forEach(function (item, i) {
      var s = bestIdOf(item), total = s.total, bestId = s.bestId;
      var idsLabel = item.custom ? item.ids[0] : (item.ids.length > 1 ? '合并 ' + item.ids.length + ' 种变体' : item.ids[0].replace('minecraft:', ''));
      var marked = hl.indexOf(item.zh) >= 0;
      var row = document.createElement('div');
      row.className = 'ipv-row' + (total < ONE_STACK ? ' low' : '') + (marked ? ' hl' : '') + (q ? '' : ' draggable');
      row.draggable = !q;
      row.setAttribute('data-zh', item.zh);
      row.innerHTML =
        '<div class="ipv-handle" title="' + (q ? '清空搜索后可拖动排序' : '拖动调整顺序；右键更多操作') + '">⠿</div>' +
        '<div class="ipv-rank">' + (i + 1) + '</div>' +
        '<div class="ipv-name"><b>' + (marked ? '⭐ ' : '') + esc(item.zh) + '</b><span>' + esc(idsLabel) + '</span></div>';
      var stockEl = document.createElement('div');
      stockEl.className = 'ipv-stock';
      stockEl.textContent = fmt(total);
      row.appendChild(stockEl);
      var entry = { zh: item.zh, total: total, bestId: bestId, row: row, stockEl: stockEl, btn: null };
      var btn = document.createElement('button');
      btn.className = 'ipv-buy'; btn.textContent = '取货';
      btn.disabled = total <= 0;
      // 读 entry.bestId 而不是闭包快照: 变体库存变了也能取到最多的那一种
      btn.addEventListener('click', function () { order(item, entry.bestId, btn); });
      entry.btn = btn;
      row.appendChild(btn);
      row.addEventListener('contextmenu', function (e) {
        e.preventDefault(); showCtx(e.clientX, e.clientY, item);
      });
      listEl.appendChild(row);
      rows.push(entry);
    });
    lastRender = { sig: sig, rows: rows };
    if (!q) bindDnd();
    renderMsg(list.length, q);
  }

  // 只更新数字/红底/按钮可用性, 不动 DOM 结构
  function syncStocks(rows, list) {
    for (var i = 0; i < list.length; i++) {
      var item = list[i], e = rows[i];
      if (!e || e.zh !== item.zh) { lastRender = null; render(); return; }
      var s = bestIdOf(item), total = s.total, bestId = s.bestId;
      e.bestId = bestId;
      if (total !== e.total) {
        e.total = total;
        e.stockEl.textContent = fmt(total);
        e.row.classList.toggle('low', total < ONE_STACK);
        if (e.btn) e.btn.disabled = total <= 0;
      }
    }
  }

  function renderMsg(n, q) {
    var s = q ? '搜索结果 ' + n + ' 项（搜索时不可拖动排序）'
      : '库存每 10 秒自动刷新 · 低于一箱（' + ONE_STACK + '）标红 · 拖 ⠿ 排序 · 右键高亮/删除';
    if (msgEl.textContent !== s) msgEl.textContent = s;   // 文字没变就不碰 DOM
  }

  function bindDnd() {
    var dragged = null;
    Array.prototype.forEach.call(listEl.querySelectorAll('.ipv-row'), function (row) {
      row.addEventListener('dragstart', function (e) {
        dragged = row; row.classList.add('dragging');
        try { e.dataTransfer.setData('text/plain', row.getAttribute('data-zh')); } catch (err) {}
        e.dataTransfer.effectAllowed = 'move';
      });
      row.addEventListener('dragend', function () {
        row.classList.remove('dragging'); dragged = null;
        var order = [];
        Array.prototype.forEach.call(listEl.querySelectorAll('.ipv-row'), function (r) { order.push(r.getAttribute('data-zh')); });
        var rest = orderedRanking().map(function (it) { return it.zh; }).filter(function (zh) { return order.indexOf(zh) < 0; });
        if (!lsSet(lsKey('customOrder'), order.concat(rest))) { showWorldError(); return; }
        render();
        msgEl.textContent = '顺序已保存（按存档分别记忆）。';
      });
      row.addEventListener('dragover', function (e) {
        if (!dragged || dragged === row) return;
        e.preventDefault();
        var rect = row.getBoundingClientRect();
        var before = (e.clientY - rect.top) < rect.height / 2;
        listEl.insertBefore(dragged, before ? row : row.nextSibling);
      });
    });
  }

  // 校验 LMS 返回结构; 不匹配时返回 null, 让调用方保留上一次有效库存并给出可读提示。
  function parseStockData(data) {
    if (!Array.isArray(data)) return null;
    var next = {};
    for (var i = 0; i < data.length; i++) {
      var g = data[i];
      if (!g || !Array.isArray(g.d)) return null;
      for (var j = 0; j < g.d.length; j++) {
        var it = g.d[j];
        if (!it || typeof it.i === 'undefined') return null;
        var c = Number(it.c || 0);
        if (!isFinite(c) || c < 0) return null;
        var id = norm(it.i);
        next[id] = (next[id] || 0) + c;
      }
    }
    return next;
  }

  function refresh() {
    if (dataInFlight) return;            // 慢响应时不堆叠请求, 避免乱序覆盖 stocks
    var t = token();
    if (!t) { showLoginHint(); return; }
    dataInFlight = true;
    fetch('/api/storage/getData', { headers: { 'Authorization': 'Bearer ' + t }, cache: 'no-store' })
      .then(function (r) { if (r.status === 401) throw new Error('登录已过期，请在主页面重新登录'); if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (data) {
        var next = parseStockData(data);
        if (next === null) {
          msgEl.textContent = '库存数据结构不匹配，可能 LMS 版本不兼容（已保留上一次库存）。';
          console.warn('[重要物品] /api/storage/getData 返回结构不符合预期');
          return;
        }
        stocks = next;
        render();
      })
      .catch(function (e) { msgEl.textContent = '加载失败：' + e.message; })
      .then(function () { dataInFlight = false; lastFetch = Date.now(); });
  }

  // 两步取货接口共用 headers 与 401 判定。
  function postJson(url, body, t) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + t, 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      if (r.status === 401) throw new Error('登录已过期，请在主页面重新登录');
      return r.text().then(function (text) {
        if (!r.ok) throw new Error('HTTP ' + r.status + ' ' + text.slice(0, 200));
        return text ? JSON.parse(text) : null;
      });
    });
  }

  function order(item, bestId, btn) {
    var t = token();
    if (!t) { msgEl.textContent = '请先在主页面登录后再取货。'; return; }
    var n = window.prompt('输入取货数量（' + item.zh + '）\n\n注：假人按「整格」搬运，不足一格也会给一整格（1 组 = 64），数量会被向上补齐。', '64');
    if (n === null) return;
    var raw = String(n).trim();
    if (!/^\d+$/.test(raw)) { msgEl.textContent = '数量必须是整数（不能带逗号、小数或科学计数法）。'; return; }
    var c = parseInt(raw, 10);
    if (!c || c <= 0) { msgEl.textContent = '数量无效。'; return; }
    var est = Math.ceil(c / 64) * 64;
    if (!window.confirm('确认取货 ' + c + ' 个「' + item.zh + '」？\n\n' +
        '· 点确定后立刻从仓库搬进假人背包，按整格补齐，实际约 ' + est + ' 个\n' +
        '· 无法撤销：东西会先存在假人身上，网站这边照常扣库存\n' +
        '· 想拿回来：点游戏聊天框的 [↑] 召它上线、[O] 开背包；或本面板右上「🧰 找回」\n' +
        '· 忘了是哪个假人：游戏里输入 /cleanGetItemBot clean 1000，会全部倒在你脚下')) return;
    btn.disabled = true; msgEl.textContent = '正在请求取货…';
    postJson('/api/storage/getItem', { i: bestId, c: c }, t)
      .then(function (bots) {
        var arr = (Array.isArray(bots) ? bots : []).map(function (b) { return { i: bestId, c: b.c, n: b.n }; });
        if (!arr.length) throw new Error('服务器未返回假人信息');
        var got = arr.reduce(function (s, b) { return s + (b.c || 0); }, 0);
        return postJson('/api/storage/sendGetItemResult', arr, t)
          .then(function () { return { got: got, bots: arr }; });
      })
      .then(function (res) {
        var got = res.got;
        var log = botLog();
        res.bots.forEach(function (b) { log.unshift({ n: b.n, zh: item.zh, c: b.c, t: Date.now() }); });
        var logged = saveBotLog(log);
        lastNewBot = res.bots.length ? res.bots[0].n : null;
        if (botMode) renderBots();
        msgEl.textContent = '取货成功！实际取走 ' + got + ' 个（请求 ' + c + ' 个，按整格补齐）。游戏聊天框已出现 [↑][↓][O] 按钮：点 [↑] 假人在你身边上线，[O] 开背包取物品，[↓] 让假人下线。'
          + (logged ? '假人名已记进右上「🧰 找回」。' : '（注意：找回记录未保存，存档名未就绪。）');
        setTimeout(refresh, 1500);
      })
      .catch(function (e) { msgEl.textContent = '取货失败：' + e.message; })
      .then(function () { btn.disabled = false; });
  }
})();
