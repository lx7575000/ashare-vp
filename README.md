# A股量价分析工具（ashare-vp）

一个零第三方依赖的 Python 命令行工具，用于每日分析 A 股创新药、军工、生物医药 ETF 以及主要宽基指数的量价状态，生成 Markdown / JSON / CSV 日报、盘中快照、条件化建议和 H5 可视化页面。

> 仅用于量化研究与学习，不构成任何投资建议。

## 分析范围

默认资产池共 **25 个标的**，可在 `config/assets.json` 中自由增删：

| 分组 | 数量 | 标的 |
|---|---:|---|
| 创新药ETF | 5 | 159992 银华、516080 易方达、159835 建信、517110 国泰、159858 南方 |
| 军工ETF | 5 | 512660 国泰、512710 富国龙头、512810 华宝、512680 广发、512560 易方达 |
| 生物医药ETF | 4 | 512290 国泰、159859 天弘、159839 汇添富、516500 华夏生物科技 |
| 宽基指数 | 11 | 上证指数、深证成指、创业板指、科创50、沪深300、上证50、中证500、中证1000、中证A500、中证全指、北证50 |

## 功能特性

- **收盘日报 + 盘中分析**：收盘后生成完整日报；工作日 10:30 / 11:00 / 14:00 可用实时快照生成盘中分析。
- **多数据源容错**：腾讯财经 → 新浪财经 → 东方财富，单源失败自动切换；某只标的失败不影响整体报告。
- **本地缓存**：按标的缓存日线，当日重复运行不重复请求；支持离线模式与历史日期回看。
- **量价指标**：量比（5/20日）、成交量分位、MA5/10/20/60、OBV、MFI、RSI、ATR、VWAP、量价相关性、20日高低点位置等。
- **信号识别**：放量突破、缩量新高、放量上涨/下跌、缩量回调、放量滞涨、量价顶/底背离、天量/地量、超买/超卖等。
- **综合评分**：趋势、量能、OBV、动量、位置五维打分，输出 0–100 分与强势/偏强/中性/偏弱/弱势评级。
- **条件化建议**：A/B/C/D 四级建议、参考仓位、触发条件、参考止损，并识别近高/近低标的。
- **跨时段连贯性**：10:30 → 11:00 → 14:00 → 收盘自动对比上一份快照，跟踪评分与信号变化。
- **多格式输出**：Markdown 便于阅读，JSON 便于二次开发，CSV 便于 Excel 分析；建议同时写入三种格式。
- **H5 可视化**：单文件 HTML，内嵌数据，支持分组筛选、搜索、标的全量表格、价格/成交量图和建议详情。
- **轻量 HTTP 服务**：仅标准库，提供 H5、快照 JSON 与健康检查接口，便于手机或局域网访问。
- **零依赖**：仅使用 Python 标准库，Python 3.10+ 即可运行。

## 快速开始

```bash
cd /Users/liuxin/Documents/deepseek-harness/default-workspace

# 查看资产池
python3 -m ashare_vp --list

# 生成最新交易日日报（默认 md + json + csv + H5 + 快照）
python3 -m ashare_vp

# 附带完整指标明细
python3 -m ashare_vp --detail

# 只看创新药和宽基指数
python3 -m ashare_vp --group 创新药 --group 宽基

# 指定历史日期
python3 -m ashare_vp --date 2026-10-16

# 只看某只 ETF
python3 -m ashare_vp --code 159992

# 离线模式（只读本地缓存）
python3 -m ashare_vp --offline

# 强制刷新行情
python3 -m ashare_vp --refresh

# 盘中分析（10:30 / 11:00 / 14:00 / 收盘；auto 按当前时间推断）
python3 -m ashare_vp.session --session auto
python3 -m ashare_vp.session --session 1030
python3 -m ashare_vp.session --session 1100

# 启动 H5 / 快照服务
python3 -m ashare_vp.server --port 8765

# 只打印未来调度时间，不执行
python3 -m ashare_vp.scheduler --dry-run

# 立即执行一次定时任务逻辑
python3 -m ashare_vp.scheduler --once
```

也可以使用封装脚本：

```bash
./run_daily.sh
./run_daily.sh --group 军工 --detail
```

## 线上部署（每日自动更新）

仓库提供了静态站点整理脚本和 GitHub Actions 模板，可把每天的报告发布到 Cloudflare Workers 静态资源（也适用于 Pages、COS 等静态托管）：

