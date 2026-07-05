import asyncio
from datetime import datetime, timedelta
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot
from sqlalchemy import select, func
from app.database import async_session
from app.models import User, Store, Problem, UserRole, ProblemStatus
from app.config import settings
from app.ai_summary import generate_ai_summary

scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

async def send_report(user_id: int, bot: Bot, days: int):
    """Отправляет отчет конкретному пользователю"""
    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user:
            return

        cutoff_date = datetime.now() - timedelta(days=days)
        
        base_filter = [
            Problem.created_at >= cutoff_date,
            Problem.status != ProblemStatus.RESOLVED
        ]
        
        if user.role == UserRole.SUPERVISOR:
            scope_filter = Store.cluster == user.cluster
            scope = f"кластера '{user.cluster}'"
        elif user.role == UserRole.DIRECTOR:
            scope_filter = Store.region == user.region
            scope = f"региона '{user.region}'"
        else:
            return

        count_q = select(func.count(Problem.id)).join(Store).where(*base_filter, scope_filter)
        total_count = (await session.execute(count_q)).scalar()

        prob_q = select(Problem).join(Store).where(*base_filter, scope_filter).order_by(Problem.created_at.desc()).limit(15)
        problems = (await session.execute(prob_q)).scalars().all()

        stores_map = {}
        if problems:
            store_ids = [p.store_id for p in problems]
            stores_res = await session.execute(select(Store).where(Store.id.in_(store_ids)))
            stores_map = {s.id: s.name for s in stores_res.scalars().all()}

    period = "неделю" if days == 7 else "месяц"
    status_emojis = {
        ProblemStatus.NEW: "🆕",
        ProblemStatus.IN_PROGRESS: "🔄",
        ProblemStatus.POSTPONED: "⏸"
    }

    if total_count == 0:
        text = f"🤖 <b>Автоматический отчет</b>\n\n🎉 За последнюю {period} в {scope} нет нерешенных проблем! Все задачи закрыты."
    else:
        text = f"🤖 <b>Автоматический отчет за {period}</b>\n📍 {scope}\n🔢 Нерешенных проблем: {total_count}\n\n"
                # Генерируем AI-саммари
        ai_summary = await generate_ai_summary(problems, stores_map)
        text += f"🤖 <b>AI-саммари:</b>\n{ai_summary}\n\n"
        text += "📋 <b>Список проблем:</b>\n\n"

        for p in problems:
            store_name = stores_map.get(p.store_id, "Неизвестно")
            emoji = status_emojis.get(p.status, "❓")
            status_text = p.status.value.capitalize()
            date_str = p.created_at.strftime("%d.%m %H:%M") if p.created_at else ""
            txt = p.text[:80] + "..." if len(p.text) > 80 else p.text
            text += f"• {emoji} <b>#{p.id}</b> | {store_name} | {status_text}\n  📝 {txt}\n  📅 {date_str}\n\n"

        if total_count > 15:
            text += f"⚠️ Показаны последние 15 из {total_count}."

    await bot.send_message(user_id, text, parse_mode="HTML")

async def send_weekly_reports(bot: Bot):
    """Отправляет недельные отчеты всем супервайзерам и директорам"""
    print(f"[{datetime.now()}] Отправка недельных отчетов...")
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.role.in_([UserRole.SUPERVISOR, UserRole.DIRECTOR]))
        )
        users = result.scalars().all()
    
    for user in users:
        try:
            await send_report(user.tg_id, bot, days=7)
        except Exception as e:
            print(f"Ошибка отправки отчета пользователю {user.tg_id}: {e}")

async def send_monthly_reports(bot: Bot):
    """Отправляет месячные отчеты всем супервайзерам и директорам"""
    print(f"[{datetime.now()}] Отправка месячных отчетов...")
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.role.in_([UserRole.SUPERVISOR, UserRole.DIRECTOR]))
        )
        users = result.scalars().all()
    
    for user in users:
        try:
            await send_report(user.tg_id, bot, days=30)
        except Exception as e:
            print(f"Ошибка отправки отчета пользователю {user.tg_id}: {e}")

async def send_quarterly_reminders(bot: Bot):
    """Отправляет квартальные напоминания супервайзерам и директорам"""
    print(f"[{datetime.now()}] Отправка квартальных напоминаний...")
    
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.role.in_([UserRole.SUPERVISOR, UserRole.DIRECTOR]))
        )
        managers = result.scalars().all()
        
        for m in managers:
            print(f"  - {m.tg_id}, роль: {m.role.value}, кластер: {m.cluster}, регион: {m.region}")
        
        cutoff_date = datetime.now() - timedelta(days=90)
        
        for manager in managers:
            if manager.role == UserRole.SUPERVISOR:
                scope_filter = Store.cluster == manager.cluster
                scope = f"кластера '{manager.cluster}'"
            else:
                scope_filter = Store.region == manager.region
                scope = f"региона '{manager.region}'"
                
            count_q = select(func.count(Problem.id)).join(Store).where(
                scope_filter,
                Problem.status != ProblemStatus.RESOLVED,
                Problem.created_at < cutoff_date
            )
            count = (await session.execute(count_q)).scalar()
            
            
            if count and count > 0:
                text = (
                    f"⏰ <b>Квартальное напоминание!</b>\n\n"
                    f"В {scope} есть <b>{count}</b> открытых проблем старше 3 месяцев.\n"
                    f"Пожалуйста, проверьте их статусы и актуализируйте информацию.\n\n"
                    f"Используйте кнопку «✏️ Обновить статус» в меню бота."
                )
                try:
                    await bot.send_message(manager.tg_id, text, parse_mode="HTML")
                except Exception as e:
                    print(f"Не удалось отправить напоминание юзеру {manager.tg_id}: {e}")
            else:
                pass  # У менеджера нет старых проблем


def setup_scheduler(bot: Bot):
    """Настраивает планировщик задач"""
    msk_tz = pytz.timezone("Europe/Moscow")
    
    scheduler.add_job(
        send_weekly_reports,
        trigger=CronTrigger(day_of_week=4, hour=18, minute=20, timezone=msk_tz),
        args=[bot],
        id="weekly_reports",
        name="Недельные отчеты"
    )
    
    scheduler.add_job(
        send_monthly_reports,
        trigger=CronTrigger(day=1, hour=18, minute=20, timezone=msk_tz),
        args=[bot],
        id="monthly_reports",
        name="Месячные отчеты"
    )
    
    scheduler.add_job(
        send_quarterly_reminders,
        trigger=CronTrigger(day=1, month='1,4,7,10', hour=10, minute=0, timezone=msk_tz),
        args=[bot],
        id="quarterly_reminders",
        name="Квартальные напоминания"
    )

    scheduler.start()
    print("Планировщик отчетов запущен")
    
    for job in scheduler.get_jobs():
        print(f"📅 Задача: {job.name} | Следующий запуск: {job.next_run_time}")