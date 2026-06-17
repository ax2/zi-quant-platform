# ZiQuant Platform

面向 zicode 体系的独立 A 股量化交易平台。

功能范围：

- 500 只内置 A 股股票池，支持用户私有池、公共池、自定义维护和按策略重建。
- 股票基础信息同步：支持从公开市场列表刷新真实 A 股代码、名称、市场和行业，并重置公共 500 股票池。
- 数据源抽象：默认 QVeris 数据接口，不做每次 discovery；A 股长历史行情可由东方财富公开 K 线补足，也可替换为同花顺或 Tushare。
- 真实数据链路：支持 A 股日线行情、财报利润表同步、覆盖率检查；QVeris 短样本与东方财富长历史都会标记真实来源，fallback 数据会显式标记为 `simulated_fallback`。
- 六层量化结构：数据、因子、策略、雷达、智能与市场、模拟执行。
- PostgreSQL 持久化：用户、股票、股票池、策略、模拟盘、数据源配置、任务、审计。
- 多用户模型：用户私有资源和公共资源并存。
- 回测与策略优化：日频多头回测、A 股 100 股手、手续费、止损/止盈、LLM 参数建议、候选策略验证。
- 回测执行约束：支持滑点、成交量参与率、涨跌停不可买卖、100 股手、佣金、过户费和卖出印花税，交易明细会记录原始收盘价和约束参数。
- 模拟盘：支持手工纸面订单，也支持按当前启用策略生成调仓建议并执行为纸面订单；估值和成交价优先使用已落库真实行情。
- 策略荐股与个股分析：工作台第一屏展示实时策略推荐、昨日推荐复盘和输入股票分析，参考 `ZhuLinsen/daily_stock_analysis` 的 AI 决策报告、策略问股和多渠道推送产品形态。
- 飞书信号提醒：支持通过本机 `lark-cli` 把策略信号发送到飞书；默认提供 dry-run 预览，真实发送必须同时设置 `dry_run=false` 和 `LARK_SIGNAL_LIVE_ENABLED=true`。
- 策略有效性改进：质量动量因子会融合行情趋势与真实财报质量，优先使用 QVeris 财报的净利率、同季营收同比和 ROE。
- 策略准入：LLM 候选策略必须通过回测和基准策略对比，验证通过后才能提升为启用策略。
- 策略准入要求正式回测不是短样本，且候选策略相对基准需要有实质改善；默认使用 900 天真实行情和 50 只公共池样本做验证。
- 管理功能：数据源、任务、用户、运维配置、审计日志。
- 现代化前端：二级侧边菜单、工作台、股票池、策略、雷达、模拟盘、管理页。

启动：

```bash
cd /opt/zi-quant-platform
uv sync --extra dev
uv run uvicorn app.main:app --host 127.0.0.1 --port 8092
```

本地 PostgreSQL 默认连接：

```text
postgresql+asyncpg:///postgres?host=/var/run/postgresql
```

如果你的本地 PostgreSQL 需要密码，设置：

```bash
export DATABASE_URL='postgresql+asyncpg://user:password@127.0.0.1:5432/postgres'
```

Local Services：

项目已加入本地服务面板配置，服务 id 为 `zi-quant-platform`。

数据库迁移：

```bash
# 首次对已有本地库打基线版本
uv run alembic stamp head

# 新环境或后续升级
uv run alembic upgrade head

# 部署前检查当前库是否到最新迁移
uv run python scripts/check_migrations.py
```

本地开发可以保留 `AUTO_CREATE_SCHEMA=true` 以便自动补表；生产部署建议设置 `ZI_DEPLOYMENT_MODE=production` 和 `AUTO_CREATE_SCHEMA=false`，并在启动前显式运行 Alembic 迁移。`/ready` 会检查这组运行配置；如果生产模式仍开启自动建表，会降级提示 `set_auto_create_schema_false`。

数据库备份：

```bash
set -a; . ./.env; set +a
uv run python scripts/db_backup.py --output-dir /var/backups/zi-quant
# 或安装为 console script 后：
uv run zi-quant-db-backup --output-dir /var/backups/zi-quant
```

备份脚本使用 `pg_dump --format=custom` 生成 `.dump` 文件，并写入同名 `.manifest.json`，记录备份时间、文件大小、sha256、脱敏数据库连接和执行状态。数据库密码不会出现在命令参数或 manifest 中，脚本只通过 `PGPASSWORD` 传给 `pg_dump` 子进程。恢复到新库时可使用：

```bash
pg_restore --clean --if-exists --no-owner --dbname postgresql://zi_quant@127.0.0.1:5432/zi_quant /var/backups/zi-quant/zi_quant_YYYYMMDDTHHMMSSZ.dump
```

生产环境建议用 cron 或 systemd timer 至少每日备份一次，并把 `/var/backups/zi-quant` 纳入主机级备份或对象存储归档。示例 cron：

```cron
15 2 * * * cd /opt/zi-quant-platform && set -a && . ./.env && set +a && uv run zi-quant-db-backup --output-dir /var/backups/zi-quant >/var/log/zi-quant-db-backup.log 2>&1
```

