from difflib import SequenceMatcher
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
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

# Глобальное хранилище ID последних сообщений для edit_text
last_bot_messages = {}
from aiogram.exceptions import TelegramBadRequest

async def delete_user_message(message: Message):
    """Удаляет сообщение пользователя из чата."""
    try:
        await message.delete()
        print(f"🗑️ Удалено сообщение пользователя {message.from_user.id}")
    except Exception as e:
        print(f"⚠️ Не удалось удалить сообщение пользователя: {e}")

async def delete_user_message(message: Message):
    """Удаляет сообщение пользователя из чата."""
    try:
        await message.delete()
        print(f"🗑️ Удалено сообщение пользователя {message.from_user.id}")
    except Exception as e:
        print(f"⚠️ Не удалось удалить сообщение пользователя: {e}")

async def smart_send(message_or_callback, text: str, reply_markup=None, parse_mode: str = None, add_keyboard: bool = True, **kwargs):
    """
    Умная отправка сообщений: обновляет текущее или создаёт новое.
    Reply-клавиатуру отправляем только при первом сообщении.
    Inline-клавиатуру передаём и при создании, и при редактировании.
    ВСЕГДА обновляем last_bot_messages на ID последнего сообщения.
    """
    # Определяем user_id и chat_id
    user_id = None
    chat_id = None
    bot = None
    
    # Определяем тип объекта
    if hasattr(message_or_callback, 'message'):
        # Это CallbackQuery
        user_id = message_or_callback.from_user.id
        chat_id = message_or_callback.message.chat.id
        bot = message_or_callback.bot
    elif hasattr(message_or_callback, 'chat'):
        # Это Message
        user_id = message_or_callback.from_user.id
        chat_id = message_or_callback.chat.id
        bot = message_or_callback.bot
    else:
        print("⚠️ smart_send: неизвестный тип объекта")
        return
    
    if not user_id or not chat_id or not bot:
        print("⚠️ smart_send: не удалось определить user_id, chat_id или bot")
        return
    
    # Если это первое сообщение пользователя - отправляем с reply-клавиатурой
    if user_id not in last_bot_messages:
        # Отправляем reply-клавиатуру один раз
        await bot.send_message(
            chat_id=chat_id,
            text="⌨️",
            reply_markup=get_nav_keyboard()
        )
        
        # Отправляем основное сообщение С inline-клавиатурой
        new_msg = await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup if not isinstance(reply_markup, ReplyKeyboardMarkup) else None,
            parse_mode=parse_mode,
            **kwargs
        )
        
        if new_msg:
            last_bot_messages[user_id] = new_msg.message_id
            print(f"✅ Создано первое сообщение {new_msg.message_id} для пользователя {user_id}")
        return
    
    # Для последующих сообщений - пытаемся отредактировать ПОСЛЕДНЕЕ сообщение
    msg_id = last_bot_messages[user_id]
    
    # Передаём inline-клавиатуру при редактировании
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=text,
            reply_markup=reply_markup if not isinstance(reply_markup, ReplyKeyboardMarkup) else None,
            parse_mode=parse_mode,
            **kwargs
        )
        print(f"✅ Отредактировано сообщение {msg_id} для пользователя {user_id}")
        # last_bot_messages[user_id] остаётся тем же - это последнее сообщение
        return
    except TelegramBadRequest as e:
        error_msg = str(e).lower()
        # Если сообщение не изменилось - это нормально
        if "not modified" in error_msg:
            print(f"ℹ️ Сообщение {msg_id} уже содержит нужный контент для пользователя {user_id}")
            return
        # Если сообщение нельзя редактировать (например, старое) - создаём новое
        print(f"⚠️ Не удалось отредактировать {msg_id}: {e}, создаём новое")
    
    # Создаём новое сообщение С inline-клавиатурой
    new_msg = await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup if not isinstance(reply_markup, ReplyKeyboardMarkup) else None,
        parse_mode=parse_mode,
        **kwargs
    )
    
    # ВАЖНО: обновляем last_bot_messages на ID нового сообщения
    if new_msg:
        last_bot_messages[user_id] = new_msg.message_id
        print(f"✅ Создано новое сообщение {new_msg.message_id} для пользователя {user_id} (обновлён last_bot_messages)")

