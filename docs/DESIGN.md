# A股财报分析系统 · 设计方案

> 版本: v0.1 (2026-06-24)
> 定位: 本地化、零运维的 A 股财报分析系统，支持「单公司多年纵向分析」+「同行业多家公司横向对比」，面向个人/小团队。

---

## 一、系统定位与核心能力

**一句话定位**：拉取 A 股上市公司多年财报，做单公司深度分析 + 同行业多家公司横向对比，本地缓存、零运维。

**核心能力**：
1. **多年财报获取**——任意 A 股公司三大报表 + 财务指标，本地缓存，支持增量更新
2. **单公司深度分析**——五大能力指标 + 杜邦分解 + 多年趋势
3. **同行业对比**——按申万行业自动圈定可比公司，中位数/百分位排名，雷达图多维对比
4. **报告生成**——一键导出 HTML / Excel / PDF 分析报告

---

## 二、关键技术选型（决策表）

| 层 | 选型 | 核心理由 |
|---|---|---|
| 数据源 | **AkShare（主）** + Tushare Pro（备/校验） | AkShare 东财源免费提供完整三大报表（319/203/252 字段）+ 140+ 财务指标，`stock_zh_dupont_comparison_em` 等同行对比接口一步到位；Tushare 字段规范，做双源交叉校验 |
| 数据存储 | **Parquet（归档）+ DuckDB（查询）** | 列式存储，多年聚合比 SQLite 快 1~3 个数量级；零服务、pip 即用；ASOF/窗口函数原生支持 |
| 数据处理 | **polars**（ETL）+ DuckDB SQL（聚合）+ pandas（兼容兜底） | 比 pandas 快 5~30×，内存省数十倍 |
| 交互形态 | **Streamlit**（看板）+ Typer（CLI） | 个人开发者开发成本最低；CLI 驱动定时任务 |
| 可视化 | **pyecharts** | 中文原生，趋势折线/同业雷达/杜邦 Treemap/瀑布图全覆盖 |
| 报告导出 | HTML（Jinja2）+ Excel（XlsxWriter）+ PDF（WeasyPrint） | 一套 Jinja2 模板，HTML 与 PDF 同源 |
| 行业分类 | **申万 2021**（默认二级 134 个，样本不足回退一级） | 量化圈事实标准，AkShare 免费提供 |

### 数据源关键接口

```python
# 三大报表 (AkShare 东财源, 单位:元)
ak.stock_balance_sheet_by_report_em(symbol="SH600519")   # 资产负债表 319字段
ak.stock_profit_sheet_by_report_em(symbol="SH600519")    # 利润表 203字段
ak.stock_cash_flow_sheet_by_report_em(symbol="SH600519") # 现金流量表 252字段
ak.stock_financial_analysis_indicator_em(symbol="600519.SH", indicator="按报告期")  # 140+指标

# 同行对比 (AkShare 杀手锏, 直接返回同行清单+排名+行业中值)
ak.stock_zh_dupont_comparison_em(symbol="SZ000895")     # 杜邦同行比较
ak.stock_zh_growth_comparison_em(symbol="SZ000895")     # 成长性同行比较
ak.stock_zh_valuation_comparison_em(symbol="SZ000895")  # 估值同行比较

# 行业分类与成分股
ak.stock_industry_clf_hist_sw()                          # 申万分类历史
ak.stock_board_industry_cons_em(symbol="白酒")           # 东财板块成分股
```

---

## 三、系统架构（五层 + 数据流）