该备份流程只读取 PostgreSQL 数据，不同步外部数据、不改模拟盘、不提交真实交易订单，也不构成投资建议。

常用 API：

```text
GET  /health
GET  /ready
GET  /api/dashboard
GET  /api/recommendations/realtime
GET  /api/recommendations/yesterday-review
GET  /api/stocks/analyze?symbol=600519.SH
POST /api/signals/feishu
GET  /api/admin/ops-status
GET  /api/admin/production-audit
GET  /api/admin/production-acceptance
GET  /api/admin/audit-logs
GET  /api/admin/jobs
POST /api/admin/jobs/reset-stale
POST /api/admin/jobs/reset-failed
POST /api/admin/jobs/run-due
POST /api/data/sync
GET  /api/data/quality
GET  /api/data/provenance
POST /api/data/coverage
POST /api/stocks/sync
POST /api/data/bootstrap-real
POST /api/financials/sync
POST /api/financials/coverage
GET  /api/financials
GET  /api/data-sources
GET  /api/data-sources/capabilities
PUT  /api/data-sources
PATCH /api/data-sources/{source_id}/enabled
POST /api/backtests/run
GET  /api/strategies/health
GET  /api/strategies/optimization-health
PUT  /api/strategies/{strategy_id}
POST /api/strategies/optimize
POST /api/strategies/alpha-search
POST /api/strategies/remediate-health
POST /api/strategies/research-next
GET  /api/strategies/repair-timeline
GET  /api/strategies/promotion-candidates
POST /api/optimizations/{optimization_id}/apply
POST /api/strategies/{strategy_id}/validate
POST /api/strategies/{strategy_id}/promote
GET  /api/strategy-experiments
GET  /api/portfolios
POST /api/portfolios/order
GET  /api/risk/events
POST /api/portfolios/{portfolio_id}/snapshot
POST /api/portfolios/{portfolio_id}/rebalance
POST /api/admin/jobs/{job_id}/run
GET  /api/admin/job-runs
GET  /api/admin/users
PUT  /api/admin/users
PATCH /api/admin/users/{user_id}/active
```

生产访问控制：

`ZI_API_TOKEN` 必须显式设置；为空时所有会改变状态的接口都会返回 401。生产或共享环境建议设置一个随机长 token，本地开发也建议写入 `.env`：

```bash
export ZI_API_TOKEN='<random-long-token>'
```

设置后，所有会改变状态、触发数据同步、消耗数据额度、运行回测/优化、模拟下单或访问管理信息的接口都必须带请求头：

```text
X-Zi-Api-Token: <random-long-token>
```

前端右上角的 `API Token` 按钮会把 token 保存到当前浏览器 localStorage，并自动附加到受保护请求。`/health`、`/ready` 和普通只读浏览接口保持可读，便于健康检查和本地调试。

平台级写操作还会检查用户角色：刷新全局股票池、重建公共股票池、同步行情/财报、维护数据源、准备预置数据接口和刷新因子需要 `admin` 或 `operator`；创建公共股票池或公共模拟盘需要 `admin`。普通 `researcher` 仍可维护自己的私有股票池、私有策略、私有模拟盘，并运行自己的回测、优化和模拟盘动作。

工作台主流程：

- `GET /api/recommendations/realtime?limit=10`：基于当前公共股票池、真实行情、财报质量因子和启用策略参数输出实时股票推荐。推荐会区分 `BUY_WATCH`、`OBSERVE`、`HOLD_WATCH` 和 `RISK_WATCH`，并给出策略标签、证据和纸面仓位上限。
- `GET /api/recommendations/yesterday-review?limit=10`：用最近两个真实交易日复盘昨日推荐，展示次日收益、命中状态、命中率和平均收益。
- `GET /api/stocks/analyze?symbol=600519.SH`：输入股票代码后输出行情、财报、技术因子、策略视图和风险发现。
- `POST /api/signals/feishu`：生成飞书策略信号。请求体示例：`{"dry_run": true, "limit": 8}`。默认 dry-run 只返回消息预览并写审计日志；真实发送会调用 `lark-cli im +messages-send --as bot`，目标会话默认使用 `LARK_SIGNAL_CHAT_ID` 或内置本地测试群配置。为避免误发，live 发送必须同时满足：请求体 `dry_run=false`、环境变量 `LARK_SIGNAL_LIVE_ENABLED=true`、`LARK_SIGNAL_CHAT_ID` 已配置、`lark-cli` 可执行；任一条件不满足会写入 `feishu_signal_blocked` 审计日志并返回阻断原因。
- 平台内置 `飞书策略信号` 计划任务，`job_type=feishu_signal`，默认调度为交易日 15:45，payload 默认使用 `LARK_SIGNAL_DEFAULT_DRY_RUN`。它会生成与工作台一致的实时推荐和昨日复盘信号，写入任务运行记录和审计日志；如需真实发送到飞书，需要管理员将该任务 payload 确认为 `{"dry_run": false, "limit": 8}`，并确认 `LARK_SIGNAL_LIVE_ENABLED=true` 且 `lark-cli` bot 身份已具备群聊发送权限。