def get_nav_keyboard():
    """Постоянная клавиатура с 4 кнопками внизу."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⬅️ Назад"), KeyboardButton(text="🏠 Главное меню")],
            [KeyboardButton(text="💬 Обратная связь"), KeyboardButton(text="📖 Инструкция")]
        ],
        resize_keyboard=True,
        is_persistent=True
    )

# Алиас для обратной совместимости
def get_bottom_keyboard():
    return get_nav_keyboard()

async def safe_edit_or_send(message, text: str, parse_mode: str = None, reply_markup=None):
    """Пытается отредактировать сообщение, если не вышло — отправляет новое."""
    try:
        await message.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message to edit not found" in str(e).lower() or "not modified" in str(e).lower():
            # Если сообщение нельзя редактировать, отправляем новое
            await smart_send(message, text, parse_mode=parse_mode, reply_markup=reply_markup)
        else:
            # Другие ошибки тоже обрабатываем как новое сообщение
            await smart_send(message, text, parse_mode=parse_mode, reply_markup=reply_markup)
    except Exception:
        await smart_send(message, text, parse_mode=parse_mode, reply_markup=reply_markup)



# Клавиатуры
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
    
    if role in [UserRole.SUPERVISOR, UserRole.DIRECTOR]:
        buttons.append([InlineKeyboardButton(text="🎓 Материалы по кайдзен", url="https://example.com/kaizen")])
    
    buttons.append([InlineKeyboardButton(text="💬 Обратная связь", callback_data="action_feedback")])
    buttons.append([InlineKeyboardButton(text="🔄 Сменить роль", callback_data="action_change_role")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# Команды


async def format_similar_info(problem, session) -> str:
    """Форматирует информацию о похожей проблеме для отображения сотруднику."""
    store = await session.get(Store, problem.store_id)
    user = await session.get(User, problem.user_id)
    region = user.region if user else "Неизвестно"
    cluster = user.cluster if user else "Неизвестно"
    date_str = problem.created_at.strftime("%d.%m.%Y %H:%M") if problem.created_at else ""
    comment = f"\n💬 Решение: {problem.resolution_comment}" if problem.resolution_comment else ""
    return (
        f"• <b>#{problem.id}</b> | {region}, {cluster}\n"
        f"📍 {store.name if store else 'Неизвестно'} | 📅 {date_str} | Статус: {problem.status.value.capitalize()}\n"
        f"📝 {problem.text[:80]}{'...' if len(problem.text)>80 else ''}{comment}\n\n"
    )

@router.message(Command("start"), State("*"))
async def cmd_start(message: Message, state: FSMContext):
    await delete_user_message(message)  # Удаляем команду /start
    await state.clear()
    
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
    
    # Отправляем reply-клавиатуру при старте
    await smart_send(message, "⌨️", reply_markup=get_nav_keyboard())
    
    if user:
        await smart_send(message,
            f"Привет, {user.name}! Твоя роль: {get_role_name(user.role)}",
            reply_markup=get_main_menu(user.role)
        )
    else:
        await smart_send(message,
            "🤖 <b>Привет! Я — бот Супер Кайдзен с ИИ ассистентом 🤖</b>\n\n"
            "Это умная замена привычной доске проблем. Вместо того чтобы заполнять таблицы, просто опиши проблему — я сделаю остальное:\n\n"
            "🔍 Найду похожие случаи через ИИ\n"
            "📋 Автоматически определю категорию\n"
            "📊 Подготовлю краткое резюме для руководства\n\n"
            "Давай настроим твой профиль. Кем ты работаешь?",
            parse_mode="HTML",
            reply_markup=get_role_keyboard()
        )

@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
    
    if user:
        await smart_send(message, "Главное меню:", reply_markup=get_main_menu(user.role))
    else:
        await smart_send(message, "Сначала пройди регистрацию: /start", reply_markup=get_bottom_keyboard())

@router.message(Command("change_role"))
async def cmd_change_role(message: Message, state: FSMContext):
    await change_user_role(message.from_user.id)
    await state.clear()
    await smart_send(message, 
        "🤖 <b>Бот «Супер Кайдзен с ИИ ассистентом с ИИ»</b>\n\n"
        "Бот для фиксации проблем магазинов: Сотрудники фиксируют проблемы, искусственный интеллект их обрабатывает, руководители анализируют и решают их\n\n"
        "Выберите вашу роль:",
        parse_mode="HTML",
        reply_markup=get_role_keyboard()
    )

# Callback для выбора роли
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
    await delete_user_message(message)  # Удаляем пароль из чата
    data = await state.get_data()
    role = data['role']
    
    if role == UserRole.SUPERVISOR and message.text == "super1":
        await show_supervisor_region_keyboard(message, state)
    elif role == UserRole.DIRECTOR and message.text == "super2":
        await show_region_keyboard(message, state)
    else:
        await smart_send(message, "❌ Неверный пароль. Попробуйте еще раз:")
        return

# Регистрация сотрудника
async def show_employee_region_keyboard(message_or_callback, state: FSMContext):
    async with async_session() as session:
        result = await session.execute(
            select(Store.region).distinct().order_by(Store.region)
        )
        regions = result.scalars().all()
    
    if not regions:
        await smart_send(message_or_callback, "❌ В базе нет регионов. Обратись к администратору.")
        await state.clear()
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=region, callback_data=f"emp_region_{i}")]
        for i, region in enumerate(regions)
    ])
    
    await smart_send(message_or_callback, "Выбери свой регион:", reply_markup=keyboard)
    await state.update_data(employee_regions=regions)
    await state.set_state(OnboardingForm.employee_region)

@router.callback_query(F.data.startswith("emp_region_"))
async def process_employee_region_select(callback: CallbackQuery, state: FSMContext):
    index = int(callback.data.split("_")[2])
    data = await state.get_data()
    region = data['employee_regions'][index]
    
    await state.update_data(employee_region=region)
    
    async with async_session() as session:
        result = await session.execute(
            select(Store.cluster)
            .where(Store.region == region)
            .distinct()
            .order_by(Store.cluster)
        )
        clusters = result.scalars().all()
    
    if not clusters:
        await smart_send(callback, f"❌ В регионе '{region}' нет кластеров.")
        await state.clear()
        await callback.answer()
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=cluster, callback_data=f"emp_cluster_{i}")]
        for i, cluster in enumerate(clusters)
    ])
    
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
        result = await session.execute(
            select(Store)
            .where(Store.region == region, Store.cluster == cluster)
            .order_by(Store.name)
        )
        stores = result.scalars().all()
    
    if not stores:
        await smart_send(callback, f"❌ В кластере '{cluster}' нет магазинов.")
        await state.clear()
        await callback.answer()
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=store.name, callback_data=f"emp_store_{i}")]
        for i, store in enumerate(stores)
    ])
    
    await smart_send(callback, f"Кластер: {cluster}\n\nВыбери свой магазин:", reply_markup=keyboard)
    await state.update_data(employee_stores=[s.id for s in stores], employee_stores_names=[s.name for s in stores])
    await state.set_state(OnboardingForm.employee_store)
    await callback.answer()

@router.callback_query(F.data.startswith("emp_store_"))
async def process_employee_store_select(callback: CallbackQuery, state: FSMContext):
    index = int(callback.data.split("_")[2])
    data = await state.get_data()
    
    store_id = data['employee_stores'][index]
    store_name = data['employee_stores_names'][index]
    cluster = data['employee_cluster']
    region = data['employee_region']
    
    async with async_session() as session:
        user = await session.get(User, callback.from_user.id)
        if user:
            user.role = data['role']
            user.store_id = store_id
            user.cluster = cluster
            user.region = region
        else:
            user = User(
                tg_id=callback.from_user.id,
                name=callback.from_user.full_name,
                role=data['role'],
                store_id=store_id,
                cluster=cluster,
                region=region
            )
            session.add(user)
        await session.commit()
    
    await safe_edit_message(
        callback.message,
        f"✅ Регистрация завершена!\n"
        f"Роль: Сотрудник\n"
        f"Регион: {region}\n"
        f"Кластер: {cluster}\n"
        f"Магазин: {store_name}",
        reply_markup=get_main_menu(UserRole.EMPLOYEE)
    )
    await state.clear()
    await callback.answer()

# Регистрация супервайзера
async def show_supervisor_region_keyboard(message_or_callback, state: FSMContext):
    async with async_session() as session:
        result = await session.execute(
            select(Store.region).distinct().order_by(Store.region)
        )
        regions = result.scalars().all()
    
    if not regions:
        await smart_send(message_or_callback, "❌ В базе нет ни одного региона. Обратись к администратору.")
        await state.clear()
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=region, callback_data=f"sup_region_{i}")]
        for i, region in enumerate(regions)
    ])
    
    await smart_send(message_or_callback, "Выбери свой регион:", reply_markup=keyboard)
    await state.update_data(supervisor_regions=regions)
    await state.set_state(OnboardingForm.supervisor_region)

@router.callback_query(F.data.startswith("sup_region_"))
async def process_supervisor_region_select(callback: CallbackQuery, state: FSMContext):
    
    index = int(callback.data.split("_")[2])
    data = await state.get_data()
    region = data.get('supervisor_regions', [])[index]
    
    await state.update_data(supervisor_region=region)
    
    async with async_session() as session:
        result = await session.execute(
            select(Store.cluster)
            .where(Store.region == region)
            .distinct()
            .order_by(Store.cluster)
        )
        clusters = result.scalars().all()
    
    if not clusters:
        await smart_send(callback, f"❌ В регионе '{region}' нет кластеров.")
        await state.clear()
        await callback.answer()
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=cluster, callback_data=f"sup_cluster_{i}")]
        for i, cluster in enumerate(clusters)
    ])
    
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
                user.role = data['role']
                user.cluster = cluster
                user.region = region
                user.store_id = None
            else:
                user = User(
                    tg_id=callback.from_user.id,
                    name=callback.from_user.full_name,
                    role=data['role'],
                    cluster=cluster,
                    region=region
                )
                session.add(user)
            await session.commit()
        
        await smart_send(callback, 
            f"✅ Регистрация завершена!\n"
            f"Роль: Супервайзер\n"
            f"Регион: {region}\n"
            f"Кластер: {cluster}",
            reply_markup=get_main_menu(UserRole.SUPERVISOR)
        )
        await state.clear()
    except Exception as e:
        print(f"ERROR in sup_cluster: {e}")
        await smart_send(callback, f"Ошибка: {e}")
    
    await callback.answer()

# Регистрация директора
async def show_region_keyboard(message_or_callback, state: FSMContext):
    async with async_session() as session:
        result = await session.execute(
            select(Store.region).distinct().order_by(Store.region)
        )
        regions = result.scalars().all()
    
    if not regions:
        await smart_send(message_or_callback, "❌ В базе нет ни одного региона. Обратись к администратору.")
        await state.clear()
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=region, callback_data=f"region_{i}")]
        for i, region in enumerate(regions)
    ])
    
    await smart_send(message_or_callback, "Выбери свой регион:", reply_markup=keyboard)
    await state.update_data(regions=regions)
    await state.set_state(OnboardingForm.region_select)

@router.callback_query(F.data.startswith("region_"))
async def process_region_select(callback: CallbackQuery, state: FSMContext):
    try:
        index = int(callback.data.split("_")[1])
        data = await state.get_data()
        region = data['regions'][index]
        
        async with async_session() as session:
            user = await session.get(User, callback.from_user.id)
            if user:
                user.role = data['role']
                user.region = region
                user.cluster = None
                user.store_id = None
            else:
                user = User(
                    tg_id=callback.from_user.id,
                    name=callback.from_user.full_name,
                    role=data['role'],
                    region=region
                )
                session.add(user)
            await session.commit()
        
        await smart_send(callback, 
            f"✅ Регистрация завершена!\n"
            f"Роль: Региональный директор\n"
            f"Регион: {region}",
            reply_markup=get_main_menu(UserRole.DIRECTOR)
        )
        await state.clear()
    except Exception as e:
        print(f"ERROR in region: {e}")
        await smart_send(callback, f"Ошибка: {e}")
    
    await callback.answer()

# Callback для действий
@router.callback_query(F.data == "action_problem")
async def action_problem(callback: CallbackQuery, state: FSMContext):
    await smart_send(callback, "Напиши текст проблемы или идеи:")
    await state.set_state(ProblemForm.text)
    await callback.answer()

@router.callback_query(F.data == "action_cluster_problems")
async def action_cluster_problems(callback: CallbackQuery, state: FSMContext):
    async with async_session() as session:
        user = await session.get(User, callback.from_user.id)
        
        if not user or user.role != UserRole.SUPERVISOR:
            await smart_send(callback, "❌ У тебя нет доступа к этой функции.", reply_markup=get_bottom_keyboard())
            await callback.answer()
            return
        
        result = await session.execute(
            select(Problem)
            .join(Store)
            .where(
                Store.cluster == user.cluster,
                Problem.status != ProblemStatus.RESOLVED
            )
            .order_by(Problem.created_at.desc())
            .limit(20)
        )
        problems = result.scalars().all()
        
        if not problems:
            await smart_send(callback, "🎉 В твоем кластере нет активных проблем. Все задачи закрыты!", reply_markup=get_bottom_keyboard())
        else:
            # Формируем stores_map
            store_ids = [p.store_id for p in problems]
            stores_res = await session.execute(select(Store).where(Store.id.in_(store_ids)))
            stores_map = {s.id: s.name for s in stores_res.scalars().all()}
            
            # Генерируем AI-саммари
            ai_summary = await generate_ai_summary(problems, stores_map)
            
            text = f"📊 Проблемы кластера '{user.cluster}':\n\n"
            text += f"🤖 <b>AI-саммари:</b>\n{ai_summary}\n\n"
            text += "📋 <b>Список проблем:</b>\n\n"
            
            # Загружаем все проблемы для поиска похожих
            all_problems_q = select(Problem).order_by(Problem.created_at.desc()).limit(200)
            all_problems = (await session.execute(all_problems_q)).scalars().all()
            
            status_emojis = {
                ProblemStatus.NEW: "🆕",
                ProblemStatus.IN_PROGRESS: "🔄",
                ProblemStatus.POSTPONED: "⏸"
            }
            
            for p in problems[:10]:
                store_name = stores_map.get(p.store_id, "Неизвестно")
                emoji = status_emojis.get(p.status, "❓")
                status_text = p.status.value.capitalize()
                date_str = p.created_at.strftime("%d.%m %H:%M") if p.created_at else ""
                txt = p.text[:80] + "..." if len(p.text) > 80 else p.text
                text += f"• {emoji} <b>#{p.id}</b>| {store_name}| {status_text}\n📝 {txt}\n📅 {date_str}\n"
                
                # Ищем похожие проблемы через ИИ
                try:
                    similar_ids = await find_similar_problems_ai(p.text, [s for s in all_problems if s.id != p.id], threshold=1)
                    if similar_ids:
                        similar_problem = next((s for s in all_problems if s.id == similar_ids[0]), None)
                        if similar_problem:
                            text += f"🔍 <b>Похожая проблема:</b>\n{await format_similar_info(similar_problem, session)}\n"
                except Exception as e:
                    print(f"⚠️ Ошибка поиска похожих для проблемы #{p.id}: {e}")
                
                text += "\n"
            
            await smart_send(callback, text, parse_mode="HTML", reply_markup=get_nav_keyboard())
            
    await callback.answer()

@router.callback_query(F.data == "action_region_problems")
async def action_region_problems(callback: CallbackQuery, state: FSMContext):
    async with async_session() as session:
        user = await session.get(User, callback.from_user.id)
        
        if not user or user.role != UserRole.DIRECTOR:
            await smart_send(callback, "❌ У тебя нет доступа к этой функции.", reply_markup=get_bottom_keyboard())
            await callback.answer()
            return
        
        result = await session.execute(
            select(Problem)
            .join(Store)
            .where(
                Store.region == user.region,
                Problem.status != ProblemStatus.RESOLVED
            )
            .order_by(Problem.created_at.desc())
            .limit(20)
        )
        problems = result.scalars().all()
    
    if not problems:
        await smart_send(callback, "🎉 В твоем регионе нет активных проблем. Все задачи закрыты!", reply_markup=get_bottom_keyboard())
    else:
        # Формируем stores_map
        async with async_session() as session2:
            store_ids = [p.store_id for p in problems]
            stores_res = await session2.execute(select(Store).where(Store.id.in_(store_ids)))
            stores_map = {s.id: s.name for s in stores_res.scalars().all()}
        
        # Генерируем AI-саммари
        ai_summary = await generate_ai_summary(problems, stores_map)
        
        text = f"📊 Проблемы региона '{user.region}':\n\n"
        text += f"🤖 <b>AI-саммари:</b>\n{ai_summary}\n\n"
        text += "📋 <b>Список проблем:</b>\n\n"
        
        # Загружаем все проблемы для поиска похожих
        all_problems_q = select(Problem).order_by(Problem.created_at.desc()).limit(200)
        all_problems = (await session.execute(all_problems_q)).scalars().all()
        
        for p in problems[:10]:
            store = await session.get(Store, p.store_id)
            status_names = {
                ProblemStatus.NEW: "Новая",
                ProblemStatus.IN_PROGRESS: "В работе",
                ProblemStatus.POSTPONED: "Отложена"
            }
            status_text = status_names.get(p.status, p.status.value)
            text += f"• [{status_text}] {store.name}: {p.text[:50]}{'...' if len(p.text) > 50 else ''}"
            
            # Ищем похожие проблемы через ИИ
            try:
                similar_ids = await find_similar_problems_ai(p.text, [s for s in all_problems if s.id != p.id], threshold=1)
                if similar_ids:
                    similar_problem = next((s for s in all_problems if s.id == similar_ids[0]), None)
                    if similar_problem:
                        text += "\n" + await format_similar_info(similar_problem, session)
            except Exception as e:
                print(f"⚠️ Ошибка поиска похожих для проблемы #{p.id}: {e}")
            
            text += "\n"
        
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
    await smart_send(callback, 
        "Твоя роль сброшена. Давай настроим профиль заново.\n\n"
        "Кем ты работаешь?",
        reply_markup=get_role_keyboard()
    )
    await callback.answer()

# Обработка текста проблемы


# ===== Вспомогательные функции для поиска похожих проблем =====
def find_similar_problems(text: str, all_problems: list, threshold: float = 0.5) -> list:
    similar = []
    for p in all_problems:
        if SequenceMatcher(None, text.lower(), p.text.lower()).ratio() > 0.6:
            similar.append(p)
    return similar


async def get_similar_info_text(problem, all_problems: list, session) -> str:
    similar = find_similar_problems(problem.text, [p for p in all_problems if p.id != problem.id])
    if not similar:
        return ""
    
    info = "\n⚠️ <b>Похожие проблемы:</b>\n"
    for p in similar[:3]:
        store = await session.get(Store, p.store_id)
        store_name = store.name if store else "Неизвестно"
        user = await session.get(User, p.user_id)
        region = user.region if user else "Неизвестно"
        cluster = user.cluster if user else "Неизвестно"
        
        date_str = p.created_at.strftime("%d.%m.%Y") if p.created_at else ""
        info += f"• #{p.id} ({p.status.value}) | {store_name} | {region}, {cluster} | {date_str}\n"
        if p.resolution_comment:
            info += f"  💬 {p.resolution_comment}\n"
    return info
# =================================================================


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
        
        all_problems = (await session.execute(select(Problem))).scalars().all()
        
        # Используем ИИ для поиска похожих проблем по смыслу
        similar_ids = await find_similar_problems_ai(message.text, all_problems, threshold=3)
        similar = [p for p in all_problems if p.id in similar_ids]

        if similar:
            info_text = "⚠️ <b>ИИ проанализировал и нашел похожие проблемы, о которых сообщали ранее:</b>\n\n"
            for p in similar[:5]:
                info_text += await format_similar_info(p, session)
            info_text += "❓ Вы всё ещё хотите подать эту проблему?"
            await smart_send(message, info_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Да, подать", callback_data="confirm_dup_yes")],
                [InlineKeyboardButton(text="❌ Нет, отменить", callback_data="confirm_dup_no")]
            ]))
            await state.set_state(ProblemForm.confirm_duplicate)
        else:
            # Сохраняем проблему сразу с магазином пользователя
            problem = Problem(
                user_id=user.tg_id,
                store_id=user.store_id,
                text=message.text,
                status=ProblemStatus.NEW
            )
            session.add(problem)
            await session.commit()
            
            store = await session.get(Store, user.store_id)
            store_name = store.name if store else "Неизвестно"
            
            await smart_send(message, 
                f"✅ Проблема зафиксирована для магазина '{store_name}'! Спасибо.",
                reply_markup=get_main_menu(user.role)
            )
            await state.clear()



@router.callback_query(F.data == "confirm_dup_yes")
async def confirm_dup_yes(callback: CallbackQuery, state: FSMContext):
    """Пользователь подтвердил подачу похожей проблемы."""
    data = await state.get_data()
    problem_text = data.get('text')
    
    if not problem_text:
        await smart_send(callback, "❌ Ошибка: текст проблемы не найден. Начните заново: /start")
        await state.clear()
        await callback.answer()
        return
    
    async with async_session() as session:
        user = await session.get(User, callback.from_user.id)
        
        if not user or not user.store_id:
            await smart_send(callback, "❌ Сначала привяжи себя к магазину: /start")
            await state.clear()
            await callback.answer()
            return
        
        # Сохраняем проблему с уже известным магазином пользователя
        problem = Problem(
            user_id=user.tg_id,
            store_id=user.store_id,
            text=problem_text,
            status=ProblemStatus.NEW
        )
        session.add(problem)
        await session.commit()
        
        store = await session.get(Store, user.store_id)
        store_name = store.name if store else "Неизвестно"
        
        await smart_send(callback, 
            f"✅ Проблема зафиксирована для магазина '{store_name}'! Спасибо.",
            reply_markup=get_main_menu(user.role)
        )
        await state.clear()
    
    await callback.answer()


@router.callback_query(F.data == "confirm_dup_no")
async def confirm_dup_no(callback: CallbackQuery, state: FSMContext):
    """Пользователь отменил подачу похожей проблемы."""
    await smart_send(callback, "❌ Подача проблемы отменена. Спасибо за внимательность!")
    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        user = await session.get(User, callback.from_user.id)
    if user:
        await show_main_menu(callback, user)
    await callback.answer()


@router.message(F.text == "⬅️ Назад")
async def btn_back(message: Message, state: FSMContext):
    await delete_user_message(message)
    await state.clear()
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
    if user:
        await smart_send(message, f"Привет, {user.name}! Твоя роль: {get_role_name(user.role)}", 
                                parse_mode="HTML", reply_markup=get_main_menu(user.role))
    else:
        await smart_send(message, "Сначала пройди регистрацию: /start", reply_markup=get_bottom_keyboard())

@router.message(F.text == "🏠 Главное меню")
async def btn_main_menu(message: Message, state: FSMContext):
    await delete_user_message(message)
    await state.clear()
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
    if user:
        await smart_send(message, f"Привет, {user.name}! Твоя роль: {get_role_name(user.role)}", 
                                parse_mode="HTML", reply_markup=get_main_menu(user.role))
    else:
        await smart_send(message, "Сначала пройди регистрацию: /start", reply_markup=get_bottom_keyboard())


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
    
    if new_status == ProblemStatus.RESOLVED:
        if user:
            try:
                notification = (
                    f"✅ <b>Ваша проблема решена!</b>\n\n"
                    f"Проблема #{problem_id}\n"
                    f"Магазин: {store.name}\n"
                    f"Описание: <i>{problem.text[:100]}...</i>\n\n"
                    f"💬 Комментарий руководителя:\n{comment}"
                )
                notification_msg = await message.bot.send_message(user.tg_id, notification, parse_mode="HTML")
                if notification_msg:
                    last_bot_messages[user.tg_id] = notification_msg.message_id
                    print(f"✅ Уведомление отправлено юзеру {user.tg_id}, обновлён last_bot_messages")
            except Exception as e:
                print(f"Не удалось отправить уведомление юзеру {user.tg_id}: {e}")
        else:
            print(f"⚠️ Автор проблемы #{problem_id} не найден в базе")
    
    elif new_status == ProblemStatus.POSTPONED:
        if user:
            try:
                notification = (
                    f"⏸ <b>Ваша проблема отложена</b>\n\n"
                    f"Проблема #{problem_id}\n"
                    f"Магазин: {store.name}\n"
                    f"Описание: <i>{problem.text[:100]}...</i>\n\n"
                    f"💬 Комментарий руководителя:\n{comment}"
                )
                notification_msg = await message.bot.send_message(user.tg_id, notification, parse_mode="HTML")
                if notification_msg:
                    last_bot_messages[user.tg_id] = notification_msg.message_id
                    print(f"✅ Уведомление об откладывании отправлено юзеру {user.tg_id}")
            except Exception as e:
                print(f"Не удалось отправить уведомление юзеру {user.tg_id}: {e}")
        else:
            print(f"⚠️ Автор проблемы #{problem_id} не найден в базе")
    
    await smart_send(message, f"✅ Статус проблемы #{problem_id} обновлен и комментарий сохранен.")
    await state.clear()
    
    # Показываем обновлённый список проблем для выбора следующей
    await _show_problems_for_update(message, message.from_user.id)


async def _show_problems_for_update(message_or_callback, user_id: int):
    """Вспомогательная функция для показа списка проблем для обновления статуса."""
    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user:
            return
        
        if user.role == UserRole.SUPERVISOR:
            result = await session.execute(
                select(Problem)
                .join(Store)
                .where(Store.cluster == user.cluster)
                .order_by(Problem.created_at.desc())
                .limit(20)
            )
            scope_name = f"кластер {user.cluster}"
        elif user.role == UserRole.DIRECTOR:
            result = await session.execute(
                select(Problem)
                .join(Store)
                .where(Store.region == user.region)
                .order_by(Problem.created_at.desc())
                .limit(20)
            )
            scope_name = f"регион {user.region}"
        else:
            return
        
        problems = result.scalars().all()
        problems = [p for p in problems if p.status.value != "Решена"]
        
        if not problems:
            keyboard = [[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_update")]]
            await smart_send(
                message_or_callback,
                f"🎉 <b>В вашем {scope_name} нет активных проблем для обновления.</b>\n\nВсе задачи закрыты!",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
            return
        
        keyboard = []
        status_names = {
            ProblemStatus.NEW: "Новая",
            ProblemStatus.IN_PROGRESS: "В работе",
            ProblemStatus.POSTPONED: "Отложена"
        }
        for p in problems:
            store = await session.get(Store, p.store_id)
            status_text = status_names.get(p.status, p.status.value)
            text = f"#{p.id} | {store.name if store else '?'} | {status_text} | {p.text[:30]}{'...' if len(p.text) > 30 else ''}"
            keyboard.append([InlineKeyboardButton(text=text, callback_data=f"update_prob_{p.id}")])
        
        keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_update")])
        
        await smart_send(
            message_or_callback,
            f"✏️ <b>Выберите проблему для обновления статуса</b>\n\n📍 {scope_name}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

# Обработчик кнопки "Отмена" при обновлении статуса
@router.callback_query(F.data == "cancel_update")
async def cancel_update(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        user = await session.get(User, callback.from_user.id)
    
    if user:
        await smart_send(callback, 
            f"👋 Привет, {user.name}!\n\nТвоя роль: <b>{get_role_name(user.role)}</b>",
            parse_mode="HTML",
            reply_markup=get_main_menu(user.role)
        )
    else:
        await smart_send(callback, "Сначала пройди регистрацию: /start")
    
    await callback.answer()

# Обратная связь
@router.callback_query(F.data == "action_feedback")
async def action_feedback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await smart_send(callback, 
        "💬 <b>Обратная связь</b>\n\nНапишите ваш отзыв о работе бота:",
        parse_mode="HTML"
    )
    await state.set_state(FeedbackForm.text)
    await callback.answer()

@router.callback_query(F.data == "action_instruction")
async def action_instruction(callback: CallbackQuery, state: FSMContext):
    async with async_session() as session:
        user = await session.get(User, callback.from_user.id)
    
    if user and user.role:
        if user.role == UserRole.EMPLOYEE:
            text = """🏪 <b>Главное меню сотрудника</b>

