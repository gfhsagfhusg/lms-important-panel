# -*- coding: utf-8 -*-
"""litematic 用料统计 - 统计 .litematic 投影文件里每种方块的数量。

用法:
  python litematic_counts.py <投影文件夹> [输出.json]
  python litematic_counts.py D:\\投影 counts.json

输出 JSON: {"files": {文件名: {volume, blocks}}, "totals": {方块: 总数}, "errors": {}}
依赖: 无硬依赖; 装了 numpy 会快很多(可选)。
用途: 给「重要物品专栏」生成你自己的默认排序 - 用各机器用量从高到低排列,
     再把结果填进 panel/important_panel.js 的 RANKING 数组。
"""
import gzip
import json
import os
import struct
import sys
from collections import Counter

MAX_GZIP_BYTES = 64 * 1024 * 1024   # 单个投影解压上限, 防压缩炸弹耗尽内存
MAX_NBT_ELEMENTS = 4 * 1024 * 1024  # NBT 数组/列表元素上限

try:
    import numpy as np
except ImportError:
    # numpy 可选: 静默降级到 decode_indices_py; import 期禁止 print 中文
    # (本模块被 tests/test_python.py 用 importlib 直接 exec, cp1252 下中文 print 会 UnicodeEncodeError)
    np = None

TECHNICAL_SKIP = {
    "minecraft:air", "minecraft:cave_air", "minecraft:void_air",
    "minecraft:light", "minecraft:structure_void", "minecraft:water",
    "minecraft:lava", "minecraft:bubble_column", "minecraft:fire",
    "minecraft:soul_fire", "minecraft:piston_head", "minecraft:moving_piston",
    "minecraft:bamboo_sapling",
}


class R:
    """最小 NBT 读取器 (big-endian, 覆盖 .litematic 用到的标签类型)。"""
    __slots__ = ("d", "i")

    def __init__(self, d):
        self.d = d
        self.i = 0

    def u1(self):
        v = self.d[self.i]
        self.i += 1
        return v

    def u2(self):
        v = struct.unpack_from(">H", self.d, self.i)[0]
        self.i += 2
        return v

    def i4(self):
        v = struct.unpack_from(">i", self.d, self.i)[0]
        self.i += 4
        return v

    def stri(self):
        n = self.u2()
        v = self.d[self.i:self.i + n].decode("utf-8", "replace")
        self.i += n
        return v

    def payload(self, t):
        if t == 1:
            v = struct.unpack_from(">b", self.d, self.i)[0]
            self.i += 1
            return v
        if t == 2:
            return self.u2()
        if t == 3:
            return self.i4()
        if t == 4:
            v = struct.unpack_from(">q", self.d, self.i)[0]
            self.i += 8
            return v
        if t == 5:
            v = struct.unpack_from(">f", self.d, self.i)[0]
            self.i += 4
            return v
        if t == 6:
            v = struct.unpack_from(">d", self.d, self.i)[0]
            self.i += 8
            return v
        if t == 7:
            n = self.i4()
            if n < 0 or n > MAX_NBT_ELEMENTS or self.i + n > len(self.d):
                raise ValueError("bad byte array length %d" % n)
            v = bytes(self.d[self.i:self.i + n])
            self.i += n
            return v
        if t == 8:
            return self.stri()
        if t == 9:
            et = self.u1()
            n = self.i4()
            if n < 0 or n > MAX_NBT_ELEMENTS:
                raise ValueError("bad list length %d" % n)
            return [self.payload(et) for _ in range(n)]
        if t == 10:
            out = {}
            while True:
                et = self.u1()
                if et == 0:
                    return out
                name = self.stri()
                out[name] = self.payload(et)
        if t == 11:
            n = self.i4()
            if n < 0 or n > MAX_NBT_ELEMENTS or self.i + 4 * n > len(self.d):
                raise ValueError("bad int array length %d" % n)
            v = list(struct.unpack_from(">%di" % n, self.d, self.i))
            self.i += 4 * n
            return v
        if t == 12:
            n = self.i4()
            if n < 0 or n > MAX_NBT_ELEMENTS or self.i + 8 * n > len(self.d):
                raise ValueError("bad long array length %d" % n)
            v = list(struct.unpack_from(">%dq" % n, self.d, self.i))
            self.i += 8 * n
            return v
        raise ValueError("bad tag %d at %d" % (t, self.i))


def decode_indices_np(longs, count, bits):
    arr = np.array(longs, dtype=np.int64).view(np.uint64)
    b = arr.view(np.uint8)
    stream = np.unpackbits(b, bitorder="little")[:count * bits]
    m = stream.reshape(count, bits)
    w = (1 << np.arange(bits, dtype=np.uint64))
    return (m.astype(np.uint64) * w).sum(axis=1)


