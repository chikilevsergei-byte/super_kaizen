import asyncio
from sqlalchemy import select
from app.database import async_session
from app.models import Store

TEST_STORES = [
    Store(name="Магазин №1 Север", cluster="Север", region="Москва"),
    Store(name="Магазин №2 Север", cluster="Север", region="Москва"),
    Store(name="Магазин №3 Север", cluster="Север", region="Санкт-Петербург"),
    Store(name="Магазин №1 Юг", cluster="Юг", region="Москва"),
    Store(name="Магазин №2 Юг", cluster="Юг", region="Казань"),
    Store(name="Магазин №1 Центр", cluster="Центр", region="Москва"),
    Store(name="Магазин №2 Центр", cluster="Центр", region="Санкт-Петербург"),
    Store(name="Магазин №1 Запад", cluster="Запад", region="Санкт-Петербург"),
    Store(name="Магазин №2 Запад", cluster="Запад", region="Калининград"),
    Store(name="Магазин №1 Восток", cluster="Восток", region="Екатеринбург"),
    Store(name="Магазин №2 Восток", cluster="Восток", region="Новосибирск"),
]

async def seed():
    async with async_session() as session:
        existing = await session.execute(select(Store))
        if existing.scalars().first():
            print("⚠️ Магазины уже существуют")
            return
        
        for store in TEST_STORES:
            session.add(store)
        await session.commit()
        print(f"✅ Добавлено {len(TEST_STORES)} магазинов")

if __name__ == "__main__":
    asyncio.run(seed())