<b>Что ты можешь:</b>

📝 <b>Подать проблему</b>
Просто опиши, что случилось — ИИ сам разберется с категорией и найдет похожие случаи. Не нужно заполнять длинные формы!

📊 <b>Мои проблемы</b>
Посмотри статус всех своих обращений: в работе, решено, отклонено.

🔍 <b>Поиск похожих</b>
ИИ покажет, как мы решали похожие проблемы раньше. Возможно, решение уже есть!

🔔 <b>Уведомления о статусе</b>
Ты автоматически получишь сообщение, когда:
• Проблема принята в работу
• Назначен ответственный
• Проблема решена или отклонена

💡 <b>Как подать проблему:</b>
1. Нажми "Подать проблему"
2. Опиши ситуацию простыми словами
3. ИИ предложит категорию — подтверди или выбери другую
4. Готово! Ты получишь уведомление, когда проблема решится

💬 Нужна помощь? Нажми кнопку Обратная связь"""
        elif user.role == UserRole.SUPERVISOR:
            text = """👨‍💼 <b>Главное меню супервайзера</b>

<b>Твои возможности:</b>

📊 <b>Аналитика по кластеру</b>
Посмотри статистику по всем магазинам твоего кластера.

📋 <b>Управление проблемами</b>
Просматривай обращения от сотрудников и меняй статусы.

