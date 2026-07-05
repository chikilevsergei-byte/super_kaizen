import openai
import re
from app.config import settings
from app.models import ProblemStatus

def clean_html_for_telegram(html_text: str) -> str:
    html_text = re.sub(r'<!DOCTYPE[^>]*>', '', html_text, flags=re.IGNORECASE)
    html_text = re.sub(r'<html[^>]*>', '', html_text, flags=re.IGNORECASE)
    html_text = re.sub(r'</html>', '', html_text, flags=re.IGNORECASE)
    html_text = re.sub(r'<head[^>]*>.*?</head>', '', html_text, flags=re.IGNORECASE | re.DOTALL)
    html_text = re.sub(r'<body[^>]*>', '', html_text, flags=re.IGNORECASE)
    html_text = re.sub(r'</body>', '', html_text, flags=re.IGNORECASE)
    return html_text.strip()

async def generate_ai_summary(problems: list, stores_map: dict) -> str:
    if not problems:
        return "Нет проблем для анализа."
    
    problems_text = ""
    for i, p in enumerate(problems, 1):
        store_name = stores_map.get(p.store_id, "Неизвестно")
        status_text = p.status.value
        problems_text += f"{i}. [{status_text}] {store_name}: {p.text}\n"
    
    try:
        print(f"DEBUG AI: Запускаем YandexGPT для {len(problems_to_analyze)} проблем")
        client = openai.AsyncOpenAI(
            api_key=settings.YANDEX_API_KEY,
            base_url="https://ai.api.cloud.yandex.net/v1",
            project=settings.YANDEX_PROJECT_ID
        )
        
        print(f"DEBUG AI: Отправляем запрос в YandexGPT...")
        response = await client.responses.create(
            prompt={"id": settings.YANDEX_PROMPT_ID},
            input=f"""Проанализируй проблемы из системы кайдзен и напиши краткое саммари (3-5 предложений) на русском языке.
1. Выдели основные темы и повторяющиеся проблемы
2. Укажи, какие области требуют внимания
3. Дай краткую рекомендацию

ВАЖНО: Используй только теги <b> для выделения важного. НЕ используй DOCTYPE, html, head, body.

Проблемы:
{problems_text}"""
        )
        
        return clean_html_for_telegram(response.output_text)
    except Exception as e:
        print(f"Ошибка генерации AI-саммари: {e}")
        return "⚠️ Не удалось сгенерировать AI-саммари"


async def find_similar_problems_ai(new_problem_text: str, existing_problems: list, threshold: int = 3) -> list:
    """
    Находит похожие проблемы по смыслу с помощью YandexGPT.
    
    Args:
        new_problem_text: Текст новой проблемы
        existing_problems: Список существующих проблем (объекты Problem)
        threshold: Максимальное количество похожих проблем (по умолчанию 3)
    
    Returns:
        Список ID похожих проблем
    """
    print(f"DEBUG AI: Проверяем условия: existing_problems={len(existing_problems)}, text_len={len(new_problem_text.strip())}")
    if not existing_problems:
        print("DEBUG AI: Нет существующих проблем")
        return []
    if len(new_problem_text.strip()) < 3:
        print("DEBUG AI: Текст слишком короткий")
        return []
    
    # Формируем список проблем для анализа (ограничиваем до 50, чтобы не превысить лимит токенов)
    problems_to_analyze = existing_problems[:50]
    
    problems_text = ""
    for i, p in enumerate(problems_to_analyze, 1):
        problems_text += f"{i}. ID={p.id}: {p.text}\n"
    
    try:
        print(f"DEBUG AI: Запускаем YandexGPT для {len(problems_to_analyze)} проблем")
        client = openai.AsyncOpenAI(
            api_key=settings.YANDEX_API_KEY,
            base_url="https://ai.api.cloud.yandex.net/v1",
            project=settings.YANDEX_PROJECT_ID
        )
        
        print(f"DEBUG AI: Отправляем запрос в YandexGPT...")
        response = await client.responses.create(
            prompt={"id": settings.YANDEX_PROMPT_ID},
            input=f"""Проанализируй новую проблему и найди среди существующих проблем похожие по СМЫСЛУ (не по словам).

НОВАЯ ПРОБЛЕМА:
{new_problem_text}

СУЩЕСТВУЮЩИЕ ПРОБЛЕМЫ:
{problems_text}

ИНСТРУКЦИЯ:
Ты работаешь в розничной сети магазинов. Твоя задача — находить проблемы по СМЫСЛУ, а не по словам.

1. Анализируй СУТЬ проблемы, а не формулировку
2. Учитывай контекст розничной сети:
   - "Сломалась кофемашина" = "Аппарат для кофе не работает" = "Кофейный аппарат неисправен"
   - "Грязный пол" = "Не убрались" = "Пол в зале грязный"
   - "Нет ценников" = "Ценники отсутствуют" = "Товары без цен"
3. Найди проблемы, которые похожи по смыслу на новую проблему
4. Верни ТОЛЬКО номера строк (1, 2, 3...) из списка существующих проблем
5. Верни максимум {threshold} номеров
6. Формат ответа: просто числа через запятую, например: "3, 7, 12"
7. Если похожих проблем нет, верни: "нет"

ПРИМЕРЫ:
- Новая: "Сломалась кофемашина в зале" → Похожие: "Аппарат для кофе не работает", "Кофейный аппарат сломан"
- Новая: "Грязно в туалете" → Похожие: "Туалет не убран", "Санузел грязный"
- Новая: "Нет ценников на полках" → Похожие: "Ценники отсутствуют", "Товары без цен"

ОТВЕТ (только номера или "нет"):"""
        )
        
        result_text = response.output_text.strip().lower()
        print(f"DEBUG AI: YandexGPT вернул: {result_text}")
        
        # Парсим результат
        if result_text == "нет" or not result_text:
            return []
        
        # Извлекаем номера
        similar_ids = []
        for part in result_text.replace(" ", "").split(","):
            try:
                line_num = int(part)
                if 1 <= line_num <= len(problems_to_analyze):
                    similar_ids.append(problems_to_analyze[line_num - 1].id)
            except ValueError:
                continue
        
        return similar_ids[:threshold]
        
    except Exception as e:
        print(f"Ошибка поиска похожих проблем через ИИ: {e}")
        return []