- `scripts/build_site.py`：把 `reports/h5/` 整理为 `site/`（首页 / 历史 / 归档 / JSON），自动脱敏本机路径、保留 120 天。
- `wrangler.jsonc`：Cloudflare Worker 配置，Worker 名 `ashare-vp`，静态目录 `./site`。
- `.github/workflows/daily.yml`：每个交易日 18:20（北京时间）生成日报、提交归档并部署。
- 完整方案、免费额度与国内访问备选：[docs/部署方案.md](docs/部署方案.md)。

线上示例：<https://ashare-vp.narcissusliu0428.workers.dev/>

```bash
python3 -m ashare_vp --quiet          # 生成当天日报
python3 scripts/build_site.py         # 整理为可部署的 site/
python3 -m http.server 8766 -d site   # 本地预览 http://127.0.0.1:8766
npx wrangler deploy                   # 手动部署到 Cloudflare Worker
```

## 输出

收盘报告默认写入 `reports/YYYY-MM-DD/`：

```
reports/2026-10-16/
├── vp_report.md    # Markdown 日报
├── vp_report.json  # 结构化指标、信号与建议
└── vp_report.csv   # 扁平表，UTF-8 BOM，Excel 可直接打开
```

H5 与快照：

```
reports/h5/
├── 2026-10-16_1100.html
├── 2026-10-16_1400.html
├── 2026-10-16_close.html
├── latest.html       # 最近一次发布
└── index.html        # 历史快照入口

data/snapshots/
├── 2026-10-16/
│   ├── 1100.json
│   ├── 1400.json
│   └── close.json
└── index.json        # 快照索引
```

Markdown 日报包含：

1. **市场概览**：涨跌分布、20日线之上比例、中位涨跌/量比、市场状态、分组表现。
2. **操作建议**：市场判断、参考仓位、近高/近低数量、A/B/D 级条件化建议。
3. **重点信号**：相对强势/弱势榜、放量异动、量价背离。
4. **分组明细**：创新药、军工、生物医药、宽基指数逐只指标与信号。
5. **全量评分排序**：含评级、信号与建议等级。
6. **指标明细**（加 `--detail` 时）。
7. 指标说明、数据说明与免责声明。

日期处理：如果当天是周末或行情尚未更新，会自动使用最近交易日，并在报告中注明。例如在 2026-10-18（周日）运行，报告日期为 2026-10-16。

## 命令行参数

### 收盘日报 `python3 -m ashare_vp`

| 参数 | 说明 |
|---|---|
| `--list` | 列出资产池并退出 |
| `--date YYYY-MM-DD` | 分析截止日期，默认今天 |
| `--group NAME` | 按分组筛选，可重复，支持名称包含匹配 |
| `--code CODE` | 按代码筛选，可重复 |
| `--source auto/tencent/sina/eastmoney` | 指定数据源，默认 `auto` |
| `--config PATH` | 自定义资产池配置 |
| `--cache-dir PATH` | 缓存目录，默认 `data/cache` |
| `--output-dir PATH` | 报告目录，默认 `reports` |
| `--snapshot-dir PATH` | 快照目录，默认 `data/snapshots` |
| `--h5 / --no-h5` | 是否生成 H5，默认开启 |
| `--snapshot / --no-snapshot` | 是否留存快照，默认开启 |
| `--start-date YYYY-MM-DD` | 抓取起始日期，默认读取配置 |
| `--min-bars N` | 最少日线数量，默认读取配置（30） |
| `--timeout SECONDS` | 单次请求超时 |
| `--offline` | 只使用本地缓存 |
| `--refresh` | 忽略当日缓存，强制重新抓取 |
| `--format md,json,csv` | 输出格式 |
| `--detail` | Markdown 增加完整指标明细 |
| `--top N` | 强势/弱势榜数量，默认 5 |
| `--quiet` | 只输出报告文件路径 |

### 盘中分析 `python3 -m ashare_vp.session`

| 参数 | 说明 |
|---|---|
| `--session auto/1030/1100/1400/close` | 时段；`auto` 按当前时间推断 |
| `--force` | 快照日期不是今天时也使用（预览/回放）；同日跨时段运行也会在标题标注“回放” |
| `--no-quote` | 不使用实时快照，只用日线缓存 |
| `--require-current` | 没有当日实时快照时直接跳过，避免节假日生成过期报告 |
| `--refresh` | 强制刷新日线缓存 |
| 其余参数 | 与收盘日报相同（`--group`、`--code`、`--offline`、`--top` 等） |