这些接口只生成研究、复盘、提醒和模拟盘观察信号，不连接券商、不提交真实交易订单，也不构成投资建议。

`/ready` 会返回系统就绪报告；只有迁移版本、股票池、启用数据源、启用策略等 critical 检查失败时返回 HTTP 503。公共股票池真实行情/财报覆盖不足、长历史覆盖不足、fallback 比例偏高，外部集成配置不完整，启用策略未通过且没有可人工晋升的验证候选，策略荐股/昨日复盘/个股分析/飞书信号任务不可用，或模拟盘未绑定有效策略/权益快照过期时，会标记为 `degraded`，但保留 HTTP 200，便于区分“不可启动”和“可运行但数据/策略/模拟观察置信度不足”。`integration_config` 只返回 QVeris/DeepSeek/API Token 是否已配置、base URL host、模型名和 prepared tool 数量，不返回任何密钥值。

`/api/admin/ops-status` 是管理员运维摘要接口，需要 API Token 和管理员身份。它会聚合 readiness、策略健康度、模拟盘健康度、数据质量、外部集成配置、active 策略数量、最近任务运行、最近审计日志、当前到期计划任务、最近 24 小时可能漏跑的计划任务和行动项；当 active 策略数量不是 1、策略健康度退化、模拟盘观察闭环退化、数据质量退化、外部集成配置不完整、计划任务失败或存在超过 2 小时的 running 任务时会返回 `degraded`，用于上线后巡检和告警接入。历史手动任务失败和可能漏跑的计划任务会单独展示为低优先级行动项，提醒确认 runner 是否每分钟执行，不影响自动任务健康判定。`POST /api/admin/jobs/reset-stale?hours=2` 可把超时 running 的任务运行标记为 timeout，并释放父任务回到 idle；`POST /api/admin/jobs/reset-failed?scheduled_only=true` 可把 failed 的计划任务重置为 idle，便于运维后续重跑；`POST /api/admin/jobs/run-due?limit=5` 会按后端 cron 表达式运行当前到期任务，并写入 `zi_quant_data_job_runs` 与审计日志。

`GET /api/admin/audit-logs` 是管理员审计日志查询接口，需要 API Token 和管理员身份，支持 `limit`、`action` 和 `target` 参数。返回内容包含操作者、动作、目标、创建时间和脱敏后的 payload，适合排查数据源配置、用户管理、策略修复、模拟盘纸面订单和任务调度等敏感操作链路。

`/api/admin/production-audit` 是上线前生产就绪审计接口，需要 API Token 和管理员身份。它会把 `/ready` 和运维状态按生产要求归类为数据库与迁移、上线运行配置、A 股 500 股票池、真实行情与长历史、真实财报与质量因子、数据源抽象与可替换性、回测与基准评估、策略有效性证据、策略荐股/个股分析/飞书信号、大模型策略优化闭环、模拟盘观察闭环、多用户与权限控制和 fallback 数据占比。每个审计项都会返回关联 readiness checks、是否必需、状态、证据和下一步动作，并额外返回 `coverage` 摘要，列出 readiness 覆盖数量、失败检查、缺失必需项、按类别统计和运维行动项严重级别。该接口只证明研究、回测和模拟盘能力，不代表投资建议，也不会提交真实交易订单。

`/api/admin/production-acceptance` 是交付验收报告接口，需要 API Token 和管理员身份。它复用生产就绪审计结果，额外输出 `decision`、逐项 `checklist`、关键证据摘要和 `residual_risks`，用于确认平台是否达到“研究 + 回测 + 大模型优化 + 模拟盘观察”的纸面生产观察条件。返回 `accepted_for_paper_observation` 只代表模拟盘观察链路可用，不代表真实交易授权或投资建议。

部署后可运行生产 smoke 检查，一次性验证迁移、`/ready`、运维状态、交付验收、实时股票推荐、昨日推荐复盘、输入股票分析、数据来源报告、模拟盘风险事件和数据库备份 dry-run：

```bash
set -a; . ./.env; set +a
uv run python scripts/production_smoke.py --base-url http://127.0.0.1:8092
# 或安装为 console script 后：
uv run zi-quant-production-smoke --base-url http://127.0.0.1:8092
```

上线前应额外运行严格生产配置检查，它会要求 `/api/admin/production-acceptance?strict_production=true` 通过；如果当前仍是 `ZI_DEPLOYMENT_MODE=development` 或 `AUTO_CREATE_SCHEMA=true`，会返回 `not_accepted`，用于阻止把本地开发配置误判为生产可上线：

```bash
uv run python scripts/production_smoke.py --base-url http://127.0.0.1:8092 --strict-production
```

默认 smoke 会检查本机 `pg_dump` 是否可用，并对备份脚本执行 dry-run，确认能生成 custom dump 的计划和脱敏 manifest；它不会真正导出数据库。远程只测 API、当前机器不负责数据库备份时，可以加 `--skip-backup-check`。该命令只读取平台状态、推荐、复盘和个股分析结果并输出 JSON 报告，不会同步外部数据、不会改模拟盘、不会发送飞书消息、不会提交真实交易订单，也不构成投资建议。

