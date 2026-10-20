"""Create the required MongoDB indexes.

Usage:
    python -m backend.init_db
"""

from __future__ import annotations

import asyncio

from pymongo.asynchronous.mongo_client import AsyncMongoClient

from .config import get_settings
from .database import create_indexes


async def main() -> None:
    settings = get_settings()
    client = AsyncMongoClient(settings.mongodb_uri, tz_aware=True)
    try:
        await create_indexes(client[settings.mongodb_db])
        print(f"indexes ensured in database {settings.mongodb_db!r}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