盘中成交量会按“已交易时长 / 240 分钟”外推到全天等效值，仅用于量比和量价结构判断，不代表真实全日成交。快照时间优先按行情时间戳计算，避免收盘后重复外推。

### 定时调度 `python3 -m ashare_vp.scheduler`

| 参数 | 说明 |
|---|---|
| `--at 10:30,14:00` | 每日运行时间，逗号分隔 |
| `--max-lag-minutes 30` | 系统休眠后错过任务超过该分钟数则跳过；0 表示不限制 |
| `--once` | 立即执行一次后退出 |
| `--dry-run` | 只打印未来 6 个任务时间 |
| `--force` | 忽略周末/休市/已执行状态，立即执行 |
| `--holiday-file PATH` | 可选 JSON 数组，列出休市日期 `YYYY-MM-DD` |
| `--state-file PATH` | 运行状态文件，默认 `data/scheduler_state.json` |
| 其余参数 | 与盘中分析相同 |

调度器在周末直接跳过；工作日通过 `--require-current` 检查实时快照日期，非交易日不会继续抓取 25 个标的的日线。任务成功后写入状态文件，同一交易日同一时段不会重复执行。

### HTTP 服务 `python3 -m ashare_vp.server`

| 参数 | 说明 |
|---|---|
| `--host` | 监听地址，默认 `127.0.0.1` |
| `--port` | 端口，默认 `8765` |
| `--output-dir` | 报告目录，默认 `reports` |
| `--snapshot-dir` | 快照目录，默认 `data/snapshots` |

接口：

| 路径 | 说明 |
|---|---|
| `/`、`/h5/` | 最近一次 H5（`reports/h5/latest.html`） |
| `/health` | 健康检查，返回 H5 是否存在、快照数量与最新快照 key |
| `/api/latest` | 最新快照 JSON |
| `/api/snapshots` | 快照索引列表 |
| `/h5/*` | H5 静态文件 |
| `/snapshots/*` | 快照 JSON 文件 |

## 操作建议模型

对每只标的同时输出：

- **等级**：A 积极关注、B 谨慎参与、C 观察等待、D 风险回避。
- **参考仓位**：根据市场状态（偏强/震荡/偏弱）与建议等级给出区间。
- **触发条件**：例如“回踩突破位缩量企稳”“放量收复 MA20”。
- **参考止损**：收盘价下方约 1.5×ATR，或 MA20/近低等关键位。
- **近高/近低**：收盘价距 20 日高点/低点 1.5% 以内，或创 20 日新高/新低。
- **连贯性**：与同一交易日上一时段快照对比，统计评分上调/下调数量和信号变化。

建议同时写入 `vp_report.md`、`vp_report.json`、`vp_report.csv`、H5 payload 和快照 JSON。建议是规则化统计结果，不构成投资建议。

## 指标体系

| 指标 | 含义 |
|---|---|
| 涨跌% | 当日收盘相对前一交易日收盘 |
| 5日% / 20日% | 近 5 / 20 个交易日累计涨跌 |
| 量比5 / 量比20 | 当日成交量 ÷ 前 5/20 个交易日均量（不含当日） |
| 成交量分位 | 当日成交量在近 60 个交易日中的分位（0–100） |
| MA5/10/20/60 | 收盘价简单移动平均 |
| MA20偏离 | 收盘价相对 MA20 的百分比偏离 |
| 趋势 | 多头排列 / 空头排列 / 均线交织偏强或偏弱 |
| OBV | 能量潮，上涨日加成交量、下跌日减成交量 |
| OBV趋势 | OBV 相对自身 20 日均线及 5 日变化方向 |
| MFI14 | 结合价格与成交量的资金流量指标（0–100） |
| RSI14 | 相对强弱指标（0–100） |
| ATR% | 14 日平均真实波幅 ÷ 收盘价 |
| VWAP20偏离 | 收盘价相对 20 日成交量加权均价 |
| 量价相关 | 近 20 日收益率变化与成交量变化率的相关系数 |
| 20日位置 | 收盘价在近 20 日高低区间中的位置（0–100） |

