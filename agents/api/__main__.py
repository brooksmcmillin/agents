"""Entry point: ``uv run python -m agents.api``."""

import uvicorn
from dotenv import load_dotenv

load_dotenv()

from .server import app  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
