# -*- coding: utf-8 -*-
"""
bot_item_watch —— 假人物品积压提醒（MCDR 插件，单文件）

作用：假人「下线」的那一刻检查它背包里还有没有东西。
  - 在线时完全不看：召唤出来忘了拿、人有事走开，都不会播报；
  - 下线时背包是空的 -> 什么都不做；
  - 下线时背包有东西 -> 记下来，之后每 5 分钟把「哪只假人 + 有什么 + 多少」播报一轮，
    整组消息重复 3 遍、每遍间隔 1 秒，全部标红加粗；
  - LMS 自动取货（上线时装满、又自动下线）不算残留：下线件数比上线时多 = 自动交付，跳过不打扰。

原理：LMS 的取货假人取完货就 silenceLogout 下线，物品存在它的玩家数据里
（26.x：saves/<存档>/players/data/<uuid>.dat）。本插件读这些 .dat 的 Inventory，
按 usercache.json 里的 bot_getitem_ 前缀认出假人，实时求和，不依赖网站。

手动查看：游戏里输入 !!biw
重新加载：!!MCDR reload plugin bot_item_watch
"""
import gzip
import json
import os
import re
import struct
import threading
import time
import traceback
import zlib

from mcdreforged.api.all import *

PLUGIN_METADATA = {
    'id': 'bot_item_watch',
    'version': '1.0.0',
    'name': 'Bot Item Watch',
    'description': '假人下线时检查背包，有残留就每 5 分钟播报一次（标红 ×3）',
    'author': ['lms-important-panel'],
    'dependencies': {'mcdreforged': '>=2.0.0'},
}

DEFAULT_CONFIG = {
    "enabled": True,
    "report_interval": 300,     # 每 5 分钟播报一轮（秒）
    "repeat": 3,                # 一轮里整组消息重复几遍
    "repeat_interval": 1.0,     # 每遍之间隔几秒
    "max_chars": 180,           # 单条消息最多多少字符，超出自动拆成 1/n、2/n
    "check_interval": 20,       # 空转时的巡检间隔（收到下线事件会立刻处理）
    "bot_prefix": "bot_getitem_",
    "instance_dir": "..",       # 相对 MCDR 根目录的游戏实例目录
    "world": "",                # 留空 = 自动识别正在玩的存档
}
LEAVE_SETTLE = 1.0  # 假人下线后等游戏写完 .dat 再读（秒）
MAX_GZIP_BYTES = 64 * 1024 * 1024   # 单个 gzip 解压上限, 防压缩炸弹耗尽内存
MAX_NBT_ELEMENTS = 4 * 1024 * 1024  # NBT 数组/列表元素上限

# 共享状态锁: MCDR 事件回调(主线程)写 ONLINE_BOTS / SESSION_START / leave_queue,
# Watcher 线程读并整体替换 leave_queue、增删 residual。统一用一把可重入锁保护,
# 与 _FILE_CACHE_LOCK / _ZH_LOCK 的口径保持一致。
_STATE_LOCK = threading.RLock()


# ---------------- NBT ----------------