```
┌──────────────────────────────────────────────────────────────┐
│ ① 数据获取层 Fetcher                                          │
│    AkShare(主) / Tushare(备) — 限频重试 + 双源校验 + 增量同步  │
│    接口: fetch(code, years) -> raw DataFrame                 │
├──────────────────────────────────────────────────────────────┤
│ ② 数据存储层 Storage                                          │
│    Parquet(原始分区归档) + DuckDB(查询引擎) + sync_state     │
│    接口: upsert(raw) / query(code, fields) -> clean DF       │
├──────────────────────────────────────────────────────────────┤
│ ③ 指标计算层 Metrics （纯函数,无副作用,可单测）               │
│    profitability/growth/solvency/operating/cashflow/dupont   │
│    registry 按 metrics.yaml 动态注册（新增指标零代码）        │
│    接口: compute(clean DF) -> indicators DF                  │
├──────────────────────────────────────────────────────────────┤
│ ④ 分析对比层 Analysis                                         │
│    peer_compare(中位数/百分位/MAD去极值) + trend(CAGR/同比)   │
│    industry(申万圈定+龙头识别) -> 标准化 Result 对象          │
├──────────────────────────────────────────────────────────────┤
│ ⑤ 展示层 Presentation                                         │
│    Streamlit 看板 / Typer CLI / HTML·Excel·PDF 报告          │
│    仅消费 ④ 结果,不含计算逻辑（可整体替换）                  │
└──────────────────────────────────────────────────────────────┘
```

**设计原则体现**：
- 分层职责单一 = **SRP**
- `FetcherBase` 抽象基类 = **DIP**（依赖抽象而非 AkShare 具体实现，可切换/降级）
- `metrics.yaml` 动态注册 = **OCP**（加指标不改代码）
- 每层只暴露窄接口 = **ISP**

---

## 四、核心设计要点

### 4.1 指标体系（核心 15 项，纯财报无行情依赖）

| 能力 | 指标 | 计算口径 |
|---|---|---|
| 盈利/综合 | ROE(加权归母) | 归母净利润 / 平均归母净资产 |
| 盈利 | 毛利率 | (营收-营业成本) / 营收 |
| 盈利 | 销售净利率 | 净利润 / 营收 |
| 盈利质量 | **扣非净利率** | 扣非净利润 / 营收 |
| 盈利/资本 | ROIC | NOPAT / 平均投入资本(股东权益+有息负债) |
| 营运 | 总资产周转率 | 营收 / 平均总资产 |
| 营运 | 存货周转天数 | 365 / (营业成本/平均存货) |
| 营运 | 应收账款周转天数 | 365 / (营收/平均应收账款) |
| 偿债 | 资产负债率 | 总负债 / 总资产 |
| 偿债 | 流动比率 | 流动资产 / 流动负债 |
| 偿债 | 利息保障倍数 | EBIT / 利息费用 |
| 成长 | 营收同比 | (本期-上年同期) / 上年同期 |
| 成长 | 归母净利润增速 | 同上口径 |
| 现金流 | 净现比 | 经营现金流净额 / 净利润 |
| 现金流 | 收现比 | 销售收现 / 营收 |

**雷达图 8 维**（百分位标准化到 [0,100]）：
ROE、毛利率、总资产周转率、营收增速、净现比、流动比率、扣非净利率、资产负债率（反向）。

**杜邦分解**：ROE = 销售净利率 × 总资产周转率 × 权益乘数（支持点击下钻到三因素分别对标行业）。

### 4.2 A股财报避坑清单（计算层强制处理）

1. 区分「净利润」与「扣非净利润」——盈利质量以扣非为准
2. 商誉占净资产比 >30% → 高风险预警
3. 全部用「归属于母公司股东」口径 + 合并报表
4. 资产负债恒等式校验：`|资产 - (负债+所有者权益)| / 总资产 ≤ 0.1%`（吸收数据源舍入误差），超阈值标记异常并写入 `validation_log`
5. 周转率分子口径：成本类（存货/应付）用营业成本，收入类（应收/总资产）用营收
6. 现金流造假信号：净现比长期 <0.7、CFFO 与净利润背离、存贷双高

### 4.3 同业对比方法论

- **基准用中位数**（非均值）——财务分布右偏严重；同时展示 Q1/Q3
- **百分位排名**——公司值在行业内的分位
- **去极值**——算行业统计量前先做 MAD 或 1% Winsorize，再标准化（顺序不可颠倒）
- **行业适配**——金融/地产走专用指标集（剔除流动比率等失真指标，改用资本充足率/不良率）
- **同业圈定流程**：
  ```
  申万二级初筛 → 样本数自适应(<5回退一级, >30取龙头组)
              → 剔除 ST/上市<2年/停牌/异常报表
              → 龙头识别(规模×盈利×成长 加权 zscore)
  ```

