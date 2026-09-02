# OmniNAV · 开发计划 (Development Plan)

> 依据：[TechnicalArchitecture.md](./TechnicalArchitecture.md) V1.0 + [PRD.md](./PRD.md) V1.0
> 约束：**暂不考虑容器编排**（技术方案 §6.4），开发期使用本机 PostgreSQL + Redis，docker-compose 推迟到 Sprint 4 收尾。
> 节奏：4 个 Sprint（约 8 周，单人全职；业余时间按 2~2.5 倍拉长）。

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

> 注：以上决策已于 2026-09-02 反向同步至原文档——PRD §2.1（双跑批）、§3.2（现金建模与转账说明）、§3.5（移除理财到期提醒）；技术方案 §2（版本策略）、§4（三阶段流水线）、§7（Sprint 2 描述）。

---

## 1. 里程碑总览与依赖

```
Sprint 0 脚手架 ──► Sprint 1 数据层+行情 ──► Sprint 2 NAV核算+调度推送 ──► Sprint 3 前端看板 ──► Sprint 4 复盘告警+部署
                     (M1→M2 可并行)              (核心闭环, 最关键)
```

| Sprint | 主题 | 周期 | 里程碑验收（Demo 标准） |
| :--- | :--- | :--- | :--- |
| 0 | 工程底座 | 第 1 周 | 前后端可本地启动联通；Alembic 空迁移跑通；5 张表建表完成 |
| 1 | 数据层 + 行情接入 | 第 2–3 周 | 一条命令抓取全部持仓标的收盘价与汇率入库；资产/流水 CRUD 可用 |
| 2 | NAV 核算 + 调度推送 | 第 4–5 周 | 22:00 简报与 06:00 终局清算双跑批跑通，飞书收到复盘卡片；NAV 单测全绿 |
| 3 | 前端暗黑看板 | 第 6 周 | 录入真实数据后看板正确渲染净值曲线（vs 双基准）与资产穿透图 |
| 4 | 告警 + 复盘 + 部署 | 第 7–8 周 | 告警规则触发可收到推送；月报含夏普/最大回撤；docker-compose 一键起 |

---

## 2. Sprint 0 · 工程底座（第 1 周）

**目标**：可运行的前后端骨架 + 数据库就绪。

| # | 任务 | 产出 | 验收 |
| :--- | :--- | :--- | :--- |
| 0.1 | 验证技术栈版本（见 D6）：创建 venv，安装 requirements.txt 全量依赖 | `backend/requirements.txt`（修正后） | `pip install` + 全量 `import` 无报错 |
| 0.2 | Monorepo 目录结构：`backend/`（app/api, app/core, app/models, app/schemas, app/services, app/jobs, tests/）、`frontend/` | 目录骨架 + README | — |
| 0.3 | 本机安装 PostgreSQL 18 + Redis 8（brew），创建库 `omninav` 与专用用户 | `.env.example`（DATABASE_URL / REDIS_URL / FEISHU_WEBHOOK_URL） | `psql` / `redis-cli ping` 连通 |
| 0.4 | FastAPI 骨架：pydantic-settings 配置加载、异步 SQLAlchemy engine/session、`/api/health`（含 DB/Redis 连通检查） | `backend/app/main.py` 等 | `uvicorn` 启动后 `/api/health` 返回 200 |
| 0.5 | Alembic 初始化 + 5 张表迁移（按技术方案 §5 DDL 原样，无增补字段） | `alembic/versions/xxx_init.py` | `alembic upgrade head` 后 psql 可见全部表 |
| 0.6 | 前端脚手架：Vite 6 + React 19 + TS + Tailwind v4（按 §6.2/§6.3 配置，含暗黑主题 tokens） | 可启动的空看板页 | `npm run dev` 显示暗色占位布局；vite proxy 到 8000 |

---

## 3. Sprint 1 · 数据层与行情接入（第 2–3 周）

**目标**：资产/流水可录入；行情与汇率可自动抓取。

### M1 · 资产与账本 CRUD

| # | 任务 | 产出 | 验收 |
| :--- | :--- | :--- | :--- |
| 1.1 | SQLAlchemy 模型 + Pydantic v2 Schema（Decimal 全程精度，禁止 float） | models / schemas | mypy/pyright 无高危类型错误 |
| 1.2 | `dim_assets` CRUD API：四类资产（STOCK/ETF/WEALTH/CASH）、四种估值模式（MARKET/FIXED_YIELD/MANUAL_NAV/CASH）、币种 | `/api/assets` | OpenAPI 文档中可完整录入含年化收益率、到期日的理财 |
| 1.3 | `fact_transactions` CRUD API：BUY/SELL/DEPOSIT/WITHDRAW/DIVIDEND（D4：无转账类型，BUY 支持以外部资金直接买入） | `/api/transactions` | 录入每类流水均通过校验；非法 trans_type 被拒 |
| 1.4 | 交易录入辅助校验：交易日期不晚于今天、金额=price×quantity±fee 一致性检查 | 服务层校验 | 构造不一致数据返回 422 |