class NBTReader:
    def __init__(self, data):
        self.d = data
        self.i = 0

    def _u(self, fmt):
        v = struct.unpack_from(fmt, self.d, self.i)[0]
        self.i += struct.calcsize(fmt)
        return v

    def _str(self):
        n = self._u('>H')
        s = self.d[self.i:self.i + n].decode('utf-8', 'replace')
        self.i += n
        return s

    def payload(self, t):
        if t == 1:
            return self._u('>b')
        if t == 2:
            return self._u('>h')
        if t == 3:
            return self._u('>i')
        if t == 4:
            return self._u('>q')
        if t == 5:
            return self._u('>f')
        if t == 6:
            return self._u('>d')
        if t == 7:
            n = self._u('>i')
            if n < 0 or n > MAX_NBT_ELEMENTS or self.i + n > len(self.d):
                raise ValueError('bad byte array length %d' % n)
            v = self.d[self.i:self.i + n]
            self.i += n
            return v
        if t == 8:
            return self._str()
        if t == 9:
            it = self._u('>b')
            n = self._u('>i')
            if n < 0 or n > MAX_NBT_ELEMENTS:
                raise ValueError('bad list length %d' % n)
            return [self.payload(it) for _ in range(n)]
        if t == 10:
            out = {}
            while True:
                tt = self._u('>b')
                if tt == 0:
                    break
                nm = self._str()
                out[nm] = self.payload(tt)
            return out
        if t == 11:
            n = self._u('>i')
            if n < 0 or n > MAX_NBT_ELEMENTS or self.i + 4 * n > len(self.d):
                raise ValueError('bad int array length %d' % n)
            v = self.d[self.i:self.i + 4 * n]
            self.i += 4 * n
            return list(struct.unpack('>%di' % n, v)) if n else []
        if t == 12:
            n = self._u('>i')
            if n < 0 or n > MAX_NBT_ELEMENTS or self.i + 8 * n > len(self.d):
                raise ValueError('bad long array length %d' % n)
            v = self.d[self.i:self.i + 8 * n]
            self.i += 8 * n
            return list(struct.unpack('>%dq' % n, v)) if n else []
        raise ValueError('bad tag %d at %d' % (t, self.i))


