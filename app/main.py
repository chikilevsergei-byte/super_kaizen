import asyncio
import signal
import uvicorn
from aiogram import Bot, Dispatcher
from app.config import settings
from app.bot import router
from app.scheduler import setup_scheduler
from app.web.main import app as web_app

async def on_shutdown(bot: Bot):
    await bot.session.close()

async def main():
    bot = Bot(token=settings.BOT_TOKEN)
    dp = Dispatcher()
    
    dp.include_router(router)
    
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Запускаем планировщик отчетов
    setup_scheduler(bot)
    
    # Обработка сигналов для graceful shutdown
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(on_shutdown(bot)))
    
    # Запускаем бота и веб-сервер параллельно
    await asyncio.gather(
        dp.start_polling(bot),
        uvicorn.run(web_app, host="0.0.0.0", port=8000)
    )

if __name__ == "__main__":
    asyncio.run(main())