`GET /api/data/provenance` 是只读数据来源报告接口，会按 source 汇总行情和财报行数、覆盖股票数、最早/最新日期，并返回数据源 `last_status`、最近同步审计和 QVeris 调用遥测。响应会脱敏密钥字段，只用于真实数据链路排障、fallback 占比确认和上线审计，不触发外部同步。

任务执行入口会对 `zi_quant_data_jobs` 行加锁并检查状态；如果任务已经是 `running`，手工执行和到期 runner 都会返回 `job_already_running`，不会重复创建运行记录。到期 runner 会执行当前分钟命中的计划任务，也会补跑最近 24 小时内检测到的漏跑任务。超过 2 小时仍处于 running 的任务应先通过 `reset-stale` 标记为 timeout，再由运维决定是否重跑。

数据质量：

`/api/data/quality` 返回当前真实行情、财报和 fallback 数据的生产质量摘要。平台默认把真实行情 7 天内视为新鲜，财报 220 天内视为新鲜；同时展示公共 500 股票池的真实行情覆盖、>=250 日长历史覆盖、财报覆盖和 fallback 行情比例。前端“任务与运维”页会把这些指标放在就绪度之前，便于运维先判断数据是否可靠。

生产数据覆盖门槛支持通过环境变量调整，并会同时影响 `/api/data/quality`、`/ready` 和 `/api/admin/production-audit`。默认门槛按当前本地生产观察链路设定：真实行情覆盖 18% 且至少 90 只公共股票池成员，>=250 日长历史覆盖 12% 且至少 60 只，财报覆盖 12% 且至少 60 只，fallback 行情比例不超过 5%。生产上线前可以继续逐步提高：

```env
MIN_PUBLIC_POOL_REAL_BAR_COVERAGE=0.60
MIN_PUBLIC_POOL_LONG_HISTORY_COVERAGE=0.60
MIN_PUBLIC_POOL_FINANCIAL_COVERAGE=0.50
MIN_PUBLIC_POOL_REAL_BAR_SYMBOLS=300
MIN_PUBLIC_POOL_LONG_HISTORY_SYMBOLS=300
MIN_PUBLIC_POOL_FINANCIAL_SYMBOLS=250
MAX_FALLBACK_BAR_RATIO=0.00
```

这些门槛只用于研究、回测和模拟盘质量控制，不会触发真实交易订单。

真实数据引导：

先刷新真实股票基础信息和公共 500 股票池：

```bash
curl -X POST http://127.0.0.1:8092/api/stocks/sync \
  -H 'Content-Type: application/json' \
  -H 'X-Zi-Api-Token: <random-long-token>' \
  -d '{"limit":500,"reset_public_pool":true}'
```

```bash
curl -X POST http://127.0.0.1:8092/api/data/bootstrap-real \
  -H 'Content-Type: application/json' \
  -H 'X-Zi-Api-Token: <random-long-token>' \
  -d '{"days":180,"limit":10}'
```

该接口会对核心股票执行严格真实行情同步、严格真实财报同步和因子刷新；失败时不会静默写入 fallback。这个动作会消耗数据源额度，适合作为新环境初始化或运维补数入口。

未指定 `symbols` 时，真实数据引导会优先从公共 500 股票池中选择尚未被 QVeris 行情或财报覆盖的股票，按 `limit` 批次逐步扩大真实覆盖。

行情和财报同步会把 QVeris 预置工具调用遥测写入数据源 `last_status`、任务结果和审计日志中的 `qveris_calls` 字段，包括工具 ID、是否使用缓存 search id、尝试次数、成功次数、空响应次数、错误次数、最近错误、可解析的 cost 和 remaining credits。该遥测不包含 API Key，只用于真实数据链路排障和额度观察。

正式回测建议先同步 900 天真实行情：

```bash
curl -X POST http://127.0.0.1:8092/api/data/sync \
  -H 'Content-Type: application/json' \
  -H 'X-Zi-Api-Token: <random-long-token>' \
  -d '{"days":900,"allow_fallback":false}'
```

当 QVeris 日线返回短样本时，平台会用东方财富真实长历史日线补足；如果真实行情已存在，同一区间内的 `simulated_fallback` 会被清理，避免不同价格口径混入回测。

数据源管理：

`/api/data-sources` 支持维护 QVeris、东方财富、Tushare 和同花顺 iFinD 的启停、优先级和配置。接口响应会对 `api_key`、`token`、`password`、`secret` 等字段脱敏；保存配置时如果误传这些字段，平台会写入 `***managed-by-secret-ref***` 占位，并在 `stripped_secret_keys` 中记录被剥离的字段名。生产环境应把真实密钥放在环境变量或外部密钥系统，用 `secret_ref` 引用，例如：

```bash
curl -X PUT http://127.0.0.1:8092/api/data-sources \
  -H 'Content-Type: application/json' \
  -H 'X-Zi-Api-Token: <random-long-token>' \
  -d '{
    "name":"Tushare",
    "adapter":"tushare",
    "enabled":true,
    "priority":20,
    "secret_ref":"env:TUSHARE_TOKEN",
    "config":{"apis":["stock_basic","daily","fina_indicator"]}
  }'
```

