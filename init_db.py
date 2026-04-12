import asyncio
from app.db.session import engine
from app.db import models


async def init():
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    print("테이블 생성 완료")


asyncio.run(init())
