# 重要物品专栏 (Important Items Panel)

🎬 **使用前请先看完前两个视频，第三个按需**（本项目的整套流程就是照这个顺序搭的；本仓库只负责给视频里的仓储**网站**加一个「⭐ 重要物品」面板）：

1. [【!?客户端假人全物品!?】](https://www.bilibili.com/video/BV14sgv6uE59/) —— 先看效果与原理，**第一个看这个**。
2. [【假人全物品】从0到1 教你如何安装属于你的假人全物品！！](https://www.bilibili.com/video/BV1gQVS6ZEcy/) —— 动手装之前必看。
3. [【在单人游戏中使用 MCDR 以及 [PB] 备份插件】](https://www.bilibili.com/video/BV1kmHi6aESK/) —— **选看，重要性不高**：只有你想用「假人积压红色提醒」这条可选增强（顺带还想要自动备份）时，才需要照它装 MCDR。不装 MCDR 也不影响网站和取货。

> [!CAUTION]
> **视频 2 其实是一个三集的合集，上面只放了第一集。三集都要看，别少看！三集都要看，别少看！三集都要看，别少看！**
> 少看后两集，安装那一步很容易卡住（漏装模组、漏配 MCDR、装完发现取货没反应），到那时候再回头补课更费劲。

> 视频里没有的网站面板部分，看下面的[快速上手](#快速上手从零到取货约-10-分钟)，或用详细的书面教程 **[教程.md](教程.md)**（从安装到取货逐步带截图式说明 + 常见问题）。
> 打不开 `.md` 的话，同目录下有一份内容相同的纯文本版 **[教程.txt](教程.txt)**，记事本 / 写字板直接能打开。

为 [Carpet-LMS-Addition](https://github.com/Citrus-Union/Carpet-LMS-Addition) 仓储网站增加一个「重要物品专栏」面板：

[![点击观看完整操作演示](https://cdn.jsdelivr.net/gh/gfhsagfhusg/lms-important-panel@main/docs/video-cover.jpg)](https://www.bilibili.com/video/BV12h4h6iEr9/)

*▶ 点击封面观看完整操作演示（B 站，3 分 49 秒）：安装 → 启动网站 → 面板 → 一键取货。*

![仓储网站主界面与右侧的「⭐ 重要物品」入口按钮](https://cdn.jsdelivr.net/gh/gfhsagfhusg/lms-important-panel@main/docs/screenshot-site.png)

*安装完成后：网站主界面，右边缘的橙色按钮就是本面板的入口。*

![「重要物品专栏」面板：32 类物品、中文名 / 物品 ID / 数量齐全，低于一箱（1728）标红，顶部显示当前存档](https://cdn.jsdelivr.net/gh/gfhsagfhusg/lms-important-panel@main/docs/screenshot-panel-important-items.png)

*面板展开后的样子：物品按红石机器用量预排序，库存低于一箱整行标红，顶部「当前存档」按存档分别显示。*

- **重要物品清单**：按红石机器用量预排序的 32 类物品（黏液块、活塞、侦测器……），可拖动排序、搜索、删除、自定义添加（按存档分别记忆）
- **实时库存**：每 10 秒自动刷新，合计该物品所有变体（如 17 种潜影盒）的库存
- **缺货标红**：库存低于一箱（1728）自动红色背景
- **一键取货**：点「取货」输入数量 → 网站自动生成假人到仓库取货下线 → 游戏聊天框出现 `[↑][↓][O]` 按钮，点 `[↑]` 假人带着物品出现在你身边
- **多存档支持**：每个存档独立安装/独立数据，面板顶部显示当前存档名

## 在 LMS 之上，我们加了什么

> LMS 的网站本身已经做得很完整——库存实时刷新、网页下单、假人取货，这些逻辑本项目**一行没改**。我们不替代它，只在旁边补几样「日常取货时更顺手」的东西，外加两处性能优化。

**取货前**：右侧「⭐ 重要物品」面板只列你关心的 32 类物品，按红石机器用料从多到少排好，可拖动、搜索、增删（每个存档各记一份）；库存低于一箱（1728）那一行会整行变红，一眼看出哪个材料见底。

**取货时**：点「取货」先弹确认框，并告诉你「按整格补齐」后实际会拿走多少 —— 避免手滑把 64 打成 640。

**取货后**：面板右上「🧰 找回」会记下每次取货的假人名字、物品和数量，一键复制 `/player <bot> spawn` / `inventory` / `kill`；聊天框那行 `[↑][↓][O]` 刷上去找不到了也不慌。

**装和卸**：`python install.py` 从你已装的 LMS jar 里直接提取网站文件，中文物品名跟着版本自动匹配（不写死哈希）；安装前先做只读预检，网站目录用「暂存目录 + 原子替换」生成，中途失败会完整保留安装前的目录。`--uninstall` 按安装前的快照与改动清单还原配置和 `wh-selector.properties`，并清理临时文件。装了 MCDR 的话，还会顺手把可选插件放进 `plugins/`。

**可选增强**：假人**下线**时扫一遍背包，只要有东西就记下来，之后**每 5 分钟**把「哪只假人、有什么、多少」标红播报一轮（整组连发 3 遍）；在线时不播，LMS 自动取货交付的那种也不算残留。

### 顺手做的性能优化（实测数据）

- **刷新不再重建页面**：面板每 10 秒拉一次库存。以前每次刷新都把 32 行 DOM 拆掉重建，现在先算一个渲染签名（搜索词 + 高亮 + 物品顺序），签名没变就只改变化的库存数字。实测 50 次刷新（库存没变）DOM 插入从 3,200 次降到 **0 次**；20 次刷新（库存全变）从 1,280 次插入 + 660 次写文本降到 **0 次插入 + 134 次写文本**。代价是首次打开稍慢一点（47 ms → 70 ms，只发生一次）。
- **后台不再空转**：标签页切到后台时轮询从 10 秒放宽到 60 秒，切回前台立即刷新。
- **搜索防抖**：停止输入 120 ms 才过滤，连续打字不卡。
- **插件扫描加文件缓存**：`usercache.json` 和每个假人的 `.dat` 按「修改时间 + 大小」缓存，文件没动就不重新解析 NBT。一次扫描 5.26 ms → **1.88 ms**，一小时 180 次合计 947 ms → 339 ms。正确性用 5 个真实存档 + 一个 13 假人 / 29,952 件的合成实例核对过，结果逐条一致。
- **轮询不再堆叠**：库存请求在途时跳过新一轮，响应完成后才记时间，避免大仓库慢响应时多个请求乱序覆盖库存数字。
- **投影位宽反推**：由 `BlockStates` 长度直接推算位宽，通常一次解码命中；保留索引上界校验作为正确性兜底，不再逐个试 17 种位宽。

### 稳定性与安全性设计（v1.1.0）

- **安装原子化**：先对 jar 内全部条目做纯字符串路径校验（拒绝绝对路径、盘符、UNC、`..` 越界、NUL），全部通过后才解压到独立暂存目录，最后原子替换网站目录。越界条目、超长文件名、磁盘满、权限不足、jar 损坏都会**保留安装前的完整网站目录**，不会留下半安装状态。
- **配置写入原子化**：`checkStorageConfig.json`、`config.json`、`wh-selector.properties`、快照都走「同目录临时文件 + `os.replace`」，进程被中断也不会留下截断的 JSON。
- **快照先行**：快照与改动清单在**任何破坏性步骤之前**写入；中途失败也能完整卸载。快照缺字段或类型异常时逐键跳过并告警，不整体中断。
- **properties 无损**：`wh-selector.properties` 用 `surrogateescape` 读写，GBK 等非 UTF-8 注释按原始字节保留；BMP 外字符（emoji、生僻字）按 UTF-16 代理对写成两个 `\uXXXX`，Java 能正确读回。重复的 `jsonFile=` 行会合并成一行。
- **面板按存档隔离**：`config.json` 读取失败、超时或缺少 `worldName` 时，面板保持锁定并提示「存档名读取失败」，**不会**把排序/高亮/增删写进 `_unknown` 档造成跨存档串味；`lsSet()` 数据层守卫兜底，工具栏写盘失败不再显示「假成功」。
- **请求韧性**：`/config.json` 带 5 秒超时（防止请求挂起时面板永久锁定）；库存响应做结构校验，LMS 升级改了返回格式会明确报「数据结构不匹配」并保留上一次库存，而不是静默显示全 0；关闭面板后轮询回调不再拉数据。
- **解压上限**：所有 gzip/NBT 读取设 64 MB 上限并校验数组长度，外部下载的恶意 `.litematic` 不会耗尽内存。

### 边界

不改 LMS 的任何 Java 代码，不碰取货 / 回收 / 假人生成逻辑，网站主体仍是 LMS 原版；也不往存档里塞自定义方块或数据包。面板只读 `/api/storage/*`，取货走的还是 LMS 自己的接口。

## 前置要求

| 组件 | 版本 | 必需 | 说明 |
|---|---|---|---|
| Minecraft Java | 26.1.2 + Fabric | ✅ | 其他版本未测试 |
| [Carpet](https://github.com/gnembon/fabric-carpet) | 适配 26.1.2 | ✅ | LMS 的前置 |
| [Carpet-LMS-Addition](https://github.com/Citrus-Union/Carpet-LMS-Addition) | **v1.15.0** | ✅ | 仓储网站本体（本面板的宿主，已测试版本） |
| [wh-selector](https://github.com/Citrus-Union/wh-selector) | 26.1.2-0.1.0 | 推荐 | 金斧框选仓库容器、`/wh add` 登记到网站 |
| Python | 3.6+ | 仅安装时 | 仅标准库，无需联网 |
| [ASA 反死亡生存助手](https://github.com/jfglzs/Antideath-survival-assistant) | 可选 | 推荐 | 装了它点 `[↑]` 可自动上线假人（推荐一起使用，效果更佳） |
| [MCDR](https://github.com/MCDReforged/MCDReforged) | 2.x（`mcdr-singleplayer` 亦可） | 推荐 | 只有「假人积压红色提醒」需要它，装了安装器会自动带插件（推荐一起使用，效果更佳） |

> 「必需」列标 **推荐** 的几项不是硬性要求，但**推荐一起使用，效果更佳**：ASA 让取货后假人自动到身边，MCDR 负责假人积压红色提醒。

## 快速上手：从零到取货（约 10 分钟）

> 已经装好 LMS 并用过它的仓储网站？直接从第 2 步开始。

1. **装前置**（只需一次）：Fabric + Carpet + Carpet-LMS-Addition **v1.15.0**。进世界后聊天执行 `/getStorageData` 有输出，说明 LMS 正常。
2. **装面板**：下载解压本项目 → 在解压目录打开终端（Windows：文件夹地址栏输 `cmd` 回车）→ `python install.py` → 按提示确认游戏目录（一般会自动找到；找不到就把你的 `.minecraft` 文件夹拖进窗口回车）→ 输入存档编号，看到「安装完成!」。
3. **启动网站**：进入该存档，聊天执行 `/storageWebsite start`（只需这一次；安装已开启自动启动，以后重启游戏自动起）。
4. **打开网站**：浏览器访问 `http://127.0.0.1:7000`（端口以安装完成提示为准），按 `Ctrl+F5` 强刷 → 右边缘出现橙色「⭐ 重要物品」按钮。
5. **登记仓库**（首次，需可选的 wh-selector）：手持金斧，左键+右键点仓库两个对角 → `/wh add` → 聊天提示扫描到 N 个容器，网站主页出现库存（青色框 = 已登记容器）。
6. **设密码并登录**：游戏内 `/setPassword 你的密码` → 网站右上角用「游戏名 + 密码」登录。
7. **取货**：点开「⭐ 重要物品」→ 点物品行「取货」→ 输入数量 → 游戏聊天框出现 `[↑][↓][O]` → 点 `[↑]` 假人带货上线（装了 ASA 的连点都不用点，自动上线）；`[O]` 开假人背包拿东西，`[↓]` 让假人下线。

卡住了？看[常见问题](#常见问题)：网站打不开 → 游戏内 `/storageWebsite status`；点「取货」没反应 → 用 Chrome/Edge 等真实浏览器打开网站。

## 安装（一条命令）

```bash
python install.py
```

安装器会：

1. 自动查找游戏实例目录（会在当前文件夹附近、`%appdata%\.minecraft`、PCL/HMCL 的 `versions\<版本>` 里找，**优先挑装了 Carpet-LMS-Addition 的实例**；找到多个让你选，找不到会提示常见位置并允许直接粘贴路径；也可用 `--instance "D:\你的版本目录"` 指定）
2. 列出所有存档让你选择（或直接 `python install.py 存档文件夹名`）
3. **从你自己安装的 LMS jar 中提取原版网站文件**（仓库不携带任何第三方文件，版本永远和你装的一致）；动手前先做**只读预检**：配置能否解析、jar 结构是否合法、路径是否越界，任一项不通过就直接报错且不改动任何文件
4. 注入面板脚本并打开网站的 `customWebsite` 开关
5. 从存档 `level.dat` 读取世界名，面板顶部显示「当前存档：xxx」

然后：

1. 进游戏；若网站未运行，游戏内执行 `/storageWebsite start`（安装已开启 `autoStartWebsite`，之后重启游戏自动启动，不用再敲）
2. 浏览器打开 `http://127.0.0.1:7000`，按 `Ctrl+F5` 强制刷新
3. 右侧出现橙色「⭐ 重要物品」按钮

> 注意：每次运行安装器都会用 jar 里的原版文件**重建** `customStorageWebsite` 目录——如果你在该目录放过自己的自定义修改，会被覆盖（面板脚本和 config.json 由安装器重新生成，不受影响）。重建采用暂存目录 + 原子替换，过程中若失败会回滚到原目录，不会只写一半。

### 卸载

```bash
python install.py --uninstall 存档名
```

会按安装前的快照还原 `checkStorageConfig.json`（`customWebsite`、`autoStartWebsite`、`port`、`storageList` 四项）、移除 `index.html` 里的面板注入、把 `wh-selector.properties` 还原到安装前的原始字节，并清理本次生成的快照与 `.bak`。卸载输出会列出仍保留的网站目录、MCDR 插件和原本就存在的备份路径，由你确认后再手动处理。游戏内 `/storageWebsite restart` 即恢复原版网站。

> 找不到快照（或快照损坏）时会执行**保守回滚**：把 `customWebsite`、`autoStartWebsite` 都置为 `false`，`port`/`storageList` 保持现状并给出提示，不会假装完整还原。

## 使用

![仓储网站仪表盘：统计卡片与物品列表，每件物品都可一键取货](https://cdn.jsdelivr.net/gh/gfhsagfhusg/lms-important-panel@main/docs/screenshot-dashboard.png)

1. **登记仓库**：游戏里左手拿金斧右键两个角框选仓库区域，`/wh add` 写入网站（wh-selector 功能；青色高亮 = 已登记容器，`/wh hide` 可关）
2. **设置密码**：游戏内 `/setPassword 你的密码`
3. **网站登录**：右上角输入游戏名 + 密码登录（不登录只能看库存，取货需要登录）
4. **面板操作**：
   - 拖 `⠿` 调整顺序（按存档记忆）；「默认排序」恢复机器用量排序
   - 右键物品 → ⭐高亮 / 🗑删除
   - 「＋ 添加物品」可搜索当前版本全部 1500+ 种物品加入专栏
   - 点「取货」→ 输入数量 → **确认框**（会立刻搬走、无法撤回，所以多问一次）→ 游戏聊天框出现 `[↑][↓][O]` → 点 `[↑]` 假人带货上线，`[O]` 开假人背包拿东西，`[↓]` 让假人下线
   - 取错了？点右上「**🧰 找回**」，里面记着最近取货的假人名，可一键复制 `/player <假人名> spawn` 等命令；批量回收用游戏内 `/cleanGetItemBot clean 1000`（详见[教程.md](教程.md) 常见问题）

### 换存档 / 新建存档

三部分作用范围不同：**网站和面板是「一个存档装一次」，积压提醒插件是「一次装全局」**。

- 新存档：`python install.py` → 菜单里选那个存档；卸载用 `python install.py --uninstall <存档名>`，只影响这一个存档。
- 积压提醒插件装在 `mcdr-singleplayer\plugins\`，跟随整个实例，换存档/开新档都不用重装（它自己识别当前运行的存档）。
- 完整步骤与原理见 [教程.md](教程.md) 第 10 节。

> ⚠️ 已知上游限制：同一次游戏进程内**切换存档**时，LMS v1.15.0 的网站目录（`checkStorageConfig.json`、`customStorageWebsite`）是 `static final`，在**启动时按第一个加载的存档固定**，之后 `/storageWebsite restart` 也不会变。切换存档后请**完全退出游戏**（回主菜单不算）再重新进入目标存档。

## 可选增强：假人积压红色提醒（需 MCDR）

取货假人把自己装满了，你只拿走一部分就下线，剩下的会一直压在它身上，游戏里又看不见。
安装器检测到 `<实例>\mcdr-singleplayer` 时，会把 `tools/bot_item_watch.py` 放进 `plugins`：

![假人下线时背包还有东西，聊天框出现的红色「背包未清空」提醒（截图已裁去顶部调试信息）](https://cdn.jsdelivr.net/gh/gfhsagfhusg/lms-important-panel@main/docs/screenshot-game-bot-getitem.jpg)

*假人下线时背包还有东西，游戏聊天框就会滚动播报红色「背包未清空」提醒（截图已裁去顶部的坐标 / 种子等调试信息，仅保留警告行）。*

**报警机制（只认「下线时背包还有东西」，不设数量阈值）**

| 环节 | 行为 |
|---|---|
| 触发时机 | 假人**下线**那一秒扫背包。在线（召唤出来还没点下线）完全不看，人走开了也不会吵 |
| 背包是空的 | 什么都不做，不记录、不播报 |
| 背包有东西 | 记下这只假人，之后**每 5 分钟**播一轮：`❗bot_getitem_3 背包未清空：钻石×64、潜影盒×2（钻石1728、红石1728）` |
| 播报力度 | 全部**红色加粗**，同一组消息连发 **3 遍**，每遍间隔 1 秒 |
| 太长怎么办 | 单条超过约 180 字符自动拆成 `(1/2)`、`(2/2)`；同组整体重复 3 遍，不会只发一半 |
| 自动取货不算 | LMS 自动取货是「上线时装满、又自动下线」，下线件数比上线时多 → 判为交付，不记录（避免每次取货都开始催） |
| 清空后 | 取完之后下一轮扫描自动移除，停止播报 |

> 物品名会自动读游戏自带的语言文件译成中文（如 钻石、活塞、下界合金剑）；读不到语言文件时才退回游戏 id。潜影盒会单独列出盒内物品，**空的潜影盒也算一件**——假人身上只剩空盒时同样会提醒你清空。

```bash
python install.py            # 检测到 MCDR 就自动安装；没有就跳过
python install.py --no-watch # 明确不装
```

游戏里 `!!biw` 看当前哪些假人还有残留，`!!biw test` 立即播一轮看效果；
间隔（`report_interval`）、遍数（`repeat`）、单条字数（`max_chars`）都在
`mcdr-singleplayer/plugindata/<存档>/config/bot_item_watch/config.json`。

> 没有 MCDR 的玩家：所有其他功能照常可用，只是没有这条提醒（纯静态网站无法向游戏聊天框发消息）。
> 手动查看用 `/cleanGetItemBot view`，批量回收用 `/cleanGetItemBot clean 1000`。

## 项目结构与自测

```
lms-important-panel/
├─ install.py                  ← 一键安装 / 卸载（仅 Python 标准库）
├─ panel/important_panel.js     ← 面板，安装时注入网站 index.html
├─ tools/bot_item_watch.py      ← 可选 MCDR 单文件插件
├─ tools/litematic_counts.py    ← 投影用料统计（可选）
├─ docs/                        ← 截图
├─ tests/                       ← 纯标准库回归测试
│  ├─ test_python.py
│  ├─ test_panel.js
│  └─ README.md
├─ README.md / 教程.md / 教程.txt
└─ LICENSE / .gitignore
```

自测不需要联网、不需要安装任何依赖（Python 用 `unittest`，前端用 Node 内置 `vm` + 手写 DOM 桩）：

```bash
python -m unittest discover -s tests -p "test_python.py" -v
node tests/test_panel.js
```

覆盖安装器的原子替换与失败回滚、路径越界校验、快照与卸载分支、properties 中文/emoji/GBK 往返、投影统计双解码路径与空气过滤、插件空潜影盒计数；以及面板在 6 种 `config.json` 结果下的锁状态与 localStorage 键名、超时、轮询去重、库存结构校验、取货数量校验与两步 API 调用序列。详见 `tests/README.md`。

## 自定义默认排序（可选）

默认排序来自 44 台红石机器投影的用料统计。想要按自己机器排序：

```bash
python tools/litematic_counts.py "你的投影文件夹" counts.json
```

打开 `counts.json` 看 `totals`，按数量从高到低调整 `panel/important_panel.js` 里的 `RANKING` 数组，然后重跑 `python install.py 存档名` 覆盖安装。缺货阈值一箱（1728）在该文件顶部 `ONE_STACK` 处修改。

## 常见问题

**网站打不开 / 打不开 7000 端口**
游戏内执行 `/storageWebsite start`；安装器已把 `autoStartWebsite` 设为 true，重启游戏后会自动启动。端口在 `saves/存档名/carpetlmsaddition/checkStorageConfig.json` 的 `port` 修改。

**点「取货」没反应**
取货用浏览器原生弹窗输入数量。某些内嵌浏览器/预览 iframe 会禁用弹窗 → 请用 Chrome/Edge 等真实浏览器打开网站。

**裸 `/getStorageData` 命令没输出**
如果你装了 ASA，这是它的正常行为（它拦截全量列表喂给自己的缓存）。网站和本面板不受影响。

**面板里物品显示英文 id 而不是中文名**
安装器会从 jar 里自动匹配中文物品库（`zh_cn-*.js`）；如果面板来自手动复制，它也会尝试自动嗅探。都失败时会退化为显示 id，功能不受影响。

**登录过期 / 401**
token 有效期由 LMS 的 `expireDay` 控制（安装器默认 7 天，可在 `checkStorageConfig.json` 改），过期后在主页面重新登录。

**面板提示「存档名读取失败，刷新页面重试」**
说明 `/config.json` 返回 404、超时或缺少 `worldName`。常见于网站没装好、LMS 未启动或换存档后没强刷。面板会保持锁定、不写任何偏好，避免串档；刷新页面（`Ctrl+F5`）后重试即可。

**面板提示「库存数据结构不匹配，可能 LMS 版本不兼容」**
面板会保留上一次的库存数字并给出可读提示，而不是把 32 行刷成全 0。请确认 LMS 仍是已测试的 v1.15.0。

**安装中途报错，网站目录会不会坏？**
不会。安装器先做只读预检，再解压到暂存目录，全部成功后才原子替换；任何失败都会保留安装前的完整目录，并提示原因。

## 安全说明（请务必阅读）

- **网站开放范围**：LMS 仓储网站监听 `0.0.0.0`（LMS 自身行为，本面板无法改变），即同一局域网内的设备都可以访问 `http://你的电脑IP:端口/`。**请务必在游戏内 `/setPassword` 设置强密码**，保持 `noPassword=false`；安装器检测到 `noPassword=true` 时会打印警告。
- **面板数据流向**：面板只读取本站登录态（localStorage 的 token）并只向本站 `/api/*` 发请求，**不向任何第三方发送数据**；你的排序/高亮/增删偏好只存在浏览器 localStorage，不上传。
- **动态加载限制**：中文物品库文件路径来自安装器写入的 `config.json`，面板只接受站内相对路径（`/xxx.js`），远程地址、协议相对地址、含 `.`/`..` 路径段的地址一律拒绝，并用 `URL` 二次校验同源。
- **安装器行为**：install.py 全程只读写本机文件（mods jar、存档目录），无任何网络请求，不收集任何信息；jar 条目路径经过越界校验，配置写入均为原子替换，安装前会保存可回滚的快照与改动清单。

## 更新记录

**v1.1.0（稳定性整改）**：修复解压校验时机导致的半安装、config 失败路径下的存档偏好串档、请求挂起与轮询堆叠、回滚范围不完整、GBK 与非 BMP 路径损坏等 22 项问题；新增原子写入、安装快照/改动清单、5 秒超时、库存结构断言、解压上限、纯标准库测试套件。修复项与验证方式见仓库内测试与 `tests/README.md`。

**v1.0.0**：初版，为 LMS 仓储网站增加重要物品专栏面板。

## 致谢

这个项目能存在，全靠下面几位的工作。**面板、安装器、插件都是本项目独立实现的，没有修改也没重新分发它们的源码。**

- [Carpet-LMS-Addition](https://github.com/Citrus-Union/Carpet-LMS-Addition)（Citrus-Union，GPL-3.0）—— 仓储网站本体、取货假人 `bot_getitem_*`、`/getItem`、`/cleanGetItemBot`、`/storageWebsite` 全部来自这里。本项目的网站页面是安装时**从你自己下载的 jar 里提取**的，仓库里不含它的任何文件；面板只是往 `index.html` 注入一行 `<script>`。
- [wh-selector](https://github.com/Citrus-Union/wh-selector)（Citrus-Union，GPL-3.0）—— 金斧框选、`/wh add` 把容器坐标写进 `main.json`；仓库能被扫描成库存，靠的就是它。
- [Antideath-survival-assistant](https://github.com/jfglzs/Antideath-survival-assistant)（jfglzs，CC0）—— 可选但很值：取货后自动把假人叫到身边、自动开背包/自动下线。顺带一提，正因为它会拦截全量 `/getStorageData` 的输出，才有了「在网页上直接看库存 + 一键取货」这个更省事的替代方案。
- [Fabric](https://fabricmc.net/)、[Carpet](https://github.com/gnembon/fabric-carpet)、[MCDReforged](https://github.com/Fallen-Breath/MCDReforged) —— 承载上面一切的运行环境；本项目的「假人积压红色提醒」就是 MCDR 的一个单文件插件。
- **视频教程**：[README 顶部那三期](https://www.bilibili.com/video/BV14sgv6uE59/) B 站视频，整套搭建流程（装模组、开 MCDR、圈仓库、取货）都出自它们；本仓库只补了视频里没有的「网站面板」部分。

`docs/` 里的界面截图取自真实存档，已裁掉玩家名；其中游戏内聊天日志截图（`screenshot-game-bot-getitem.jpg`）已裁去顶部的坐标 / 种子 / FPS 等调试信息，仅保留取货假人 `bot_getitem_*` 的「背包未清空」警告行，不含真实玩家名。

## 许可

本项目代码以 [MIT](LICENSE) 发布。仓库**不包含**任何第三方项目的代码或资源——运行时网站文件由安装器从用户自己安装的 Carpet-LMS-Addition（GPL-3.0）中提取。第三方项目的许可见上方「致谢」。