`GET /api/data-sources/capabilities` 会返回数据源能力矩阵，并已接入 `/ready`、`/api/dashboard` 和 `/api/admin/ops-status`。矩阵会区分“默认运行链路”和“替换型接口”：

- `qveris`：默认真实数据接口，要求启用、环境变量 API key 已配置、预置工具不少于 2 个，运行时不做 discovery。
- `eastmoney`：默认公开长历史/股票池补足接口，要求启用，不需要密钥。
- `tushare`：替换型接口，要求启用并配置 `secret_ref`。
- `ths`：同花顺 iFinD 替换型接口，要求启用并配置 `secret_ref`。

能力矩阵会展示每个适配器支持的股票基础信息、实时/历史行情、财报、公告/新闻能力，以及当前从该 source 落库的行情、财报和股票基础行数。响应只返回 `has_secret_ref`、prepared tool 数量、host/状态等安全元数据，不返回任何密钥。

当前启用策略：

`金叉质量轮动 - 长历史网格优化候选` 已基于 DeepSeek 风险建议和本地长历史参数网格验证提升为 active。最近一次 594 个交易日正式验证显示候选相对原基准提高总收益和 Sharpe，同时降低最大回撤；仍然只用于模拟盘观察，不构成实盘下单建议。

策略实验管理：

候选策略执行 `/api/strategies/{strategy_id}/validate` 时，会同步写入 `zi_quant_strategy_experiments`，记录候选策略、来源策略、优化记录、候选/基准回测、指标、差异、分段稳定性、是否通过和决策理由。前端“策略优化”页会展示最近实验，便于追踪大模型建议、回测验证和策略提升之间的因果链。

策略准入除了看全段收益、Sharpe、最大回撤和源策略差异，还会检查同源等权基准下的 `alpha_return`。有市场基准时，候选策略 Alpha 低于 -5% 会被拒绝；相对源策略 Alpha 退化超过 2 个百分点也会被拒绝。系统还会对回测净值曲线做四段稳定性检查：至少 3 段正收益，且最差分段回撤不超过 20%。此外，平台会把净值曲线后 30% 作为样本外区间，要求样本外收益不低于 -5%、最大回撤不超过 25%、Sharpe 不低于 -0.5，并且样本外 Alpha 相对同源等权基准不低于 -5%。Alpha、稳定性或样本外失败的候选策略会保留为研究草稿，不能直接提升为启用策略。

策略参数维护：

前端“策略中心”支持编辑策略名称、公共/私有可见性、风险参数和撮合约束，并通过 `PUT /api/strategies/{strategy_id}` 持久化到 PostgreSQL。保存时只覆盖 `rule.risk` 和 `rule.params`，保留原有买入信号、验证历史和大模型优化来源。私有策略仅 owner 可维护；公共策略和平台策略需要管理员身份。

回测撮合约束：

默认回测不是理想化“按收盘价无限成交”。策略参数中的 `params` 可配置：

- `slippage_bps`：买入上滑、卖出下滑的基点数，默认 8 bps。
- `min_momentum`：入选候选的最小动量阈值，默认 0；提高后会过滤弱趋势候选。
- `min_quality`：入选候选的最小质量因子阈值，默认 0；提高后会结合财报质量过滤低质量趋势候选。
- `volume_participation`：单笔最多参与当日成交量比例，默认 5%。
- `limit_up_pct` / `limit_down_pct`：涨跌停阈值，默认 9.9%；涨停日不买入，跌停日不卖出。
- `max_sector_pct`：单行业最大组合暴露，默认 35%；超过上限的新买入会跳过并记录原因。
- `entry_mode`：支持 `trend_following`、`relative_strength_rotation`、`equal_weight_rotation`、`equal_weight_buy_hold` 和 `pool_equal_weight_hold`。其中 `equal_weight_buy_hold` 只做首次等权建仓，后续不做轮动卖出；`pool_equal_weight_hold` 以全池可交易等权为目标建仓，适合作为平台最低可用基线策略验证。
- `rebalance`：支持 `daily`、`weekly` 和 `monthly`；Alpha 搜索会优先覆盖周度/月度低换手候选。

回测指标会记录 `execution_constraints`、`skipped_trade_count` 和最多 50 条 `skipped_trades`，交易明细 payload 会记录 `raw_close`、`slippage_bps`、`volume` 和 `participation`。

回测基准：

每次回测会基于同一批清洗后的真实行情计算 `tradable_equal_weight_pool` 等权买入持有基准，并输出 `benchmark_return`、`alpha_return`、基准最大回撤、基准 Sharpe、基准净值曲线和 `out_of_sample` 样本外表现。基准建仓同样遵守 A 股 100 股手、滑点、手续费和成交量参与约束，并在指标中记录 `cost_model` 和 `fees_paid`，避免用无成本理想基准误判策略 Alpha。`out_of_sample` 同时包含策略样本外收益、基准样本外收益和样本外 Alpha。前端回测中心会同时展示策略收益、基准收益、Alpha、样本外收益和样本外 Alpha，避免只用绝对收益判断策略有效性。