🔔 <b>Автоматические запросы и рассылки</b>
Тебе будут приходить:
• 📩 <b>Еженедельный отчет</b> (каждый понедельник) — сводка по всем проблемам кластера за неделю. Изучи и прими к сведению.
• 📊 <b>Напоминание о просроченных</b> — список проблем, которые висят без движения. Проверь и обнови статусы.

💡 <b>Как работать эффективно:</b>
1. Используй ИИ-резюме — оно покажет суть без чтения длинных описаний
2. Реагируй на запросы бота — это помогает держать всё под контролем

💬 Нужна помощь? Нажми кнопку Обратная связь"""
        elif user.role == UserRole.DIRECTOR:
            text = """🏢 <b>Главное меню регионального руководителя</b>

📊 <b>Аналитика по кластеру</b>
Посмотри статистику по всем магазинам твоего кластера.

📋 <b>Управление проблемами</b>
Просматривай обращения от сотрудников и меняй статусы.

🔔 <b>Автоматические запросы и рассылки</b>
Тебе будут приходить:
• 📩 <b>Еженедельная сводка</b> (каждый понедельник) — краткий обзор по всем кластерам региона. Помогает держать руку на пульсе.
• 📊 <b>Ежемесячный отчет</b> (1-е число месяца) — обзор ключевых показателей региона.
• 🎯 <b>Квартальное напоминание</b> (раз в 3 месяца) — стратегический обзор с выводами и рекомендациями.

