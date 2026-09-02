# OmniNAV · 个人全资产投资分析与复盘系统

## 完整技术架构方案与实施蓝图 (Technical Specification Document)

| 项目名称     | OmniNAV（全资产净值化复盘系统）                                    | 文档版本     | V1.0 - Production                 |
| :----------- | :----------------------------------------------------------------- | :----------- | :-------------------------------- |
| **系统定位** | 跨市场全资产汇总记账、单位净值核算、周期复盘与告警系统             | **基准法币** | CNY（支持全局切换 USD）           |
| **覆盖资产** | A股、港股、美股、全球ETF、银行理财（固收/净值/现金类）、多币种现金 | **部署方式** | Docker Compose 一键私有化容器编排 |

---

## 1. 总体系统架构与分层拓扑

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        前端表现层 (Presentation Layer)                   │
│   React 19 + TailwindCSS v4.3 + Vite 6 + Apache ECharts 6.1 (暗黑金融看板)│
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ RESTful API (OpenAPI 3.1)
┌────────────────────────────────────▼────────────────────────────────────┐
│                        服务层 (Application Layer)                        │
│                 FastAPI (Python 3.14.7) + Pydantic v2.13                │
│  ┌───────────────────────┐ ┌───────────────────────┐ ┌────────────────┐ │
│  │   NAV 份额化核算引擎   │ │   银行固收计息引擎    │ │ 风险与归因引擎 │ │
│  └───────────────────────┘ └───────────────────────┘ └────────────────┘ │
└──────────────────────┬───────────────────────────────┬──────────────────┘
                       │                               │
┌──────────────────────▼──────────┐         ┌──────────▼──────────────────┐
│     数据持久层 (Persistence)     │         │     任务调度与外部交互       │
│  • PostgreSQL 18.6 (核心存储)   │         │  • APScheduler (轻量内嵌调度)│
│  • Redis 8.10 (缓存/防刷锁)     │         │  • 数据源: AkShare / yfinance│
│                                 │         │  • 推送: 飞书 Webhook/Telegram │
└─────────────────────────────────┘         └─────────────────────────────┘
```

---

## 2. 技术选型矩阵与版本清单

| 分层               | 组件 / 库名称          | 选定最新版本          | 关键技术特性与决策依据                                                          |
| :----------------- | :--------------------- | :-------------------- | :------------------------------------------------------------------------------ |
| **后端运行时**     | **Python**             | `3.14.7`              | JIT 编译增强、更低的解释器开销，提升金融时序与量化指标计算吞吐。                |
| **API 框架**       | **FastAPI**            | `^0.141.1`            | 原生兼容 Python 3.14 异步规范，自动输出 OpenAPI 3.1+ 交互文档。                 |
| **模型校验**       | **Pydantic**           | `^2.13.5`             | Rust 核心，支持原生 `Decimal` 与 `UUIDv7` 高性能解析，杜绝浮点精度丢失。        |
| **ORM / 数据库层** | **SQLAlchemy**         | `^2.0.52`             | 2.0 异步标准，搭配 `asyncpg` 驱动充分榨干底层 I/O 性能。                        |
| **时序与量化**     | **Pandas**             | `^3.0.5`              | 默认采用 PyArrow 后端，跨市场汇率换算与持仓矩阵计算内存减半。                   |
| **行情接入**       | **AkShare / yfinance** | `^1.18.94` / `^1.5.2` | **零成本方案**：`AkShare` 覆盖 A股/港股/外汇，`yfinance` 覆盖美股/全球ETF。     |
| **量化指标**       | **QuantStats**         | `^0.0.64`             | 封装夏普比率、最大回撤、波动率、对标 Alpha 等专业投资组合指标。                 |
| **主数据库**       | **PostgreSQL**         | `18.6-alpine`         | **PG18 特性**：异步 I/O (AIO) 子系统、B-Tree 索引 Skip Scan，大幅加速时序检索。 |
| **缓存引擎**       | **Redis**              | `8.10-alpine`         | 紧凑型 Hash 结构，低内存缓存盘中行情与汇率，防止外部 API 限流。                 |
| **前端运行时**     | **React**              | `^19.0.0`             | 原生 Actions 简化表单提交，React Compiler 优化重渲染。                          |
| **CSS 引擎**       | **TailwindCSS**        | `^4.3.3`              | **Tailwind v4** Rust 驱动引擎，全 CSS 驱动配置（免 `tailwind.config.js`）。     |
| **前端构建**       | **Vite**               | `^6.0.11`             | 极速冷启动，原生集成 `@tailwindcss/vite`。                                      |
| **图表可视化**     | **Apache ECharts**     | `^6.1.0`              | 渲染多轴对标净值曲线（vs 标普500/沪深300）、资产穿透饼图与收益热力图。          |

> **版本策略（已确认）**：上表版本为撰写时的最新版参考；实际开发**兼容优先于版本号**——以 pip 依赖解析出一组互相兼容的最新稳定版为准（必要时 Python 降至 3.13、pandas 降至 2.x），并在开发第一步完成全量安装验证。

---

## 3. 核心计算与量化算法设计

### 3.1 基金份额法单位净值（Unit NAV）平滑核算引擎

彻底解决外部出入金对真实收益率曲线的扭曲问题：

```python
from decimal import Decimal, ROUND_HALF_UP