启用策略健康度：

`GET /api/strategies/health` 会读取当前用户可见的 active 策略、最近一次成功回测和最近策略实验，汇总 `alpha_return`、`benchmark_return`、样本外 Alpha、walk-forward 稳定性、最大回撤、Sharpe、交易次数和短样本标记。总览页和策略中心会展示同一份健康度卡片；`/ready` 也会返回该摘要用于运维观察，但不会把策略表现波动等同于服务不可用。样本外 Alpha 低于 -5%、全段 Alpha 低于 -5% 且 Sharpe 不足、最大回撤超过 30%、分段稳定性失败或交易次数不足时，健康状态会标记为 `rejected` 或 `degraded`，提醒只能继续模拟盘观察和研究验证。响应中的 `repair_plan` 会把失败原因转成结构化下一步，例如运行正式回测、执行健康度修复、做 Alpha 网格搜索、收紧质量/动量门槛、降低行业暴露或扩大数据覆盖；前端健康度卡片会展示优先级最高的修复动作，并按 `repair_plan.params` 直接触发对应的研究/回测 API。所有动作仍只生成候选、实验、建议或纸面模拟结果，不会自动启用策略或提交真实交易订单。

策略健康响应还包含 `effectiveness_evidence`，用于把生产审查需要的证据压缩成一段可审计摘要：结论、置信度、证据强项、剩余风险、下一步动作、回测/实验引用和关键指标。即使策略健康为 `ready`，如果交易次数偏少或历史样本有限，剩余风险也会继续保留，前端会在健康度卡片中展示。

策略优化闭环：

`GET /api/strategies/optimization-health` 会返回大模型策略优化闭环健康度，并已接入 `/ready`、`/api/dashboard` 和 `/api/admin/ops-status`。该摘要会检查 DeepSeek 配置、最近一次 DeepSeek 大模型优化是否成功且在 30 天内、最近候选策略验证实验是否通过、当前 active 策略是否健康或是否存在可人工晋升候选。响应会同时返回 `latest_optimization` 和 `latest_llm_optimization`：本地 `local-alpha-grid` 只能证明 Alpha 搜索或参数验证，不能替代大模型建议证据。状态不是 `ready` 时会给出 `next_action`，例如 `configure_deepseek`、`optimize_strategy`、`validate_candidate_or_alpha_search`、`promote_after_manual_review` 或 `run_next_strategy_research_action`。该闭环只生成建议、候选策略、回测验证和人工晋升信号，不会自动提交真实交易订单。

健康度修复实验：

`POST /api/strategies/remediate-health` 会在 active 策略健康度不是 `ready` 时自动编排一次修复闭环：读取健康度失败原因和最近策略回测，调用大模型优化生成参数调整，落地为私有草稿候选策略，并立即执行正式回测验证和策略实验记录。接口不会自动提升候选策略为 active；只有验证通过后，研究员才可以通过 `/api/strategies/{strategy_id}/promote` 人工启用。若大模型不可用，本地 fallback 会优先针对全段 Alpha、样本外 Alpha、质量因子门槛、动量门槛和行业暴露生成保守修复建议。

`POST /api/strategies/research-next` 会读取 `/ready` 中的 `strategy_promotion_readiness`、策略健康度 `repair_plan` 和最近修复时间线，自动选择下一步研究动作：健康策略只返回模拟盘观察建议；已有可晋升候选时提示人工复核；没有候选时按优先级执行 `remediate_health`、`alpha_search`、`run_backtest` 或 `tighten_signal_quality`。当进入 `tighten_signal_quality` 时，系统会调用大模型/本地规则生成收紧信号建议、落地为草稿候选并立即验证。该接口会写审计日志并刷新健康度/候选状态，但不会自动晋升策略或提交真实交易订单。

`GET /api/strategies/repair-timeline` 会从审计日志中归并健康度修复、大模型优化、候选策略生成、Alpha 网格搜索、验证和提升动作，输出候选策略、优化记录、验证是否通过、Alpha、样本外 Alpha 和失败原因。前端“策略优化”页会展示这条时间线，用于追踪每次 rejected 策略修复尝试的输入、结果和下一步。

`GET /api/strategies/promotion-candidates` 会从通过验证的策略实验中提取仍为 `draft` 的候选策略，展示 Alpha、样本外 Alpha、walk-forward 稳定性、回撤、Sharpe 和阻断原因。前端“策略优化”页会把这些候选集中展示为“可晋升候选”；只有 `promotable=true` 的候选才提供人工启用按钮，启用仍走 `/api/strategies/{strategy_id}/promote`，不会自动切换 active 策略。

`/ready` 的 `strategy_promotion_readiness` 会把启用策略健康度和候选策略准入合并为运维信号：如果 active 策略已通过，则继续模拟盘观察；如果 active 策略未通过但存在 `promotable=true` 的候选，则提示人工复核后晋升；如果两者都没有，则返回 warning 级检查失败，并给出下一步修复动作，例如 `remediate_health` 或 `alpha_search`。