### 4.4 数据获取工程化

- **增量同步**：`sync_state` 表记录 `(code, report_type, last_period)`，只拉新报告期；`--force-full` 全量重刷
- **限频容灾**：`tenacity` 指数退避重试 + 令牌桶限频；AkShare 失败自动降级 Tushare
- **双源校验**：关键字段（净利润/营收/总资产/净资产/经营现金流）AkShare vs Tushare 差异 >1% 标记复核
- **单位统一**：全部换算为「元」
- **分析只读本地**：抓取与查询解耦，看板不触发网络请求
- **错误分类处理**（决定重试还是跳过，避免无效重试）：
  - 网络错误（超时/连接失败）→ `tenacity` 指数退避重试
  - 限频错误（HTTP 429/源站封禁）→ 延长退避 + 切换 Tushare 备源
  - 数据错误（字段缺失/单位异常/恒等式超阈值）→ 标记异常不阻断，写入 `validation_log`
  - 业务错误（公司退市/代码无效）→ 跳过并记录到失败队列

---

## 五、项目目录结构

```
financial_report/
├── pyproject.toml              # uv/poetry 依赖管理
├── config/
│   ├── settings.yaml           # token/路径/限频参数
│   ├── metrics.yaml            # 指标定义(公式/依赖字段/方向)——配置化
│   └── industry.yaml           # 申万映射+行业适配规则
├── data/
│   ├── raw/                    # Parquet 原始数据 (code/year 分区)
│   │   └── balance_sheet/code=600519/year=2023/data.parquet
│   ├── meta/sync_state.duckdb  # 同步状态表
│   └── warehouse.duckdb        # 物化结果(可选)
├── src/
│   ├── fetcher/                # ① 数据获取层
│   │   ├── base.py             # 抽象接口 + 重试/限频装饰器
│   │   ├── akshare_source.py
│   │   ├── tushare_source.py
│   │   └── sync.py             # 增量同步编排
│   ├── storage/                # ② 数据存储层
│   │   ├── repo.py             # upsert/query 统一接口
│   │   └── schema.sql          # DuckDB 建表/视图
│   ├── metrics/                # ③ 指标计算层 (纯函数)
│   │   ├── profitability.py
│   │   ├── growth.py
│   │   ├── solvency.py
│   │   ├── operating.py
│   │   ├── cashflow.py
│   │   ├── dupont.py
│   │   └── registry.py         # 按 metrics.yaml 动态注册
│   ├── analysis/               # ④ 分析对比层
│   │   ├── peer_compare.py     # 同业横向对比
│   │   ├── trend.py            # 多年纵向趋势
│   │   ├── industry.py         # 申万圈定+龙头识别
│   │   └── result.py           # 标准化 Result 对象
│   ├── viz/                    # 可视化 (pyecharts 封装)
│   │   ├── charts_trend.py
│   │   ├── charts_radar.py
│   │   └── charts_dupont.py
│   ├── report/                 # 报告导出
│   │   ├── templates/*.html    # Jinja2 模板
│   │   ├── html_export.py
│   │   ├── excel_export.py     # XlsxWriter
│   │   └── pdf_export.py       # WeasyPrint
│   ├── app/
│   │   └── streamlit_app.py    # ⑤ Streamlit 看板
│   └── cli/
│       └── main.py             # Typer CLI: sync/report/serve
├── tests/                      # pytest
│   ├── test_metrics.py
│   ├── test_fetcher_retry.py
│   └── fixtures/
└── reports/                    # 报告输出 html/excel/pdf
```

---

## 六、实施路线