💡 <b>Как использовать:</b>
1. Начни с еженедельной сводки — увидишь общую картину
2. ИИ-резюме поможет быстро понять суть проблем

💬 Нужна помощь? Нажми кнопку Обратная связь"""
        else:
            text = "Инструкция недоступна для этой роли."
    else:
        text = """👋 <b>Добро пожаловать в Супер Кайдзен с ИИ ассистентом!</b>

Это умная система для решения проблем магазинов. Вместо привычной "доски проблем" у нас ИИ, который:
🔍 Находит похожие случаи из прошлого
📂 Автоматически категоризирует проблемы
📊 Делает краткие резюме для руководства

<b>Как это работает:</b>
1️⃣ Ты описываешь проблему в 2-3 предложениях
2️⃣ ИИ ищет похожие решения и предлагает категорию
3️⃣ Руководитель получает суть проблемы и принимает решение
4️⃣ Ты узнаешь о статусе решения

<b>Выбери свою роль:</b>
• Сотрудник магазина — подача проблем
• Супервайзер — управление проблемами в кластере
• Региональный руководитель — аналитика и отчеты

💬 Нужна помощь? Нажми кнопку Обратная связь"""
    
    await smart_send(callback, text, parse_mode="HTML")
    await callback.answer()

@router.message(Command("feedback"))
async def cmd_feedback(message: Message, state: FSMContext):
    await delete_user_message(message)  # Удаляем команду /feedback
    await state.clear()
    await smart_send(message, 
        "💬 <b>Обратная связь</b>\n\nНапишите ваш отзыв о работе бота:",
        parse_mode="HTML"
    )
    await state.set_state(FeedbackForm.text)

@router.message(FeedbackForm.text)
async def process_feedback_text(message: Message, state: FSMContext):
    await delete_user_message(message)
    await state.update_data(feedback_text=message.text)
    
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить номер телефона", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    
    await smart_send(message, 
        "📱 Отправьте ваш номер телефона (кнопка ниже или текстом):",
        reply_markup=keyboard
    )
    await state.set_state(FeedbackForm.phone)

@router.message(FeedbackForm.phone)
async def process_feedback_phone(message: Message, state: FSMContext):
    await delete_user_message(message)
    data = await state.get_data()
    feedback_text = data.get('feedback_text', '')
    
    phone = message.contact.phone_number if message.contact else message.text

    async with async_session() as session:
        session.add(Feedback(
            user_id=message.from_user.id,
            text=feedback_text,
            phone=phone
        ))
        await session.commit()
    
    await smart_send(message, 
        "✅ Спасибо! Отзыв сохранен."
    )
    await state.clear()

@router.message(Command("view_feedback"))
async def cmd_view_feedback(message: Message, state: FSMContext):
    if message.from_user.id != settings.ADMIN_ID:
        await smart_send(message, "❌ Только для администратора.")
        return
    
    async with async_session() as session:
        result = await session.execute(
            select(Feedback).order_by(Feedback.created_at.desc()).limit(20)
        )
        feedbacks = result.scalars().all()
    
    if not feedbacks:
        await smart_send(message, "📋 Нет обратной связи.")
        return
    
    text = "📋 <b>Последние отзывы:</b>\n\n"
    for f in feedbacks[:10]:
        user = await session.get(User, f.user_id)
        username = user.name if user and user.name else f"ID: {f.user_id}"
        date_str = f.created_at.strftime("%d.%m.%Y %H:%M") if f.created_at else ""
        text += f"<b>#{f.id}</b> | {username} | {date_str}\n"
        text += f"📝 {f.text[:100]}{'...' if len(f.text) > 100 else ''}\n"
        text += f"📞 Телефон: {f.phone or 'Не указан'}\n\n"
    
    await smart_send(message_or_callback, text, parse_mode="HTML")


async def show_main_menu(message_or_callback, user):
    """Показывает главное меню через edit_text или answer."""
    text = f"👋 Привет, {user.name}!\n\nТвоя роль: <b>{get_role_name(user.role)}</b>"
    keyboard = get_main_menu(user.role)
    
    # Если это callback - редактируем, если message - отправляем
    if hasattr(message_or_callback, 'message'):
        try:
            await message_or_callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            await message_or_callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await message_or_callback.answer(text, reply_markup=keyboard, parse_mode="HTML")


from app.scheduler import send_weekly_reports, send_quarterly_reminders

async def safe_edit_message(message, text: str, reply_markup=None, parse_mode: str = None):
    """Безопасное редактирование сообщения с обработкой ошибок."""
    try:
        if reply_markup:
            await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        else:
            await message.edit_text(text, parse_mode=parse_mode)
    except MessageNotModified:
        pass  # Текст не изменился, игнорируем
    except Exception as e:
        print(f"Ошибка редактирования сообщения: {e}")
        # Fallback на отправку нового сообщения
        if reply_markup:
            await smart_send(message, text, reply_markup=reply_markup, parse_mode=parse_mode)
        else:
            await smart_send(message, text, parse_mode=parse_mode)



@router.message(Command("force_weekly"))
async def cmd_force_weekly(message: Message, state: FSMContext):
    if message.from_user.id != settings.ADMIN_ID:
        await smart_send(message, "❌ Только для админа.")
        return
    
    await smart_send(message, "🚀 Запускаю принудительную рассылку недельных отчетов...")
    await send_weekly_reports(message.bot)
    await smart_send(message, "✅ Рассылка завершена. Проверь, пришли ли отчеты супервайзерам и директорам.")

@router.message(Command("force_quarterly"))
async def cmd_force_quarterly(message: Message, state: FSMContext):
    if message.from_user.id != settings.ADMIN_ID:
        await smart_send(message, "❌ Только для админа.")
        return
    
    await smart_send(message, "🚀 Запускаю принудительную рассылку квартальных напоминаний...")
    await send_quarterly_reminders(message.bot)
    await smart_send(message, "✅ Рассылка завершена. Проверь, пришли ли напоминания.")

# Обработчики кнопок нижнего меню (без требования регистрации)
@router.message(F.text == "🏠 Домой")
async def btn_home(message: Message, state: FSMContext):
    await delete_user_message(message)
    await state.clear()
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
    
    if user:
        await smart_send(message, "Главное меню:", reply_markup=get_main_menu(user.role))
    else:
        await smart_send(message, 
            "Привет! Я бот «Супер Кайдзен с ИИ ассистентом».\n\n"
            "Давай настроим твой профиль. Кем ты работаешь?",
            reply_markup=get_role_keyboard()
        )

@router.message(F.text == "🔄 Сменить роль")
async def btn_change_role_text(message: Message, state: FSMContext):
    await delete_user_message(message)
    await state.clear()
    await change_user_role(message.from_user.id)
    await smart_send(message, 
        "🤖 <b>Бот «Супер Кайдзен с ИИ ассистентом»</b>\n\n"
        "Бот для фиксации проблем магазинов: Сотрудники фиксируют проблемы, искусственный интеллект их обрабатывает, руководители анализируют и решают их\n\n"
        "Выберите вашу роль:",
        parse_mode="HTML",
        reply_markup=get_role_keyboard()
    )

@router.message(F.text == "💬 Обратная связь")
async def btn_feedback_text(message: Message, state: FSMContext):
    await delete_user_message(message)
    await state.clear()
    await smart_send(message, 
        "💬 <b>Обратная связь</b>\n\nНапишите ваш отзыв о работе бота:",
        parse_mode="HTML"
    )
    await state.set_state(FeedbackForm.text)

@router.message(F.text == "📖 Инструкция")
async def btn_instruction(message: Message, state: FSMContext):
    await delete_user_message(message)
    
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
    
    if user and user.role:
        if user.role == UserRole.EMPLOYEE:
            text = """🏪 <b>Главное меню сотрудника</b>

