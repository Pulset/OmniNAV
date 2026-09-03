# OmniNAV · 多用户账号管理与数据隔离技术方案

| 文档版本     | V1.0 - 待实施（2026-09-03） | 关联文档 | [TechnicalArchitecture.md](TechnicalArchitecture.md) · [DevelopmentPlan.md](DevelopmentPlan.md) |
| :----------- | :-------------------------- | :------- | :---------------------------------------------------------------------------------------------- |

## 1. 背景与目标

系统当前为**单实例单租户**：5 张核心表全部全局无 `user_id`、API 无任何鉴权、4 个定时任务与通知 webhook（飞书/Telegram）均为全局单份配置。后续将开放给多人使用，需要补齐账号体系并实现用户间数据完全隔离（个人资产数据敏感，隔离是硬需求，不是可选项）。

**目标：**

1. 账号认证：用户名密码登录、会话管理、登出/吊销、管理员建号（不开放公开注册）。
2. 数据隔离：资产、流水、快照、告警规则按用户隔离；跨用户访问一律 404。
3. 任务与通知多用户化：结算/简报/监控/月报按用户循环执行，推送渠道个人化。
4. 存量数据无损迁移到首个管理员账号名下。

**非目标（本期不做）：**

- 公开注册、邮箱验证、找回密码（管理员可重置密码即可）。
- 团队/共享组合（一个组合多人可见）。
- SSO / OIDC（预留切换点，见 §10）。

**关键红利：** `fact_daily_market_data`（行情与汇率）是公共数据，**完全不改**；行情抓取与 Redis 行情缓存天然全用户共享，抓一次全员复用。

## 2. 方案选型

| 备选                          | 结论 | 理由                                                                     |
| :---------------------------- | :--- | :----------------------------------------------------------------------- |
| **共库共表 + `user_id` 列**   | ✅   | 几人规模下改动最小；行情缓存共享；一套部署一套运维。                     |
| 反代层 Basic Auth / oauth2-proxy | ❌   | 只能挡人，做不到行级数据隔离与账号管理，不满足核心需求。                 |
| 每人一套实例 / 独立 schema    | ❌   | 零代码改动但运维成本随人数线性增长，行情重复抓取浪费三方 API 限额。     |
| Keycloak / Authentik 等外部 IdP | ❌   | 为几个用户多维护一个重服务；自建轻量账号足够。                           |
| JWT access/refresh 双令牌     | ❌   | 需要即时吊销（改密/停用踢下线），Redis 服务端会话更直接，省掉轮换逻辑。 |

**总体结论：共享数据库共享表 + `user_id` 隔离 + 自建轻量账号体系**（用户名密码 + argon2id + Redis 会话 + httpOnly Cookie），不改变现有部署形态（非容器、单机常驻，见架构文档 §6.4）。

## 3. 账号与认证设计

### 3.1 新增表 DDL

```sql
-- 6. 用户表
CREATE TABLE sys_users (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(32) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,        -- argon2id（argon2-cffi）
    role VARCHAR(8) NOT NULL DEFAULT 'member',  -- admin / member
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 7. 用户个人设置（通知渠道从全局 .env 迁移到每人一份）
CREATE TABLE user_settings (
    user_id BIGINT PRIMARY KEY REFERENCES sys_users(id) ON DELETE CASCADE,
    feishu_webhook_url VARCHAR(255),
    telegram_bot_token VARCHAR(255),
    telegram_chat_id VARCHAR(64)
);
```

> 新增依赖仅 `argon2-cffi`。`user_settings` 独立于 `sys_users`，避免每次鉴权都加载 webhook token。

### 3.2 会话机制

- 登录成功签发 **opaque token**：`secrets.token_urlsafe(32)`，存 Redis `session:{token}` → `user_id`，TTL 7 天，每次请求滑动续期。
- 通过 **httpOnly + SameSite=Lax Cookie**（`omninav_session`）下发。前端已由 FastAPI 同源托管（`app/main.py` 静态挂载），CSRF 攻击面小；生产前置 HTTPS 后加 `Secure` 属性。
- 吊销：改密、被停用、登出即删 Redis key，全部会话即时失效。

### 3.3 API 设计

| 接口                              | 方法 | 说明                                                         |
| :-------------------------------- | :--- | :----------------------------------------------------------- |
| `/api/auth/login`                 | POST | `{username, password}` → 签发 Cookie；失败计数限速           |
| `/api/auth/logout`                | POST | 删除当前会话                                                 |
| `/api/auth/me`                    | GET  | 当前用户信息（id / username / role）                         |
| `/api/auth/me/password`           | PUT  | `{old_password, new_password}`，成功后吊销所有会话          |
| `/api/admin/users`                | GET/POST | 列表 / 建号 `{username, password, role}`（仅 admin）   |
| `/api/admin/users/{id}`           | PATCH | 停用/启用、重置密码（仅 admin；禁止停用自己）                |

登录限速：Redis key `login_fail:{username}:{ip}`，15 分钟窗口 5 次失败即拒绝（TTL 自过期）。

