# OmniNAV · 开发计划 (Development Plan)

> 依据：[TechnicalArchitecture.md](./TechnicalArchitecture.md) V1.0 + [PRD.md](./PRD.md) V1.0
> 约束：**不使用 Docker**（设计决策 D7）；数据库**复用本机已有 PostgreSQL 17**（设计决策 D8）；Redis 由用户自行管理；后端 uvicorn、前端 Vite。
> 节奏：4 个 Sprint（约 8 周，单人全职；业余时间按 2~2.5 倍拉长）。

---

## 实施状态速览（2026-09-02 第二次开发收官标注）

**总体：Sprint 0–4 编码全部完成（含任务 4.5 月度/年度报告 Job）；核心算法 28 个单测全绿，前端构建通过。端到端联调因数据库凭据未就绪而暂停。**

| 分类 | 内容 |
| :--- | :--- |
| ✅ 已完成 | 后端全部模块（脚手架/迁移/CRUD/行情适配/NAV 引擎/估值器/调度 Job/飞书+Telegram 推送/告警/指标/**月度年度报告**/回补 CLI）；前端五页看板（总览/持仓/流水/复盘/设置）；`pytest` 28 个单测通过；`npm run build` 通过；备份脚本 `scripts/backup_db.sh`；`.gitignore` |
| ⬜ 未完成 | 集成级端到端验证（建库 → 迁移 → uvicorn 冒烟 → 录数据 → 手动触发清算闭环）；备份恢复演练；真实 Webhook 推送验收 |
| 🚧 阻塞项 | PostgreSQL 需要超级用户口令才能建库（本机 PG17 为密码认证、无免密配置），需用户执行下方命令 |

**待用户执行（解锁端到端验证）：**

```bash
# 1. 在本机 PostgreSQL 17 上建专用角色与库（口令与 backend/.env.example 默认值一致）
sudo -u postgres /Library/PostgreSQL/17/bin/psql \
  -c "CREATE ROLE omninav_admin LOGIN PASSWORD 'omninav';" \
  -c "CREATE DATABASE omninav OWNER omninav_admin;"

# 2. Redis 启动（用户自行管理）
brew services start redis

# 3. 后端配置并起服务
cd backend && cp .env.example .env   # 按需填 FEISHU_WEBHOOK_URL
source .venv/bin/activate && alembic upgrade head && uvicorn app.main:app --reload

# 4. 冒烟：浏览器打开 http://localhost:8000/docs 建资产/录流水，
#    「设置」页手动触发「06:00 终局清算」，或命令行回补历史：
#    python -m app.jobs.backfill --from 2026-01-01
```

**实现备注（与原文档的合理偏差）：**
- 汇率源实现为 **Frankfurter**（欧洲央行参考汇率，免费无 Key、接口稳定），替代 AkShare 外汇接口；AkShare/yfinance 覆盖范围不变。
- 前端 ECharts 采用自写轻封装（init/setOption/resize/销毁）替代 `echarts-for-react`，规避其与 React 19 的兼容风险。
- 交易表单用受控组件实现（未用 React 19 Actions），行为等价。
- 月度报告「最后交易日」以周一至五近似（无节假日历），与盘中监控窗口同策略；节假日触发时报告基于最近可得快照与行情生成。月内最后一个交易日的权威快照由次日 06:00 清算生成，20:00 推送的期末估值为最新可得行情的预估。
- 持仓成本采用与券商 App 一致的**摊薄口径**（买入金额+手续费、卖出按净回款冲减、分红不加成本、清仓结转归零），用于持仓页成本/浮动盈亏展示；NAV 净值核算与该口径无关。

---

## 0. 设计决策记录（2026-09-02 已全部确认）

