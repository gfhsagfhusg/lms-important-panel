#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重要物品专栏 (Important Items Panel) 一键安装器。

作用:
  1. 从你已安装的 Carpet-LMS-Addition mod jar 里提取原版仓储网站文件,
     复制到指定存档的 carpetlmsaddition/customStorageWebsite/ 目录;
  2. 注入「重要物品专栏」面板脚本 (panel/important_panel.js);
  3. 打开 checkStorageConfig.json 的 customWebsite 开关;
  4. 从存档 level.dat 读取世界名写入 config.json (面板顶部显示用)。

用法:
  python install.py                        # 交互式: 列出所有存档让你选
  python install.py 存档名                 # 直接安装到 saves/存档名
  python install.py --instance "D:\\xxx" 存档名
  python install.py --uninstall 存档名     # 按安装前快照还原配置并移除面板注入
                                          # (无快照时仅关闭 customWebsite / autoStartWebsite)

依赖: 仅 Python 3.6+ 标准库, 无需联网。
适配: Carpet-LMS-Addition v1.15.0 (MC 26.1.2)。

设计约定（改动前请先读）:
  * 安装分「预检 / 执行」两段: 预检只读、全部通过后才产生任何写操作。
  * 网站目录用「暂存目录 + 原子替换」生成, 中途失败会保留安装前的完整目录。
  * 所有配置写入都走原子替换, 不会留下截断的 JSON / properties。
  * 安装前一次性写快照 + manifest, 卸载时按它逆序回滚并清理临时文件。
