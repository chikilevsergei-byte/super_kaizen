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
    
    # Создаем uvicorn сервер
    config = uvicorn.Config(web_app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)
    
    # Обработка сигналов для graceful shutdown
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown(bot, server)))
    
    # Запускаем бота и веб-сервер параллельно
    print("🤖 Бот запущен в режиме Long Polling...")
    print("🌐 Веб-админка запущена на http://0.0.0.0:8000")
    
    await asyncio.gather(
        dp.start_polling(bot),
        server.serve()
    )

async def shutdown(bot: Bot, server: uvicorn.Server):
    print("\n🛑 Завершение работы...")
    server.should_exit = True
    await on_shutdown(bot)

if __name__ == "__main__":
    asyncio.run(main())
