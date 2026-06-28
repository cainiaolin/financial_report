"""finrep CLI: sync (同步数据) / report (生成报告) / serve (启动看板).

用法:
  python -m finrep.cli.main sync 600519 000858
  python -m finrep.cli.main report 600519 --peers 000858 --fmt both
  python -m finrep.cli.main serve
"""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

# Windows 控制台默认 GBK, 强制 stdout/stderr 为 UTF-8 (避免中文与 ✓ 等字符编码崩溃)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

import typer

from ..fetcher.errors import FetchError
from ..fetcher.manager import FetcherManager
from ..report import export_excel, render_report
from ..storage import Repository

app = typer.Typer(help="A股财报分析系统 (finrep)", no_args_is_help=True)
logger = logging.getLogger(__name__)


@app.command()
def sync(codes: list[str] = typer.Argument(None, help="股票代码, 空格分隔, 如: 600519 000858")):
    """同步公司三大报表到本地 Parquet (增量)."""
    if not codes:
        typer.echo("请提供至少一个股票代码", err=True)
        raise typer.Exit(1)
    fm = FetcherManager()
    with Repository() as repo:
        for code in codes:
            try:
                for _, r in fm.fetch_all(code).items():
                    repo.save(r)
                typer.echo(f"✓ {code} 同步成功 (截至 {repo.last_period(code, 'balance_sheet')})")
            except FetchError as e:
                typer.echo(f"✗ {code} 同步失败: {type(e).__name__}", err=True)


@app.command()
def report(
    code: str = typer.Argument(..., help="主公司代码"),
    peers: list[str] = typer.Option(None, "--peers", "-p", help="对比公司代码 (可多次)"),
    fmt: str = typer.Option("both", "--fmt", "-f", help="输出格式: html | excel | both"),
):
    """生成分析报告 (需先 sync)."""
    if fmt not in ("html", "excel", "both"):
        typer.echo(f"无效 fmt: {fmt} (可选 html|excel|both)", err=True)
        raise typer.Exit(1)
    with Repository() as repo:
        try:
            if fmt in ("html", "both"):
                p = render_report(code, repo, peers=peers or None)
                typer.echo(f"✓ HTML 报告: {p}")
            if fmt in ("excel", "both"):
                p = export_excel(code, repo, peers=peers or None)
                typer.echo(f"✓ Excel 报告: {p}")
        except FileNotFoundError as e:
            typer.echo(f"{e} — 请先运行: finrep sync {code}", err=True)
            raise typer.Exit(1)


@app.command()
def serve():
    """启动 Streamlit 看板."""
    script = Path(__file__).resolve().parent.parent / "app" / "streamlit_app.py"
    typer.echo(f"启动 Streamlit 看板: {script}")
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(script)], check=False)


if __name__ == "__main__":
    app()