### 3.4 鉴权依赖（后端改造入口）

所有 `/api` 业务路由统一挂依赖，唯一切换点将来对接 OIDC 也只改这里：

```python
async def get_current_user(
    omninav_session: str | None = Cookie(default=None),
    session: AsyncSession = Depends(get_session),
) -> SysUser:
    # Redis 校验 token → user_id → 加载 SysUser，校验 is_active，滑动续期
    # 失败一律 401
    ...

router = APIRouter(prefix="/assets", tags=["assets"],
                   dependencies=[Depends(get_current_user)])
```

例外：`/api/auth/login`、`/api/health` 不鉴权；`/api/admin/*` 额外校验 `role == "admin"`。

### 3.5 首管理员 seed

应用启动时（或 alembic 迁移内）检查 `sys_users` 为空，则用环境变量 `INIT_ADMIN_USERNAME`（默认 `admin`）与 `INIT_ADMIN_PASSWORD` 创建 admin，并把 `.env` 中已有的飞书/Telegram 配置回填进该用户的 `user_settings`。之后以表内配置为准。

## 4. 数据隔离设计

### 4.1 关键设计点：资产主键复合化

`dim_assets.asset_id` 是用户手起的自然键（如 `600519.SH`、`CASH_CNY`），多个用户跟踪同一标的必然撞主键。因此资产表主键改为 `(user_id, asset_id)`，下游外键随之复合化。**行情表按 symbol 查询天然与用户无关，不受影响。**

### 4.2 表改动清单与 DDL

| 表                          | 改动                                                                                          |
| :-------------------------- | :-------------------------------------------------------------------------------------------- |
| `dim_assets`                | +`user_id`；主键 `(asset_id)` → `(user_id, asset_id)`                                         |
| `fact_transactions`         | +`user_id`；外键改 `(user_id, asset_id)` 复合引用；加索引 `(user_id, trans_date)`             |
| `fact_portfolio_snapshots`  | +`user_id`；主键 `(snapshot_date)` → `(user_id, snapshot_date)`                               |
| `sys_alert_rules`           | +`user_id`；外键改 `(user_id, asset_id)` 复合引用                                             |
| `fact_daily_market_data`    | **不改**（公共行情，全用户共享）                                                              |

```sql
-- dim_assets
ALTER TABLE dim_assets ADD COLUMN user_id BIGINT REFERENCES sys_users(id);
-- （回填 user_id 后，见 §6）
ALTER TABLE dim_assets DROP CONSTRAINT dim_assets_pkey;
ALTER TABLE dim_assets ADD PRIMARY KEY (user_id, asset_id);

-- fact_transactions
ALTER TABLE fact_transactions ADD COLUMN user_id BIGINT REFERENCES sys_users(id);
ALTER TABLE fact_transactions DROP CONSTRAINT fact_transactions_asset_id_fkey;
ALTER TABLE fact_transactions
    ADD CONSTRAINT fact_transactions_user_asset_fkey
    FOREIGN KEY (user_id, asset_id) REFERENCES dim_assets(user_id, asset_id);
CREATE INDEX ix_fact_transactions_user_date ON fact_transactions(user_id, trans_date);

-- fact_portfolio_snapshots
ALTER TABLE fact_portfolio_snapshots ADD COLUMN user_id BIGINT REFERENCES sys_users(id);
ALTER TABLE fact_portfolio_snapshots DROP CONSTRAINT fact_portfolio_snapshots_pkey;
ALTER TABLE fact_portfolio_snapshots ADD PRIMARY KEY (user_id, snapshot_date);

-- sys_alert_rules
ALTER TABLE sys_alert_rules ADD COLUMN user_id BIGINT REFERENCES sys_users(id);
ALTER TABLE sys_alert_rules DROP CONSTRAINT sys_alert_rules_asset_id_fkey;
ALTER TABLE sys_alert_rules
    ADD CONSTRAINT sys_alert_rules_user_asset_fkey
    FOREIGN KEY (user_id, asset_id) REFERENCES dim_assets(user_id, asset_id);
```

### 4.3 路由层改造模式

- 所有查询/写入追加 `where user_id == current_user.id`（services 层函数签名统一加 `user_id` 首参或 `user` 对象）。
- 按主键取资产的调用从 `session.get(DimAsset, asset_id)` 改为 `session.get(DimAsset, (user_id, asset_id))`——**`get()` 不吃过滤条件，这类调用必须逐个排查**（现有 `assets.py` 的 create/update/delete 均命中）。
- 跨用户资源访问返回 404（不泄露存在性）。
- 不使用 SQLAlchemy 全局过滤器等隐式手段，保持项目现有直白风格；防漏靠 §4.4 的隔离测试兜底。

### 4.4 隔离测试（防漏兜底，随 M2 交付）

`tests/test_isolation.py`：双用户各建资产/流水/告警规则，断言——

- A 列表看不到 B 的任何数据；A 直接访问 B 的 `asset_id` / 流水 id / 快照返回 404 或不含 B 记录；
- A 删除 B 的资产返回 404 而非 409；
- 未经登录访问全部业务接口返回 401。