| # | 问题 | 已确认方案 |
| :--- | :--- | :--- |
| D1 | **跑批时间**（PRD §2.1 与技术方案 §4 原不一致） | **双跑批**：① 每日 **22:00「A股日终简报」**——A/港股用当日收盘终值，美股以最近可得价格估算，计算预估净值并推送简报卡片（**不落快照**）；② 次日 **06:00「终局清算」**——抓美股收盘价 + 即期汇率终值，固收计息，生成 T-1 **权威快照**并推送全量复盘卡片。`fact_portfolio_snapshots` 每日仅一条权威记录，无需改表 |
| D2 | **理财到期提醒** | **不需要**。不新增 `maturity_date` 字段，DDL 维持技术方案 §5 原样；PRD §3.5 该条不实施 |
| D3 | **现金的建模方式** | **现金建为 CASH 类资产**（如 `CASH_CNY` / `CASH_USD` / `CASH_HKD`），净值恒 1；SELL/DIVIDEND 所得可入账到对应币种现金资产 |
| D4 | **银证转账** | **不涉及**。只录入已购成的资产，BUY 支持以外部资金直接买入，不跟踪账户间内部流转；不新增转账类交易类型 |
| D5 | **基准指数数据源** | **可以，且零额外成本**：沪深300 用 AkShare 指数接口（`index_zh_a_hist` / `stock_zh_index_daily`），标普500 用 yfinance `^GSPC`，均免费、无需 API Key；与普通标的统一写入 `fact_daily_market_data`，跑批时按首日归一化。官方渠道（中证指数公司 / S&P 官网）无免费好用 API，三方源精度足够个人复盘 |
| D6 | **依赖版本激进** | 确为风险点（详见 §8）：pandas 3.x 为破坏性大版本，quantstats/akshare 适配可能滞后；Python 3.14 太新可能缺 wheel。策略：**兼容优先于版本号**——Sprint 0.1 用 pip resolver 选一组互相兼容的最新稳定版（必要时 Python 降 3.13、pandas 降 2.x），架构价值不在小版本号 |
| D7 | **容器化部署** | **不采用 Docker**。本机部署：brew services 管理 PostgreSQL 18 + Redis 8，后端 uvicorn 常驻，前端构建产物由静态服务器托管。技术方案 §6.4 的 docker-compose 内容作废 |
| D8 | **数据库实例** | **复用本机已有 PostgreSQL 17**（EDB 安装，localhost:5432），不再 brew 安装 PG18；建库/建角色命令见上方「实施状态速览」；Redis 安装与启动由用户自行管理 |

> 注：D1–D5 已反向同步至原文档——PRD §2.1（双跑批）、§3.2（现金建模与转账说明）、§3.5（移除理财到期提醒）；技术方案 §2（版本策略）、§4（三阶段流水线）、§7（Sprint 2 描述）。D7 已同步（技术方案 §6.4 改为本机部署说明、README 移除 Docker 章节）。

---

## 1. 里程碑总览与依赖

```
Sprint 0 脚手架 ──► Sprint 1 数据层+行情 ──► Sprint 2 NAV核算+调度推送 ──► Sprint 3 前端看板 ──► Sprint 4 复盘告警+收尾
                     (M1→M2 可并行)              (核心闭环, 最关键)
```

| Sprint | 主题 | 周期 | 里程碑验收（Demo 标准） | 状态 |
| :--- | :--- | :--- | :--- | :--- |
| 0 | 工程底座 | 第 1 周 | 前后端可本地启动联通；Alembic 空迁移跑通；5 张表建表完成 | ✅ 代码完成，迁移执行待 PG 建库 |
| 1 | 数据层 + 行情接入 | 第 2–3 周 | 一条命令抓取全部持仓标的收盘价与汇率入库；资产/流水 CRUD 可用 | ✅ 完成（真实行情抽查待环境） |
| 2 | NAV 核算 + 调度推送 | 第 4–5 周 | 22:00 简报与 06:00 终局清算双跑批跑通，飞书收到复盘卡片；NAV 单测全绿 | 🚧 单测全绿；跑批/推送验收待环境 |
| 3 | 前端暗黑看板 | 第 6 周 | 录入真实数据后看板正确渲染净值曲线（vs 双基准）与资产穿透图 | ✅ 完成并构建通过（真实数据联调待环境） |
| 4 | 告警 + 复盘 + 收尾 | 第 7–8 周 | 告警规则触发可收到推送；月报含夏普/最大回撤；备份脚本可用 | 🚧 编码全部完成（含 4.5 月度报告）；推送/端到端验收待环境 |

---

## 2. Sprint 0 · 工程底座（第 1 周）

**目标**：可运行的前后端骨架 + 数据库就绪。

