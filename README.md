# 回归测试说明

全部使用 **Python / Node 标准库**，不需要联网、不需要安装 pytest / jest / jsdom，也不会碰你真实的游戏目录。
临时数据只写在 `tests/_work/`，每个用例开始前自动清理。

## 运行

在项目根目录执行：

```bash
python -m unittest discover -s tests -p "test_python.py" -v
node tests/test_panel.js
```

或直接：

```bash
python tests/test_python.py
```

预期：Python 30 项通过，Node 15 项通过，合计 **45 项**。

CI 另有一条坏环境冒烟步骤，验证非 UTF-8 locale 下全套仍可运行（锁的是测试宿主的编码兜底是否仍生效）：

```bash
PYTHONUTF8=0 PYTHONIOENCODING=cp1252 python -m unittest discover -s tests -p "test_python.py" -v
```

## 覆盖内容

### `test_python.py`（30 项）

| 组 | 覆盖点 |
|---|---|
| T1 转义往返 | 中文+空格路径、emoji（UTF-16 代理对）、`\ : =`、行首空格、控制字符、字面 `\u`、BMP 外生僻字的 `_escape_prop` → `_unescape_prop` 往返恒等；输出全 ASCII |
| T4 安装原子性 | 纯净 jar 提取清单全等（C/D）；`../../` 越界条目、绝对路径、盘符、UNC 被拒绝且**安装前目录与 marker 完整保留**（A）；4000 字符文件名触发写入异常时同样不留半安装（B）；预检不碰磁盘 |
| T2 快照与卸载 | 快照完整还原 4 项且保留用户自定义字段；快照缺失时保守回滚两个开关；快照值类型异常时逐键跳过而不整体中断；卸载后清理快照 |
| T8 配置读写 | 坏 JSON 预检「零文件改动」；安装后原有 `port`/`customField`/`expireDay`/`noPassword` 保持不变；原子写不留临时文件 |
| T1 properties | GBK 中文注释按原始字节保留（不被 U+FFFD 替换）、CRLF 与其余配置行不变、重复 `jsonFile` 行合并成一行、已存在的 `.bak` 不被覆盖 |
| T9 世界名 | 中文 `LevelName` 正确读取；损坏的 level.dat 回退到存档文件夹名 |
| T5 投影统计 | 同名不同 blockstate 累加（2 个活塞算 2）、`TECHNICAL_SKIP` 剔除空气、numpy 与纯 Python 双路径结果全等、解压上限拒绝压缩炸弹 |
| T6 插件 | 空潜影盒计 1 件并输出「潜影盒×1（空）」、盒内物品×盒数 + 散装混合计数、语言表本地化、`_slot_count` 非法值按 0、消息拆分编号、空语言表不被缓存 |
| T10 import 期副作用 | 三个生产模块重新 exec 后 stdout/stderr 均无输出；强制 numpy 缺失并自证前置条件，避免断言恒真。自建捕获流不经真实 stdout，即使 CI 强制 UTF-8 也能抓住「import 期中文 print」回归 |

### `test_panel.js`（15 项）

使用 Node 内置 `vm` + 手写 DOM 桩加载 `panel/important_panel.js`，记录 `localStorage.setItem` 键名、`fetch` 调用序列、`classList` 状态与定时器。

| 组 | 覆盖点 |
|---|---|
| T3 六种 config 结果 | 404 / fetch reject / 200 无 `worldName` / 空串 / JSON 解析失败：面板**保持锁定**、不启动 `refresh()`、不写任何 `_unknown` 键；200 有效存档名：解锁并渲染 32 行，键名落在真实存档档 |
| T3 超时与并发 | 请求挂起时零写入，5 秒超时后保持锁定并提示；快速开关面板 `config.json` 只请求一次 |
| T3 登录与路径 | 无 token 时「尚未登录」提示不被覆盖；`localeFile` 含 `..` 段被拒绝 |
| T7 数据韧性 | 库存结构不匹配时报可读错误并保留上次库存；慢响应在途时不堆叠第二次 `getData` |
| T7 取货 | `1,024` / `1.5` / `1e3` / `-5` / `0` / `64abc` 全部零 fetch；正常取货调用序列为 `getItem` → `sendGetItemResult`，body 数量正确 |
| T5 关闭守卫 | 面板关闭后轮询回调不再拉数据 |

## 构造测试数据的方式

- LMS jar、gzip NBT `level.dat`、合成 `.litematic`、玩家 `.dat` 都由测试在 `tests/_work/` 内现场生成，仓库里不含任何第三方文件。
- `tools/bot_item_watch.py` 顶层 `from mcdreforged.api.all import *` 用桩模块注入后再导入，因此不需要真的安装 MCDR。

## 没覆盖的部分

真实 Minecraft / LMS 服务端联调、真实浏览器 CSS 渲染、真实 MCDR 运行时加载——这些需要对应的游戏环境，不在纯标准库测试范围内。
