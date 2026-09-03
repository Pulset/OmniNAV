# OmniNAV

Personal Multi-Asset Portfolio & Review System —— 个人全资产投资分析与复盘系统

跨市场（A股 / 港股 / 美股 / 全球ETF / 银行理财 / 多币种现金）汇总记账、基金份额法单位净值核算、周期复盘与告警推送。

- 产品需求：[docs/PRD.md](docs/PRD.md)
- 技术架构：[docs/TechnicalArchitecture.md](docs/TechnicalArchitecture.md)
- 开发计划与设计决策：[docs/DevelopmentPlan.md](docs/DevelopmentPlan.md)
- 多用户账号管理与数据隔离方案：[docs/MultiUser.md](docs/MultiUser.md)

## 架构

```
React 19 + TailwindCSS v4 + Vite 6 + ECharts 6 (暗黑看板)
        │ RESTful API
FastAPI (Python 3.14) + Pydantic v2 + SQLAlchemy 2.0 (async)
        │
PostgreSQL 18 (核心存储) · Redis 8 (行情缓存/告警去重)
        │
APScheduler: 22:00 A股日终简报 / 06:00 终局清算 / 盘中 15min 监控
AkShare + yfinance + Frankfurter (三方免费行情/汇率) → 飞书 / Telegram 推送
```

## 快速开始（本机开发）

### 1. 准备依赖服务

复用本机已有的 PostgreSQL 17（localhost:5432），Redis 自行管理：

```bash
# 建专用角色与库（口令与 backend/.env.example 默认一致）
sudo -u postgres /Library/PostgreSQL/17/bin/psql \
  -c "CREATE ROLE omninav_admin LOGIN PASSWORD 'omninav';" \
  -c "CREATE DATABASE omninav OWNER omninav_admin;"

# Redis（若尚未运行）
brew services start redis
```

### 2. 后端

```bash
cd backend
cp .env.example .env            # 填入飞书/Telegram Webhook（可选）
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt   # 或 pip install -r requirements.lock.txt 锁定已验证版本
alembic upgrade head            # 建 5 张核心表
uvicorn app.main:app --reload   # http://localhost:8000/docs
```

### 3. 前端

```bash
cd frontend
npm install
npm run dev                     # http://localhost:5173（/api 代理到 8000）
```

### 4. 录入第一笔数据

1. 「流水」页需要先有资产：通过 `POST /api/assets` 或 OpenAPI 文档创建（如 `CASH_CNY` 现金、`600519.SH` 股票、`CMB_WEALTH_01` 固收理财）。
2. 录入 `DEPOSIT`（外部入金，触发初始份额设立）→ 录入 `BUY`。
3. 「设置」页手动触发 `06:00 终局清算` Job 立即生成快照，看板即可看到净值曲线。

历史数据回补：

```bash
cd backend && source .venv/bin/activate
python -m app.jobs.backfill --from 2026-01-01    # 抓历史行情并逐日重放净值
```

## 部署方式

不使用容器（已确认）。生产部署即上述本机流程：brew services/systemd 管理 PostgreSQL 与 Redis，后端 `uvicorn` 常驻，前端 `npm run build` 后由静态服务器托管（开发期用 `npm run dev`）。

**部署约束**：

- 后端必须**单 worker** 运行（`uvicorn app.main:app`，不要加 `--workers N`，也不要多副本）：API 进程内嵌 APScheduler，多进程会重复调度（重复推送、快照并发写冲突）。业务时区固定 `Asia/Shanghai`，与服务器本地时区解耦。
- 若部署在反向代理后，需正确配置 `X-Forwarded-For`，否则登录限速按代理 IP 计数，一个来源的爆破会锁定全部用户。

## 核心概念

- **单位净值（Unit NAV）**：基金份额法平滑核算，出入金按当日真实净值增发/赎回份额，净值曲线只反映真实投资能力。
- **交易语义**：`BUY/SELL` 只改目标资产持仓；外部资金直接买入视作外部现金流（自动增发份额）；若资金来自已跟踪的现金资产，同时录一笔该现金的 `WITHDRAW`，两笔流水自动抵消。`DIVIDEND` 落到现金资产，属内部收益不改份额。
- **估值模式**：`MARKET`（收盘价×汇率）/ `FIXED_YIELD`（按日计息）/ `MANUAL_NAV`（手录净值）/ `CASH`（净值恒 1）。
- **双跑批**：22:00 推送 A股日终简报（预估值，不落快照）；次日 06:00 美股收盘后生成 T-1 权威快照并推送全量复盘卡片。

## 测试

```bash
cd backend && source .venv/bin/activate
pytest            # NAV 平滑 4 场景 + 四类估值器 + 持仓重放 + 已知答案回归
```