| # | 任务 | 产出 | 验收 | 状态 |
| :--- | :--- | :--- | :--- | :--- |
| 0.1 | 验证技术栈版本（见 D6）：创建 venv，安装 requirements.txt 全量依赖 | `backend/requirements.txt`（修正后） | `pip install` + 全量 `import` 无报错 | ✅ Python 3.14.3 上全部激进版本可用（fastapi 0.141.1 / pandas 3.0.5 / akshare 1.18.94 / quantstats 0.0.81 / SQLAlchemy 2.0.52），pip resolver 自动兼容，无需降级；已固化 `requirements.lock.txt` |
| 0.2 | Monorepo 目录结构：`backend/`（app/api, app/core, app/models, app/schemas, app/services, app/jobs, tests/）、`frontend/` | 目录骨架 + README | — | ✅ |
| 0.3 | 准备数据库与缓存 | `.env.example` | `psql` / `redis-cli ping` 连通 | 🚧 PG 改用本机 PostgreSQL 17（D8），建库命令待用户执行；Redis 8.10.1 已装（清华镜像），服务启动由用户处理 |
| 0.4 | FastAPI 骨架：pydantic-settings 配置加载、异步 SQLAlchemy engine/session、`/api/health`（含 DB/Redis 连通检查） | `backend/app/main.py` 等 | `uvicorn` 启动后 `/api/health` 返回 200 | ✅ 代码完成，app 导入与调度装配验证通过；HTTP 冒烟待 PG |
| 0.5 | Alembic 初始化 + 5 张表迁移（按技术方案 §5 DDL 原样，无增补字段） | `alembic/versions/0001_init_tables.py` | `alembic upgrade head` 后 psql 可见全部表 | 🚧 迁移已写好，执行待 PG 建库 |
| 0.6 | 前端脚手架：Vite 6 + React 19 + TS + Tailwind v4（按 §6.2/§6.3 配置，含暗黑主题 tokens） | 可启动的空看板页 | `npm run dev` 显示暗色占位布局；vite proxy 到 8000 | ✅ |

---

## 3. Sprint 1 · 数据层与行情接入（第 2–3 周）

**目标**：资产/流水可录入；行情与汇率可自动抓取。

### M1 · 资产与账本 CRUD

| # | 任务 | 产出 | 验收 | 状态 |
| :--- | :--- | :--- | :--- | :--- |
| 1.1 | SQLAlchemy 模型 + Pydantic v2 Schema（Decimal 全程精度，禁止 float） | models / schemas | mypy/pyright 无高危类型错误 | ✅ |
| 1.2 | `dim_assets` CRUD API：四类资产（STOCK/ETF/WEALTH/CASH）、四种估值模式（MARKET/FIXED_YIELD/MANUAL_NAV/CASH）、币种 | `/api/assets` | OpenAPI 文档中可完整录入含年化收益率的理财 | ✅ |
| 1.3 | `fact_transactions` CRUD API：BUY/SELL/DEPOSIT/WITHDRAW/DIVIDEND（D4：无转账类型，BUY 支持以外部资金直接买入） | `/api/transactions` | 录入每类流水均通过校验；非法 trans_type 被拒 | ✅（交易类型/资产类别匹配、币种一致性、未来日期校验均返回 422） |
| 1.4 | 交易录入辅助校验：交易日期不晚于今天、金额一致性检查 | 服务层校验 | 构造不一致数据返回 422 | ✅ 并入 1.3 |

### M2 · 行情与汇率服务（与 M1 并行）

| # | 任务 | 产出 | 验收 | 状态 |
| :--- | :--- | :--- | :--- | :--- |
| 1.5 | 统一行情适配器接口 `MarketDataProvider`（symbol → close_price），下挂 AkShare / yfinance 两个实现 | `app/services/market/` | 同一接口覆盖 A股、港股、美股、ETF | ✅ |
| 1.6 | AkShare 实现：A股/港股日收盘价、沪深300（D5） | provider + 写入 `fact_daily_market_data` | 抓取结果与主流行情软件抽查一致 | ✅ 防御式列解析防接口变更；行情抽查待环境 |
| 1.7 | yfinance 实现：美股、全球ETF、标普500（^GSPC） | 同上 | 同上 | ✅ 同上 |
| 1.8 | Redis 缓存层：盘中行情/汇率缓存 + 防刷/告警去重锁 | `app/services/market/cache.py` | 重复请求命中缓存（可观测） | ✅ Redis 不可用时优雅降级（跳过缓存/放行锁） |
| 1.9 | CLI 补数脚本：`python -m app.jobs.backfill --from 2026-01-01` | backfill 命令 | 空库可回填半年历史数据 | ✅ 抓历史行情+汇率后逐日重放净值（幂等） |

> 实现备注：汇率源用 **Frankfurter**（ECB，免费无 Key）替代 AkShare 外汇接口，见「实施状态速览」。

---

## 4. Sprint 2 · NAV 核算引擎与调度推送（第 4–5 周）★ 核心闭环

**目标**：系统最核心的价值闭环——净值正确 + 全自动跑批 + 推送到手机。

### M3 · 核算引擎