<b>Что ты можешь:</b>

📝 <b>Подать проблему</b>
Просто опиши, что случилось — ИИ сам разберется с категорией и найдет похожие случаи. Не нужно заполнять длинные формы!

📊 <b>Мои проблемы</b>
Посмотри статус всех своих обращений: в работе, решено, отклонено.

🔍 <b>Поиск похожих</b>
ИИ покажет, как мы решали похожие проблемы раньше. Возможно, решение уже есть!

🔔 <b>Уведомления о статусе</b>
Ты автоматически получишь сообщение, когда:
• Проблема принята в работу
• Назначен ответственный
• Проблема решена или отклонена

💡 <b>Как подать проблему:</b>
1. Нажми "Подать проблему"
2. Опиши ситуацию простыми словами
3. ИИ предложит категорию — подтверди или выбери другую
4. Готово! Ты получишь уведомление, когда проблема решится

💬 Нужна помощь? Нажми кнопку Обратная связь"""
        elif user.role == UserRole.SUPERVISOR:
            text = """👨‍💼 <b>Главное меню супервайзера</b>

<b>Твои возможности:</b>

📊 <b>Аналитика по кластеру</b>
Посмотри статистику по всем магазинам твоего кластера.

📋 <b>Управление проблемами</b>
Просматривай обращения от сотрудников и меняй статусы.