### M2 · 行情与汇率服务（与 M1 并行）

| # | 任务 | 产出 | 验收 |
| :--- | :--- | :--- | :--- |
| 1.5 | 统一行情适配器接口 `MarketDataProvider`（symbol → close_price），下挂 AkShare / yfinance 两个实现 | `app/services/market/` | 同一接口覆盖 A股、港股、美股、ETF |
| 1.6 | AkShare 实现：A股/港股日收盘价、沪深300（D5）；USD/CNY、HKD/CNY 即期汇率 | provider + 写入 `fact_daily_market_data` | 抓取结果与主流行情软件抽查一致 |
| 1.7 | yfinance 实现：美股、全球ETF、标普500（^GSPC） | 同上 | 同上 |
| 1.8 | Redis 缓存层：盘中行情/汇率缓存 + 简单防刷锁（防外部 API 限流） | cache 装饰器 | 重复请求命中缓存（可观测） |
| 1.9 | CLI 补数脚本：`python -m app.jobs.backfill --from 2026-01-01`，支持历史行情批量回填 | backfill 命令 | 空库可回填半年历史数据 |

---

## 4. Sprint 2 · NAV 核算引擎与调度推送（第 4–5 周）★ 核心闭环

**目标**：系统最核心的价值闭环——净值正确 + 全自动跑批 + 推送到手机。

### M3 · 核算引擎

| # | 任务 | 产出 | 验收 |
| :--- | :--- | :--- | :--- |
| 2.1 | 持仓聚合：从 `fact_transactions` 重放出每标的持仓数量与成本（SELL 不允许超卖） | `portfolio_service` | 任意流水序列重放结果与手算一致 |
| 2.2 | 多估值器：MARKET（收盘价×汇率折 CNY）、FIXED_YIELD（按日计息公式 §3.2）、MANUAL_NAV（最近手录净值）、CASH（净值恒 1） | `valuators/` | 四类资产各写单测一例 |
| 2.3 | **单位净值平滑算法**（§3.1，Decimal + ROUND_HALF_UP）：初始建仓、纯波动、入金、出金四种场景 | `nav_service.calculate_daily_nav` | **pytest 单测覆盖全部 4 场景**：出入金当日 NAV 仅反映市场波动 |
| 2.4 | T-1 快照生成：总资产折 CNY、unit_nav、total_shares、daily_pnl、daily_return、双基准归一化净值 → `fact_portfolio_snapshots` | 快照服务 | 用样例数据回放 30 天，NAV 曲线无出入金跳变 |
| 2.5 | 幂等与补算：同一天重复跑批覆盖更新而非重复插入；支持指定日期区间补算 | upsert 逻辑 | 重跑同一天结果不变 |

### M4 · 调度与推送

| # | 任务 | 产出 | 验收 |
| :--- | :--- | :--- | :--- |
| 2.6 | 通知器统一接口 + 飞书 Webhook 推送：富文本卡片（净值、当日盈亏、基准对比、领涨领跌、资产分布） | `app/services/notify/` | 真实 Webhook 收到卡片（样式按 PRD §3.4） |
| 2.7 | **22:00「A股日终简报」Job**（D1）：A/港股用当日收盘终值、美股以最近可得价格估算，计算预估净值并推送简报卡片（不落快照） | `app/jobs/evening_brief.py` | 手动触发等价于定时触发 |
| 2.8 | **06:00「终局清算」Job**（D1）：抓美股收盘价 + 即期汇率 → 固收计息 → NAV 权威快照（upsert）→ 推送全量复盘卡片 | `app/jobs/eod_settlement.py` | 手动触发等价于定时触发 |
| 2.9 | 盘中微监控 Job：交易日 09:30–23:00 每 15 分钟轮询持仓实时行情（Redis 缓存兜底） | `app/jobs/intraday_monitor.py` | 模拟行情命中阈值时产生告警事件 |
| 2.10 | Telegram Bot 通道（备选） | notify 第二实现 | 配置任一通道即可用 |

---

## 5. Sprint 3 · 前端暗黑看板（第 6 周）

**目标**：日常使用的核心界面——看数 + 录数。

