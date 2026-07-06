import asyncio
from app.database import engine
from app.models import Base

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Таблицы созданы!")

if __name__ == "__main__":
    asyncio.run(init_db())
