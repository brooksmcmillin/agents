"""Entry point for `python -m tests.evaluations`."""

from .runner import _main

if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
