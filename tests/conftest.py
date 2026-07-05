import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.models import Base, Store, User, Problem, UserRole, ProblemStatus
from app.database import async_session as real_session

# Фикстура для event loop (нужна для pytest-asyncio)
@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

# Фикстура для создания тестовой БД в памяти
@pytest.fixture(autouse=True)
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async_session_test = async_sessionmaker(engine, expire_on_commit=False)
    
    # Заполняем тестовыми данными
    async with async_session_test() as session:
        store = Store(id=1, name="Test Store", cluster="C1", region="R1")
        session.add(store)
        
        user = User(tg_id=123, name="Test User", role=UserRole.EMPLOYEE, store_id=1, cluster="C1", region="R1")
        session.add(user)
        
        problem = Problem(id=1, user_id=123, store_id=1, text="Сломалась кофемашина", status=ProblemStatus.RESOLVED, resolution_comment="Мастер починил")
        session.add(problem)
        
        await session.commit()
    
    yield async_session_test
    
    await engine.dispose()

# Фикстура для мока YandexGPT
@pytest.fixture
def mock_yandex_gpt(monkeypatch):
    mock_response = MagicMock()
    mock_response.output_text = "1"  # ИИ всегда находит проблему с ID 1
    
    mock_client_instance = AsyncMock()
    mock_client_instance.responses.create = AsyncMock(return_value=mock_response)
    
    class MockAsyncOpenAI:
        def __init__(self, *args, **kwargs):
            pass
        @property
        def responses(self):
            return mock_client_instance

    monkeypatch.setattr('app.ai_summary.openai.AsyncOpenAI', MockAsyncOpenAI)
    return mock_client_instance
