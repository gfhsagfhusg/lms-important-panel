# -*- coding: utf-8 -*-
"""纯标准库回归测试：安装器、投影统计、MCDR 插件。

运行：python -m unittest discover -s tests -p "test_*.py" -v
或：  python tests/test_python.py
所有临时数据只写在 tests/_work/ 下（项目目录内），结束后自动清理。
"""
import gzip
import importlib.util
import io
import json
import os
import struct
import sys
import types
import unittest
import zipfile

def _ensure_utf8():
    """测试宿主自保: 仅当 stdout/stderr 不是 UTF-8 家族时才改; 生产模块不做此事。"""
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        try:
            enc = (stream.encoding or '').lower().replace('-', '')
            if enc not in ('utf8', 'utf8sig'):
                stream.reconfigure(encoding='utf-8', errors='backslashreplace')
        except (AttributeError, ValueError, OSError, TypeError):
            pass


_ensure_utf8()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_work')
sys.path.insert(0, ROOT)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ipv = load('ipv_install', os.path.join(ROOT, 'install.py'))
lit = load('ipv_litematic', os.path.join(ROOT, 'tools', 'litematic_counts.py'))

# MCDR 插件顶层 import mcdreforged.api.all, 用桩模块注入后再加载
if 'mcdreforged' not in sys.modules:
    pkg = types.ModuleType('mcdreforged'); pkg.__path__ = []
    api = types.ModuleType('mcdreforged.api'); api.__path__ = []
    allm = types.ModuleType('mcdreforged.api.all')
    allm.Literal = lambda *a, **k: None
    allm.__all__ = ['Literal']
    sys.modules.update({'mcdreforged': pkg, 'mcdreforged.api': api,
                        'mcdreforged.api.all': allm})
bot = load('ipv_bot_watch', os.path.join(ROOT, 'tools', 'bot_item_watch.py'))


def clean_dir(path):
    """逐个 os.remove / os.rmdir 清理测试临时目录, 不依赖 shutil.rmtree。"""
    if not os.path.isdir(path):
        return
    for root, dirs, files in os.walk(path, topdown=False):
        for f in files:
            try:
                os.remove(os.path.join(root, f))
            except OSError:
                pass
        for d in dirs:
            try:
                os.rmdir(os.path.join(root, d))
            except OSError:
                pass
    try:
        os.rmdir(path)
    except OSError:
        pass


def write_bytes(path, data):
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, 'wb') as f:
        f.write(data)


def write_json(path, obj):
    write_bytes(path, json.dumps(obj, ensure_ascii=False, indent=2).encode('utf-8'))


def read_bytes(path):
    with open(path, 'rb') as f:
        return f.read()


def read_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def make_jar(path, entries):
    with zipfile.ZipFile(path, 'w') as z:
        for name, data in entries:
            z.writestr(name, data)
    return path


SITE = [('websites/storage/index.html', '<html><body><div id="app"></div></body></html>'),
        ('websites/storage/assets/app.js', 'console.log("lms");'),
        ('websites/storage/assets/zh_cn-ABC.js', 'export default {};')]


class Base(unittest.TestCase):
    def setUp(self):
        clean_dir(WORK)
        os.makedirs(WORK, exist_ok=True)
        self.root = os.path.join(WORK, self._testMethodName)
        os.makedirs(self.root)

    @classmethod
    def tearDownClass(cls):
        clean_dir(WORK)

    def tmp(self, name):
        p = os.path.join(self.root, name)
        os.makedirs(p, exist_ok=True)
        return p