## 5. 定时任务与通知多用户化

### 5.1 任务循环模式

行情抓取（AkShare / yfinance / Frankfurter）保持**全局一次**（取全体活跃用户持仓 symbol 并集），结算与推送按用户循环，单用户失败不中断他人：

```python
async def eod_settlement_job():
    symbols = await collect_all_user_symbols()      # 全局一次抓行情
    quotes = await fetch_market_data(symbols)
    for user in await get_active_users():
        try:
            snapshot = await settle_for_user(user, quotes)
            await notify_user(user, build_report(user, snapshot))
        except Exception:
            logger.exception("user=%s 终局清算失败，跳过", user.id)
```

四个任务（`eod_settlement` / `evening_brief` / `intraday_monitor` / `monthly_report`）统一套此模式；`backfill` 脚本加 `--user` 参数（默认 admin）。

### 5.2 通知个人化

- `notify/base.py` 的 `get_notifiers()`（读全局 Settings）重构为 `get_user_notifiers(user)`：读该用户 `user_settings`，未配置走现有 `NullNotifier`。
- Redis 告警去重 key 增加 user 维度前缀（如 `alert_dedup:{user_id}:{rule_id}:{date}`），避免 A 触发的告警把 B 的去重窗口占掉。

## 6. 存量数据迁移（alembic `0003_multi_user`）

单次迁移按序完成，全程可回滚：

1. 建 `sys_users` / `user_settings`；
2. seed 首个 admin（§3.5），并把 `.env` 的通知配置回填其 `user_settings`；
3. 四张业务表 `ADD COLUMN user_id`（先 nullable）→ `UPDATE ... SET user_id = admin_id` → `SET NOT NULL`；
4. 删旧主键/外键，按 §4.2 建复合主键、复合外键与索引。

迁移后现有全部数据无损归属 admin，现有页面行为不变。

## 7. 前端改造

前端为 state 切页（无路由库），登录态直接挂在 `App` 层，**不引入 react-router**：

- `client.ts`：`fetch` 加 `credentials: 'include'`；统一拦截 401 → 渲染登录页。
- `App.tsx`：启动时调 `GET /api/auth/me`；未登录渲染 `<Login />`，成功后渲染现有 `Layout`。新增 `PageKey: 'login'`（或独立分支）。
- `Login.tsx`：新页，用户名密码 + 错误提示。
- `Settings.tsx`：加「修改密码」「我的通知渠道」（飞书/Telegram 表单，写 `user_settings`）；保留现有任务手动触发。
- `Users.tsx`（仅 admin 可见入口）：建号、停用/启用、重置密码。
- `main.py` CORS 收紧为仅开发域名（`localhost:5173`），同源生产流量不依赖 CORS。

## 8. 安全清单

| 项           | 措施                                                                   |
| :----------- | :--------------------------------------------------------------------- |
| 密码存储     | argon2id（`argon2-cffi`），禁止明文/可逆加密入库                       |
| 暴力破解     | 登录失败 Redis 计数限速（15 分钟 5 次，按 username+IP）                |
| 会话         | 128-bit+ 随机 opaque token；httpOnly + SameSite=Lax；TTL 滑动续期；改密/停用即全量吊销 |
| 传输         | 生产前置 HTTPS（推荐 Caddy 反代，自动证书），Cookie 加 `Secure`        |
| 暴露面       | 不开放注册；admin 接口独立鉴权；跨用户资源 404 不泄露存在性            |
| 日志         | 不打印密码哈希、webhook token、session token                           |

## 9. 实施分期与验证

| 里程碑 | 内容                                                                                       | 验证标准                                                              |
| :----- | :----------------------------------------------------------------------------------------- | :-------------------------------------------------------------------- |
| M1 认证骨架 | `sys_users`/迁移、登录/登出/`me`/改密、`get_current_user` 挂全部路由（数据暂不隔离）、前端登录页与 401 拦截 | 未登录访问全 401；登录后现有页面全部功能正常；限速生效                 |
| M2 数据隔离 | §4 表结构迁移与存量归属、路由/服务层 user_id 过滤、`session.get` 复合键排查、隔离集成测试 | `test_isolation.py` 全绿；现有 pytest（NAV/估值/重放等）全绿；admin 数据无损 |
| M3 多用户周边 | 四任务按用户循环、通知个人化、admin 用户管理页、backfill `--user`、CORS 收紧             | 双用户各录数据手动触发 06:00 清算，各生成各的快照、推送各到各的 webhook |

规模预估：M1 ≈ 1 天，M2 ≈ 1 天，M3 ≈ 1–2 天。

## 10. 未来扩展预留

- **SSO/OIDC**：认证已收敛在 `get_current_user` 单一依赖，未来接 Authentik/飞书扫码时仅替换该依赖实现，业务路由不动。
- **配额/审计**：`fact_transactions` 已带 `user_id`，后续可按用户统计录入量与操作审计日志。
