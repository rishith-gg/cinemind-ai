"""Command line entry point: `cinemind doctor | serve | worker | models | export-openapi`."""

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from cinemind.api.app import create_app
from cinemind.core import face_config
from cinemind.core.config import REPO_ROOT, get_settings
from cinemind.core.doctor import run_doctor
from cinemind.core.transcribe_config import ASK_ABOVE_MB, WHISPER_MODELS
from cinemind.db.migrate import upgrade_head

app = typer.Typer(help="CineMind AI: local-first pre-editing assistant.", no_args_is_help=True)

models_app = typer.Typer(help="Speech and face models: list, download.", no_args_is_help=True)
app.add_typer(models_app, name="models")

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
def worker() -> None:
    """Run the job worker in the foreground (normally `serve` starts it for you)."""
    from cinemind.jobs.worker import main

    main()


@app.command()
def serve(
    reload: Annotated[bool, typer.Option(help="Auto-reload (development).")] = False,
    with_worker: Annotated[
        bool, typer.Option("--worker/--no-worker", help="Also start the job worker process.")
    ] = True,
) -> None:
    """Start the API (and the built frontend, if present) on 127.0.0.1, plus the worker."""
    s = get_settings()
    if with_worker:
        upgrade_head(s.db_path)  # migrate once, before API and worker start together
    proc = (
        subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", "cinemind.jobs.worker", "--parent-pid", str(os.getpid())]
        )
        if with_worker
        else None
    )
    try:
        if reload:
            uvicorn.run(
                "cinemind.api.app:create_app", factory=True, host=s.host, port=s.port, reload=True
            )
        else:
            uvicorn.run(create_app(), host=s.host, port=s.port)
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()


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


@models_app.command("list")
def models_list() -> None:
    """Show the speech models the app knows and which are downloaded."""
    from cinemind.ai import transcriber

    settings = get_settings()
    in_use = transcriber.choose_model(settings).name
    table = Table(title=f"Speech models (folder: {settings.models_path})")
    for col in ("model", "download", "status", "in use"):
        table.add_column(col)
    for name in WHISPER_MODELS:
        choice = transcriber.choose_model(settings, name)
        status = "[green]downloaded[/]" if choice.ready else "not downloaded"
        table.add_row(name, f"{choice.size_mb} MB", status, "yes" if name == in_use else "")
    console = Console()
    console.print(table)
    faces = Table(title="Face models (pull with `cinemind models pull faces`)")
    for col in ("file", "download", "status"):
        faces.add_column(col)
    for spec in face_config.FACE_MODELS:
        on_disk = spec.path(settings.models_path).is_file()
        status = "[green]downloaded[/]" if on_disk else "not downloaded"
        faces.add_row(spec.filename, f"{spec.size_kb / 1024:.1f} MB", status)
    console.print(faces)


@models_app.command("pull")
def models_pull(
    name: Annotated[
        str | None,
        typer.Argument(
            help="A speech model name, or 'faces'. Default: the speech model the app will "
            "use and the face models."
        ),
    ] = None,
    yes: Annotated[bool, typer.Option("--yes", help="Do not ask before a large download.")] = False,
) -> None:
    """Download models once (needs internet). Processing itself never downloads."""
    from cinemind.ai import faces, transcriber
    from cinemind.core.errors import DomainError

    settings = get_settings()

    def fetch(label: str, action: Callable[[], None]) -> None:
        typer.echo(f"Downloading {label} ...")
        try:
            action()
        except DomainError as exc:
            typer.echo(exc.message, err=True)
            raise typer.Exit(1) from exc
        except Exception as exc:  # network, disk, or the model host
            typer.echo(
                f"The download failed ({exc}). Check the internet connection and retry.", err=True
            )
            raise typer.Exit(1) from exc

    if name != "faces":
        try:
            choice = transcriber.choose_model(settings, name)
        except DomainError as exc:
            typer.echo(f"{exc.message} Or 'faces' for the face models.", err=True)
            raise typer.Exit(2) from exc
        if choice.ready:
            typer.echo(f"'{choice.name}' is already downloaded: {choice.path}")
        else:
            if choice.size_mb > ASK_ABOVE_MB and not yes:
                typer.confirm(
                    f"'{choice.name}' is a {choice.size_mb} MB download. Continue?", abort=True
                )
            label = f"speech model '{choice.name}' ({choice.size_mb} MB) from {choice.repo}"
            fetch(label, lambda: transcriber.pull(choice))
            typer.echo(f"Done: {choice.path}")
    if name in (None, "faces"):
        folder = settings.models_path / "faces"
        if face_config.models_ready(settings.models_path):
            typer.echo(f"The face models are already downloaded: {folder}")
        else:
            size_mb = sum(spec.size_kb for spec in face_config.FACE_MODELS) / 1024
            label = f"face models YuNet and SFace ({size_mb:.0f} MB) from the OpenCV model zoo"
            fetch(label, lambda: faces.pull(settings.models_path))
            typer.echo(f"Done: {folder}")