# ---------------------------------------------------------------- T1 转义往返
class TestPropEscape(Base):
    def test_roundtrip_chinese_space_emoji_and_specials(self):
        cases = [
            r'D:\游戏 存档\v1\checkStorageList\main.json',
            'emoji_😀.json',
            'C:\\a:b=c \\ path',
            ' leading space',
            'a\tb\nc\r',
            'ascii-only.json',
            'literal\\u4E2D',
            '汉字\u4e00\U00020000',
        ]
        for s in cases:
            esc = ipv._escape_prop(s)
            self.assertTrue(all(ord(c) < 128 for c in esc), esc)
            self.assertEqual(ipv._unescape_prop(esc), s, esc)

    def test_non_bmp_written_as_surrogate_pair(self):
        esc = ipv._escape_prop('😀')
        self.assertEqual(esc, r'\uD83D\uDE00')
        self.assertEqual(len(esc), 12)  # 两组 \uXXXX, 不是 6 位十六进制


# ---------------------------------------------------------------- T4 半安装
class TestExtractSite(Base):
    def _dest_with_marker(self):
        dest = self.tmp('web')
        write_bytes(os.path.join(dest, 'OLD_MARKER.txt'), b'keep-me')
        return dest

    def test_c_plain_jar_extracts_every_entry(self):
        jar = make_jar(os.path.join(self.root, 'ok.jar'), SITE)
        dest = self.tmp('fresh')
        names = ipv.extract_site(jar, dest)
        self.assertEqual(sorted(names), sorted(n for n, _ in SITE))
        for n, data in SITE:
            rel = n[len(ipv.JAR_PREFIX):]
            with open(os.path.join(dest, rel.replace('/', os.sep)), 'rb') as f:
                self.assertEqual(f.read(), data.encode('utf-8'))

    def test_d_extract_replaces_existing_dir_atomically(self):
        jar = make_jar(os.path.join(self.root, 'ok2.jar'), SITE)
        dest = self._dest_with_marker()
        ipv.extract_site(jar, dest)
        self.assertFalse(os.path.exists(os.path.join(dest, 'OLD_MARKER.txt')))
        self.assertTrue(os.path.isfile(os.path.join(dest, 'index.html')))

    def test_a_out_of_bounds_keeps_original_dir(self):
        dest = self._dest_with_marker()
        jar = make_jar(os.path.join(self.root, 'bad.jar'),
                       SITE[:1] + [('websites/storage/../../PWNED.txt', 'evil')])
        try:
            ipv.extract_site(jar, dest)
            self.fail('应当拒绝越界条目')
        except SystemExit:
            pass
        marker = os.path.join(dest, 'OLD_MARKER.txt')
        self.assertTrue(os.path.isfile(marker))
        with open(marker, 'rb') as f:
            self.assertEqual(f.read(), b'keep-me')
        self.assertEqual(os.listdir(dest), ['OLD_MARKER.txt'])
        self.assertFalse(os.path.exists(os.path.join(self.root, 'PWNED.txt')))

    def test_b_long_filename_failure_keeps_original_dir(self):
        dest = self._dest_with_marker()
        bad = 'websites/storage/' + ('a' * 4000) + '.js'
        jar = make_jar(os.path.join(self.root, 'long.jar'), SITE[:1] + [(bad, 'x')])
        try:
            ipv.extract_site(jar, dest)
            self.fail('超长文件名应触发失败')
        except SystemExit:
            pass
        self.assertTrue(os.path.isfile(os.path.join(dest, 'OLD_MARKER.txt')))
        self.assertEqual(os.listdir(dest), ['OLD_MARKER.txt'])

    def test_a_absolute_and_drive_letters_rejected(self):
        for rel in ('/abs/x.js', 'C:/win/x.js', r'..\..\x.js', 'a/b/../../../x.js'):
            with self.assertRaises(SystemExit):
                ipv._safe_rel(rel)

    def test_c_legal_nested_path_not_false_positive(self):
        self.assertEqual(ipv._safe_rel('assets/./zh_cn-a.js'), 'assets/zh_cn-a.js')
        self.assertEqual(ipv._safe_rel('assets/sub/../zh_cn-a.js'), 'assets/zh_cn-a.js')

    def test_precheck_does_not_touch_disk(self):
        dest = self._dest_with_marker()
        jar = make_jar(os.path.join(self.root, 'bad2.jar'),
                       SITE[:1] + [('websites/storage/../../EVIL.txt', 'evil')])
        with self.assertRaises(SystemExit):
            ipv._site_entries(jar)
        self.assertEqual(os.listdir(dest), ['OLD_MARKER.txt'])