大模型优化：

DeepSeek-V4-Pro 的策略优化提示会优先分析 `alpha_return`、`benchmark_return`、`out_of_sample`、`walk_forward_stability`、最大回撤、Sharpe 和交易次数。若策略跑输同源等权基准或样本外表现不稳，系统会要求优化目标明确指向提高 Alpha 和泛化能力；本地 fallback 建议也会优先收窄弱信号候选数量和行业暴露。

本地 Alpha 搜索：

`POST /api/strategies/alpha-search` 会基于当前启用策略生成有限参数网格，重点搜索 `entry_mode`、`candidate_top_n`、`min_momentum`、`min_quality`、`min_relative_strength`、`relative_strength_window`、`min_market_breadth`、`rebalance`、`max_sector_pct` 和 `max_position_pct`，逐个运行真实行情回测，并按 Alpha、Sharpe、最大回撤和分段稳定性综合评分。搜索空间内置相对强弱轮动、等权轮动、等权买入持有、全池等权持有、周度/月度低换手和高仓位压力候选。接口只会保留最佳候选为草稿策略，其他试验候选归档；最佳候选会立即进入候选验证实验并和来源策略做基准对比。验证通过后会出现在“可晋升候选”中，但仍不会自动启用策略，必须由研究员人工复核后走 `/api/strategies/{strategy_id}/promote`。

模拟盘调仓建议：

模拟盘执行会先读取 active 策略健康度；健康度未通过时默认阻断纸面执行。生成建议时会同时应用策略参数和组合风控参数，实际单笔目标金额取 `strategy.max_position_pct`、组合 `max_single_position_pct` 和组合 `max_order_pct` 的更小值。持有型策略（`equal_weight_buy_hold` / `pool_equal_weight_hold`）不会因为短期 TopN 变化、止损或止盈自动卖出现有持仓，只会生成继续持有或首次/补充建仓建议。

```bash
curl -X POST http://127.0.0.1:8092/api/portfolios/<portfolio_id>/rebalance \
  -H 'Content-Type: application/json' \
  -H 'X-Zi-Api-Token: <random-long-token>' \
  -d '{"execute":false}'
```

`execute=false` 只生成买入、卖出和持有建议；`execute=true` 会把通过风控检查的建议写入纸面订单。手工纸面订单和调仓执行都会返回风险检查结果，审计日志会记录价格来源、成交金额、费用、组合风控配置、单笔/单仓/现金检查和 `paper_only=true` 标记。该接口会读取模拟盘绑定策略；如果绑定策略已归档，会自动使用当前 active 策略。策略晋升时，原来绑定旧 active 策略的模拟盘会迁移到新策略。所有动作仅影响 `zi_quant_paper_*` 表，不会提交真实交易订单。

纸面执行还会检查策略健康度。若绑定或启用策略最近成功回测的 Alpha、样本外 Alpha、分段稳定性、回撤或交易次数未通过准入，接口仍会返回调仓建议，但默认设置 `execution_blocked=true`，不会写入纸面订单。研究员需要先通过大模型优化、Alpha 网格搜索和回测验证启用新策略；只有显式传入 `allow_unhealthy_strategy=true` 才允许在已知风险下做纸面覆盖测试。

模拟盘净值快照：

新建模拟盘和手工纸面订单会自动写入 `zi_quant_paper_equity_snapshots`，记录现金、市值、总权益、浮盈、已实现收益、日收益、总收益和最大回撤。也可以手动记录估值快照：

```bash
curl -X POST http://127.0.0.1:8092/api/portfolios/<portfolio_id>/snapshot \
  -H 'Content-Type: application/json' \
  -H 'X-Zi-Api-Token: <random-long-token>' \
  -d '{"source":"manual_close"}'
```

`GET /api/portfolios/<portfolio_id>` 会返回当前持仓、最近订单、`performance` 绩效摘要和最近 60 条快照；最近订单会带 `price_source`、成交金额、费用、风险检查摘要和 `paper_only` 标记。前端“模拟盘”页会展示账户权益、收益、回撤、最近订单风控证据和快照历史。

平台内置 `模拟盘净值快照` 任务，`job_type=paper_snapshot`，默认调度为交易日 16:00。管理员可在“任务与运维”页手动执行，任务结果会写入 `zi_quant_data_job_runs`，包含每个模拟盘的权益、总收益和最大回撤。

模拟盘健康度：

`/ready`、`/api/dashboard` 和 `/api/admin/ops-status` 会返回 `paper_portfolio_health` / `portfolio_health`。健康度会检查可见模拟盘数量、是否绑定未归档策略、是否绑定 active/public 策略、最近权益快照是否在 7 天内、持仓数量和启用策略健康度。状态为 `degraded` 时会给出 `next_action`，例如 `bind_active_strategy`、`record_paper_snapshot` 或 `run_next_strategy_research_action`。该检查只服务纸面观察和模拟调仓，不会触发真实交易。

