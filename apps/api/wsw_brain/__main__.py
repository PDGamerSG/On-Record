"""Run the On Record API with Uvicorn."""

from __future__ import annotations

import uvicorn


def main() -> None:
    """Start the API application on the local development port."""
    uvicorn.run("wsw_brain.app:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