def calculate_daily_nav(
    yesterday_nav: Decimal,
    yesterday_shares: Decimal,
    today_market_value_before_flow: Decimal,
    today_net_cash_flow: Decimal  # 外部入金为正，出金为负；内部转账为 0
) -> tuple[Decimal, Decimal]:
    """
    计算当日单位净值与新总份额
    """
    # 1. 初始建仓设立 (Day 0)
    if yesterday_shares == Decimal("0"):
        initial_nav = Decimal("1.0000")
        initial_shares = today_net_cash_flow / initial_nav
        return initial_nav, initial_shares

    # 2. 计算出入金发生前因市场波动产生的真实净值
    today_nav = today_market_value_before_flow / yesterday_shares

    # 3. 按当日真实净值平滑增发/赎回份额
    delta_shares = today_net_cash_flow / today_nav
    today_shares = yesterday_shares + delta_shares

    return (
        today_nav.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
        today_shares.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    )
```

### 3.2 银行非标/固收资产估值算法

针对不同类型理财产品采取差异化每日估值：

1. **固收型 / 封闭式定期理财（按日计息模型）**：
   $$\text{当日总值}(t) = \text{本金} \times \left(1 + \text{年化收益率} \times \frac{\text{当前日期} - \text{起息日期}}{365}\right)$$
2. **净值型理财**：沿用用户最近一次手动录入的单位净值。
3. **现金管理类（T+0 零钱/货币基金）**：净值恒定为 `1.0000`，每日结息直接并入现金余额。

---

## 4. 跨市场结算与定时调度设计（Pipeline）

针对跨市场时区不一致问题（A股 15:00 收盘、港股 16:00 收盘、美股次日 04:00/05:00 收盘），采用**三阶段流水线**：

```
[阶段一: 盘中微监控 (09:30 - 23:00 / 每15分钟)]
  └─► 轮询持仓标的实时行情 ──► 命中涨跌幅告警阈值(如 ±5%) ──► 立即推送 Webhook 告警

[阶段二: A股日终简报 (每日 22:00 CST 定时触发)]
  ├─ 1. 抓取 A股/港股当日最终收盘价（美股以最近可得价格估算）
  └─ 2. 计算预估组合净值，推送 A股视角简报卡片（不落正式快照）

[阶段三: 终局清算跑批 (每日 06:00 CST 定时触发)]
  ├─ 1. 美股已收盘，批量抓取 A/港/美 最终收盘价、即期汇率 (USD/CNY, HKD/CNY) 与基准指数 (沪深300/标普500，经 AkShare / yfinance 三方免费 API 拉取)
  ├─ 2. 自动计提银行固收利息，汇总全局各币种资产并按收盘汇率折算为 CNY
  ├─ 3. 执行基金份额化 NAV 计算，生成 T-1 日终局净值快照（每日仅一条权威记录）与归因指标
  └─ 4. 生成富文本全量复盘卡片，推送至 飞书 / 企业微信 / Telegram