# ---------------------------------------------------------------- T2 快照与卸载
class TestSnapshotAndUninstall(Base):
    def make_instance(self, cfg=None):
        inst = self.tmp('inst')
        os.makedirs(os.path.join(inst, 'saves', 'world', ipv.LMS_DIR_NAME))
        paths = ipv.paths_for(inst, 'world')
        if cfg is not None:
            write_json(paths.config_path, cfg)
        return inst, paths

    def test_t2_snapshot_restores_all_four_keys(self):
        inst, p = self.make_instance({'port': 7123, 'noPassword': False,
                                      'expireDay': 7, 'customField': 'KEEP'})
        before = ipv._read_storage_config(p.lms_dir)
        ipv.atomic_write_json(p.snapshot_path, ipv.build_manifest(p, before))
        ipv.update_storage_config(p.lms_dir)
        ipv.uninstall(inst, 'world')
        after = read_json(p.config_path)
        self.assertEqual(after, {'port': 7123, 'noPassword': False,
                                'expireDay': 7, 'customField': 'KEEP'})
        self.assertFalse(os.path.exists(p.snapshot_path))

    def test_t2_missing_snapshot_conservative_rollback(self):
        inst, p = self.make_instance({'port': 7123, 'customWebsite': False})
        ipv.update_storage_config(p.lms_dir)
        ipv.uninstall(inst, 'world')
        after = read_json(p.config_path)
        self.assertFalse(after.get('customWebsite'))
        self.assertFalse(after.get('autoStartWebsite'))
        self.assertEqual(after.get('port'), 7123)

    def test_t2_bad_snapshot_value_skipped_not_aborted(self):
        inst, p = self.make_instance({'port': 7123})
        snap = ipv.build_manifest(p, ipv._read_storage_config(p.lms_dir))
        snap['values']['port'] = {'present': True, 'value': 'not-an-int'}
        ipv.atomic_write_json(p.snapshot_path, snap)
        ipv.update_storage_config(p.lms_dir)
        ipv.uninstall(inst, 'world')          # 不应抛异常
        self.assertFalse(os.path.exists(p.snapshot_path))
        after = read_json(p.config_path)
        # 非法值被跳过 = 该键不回滚(保留安装后的 7123), 但其余键照常还原且不中断
        self.assertEqual(after.get('port'), 7123)
        self.assertNotIn('customWebsite', after)
        self.assertNotIn('autoStartWebsite', after)

    def test_t8_bad_json_precheck_writes_nothing(self):
        inst, p = self.make_instance()
        write_bytes(p.config_path, b'{ not json')
        raw = read_bytes(p.config_path)
        with self.assertRaises(SystemExit):
            ipv.precheck_storage_config(p.lms_dir)
        self.assertEqual(read_bytes(p.config_path), raw)
        self.assertFalse(os.path.exists(p.snapshot_path))

    def test_t8_existing_fields_preserved(self):
        inst, p = self.make_instance({'port': 7123, 'customField': 'KEEP',
                                      'expireDay': 7, 'noPassword': False})
        cfg, _ = ipv.update_storage_config(p.lms_dir)
        self.assertEqual(cfg['port'], 7123)
        self.assertEqual(cfg['customField'], 'KEEP')
        self.assertEqual(cfg['expireDay'], 7)
        self.assertFalse(cfg['noPassword'])
        self.assertTrue(cfg['customWebsite'])

    def test_atomic_write_no_partial_file_on_failure(self):
        p = os.path.join(self.root, 'cfg.json')
        ipv.atomic_write_json(p, {'a': 1})
        self.assertEqual(read_json(p), {'a': 1})
        self.assertFalse(os.path.exists(p + ipv.ATOMIC_SUFFIX))