🔔 <b>Автоматические запросы и рассылки</b>
Тебе будут приходить:
• 📩 <b>Еженедельный отчет</b> (каждый понедельник) — сводка по всем проблемам кластера за неделю. Изучи и прими к сведению.
• 📊 <b>Напоминание о просроченных</b> — список проблем, которые висят без движения. Проверь и обнови статусы.

💡 <b>Как работать эффективно:</b>
1. Используй ИИ-резюме — оно покажет суть без чтения длинных описаний
2. Реагируй на запросы бота — это помогает держать всё под контролем

💬 Нужна помощь? Нажми кнопку Обратная связь"""
        elif user.role == UserRole.DIRECTOR:
            text = """🏢 <b>Главное меню регионального руководителя</b>

📊 <b>Аналитика по кластеру</b>
Посмотри статистику по всем магазинам твоего кластера.

📋 <b>Управление проблемами</b>
Просматривай обращения от сотрудников и меняй статусы.

🔔 <b>Автоматические запросы и рассылки</b>
Тебе будут приходить:
• 📩 <b>Еженедельная сводка</b> (каждый понедельник) — краткий обзор по всем кластерам региона. Помогает держать руку на пульсе.
• 📊 <b>Ежемесячный отчет</b> (1-е число месяца) — обзор ключевых показателей региона.
• 🎯 <b>Квартальное напоминание</b> (раз в 3 месяца) — стратегический обзор с выводами и рекомендациями.

💡 <b>Как использовать:</b>
1. Начни с еженедельной сводки — увидишь общую картину
2. ИИ-резюме поможет быстро понять суть проблем

💬 Нужна помощь? Нажми кнопку Обратная связь"""
        else:
            text = "Инструкция недоступна для этой роли."
    else:
        text = """👋 <b>Добро пожаловать в Супер Кайдзен с ИИ ассистентом!</b>

Это умная система для решения проблем магазинов. Вместо привычной "доски проблем" у нас ИИ, который:
🔍 Находит похожие случаи из прошлого
📂 Автоматически категоризирует проблемы
📊 Делает краткие резюме для руководства

<b>Как это работает:</b>
1️⃣ Ты описываешь проблему в 2-3 предложениях
2️⃣ ИИ ищет похожие решения и предлагает категорию
3️⃣ Руководитель получает суть проблемы и принимает решение
4️⃣ Ты узнаешь о статусе решения

<b>Выбери свою роль:</b>
• Сотрудник магазина — подача проблем
• Супервайзер — управление проблемами в кластере
• Региональный руководитель — аналитика и отчеты

