from difflib import SequenceMatcher
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func
from datetime import datetime, timedelta
from app.states import OnboardingForm, ProblemForm, AdminForm, StatusUpdateForm, FeedbackForm
from app.database import async_session
from app.models import User, Store, Problem, UserRole, ProblemStatus, Feedback
from app.config import settings
from app.ai_summary import generate_ai_summary, find_similar_problems_ai

router = Router()
last_bot_messages = {}




async def delete_user_message(message: Message):
    """Удаление сообщений пользователей не работает в личных чатах (ограничение Telegram API)."""
    pass

async def smart_send(message_or_callback, text: str, reply_markup=None, parse_mode: str = None, **kwargs):
    """Простая отправка сообщения с клавиатурой"""
    user_id = None
    chat_id = None
    bot = None
    
    if hasattr(message_or_callback, 'message'):
        user_id = message_or_callback.from_user.id
        chat_id = message_or_callback.message.chat.id
        bot = message_or_callback.bot
    elif hasattr(message_or_callback, 'chat'):
        user_id = message_or_callback.from_user.id
        chat_id = message_or_callback.chat.id
        bot = message_or_callback.bot
    else:
        return
    
    if not user_id or not chat_id or not bot:
        return
    
    # Всегда отправляем новое сообщение
    print(f"[SMART_SEND] Отправка в чат {chat_id}")
    print(f"[SMART_SEND] Text: {text[:50]}...")
    print(f"[SMART_SEND] reply_markup type: {type(reply_markup).__name__ if reply_markup else None}")
    if reply_markup and hasattr(reply_markup, 'inline_keyboard'):
        print(f"[SMART_SEND] Inline buttons count: {len(reply_markup.inline_keyboard)}")
        for row in reply_markup.inline_keyboard:
            for btn in row:
                print(f"[SMART_SEND]   Button: '{btn.text}' -> callback_data='{btn.callback_data}'")
    
    try:
        new_msg = await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode=parse_mode, **kwargs)
        if new_msg:
            last_bot_messages[user_id] = new_msg.message_id
            print(f"[SMART_SEND] ✅ Отправлено, ID: {new_msg.message_id}")
            if new_msg.reply_markup:
                print(f"[SMART_SEND] ✅ Reply markup в ответе: {type(new_msg.reply_markup).__name__}")
    except Exception as e:
        print(f"[SMART_SEND] ❌ Ошибка отправки: {e}")
        import traceback
        traceback.print_exc()