| 阶段 | 周期 | 交付内容 |
|---|---|---|
| **MVP** | 1~2 周 | AkShare 拉单公司三大报表 → Parquet+DuckDB 落地 → polars 算 8 核心指标（ROE/毛利率/资产负债率/CAGR等） → Streamlit 单页折线图 + CLI 导出一份 HTML |
| **V1** | 2~4 周 | 同业对比（中位数/百分位/雷达图）+ 杜邦 Treemap + 瀑布图 + Excel/PDF 导出 + 增量同步 + 双源校验 + metrics.yaml 配置化 + pytest 覆盖 |
| **V2** | 按需 | 行情接入（PE/PB/PS 估值）+ DCF 模型 + 定时任务（盘后自动同步+邮件推送）+ 财务粉饰预警（Beneish M-Score）+ 升级 FastAPI+前端 |

---

## 七、关键工程要点

1. **配置化指标**——`metrics.yaml` 声明公式与依赖字段，新增指标零代码改动（OCP）
2. **纯函数计算层**——输入输出均为 DataFrame，无副作用，易单测（SRP）
3. **数据校验**——入库前校验恒等式/非空/单位/连续性，异常写日志告警
4. **Token 安全**——Tushare token 走环境变量 `TUSHARE_TOKEN`，绝不入库
5. **失败隔离**——单公司抓取失败不阻塞整批，失败队列持久化支持断点续传
6. **可复现性**——原始数据只追加不改写；依赖版本锁定（uv/poetry lock）

---

## 八、配置文件示例

### settings.yaml（环境相关配置）

```yaml
# 敏感凭证: 使用环境变量占位符, 绝不写入明文 token
tushare:
  token: ${TUSHARE_TOKEN}      # 从环境变量注入; 未配置时降级为 AkShare 单源
  enabled: true

akshare:
  request_interval: [0.5, 2.0] # 随机延时秒数区间, 规避 IP 限频

paths:
  raw_dir: ./data/raw
  warehouse: ./data/warehouse.duckdb
  sync_state: ./data/meta/sync_state.duckdb

limits:
  retry_max: 5                 # tenacity 最大重试次数
  rate_per_min: 60             # 令牌桶: 每分钟请求数上限
```

### metrics.yaml（指标定义——配置化, 新增指标零代码）

```yaml
metrics:
  - name: roe
    category: profitability
    formula: net_profit_parent / avg(parent_equity)
    depends: [net_profit_parent, parent_equity]
    unit: percent
    direction: higher_better
  - name: gross_margin
    category: profitability
    formula: (revenue - operating_cost) / revenue
    depends: [revenue, operating_cost]
    unit: percent
    direction: higher_better
  # ... 其余指标同结构声明
```

### industry.yaml（行业适配规则）

```yaml
classification: SW2021           # 申万 2021
default_level: L2                # 默认二级行业圈定同业
fallback:
  min_samples: 5                 # 同业 <5 家回退到一级
  max_samples: 30                # >30 家按市值取龙头组

# 特殊行业专用指标集 (剔除失真指标)
special_rules:
  - industry: [银行, 保险, 证券]
    exclude: [current_ratio, quick_ratio, debt_to_asset]
    include: [capital_adequacy_ratio, np_ratio]
  - industry: [房地产开发]
    exclude: [inventory_turnover]
    include: [net_debt_ratio]
```

---

## 九、依赖清单（锁定主版本号）

```toml
[project.dependencies]
# 数据获取
akshare = "^1.14"         # 主数据源, 三大报表 + 同行对比
tushare = "^1.4"          # 可选备源, 需 5000 积分

# 存储/处理
duckdb = "^1.1"           # 列式分析引擎
polars = "^1.20"          # ETL 主力
pandas = "^2.2"           # 兼容兜底 (pyecharts 等库对接)

# 交互/可视化
streamlit = "^1.40"
typer = "^0.15"
pyecharts = "^2.0"

# 报告
jinja2 = "^3.1"
xlsxwriter = "^3.2"
weasyprint = "^62"        # PDF; 中文需 @font-face 配思源黑体

# 工程
tenacity = "^9.0"         # 指数退避重试
pyyaml = "^6.0"           # 配置解析
pytest = "^8.3"           # 测试
```

> 注：具体精确版本以 `uv lock` / `poetry lock` 生成的 lock 文件为准，lock 文件提交入库以保证可复现性（YAGNI：未用到的库不写入）。