💬 Нужна помощь? Нажми кнопку Обратная связь"""
    
    await smart_send(message, text, parse_mode="HTML")

@router.callback_query(F.data == "confirm_submit_problem")
async def confirm_submit_problem(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    text = data.get('problem_text')
    async with async_session() as session:
        user = await session.get(User, callback.from_user.id)
    if user:
        await save_problem(user.tg_id, user.store_id, text)
        await smart_send(callback, "✅ Проблема зафиксирована! Спасибо.")
    await state.clear()
    await callback.answer()

@router.callback_query(F.data == "cancel_submit_problem")
async def cancel_submit_problem(callback: CallbackQuery, state: FSMContext):
    await smart_send(callback, "❌ Подача проблемы отменена.")
    await state.clear()
    await callback.answer()

# Обработка любого текста

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id != settings.ADMIN_ID:
        await message.answer("У вас нет прав для просмотра статистики.")
        return

    async with async_session() as session:
        total = await session.execute(select(func.count(User.tg_id)))
        total_count = total.scalar()

        roles = await session.execute(
            select(User.role, func.count(User.tg_id)).group_by(User.role)
        )
        role_counts = roles.all()

    role_names = {
        "EMPLOYEE": "Сотрудник",
        "SUPERVISOR": "Супервайзер",
        "DIRECTOR": "Региональный директор"
    }

    text = "📊 <b>Статистика пользователей</b>\n\n"
    text += "👥 <b>Всего зарегистрировано:</b> " + str(total_count) + "\n\n"
    text += "<b>По ролям:</b>\n"

    for role, count in role_counts:
        name = role_names.get(role, role)
        text += "• " + name + ": " + str(count) + "\n"

    await message.answer(text, parse_mode="HTML")


@router.message(F.text)
async def handle_any_message(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state:
        return
    
    async with async_session() as session:
        
        user = await session.get(User, message.from_user.id)
    
    if user and user.store_id:
        await save_problem(user.tg_id, user.store_id, message.text)
        await smart_send(message, "✅ Проблема зафиксирована! Спасибо.", reply_markup=get_bottom_keyboard())
    else:
        await smart_send(message, "Сначала пройди регистрацию: /start", reply_markup=get_bottom_keyboard())

# Вспомогательные функции
async def save_problem(user_id: int, store_id: int, text: str):
    async with async_session() as session:
        problem = Problem(
            user_id=user_id,
            store_id=store_id,
            text=text,
            status=ProblemStatus.NEW
        )
        session.add(problem)
        await session.commit()

async def generate_report(user_id: int, message_or_callback, days: int):
    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user:
            await smart_send(message_or_callback, "❌ Пользователь не найден.")
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
            await smart_send(message_or_callback, "❌ Отчеты доступны только супервайзерам и директорам.")
            return

        count_q = select(func.count(Problem.id)).join(Store).where(*base_filter, scope_filter)
        total_count = (await session.execute(count_q)).scalar()

        prob_q = select(Problem).join(Store).where(*base_filter, scope_filter).order_by(Problem.created_at.desc()).limit(15)
        problems = (await session.execute(prob_q)).scalars().all()

        # Загружаем ВСЕ проблемы для поиска похожих (не только за период)
        all_problems_q = select(Problem).order_by(Problem.created_at.desc()).limit(200)
        all_problems = (await session.execute(all_problems_q)).scalars().all()

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
        text = f"🤖 <b>Автоматический отчет</b>\n\n🎉 За последнюю {period} в {scope} нет нерешенных проблем!"
    else:
        text = f"🤖 <b>Отчет за {period}</b>\n📍 {scope}\n🔢 Нерешенных проблем: {total_count}\n\n"
        # Генерируем AI-саммари
        ai_summary = await generate_ai_summary(problems, stores_map)
        text += f"🤖 <b>AI-саммари:</b>\n{ai_summary}\n\n"
        text += "📋 <b>Список проблем:</b>\n\n"

        for p in problems:
            # Ищем похожие проблемы через ИИ с fallback на SequenceMatcher
            similar_info = ""
            try:
                # Пытаемся использовать ИИ
                similar_ids = await find_similar_problems_ai(p.text, [s for s in all_problems if s.id != p.id], threshold=1)
                if similar_ids:
                    similar_problem = next((s for s in all_problems if s.id == similar_ids[0]), None)
                    if similar_problem:
                        similar_info = await format_similar_info(similar_problem, session)
            except Exception as e:
                print(f"⚠️ Ошибка ИИ для проблемы #{p.id}, используем fallback: {e}")
                # Fallback на SequenceMatcher
                similar_in_report = [s for s in all_problems if s.id != p.id and SequenceMatcher(None, p.text.lower(), s.text.lower()).ratio() > 0.5]
                if similar_in_report:
                    similar_problem = similar_in_report[0]
                    similar_info = await format_similar_info(similar_problem, session)
            
            store_name = stores_map.get(p.store_id, "Неизвестно")
            emoji = status_emojis.get(p.status, "❓")
            status_text = p.status.value.capitalize()
            date_str = p.created_at.strftime("%d.%m %H:%M") if p.created_at else ""
            txt = p.text[:80] + "..." if len(p.text) > 80 else p.text
            text += f"• {emoji} <b>#{p.id}</b>| {store_name}| {status_text}\n📝 {txt}\n📅 {date_str}\n"
            if similar_info:
                text += f"🔍 <b>Похожая проблема:</b>\n{similar_info}\n"
            else:
                text += "\n"

        if total_count > 15:
            text += f"⚠️ Показаны последние 15 из {total_count}."

    await smart_send(message_or_callback, text, parse_mode="HTML")

def get_role_name(role: UserRole):
    names = {
        UserRole.EMPLOYEE: "Сотрудник магазина",
        UserRole.SUPERVISOR: "Супервайзер",
        UserRole.DIRECTOR: "Региональный директор"
    }
    return names.get(role, "Неизвестно")

async def change_user_role(tg_id: int):
    async with async_session() as session:
        user = await session.get(User, tg_id)
        if user:
            await session.delete(user)
            await session.commit()
    # Очищаем ID последнего сообщения при смене роли
    if tg_id in last_bot_messages:
        del last_bot_messages[tg_id]

@router.callback_query(F.data == "action_my_problems")
async def action_my_problems(callback: CallbackQuery, state: FSMContext):
    async with async_session() as session:
        result = await session.execute(
            select(Problem)
            .where(Problem.user_id == callback.from_user.id)
            .order_by(Problem.created_at.desc())
        )
        problems = result.scalars().all()
    
    if not problems:
        await smart_send(callback, "📋 У тебя пока нет зафиксированных проблем.")
    else:
        status_names = {
            ProblemStatus.NEW: "🆕 Новая",
            ProblemStatus.IN_PROGRESS: "🔄 В работе",
            ProblemStatus.RESOLVED: "✅ Решена",
            ProblemStatus.POSTPONED: "⏸ Отложена"
        }
        
        text = "📋 <b>Твои проблемы:</b>\n\n"
        for p in problems[:20]:
            status_text = status_names.get(p.status, p.status.value)
            date_str = p.created_at.strftime("%d.%m.%Y %H:%M") if p.created_at else ""
            text += f"<b>#{p.id}</b> [{status_text}]\n"
            text += f"📝 {p.text[:100]}{'...' if len(p.text) > 100 else ''}\n"
            text += f"📅 {date_str}\n\n"
        
        await smart_send(callback, text, parse_mode="HTML", reply_markup=get_nav_keyboard())
    
    await callback.answer()

@router.callback_query(F.data == "action_update_status")
async def start_status_update(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user:
            await callback.answer("Пользователь не найден")
            return
        
        if user.role == UserRole.SUPERVISOR:
            result = await session.execute(
                select(Problem)
                .join(Store)
                .where(Store.cluster == user.cluster)
                .order_by(Problem.created_at.desc())
                .limit(20)
            )
            scope_name = f"кластер {user.cluster}"
        elif user.role == UserRole.DIRECTOR:
            result = await session.execute(
                select(Problem)
                .join(Store)
                .where(Store.region == user.region)
                .order_by(Problem.created_at.desc())
                .limit(20)
            )
            scope_name = f"регион {user.region}"
        else:
            await smart_send(callback, "❌ Доступ запрещен.")
            await callback.answer()
            return
        
        problems = result.scalars().all()
        for p in problems:
            print(f"  - Проблема #{p.id}, статус: '{p.status.value}'")
        
        problems = [p for p in problems if p.status.value != "Решена"]
        
        if not problems:
            await smart_send(callback, f"🎉 В вашем {scope_name} нет активных проблем для обновления. Все задачи закрыты!")
            await callback.answer()
            return
        
        keyboard = []
        for p in problems:
            store = await session.get(Store, p.store_id)
            status_names = {
                ProblemStatus.NEW: "Новая",
                ProblemStatus.IN_PROGRESS: "В работе",
                ProblemStatus.POSTPONED: "Отложена"
            }
            status_text = status_names.get(p.status, p.status.value)
            btn_text = f"#{p.id} | {store.name} | {status_text}"
            keyboard.append([InlineKeyboardButton(
                text=btn_text,
                callback_data=f"update_prob_{p.id}"
            )])
        
        await smart_send(callback, 
            f"📋 Выберите проблему для обновления статуса ({scope_name}):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
        await state.set_state(StatusUpdateForm.selecting_problem)
        
    await callback.answer()

@router.callback_query(F.data.startswith("update_prob_"))
async def select_problem_for_update(callback: CallbackQuery, state: FSMContext):
    problem_id = int(callback.data.split("_")[2])
    
    async with async_session() as session:
        problem = await session.get(Problem, problem_id)
        store = await session.get(Store, problem.store_id)
        
        await state.update_data(problem_id=problem_id)
        
        statuses = [
            (ProblemStatus.NEW, "🆕 Новая"),
            (ProblemStatus.IN_PROGRESS, "🔄 В работе"),
            (ProblemStatus.RESOLVED, "✅ Решена"),
            (ProblemStatus.POSTPONED, "⏸ Отложена")
        ]
        
        keyboard = []
        for status, label in statuses:
            keyboard.append([InlineKeyboardButton(
                text=label,
                callback_data=f"update_stat_{problem_id}_{status.value}"
            )])
        
        await smart_send(callback, 
            f"📝 <b>Проблема #{problem_id}</b> | {store.name}\n\n"
            f"<i>{problem.text[:150]}{'...' if len(problem.text) > 150 else ''}</i>\n\n"
            f"Выберите новый статус:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
            parse_mode="HTML"
        )
    
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
        if new_status == ProblemStatus.RESOLVED:
            prompt = "✅ <b>Статус: Решена</b>\n\nКратко напишите, как решилась проблема:"
        else:
            prompt = "⏸ <b>Статус: Отложена</b>\n\nКратко напишите, почему проблема отложена:"
        
        await smart_send(callback, prompt, parse_mode="HTML")
        await state.set_state(StatusUpdateForm.entering_comment)
    else:
        async with async_session() as session:
            problem = await session.get(Problem, problem_id)
            problem.status = new_status
            await session.commit()
            
            # Отправляем уведомление сотруднику, если статус "В работе"
            if new_status == ProblemStatus.IN_PROGRESS:
                user = await session.get(User, problem.user_id)
                store = await session.get(Store, problem.store_id)
                
                if user:
                    try:
                        notification = (
                            f"🔄 <b>Ваша проблема взята в работу!</b>\n\n"
                            f"Проблема #{problem_id}\n"
                            f"Магазин: {store.name}\n"
                            f"Описание: <i>{problem.text[:100]}...</i>"
                        )
                        notification_msg = await callback.bot.send_message(user.tg_id, notification, parse_mode="HTML")
                        if notification_msg:
                            last_bot_messages[user.tg_id] = notification_msg.message_id
                            print(f"✅ Уведомление 'В работе' отправлено юзеру {user.tg_id}")
                    except Exception as e:
                        print(f"Не удалось отправить уведомление юзеру {user.tg_id}: {e}")
        
        await smart_send(callback, f"✅ Статус проблемы #{problem_id} обновлен на '{new_status.value.capitalize()}'")
        await state.clear()
        
        # Показываем обновлённый список проблем для выбора следующей
        await _show_problems_for_update(callback, callback.from_user.id)
    
    await callback.answer()



