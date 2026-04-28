"""Run the service: ``python -m skillsmith``."""

from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run("skillsmith.app:app", host="0.0.0.0", port=47950, log_level="info")


if __name__ == "__main__":
    main()