| # | 任务 | 产出 | 验收 | 状态 |
| :--- | :--- | :--- | :--- | :--- |
| 2.1 | 持仓聚合：从 `fact_transactions` 重放出每标的持仓数量与成本（SELL 不允许超卖） | `app/services/portfolio.py` | 任意流水序列重放结果与手算一致 | ✅ FIFO 批次重放 + OverSellError，单测覆盖 |
| 2.2 | 多估值器：MARKET（收盘价×汇率折 CNY）、FIXED_YIELD（按日计息）、MANUAL_NAV（最近手录净值）、CASH（净值恒 1） | `app/services/valuation.py` | 四类资产各写单测一例 | ✅ 缺行情回退加权成本并告警；单测覆盖 |
| 2.3 | **单位净值平滑算法**（§3.1，Decimal + ROUND_HALF_UP）：初始建仓、纯波动、入金、出金四种场景 | `app/services/nav.py` | **pytest 单测覆盖全部 4 场景**：出入金当日 NAV 仅反映市场波动 | ✅ 含清仓边界、盈亏/涨跌幅计算，单测通过 |
| 2.4 | T-1 快照生成：总资产折 CNY、unit_nav、total_shares、daily_pnl、daily_return、双基准归一化净值 | `app/services/settlement.py` | 用样例数据回放 30 天，NAV 曲线无出入金跳变 | ✅ 已知答案回放（`tests/test_replay.py`）5 日场景全过 |
| 2.5 | 幂等与补算：同一天重复跑批覆盖更新而非重复插入 | upsert 逻辑 | 重跑同一天结果不变 | ✅ upsert 保留人工 review_notes |

### M4 · 调度与推送

| # | 任务 | 产出 | 验收 | 状态 |
| :--- | :--- | :--- | :--- | :--- |
| 2.6 | 通知器统一接口 + 飞书 Webhook 推送：富文本卡片（净值、当日盈亏、基准对比、领涨领跌、资产分布） | `app/services/notify/` | 真实 Webhook 收到卡片（样式按 PRD §3.4） | ✅ 代码完成；真实 Webhook 验收待环境 |
| 2.7 | **22:00「A股日终简报」Job**（D1） | `app/jobs/evening_brief.py` | 手动触发等价于定时触发 | ✅ persist=False 不落快照；等价性验收待环境 |
| 2.8 | **06:00「终局清算」Job**（D1） | `app/jobs/eod_settlement.py` | 手动触发等价于定时触发 | ✅ 含告警评估与卡片推送；等价性验收待环境 |
| 2.9 | 盘中微监控 Job：交易日 09:30–23:00 每 15 分钟轮询持仓实时行情 | `app/jobs/intraday_monitor.py` | 命中阈值产生告警事件 | ✅ A股走 AkShare 五档快照、港/美股走 yfinance 实时价；Redis 锁去重 |
| 2.10 | Telegram Bot 通道（备选） | `app/services/notify/telegram.py` | 配置任一通道即可用 | ✅ |

---

## 5. Sprint 3 · 前端暗黑看板（第 6 周）

**目标**：日常使用的核心界面——看数 + 录数。

| # | 任务 | 产出 | 验收 | 状态 |
| :--- | :--- | :--- | :--- | :--- |
| 3.1 | 布局与路由：暗黑金融看板框架（侧边导航：总览 / 持仓 / 流水 / 复盘 / 设置）、zustand 状态 + fetch 封装 | `frontend/src/` | 全路由可达，loading/empty 态完整 | ✅ |
| 3.2 | 总览页指标卡：最新 unit_nav、当日涨跌、累计收益、总资产 | 指标卡组件 | 与快照 API 数据一致；涨红跌绿（A股习惯） | ✅ |
| 3.3 | **净值曲线**（ECharts）：组合 NAV vs 沪深300 vs 标普500 归一化对比，区间切换（1M/3M/6M/1Y/ALL） | `NavChart.tsx` | 三条曲线起点归一；缩放/tooltip 可用 | ✅ |
| 3.4 | 资产穿透：按市场/大类分布饼图 + 持仓明细表（市值、成本、浮动盈亏、占比、当日涨跌） | 饼图 + 表格 | 穿透层级数据自洽（合计=总资产） | ✅ |
| 3.5 | 交易录入表单：资产选择器 + 五类交易 + 提交校验 | 录入页 | 录入后持仓与看板即时刷新 | ✅ 受控组件实现（见实施备注） |
| 3.6 | 净值型理财手录入口：快速更新 MANUAL_NAV 类资产最新单位净值 | 设置页组件 | 更新后次日估值生效 | ✅ |