def decode_indices_py(longs, count, bits):
    out = [0] * count
    bit = 0
    mask = (1 << bits) - 1
    for i in range(count):
        lo = bit >> 6
        sh = bit & 63
        v = longs[lo] >> sh
        if sh + bits > 64:
            v |= longs[lo + 1] << (64 - sh)
        out[i] = v & mask
        bit += bits
    return out


def _palette_counts(pal, weights):
    """按方块名累加：同名的不同 blockstate 合并；空气/水等工程量噪音剔除。"""
    counts = {}
    for i, w in enumerate(weights):
        if not w:
            continue
        name = pal[i].get("Name", "?")
        if name in TECHNICAL_SKIP:
            continue
        counts[name] = counts.get(name, 0) + int(w)
    return counts


def parse_litematic(path):
    with gzip.open(path, "rb") as f:
        data = f.read(MAX_GZIP_BYTES + 1)
    if len(data) > MAX_GZIP_BYTES:
        raise ValueError("投影解压后超过 %d MB: %s" % (MAX_GZIP_BYTES // 1048576, path))
    r = R(data)
    if r.u1() != 10:
        raise ValueError("root not compound")
    r.stri()
    root = r.payload(10)
    regions = root.get("Regions", {})
    agg = {}
    vol_total = 0
    for rname, reg in regions.items():
        pal = reg.get("BlockStatePalette", [])
        states = reg.get("BlockStates")
        size = reg.get("Size", [0, 0, 0])
        if isinstance(size, dict):
            size = [size.get("x", 0), size.get("y", 0), size.get("z", 0)]
        elif not isinstance(size, (list, tuple)):
            size = [0, 0, 0]
        sx, sy, sz = (abs(int(x)) for x in size)
        vol = sx * sy * sz
        if states is None:
            continue
        n = len(pal)
        if n <= 1:
            continue  # 只有空气
        # 由 BlockStates 的实际长度反推位宽, 通常一次命中; 其余候选作为兜底,
        # 避免对 vol 个体素做最多 17 次全量解码(大投影 + 无 numpy 时可达分钟级)。
        # mx < n 仍作为正确性兜底, 猜错时继续尝试下一个候选。
        candidates = []
        for w in ((len(states) * 64) // vol if vol else 0, max(1, (n - 1).bit_length())):
            if 1 <= w <= 16 and w not in candidates:
                candidates.append(w)
        candidates += [x for x in range(1, 17) if x not in candidates]
        best = None
        for w in candidates:
            try:
                if np is not None:
                    idx = decode_indices_np(states, vol, w)
                    mx = int(idx.max()) if vol else 0
                else:
                    idx = decode_indices_py(states, vol, w)
                    mx = max(idx) if idx else 0
                if mx < n:
                    best = (w, idx)
                    break
            except Exception:
                continue
        if best is None:
            raise ValueError("no bit width fits %s/%s" % (path, rname))
        w, idx = best
        if np is not None:
            bc = np.bincount(idx, minlength=n)
            counts = _palette_counts(pal, [int(bc[i]) for i in range(n)])
        else:
            c = Counter(idx)
            counts = _palette_counts(pal, [c.get(i, 0) for i in range(n)])
        vol_total += vol
        for k, v in counts.items():
            agg[k] = agg.get(k, 0) + v
    return vol_total, agg


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else fail_usage()
    out_path = sys.argv[2] if len(sys.argv) > 2 else "litematic_counts.json"
    files = sorted(f for f in os.listdir(folder) if f.lower().endswith(".litematic"))
    if not files:
        print("文件夹里没有 .litematic 文件: %s" % folder)
        sys.exit(1)
    out = {"files": {}, "totals": {}, "errors": {}}
    for i, fn in enumerate(files, 1):
        p = os.path.join(folder, fn)
        try:
            vol, agg = parse_litematic(p)
            out["files"][fn] = {"volume": vol, "blocks": agg}
            for k, v in agg.items():
                out["totals"][k] = out["totals"].get(k, 0) + v
            print("[%d/%d] %-60s vol=%d uniq=%d" % (i, len(files), fn[:60], vol, len(agg)), flush=True)
        except Exception as e:
            out["errors"][fn] = repr(e)
            print("[%d/%d] ERROR %s: %r" % (i, len(files), fn[:60], e), flush=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("完成 -> %s" % out_path, flush=True)


def fail_usage():
    print(__doc__)
    sys.exit(1)


if __name__ == "__main__":
    main()