`GET /api/risk/events` 会聚合当前用户可见模拟盘的风险事件，覆盖组合最大回撤、最近单日亏损、现金比例、单票仓位集中度、持仓止损/止盈观察和 fallback 行情来源。前端“模拟盘”页可点击“刷新风险”查看事件清单。该接口只输出模拟盘观察信号和人工复核建议，不提交真实交易订单，也不构成投资建议。

`POST /api/portfolios/{portfolio_id}/rebalance` 会生成纸面调仓观察记录，并把 `observation_id`、策略健康、执行保护、目标股票、建议数量、买卖方向统计、风控通过/拒绝数量和前 12 条建议样本写入审计日志。`execute=false` 时只生成观察计划；`execute=true` 也只会写模拟盘纸面订单，不会连接券商或提交真实交易。

任务运行审计：

手动或调度触发的任务会写入 `zi_quant_data_job_runs`，记录任务名称、类型、状态、开始/结束时间、耗时、输入 payload 和结果 JSON。运维页会展示最近运行历史，并优先展示结构化 `diagnostic`：包含失败/成功分类、严重度、是否可重试、建议动作和摘要说明。例如卡住后被重置的任务会标记为 `stale_timeout`，策略研究观察会标记为 `strategy_observation`。API 可按任务过滤：

```bash
curl http://127.0.0.1:8092/api/admin/job-runs?limit=20 \
  -H 'X-Zi-Api-Token: <random-long-token>'
```

到期任务 runner：

生产或本地服务面板可以每分钟调用一次 runner，它会读取 `zi_quant_data_jobs.schedule` 的 cron 表达式，只执行当前分钟到期且本分钟尚未运行过的任务：

```bash
uv run python scripts/run_due_jobs.py --limit 3
```

也可以作为长驻进程运行，由进程管理器守护；每轮执行后会输出一段 JSON，包含 `runner`、`mode`、`iteration`、`ran_at`、`paper_only` 和本轮任务结果：

```bash
uv run python scripts/run_due_jobs.py --loop --interval-seconds 60 --limit 3
```

systemd 示例：

```ini
[Unit]
Description=Zi Quant due job runner
After=network.target postgresql.service

[Service]
WorkingDirectory=/opt/zi-quant-platform
EnvironmentFile=/opt/zi-quant-platform/.env
ExecStart=/usr/bin/env uv run python scripts/run_due_jobs.py --loop --interval-seconds 60 --limit 3
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

安装为 console script 后也可运行：

```bash
uv run zi-quant-run-due-jobs --limit 3
uv run zi-quant-run-due-jobs --loop --interval-seconds 60 --limit 3
```

当前支持标准五段 cron 子集：`*`、`*/N`、数字、范围和逗号列表。示例调试：

```bash
uv run python scripts/run_due_jobs.py --now '2026-06-11T16:00:00+08:00' --limit 5
```

默认任务包含 `策略研究与模拟观察`，类型为 `strategy_research`。该任务会调用 `/api/strategies/research-next` 的同一套编排逻辑：策略健康时只为公共模拟盘生成纸面调仓观察；策略不健康时按健康度修复计划进入 DeepSeek 参数优化、Alpha 网格搜索、正式回测或候选验证。任务 payload 会被限制在生产安全范围内，例如 `days` 最高 1800、`max_trials` 最高 30、`max_portfolios` 最高 50；整个流程只写候选策略、回测、实验、审计和模拟盘建议，不会自动晋升策略或提交真实交易订单。

`GET /api/admin/jobs` 会返回当前任务表，包含任务类型、状态、调度表达式、最近运行时间、payload、是否手工任务、最近漏跑提示和启动阻断原因。前端“任务与运维”页和运维脚本可以直接使用该接口核对计划任务是否存在、是否卡在 running、是否可能漏跑。`stock_universe` 计划任务默认只同步股票基础信息，不重置“公共 A 股 500”成员，避免日常基础信息同步破坏已经验证过的真实数据覆盖；如需重建公共池，应使用 `pool_rebuild` 任务或显式设置 `reset_public_pool=true`。

运维页和 `/api/admin/ops-status` 会标记最近 24 小时可能漏跑的计划任务，显示最近应触发时间、上次运行时间和漏跑分钟数；这用于检查 runner 守护进程，不会自动补跑或执行真实交易。

用户与权限管理：

管理员接口需要同时具备 API Token 和管理员用户身份。测试环境可用请求头切到内置管理员：

```text
X-Zi-User-Email: admin@local.zicode
```

用户管理接口支持列出、创建/更新用户、切换角色和启停账号；平台会阻止停用最后一个 active admin。业务资源仍然通过 `owner_id` 与 `visibility` 做公共/私有隔离。

多用户调试可通过请求头切换当前用户：

```text
X-Zi-User-Email: researcher@local.zicode
X-Zi-User-Id: <user uuid>
```

安全边界：

- 平台只做量化研究和模拟盘，不会向真实券商账户提交订单。
- 严格真实同步时 `allow_fallback=false`；数据源不可用或响应不可解析会返回失败，不会静默写入样本数据。
- 因子 payload 会标记 `quality_source`，例如 `financial_report:qveris` 或 `market_or_seed`，便于审计真实数据参与程度。