```

---

## 5. 数据库建模与 PostgreSQL 18.6 DDL

```sql
-- 1. 标的资产维度表
CREATE TABLE dim_assets (
    asset_id VARCHAR(32) PRIMARY KEY,          -- 标识: AAPL.US, 600519.SH, 00700.HK, CMB_WEALTH_01
    name VARCHAR(64) NOT NULL,                 -- 标的名称
    asset_class VARCHAR(16) NOT NULL,          -- STOCK, ETF, WEALTH, CASH
    market VARCHAR(8) NOT NULL,                -- CN, HK, US, GLOBAL
    currency VARCHAR(4) NOT NULL DEFAULT 'CNY',-- CNY, USD, HKD
    valuation_type VARCHAR(16) NOT NULL,       -- MARKET, FIXED_YIELD, MANUAL_NAV, CASH
    expected_apr NUMERIC(6, 4) DEFAULT 0.0000, -- 固收年化收益率 (如 0.0280)
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 2. 交易流水事实表 (仅支持买入、卖出、出入金、分红)
CREATE TABLE fact_transactions (
    id BIGSERIAL PRIMARY KEY,
    asset_id VARCHAR(32) NOT NULL REFERENCES dim_assets(asset_id),
    trans_type VARCHAR(16) NOT NULL,           -- BUY, SELL, DEPOSIT, WITHDRAW, DIVIDEND
    trans_date DATE NOT NULL,
    price NUMERIC(18, 4) NOT NULL,             -- 交易价格 / 买入净值
    quantity NUMERIC(18, 4) NOT NULL,          -- 交易份额 / 股数
    fee NUMERIC(12, 2) DEFAULT 0.00,           -- 手续费
    currency VARCHAR(4) NOT NULL,              -- 结算币种
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 3. 每日标的行情与汇率历史表
CREATE TABLE fact_daily_market_data (
    trade_date DATE NOT NULL,
    symbol VARCHAR(32) NOT NULL,               -- 标的代码 或 汇率代号 (如 USD/CNY)
    close_price NUMERIC(18, 4) NOT NULL,
    PRIMARY KEY (trade_date, symbol)
);

-- 4. 组合每日净值快照表 (用于走势图、指标与复盘)
CREATE TABLE fact_portfolio_snapshots (
    snapshot_date DATE PRIMARY KEY,
    total_market_value_cny NUMERIC(18, 2) NOT NULL, -- 折合人民币总资产
    unit_nav NUMERIC(12, 4) NOT NULL,               -- 组合单位净值 (起始 1.0000)
    total_shares NUMERIC(18, 4) NOT NULL,           -- 总份额
    daily_pnl_cny NUMERIC(18, 2) NOT NULL,          -- 当日盈亏金额
    daily_return NUMERIC(8, 4) NOT NULL,            -- 当日涨跌幅
    csi300_nav NUMERIC(12, 4),                      -- 沪深300归一化净值 (对标基准)
    sp500_nav NUMERIC(12, 4),                       -- 标普500归一化净值 (对标基准)
    review_notes TEXT                               -- 当日复盘日记
);

-- 5. 监控预警规则配置表
CREATE TABLE sys_alert_rules (
    id SERIAL PRIMARY KEY,
    asset_id VARCHAR(32) REFERENCES dim_assets(asset_id),
    rule_type VARCHAR(32) NOT NULL,   -- DAILY_PCT_CHANGE, DRAWDOWN
    threshold NUMERIC(8, 4) NOT NULL, -- 阈值 (如 0.05 代表 5%)
    is_active BOOLEAN DEFAULT TRUE
);
```

---

## 6. 配置文件清单

### 6.1 后端依赖清单 (`backend/requirements.txt`)

```ini
fastapi>=0.141.1
pydantic>=2.13.5
pydantic-settings>=2.8.0
uvicorn[standard]>=0.34.0
httpx>=0.28.1
sqlalchemy>=2.0.52
asyncpg>=0.30.0
alembic>=1.19.1
redis>=5.2.1
pandas>=3.0.5
numpy>=2.2.0
akshare>=1.18.94
yfinance>=1.5.2
quantstats>=0.0.64
apscheduler>=3.10.4
python-dateutil>=2.9.0
```

### 6.2 前端配置清单 (`frontend/package.json`)

```json
{
  "name": "omninav-frontend",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "echarts": "^6.1.0",
    "echarts-for-react": "^3.0.2",
    "zustand": "^5.0.3",
    "lucide-react": "^0.475.0",
    "clsx": "^2.1.1",
    "tailwind-merge": "^3.0.1"
  },
  "devDependencies": {
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@vitejs/plugin-react": "^4.3.4",
    "vite": "^6.0.11",
    "typescript": "^5.7.3",
    "@tailwindcss/vite": "^4.3.3",
    "tailwindcss": "^4.3.3"
  }
}
```

### 6.3 TailwindCSS v4 主题配置 (`frontend/src/index.css`)

```css
@import 'tailwindcss';

@theme {
  --color-profit: #10b981; /* 涨/收益 绿 (Emerald 500) */
  --color-loss: #ef4444; /* 跌/亏损 红 (Red 500) */
  --color-brand-primary: #3b82f6; /* 主色调 (Blue 500) */
  --color-card-bg: #1e293b; /* 暗黑看板卡片底色 */
}
```

### 6.4 部署方式（不使用容器）

> **已确认（2026-09-02，设计决策 D7）：不采用 Docker 容器化部署。** 本机/私有服务器直接部署：PostgreSQL 18.6 与 Redis 8.10 由系统服务管理（macOS 用 `brew services`，Linux 用 systemd），后端 `uvicorn` 常驻，前端 `npm run build` 产物由静态服务器托管并反代 `/api`。

---

## 7. 实施落地路线图 (Sprint Plan)

- **Sprint 1 (底座搭建)**：建立 PG 18.6 表结构与初始迁移，编写 `AkShare` + `yfinance` 行情抓取与汇率转换脚本。
- **Sprint 2 (核算闭环)**：实现“单位净值平滑算法”单元测试，接入 `APScheduler` 实现 22:00 A股简报 + 次日 06:00 终局清算双时点自动跑批与飞书 Webhook 推送。
- **Sprint 3 (前端大盘)**：React 19 + Tailwind v4 搭建暗黑看板，集成 ECharts 净值曲线（vs 标普500/沪深300）与资产穿透分布图。
- **Sprint 4 (复盘与风控)**：增加复盘日记功能，自动生成月度/年度报告与回撤告警。
