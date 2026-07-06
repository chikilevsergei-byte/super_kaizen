import asyncio
import uvicorn
from app.bot import dp, bot
from app.scheduler import start_scheduler
from app.web.main import app as web_app

async def main():
    # Запускаем планировщик
    start_scheduler()
    
    # Запускаем бота и веб-сервер параллельно
    await asyncio.gather(
        dp.start_polling(bot),
        uvicorn.run(web_app, host="0.0.0.0", port=8000)
    )

if __name__ == "__main__":
    asyncio.run(main())
