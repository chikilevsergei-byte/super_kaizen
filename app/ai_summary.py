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
        # Исправленная конфигурация клиента для YandexGPT Prompt API
        client = openai.AsyncOpenAI(
            api_key=settings.YANDEX_API_KEY,
            base_url="https://ai.api.cloud.yandex.net/v1",
            project=settings.YANDEX_PROJECT_ID
        )

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
        print(f" Ошибка генерации AI-саммари: {e}")
        return "⚠️ Не удалось сгенерировать AI-саммари"

async def find_similar_problems_ai(new_problem_text: str, existing_problems: list, threshold: int = 3) -> list:
    """Поиск похожих проблем через ИИ с защитой от ошибок."""
    print(f"[AI_SUMMARY] Start check. Text len={len(new_problem_text)}, DB count={len(existing_problems)}")
    
    if not new_problem_text or not existing_problems:
        print("[AI_SUMMARY] Нет текста или проблем для сравнения")
        return []
        
    try:
        # Здесь должна быть ваша оригинальная логика ИИ
        # Например, обращение к API нейросети или семантический поиск
        
        # ВРЕМЕННАЯ ЛОГИКА (замените на свою):
        from difflib import SequenceMatcher
        similar_ids = []
        new_text_lower = new_problem_text.lower()
        
        for p in existing_problems:
            ratio = SequenceMatcher(None, new_text_lower, p.text.lower()).ratio()
            if ratio > 0.6:  # Порог схожести
                similar_ids.append(p.id)
                
        print(f"[AI_SUMMARY] Found {len(similar_ids)} similar problems via fallback")
        return similar_ids[:threshold]
        
    except Exception as e:
        print(f"[AI_SUMMARY ERROR] Ошибка при поиске похожих: {e}")
        import traceback; traceback.print_exc()
        return []
