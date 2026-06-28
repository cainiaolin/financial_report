# finrep — A股财报分析系统

获取 A 股上市公司多年财报，支持**单公司深度分析** + **同行业多家公司横向对比**。

## 核心特性

- **双数据源**：AkShare 新浪源（主力，免费）+ Tushare Pro（备选，交叉校验）
- **多年三大报表** + **15 核心财务指标**（盈利/营运/偿债/成长/现金流）+ 杜邦分解
- **同业对比**：中位数基准 / 百分位 / 排名 + 雷达图
- **三种输出**：Streamlit 交互看板 / HTML 报告 / Excel
- **本地化**：Parquet + DuckDB 存储，增量同步，分析只读本地

## 安装

```bash
pip install -e .                  # 核心依赖 (获取/存储/指标/分析/报告/CLI)
pip install -e ".[web]"           # 追加 Streamlit 看板与可视化 (pyecharts)
pip install -e ".[dev]"           # 追加 pytest

# 可选: 配置 Tushare token (不配则自动降级为 AkShare 单源)
cp .env.example .env
# 编辑 .env 填入 TUSHARE_TOKEN (https://tushare.pro 注册, 需 5000 积分)
# ⚠️ .env 含敏感 token, 已在 .gitignore 中, 切勿提交版本库
```

## 使用

### CLI（`finrep` 命令）

```bash
finrep sync 600519 000858                            # 同步公司三大报表到本地
finrep report 600519 --peers 000858 -f both          # 生成 HTML + Excel 报告
finrep serve                                         # 启动 Streamlit 看板
```

### Streamlit 看板

```bash
streamlit run src/finrep/app/streamlit_app.py
# 浏览器中输入主公司代码 + 对比清单 → 点击「同步数据」
# 单公司: 指标趋势折线 + 最新年报 + CAGR
# 同业对比: 雷达图 + 排名表 + 柱状对比
```

### Python API

```python
from finrep.fetcher.manager import FetcherManager
from finrep.storage import Repository
from finrep.metrics import compute_metrics
from finrep.analysis import peer_compare, trend_summary

fm = FetcherManager()
with Repository() as repo:
    for rt, r in fm.fetch_all("600519").items():   # 抓取三大报表
        repo.save(r)
    metrics = compute_metrics(repo.load_all("600519"))   # 计算 15 指标
    peer = peer_compare(["600519", "000858"], repo)      # 同业对比
    trend = trend_summary("600519", repo, years=5)       # 5年趋势 + CAGR
```

## 架构（五层）

```
获取层 fetcher  →  存储层 storage  →  计算层 metrics  →  分析层 analysis  →  展示层 viz/report/app
(AkShare/Tushare)  (Parquet+DuckDB)   (15指标+杜邦)       (趋势+同业对比)      (Streamlit/HTML/Excel)
```

详见 [docs/DESIGN.md](docs/DESIGN.md)。

## 数据源说明

| 源 | 接口 | 状态 | 用途 |
|---|---|---|---|
| AkShare 新浪 | `stock_financial_report_sina` | ✅ ~3s/报表 | 主力 |
| AkShare 东财 | `stock_*_by_report_em` | ❌ ConnectionError | 降级备选 |
| Tushare Pro | `balancesheet/income/cashflow` | ✅ (需 token) | 双源校验 |

## 指标清单（15 核心）

- **盈利**：ROE(归母摊薄) / 毛利率 / 销售净利率 / ROIC
- **营运**：总资产周转率 / 存货周转天数 / 应收账款周转天数
- **偿债**：资产负债率 / 流动比率 / 利息保障倍数 / 权益乘数
- **成长**：营收同比 / 归母净利润同比 (+ CAGR)
- **现金流**：净现比 / 收现比 / 自由现金流 FCF

## 已知限制（V1 规划）

- 扣非净利润：新浪三大报表无此字段，需财务指标接口（东财恢复/Tushare 接入后补）
- 同业圈定：当前手动指定公司清单，自动申万行业圈定待东财行业接口恢复
- `debt_to_asset` 等中性指标按"越高越好"排序，展示层中性处理待 V1
- 估值指标（PE/PB）需接入行情数据（V2）

## 项目结构

```
financial_report/
├── config/          settings.yaml / metrics.yaml / industry.yaml
├── data/            Parquet 原始数据 + DuckDB 同步状态 (gitignore)
├── reports/         生成的 HTML/Excel 报告 (gitignore)
├── src/finrep/
│   ├── fetcher/     base / sina_source / tushare_source / manager / retry / codes / errors
│   ├── storage/     repo (Parquet + DuckDB + 恒等式校验)
│   ├── metrics/     calculator (纯函数) / registry (yaml 元数据)
│   ├── analysis/    trend (CAGR) / peer (中位数/百分位/排名)
│   ├── viz/         charts (pyecharts: 趋势/雷达/柱状)
│   ├── report/      html_export (Jinja2) / excel_export (XlsxWriter)
│   ├── app/         streamlit_app
│   └── cli/         main (Typer: sync/report/serve)
└── docs/DESIGN.md   完整设计方案
```