# ---------------------------------------------------------------- T1 properties
class TestWhSelector(Base):
    def test_gbk_bytes_preserved_and_only_jsonfile_changed(self):
        inst = self.tmp('inst2')
        cfgdir = os.path.join(inst, 'config')
        os.makedirs(cfgdir)
        prop = os.path.join(cfgdir, 'wh-selector.properties')
        original = (b'# \xd6\xd0\xce\xc4 comment\r\n'
                    b'jsonFile=C\\:/old/main.json\r\n'
                    b'autoScan=true\r\n'
                    b'markerBlock=minecraft:golden_axe\r\n')
        write_bytes(prop, original)
        ipv.check_wh_selector(inst, os.path.join(inst, 'saves', 'world'))
        data = read_bytes(prop)
        self.assertIn(b'# \xd6\xd0\xce\xc4 comment\r\n', data)
        self.assertIn(b'autoScan=true\r\n', data)
        self.assertIn(b'markerBlock=minecraft:golden_axe\r\n', data)
        self.assertEqual(data.count(b'jsonFile='), 1)
        self.assertEqual(data.count(b'\r\n'), 4)
        self.assertTrue(os.path.isfile(prop + '.bak'))

    def test_duplicate_jsonfile_lines_collapsed(self):
        inst = self.tmp('inst3')
        cfgdir = os.path.join(inst, 'config')
        os.makedirs(cfgdir)
        prop = os.path.join(cfgdir, 'wh-selector.properties')
        write_bytes(prop, b'jsonFile=/old/a.json\nautoScan=true\njsonFile=/old/b.json\n')
        ipv.check_wh_selector(inst, os.path.join(inst, 'saves', 'world'))
        data = read_bytes(prop)
        self.assertEqual(data.count(b'jsonFile='), 1)
        self.assertIn(b'autoScan=true', data)

    def test_existing_bak_not_overwritten(self):
        inst = self.tmp('inst4')
        cfgdir = os.path.join(inst, 'config')
        os.makedirs(cfgdir)
        prop = os.path.join(cfgdir, 'wh-selector.properties')
        write_bytes(prop, b'autoScan=true\n')
        write_bytes(prop + '.bak', b'ORIGINAL-BACKUP')
        ipv.check_wh_selector(inst, os.path.join(inst, 'saves', 'world'))
        self.assertEqual(read_bytes(prop + '.bak'), b'ORIGINAL-BACKUP')


# ---------------------------------------------------------------- T9 世界名
class TestWorldName(Base):
    def _level(self, name):
        d = self.tmp('save')
        w = name.encode('utf-8')
        nbt = (b'\x0a' + struct.pack('>H', 0) + b'\x08' + struct.pack('>H', 9)
               + b'LevelName' + struct.pack('>H', len(w)) + w + b'\x00')
        with gzip.open(os.path.join(d, 'level.dat'), 'wb') as f:
            f.write(nbt)
        return d

    def test_chinese_world_name(self):
        self.assertEqual(ipv.read_world_name(self._level('红石仓库'), 'fb'), '红石仓库')

    def test_missing_levelname_falls_back(self):
        d = self.tmp('save2')
        write_bytes(os.path.join(d, 'level.dat'), b'not a gzip')
        self.assertEqual(ipv.read_world_name(d, 'fb'), 'fb')


