import asyncio
from aiogram import Bot, Dispatcher
from app.config import settings
from app.bot import router
from app.scheduler import setup_scheduler

async def main():
    bot = Bot(token=settings.BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Запускаем планировщик отчетов
    setup_scheduler(bot)
    
    print("Бот запущен в режиме Long Polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())