| # | 任务 | 产出 | 验收 |
| :--- | :--- | :--- | :--- |
| 3.1 | 布局与路由：暗黑金融看板框架（侧边导航：总览 / 持仓 / 流水 / 复盘 / 设置）、zustand 状态 + fetch 封装 | 页面骨架 | 全路由可达，loading/empty 态完整 |
| 3.2 | 总览页指标卡：最新 unit_nav、当日涨跌、累计收益、总资产（CNY） | 指标卡组件 | 与快照 API 数据一致；涨绿跌红（主题 tokens） |
| 3.3 | **净值曲线**（ECharts 多轴）：组合 NAV vs 沪深300 vs 标普500 归一化对比，区间切换（1M/3M/6M/1Y/ALL） | 曲线组件 | 三条曲线起点归一；缩放/tooltip 可用 |
| 3.4 | 资产穿透：按市场/大类/币种的分布饼图 + 持仓明细表（市值、成本、浮动盈亏、占比） | 饼图 + 表格 | 穿透层级数据自洽（合计=总资产） |
| 3.5 | 交易录入表单：资产选择器 + 五类交易 + React 19 Actions 提交校验 | 录入页 | 录入后持仓与看板即时刷新 |
| 3.6 | 净值型理财手录入口：快速更新 MANUAL_NAV 类资产最新净值 | 编辑组件 | 更新后次日估值生效 |

---

## 6. Sprint 4 · 告警、复盘与部署（第 7–8 周）

| # | 任务 | 产出 | 验收 |
| :--- | :--- | :--- | :--- |
| 4.1 | `sys_alert_rules` CRUD + 前端规则管理页 | 告警设置 | 可增删改查规则并启停 |
| 4.2 | 告警引擎：单日涨跌幅（默认 ±5%）、组合回撤（5%/10% 两档）接入推送通道 | 告警判定服务 | 构造行情触发规则，飞书收到告警 |
| 4.3 | 复盘日记：`review_notes` 的 CRUD + 看板内编辑，随每日卡片带出 | 日记功能 | 昨日笔记出现在当日推送卡片 |
| 4.4 | 量化指标服务：QuantStats 计算夏普、最大回撤、波动率、对标 Alpha | 指标 API | 指标与 QuantStats 独立运行结果一致 |
| 4.5 | 月度/年度报告：胜率盈亏比、资产比例偏离预警（权益 >70% 警戒）、最佳/最差标的；每月最后交易日 20:00 推送 | 报告 Job | 生成一次真实月报卡片 |
| 4.6 | 基准币种全局切换 CNY ⇄ USD（汇率取当日收盘） | 前端设置 + API 参数 | 切换后全看板金额/币种正确 |
| 4.7 | docker-compose 编排（按技术方案 §6.4）+ 后端/前端 Dockerfile + `.env` 模板 | 一键部署 | `docker compose up` 全栈可用 |
| 4.8 | 收尾：pg_dump 备份脚本、结构化日志、README 部署文档 | 运维件 | 备份可恢复验证一次 |

---

## 7. 测试与质量策略

- **单测重点**（pytest）：NAV 平滑算法 4 场景（2.3）、四类估值器（2.2）、持仓重放（2.1）、固收按日计息边界（闰年/起息日当天）。
- **集成测试**：跑批 Job 端到端（临时库 + mock 行情源），验证幂等（2.5）。
- **回归基准**：构造一份「已知正确答案」的样例账本（含跨市场 + 出入金 + 理财），每次改引擎后全量回放比对快照。
- **前端**：以 E2E 关键路径为主（录入→看板刷新），不追求组件级全覆盖。

## 8. 风险与应对

| 风险 | 影响 | 应对 |
| :--- | :--- | :--- |
| AkShare 接口变动/限流 | 行情断供 | 适配器层隔离（1.5）；yfinance 兜底美股；Redis 缓存 + 失败重试；CLI 可手工补数（1.9） |
| 依赖版本过新（pandas 3.x 破坏性变更、quantstats/akshare 适配滞后、Python 3.14 可能缺 wheel） | 装不起来或运行时崩溃 | Sprint 0.1 全量安装验证；兼容优先于版本号，必要时 Python 降 3.13、pandas 降 2.x，锁定一组互相兼容的稳定版 |
| NAV 算法边界（除权除息、分红再投） | 净值失真 | V1 先按 PRD 范围（现金分红入现金资产）；除权细节列入 backlog，不在本计划内 |
| 美股收盘晚（04:00/05:00）导致 06:00 抓取失败 | 跑批缺数 | 跑批内重试 + 当日盘中监控补发更新 |
