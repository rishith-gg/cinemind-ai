"""Cross-platform task runner (replaces a justfile): `uv run python scripts/tasks.py <task>`."""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def run(*args: str, cwd: Path = ROOT) -> None:
    exe = shutil.which(args[0])
    if exe is None:
        sys.exit(f"'{args[0]}' not found on PATH. Run `uv run cinemind doctor`.")
    print(f"\n$ {' '.join(args)}", flush=True)
    if subprocess.run([exe, *args[1:]], cwd=cwd, check=False).returncode != 0:
        sys.exit(f"FAILED: {' '.join(args)}")


def gen_api() -> None:
    run("uv", "run", "cinemind", "export-openapi")
    run("pnpm", "gen-api", cwd=FRONTEND)


def check() -> None:
    run("uv", "run", "ruff", "format", "--check", "backend", "eval", "scripts")
    run("uv", "run", "ruff", "check", "backend", "eval", "scripts")
    run("uv", "run", "pyright")
    run("uv", "run", "pytest", "-q")
    run("pnpm", "typecheck", cwd=FRONTEND)
    run("pnpm", "lint", cwd=FRONTEND)
    run("pnpm", "test", cwd=FRONTEND)
    print("\nAll checks passed.")


TASKS = {
    "check": check,
    "gen-api": gen_api,
    "format": lambda: run("uv", "run", "ruff", "format", "backend", "eval", "scripts"),
    "doctor": lambda: run("uv", "run", "cinemind", "doctor"),
    "serve": lambda: run("uv", "run", "cinemind", "serve"),
    "dev-api": lambda: run("uv", "run", "cinemind", "serve", "--reload"),
    "dev-ui": lambda: run("pnpm", "dev", cwd=FRONTEND),
    "build-ui": lambda: run("pnpm", "build", cwd=FRONTEND),
}

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if name not in TASKS:
        sys.exit(f"usage: tasks.py <{'|'.join(TASKS)}>")
    TASKS[name]()