### 信号规则（摘要）

- **放量突破**：收盘创 20 日新高，量比5 ≥ 1.3 且当日上涨。
- **缩量新高**：收盘创 20 日新高，但量比5 < 0.8，需警惕无量突破。
- **放量上涨 / 放量下跌**：涨跌幅绝对值 ≥ 1%，量比5 ≥ 1.5。
- **缩量回调**：当日下跌且量比5 ≤ 0.7，通常视为良性回调。
- **放量滞涨**：涨跌幅绝对值 < 0.5%，量比5 ≥ 2.0。
- **量价顶背离**：收盘创 20 日新高、OBV 未创新高且量比5 < 1.0。
- **量价底背离**：收盘创 20 日新低、OBV 未创新低且量比5 < 1.0。
- **天量 / 地量**：量比20 ≥ 2.5 / ≤ 0.5。
- **超买 / 超卖**：RSI14 ≥ 75 或 MFI14 ≥ 85 / RSI14 ≤ 25 或 MFI14 ≤ 15。

### 评分

以 50 分为基准，按以下五个维度加减分后截断到 0–100：

- **趋势**（约 -25 ~ +25）：价格与 MA20/MA60、均线排列、MA20 斜率。
- **量能**（约 -15 ~ +20）：涨跌方向与量比配合、突破量能、天量下跌。
- **OBV**（约 -15 ~ +20）：OBV 与均线、趋势、新高及背离。
- **动量**（约 -8 ~ +10）：RSI、MFI 区间。
- **位置**（约 -2 ~ +3）：20 日区间位置。

评级：≥78 强势、62–77 偏强、45–61 中性、30–44 偏弱、<30 弱势。评分只反映量价状态，不代表未来收益。

## 数据源、缓存与容错

- 默认顺序：**腾讯财经 → 新浪财经 → 东方财富**。
- 腾讯/新浪提供 OHLCV；东方财富在可用时额外提供成交额与换手率。
- 成交量统一换算为“手”：新浪返回股数，代码中除以 100；腾讯/东财本身为手。
- ETF 成交额缺失时按 `成交量 × 100 × (最高+最低+收盘)/3` 估算，报告以 `~` 标注；指数不做估算。
- 缓存文件为 `data/cache/{exchange}{code}.json`，含抓取时间与原始日线。
- 当日已抓取过的标的直接读缓存；历史日期优先使用已有缓存；抓取失败时回退到旧缓存并给出提示。
- 可用 `--refresh` 强制刷新，或删除 `data/cache/` 后重跑。

### 快照留存

- 每个交易日最多保留 `1030`、`1100`、`1400`、`close` 四份快照。
- 默认保留最新快照日期往前 180 天；清理后会同步重建索引，不会留下失效条目。
- 单独回放/补录一个较老日期时，该快照不会因系统当前日期而被立即删除。
- 读取最新快照时会跳过索引中不存在的文件，自动回退到上一份有效快照。

### SSL 证书说明

默认会校验 HTTPS 证书。若在代理或自签名证书环境下校验失败，工具会自动降级为不校验并在报告中提示。可通过环境变量控制：

```bash
# 强制校验证书（失败则报错）
ASHARE_VP_VERIFY_SSL=1 python3 -m ashare_vp

# 直接关闭校验（仅建议在可信网络使用）
ASHARE_VP_VERIFY_SSL=0 python3 -m ashare_vp
```

## 自定义资产池

编辑 `config/assets.json`，每个标的字段如下：

```json
{
  "code": "159992",
  "name": "创新药ETF银华",
  "exchange": "SZ",
  "secid": "0.159992",
  "tencent": "sz159992",
  "sina": "sz159992"
}
```

- `code`：6 位代码，分组内唯一。
- `exchange`：`SH` / `SZ` / `BJ`。
- `secid`：东方财富代码，沪市 `1.`、深市/北交所 `0.` 前缀。
- `tencent` / `sina`：腾讯/新浪代码，通常为 `sh` / `sz` / `bj` + 6 位代码。至少配置一个。
- 分组 `kind`：`etf` 或 `index`；ETF 会启用成交额估算。

新增标的后先运行：

```bash
python3 -m ashare_vp --list
python3 -m ashare_vp --code 新代码 --refresh
```

## 定时运行

### 方式一：调度器常驻