def get_nav_keyboard():
    """Нижняя клавиатура навигации (ReplyKeyboard)"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🏠 Главное меню"), KeyboardButton(text="⬅️ Назад")],
            [KeyboardButton(text="💬 Обратная связь"), KeyboardButton(text="📖 Инструкция")]
        ],
        resize_keyboard=True,
        is_persistent=True
    )

def get_role_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👷 Сотрудник магазина", callback_data="role_employee")],
        [InlineKeyboardButton(text="👔 Супервайзер", callback_data="role_supervisor")],
        [InlineKeyboardButton(text="🎯 Региональный директор", callback_data="role_director")],
        [InlineKeyboardButton(text="💬 Обратная связь", callback_data="action_feedback")],
        [InlineKeyboardButton(text="📖 Инструкция", callback_data="action_instruction")]
    ])

def get_main_menu(role: UserRole):
    buttons = []
    if role == UserRole.EMPLOYEE:
        buttons = [
            [InlineKeyboardButton(text="📝 Рассказать о проблеме", callback_data="action_problem")],
            [InlineKeyboardButton(text="📋 Мои проблемы", callback_data="action_my_problems")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main")]
        ]
    elif role == UserRole.SUPERVISOR:
        buttons = [
            [InlineKeyboardButton(text="📊 Проблемы кластера", callback_data="action_cluster_problems")],
            [InlineKeyboardButton(text="📈 Недельный отчет", callback_data="action_week_report")],
            [InlineKeyboardButton(text="📉 Месячный отчет", callback_data="action_month_report")],
            [InlineKeyboardButton(text="✏️ Обновить статус", callback_data="action_update_status")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main")]
        ]
    elif role == UserRole.DIRECTOR:
        buttons = [
            [InlineKeyboardButton(text="📊 Проблемы региона", callback_data="action_region_problems")],
            [InlineKeyboardButton(text="📈 Недельный отчет", callback_data="action_week_report")],
            [InlineKeyboardButton(text="📉 Месячный отчет", callback_data="action_month_report")],
            [InlineKeyboardButton(text="✏️ Обновить статус", callback_data="action_update_status")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main")]
        ]
    
    buttons.append([InlineKeyboardButton(text="📖 Инструкция", callback_data="action_instruction")])
    buttons.append([InlineKeyboardButton(text="💬 Обратная связь", callback_data="action_feedback")])
    buttons.append([InlineKeyboardButton(text="🔄 Сменить роль", callback_data="action_change_role")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def format_similar_info(problem, session) -> str:
    try:
        store = await session.get(Store, problem.store_id)
        user = await session.get(User, problem.user_id)
        region = user.region if user else "Неизвестно"
        cluster = user.cluster if user else "Неизвестно"
        date_str = problem.created_at.strftime("%d.%m.%Y %H:%M") if problem.created_at else ""
        comment = f"\n💬 Решение: {problem.resolution_comment}" if problem.resolution_comment else ""
        store_display = f"Магазин №{store.id}" if store and hasattr(store, 'id') else "Неизвестно"
        return (
            f"• <b>#{problem.id}</b> | {region}, {cluster}\n"
            f"📍 {store_display} | 📅 {date_str} | Статус: {problem.status.value.capitalize()}\n"
            f"📝 {problem.text[:80]}{'...' if len(problem.text)>80 else ''}{comment}\n\n"
        )
    except Exception:
        return f"• <b>#{problem.id}</b> | Ошибка отображения\n\n"

@router.message(Command("start"), State("*"))
async def cmd_start(message: Message, state: FSMContext):
    await delete_user_message(message)
    await state.clear()
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
    if user:
        await smart_send(message, f"Привет, {user.name}! Твоя роль: {get_role_name(user.role)}", reply_markup=get_main_menu(user.role))
    else:
        await smart_send(message, "🤖 <b>Привет! Я — бот Супер Кайдзен</b>\n\nДавай настроим твой профиль. Кем ты работаешь?", parse_mode="HTML", reply_markup=get_role_keyboard())




@router.message(Command("getadmin"))
async def get_admin_credentials(message: Message):
    """Секретная команда для получения доступа к админке"""
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        
        if not user or user.role not in [UserRole.SUPERVISOR, UserRole.DIRECTOR]:
            await message.answer("У вас нет доступа к этой команде.")
            return
        
        admin_url = "http://159.194.237.54/login"
        admin_password = settings.ADMIN_PASSWORD
        
        text = "🔐 Доступ к админ-панели\n\n"
        text += f"🌐 Ссылка: {admin_url}\n\n"
        text += f"👤 Логин: (оставьте пустым)\n"
        text += f"🔑 Пароль: {admin_password}\n\n"
        text += "💡 Или создайте отдельного администратора в настройках"
        
        await message.answer(text)
        print(f"[ADMIN_ACCESS] Пользователь {message.from_user.id} ({user.role.value}) запросил доступ к админке")


@router.callback_query(F.data.startswith("role_"))
async def process_role(callback: CallbackQuery, state: FSMContext):
    role_str = callback.data.split("_")[1]
    role = UserRole(role_str)
    await state.update_data(role=role)
    if role == UserRole.EMPLOYEE:
        await show_employee_region_keyboard(callback, state)
    elif role == UserRole.SUPERVISOR:
        await smart_send(callback, "Введите пароль для супервайзера:")
        await state.set_state(OnboardingForm.password)
    elif role == UserRole.DIRECTOR:
        await smart_send(callback, "Введите пароль для регионального директора:")
        await state.set_state(OnboardingForm.password)
    await callback.answer()

@router.message(OnboardingForm.password)
async def process_password(message: Message, state: FSMContext):
    await delete_user_message(message)
    data = await state.get_data()
    role = data.get('role')
    if role == UserRole.SUPERVISOR and message.text == "super1":
        await show_supervisor_region_keyboard(message, state)
    elif role == UserRole.DIRECTOR and message.text == "super2":
        await show_region_keyboard(message, state)
    else:
        await smart_send(message, "❌ Неверный пароль. Попробуйте еще раз:")

async def show_employee_region_keyboard(message_or_callback, state: FSMContext):
    try:
        async with async_session() as session:
            result = await session.execute(select(Store.region).distinct().order_by(Store.region))
            regions = result.scalars().all()
        if not regions:
            await smart_send(message_or_callback, "❌ В базе нет регионов.")
            return
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=r, callback_data=f"emp_region_{i}")] for i, r in enumerate(regions)])
        await smart_send(message_or_callback, "Выбери свой регион:", reply_markup=keyboard)
        await state.update_data(employee_regions=regions)
        await state.set_state(OnboardingForm.employee_region)
    except Exception as e:
        print(f"[ERROR] show_employee_region_keyboard: {e}")
        await smart_send(message_or_callback, f"❌ Ошибка загрузки регионов: {str(e)[:50]}")

@router.callback_query(F.data.startswith("emp_region_"))
async def process_employee_region_select(callback: CallbackQuery, state: FSMContext):
    index = int(callback.data.split("_")[2])
    data = await state.get_data()
    region = data['employee_regions'][index]
    await state.update_data(employee_region=region)
    async with async_session() as session:
        result = await session.execute(select(Store.cluster).where(Store.region == region).distinct().order_by(Store.cluster))
        clusters = result.scalars().all()
    if not clusters:
        await smart_send(callback, f"❌ В регионе '{region}' нет кластеров.")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=c, callback_data=f"emp_cluster_{i}")] for i, c in enumerate(clusters)])
    await smart_send(callback, f"Регион: {region}\n\nВыбери свой кластер:", reply_markup=keyboard)
    await state.update_data(employee_clusters=clusters)
    await state.set_state(OnboardingForm.employee_cluster)
    await callback.answer()

@router.callback_query(F.data.startswith("emp_cluster_"))
async def process_employee_cluster_select(callback: CallbackQuery, state: FSMContext):
    index = int(callback.data.split("_")[2])
    data = await state.get_data()
    cluster = data['employee_clusters'][index]
    region = data['employee_region']
    await state.update_data(employee_cluster=cluster)
    async with async_session() as session:
        result = await session.execute(select(Store).where(Store.region == region, Store.cluster == cluster).order_by(Store.id))
        stores = result.scalars().all()
    if not stores:
        await smart_send(callback, f"❌ В кластере '{cluster}' нет магазинов.")
        return
    buttons = []
    for i, store in enumerate(stores):
        btn = InlineKeyboardButton(text=f"№{store.id}", callback_data=f"emp_store_{i}")
        if not buttons or len(buttons[-1]) >= 2:
            buttons.append([btn])
        else:
            buttons[-1].append(btn)
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await smart_send(callback, f"Кластер: {cluster}. Выбери магазин:", reply_markup=keyboard)
    await state.update_data(employee_stores=[s.id for s in stores])
    await state.set_state(OnboardingForm.employee_store)
    await callback.answer()

@router.callback_query(F.data.startswith("emp_store_"))
async def process_employee_store_select(callback: CallbackQuery, state: FSMContext):
    try:
        index = int(callback.data.split("_")[2])
        data = await state.get_data()
        store_id = data['employee_stores'][index]
        cluster = data['employee_cluster']
        region = data['employee_region']
        async with async_session() as session:
            user = await session.get(User, callback.from_user.id)
            if user:
                user.role = data['role']; user.store_id = store_id; user.cluster = cluster; user.region = region
            else:
                user = User(tg_id=callback.from_user.id, name=callback.from_user.full_name or "User", role=data['role'], store_id=store_id, cluster=cluster, region=region)
                session.add(user)
            await session.commit()
        await smart_send(callback.message, f"✅ Регистрация завершена!\nРоль: Сотрудник\nРегион: {region}\nКластер: {cluster}\nМагазин: №{store_id}", reply_markup=get_main_menu(UserRole.EMPLOYEE))
        await state.clear()
    except Exception as e:
        print(f"[ERROR] process_employee_store_select: {e}")
        await smart_send(callback, f"❌ Ошибка регистрации: {str(e)[:100]}")
    await callback.answer()

async def show_supervisor_region_keyboard(message_or_callback, state: FSMContext):
    try:
        async with async_session() as session:
            result = await session.execute(select(Store.region).distinct().order_by(Store.region))
            regions = result.scalars().all()
        if not regions:
            await smart_send(message_or_callback, "❌ В базе нет регионов.")
            return
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=r, callback_data=f"sup_region_{i}")] for i, r in enumerate(regions)])
        await smart_send(message_or_callback, "Выбери свой регион:", reply_markup=keyboard)
        await state.update_data(supervisor_regions=regions)
        await state.set_state(OnboardingForm.supervisor_region)
    except Exception as e:
        print(f"[ERROR] show_supervisor_region_keyboard: {e}")
        await smart_send(message_or_callback, f"❌ Ошибка: {str(e)[:50]}")

@router.callback_query(F.data.startswith("sup_region_"))
async def process_supervisor_region_select(callback: CallbackQuery, state: FSMContext):
    index = int(callback.data.split("_")[2])
    data = await state.get_data()
    region = data.get('supervisor_regions', [])[index]
    await state.update_data(supervisor_region=region)
    async with async_session() as session:
        result = await session.execute(select(Store.cluster).where(Store.region == region).distinct().order_by(Store.cluster))
        clusters = result.scalars().all()
    if not clusters:
        await smart_send(callback, f"❌ В регионе '{region}' нет кластеров.")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=c, callback_data=f"sup_cluster_{i}")] for i, c in enumerate(clusters)])
    await smart_send(callback, f"Регион: {region}\n\nВыбери свой кластер:", reply_markup=keyboard)
    await state.update_data(supervisor_clusters=clusters)
    await state.set_state(OnboardingForm.supervisor_cluster)
    await callback.answer()

@router.callback_query(F.data.startswith("sup_cluster_"))
async def process_supervisor_cluster_select(callback: CallbackQuery, state: FSMContext):
    try:
        index = int(callback.data.split("_")[2])
        data = await state.get_data()
        cluster = data['supervisor_clusters'][index]
        region = data['supervisor_region']
        async with async_session() as session:
            user = await session.get(User, callback.from_user.id)
            if user:
                user.role = data['role']; user.cluster = cluster; user.region = region; user.store_id = None
            else:
                user = User(tg_id=callback.from_user.id, name=callback.from_user.full_name, role=data['role'], cluster=cluster, region=region)
                session.add(user)
            await session.commit()
        await smart_send(callback, f"✅ Регистрация завершена!\nРоль: Супервайзер\nРегион: {region}\nКластер: {cluster}", reply_markup=get_main_menu(UserRole.SUPERVISOR))
        await state.clear()
    except Exception as e:
        print(f"[ERROR] sup_cluster: {e}")
        await smart_send(callback, f"Ошибка: {e}")
    await callback.answer()

async def show_region_keyboard(message_or_callback, state: FSMContext):
    try:
        async with async_session() as session:
            result = await session.execute(select(Store.region).distinct().order_by(Store.region))
            regions = result.scalars().all()
        if not regions:
            await smart_send(message_or_callback, "❌ В базе нет регионов.")
            return
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=r, callback_data=f"region_{i}")] for i, r in enumerate(regions)])
        await smart_send(message_or_callback, "Выбери свой регион:", reply_markup=keyboard)
        await state.update_data(regions=regions)
        await state.set_state(OnboardingForm.region_select)
    except Exception as e:
        print(f"[ERROR] show_region_keyboard: {e}")
        await smart_send(message_or_callback, f"❌ Ошибка: {str(e)[:50]}")

@router.callback_query(F.data.startswith("region_"))
async def process_region_select(callback: CallbackQuery, state: FSMContext):
    try:
        index = int(callback.data.split("_")[1])
        data = await state.get_data()
        region = data['regions'][index]
        async with async_session() as session:
            user = await session.get(User, callback.from_user.id)
            if user:
                user.role = data['role']; user.region = region; user.cluster = None; user.store_id = None
            else:
                user = User(tg_id=callback.from_user.id, name=callback.from_user.full_name, role=data['role'], region=region)
                session.add(user)
            await session.commit()
        await smart_send(callback, f"✅ Регистрация завершена!\nРоль: Региональный директор\nРегион: {region}", reply_markup=get_main_menu(UserRole.DIRECTOR))
        await state.clear()
    except Exception as e:
        print(f"[ERROR] region: {e}")
        await smart_send(callback, f"Ошибка: {e}")
    await callback.answer()

@router.callback_query(F.data == "action_problem")
async def action_problem(callback: CallbackQuery, state: FSMContext):
    print(f"[ACTION_PROBLEM] Получен callback от {callback.from_user.id}, data={callback.data}")
    uid = callback.from_user.id
    if uid in last_bot_messages: del last_bot_messages[uid]
    await callback.bot.send_message(chat_id=callback.message.chat.id, text="✍️ Напиши текст проблемы или идеи:")
    await state.set_state(ProblemForm.text)
    await callback.answer()

@router.message(ProblemForm.text)
async def process_problem_text(message: Message, state: FSMContext):
    await delete_user_message(message)
    await state.update_data(text=message.text)
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        if not user or not user.store_id:
            await smart_send(message, "❌ Сначала привяжи себя к магазину: /start")
            await state.clear()
            return
        ai_found_similar = False
        try:
            from app.ai_summary import find_similar_problems_ai
            all_problems = (await session.execute(select(Problem))).scalars().all()
            similar_ids = await find_similar_problems_ai(message.text, all_problems, threshold=3)
            similar = [p for p in all_problems if p.id in similar_ids]
            if similar:
                info_text = "⚠️ <b>ИИ нашел похожие проблемы:</b>\n\n"
                for p in similar[:5]: info_text += await format_similar_info(p, session)
                info_text += "\n❓ Подать эту проблему?"
                uid = message.from_user.id
                if uid in last_bot_messages: del last_bot_messages[uid]
                await message.bot.send_message(chat_id=message.chat.id, text=info_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Да, подать", callback_data="confirm_dup_yes")], [InlineKeyboardButton(text="❌ Нет, отменить", callback_data="confirm_dup_no")]]))
                await state.set_state(ProblemForm.confirm_duplicate)
                ai_found_similar = True
        except Exception as e:
            print(f"[AI_CHECK] Ошибка ИИ: {e}")
        if not ai_found_similar:
            problem = Problem(user_id=user.tg_id, store_id=user.store_id, text=message.text, status=ProblemStatus.NEW)
            session.add(problem)
            await session.commit()
            await smart_send(message, f"✅ Проблема зафиксирована для магазина №{user.store_id}! Спасибо.", reply_markup=get_main_menu(user.role))
            await state.clear()

@router.callback_query(F.data == "confirm_dup_yes")
async def confirm_dup_yes(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    problem_text = data.get('text')
    if not problem_text: return
    async with async_session() as session:
        user = await session.get(User, callback.from_user.id)
        if not user or not user.store_id: return
        problem = Problem(user_id=user.tg_id, store_id=user.store_id, text=problem_text, status=ProblemStatus.NEW)
        session.add(problem)
        await session.commit()
        await smart_send(callback, f"✅ Проблема зафиксирована для магазина №{user.store_id}! Спасибо.", reply_markup=get_main_menu(user.role))
        await state.clear()
    await callback.answer()

@router.callback_query(F.data == "confirm_dup_no")
async def confirm_dup_no(callback: CallbackQuery, state: FSMContext):
    await smart_send(callback, "❌ Подача проблемы отменена.")
    await state.clear()
    await callback.answer()

@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        user = await session.get(User, callback.from_user.id)
    if user: await show_main_menu(callback, user)
    await callback.answer()



@router.callback_query(F.data == "action_cluster_problems")
async def action_cluster_problems(callback: CallbackQuery, state: FSMContext):
    async with async_session() as session:
        user = await session.get(User, callback.from_user.id)
        if not user or user.role != UserRole.SUPERVISOR:
            await smart_send(callback, "❌ У тебя нет доступа к этой функции.", reply_markup=get_nav_keyboard())
            return
        result = await session.execute(select(Problem).join(Store).where(Store.cluster == user.cluster, Problem.status != ProblemStatus.RESOLVED).order_by(Problem.created_at.desc()).limit(20))
        problems = result.scalars().all()
        if not problems:
            await smart_send(callback, "🎉 В твоем кластере нет активных проблем.", reply_markup=get_nav_keyboard())
            return
        store_ids = [p.store_id for p in problems]
        stores_res = await session.execute(select(Store).where(Store.id.in_(store_ids)))
        stores_map = {s.id: f"№{s.id}" for s in stores_res.scalars().all()}
        ai_summary = await generate_ai_summary(problems, stores_map)
        text = f"📊 Проблемы кластера '{user.cluster}':\n\n🤖 <b>AI-саммари:</b>\n{ai_summary}\n\n📋 <b>Список проблем:</b>\n\n"
        for p in problems[:10]:
            store_display = stores_map.get(p.store_id, "Неизвестно")
            text += f"• <b>#{p.id}</b>| {store_display}| {p.status.value.capitalize()}\n📝 {p.text[:80]}...\n\n"
        await smart_send(callback, text, parse_mode="HTML", reply_markup=get_nav_keyboard())
    await callback.answer()

@router.callback_query(F.data == "action_week_report")
async def action_week_report(callback: CallbackQuery, state: FSMContext):
    await generate_report(callback.from_user.id, callback, days=7)
    await callback.answer()

@router.callback_query(F.data == "action_month_report")
async def action_month_report(callback: CallbackQuery, state: FSMContext):
    await generate_report(callback.from_user.id, callback, days=30)
    await callback.answer()

@router.callback_query(F.data == "action_change_role")
async def callback_change_role(callback: CallbackQuery, state: FSMContext):
    await change_user_role(callback.from_user.id)
    await state.clear()
    await smart_send(callback, "Твоя роль сброшена. Давай настроим профиль заново.\n\nКем ты работаешь?", reply_markup=get_role_keyboard())
    await callback.answer()

@router.callback_query(F.data == "action_feedback")
async def action_feedback(callback: CallbackQuery, state: FSMContext):
    print(f"[ACTION_FEEDBACK] Получен callback от {callback.from_user.id}, data={callback.data}")
    await state.clear()
    await smart_send(callback, "💬 <b>Обратная связь</b>\n\nНапишите ваш отзыв о работе бота:", parse_mode="HTML")
    await state.set_state(FeedbackForm.text)
    await callback.answer()

@router.callback_query(F.data == "action_instruction")
async def action_instruction(callback: CallbackQuery, state: FSMContext):
    print(f"[ACTION_INSTRUCTION] Получен callback от {callback.from_user.id}, data={callback.data}")
    await smart_send(callback, "📖 Инструкция:\n1. Нажми 'Подать проблему'\n2. Опиши ситуацию\n3. ИИ предложит категорию\n4. Готово!", reply_markup=get_nav_keyboard())
    await callback.answer()

@router.callback_query(F.data == "action_my_problems")
async def action_my_problems(callback: CallbackQuery, state: FSMContext):
    print(f"[ACTION_MY_PROBLEMS] Получен callback от {callback.from_user.id}, data={callback.data}")
    async with async_session() as session:
        result = await session.execute(select(Problem).where(Problem.user_id == callback.from_user.id).order_by(Problem.created_at.desc()))
        problems = result.scalars().all()
    if not problems:
        await smart_send(callback, "📋 У тебя пока нет зафиксированных проблем.")
    else:
        text = "📋 <b>Твои проблемы:</b>\n\n"
        for p in problems[:20]:
            text += f"<b>#{p.id}</b> [{p.status.value}]\n📝 {p.text[:100]}...\n📅 {p.created_at.strftime('%d.%m.%Y') if p.created_at else ''}\n\n"
        await smart_send(callback, text, parse_mode="HTML", reply_markup=get_nav_keyboard())
    await callback.answer()

@router.callback_query(F.data == "action_update_status")
async def start_status_update(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user: return
        if user.role == UserRole.SUPERVISOR:
            result = await session.execute(select(Problem).join(Store).where(Store.cluster == user.cluster).order_by(Problem.created_at.desc()).limit(20))
            scope_name = f"кластер {user.cluster}"
        elif user.role == UserRole.DIRECTOR:
            result = await session.execute(select(Problem).join(Store).where(Store.region == user.region).order_by(Problem.created_at.desc()).limit(20))
            scope_name = f"регион {user.region}"
        else:
            await smart_send(callback, "❌ Доступ запрещен.")
            return
        problems = result.scalars().all()
        problems = [p for p in problems if p.status != ProblemStatus.RESOLVED]
        if not problems:
            await smart_send(callback, f"🎉 В вашем {scope_name} нет активных проблем.")
            return
        keyboard = []
        for p in problems:
            store = await session.get(Store, p.store_id)
            btn_text = f"#{p.id} | №{store.id if store else '?'} | {p.status.value}"
            keyboard.append([InlineKeyboardButton(text=btn_text, callback_data=f"update_prob_{p.id}")])
        await smart_send(callback, f"📋 Выберите проблему ({scope_name}):", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
        await state.set_state(StatusUpdateForm.selecting_problem)
    await callback.answer()

@router.callback_query(F.data.startswith("update_prob_"))
async def select_problem_for_update(callback: CallbackQuery, state: FSMContext):
    problem_id = int(callback.data.split("_")[2])
    async with async_session() as session:
        problem = await session.get(Problem, problem_id)
        store = await session.get(Store, problem.store_id)
        await state.update_data(problem_id=problem_id)
        statuses = [(ProblemStatus.NEW, "🆕 Новая"), (ProblemStatus.IN_PROGRESS, "🔄 В работе"), (ProblemStatus.RESOLVED, "✅ Решена"), (ProblemStatus.POSTPONED, "⏸ Отложена")]
        keyboard = [[InlineKeyboardButton(text=label, callback_data=f"update_stat_{problem_id}_{status.value}")] for status, label in statuses]
        store_display = f"№{store.id}" if store else "?"
        await smart_send(callback, f"📝 <b>Проблема #{problem_id}</b> | Магазин {store_display}\n\n<i>{problem.text[:150]}...</i>\n\nВыберите новый статус:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode="HTML")
    await state.set_state(StatusUpdateForm.selecting_status)
    await callback.answer()

@router.callback_query(F.data.startswith("update_stat_"))
async def select_new_status(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    problem_id = int(parts[2])
    status_value = parts[3]
    new_status = ProblemStatus(status_value)
    await state.update_data(problem_id=problem_id, new_status=new_status)
    if new_status in [ProblemStatus.RESOLVED, ProblemStatus.POSTPONED]:
        prompt = "✅ <b>Статус: Решена</b>\n\nКратко напишите, как решилась проблема:" if new_status == ProblemStatus.RESOLVED else "⏸ <b>Статус: Отложена</b>\n\nКратко напишите, почему проблема отложена:"
        await smart_send(callback, prompt, parse_mode="HTML")
        await state.set_state(StatusUpdateForm.entering_comment)
    else:
        async with async_session() as session:
            problem = await session.get(Problem, problem_id)
            problem.status = new_status
            await session.commit()
        await smart_send(callback, f"✅ Статус проблемы #{problem_id} обновлен на '{new_status.value.capitalize()}'")
        await state.clear()
    await callback.answer()

@router.message(StatusUpdateForm.entering_comment)
async def save_status_with_comment(message: Message, state: FSMContext):
    await delete_user_message(message)
    data = await state.get_data()
    problem_id = data["problem_id"]
    new_status = data["new_status"]
    comment = message.text
    async with async_session() as session:
        problem = await session.get(Problem, problem_id)
        problem.status = new_status
        problem.resolution_comment = comment
        await session.commit()
        user = await session.get(User, problem.user_id)
        store = await session.get(Store, problem.store_id)
    if new_status in [ProblemStatus.RESOLVED, ProblemStatus.POSTPONED] and user:
        try:
            notification = f"{'✅' if new_status == ProblemStatus.RESOLVED else '⏸'} <b>Ваша проблема {'решена' if new_status == ProblemStatus.RESOLVED else 'отложена'}</b>\n\nПроблема #{problem_id}\nМагазин: №{store.id if store else '?'}\nОписание: <i>{problem.text[:100]}...</i>\n\n💬 Комментарий:\n{comment}"
            await message.bot.send_message(user.tg_id, notification, parse_mode="HTML")
        except Exception: pass
    await smart_send(message, f"✅ Статус проблемы #{problem_id} обновлен.")
    await state.clear()

async def generate_report(user_id: int, message_or_callback, days: int):
    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user: return
        cutoff_date = datetime.now() - timedelta(days=days)
        base_filter = [Problem.created_at >= cutoff_date, Problem.status != ProblemStatus.RESOLVED]
        if user.role == UserRole.SUPERVISOR:
            scope_filter = Store.cluster == user.cluster
            scope = f"кластера '{user.cluster}'"
        elif user.role == UserRole.DIRECTOR:
            scope_filter = Store.region == user.region
            scope = f"региона '{user.region}'"
        else: return
        count_q = select(func.count(Problem.id)).join(Store).where(*base_filter, scope_filter)
        total_count = (await session.execute(count_q)).scalar()
        prob_q = select(Problem).join(Store).where(*base_filter, scope_filter).order_by(Problem.created_at.desc()).limit(15)
        problems = (await session.execute(prob_q)).scalars().all()
        stores_map = {}
        if problems:
            store_ids = [p.store_id for p in problems]
            stores_res = await session.execute(select(Store).where(Store.id.in_(store_ids)))
            stores_map = {s.id: f"№{s.id}" for s in stores_res.scalars().all()}
    period = "неделю" if days == 7 else "месяц"
    if total_count == 0:
        text = f"🤖 <b>Отчет</b>\n\n🎉 За последнюю {period} в {scope} нет нерешенных проблем!"
    else:
        ai_summary = await generate_ai_summary(problems, stores_map)
        text = f"🤖 <b>Отчет за {period}</b>\n📍 {scope}\n🔢 Нерешенных проблем: {total_count}\n\n🤖 <b>AI-саммари:</b>\n{ai_summary}\n\n📋 <b>Список проблем:</b>\n\n"
        for p in problems:
            store_display = stores_map.get(p.store_id, "Неизвестно")
            text += f"• <b>#{p.id}</b>| {store_display}| {p.status.value.capitalize()}\n📝 {p.text[:80]}...\n\n"
    await smart_send(message_or_callback, text, parse_mode="HTML")

def get_role_name(role: UserRole):
    names = {UserRole.EMPLOYEE: "Сотрудник магазина", UserRole.SUPERVISOR: "Супервайзер", UserRole.DIRECTOR: "Региональный директор"}
    return names.get(role, "Неизвестно")

async def change_user_role(tg_id: int):
    async with async_session() as session:
        user = await session.get(User, tg_id)
        if user:
            await session.delete(user)
            await session.commit()
    if tg_id in last_bot_messages: del last_bot_messages[tg_id]

async def show_main_menu(message_or_callback, user):
    text = f"👋 Привет, {user.name}!\n\nТвоя роль: <b>{get_role_name(user.role)}</b>"
    keyboard = get_main_menu(user.role)
    if hasattr(message_or_callback, 'message'):
        try: await message_or_callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        except Exception: await message_or_callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    else: await message_or_callback.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.message(FeedbackForm.text)
async def process_feedback_text(message: Message, state: FSMContext):
    """Обработка текста отзыва"""
    print(f"DEBUG: Вошли в process_feedback_text, text={message.text}")
    
    # Сохраняем текст отзыва
    await state.update_data(feedback_text=message.text)
    
    # Спрашиваем телефон
    await smart_send(
        message,
        "📱 Укажите ваш контактный телефон (или отправьте 'пропустить'):",
        parse_mode="HTML"
    )
    await state.set_state(FeedbackForm.phone)


@router.message(FeedbackForm.phone)
async def process_feedback_phone(message: Message, state: FSMContext):
    """Обработка телефона для обратной связи"""
    print(f"DEBUG: Вошли в process_feedback_phone, text={message.text}, contact={message.contact}")
    
    # Получаем данные из состояния
    data = await state.get_data()
    feedback_text = data.get('feedback_text', '')
    
    # Обрабатываем телефон
    if message.contact:
        phone = message.contact.phone_number
    elif message.text and message.text.lower() not in ['пропустить', 'skip', 'нет']:
        phone = message.text.strip()
    else:
        phone = None
    print(f"DEBUG: Телефон={phone}")
    
    # Сохраняем отзыв в базу
    async with async_session() as session:
        feedback = Feedback(
            user_id=message.from_user.id,
            text=feedback_text,
            phone=phone
        )
        session.add(feedback)
        await session.commit()
    
    # Очищаем состояние
    await state.clear()
    
    # Отправляем подтверждение
    await smart_send(
        message,
        "✅ <b>Спасибо за обратную связь!</b>\n\n"
        "Ваш отзыв отправлен администраторам.\n"
        "Мы обязательно его рассмотрим.",
        parse_mode="HTML",
        reply_markup=get_nav_keyboard()
    )


# Обработчики кнопок нижней клавиатуры
@router.callback_query(F.data == "nav_back")
async def callback_nav_back(callback: CallbackQuery, state: FSMContext):
    print(f"[NAV_BACK] Получен callback от {callback.from_user.id}, data={callback.data}")
    print(f"[NAV_BACK] Получен callback от {callback.from_user.id}")
    await state.clear()
    async with async_session() as session:
        user = await session.get(User, callback.from_user.id)
    if user:
        await callback.message.edit_text(
            f"Привет, {user.name}! Твоя роль: {get_role_name(user.role)}", 
            parse_mode="HTML", 
            reply_markup=get_main_menu(user.role)
        )
    else:
        await callback.message.edit_text(
            "Сначала пройди регистрацию: /start", 
            reply_markup=get_nav_keyboard()
        )
    await callback.answer()

@router.callback_query(F.data == "nav_main")
async def callback_nav_main(callback: CallbackQuery, state: FSMContext):
    print(f"[NAV_MAIN] Получен callback от {callback.from_user.id}, data={callback.data}")
    print(f"[NAV_MAIN] Получен callback от {callback.from_user.id}")
    await state.clear()
    async with async_session() as session:
        user = await session.get(User, callback.from_user.id)
    if user:
        await callback.message.edit_text(
            f"Привет, {user.name}! Твоя роль: {get_role_name(user.role)}", 
            parse_mode="HTML", 
            reply_markup=get_main_menu(user.role)
        )
    else:
        await callback.message.edit_text(
            "Сначала пройди регистрацию: /start", 
            reply_markup=get_nav_keyboard()
        )
    await callback.answer()

@router.callback_query(F.data == "nav_feedback")
async def callback_nav_feedback(callback: CallbackQuery, state: FSMContext):
    print(f"[NAV_FEEDBACK] Получен callback от {callback.from_user.id}, data={callback.data}")
    print(f"[NAV_FEEDBACK] Получен callback от {callback.from_user.id}")
    await state.clear()
    await callback.message.edit_text(
        "💬 <b>Обратная связь</b>\n\nНапишите ваш отзыв о работе бота:", 
        parse_mode="HTML"
    )
    await state.set_state(FeedbackForm.text)
    await callback.answer()

@router.callback_query(F.data == "nav_instruction")
async def callback_nav_instruction(callback: CallbackQuery, state: FSMContext):
    print(f"[NAV_INSTRUCTION] Получен callback от {callback.from_user.id}, data={callback.data}")
    print(f"[NAV_INSTRUCTION] Получен callback от {callback.from_user.id}")
    await callback.message.edit_text(
        "📖 Инструкция:\n1. Нажми 'Подать проблему'\n2. Опиши ситуацию\n3. ИИ предложит категорию\n4. Готово!", 
        reply_markup=get_nav_keyboard()
    )
    await callback.answer()


# === Обработчики нижней клавиатуры (ReplyKeyboard) ===
@router.message(F.text == "🏠 Главное меню")
async def nav_main_menu(message: Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
    if user:
        await show_main_menu(message, user)
    else:
        await smart_send(message, "Сначала пройди регистрацию: /start", reply_markup=get_nav_keyboard())


@router.message(F.text == "⬅️ Назад")
async def nav_back(message: Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
    if user:
        await show_main_menu(message, user)
    else:
        await smart_send(message, "Сначала пройди регистрацию: /start", reply_markup=get_nav_keyboard())


@router.message(F.text == "💬 Обратная связь")
async def nav_feedback_text(message: Message, state: FSMContext):
    await state.clear()
    await smart_send(message, "💬 <b>Обратная связь</b>\n\nНапишите ваш отзыв о работе бота:", parse_mode="HTML", reply_markup=get_nav_keyboard())
    await state.set_state(FeedbackForm.text)


@router.message(F.text == "📖 Инструкция")
async def nav_instruction_text(message: Message, state: FSMContext):
    await state.clear()
    await smart_send(
        message,
        "📖 <b>Инструкция:</b>\n\n"
        "1. Нажми '📝 Рассказать о проблеме'\n"
        "2. Опиши ситуацию\n"
        "3. ИИ предложит категорию\n"
        "4. Подтверди и готово!\n\n"
        "💬 Для обратной связи нажми '💬 Обратная связь'",
        parse_mode="HTML",
        reply_markup=get_nav_keyboard()
    )


@router.message(F.text)
async def handle_any_message(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state: return
    
    # Игнорируем кнопки нижнего меню
    menu_buttons = ["⬅️ Назад", "🏠 Главное меню", "💬 Обратная связь", "📖 Инструкция"]
    if message.text in menu_buttons:
        return
    
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
    if user and user.store_id:
        problem = Problem(user_id=user.tg_id, store_id=user.store_id, text=message.text, status=ProblemStatus.NEW)
        async with async_session() as s2:
            s2.add(problem)
            await s2.commit()
        await smart_send(message, "✅ Проблема зафиксирована! Спасибо.", reply_markup=get_nav_keyboard())
    else:
        await smart_send(message, "Сначала пройди регистрацию: /start", reply_markup=get_nav_keyboard())