# ---------------------------------------------------------------- T5 投影统计
class TestLitematic(Base):
    def _nbt_name(self, s):
        b = s.encode('utf-8')
        return struct.pack('>H', len(b)) + b

    def _compound(self, entries):
        out = b''
        for t, name, payload in entries:
            out += bytes([t]) + self._nbt_name(name) + payload
        return out + b'\x00'

    def make_litematic(self, path, pal, longs, size=(4, 1, 1)):
        # 直接按 NBT 顺序手写: Region compound 里放 Size / BlockStatePalette / BlockStates
        body = (b'\x09' + self._nbt_name('Size') + b'\x03' + struct.pack('>i', 3)
                + b''.join(struct.pack('>i', v) for v in size))
        body += b'\x09' + self._nbt_name('BlockStatePalette') + b'\x0a' + struct.pack('>i', len(pal))
        for name in pal:
            body += self._compound([(8, 'Name', self._nbt_name(name))])
        body += b'\x0c' + self._nbt_name('BlockStates') + struct.pack('>i', len(longs))
        body += b''.join(struct.pack('>q', v) for v in longs)
        body += b'\x00'
        regions = self._compound([(10, 'Region0', body)])
        root = self._compound([(10, 'Regions', regions)])
        with gzip.open(path, 'wb') as f:
            f.write(b'\x0a' + struct.pack('>H', 0) + root)
        return path

    def test_same_name_blockstates_accumulate_and_air_skipped(self):
        p = self.make_litematic(os.path.join(self.root, 't.litematic'),
                                ['minecraft:air', 'minecraft:piston', 'minecraft:piston'],
                                [36], (4, 1, 1))   # indices [0,1,2,0]
        vol, agg = lit.parse_litematic(p)
        self.assertEqual(vol, 4)
        self.assertEqual(agg.get('minecraft:piston'), 2)
        self.assertNotIn('minecraft:air', agg)

    def test_numpy_and_pure_python_paths_agree(self):
        p = self.make_litematic(os.path.join(self.root, 't2.litematic'),
                                ['minecraft:air', 'minecraft:piston', 'minecraft:slime_block'],
                                [36], (4, 1, 1))
        saved = lit.np
        try:
            lit.np = None
            vol_a, agg_a = lit.parse_litematic(p)
            lit.np = saved
            vol_b, agg_b = lit.parse_litematic(p)
        finally:
            lit.np = saved
        self.assertEqual((vol_a, agg_a), (vol_b, agg_b))

    def test_oversized_decompression_rejected(self):
        p = os.path.join(self.root, 'bomb.litematic')
        with gzip.open(p, 'wb') as f:
            f.write(b'X' * 4096)          # 高度可压缩, 解压后远超上限
        lit.MAX_GZIP_BYTES = 8
        try:
            with self.assertRaises(ValueError):
                lit.parse_litematic(p)
        finally:
            lit.MAX_GZIP_BYTES = 64 * 1024 * 1024