```bash
# 工作日 10:30 / 14:00 自动生成盘中快照与 H5
python3 -m ashare_vp.scheduler

# 先确认未来任务时间
python3 -m ashare_vp.scheduler --dry-run

# 或交给 systemd / launchd / supervisor 常驻
```

### 方式二：crontab 收盘日报

```bash
# 编辑 crontab：crontab -e
0 18 * * 1-5 cd /Users/liuxin/Documents/deepseek-harness/default-workspace && ./run_daily.sh >> logs/daily.log 2>&1
```

建议 18:00 后运行，确保当日行情已更新。首次使用先手动跑一次确认网络与数据源正常。

## 联调自检

在没有网络或非交易时段，可用本地缓存做一次完整联调：

```bash
# 1. 单元 + 集成测试（71 个用例）
python3 -m unittest discover -s tests -v

# 2. 收盘全链路：报告 + 建议 + 快照 + H5
python3 -m ashare_vp --offline --quiet

# 3. 盘中回放：使用最近快照生成 11:00 页面
python3 -m ashare_vp.session --offline --force --session 1100 --quiet

# 4. 服务与接口
python3 -m ashare_vp.server --port 8765 &
curl -s http://127.0.0.1:8765/health
curl -s http://127.0.0.1:8765/api/latest | head -c 200

# 5. 调度时间
python3 -m ashare_vp.scheduler --dry-run
```

预期：报告目录生成 `vp_report.md/json/csv`，`reports/h5/` 生成最新 H5 与 `index.html`，`data/snapshots/` 生成对应时段 JSON，`/health` 返回 `status: ok` 与快照数量。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

当前共 **71 个用例**，覆盖指标计算、信号识别、评分、多源解析、缓存回退、离线报告、CLI 筛选、建议生成、快照索引与清理、H5 渲染、盘中会话、回放标记、归档快照回填、调度器、HTTP 服务路径安全、部署后版本校验，以及 10:30 → 11:00 → 14:00 → 收盘的端到端连贯性。

## 目录结构

```
.
├── ashare_vp/
│   ├── __main__.py      # python -m ashare_vp 入口
│   ├── cli.py           # 收盘日报参数解析与主流程
│   ├── config.py        # 资产池加载与筛选
│   ├── datasource.py    # 腾讯/新浪/东财抓取、缓存、容错
│   ├── quotes.py        # 实时快照、成交量外推、时段判断
│   ├── indicators.py    # 纯函数指标
│   ├── analysis.py      # 信号、评分、市场汇总
│   ├── advice.py        # 近高近低、条件化建议、连贯性
│   ├── snapshot.py      # 快照留存、索引、清理、历史读取
│   ├── h5.py            # H5 渲染与历史入口
│   ├── publish.py       # 建议 -> 快照 -> H5 统一发布
│   ├── session.py       # 10:30 / 14:00 盘中分析
│   ├── scheduler.py     # 工作日定时任务
│   ├── server.py        # 轻量 HTTP 服务
│   ├── report.py        # Markdown/JSON/CSV/控制台渲染
│   └── models.py        # 数据模型
├── config/assets.json   # 默认资产池
├── data/cache/          # 行情缓存（运行后生成）
├── data/snapshots/      # 盘中/收盘快照（运行后生成）
├── reports/             # 日报与 H5 输出（运行后生成）
├── templates/h5.html    # 单文件 H5 模板
├── scripts/             # 站点组装、归档快照回填与部署后版本校验
├── tests/               # 单元测试与端到端集成测试
├── run_daily.sh         # 每日运行脚本
└── README.md
```

## 已知限制

- 依赖公开行情接口，接口限流、字段变更或网络波动可能导致部分标的使用缓存或跳过。
- 日线优先使用接口返回的复权数据，历史价格与当时实际成交价可能存在差异；最新交易日通常一致。
- 盘中成交量外推是线性近似，开盘/尾盘放量或停牌会影响量比，仅用于结构判断。
- 不包含盘中分时、资金流明细、财务与基本面数据，也不做交易执行。
- 指数成交额在腾讯/新浪源下不可得，报告显示 `-`；如需成交额可切换东方财富源，但该接口可能不稳定。
- 评分、信号与建议是规则化统计结果，存在滞后与误判，请结合自身研究使用。
- H5 为静态单文件，页面数据在生成时固化；需要最新数据时重新运行收盘或盘中命令。