> `npm run build`（tsc -b + vite build）通过；echarts 独立分包。

---

## 6. Sprint 4 · 告警、复盘与收尾（第 7–8 周）

| # | 任务 | 产出 | 验收 | 状态 |
| :--- | :--- | :--- | :--- | :--- |
| 4.1 | `sys_alert_rules` CRUD + 前端规则管理页 | `/api/alert-rules` + 设置页 | 可增删改查规则并启停 | ✅ |
| 4.2 | 告警引擎：单日涨跌幅（默认 ±5%）、组合回撤（5%/10% 两档）接入推送通道 | `app/services/alerts.py` | 构造行情触发规则，飞书收到告警 | 🚧 代码完成（清算后评估 + 盘中即时告警）；触发验收待环境 |
| 4.3 | 复盘日记：`review_notes` 的 CRUD + 看板内编辑，随每日卡片带出 | 复盘页 + PATCH API | 昨日笔记出现在当日推送卡片 | ✅（卡片带出逻辑已实现，推送验收待环境） |
| 4.4 | 量化指标服务：QuantStats 计算夏普、最大回撤、波动率、对标 Alpha/Beta | `/api/metrics/summary` + 复盘页指标卡 | 指标与 QuantStats 独立运行结果一致 | ✅ 含胜率/CAGR；异常时逐项降级为 `—` |
| 4.5 | 月度/年度报告：胜率盈亏比、资产比例偏离预警（权益 >70% 警戒）、最佳/最差标的；每月最后交易日 20:00 推送 | 报告 Job | 生成一次真实月报卡片 | ✅ `app/jobs/monthly_report.py`：工作日 20:00 调度 + Job 内自检最后交易日；12 月额外推送年度报告；行情缺失时持仓明细降级；单测 7 例（`tests/test_report.py`）。真实推送验收待环境 |
| 4.6 | 基准币种全局切换 CNY ⇄ USD（汇率取当日收盘） | 侧边栏切换 + `?base=` 参数 | 切换后全看板金额/币种正确 | ✅（持仓/成本/浮动盈亏随基准换算；快照历史仍以 CNY 存储） |
| 4.7 | 收尾：pg_dump 备份脚本、结构化日志、README 本机部署文档（D7：无 Docker） | `scripts/backup_db.sh` 等 | 备份可恢复验证一次 | 🚧 脚本与文档完成；恢复演练待数据库就绪 |

---

## 7. 测试与质量策略

- **单测重点**（pytest）：NAV 平滑算法 4 场景（2.3）、四类估值器（2.2）、持仓重放（2.1）、固收按日计息边界。→ ✅ **已完成：`backend/tests/` 共 28 个用例全部通过**（含月报统计/最后交易日/权益偏离预警 7 例 `test_report.py`），另含「已知答案样例账本回放」回归基准（`test_replay.py`，5 日场景：初始建仓 / 内部出资抵消 / 纯波动 / 外部入金不扭曲 / 连续上涨）。
- **集成测试**：跑批 Job 端到端（临时库 + mock 行情源），验证幂等（2.5）。→ ⬜ 待数据库就绪后补做（可先用「手动触发 Job + 样例数据」替代）。
- **回归基准**：已知正确答案样例账本全量回放比对快照。→ ✅ 已落地为单测。
- **前端**：E2E 关键路径（录入→看板刷新）。→ ⬜ 未做。

## 8. 风险与应对

| 风险 | 影响 | 应对 |
| :--- | :--- | :--- |
| AkShare 接口变动/限流 | 行情断供 | 适配器层隔离（1.5）；yfinance 兜底美股；Redis 缓存 + 失败重试；CLI 可手工补数（1.9） |
| 依赖版本过新（pandas 3.x 破坏性变更、quantstats/akshare 适配滞后、Python 3.14 可能缺 wheel） | 装不起来或运行时崩溃 | ✅ 已验证：本机 Python 3.14.3 全量安装+导入通过；`requirements.lock.txt` 固化已验证组合 |
| NAV 算法边界（除权除息、分红再投） | 净值失真 | V1 先按 PRD 范围（现金分红入现金资产）；除权细节列入 backlog，不在本计划内 |
| 美股收盘晚（04:00/05:00）导致 06:00 抓取失败 | 跑批缺数 | 跑批内重试 + 当日盘中监控补发更新 |
| 本机网络访问三方 API 受限（AkShare/东财、Yahoo、Frankfurter） | 行情/汇率抓取失败 | 各 provider 均已隔离并记日志；缺价时估值回退加权成本；可用 backfill 重试补数 |