def read_nbt(path):
    with gzip.open(path, 'rb') as f:
        data = f.read(MAX_GZIP_BYTES + 1)
    if len(data) > MAX_GZIP_BYTES:
        raise ValueError('NBT 解压后超过 %d MB: %s' % (MAX_GZIP_BYTES // 1048576, path))
    r = NBTReader(data)
    t = r._u('>b')
    r._str()  # 根节点名（通常为空）
    return r.payload(t)


# ---------------- 找存档 / 数物品 ----------------

def find_active_world(instance_dir, forced=''):
    if forced:
        return forced
    saves = os.path.join(instance_dir, 'saves')
    if not os.path.isdir(saves):
        return None
    # 1) session.lock 被正在运行的服务器占着 —— 最可靠的判据（Windows）
    try:
        import msvcrt
    except ImportError:
        msvcrt = None
    if msvcrt is not None:
        for name in sorted(os.listdir(saves)):
            lock = os.path.join(saves, name, 'session.lock')
            if not os.path.isfile(lock):
                continue
            try:
                with open(lock, 'r+b') as f:
                    f.seek(0)
                    try:
                        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                    except OSError:
                        return name
            except OSError:
                continue
    # 2) 兜底：最近改动的 level.dat
    best, best_t = None, -1
    for name in os.listdir(saves):
        lv = os.path.join(saves, name, 'level.dat')
        if os.path.isfile(lv):
            try:
                m = os.path.getmtime(lv)
            except OSError:
                continue
            if m > best_t:
                best, best_t = name, m
    return best


def load_bot_names(instance_dir, prefix):
    """只返回「名字以 LMS 前缀开头」的假人：{uuid: name}。

    这是本插件唯一的假人筛选口径——usercache.json 里其它假人、小号、
    真实玩家的 uuid 根本不会进入后续统计。
    """
    prefix = (prefix or DEFAULT_CONFIG['bot_prefix']).strip()
    if not prefix:
        return {}
    path = os.path.join(instance_dir, 'usercache.json')
    if not os.path.isfile(path):
        return {}
    try:
        raw = _cached(path, _read_usercache)
    except Exception:
        return {}
    return {u: n for u, n in raw.items() if n.startswith(prefix)}


def _read_usercache(path):
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    return {str(e.get('uuid')): str(e.get('name')) for e in data}


# ---------------- 文件缓存 ----------------
# 玩家数据 / usercache 只有内容变了才重新解析：文件没动就直接用上次的结果。
# 键是 (mtime_ns, size)，改文件立刻失效；条目上限 4096，超出就整体清掉。
_FILE_CACHE = {}
_FILE_CACHE_LOCK = threading.Lock()


def _stat_key(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _cached(path, compute):
    key = _stat_key(path)
    if key is None:
        return compute(path)
    with _FILE_CACHE_LOCK:
        hit = _FILE_CACHE.get(path)
    if hit is not None and hit[0] == key:
        return hit[1]
    value = compute(path)
    with _FILE_CACHE_LOCK:
        if len(_FILE_CACHE) > 4096:
            _FILE_CACHE.clear()
        _FILE_CACHE[path] = (key, value)
    return value


# value = (index 文件签名, 语言表)。签名变了就重新解析; 空表不缓存,
# 避免 on_load 时资源尚未就绪导致「物品名永久退化为 id」。
_ZH_CACHE = {}
_ZH_LOCK = threading.Lock()


def _find_assets_root(instance_dir):
    """往实例目录上层找 assets/indexes（PCL 版本隔离、标准 .minecraft 都覆盖）。"""
    p = os.path.abspath(instance_dir)
    seen = []
    for _ in range(5):
        seen.append(p)
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    for base in seen:
        idx = os.path.join(base, 'assets', 'indexes')
        if os.path.isdir(idx):
            return os.path.join(base, 'assets')
    return None


def _zh_index_sig(files):
    """用 index 文件的 (mtime_ns, size) 组成签名, 资源更新后缓存自动失效。"""
    return tuple((os.path.basename(f), _stat_key(f)) for f in files)


def load_zh(instance_dir):
    """从游戏资源里读 zh_cn 语言表，返回 {物品id: 中文名}；找不到就返回空表。"""
    key = os.path.abspath(instance_dir)
    try:
        assets = _find_assets_root(key)
        indexes = os.path.join(assets, 'indexes') if assets else None
        files = []
        if indexes and os.path.isdir(indexes):
            files = [os.path.join(indexes, n) for n in os.listdir(indexes) if n.endswith('.json')]
            files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    except OSError:
        files = []
    sig = _zh_index_sig(files)
    with _ZH_LOCK:
        hit = _ZH_CACHE.get(key)
        if hit is not None and hit[0] == sig and hit[1]:
            return hit[1]
    table = {}
    try:
        for idx in files[:3]:
            try:
                with open(idx, encoding='utf-8') as f:
                    meta = json.load(f)
            except Exception:
                continue
            h = ((meta.get('objects') or {}).get('minecraft/lang/zh_cn.json') or {}).get('hash')
            if not h:
                continue
            obj = os.path.join(assets, 'objects', h[:2], h)
            if not os.path.isfile(obj):
                continue
            try:
                with open(obj, 'rb') as f:
                    raw = f.read()
                if raw[:2] == b'\x1f\x8b':
                    dec = zlib.decompressobj()
                    raw = dec.decompress(raw, MAX_GZIP_BYTES + 1)
                    if len(raw) > MAX_GZIP_BYTES:
                        continue
                data = json.loads(raw.decode('utf-8'))
            except Exception:
                continue
            for k, v in data.items():
                if k.startswith('item.minecraft.'):
                    table.setdefault(k[15:], v)
                elif k.startswith('block.minecraft.'):
                    table.setdefault(k[16:], v)
            if table:
                break
    except Exception:
        table = {}
    with _ZH_LOCK:
        if table:
            _ZH_CACHE[key] = (sig, table)
        else:
            _ZH_CACHE.pop(key, None)   # 空表不缓存, 下次资源就绪后重试
    return table


def _item_name(item_id, zh=None):
    s = str(item_id or '?')
    if s.startswith('minecraft:'):
        s = s[len('minecraft:'):]
    if zh:
        name = zh.get(s)
        if name:
            return name
    return s


def _short_list(pairs, limit=4):
    pairs = sorted(pairs, key=lambda x: (-x[1], x[0]))
    head = '、'.join('{}×{}'.format(k, v) for k, v in pairs[:limit])
    if len(pairs) > limit:
        head += ' 等 {} 种'.format(len(pairs))
    return head


def _slot_count(entry):
    """兼容新旧 NBT 的 count / Count 字段; 非法值统一按 0 处理。"""
    try:
        v = int(entry.get('count', entry.get('Count', 0)) or 0)
        return v if v > 0 else 0
    except (TypeError, ValueError):
        return 0


def detail_of(path, zh=None):
    """把一个 .dat 拆成「散装物品」和「潜影盒」两部分，供播报文案使用。

    zh 只影响显示名; 缓存时固定传 None, 避免语言表变化而 .dat 未变时读旧名字。
    """
    nbt = read_nbt(path)
    inv = nbt.get('Inventory') or []
    loose = {}
    boxes = []
    for slot in inv:
        if not isinstance(slot, dict):
            continue
        n = _slot_count(slot)
        if n <= 0:
            continue
        comps = slot.get('components')
        cont = comps.get('minecraft:container') if isinstance(comps, dict) else None
        if isinstance(cont, list):
            inner = {}
            inner_total = 0
            for e in cont:
                if not isinstance(e, dict):
                    continue
                ic = _slot_count(e.get('item') or {})
                if ic <= 0:
                    continue
                nm = _item_name(e.get('item', {}).get('id'), zh)
                inner[nm] = inner.get(nm, 0) + ic
                inner_total += ic
            boxes.append({'count': n, 'items': inner, 'inner_total': inner_total})
        else:
            nm = _item_name(slot.get('id'), zh)
            loose[nm] = loose.get(nm, 0) + n
    total = sum(loose.values()) + sum(_box_count(b) for b in boxes)
    return {'loose': loose, 'boxes': boxes, 'total': total}


def _box_count(box):
    """潜影盒贡献的件数: 有东西算盒内合计×盒数, 空盒每盒也算 1 件。"""
    n = int(box.get('count') or 0)
    inner = int(box.get('inner_total') or 0)
    return (inner if inner > 0 else 1) * n


def localize(detail, zh):
    """把缓存里的物品 id 换成当前语言表的中文名; 不改 total, 不影响积压判定。"""
    if not zh:
        return detail
    def add(target, key, value):
        name = zh.get(key, key)
        target[name] = target.get(name, 0) + value
    loose = {}
    for k, v in detail['loose'].items():
        add(loose, k, v)
    boxes = []
    for b in detail['boxes']:
        items = {}
        for k, v in b['items'].items():
            add(items, k, v)
        boxes.append({'count': b['count'], 'items': items, 'inner_total': b['inner_total']})
    return {'loose': loose, 'boxes': boxes, 'total': detail['total']}


def describe(bot, detail, zh=None):
    d = localize(detail, zh)
    parts = []
    if d['loose']:
        parts.append(_short_list(list(d['loose'].items())))
    for b in d['boxes']:
        if b['items']:
            parts.append('潜影盒×{}（{}）'.format(b['count'], _short_list(list(b['items'].items()), 3)))
        else:
            parts.append('潜影盒×{}（空）'.format(b['count']))
    return '❗ {} 背包未清空：{}'.format(bot, '；'.join(parts) or '?')


def split_chunks(segments, max_chars):
    """把若干段文字压成若干条消息，超长就编号 1/n、2/n；这些消息算「一组」。"""
    chunks, cur = [], ''
    for s in segments:
        if not cur:
            cur = s
        elif len(cur) + 3 + len(s) <= max_chars:
            cur = cur + ' ｜ ' + s
        else:
            chunks.append(cur)
            cur = s
    if cur:
        chunks.append(cur)
    out = []
    for c in chunks:
        while len(c) > max_chars:
            out.append(c[:max_chars])
            c = c[max_chars:]
        if c:
            out.append(c)
    if len(out) > 1:
        out = ['{} ({}/{})'.format(c, i + 1, len(out)) for i, c in enumerate(out)]
    return out


def load_config(server):
    try:
        cfg = server.load_config_simple(file_name='config.json', default_config=DEFAULT_CONFIG)
    except Exception:
        cfg = None
    if not isinstance(cfg, dict):
        cfg = dict(DEFAULT_CONFIG)
    return cfg


def instance_dir_of(server, cfg):
    """游戏实例目录 = MCDR 的 working_directory 拼上配置里的 instance_dir（默认 ..）。"""
    rel = str(cfg.get('instance_dir') or '..')
    if os.path.isabs(rel):
        return os.path.normpath(rel)
    base = None
    try:
        base = server.get_mcdr_config().get('working_directory')
    except Exception:
        base = None
    base = os.path.abspath(base or os.getcwd())
    cand = os.path.normpath(os.path.join(base, rel))
    for _ in range(3):   # 兜底：MCDR 的 cwd 不是自己目录时，往上找到含 saves 的实例目录
        if os.path.isdir(os.path.join(cand, 'saves')) or os.path.isfile(os.path.join(cand, 'usercache.json')):
            break
        parent = os.path.dirname(cand)
        if parent == cand:
            break
        cand = parent
    return cand


class Watcher(threading.Thread):
    def __init__(self, server, cfg):
        super().__init__(daemon=True, name='bot_item_watch')
        self.server = server
        self.cfg = cfg
        self.prefix = str(cfg.get('bot_prefix') or 'bot_getitem_')
        self.stop_event = threading.Event()
        self.leave_queue = []      # [(入队时刻, 假人名, 上线时件数)]
        self.residual = set()      # 背包里有残留、需要持续提醒的假人
        self.next_report = time.monotonic() + max(5, int(cfg.get('report_interval', 300)))
        self._load_state()

    # ---- 状态持久化：重载插件后不会忘记还没清空的假人 ----
    def _state_path(self):
        try:
            return os.path.join(self.server.get_data_folder(), 'residual.json')
        except Exception:
            return None

    def _load_state(self):
        p = self._state_path()
        if not p or not os.path.isfile(p):
            return
        try:
            with open(p, encoding='utf-8') as f:
                data = json.load(f)
            names = data.get('bots') if isinstance(data, dict) else data
            self.residual = set(n for n in (names or []) if isinstance(n, str))
        except Exception:
            self.residual = set()

    def _save_state(self):
        p = self._state_path()
        if not p:
            return
        with _STATE_LOCK:
            snapshot = sorted(self.residual)
        try:
            with open(p, 'w', encoding='utf-8') as f:
                json.dump({'bots': snapshot}, f, ensure_ascii=False)
        except Exception:
            pass

    def stop(self):
        self.stop_event.set()

    def on_bot_left(self, name, start):
        with _STATE_LOCK:
            self.leave_queue.append((time.monotonic(), name, start))

    def _sleep_seconds(self):
        with _STATE_LOCK:
            pending = bool(self.leave_queue)
        if pending:
            return 1.0
        left = self.next_report - time.monotonic()
        return max(1.0, min(max(5, int(self.cfg.get('report_interval', 300))), left))

    def run(self):
        if self.stop_event.wait(3):
            return
        while not self.stop_event.is_set():
            try:
                self.tick()
            except Exception:
                self.server.logger.error('[bot_item_watch] 检测失败：\n' + traceback.format_exc())
            if self.stop_event.wait(self._sleep_seconds()):
                return

    def _detail_context(self):
        """一轮播报里所有假人共用的目录/世界/假人名/语言表, 只在循环外算一次。"""
        inst = instance_dir_of(self.server, self.cfg)
        world = find_active_world(inst, self.cfg.get('world') or '')
        if not world:
            return None
        try:
            names = load_bot_names(inst, self.prefix)
        except Exception:
            return None
        return (inst, world, names, load_zh(inst))

    def detail_bot(self, name, ctx=None):
        if ctx is None:
            ctx = self._detail_context()
        if ctx is None:
            return None
        inst, world, names, zh = ctx
        uuid = None
        for u, n in names.items():
            if n == name:
                uuid = u
                break
        if uuid is None:
            return None
        for sub in (('players', 'data'), ('playerdata',)):
            path = os.path.join(inst, 'saves', world, *(sub + (uuid + '.dat',)))
            if os.path.isfile(path):
                try:
                    # 缓存里只放与语言表无关的原始结构; 中文名在这里按当前语言表现查。
                    return localize(_cached(path, lambda p: detail_of(p)), zh)
                except Exception:
                    return None
        return None

    def tick(self):
        now = time.monotonic()
        with _STATE_LOCK:
            batch, self.leave_queue = self.leave_queue, []
        remain = []
        for item in batch:
            at, name, start = item
            if now - at < LEAVE_SETTLE:
                remain.append(item)
                continue
            self._evaluate(name, start)
        if remain:
            with _STATE_LOCK:
                self.leave_queue = remain + self.leave_queue
        if now >= self.next_report:
            self.next_report = now + max(5, int(self.cfg.get('report_interval', 300)))
            try:
                self.report()
            except Exception:
                self.server.logger.error('[bot_item_watch] 播报失败：\n' + traceback.format_exc())

    def _evaluate(self, name, start):
        """假人下线：判断这次是不是「玩家手动下线后还有残留」。"""
        with _STATE_LOCK:
            if name in ONLINE_BOTS:      # 又上线了，这波不算
                return
        d = self.detail_bot(name)
        if d is None:
            return
        if start is None:                # 新假人还没生成 .dat，说明上线时是空的
            start = 0
        cnt = d['total']
        with _STATE_LOCK:
            if cnt > start:              # 自动取货交付：0 -> 2000，跳过
                self.residual.discard(name)
            elif cnt <= 0:
                self.residual.discard(name)
            else:
                self.residual.add(name)
        self._save_state()

    def report(self):
        """固定节拍：把当前所有有残留的假人播报一轮（整组 × repeat 遍）。"""
        with _STATE_LOCK:
            names = sorted(self.residual)
            online = set(ONLINE_BOTS)
        ctx = self._detail_context()   # 目录扫描只做一次, 不再对每只假人重复
        segments = []
        dropped = False
        for name in names:
            if name in online:           # 正在被召唤取货，先不催
                continue
            d = self.detail_bot(name, ctx)
            if d is None:
                continue
            if d['total'] <= 0:
                with _STATE_LOCK:
                    self.residual.discard(name)
                dropped = True
                continue
            segments.append(describe(name, d))
        if dropped:
            self._save_state()
        if not segments:
            return 0
        chunks = split_chunks(segments, max(40, int(self.cfg.get('max_chars', 180))))
        rounds = max(1, int(self.cfg.get('repeat', 3)))
        gap = max(0.2, float(self.cfg.get('repeat_interval', 1.0)))
        for r in range(rounds):
            for c in chunks:
                self._tell(c)
            if r < rounds - 1:
                time.sleep(gap)
        self.server.logger.warning('[bot_item_watch] 播报一轮：{} 只假人有残留，{} 条消息 × {} 遍'.format(
            len(segments), len(chunks), rounds))
        return len(chunks)

    def _tell(self, text):
        comp = {'text': text, 'color': 'red', 'bold': True}
        try:
            self.server.execute('tellraw @a ' + json.dumps(comp, ensure_ascii=False))
        except Exception as e:
            self.server.logger.warning('[bot_item_watch] 发送提醒失败：{}'.format(e))

    def rows(self):
        """!!biw 用：列出当前有残留的假人。"""
        with _STATE_LOCK:
            names = sorted(self.residual)
        ctx = self._detail_context()
        out = []
        for name in names:
            d = self.detail_bot(name, ctx)
            if d and d['total'] > 0:
                out.append((name, d))
        return out


# ---------------- 在线状态 / 下线检测 ----------------

ONLINE_BOTS = set()      # 当前在线的假人名
SESSION_START = {}       # 假人名 -> 刚上线时 .dat 里的件数（判断是不是自动取货交付）
WATCHER = None

_JOIN_RE = re.compile(r'([A-Za-z0-9_]{1,16})(?:加入了游戏| joined the game| joined the singleplayer world)')
_LEFT_RE = re.compile(r'([A-Za-z0-9_]{1,16})(?:退出了游戏| left the game)')


def _handle_join(server, name):
    w = WATCHER
    if w is None or not name.startswith(w.prefix):
        return
    with _STATE_LOCK:
        ONLINE_BOTS.add(name)
    d = w.detail_bot(name)
    cnt = None if d is None else d['total']
    with _STATE_LOCK:
        if len(SESSION_START) > 512:
            SESSION_START.clear()
        SESSION_START[name] = cnt
    server.logger.info('[bot_item_watch] 检测到 {} 上线（上线时 {} 件），在线期间不提醒'.format(
        name, '未知' if cnt is None else cnt))


def _handle_leave(server, name):
    w = WATCHER
    if w is None or not name.startswith(w.prefix):
        return
    with _STATE_LOCK:
        ONLINE_BOTS.discard(name)
        start = SESSION_START.pop(name, None)
    server.logger.info('[bot_item_watch] 检测到 {} 下线（上线时 {} 件）'.format(
        name, '未知' if start is None else start))
    w.on_bot_left(name, start)


def on_info(server, info):
    try:
        if not info.is_from_server:
            return
        text = info.content
    except Exception:
        return
    m = _LEFT_RE.search(text)
    if m is not None:
        _handle_leave(server, m.group(1))
        return
    m = _JOIN_RE.search(text)
    if m is not None:
        _handle_join(server, m.group(1))


# ---------------- MCDR 事件 ----------------

def on_load(server, prev_module):
    global WATCHER
    cfg = load_config(server)
    with _STATE_LOCK:
        ONLINE_BOTS.clear()
        SESSION_START.clear()
    if WATCHER is not None:
        WATCHER.stop()
        WATCHER = None
    WATCHER = Watcher(server, cfg)
    WATCHER.start()
    try:
        server.logger.info('[bot_item_watch] 已加载：前缀={} 每 {} 秒播报一轮，单条最多 {} 字符，整组重复 {} 遍'.format(
            cfg.get('bot_prefix'), cfg.get('report_interval'), cfg.get('max_chars'), cfg.get('repeat')))
        rows = WATCHER.rows()
        server.logger.info('[bot_item_watch] 当前有残留的假人 {} 只'.format(len(rows)))
    except Exception:
        server.logger.error('[bot_item_watch] 初始化自检失败：\n' + traceback.format_exc())

    def show_status(src):
        try:
            rows = WATCHER.rows() if WATCHER else []
            if not rows:
                src.reply('§a[假人物品] 目前没有假人背包残留。')
                return
            src.reply('§e[假人物品] 有 §c{}§e 只假人背包没清空：'.format(len(rows)))
            for name, d in rows[:10]:
                src.reply('§c' + describe(name, d))
        except Exception as e:
            src.reply('§c[假人物品] 查询失败：{}'.format(e))

    def demo(src):
        try:
            n = WATCHER.report() if WATCHER else 0
            src.reply('§a[假人物品] 已立即播报一轮（{} 条消息/遍）'.format(n))
        except Exception as e:
            src.reply('§c[假人物品] 演示失败：{}'.format(e))

    try:
        server.register_command(Literal('!!biw').runs(show_status).then(Literal('test').runs(demo)))
        server.register_help_message('!!biw', '查看哪些假人背包里还有东西')
    except Exception:
        pass


def on_unload(server):
    global WATCHER
    if WATCHER is not None:
        WATCHER.stop()
        WATCHER = None