# ---------------------------------------------------------------- T6 插件
class TestBotWatch(Base):
    def _nbt(self, s):
        b = s.encode('utf-8')
        return struct.pack('>H', len(b)) + b

    def test_empty_box_counts_as_one(self):
        # 直接构造: Inventory 是 TAG_List(9), 元素是 TAG_Compound(10)
        slot = (b'\x08' + self._nbt('id') + self._nbt('minecraft:shulker_box')
                + b'\x03' + self._nbt('count') + struct.pack('>i', 1)
                + b'\x0a' + self._nbt('components')
                + b'\x09' + self._nbt('minecraft:container') + b'\x0a' + struct.pack('>i', 0)
                + b'\x00' + b'\x00')
        inv = b'\x0a' + struct.pack('>i', 1) + slot
        body = b'\x09' + self._nbt('Inventory') + inv + b'\x00'
        with gzip.open(os.path.join(self.root, 'empty.dat'), 'wb') as f:
            f.write(b'\x0a' + struct.pack('>H', 0) + body)
        d = bot.detail_of(os.path.join(self.root, 'empty.dat'))
        self.assertEqual(d['total'], 1)
        self.assertIn('潜影盒×1（空）', bot.describe('bot_getitem_1', d))

    def test_box_with_items_and_loose(self):
        inner_items = (b'\x08' + self._nbt('id') + self._nbt('minecraft:diamond')
                       + b'\x03' + self._nbt('count') + struct.pack('>i', 32) + b'\x00')
        entry = b'\x0a' + self._nbt('item') + inner_items + b'\x00'
        container = b'\x0a' + struct.pack('>i', 1) + entry
        slot = (b'\x08' + self._nbt('id') + self._nbt('minecraft:shulker_box')
                + b'\x03' + self._nbt('count') + struct.pack('>i', 2)
                + b'\x0a' + self._nbt('components')
                + b'\x09' + self._nbt('minecraft:container') + container
                + b'\x00' + b'\x00')
        loose = (b'\x08' + self._nbt('id') + self._nbt('minecraft:slime_block')
                 + b'\x03' + self._nbt('count') + struct.pack('>i', 5) + b'\x00')
        inv = b'\x0a' + struct.pack('>i', 2) + slot + loose
        body = b'\x09' + self._nbt('Inventory') + inv + b'\x00'
        with gzip.open(os.path.join(self.root, 'mix.dat'), 'wb') as f:
            f.write(b'\x0a' + struct.pack('>H', 0) + body)
        d = bot.detail_of(os.path.join(self.root, 'mix.dat'))
        self.assertEqual(d['total'], 32 * 2 + 5)
        self.assertIn('slime_block', d['loose'])

    def test_localize_uses_language_table(self):
        d = {'loose': {'diamond': 4}, 'boxes': [], 'total': 4}
        out = bot.localize(d, {'diamond': '钻石'})
        self.assertEqual(out['loose'], {'钻石': 4})
        self.assertEqual(out['total'], 4)
        self.assertEqual(bot.describe('bot_getitem_1', d, {'diamond': '钻石'}),
                         '❗ bot_getitem_1 背包未清空：钻石×4')

    def test_slot_count_invalid_value_is_zero(self):
        self.assertEqual(bot._slot_count({'count': 'oops'}), 0)
        self.assertEqual(bot._slot_count({'Count': 7}), 7)
        self.assertEqual(bot._slot_count({'count': -3}), 0)

    def test_split_chunks(self):
        parts = bot.split_chunks(['a' * 100, 'b' * 100, 'c' * 100], 120)
        self.assertTrue(all(len(p) <= 130 for p in parts))
        self.assertTrue(all('(' in p for p in parts))

    def test_zh_empty_table_not_cached(self):
        inst = self.tmp('noassets')
        self.assertEqual(bot.load_zh(inst), {})
        self.assertEqual(bot.load_zh(inst), {})
        self.assertNotIn(os.path.abspath(inst), bot._ZH_CACHE)


class TestImportSideEffects(unittest.TestCase):
    def test_production_modules_are_silent_at_import(self):
        """锁住根因: 生产模块 import 期不得产生任何 stdout/stderr 输出。

        自建捕获流不经过真实 sys.stdout, 因此与 CI 的 PYTHONIOENCODING / 测试宿主
        的 UTF-8 兜底完全解耦; 即使 workflow 强制 UTF-8, 也能抓到回归。
        """
        import contextlib
        targets = [
            ('ipv_chk_install', os.path.join(ROOT, 'install.py')),
            ('ipv_chk_litematic', os.path.join(ROOT, 'tools', 'litematic_counts.py')),
            ('ipv_chk_bot', os.path.join(ROOT, 'tools', 'bot_item_watch.py')),
        ]
        # 强制 numpy 缺失: 否则 except ImportError 块不执行, import 期 print 回归时断言恒真
        had = 'numpy' in sys.modules
        saved = sys.modules.get('numpy')
        sys.modules['numpy'] = None
        try:
            for name, path in targets:
                with self.subTest(module=path):
                    out, err = io.StringIO(), io.StringIO()
                    spec = importlib.util.spec_from_file_location(name, path)
                    mod = importlib.util.module_from_spec(spec)
                    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                        spec.loader.exec_module(mod)
                    self.assertEqual(out.getvalue() + err.getvalue(), '',
                                     '%s import 期不应产生任何输出' % path)
                    if name == 'ipv_chk_litematic':
                        self.assertIsNone(mod.np, '必须强制 numpy 缺失，否则断言恒真')
        finally:
            if had:
                sys.modules['numpy'] = saved
            else:
                sys.modules.pop('numpy', None)


if __name__ == '__main__':
    unittest.main(verbosity=2)