"""
import argparse
import base64
import gzip
import json
import os
import re
import shutil
import struct
import sys
import zipfile
from collections import namedtuple

# ---------------------------------------------------------------- 常量 / 路径
PANEL_NAME = 'important_panel.js'
SNAPSHOT_NAME = '.ipv_install_snapshot.json'  # 安装前配置快照 + 改动清单, 卸载时按它还原
WEB_DIR_NAME = 'customStorageWebsite'
LMS_DIR_NAME = 'carpetlmsaddition'
JAR_PREFIX = 'websites/storage/'
STORAGE_CONFIG = 'checkStorageConfig.json'
DEMO_STORAGE_FILES = {'example.json'}
LOCALE_RE = re.compile(r'^assets/zh_cn-[A-Za-z0-9._-]+\.js$')
INJECT_TAG = '<script src="/%s" defer></script>' % PANEL_NAME
SNAPSHOT_KEYS = ('customWebsite', 'autoStartWebsite', 'port', 'storageList')
MAX_GZIP_BYTES = 64 * 1024 * 1024  # 单个 gzip/NBT 文件解压上限, 防压缩炸弹
STAGING_SUFFIX = '.ipv-staging'
BACKUP_SUFFIX = '.ipv-backup'
ATOMIC_SUFFIX = '.ipvtmp'

HERE = os.path.dirname(os.path.abspath(__file__))
PANEL_SRC = os.path.join(HERE, 'panel', PANEL_NAME)
WATCH_SRC = os.path.join(HERE, 'tools', 'bot_item_watch.py')
WATCH_DEST_NAME = 'bot_item_watch.py'

# 一次派生出全部路径, 避免安装/卸载各写一份
Paths = namedtuple('Paths', 'instance save_dir lms_dir web_dir config_path snapshot_path '
                            'wh_prop wh_prop_bak plugin_path')


def paths_for(instance, save_name):
    save_dir = os.path.join(instance, 'saves', save_name)
    lms_dir = os.path.join(save_dir, LMS_DIR_NAME)
    wh_prop = os.path.join(instance, 'config', 'wh-selector.properties')
    return Paths(
        instance=instance,
        save_dir=save_dir,
        lms_dir=lms_dir,
        web_dir=os.path.join(lms_dir, WEB_DIR_NAME),
        config_path=os.path.join(lms_dir, STORAGE_CONFIG),
        snapshot_path=os.path.join(lms_dir, SNAPSHOT_NAME),
        wh_prop=wh_prop,
        wh_prop_bak=wh_prop + '.bak',
        plugin_path=os.path.join(instance, 'mcdr-singleplayer', 'plugins', WATCH_DEST_NAME),
    )


# ---------------------------------------------------------------- 通用工具
def fail(msg):
    print('[错误] %s' % msg)
    sys.exit(1)


def ok(msg):
    print('[完成] %s' % msg)


def atomic_write_bytes(path, data):
    """同目录临时文件 + os.replace 原子替换; 中途失败不会留下半截文件。"""
    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    tmp = path + ATOMIC_SUFFIX
    try:
        with open(tmp, 'wb') as f:
            f.write(data)
        os.replace(tmp, path)
    except OSError:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


def atomic_write_text(path, text, encoding='utf-8', errors='strict'):
    atomic_write_bytes(path, text.encode(encoding, errors))


def atomic_write_json(path, obj):
    atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + '\n')


def b64(data):
    return base64.b64encode(data).decode('ascii') if data is not None else None


def unb64(s):
    return base64.b64decode(s.encode('ascii')) if s is not None else None


def read_bytes(path):
    with open(path, 'rb') as f:
        return f.read()


# ---------------------------------------------------------------- 实例发现
def is_instance(p):
    return os.path.isdir(os.path.join(p, 'mods')) and os.path.isdir(os.path.join(p, 'saves'))


def child_instances(p):
    """PCL/HMCL 的版本隔离: 实例根目录下的 versions/<版本>/ 本身也可能是一个实例。"""
    out = []
    vdir = os.path.join(p, 'versions')
    if not os.path.isdir(vdir):
        return out
    try:
        names = sorted(os.listdir(vdir))
    except OSError:
        return out
    for name in names:
        c = os.path.join(vdir, name)
        if is_instance(c):
            out.append(c)
    return out


def auto_candidates():
    """按常见位置自动找游戏实例, 找到几个就返回几个。"""
    cands = []
    for base in (os.getcwd(), HERE):
        p = base
        for _ in range(4):  # 解压在实例内部或旁边时, 附近几层都能找到
            if p:
                for c in (p, os.path.join(p, '.minecraft')):
                    if c not in cands:
                        cands.append(c)
            p = os.path.dirname(p)
    home = os.path.expanduser('~')
    for env in (os.environ.get('APPDATA'), os.environ.get('USERPROFILE'), home):
        if env:
            for c in (os.path.join(env, '.minecraft'), env):
                if c not in cands:
                    cands.append(c)
    found = []
    for c in cands:
        if is_instance(c) and c not in found:
            found.append(c)
    return found


def instance_has_lms(p):
    """粗略判断这个实例装没装 Carpet-LMS-Addition(看 mods 里有没有名字带 lms 的 jar)。"""
    mods = os.path.join(p, 'mods')
    try:
        for f in os.listdir(mods):
            if f.lower().endswith('.jar') and 'lms' in f.lower():
                return True
    except OSError:
        pass
    return False


def ask_instance():
    print('未找到游戏实例目录（实例目录里应同时有 mods 和 saves 两个文件夹）。')
    print('常见位置：')
    print('  · 官方启动器：%appdata%\\.minecraft  （资源管理器地址栏粘贴 %appdata%\\.minecraft 回车打开）')
    print('  · PCL / HMCL：你分配给这个版本的 .minecraft 或 版本文件夹')
    print('  · 不确定的话，直接把游戏文件夹拖进这个窗口再回车')
    print('  · 电脑上装了多个启动器时，请选【装了 Carpet-LMS-Addition 的那个】')
    for _ in range(3):
        try:
            inp = input('请输入路径（直接回车退出）: ').strip().strip('"').strip("'").rstrip('\\/')
        except EOFError:
            inp = ''
        if not inp:
            break
        hit = None
        if is_instance(inp):
            hit = os.path.abspath(inp)
        else:
            subs = child_instances(inp) or child_instances(os.path.join(inp, '.minecraft'))
            if len(subs) == 1:
                print('在这个目录的 versions 下找到实例: %s' % subs[0])
                hit = os.path.abspath(subs[0])
            elif len(subs) > 1:
                print('这个目录下有多个版本实例：')
                for i, s in enumerate(subs, 1):
                    print('  %d. %s%s' % (i, s, '  [已装 LMS]' if instance_has_lms(s) else ''))
                try:
                    pick = input('输入编号: ').strip()
                except EOFError:
                    pick = ''
                if pick.isdigit() and 1 <= int(pick) <= len(subs):
                    hit = os.path.abspath(subs[int(pick) - 1])
        if hit:
            if instance_has_lms(hit):
                return hit
            print('[注意] 这个目录的 mods 里没看到 Carpet-LMS-Addition，装下去第 1 步会失败。')
            try:
                cont = input('回车仍然使用它，或输入装了 LMS 的那个实例路径: ').strip().strip('"').strip("'").rstrip('\\/')
            except EOFError:
                cont = ''
            if not cont:
                return hit
            subs = child_instances(cont)
            if is_instance(cont):
                return os.path.abspath(cont)
            if len(subs) == 1:
                return os.path.abspath(subs[0])
            print('[没找到] %s' % cont)
            continue
        if os.path.isdir(os.path.join(inp, 'saves')):
            fail('找到 saves 但缺少 mods 文件夹：%s\n请确认这个版本里装了 Fabric 和 Carpet-LMS-Addition。' % inp)
        if os.path.isdir(os.path.join(inp, 'mods')):
            fail('找到 mods 但缺少 saves 文件夹：%s\n请先进游戏创建一个存档再安装。' % inp)
        print('[没找到] 这个目录下既没有 mods 也没有 saves：%s' % inp)
    fail('未指定游戏实例目录。也可以直接指定：python install.py --instance "D:\\你的版本文件夹"')


def resolve_instance(arg):
    if arg:
        if is_instance(arg):
            if not instance_has_lms(arg):
                print('[注意] 这个实例的 mods 里没看到 Carpet-LMS-Addition，第 1 步可能会失败。')
            return os.path.abspath(arg)
        subs = child_instances(arg)
        if len(subs) == 1:
            print('在 versions 下找到实例: %s' % subs[0])
            return os.path.abspath(subs[0])
        fail('不是有效的游戏实例目录(需要同时包含 mods 和 saves 文件夹): %s' % arg)

    found = auto_candidates()
    lms = [c for c in found if instance_has_lms(c)]
    if lms:
        print('检测到装了 Carpet-LMS-Addition 的游戏实例：')
        for i, s in enumerate(lms, 1):
            print('  %d. %s' % (i, s))
        try:
            ans = input('输入编号选择(只有一个时直接回车): ').strip().strip('"').strip("'").rstrip('\\/')
        except EOFError:
            ans = ''
        if not ans:
            if len(lms) == 1:
                return lms[0]
            sys.exit(0)
        if ans.isdigit() and 1 <= int(ans) <= len(lms):
            return lms[int(ans) - 1]
        if is_instance(ans):
            return os.path.abspath(ans)
        subs = child_instances(ans) or child_instances(os.path.join(ans, '.minecraft'))
        if len(subs) == 1:
            return os.path.abspath(subs[0])
        print('[没找到] 这个路径不是游戏实例，改为手动输入。')
    elif found:
        print('找到 %d 个游戏实例，但没有一个装了 Carpet-LMS-Addition：' % len(found))
        for i, s in enumerate(found, 1):
            print('  %d. %s' % (i, s))
        print('如果你的 LMS 装在别的启动器/版本里，请直接输入那个文件夹路径。')
        try:
            pick = input('输入编号使用(回车改为手动输入路径): ').strip().strip('"').strip("'").rstrip('\\/')
        except EOFError:
            pick = ''
        if pick.isdigit() and 1 <= int(pick) <= len(found):
            return found[int(pick) - 1]
    return ask_instance()


# ---------------------------------------------------------------- jar 与网站目录
def lms_jar_has_site(jar_path):
    try:
        with zipfile.ZipFile(jar_path) as z:
            return any(n.startswith(JAR_PREFIX) for n in z.namelist())
    except Exception:
        return False


def find_lms_jar(instance):
    mods_dir = os.path.join(instance, 'mods')
    jars = [os.path.join(mods_dir, f) for f in sorted(os.listdir(mods_dir))
            if f.lower().endswith('.jar') and 'lms' in f.lower()]
    for j in jars:
        if lms_jar_has_site(j):
            return j
    # 兜底: 逐个 jar 检查内部结构(文件名不含 lms 也能找到)
    for f in sorted(os.listdir(mods_dir)):
        if not f.lower().endswith('.jar'):
            continue
        j = os.path.join(mods_dir, f)
        if j in jars:
            continue
        if lms_jar_has_site(j):
            return j
    return None


def _safe_rel(rel):
    """纯字符串规范化 jar 内路径: 拒绝绝对/盘符/UNC/越界/NUL, 返回 dest 内的相对路径。

    只做字符串判断, 不碰文件系统, 因此可以在任何写操作之前对全部条目预检。
    """
    rel = rel.replace('\\', '/')
    if '\x00' in rel:
        fail('jar 内存在含 NUL 的非法路径: %r' % rel)
    if rel.startswith('/') or re.match(r'^[A-Za-z]:', rel):
        fail('jar 内存在非法绝对路径(或盘符/UNC): %s' % rel)
    parts = []
    for seg in rel.split('/'):
        if seg in ('', '.'):
            continue
        if seg == '..':
            if not parts:
                fail('jar 内存在越界路径(会写到网站目录之外): %s' % rel)
            parts.pop()
        else:
            parts.append(seg)
    if not parts:
        fail('jar 内存在空路径条目: %s' % rel)
    return '/'.join(parts)


def _safe_target(dest, rel):
    """把规范化后的相对路径拼到 dest 下, 并二次用 realpath + commonpath 校验。"""
    rel = _safe_rel(rel)
    base = os.path.realpath(dest)
    target = os.path.realpath(os.path.join(base, rel.replace('/', os.sep)))
    try:
        inside = os.path.commonpath([base, target]) == base
    except ValueError:
        inside = False
    if not inside:
        fail('jar 内存在越界路径(会写到网站目录之外): %s' % rel)
    return target


def _site_entries(jar_path):
    """只读预检: 打开 jar, 收集全部网站条目并逐个校验路径。不写任何文件。"""
    with zipfile.ZipFile(jar_path) as z:
        names = [n for n in z.namelist()
                 if n.startswith(JAR_PREFIX) and not n.endswith('/')]
        if not names:
            fail('jar 内没有找到 %s* 网站资源: %s' % (JAR_PREFIX, jar_path))
        plan = []
        for n in names:
            rel = _safe_rel(n[len(JAR_PREFIX):])
            plan.append((n, rel))
        if not any(rel == 'index.html' for _, rel in plan):
            fail('jar 内缺少 websites/storage/index.html, 结构可能已变化: %s' % jar_path)
        return plan


def extract_site(jar_path, dest):
    """从 jar 提取 websites/storage/** 到 dest。

    两阶段提交: 先对全部条目做纯校验(不写盘), 再解压到独立的暂存目录,
    全部成功后才原子替换 dest。任何失败(越界、超长文件名、磁盘满、权限不足、
    jar 损坏)都不会动安装前的网站目录, 也不会留下残缺的半安装目录。
    """
    plan = _site_entries(jar_path)
    staging = dest + STAGING_SUFFIX
    backup = dest + BACKUP_SUFFIX
    for stale in (staging, backup):
        if os.path.isdir(stale):
            shutil.rmtree(stale, ignore_errors=True)
        elif os.path.exists(stale):
            os.remove(stale)
    try:
        os.makedirs(staging)
        with zipfile.ZipFile(jar_path) as z:
            for n, rel in plan:
                target = _safe_target(staging, rel)
                parent = os.path.dirname(target)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                with z.open(n) as src, open(target, 'wb') as out:
                    shutil.copyfileobj(src, out)
    except (OSError, ValueError) as e:
        shutil.rmtree(staging, ignore_errors=True)
        fail('从 jar 提取网站文件失败: %s\n原网站目录未改动, 请检查磁盘空间/权限或 jar 是否完整。' % e)
    except SystemExit:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    had_dest = os.path.exists(dest)
    try:
        if had_dest:
            os.replace(dest, backup)
        os.replace(staging, dest)
    except OSError as e:
        if had_dest and os.path.exists(backup) and not os.path.exists(dest):
            os.replace(backup, dest)
        shutil.rmtree(staging, ignore_errors=True)
        fail('替换网站目录失败: %s\n已回滚到安装前的网站目录。' % e)
    if had_dest:
        shutil.rmtree(backup, ignore_errors=True)
    return [n for n, _ in plan]


def find_locale_chunk(jar_path):
    with zipfile.ZipFile(jar_path) as z:
        for n in z.namelist():
            rel = n[len(JAR_PREFIX):] if n.startswith(JAR_PREFIX) else None
            if rel and LOCALE_RE.match(rel):
                return '/%s' % rel
    return None


def read_world_name(save_dir, fallback):
    p = os.path.join(save_dir, 'level.dat')
    try:
        with gzip.open(p, 'rb') as f:
            raw = f.read(MAX_GZIP_BYTES + 1)
        if len(raw) > MAX_GZIP_BYTES:
            print('      [注意] level.dat 解压后超过 %d MB, 跳过世界名读取。' % (MAX_GZIP_BYTES // 1048576))
            return fallback
        i = raw.find(b'LevelName')
        if i >= 0:
            ln = struct.unpack('>H', raw[i + 9:i + 11])[0]
            if i + 11 + ln <= len(raw):
                name = raw[i + 11:i + 11 + ln].decode('utf-8', 'replace').strip()
                if name:
                    return name
    except Exception:
        pass
    return fallback


# ---------------------------------------------------------------- 配置读写 / 快照
def _read_storage_config(lms_dir):
    """读取 checkStorageConfig.json; 不存在返回 {}。解析失败带阶段信息。"""
    p = os.path.join(lms_dir, STORAGE_CONFIG)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        fail('%s 解析失败(读取阶段): %s\n文件位置: %s' % (STORAGE_CONFIG, e, p))
    if not isinstance(cfg, dict):
        fail('%s 顶层不是对象, 先修好它再安装: %s' % (STORAGE_CONFIG, p))
    return cfg


def _write_storage_config(lms_dir, cfg):
    p = os.path.join(lms_dir, STORAGE_CONFIG)
    try:
        atomic_write_json(p, cfg)
    except OSError as e:
        fail('写入 %s 失败(写回阶段): %s' % (STORAGE_CONFIG, e))


def precheck_storage_config(lms_dir):
    """安装前只读确认配置能解析, 避免改完一半才失败。"""
    _read_storage_config(lms_dir)


def _snapshot_values(cfg):
    values = {}
    for k in SNAPSHOT_KEYS:
        if k in cfg:
            values[k] = {'present': True, 'value': cfg[k]}
        else:
            values[k] = {'present': False}
    return values


def _valid_snapshot_value(k, v):
    if k in ('customWebsite', 'autoStartWebsite'):
        return isinstance(v, bool)
    if k == 'port':
        return isinstance(v, int) and not isinstance(v, bool)
    if k == 'storageList':
        return isinstance(v, list) and all(isinstance(x, str) for x in v)
    return False


def build_manifest(paths, cfg_before):
    """记录安装前每个被改动路径的原值/是否存在, 供 uninstall 逆序回滚。"""
    return {
        'version': 1,
        'values': _snapshot_values(cfg_before),
        'manifest': {
            'config_existed': os.path.isfile(paths.config_path),
            'config_bytes': b64(read_bytes(paths.config_path)) if os.path.isfile(paths.config_path) else None,
            'web_dir_existed': os.path.isdir(paths.web_dir),
            'wh_prop_path': paths.wh_prop,
            'wh_prop_existed': os.path.isfile(paths.wh_prop),
            'wh_prop_bytes': b64(read_bytes(paths.wh_prop)) if os.path.isfile(paths.wh_prop) else None,
            'wh_prop_bak_existed': os.path.isfile(paths.wh_prop_bak),
            'plugin_path': paths.plugin_path,
            'plugin_existed': os.path.isfile(paths.plugin_path),
        },
    }


def write_snapshot(paths, cfg_before):
    """安装前(任何破坏性步骤之前)一次性写快照; 已存在则保留最原始的一份。"""
    if os.path.exists(paths.snapshot_path):
        return
    data = build_manifest(paths, cfg_before)
    try:
        atomic_write_json(paths.snapshot_path, data)
    except OSError as e:
        fail('无法写入安装前快照 %s: %s\n没有快照就无法安全卸载, 安装已取消(未改动任何文件)。' % (paths.snapshot_path, e))


def update_storage_config(lms_dir):
    """打开 customWebsite / autoStartWebsite / port / storageList, 保留其余字段。

    快照由 install() 在任何写操作之前统一写入, 这里不再重复写。
    返回 (cfg, changed)。
    """
    cfg = _read_storage_config(lms_dir)
    changed = []
    if not cfg.get('customWebsite'):
        cfg['customWebsite'] = True
        changed.append('customWebsite=true')
    if not cfg.get('autoStartWebsite'):
        cfg['autoStartWebsite'] = True
        changed.append('autoStartWebsite=true(重启游戏后网站自动启动)')
    if cfg.get('port') is None:
        cfg['port'] = 7000
        changed.append('port=7000')
    if not cfg.get('storageList'):
        cfg['storageList'] = ['main.json']
        changed.append('storageList=["main.json"]')
    elif all(str(x).replace('\\', '/').split('/')[-1].lower() in DEMO_STORAGE_FILES
             for x in cfg['storageList']):
        # 新存档在装本项目之前先开过一次游戏, LMS 会先写一份自带示例清单;
        # 沿用 example.json 的话网站只会扫到那个示例方块, 表现为「框选了也不更新」。
        old = list(cfg['storageList'])
        cfg['storageList'] = ['main.json']
        changed.append('storageList 原为 LMS 示例清单 %s, 已改为 ["main.json"]'
                       % json.dumps(old, ensure_ascii=False))
    _write_storage_config(lms_dir, cfg)
    if cfg.get('noPassword'):
        print('      [!] 安全警告: noPassword=true, 任何能访问这台电脑端口 %s 的人(包括局域网设备)都可直接下单取货。'
              '建议游戏内 /setPassword 设置密码, 并保持 noPassword=false。' % cfg.get('port'))
    return cfg, changed


def inject_index_html(web_dir):
    p = os.path.join(web_dir, 'index.html')
    if not os.path.exists(p):
        fail('index.html 不存在, jar 结构可能已变化: %s' % p)
    try:
        with open(p, 'r', encoding='utf-8') as f:
            html = f.read()
        if PANEL_NAME in html:
            return False
        if '</body>' not in html:
            fail('index.html 中找不到 </body>, 注入失败')
        html = html.replace('</body>', '  %s\n</body>' % INJECT_TAG, 1)
        atomic_write_text(p, html)
    except OSError as e:
        fail('写入 index.html 失败: %s' % e)
    return True


def write_site_config(web_dir, world, locale):
    cfg = {'worldName': world}
    if locale:
        cfg['localeFile'] = locale
    try:
        atomic_write_json(os.path.join(web_dir, 'config.json'), cfg)
    except OSError as e:
        fail('写入 config.json 失败: %s' % e)


def install_mcdr_plugin(instance):
    """可选: 把假人积压提醒插件放进 MCDR 的 plugins 目录。"""
    mcdr_dir = os.path.join(instance, 'mcdr-singleplayer')
    plugins_dir = os.path.join(mcdr_dir, 'plugins')
    if not os.path.isdir(mcdr_dir):
        print('      未检测到 MCDR (mcdr-singleplayer), 跳过这一项。')
        print('      没有 MCDR 也能正常用网站和取货, 只是不会有那条积压红色警告。')
        return False
    if not os.path.isdir(plugins_dir):
        try:
            os.makedirs(plugins_dir)
        except OSError as e:
            print('      创建 %s 失败: %s' % (plugins_dir, e))
            return False
    if not os.path.exists(WATCH_SRC):
        print('      发布包里缺少 tools/%s, 跳过。' % WATCH_DEST_NAME)
        return False
    with open(WATCH_SRC, 'rb') as f:
        new_data = f.read()
    dest = os.path.join(plugins_dir, WATCH_DEST_NAME)
    if os.path.exists(dest):
        with open(dest, 'rb') as f:
            if f.read() == new_data:
                ok('已是最新, 无需更新')
                return True
    try:
        atomic_write_bytes(dest, new_data)
    except OSError as e:
        print('      写入 %s 失败: %s' % (dest, e))
        return False
    ok('已放入 %s' % dest)
    print('      MCDR 正开着: 游戏里执行 !!MCDR reload plugin 生效; 没开: 下次启动自动加载')
    return True


# ---------------------------------------------------------------- properties 转义与同步
def _unescape_prop(s):
    """还原 java properties 里的转义（\\uXXXX、\\:、\\\\ 等）, 支持 UTF-16 代理对。"""
    out = []
    i = 0
    special = {'n': '\n', 't': '\t', 'r': '\r'}
    while i < len(s):
        c = s[i]
        if c == '\\' and i + 1 < len(s):
            n = s[i + 1]
            if n == 'u' and i + 6 <= len(s):
                try:
                    cp = int(s[i + 2:i + 6], 16)
                    i += 6
                    # 高代理 + 紧跟的低代理 -> 还原成 BMP 外字符
                    if 0xD800 <= cp <= 0xDBFF and i + 6 <= len(s) and s[i:i + 2] == '\\u':
                        try:
                            lo = int(s[i + 2:i + 6], 16)
                            if 0xDC00 <= lo <= 0xDFFF:
                                cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00)
                                i += 6
                        except ValueError:
                            pass
                    out.append(chr(cp))
                    continue
                except ValueError:
                    pass
            out.append(special.get(n, n))
            i += 2
            continue
        out.append(c)
        i += 1
    return ''.join(out)


def _escape_prop(s):
    """按 java properties 规则转义。

    Properties.load(InputStream) 按 ISO-8859-1 解码, 非 ASCII 必须写成 \\uXXXX;
    BMP 外的字符(emoji、CJK 扩展 B 区)要拆成 UTF-16 代理对写两个 \\uXXXX,
    否则 %04X 会写出 6 位十六进制, Java 读不回来。
    """
    out = []
    for i, ch in enumerate(s):
        cp = ord(ch)
        if ch == '\\':
            out.append('\\\\')
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\r':
            out.append('\\r')
        elif ch == '\t':
            out.append('\\t')
        elif ch in ':=':
            out.append('\\' + ch)
        elif ch == ' ' and i == 0:
            out.append('\\ ')
        elif cp < 0x20 or cp > 0x7e:
            if cp > 0xFFFF:
                v = cp - 0x10000
                out.append('\\u%04X\\u%04X' % (0xD800 + (v >> 10), 0xDC00 + (v & 0x3FF)))
            else:
                out.append('\\u%04X' % cp)
        else:
            out.append(ch)
    return ''.join(out)


def world_running(save_dir):
    """这个存档现在是否被游戏占用(独占 session.lock)。只在 Windows 上探测, 其他平台返回 False。"""
    lock = os.path.join(save_dir, 'session.lock')
    if not os.path.exists(lock):
        return False
    try:
        import msvcrt
    except ImportError:
        return False
    try:
        with open(lock, 'r+b') as f:
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        return False
    except OSError:
        return True


def check_wh_selector(instance, save_dir):
    """把 wh-selector 的金斧清单指向本存档。

    只替换 jsonFile= 那一行（重复的 jsonFile 行会合并成一行）, 其余配置/注释
    按原始字节原样保留: 用 surrogateescape 读写, GBK 等非 UTF-8 字节不会被
    U+FFFD 替换掉。
    """
    prop = os.path.join(instance, 'config', 'wh-selector.properties')
    target = os.path.join(save_dir, LMS_DIR_NAME, 'checkStorageList', 'main.json')
    if not os.path.exists(prop):
        return
    try:
        with open(prop, 'r', encoding='utf-8', errors='surrogateescape', newline='') as f:
            lines = f.readlines()
    except OSError as e:
        print('      [注意] 无法读取 %s: %s' % (prop, e))
        return
    cur = ''
    for line in lines:
        s = line.strip()
        if s.startswith('jsonFile='):
            cur = _unescape_prop(s[len('jsonFile='):])
    wanted = _escape_prop(target)
    same = (len([l for l in lines if l.lstrip().startswith('jsonFile=')]) == 1
            and cur and os.path.normcase(os.path.normpath(cur)) == os.path.normcase(os.path.normpath(target)))
    if same:
        return
    nl = '\r\n' if any(l.endswith('\r\n') for l in lines) else '\n'
    out, replaced = [], False
    for line in lines:
        if line.lstrip().startswith('jsonFile='):
            if not replaced:
                out.append('jsonFile=%s%s' % (wanted, nl))
                replaced = True
            # 其余重复的 jsonFile 行直接丢弃, 避免「最后一值生效」之外的歧义
        else:
            out.append(line if line.endswith('\n') else line + nl)
    if not replaced:
        out.append('jsonFile=%s%s' % (wanted, nl))
    bak = prop + '.bak'
    if not os.path.exists(bak):
        try:
            atomic_write_bytes(bak, read_bytes(prop))
        except OSError as e:
            print('      [注意] 无法创建备份 %s: %s' % (bak, e))
            return
    try:
        atomic_write_text(prop, ''.join(out), encoding='utf-8', errors='surrogateescape')
    except OSError as e:
        print('      [注意] 无法写入 %s: %s' % (prop, e))
        return
    print()
    if cur:
        print('      [已同步] wh-selector 的金斧清单原指向别的存档:')
        print('               %s' % cur)
    print('      [已同步] 现已指向本存档: %s' % target)
    print('      [已保留] 其余配置项与注释按原始字节原样未动（备份: %s）' % bak)
    if world_running(save_dir):
        print()
        print('      [!] 这个存档正在游戏里运行, 而金斧的路径只在游戏启动时读一次。')
        print('          不重启的话, 现在框选仍会写进旧的清单, 网站也可能还停在旧存档/LMS 自带页面。二选一:')
        print('          · 关掉游戏重进 (推荐)')
        print('          · 或者进游戏执行一次 (不要加引号, 路径里的空格原样保留):')
        print('            /wh file %s' % target)


# ---------------------------------------------------------------- 安装 / 卸载编排
def install(instance, save_name, with_watch=True):
    paths = paths_for(instance, save_name)
    if not os.path.isdir(paths.save_dir):
        fail('存档不存在: %s' % paths.save_dir)
    if not os.path.exists(PANEL_SRC):
        fail('找不到面板脚本: %s' % PANEL_SRC)

    # ---- 预检段: 只读, 全部通过后才产生任何写操作 ----
    print('[1/6] 查找 Carpet-LMS-Addition jar ...')
    jar = find_lms_jar(instance)
    if not jar:
        fail('mods 目录里没有找到包含仓储网站的 LMS jar, 请确认已安装 Carpet-LMS-Addition。')
    print('      使用: %s' % os.path.basename(jar))
    precheck_storage_config(paths.lms_dir)   # 坏 JSON 在此失败, 未动任何文件
    _site_entries(jar)                       # 越界/缺 index.html 在此失败, 未动任何文件
    cfg_before = _read_storage_config(paths.lms_dir)

    # ---- 执行段 ----
    # 快照必须在所有破坏性步骤之前写, 否则中途失败就无从完整回滚。
    write_snapshot(paths, cfg_before)

    print('[2/6] 从 jar 提取原版网站文件 ...')
    extract_site(jar, paths.web_dir)
    ok('提取到 %s' % paths.web_dir)

    print('[3/6] 注入面板脚本 ...')
    try:
        atomic_write_bytes(os.path.join(paths.web_dir, PANEL_NAME), read_bytes(PANEL_SRC))
    except OSError as e:
        fail('复制面板脚本失败: %s' % e)
    injected = inject_index_html(paths.web_dir)
    ok('已注入' if injected else '此前已注入过, 跳过')

    print('[4/6] 读取世界名并写入 config.json ...')
    world = read_world_name(paths.save_dir, save_name)
    locale = find_locale_chunk(jar)
    write_site_config(paths.web_dir, world, locale)
    ok('世界名: %s%s' % (world, ('; 中文物品库: %s' % locale) if locale else '; 未找到中文物品库(面板将显示物品 id)'))

    print('[5/6] 更新 %s ...' % STORAGE_CONFIG)
    cfg, changed = update_storage_config(paths.lms_dir)
    ok('%s, 端口 %s' % (','.join(changed) if changed else '配置无需改动', cfg.get('port')))
    check_wh_selector(instance, paths.save_dir)

    print('[6/6] 安装可选的假人积压提醒插件 (需要 MCDR) ...')
    watched = False
    if with_watch:
        watched = install_mcdr_plugin(instance)
    else:
        print('      已按 --no-watch 跳过 (网站与取货不受影响)')

    print()
    print('安装完成! 接下来:')
    print('  1. 进游戏(存档: %s)' % save_name)
    print('  2. 若网站未运行, 游戏内执行 /storageWebsite start (安装已开启自动启动, 之后重启游戏不再需要)')
    print('  3. 浏览器打开 http://127.0.0.1:%s , 按 Ctrl+F5 强制刷新' % cfg.get('port'))
    print('  4. 游戏里用金斧框选仓库后 /wh add 登记容器 (需安装 wh-selector)')
    print('  5. 网站右上角出现橙色「重要物品」按钮, 主页面登录(游戏名+密码)后即可取货')
    if watched:
        print('  6. 假人积压提醒已就绪: 游戏里输入 !!biw 看当前积压件数, !!biw test 看警告效果')
    print()
    if world_running(paths.save_dir):
        print('=' * 68)
        print('[!] 重要: 你安装时这个存档正被游戏加载着。')
        print('    LMS 在游戏启动那一刻就把「网站目录 + 配置路径」固定死了, 装完不会自动切换,')
        print('    所以现在打开网站很可能还是旧存档的内容, 或者是 LMS 自带的空白页面')
        print('    (表现: http://127.0.0.1:端口/config.json 返回 404)。')
        print('    => 请【完全退出游戏】(回主菜单不算) 再重新进入「%s」, 然后 Ctrl+F5。' % save_name)
        print('=' * 68)
    else:
        print('注意: LMS 的网站目录在游戏进程启动时就固定了。以后换存档, 同样要【完全退出游戏】再进,')
        print('      只回主菜单或 /storageWebsite stop+start 都不管用。')


def list_saves(instance):
    saves_dir = os.path.join(instance, 'saves')
    rows = []
    for name in sorted(os.listdir(saves_dir)):
        d = os.path.join(saves_dir, name)
        if not os.path.isdir(d):
            continue
        rows.append((name, read_world_name(d, name),
                     os.path.isdir(os.path.join(d, LMS_DIR_NAME, WEB_DIR_NAME))))
    if not rows:
        fail('saves 目录下没有存档: %s' % saves_dir)
    print('可用存档:')
    for i, (name, world, installed) in enumerate(rows, 1):
        mark = ' [已安装专栏]' if installed else ''
        title = world if world == name else '%s (文件夹: %s)' % (world, name)
        print('  %d. %s%s' % (i, title, mark))
    for _ in range(3):
        try:
            pick = input('输入编号选择存档(直接回车退出): ').strip()
        except EOFError:
            pick = ''
        if not pick:
            sys.exit(0)
        if pick.isdigit() and 1 <= int(pick) <= len(rows):
            return rows[int(pick) - 1][0]
        print('[没找到] 请输入 1 ~ %d 之间的编号。' % len(rows))
    fail('没有选择存档，安装已取消。')


def _load_snapshot(paths):
    """读取并校验快照; 结构不合法时逐项跳过而不是整体中断。"""
    if not os.path.isfile(paths.snapshot_path):
        return None
    try:
        with open(paths.snapshot_path, 'r', encoding='utf-8') as f:
            snap = json.load(f)
    except (OSError, ValueError) as e:
        print('      [注意] 快照解析失败, 将使用保守回滚: %s' % e)
        return None
    if not isinstance(snap, dict) or not isinstance(snap.get('values'), dict):
        print('      [注意] 快照格式不合法, 将使用保守回滚。')
        return None
    return snap


def _restore_storage_config(paths):
    """按快照逐键还原配置; 单键类型异常跳过该键, 不整体 fail。返回还原的键名列表。"""
    cfg = _read_storage_config(paths.lms_dir)
    snap = _load_snapshot(paths)
    restored = []
    if snap is None:
        # 无快照(或快照损坏): 保守回滚, 两个开关都关掉, 其余字段保持现状。
        cfg['customWebsite'] = False
        cfg['autoStartWebsite'] = False
        restored.extend(['customWebsite', 'autoStartWebsite'])
        print('      [注意] 未找到有效快照, 已关闭 customWebsite / autoStartWebsite;')
        print('             port / storageList 保持现状, 如有需要请手工改回。')
    else:
        vals = snap['values']
        for k in SNAPSHOT_KEYS:
            item = vals.get(k)
            if not isinstance(item, dict):
                print('      [注意] 快照中 %s 的条目格式异常, 跳过该键。' % k)
                continue
            if item.get('present'):
                v = item.get('value')
                if not _valid_snapshot_value(k, v):
                    print('      [注意] 快照中 %s 的值类型异常, 跳过该键。' % k)
                    continue
                cfg[k] = v
            else:
                cfg.pop(k, None)
            restored.append(k)
    if restored:
        try:
            atomic_write_json(paths.config_path, cfg)
        except OSError as e:
            fail('写回 %s 失败(写回阶段): %s' % (STORAGE_CONFIG, e))
    return restored, snap


def _restore_wh_selector(snap):
    """按 manifest 还原 wh-selector.properties 的原始字节; 返回是否处理过。"""
    if not isinstance(snap, dict):
        return False
    m = snap.get('manifest')
    if not isinstance(m, dict):
        return False
    prop = m.get('wh_prop_path')
    if not prop:
        return False
    existed = bool(m.get('wh_prop_existed'))
    try:
        original = unb64(m.get('wh_prop_bytes'))
        if existed and original is not None:
            atomic_write_bytes(prop, original)
            ok('已还原 wh-selector.properties 到安装前内容')
        elif not existed and os.path.isfile(prop):
            os.remove(prop)
            ok('已移除安装时新建的 wh-selector.properties')
    except (OSError, ValueError) as e:
        print('      [注意] 还原 %s 失败: %s' % (prop, e))
    if not m.get('wh_prop_bak_existed') and os.path.isfile(prop + '.bak'):
        try:
            os.remove(prop + '.bak')
        except OSError as e:
            print('      [注意] 删除备份 %s.bak 失败: %s' % (prop, e))
    return True


def uninstall(instance, save_name):
    """按安装前快照/manifest 逆序回滚, 并用 finally 统一清理临时文件。"""
    paths = paths_for(instance, save_name)
    if not os.path.isdir(paths.save_dir):
        saves_dir = os.path.join(instance, 'saves')
        names = sorted(d for d in os.listdir(saves_dir)
                       if os.path.isdir(os.path.join(saves_dir, d))) if os.path.isdir(saves_dir) else []
        fail('存档不存在: %s\n这个实例下的存档文件夹: %s' % (paths.save_dir, ', '.join(names) or '(无)'))
    has_web = os.path.isdir(paths.web_dir)
    has_cfg = os.path.isfile(paths.config_path)
    has_snap = os.path.isfile(paths.snapshot_path)
    if not has_web and not has_cfg and not has_snap:
        ok('这个存档里没有安装本项目，无需卸载。')
        return

    snap = None
    completed = False
    try:
        restored, snap = _restore_storage_config(paths)
        if restored:
            ok('已还原安装前的配置项: %s' % ', '.join(restored))

        index_path = os.path.join(paths.web_dir, 'index.html')
        if os.path.exists(index_path):
            try:
                with open(index_path, 'r', encoding='utf-8') as f:
                    html = f.read()
                if PANEL_NAME in html:
                    html = html.replace('  %s\n' % INJECT_TAG, '').replace(INJECT_TAG, '')
                    atomic_write_text(index_path, html)
                    ok('已从 index.html 移除面板注入')
            except OSError as e:
                fail('移除面板注入失败(写入阶段): %s' % e)

        _restore_wh_selector(snap)
        completed = True
    finally:
        # 成功路径: 清理快照与本次生成的备份; 中断路径: 保留以便修复后重试。
        if completed:
            if os.path.isfile(paths.snapshot_path):
                try:
                    os.remove(paths.snapshot_path)
                except OSError as e:
                    print('      [注意] 删除快照 %s 失败: %s' % (paths.snapshot_path, e))
        else:
            print('      [注意] 卸载未完成, 已保留快照以便重试: %s' % paths.snapshot_path)

    print('网站文件仍保留在 %s (确认不再需要可手动删除该文件夹)。' % paths.web_dir)
    print('游戏内执行 /storageWebsite restart 后恢复原版网站。')
    m = snap.get('manifest') if isinstance(snap, dict) else None
    plugin_path = m.get('plugin_path') if isinstance(m, dict) else paths.plugin_path
    if os.path.exists(plugin_path):
        print('假人积压提醒插件仍保留在 %s (它对所有存档生效, 不需要的话手动删除)。' % plugin_path)
    if os.path.isfile(paths.wh_prop_bak):
        print('安装前的 properties 备份仍保留在 %s (原本就存在, 未由本项目删除)。' % paths.wh_prop_bak)
    print('卸载只改动 checkStorageConfig.json / index.html / wh-selector.properties; '
          '网站目录与 MCDR 插件按上述提示由你确认后处理。')


def main():
    ap = argparse.ArgumentParser(description='重要物品专栏一键安装器')
    ap.add_argument('save', nargs='?', help='存档文件夹名(saves 下的名字)')
    ap.add_argument('--instance', help='游戏实例目录(包含 mods 与 saves)')
    ap.add_argument('--uninstall', action='store_true',
                    help='按安装前快照还原配置并移除面板注入(无快照时仅关闭 customWebsite / autoStartWebsite)')
    ap.add_argument('--no-watch', action='store_true', help='不安装可选的假人物品积压提醒插件(MCDR)')
    args = ap.parse_args()
    instance = resolve_instance(args.instance)
    print('游戏实例: %s' % instance)
    save_name = args.save or list_saves(instance)
    if args.uninstall:
        uninstall(instance, save_name)
    else:
        install(instance, save_name, with_watch=not args.no_watch)


if __name__ == '__main__':
    main()
