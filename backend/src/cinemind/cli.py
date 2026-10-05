"""Command line entry point: `cinemind doctor | serve | export-openapi`."""

import json
from pathlib import Path
from typing import Annotated

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from cinemind.api.app import create_app
from cinemind.core.config import REPO_ROOT, get_settings
from cinemind.core.doctor import run_doctor

app = typer.Typer(help="CineMind AI: local-first pre-editing assistant.", no_args_is_help=True)

_STYLE = {"ok": "green", "missing": "red", "warn": "yellow"}


@app.command()
def doctor(as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False) -> None:
    """Check the environment and recommend a model tier."""
    report = run_doctor(get_settings())
    if as_json:
        typer.echo(report.model_dump_json(indent=2))
        raise typer.Exit(0 if report.ok else 1)

    console = Console()
    table = Table(title="CineMind doctor")
    for col in ("check", "status", "version", "notes"):
        table.add_column(col)
    for c in report.checks:
        notes = " | ".join(x for x in (c.detail, f"fix: {c.fix}" if c.fix else None) if x)
        label = c.status if c.status == "ok" or c.required else f"{c.status} (optional)"
        table.add_row(c.name, f"[{_STYLE[c.status]}]{label}[/]", c.version or "", notes)
    console.print(table)

    hw, gpu = report.hardware, report.hardware.gpu
    console.print(f"\n[bold]Machine:[/] {hw.os} {hw.arch} | {hw.cpu_name} | {hw.cpu_cores} threads")
    console.print(
        f"[bold]RAM:[/] {hw.ram_gb} GB | [bold]GPU:[/] {gpu.kind}"
        + (f" ({gpu.name})" if gpu.name else "")
        + (f", {gpu.vram_gb} GB VRAM" if gpu.vram_gb else "")
    )
    console.print(
        f"[bold]Recommended model tier:[/] {report.recommended.tier} ({report.recommended.reason})"
    )
    console.print(f"[bold]Tier in use:[/] {report.selected_tier}")
    console.print(
        "[green]Ready.[/]" if report.ok else "[red]Fix the required items above first.[/]"
    )
    raise typer.Exit(0 if report.ok else 1)


@app.command()
def serve(reload: Annotated[bool, typer.Option(help="Auto-reload (development).")] = False) -> None:
    """Start the API (and the built frontend, if present) on 127.0.0.1."""
    s = get_settings()
    if reload:
        uvicorn.run(
            "cinemind.api.app:create_app", factory=True, host=s.host, port=s.port, reload=True
        )
    else:
        uvicorn.run(create_app(), host=s.host, port=s.port)


@app.command("export-openapi")
def export_openapi(
    out: Annotated[Path, typer.Option(help="Output file, relative to repo root.")] = Path(
        "frontend/openapi.json"
    ),
) -> None:
    """Write the OpenAPI schema; the frontend client is generated from it."""
    target = REPO_ROOT / out
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(create_app(frontend_dist=None).openapi(), indent=2) + "\n")
    typer.echo(f"wrote {target.relative_to(REPO_ROOT)}")
