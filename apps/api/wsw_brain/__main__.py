"""Run the On Record API with Uvicorn."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

import uvicorn


def main(argv: Sequence[str] | None = None) -> None:
    """Start the API application with optional local server settings."""
    parser = argparse.ArgumentParser(description="Run the On Record API")
    parser.add_argument("--host", default="127.0.0.1", help="interface to bind")
    parser.add_argument("--port", default=8000, type=int, help="port to bind")
    parser.add_argument("--reload", action="store_true", help="reload when source files change")
    options = parser.parse_args(argv)
    run_options = {"host": options.host, "port": options.port}
    if options.reload:
        run_options["reload"] = True
    uvicorn.run("wsw_brain.app:app", **run_options)


if __name__ == "__main__":
    main()
