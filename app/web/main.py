from fastapi import FastAPI, Request, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
import secrets
import io
import pandas as pd
from sqlalchemy import select, text, func, text, update, delete, desc
from app.database import async_session, engine
from app.models import User, Problem, Feedback, Store, ProblemStatus, UserRole
from app.config import settings
import os

app = FastAPI(title="Super Kaizen Admin")

SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex(32))
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

templates = Jinja2Templates(directory="app/web/templates")
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")


def get_current_user(request: Request):
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return True


# ==================== AUTH ====================

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login(request: Request):
    form = await request.form()
    username = form.get("username", "").strip()
    password = form.get("password", "")
    
    # Если введён username - проверяем в таблице администраторов
    if username:
        import hashlib
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT id FROM admins WHERE username = :username AND password_hash = :hash"),
                {"username": username, "hash": password_hash}
            )
            admin = result.fetchone()
            
            if admin:
                request.session["authenticated"] = True
                request.session["admin_username"] = username
                return RedirectResponse(url="/", status_code=303)
            else:
                return templates.TemplateResponse("login.html", {
                    "request": request, "error": "Неверный логин или пароль"
                })
    
    # Если username не введён - проверяем основной пароль из .env
    env_password = settings.ADMIN_PASSWORD
    if password == env_password:
        request.session["authenticated"] = True
        request.session["admin_username"] = "admin"
        return RedirectResponse(url="/", status_code=303)
    
    return templates.TemplateResponse("login.html", {
        "request": request, "error": "Неверный пароль"
    })


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login")


# ==================== DASHBOARD ====================

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, authenticated: bool = Depends(get_current_user)):
    async with async_session() as session:
        total_users = (await session.execute(select(func.count(User.tg_id)))).scalar()
        
        # Активные проблемы (все кроме Решена)
        active_problems = (await session.execute(
            select(func.count(Problem.id)).where(Problem.status != ProblemStatus.RESOLVED)
        )).scalar()
        
        # Решённые проблемы
        resolved_problems = (await session.execute(
            select(func.count(Problem.id)).where(Problem.status == ProblemStatus.RESOLVED)
        )).scalar()
        
        # Считаем только новую обратную связь (не из архива)
        from app.models import FeedbackStatus
        total_feedback = (await session.execute(
            select(func.count(Feedback.id)).where(Feedback.status == FeedbackStatus.NEW)
        )).scalar()
        total_stores = (await session.execute(select(func.count(Store.id)))).scalar()
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "total_users": total_users,
        "active_problems": active_problems,
        "resolved_problems": resolved_problems,
        "total_feedback": total_feedback,
        "total_stores": total_stores,
    })


# ==================== PROBLEMS ====================

@app.get("/problems", response_class=HTMLResponse)
async def problems_list(request: Request, authenticated: bool = Depends(get_current_user)):
    """Активные проблемы — все кроме Решена"""
    from sqlalchemy.orm import aliased
    async with async_session() as session:
        query = (
            select(
                Problem.id,
                Problem.user_id,
                Problem.store_id,
                Problem.text,
                Problem.status,
                Problem.created_at,
                Problem.updated_at,
                User.name.label("user_name"),
                User.cluster,
                User.region,
            )
            .outerjoin(User, Problem.user_id == User.tg_id)
            .where(Problem.status != ProblemStatus.RESOLVED)
            .order_by(desc(Problem.created_at))
        )
        result = await session.execute(query)
        problems = [dict(row._mapping) for row in result.all()]
    print(f"[PROBLEMS] Найдено проблем: {len(problems)}")
    if problems:
        print(f"[PROBLEMS] Первая проблема: {problems[0]}")
    # Обрабатываем отсутствие имени пользователя
    for p in problems:
        if not p.get("user_name"):
            p["user_name"] = "Неизвестный пользователь"
    
    return templates.TemplateResponse("problems.html", {
        "request": request, "problems": problems, "archive": False
    })


@app.get("/problems/archive", response_class=HTMLResponse)
async def problems_archive(request: Request, authenticated: bool = Depends(get_current_user)):
    """Архив — только Решённые проблемы"""
    async with async_session() as session:
        query = (
            select(
                Problem.id,
                Problem.user_id,
                Problem.store_id,
                Problem.text,
                Problem.status,
                Problem.created_at,
                Problem.updated_at,
                User.name.label("user_name"),
                User.cluster,
                User.region,
            )
            .outerjoin(User, Problem.user_id == User.tg_id)
            .where(Problem.status == ProblemStatus.RESOLVED)
            .order_by(desc(Problem.created_at))
        )
        result = await session.execute(query)
        problems = [dict(row._mapping) for row in result.all()]
    return templates.TemplateResponse("problems.html", {
        "request": request, "problems": problems, "archive": True
    })


@app.post("/problems/{problem_id}/update-status")
async def update_problem_status(problem_id: int, request: Request, authenticated: bool = Depends(get_current_user)):
    form = await request.form()
    new_status = form.get("status")
    async with async_session() as session:
        await session.execute(update(Problem).where(Problem.id == problem_id).values(status=new_status))
        await session.commit()
    return RedirectResponse(url="/problems", status_code=303)


@app.post("/problems/{problem_id}/delete")
async def delete_problem(problem_id: int, request: Request, authenticated: bool = Depends(get_current_user)):
    async with async_session() as session:
        await session.execute(delete(Problem).where(Problem.id == problem_id))
        await session.commit()
    return RedirectResponse(url="/problems", status_code=303)


@app.get("/problems/export")
async def export_problems_excel(request: Request, authenticated: bool = Depends(get_current_user)):
    """Экспорт ВСЕХ проблем с данными пользователя"""
    try:
        async with async_session() as session:
            # Получаем все проблемы
            result = await session.execute(
                select(Problem).order_by(desc(Problem.created_at))
            )
            problems = result.scalars().all()
            
            # Получаем словарь пользователей для быстрого поиска по tg_id
            user_result = await session.execute(select(User))
            users_map = {u.tg_id: u for u in user_result.scalars().all()}
        
        data = []
        for p in problems:
            user = users_map.get(p.user_id)
            status_val = p.status.value if hasattr(p.status, 'value') else str(p.status)
            
            # Проверяем наличие поля updated_by_id и редактора
            editor_name = "-"
            if hasattr(p, 'updated_by_id') and p.updated_by_id:
                editor = users_map.get(p.updated_by_id)
                if editor:
                    editor_name = editor.name
            
            data.append({
                "ID": p.id,
                "TG ID Пользователя": p.user_id,
                "Имя Пользователя": user.name if user else "-",
                "Магазин ID": p.store_id,
                "Кластер": user.cluster if user and user.cluster else "-",
                "Регион": user.region if user and user.region else "-",
                "Описание": p.text,
                "Статус": status_val,
                "Создано": p.created_at.strftime("%d.%m.%Y %H:%M") if p.created_at else "",
                "Обновлено": p.updated_at.strftime("%d.%m.%Y %H:%M") if p.updated_at else "",
                "Кто редактировал": editor_name,
            })
        
        df = pd.DataFrame(data)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Проблемы")
        output.seek(0)
        
        return StreamingResponse(output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=problems.xlsx"})
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        # Возвращаем файл с ошибкой вместо 500
        err_df = pd.DataFrame([{"Ошибка экспорта": str(e)}])
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            err_df.to_excel(writer, index=False, sheet_name="Error")
        output.seek(0)
        return StreamingResponse(output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=export_error.xlsx"})
            
    except Exception as e:
        print(f"❌ Ошибка экспорта проблем: {e}")
        import traceback
        traceback.print_exc()
        # Возвращаем пустой Excel с ошибкой
        df = pd.DataFrame([{"Ошибка": str(e)}])
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Ошибка")
        output.seek(0)
        return StreamingResponse(output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=error.xlsx"})


# ==================== FEEDBACK ====================

@app.get("/feedback", response_class=HTMLResponse)
async def feedback_list(request: Request, authenticated: bool = Depends(get_current_user)):
    """Активная обратная связь (статус NEW)"""
    from app.models import FeedbackStatus
    async with async_session() as session:
        query = (
            select(
                Feedback.id,
                Feedback.user_id,
                Feedback.text,
                Feedback.phone,
                Feedback.created_at,
                Feedback.status,
                User.name.label("user_name"),
                User.store_id.label("store_id"),
                User.cluster,
                User.region,
            )
            .outerjoin(User, Feedback.user_id == User.tg_id)
            .where(Feedback.status == FeedbackStatus.NEW)
            .order_by(desc(Feedback.created_at))
        )
        result = await session.execute(query)
        feedbacks = [dict(row._mapping) for row in result.all()]
    print(f"[FEEDBACK] Найдено отзывов: {len(feedbacks)}")
    if feedbacks:
        print(f"[FEEDBACK] Первый отзыв: {feedbacks[0]}")
    # Обрабатываем отсутствие имени пользователя
    for f in feedbacks:
        if not f.get("user_name"):
            f["user_name"] = "Неизвестный пользователь"
    
    return templates.TemplateResponse("feedback.html", {
        "request": request, "feedbacks": feedbacks, "archive": False
    })


@app.get("/feedback/archive", response_class=HTMLResponse)
async def feedback_archive(request: Request, authenticated: bool = Depends(get_current_user)):
    """Архив обратной связи (статус RESOLVED)"""
    from app.models import FeedbackStatus
    async with async_session() as session:
        query = (
            select(
                Feedback.id,
                Feedback.user_id,
                Feedback.text,
                Feedback.phone,
                Feedback.created_at,
                Feedback.status,
                User.name.label("user_name"),
                User.store_id.label("store_id"),
                User.cluster,
                User.region,
            )
            .outerjoin(User, Feedback.user_id == User.tg_id)
            .where(Feedback.status == FeedbackStatus.RESOLVED)
            .order_by(desc(Feedback.created_at))
        )
        result = await session.execute(query)
        feedbacks = [dict(row._mapping) for row in result.all()]
    return templates.TemplateResponse("feedback.html", {
        "request": request, "feedbacks": feedbacks, "archive": True
    })


@app.post("/feedback/{feedback_id}/delete")
async def delete_feedback(feedback_id: int, request: Request, authenticated: bool = Depends(get_current_user)):
    async with async_session() as session:
        await session.execute(delete(Feedback).where(Feedback.id == feedback_id))
        await session.commit()
    return RedirectResponse(url="/feedback", status_code=303)

@app.post("/feedback/{feedback_id}/resolve")
async def resolve_feedback(feedback_id: int, request: Request, authenticated: bool = Depends(get_current_user)):
    """Переместить отзыв в архив (пометить как решённый)"""
    from app.models import FeedbackStatus
    async with async_session() as session:
        await session.execute(
            update(Feedback)
            .where(Feedback.id == feedback_id)
            .values(status=FeedbackStatus.RESOLVED)
        )
        await session.commit()
    return RedirectResponse(url="/feedback", status_code=303)

@app.post("/feedback/{feedback_id}/unresolve")
async def unresolve_feedback(feedback_id: int, request: Request, authenticated: bool = Depends(get_current_user)):
    """Вернуть отзыв из архива (пометить как новый)"""
    from app.models import FeedbackStatus
    async with async_session() as session:
        await session.execute(
            update(Feedback)
            .where(Feedback.id == feedback_id)
            .values(status=FeedbackStatus.NEW)
        )
        await session.commit()
    return RedirectResponse(url="/feedback/archive", status_code=303)



@app.get("/feedback/export")
async def export_feedback_excel(request: Request, authenticated: bool = Depends(get_current_user)):
    try:
        async with async_session() as session:
            # Получаем все отзывы с данными пользователя
            query = (
                select(
                    Feedback.id,
                    Feedback.user_id,
                    Feedback.text,
                    Feedback.phone,
                    Feedback.created_at,
                    Feedback.status,
                    User.name.label("user_name"),
                    User.store_id.label("store_id"),
                    User.cluster,
                    User.region,
                )
                .outerjoin(User, Feedback.user_id == User.tg_id)
                .order_by(desc(Feedback.created_at))
            )
            result = await session.execute(query)
            rows = result.all()
        
        data = []
        for row in rows:
            r = dict(row._mapping)
            status_val = r['status'].value if hasattr(r['status'], 'value') else str(r['status'])
            data.append({
                "ID": r['id'],
                "TG ID Пользователя": r['user_id'],
                "Имя Пользователя": r.get('user_name') or "-",
                "Магазин ID": r.get('store_id') or "-",
                "Кластер": r.get('cluster') or "-",
                "Регион": r.get('region') or "-",
                "Сообщение": r['text'],
                "Телефон": r.get('phone') or "-",
                "Статус": status_val,
                "Дата": r['created_at'].strftime("%d.%m.%Y %H:%M") if r['created_at'] else "",
            })
            df = pd.DataFrame(data)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Обратная связь")
        output.seek(0)
        return StreamingResponse(output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=feedback.xlsx"})
    except Exception as e:
        import traceback
        traceback.print_exc()
        err_df = pd.DataFrame([{"Ошибка": str(e)}])
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            err_df.to_excel(writer, index=False, sheet_name="Error")
        output.seek(0)
        return StreamingResponse(output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=feedback_error.xlsx"})


# ==================== USERS ====================

@app.get("/users", response_class=HTMLResponse)
async def users_list(request: Request, authenticated: bool = Depends(get_current_user)):
    async with async_session() as session:
        result = await session.execute(select(User).order_by(desc(User.tg_id)))
        users = result.scalars().all()
    return templates.TemplateResponse("users.html", {"request": request, "users": users})


@app.post("/users/{user_id}/toggle-block")
async def toggle_user_block(user_id: int, request: Request, authenticated: bool = Depends(get_current_user)):
    """Блокировка/разблокировка через флаг is_blocked"""
    async with async_session() as session:
        user = await session.get(User, user_id)
        if user:
            # Инвертируем текущее состояние
            new_status = not user.is_blocked
            await session.execute(
                update(User)
                .where(User.tg_id == user_id)
                .values(is_blocked=new_status)
            )
            await session.commit()
    return RedirectResponse(url="/users", status_code=303)


# ==================== STORES ====================

@app.get("/stores", response_class=HTMLResponse)
async def stores_list(request: Request, authenticated: bool = Depends(get_current_user)):
    async with async_session() as session:
        result = await session.execute(select(Store).order_by(Store.id))
        stores = result.scalars().all()
    return templates.TemplateResponse("stores.html", {"request": request, "stores": stores})


@app.post("/stores/add")
async def add_store(request: Request, authenticated: bool = Depends(get_current_user)):
    """Добавление нового магазина вручную"""
    form = await request.form()
    store_id = form.get("store_id", "").strip()
    cluster = form.get("cluster", "").strip()
    region = form.get("region", "").strip()
    
    if not store_id or not cluster or not region:
        return RedirectResponse(url="/stores", status_code=303)
    
    try:
        store_id_int = int(store_id)
        async with async_session() as session:
            # Проверяем, существует ли магазин с таким ID
            existing = await session.get(Store, store_id_int)
            if existing:
                # Обновляем существующий
                existing.cluster = cluster
                existing.region = region
            else:
                # Создаем новый
                new_store = Store(id=store_id_int, cluster=cluster, region=region)
                session.add(new_store)
            await session.commit()
    except Exception as e:
        print(f"[ERROR] Ошибка добавления магазина: {e}")
        import traceback; traceback.print_exc()
    
    return RedirectResponse(url="/stores", status_code=303)


@app.post("/stores/{store_id}/edit")
async def edit_store(store_id: int, request: Request, authenticated: bool = Depends(get_current_user)):
    """Редактирование существующего магазина"""
    form = await request.form()
    cluster = form.get("cluster", "").strip()
    region = form.get("region", "").strip()
    
    if not cluster or not region:
        return RedirectResponse(url="/stores", status_code=303)
    
    async with async_session() as session:
        store = await session.get(Store, store_id)
        if store:
            store.cluster = cluster
            store.region = region
            await session.commit()
    
    return RedirectResponse(url="/stores", status_code=303)


@app.post("/stores/{store_id}/delete")
async def delete_store(store_id: int, request: Request, authenticated: bool = Depends(get_current_user)):
    """Удаление магазина"""
    async with async_session() as session:
        await session.execute(delete(Store).where(Store.id == store_id))
        await session.commit()
    return RedirectResponse(url="/stores", status_code=303)


@app.get("/stores/template")
async def download_excel_template(request: Request, authenticated: bool = Depends(get_current_user)):
    """Скачивание пустого Excel шаблона для загрузки магазинов"""
    try:
        data = [
            {"ID": 1001, "Кластер": "Пример кластера", "Регион": "Пример региона"},
            {"ID": 1002, "Кластер": "", "Регион": ""}
        ]
        df = pd.DataFrame(data)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Шаблон")
        output.seek(0)
        
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=stores_template.xlsx"}
        )
    except Exception as e:
        print(f"[ERROR] Ошибка создания шаблона: {e}")
        return RedirectResponse(url="/stores", status_code=303)


@app.get("/stores/export")
async def export_stores_excel(request: Request, authenticated: bool = Depends(get_current_user)):
    """Экспорт всех магазинов в Excel"""
    try:
        async with async_session() as session:
            result = await session.execute(select(Store).order_by(Store.id))
            stores = result.scalars().all()
        
        data = []
        for s in stores:
            data.append({
                "ID": s.id,
                "Кластер": s.cluster or "",
                "Регион": s.region or ""
            })
            
        df = pd.DataFrame(data)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Магазины")
        output.seek(0)
        
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=stores.xlsx"}
        )
    except Exception as e:
        print(f"[ERROR] Ошибка экспорта: {e}")
        import traceback; traceback.print_exc()
        return RedirectResponse(url="/stores", status_code=303)


@app.post("/stores/import")
async def import_stores_excel(request: Request, file: UploadFile = File(...), authenticated: bool = Depends(get_current_user)):
    """Импорт магазинов из Excel файла"""
    contents = await file.read()
    try:
        df = pd.read_excel(io.BytesIO(contents))
        async with async_session() as session:
            added = 0
            updated = 0
            
            for _, row in df.iterrows():
                store_id = row.get("ID") or row.get("id") or row.get("Номер") or row.get("номер")
                cluster = str(row.get("Кластер") or row.get("cluster") or "").strip()
                region = str(row.get("Регион") or row.get("region") or "").strip()
                
                if store_id and cluster and region:
                    try:
                        store_id_int = int(store_id)
                        existing = await session.get(Store, store_id_int)
                        if existing:
                            existing.cluster = cluster
                            existing.region = region
                            updated += 1
                        else:
                            new_store = Store(id=store_id_int, cluster=cluster, region=region)
                            session.add(new_store)
                            added += 1
                    except (ValueError, TypeError) as e:
                        print(f"[WARN] Пропущена строка с ID={store_id}: {e}")
            
            await session.commit()
            print(f"[INFO] Импорт завершён: добавлено {added}, обновлено {updated}")
    except Exception as e:
        print(f"[ERROR] Ошибка импорта: {e}")
        import traceback; traceback.print_exc()
    
    return RedirectResponse(url="/stores", status_code=303)



# ==================== SETTINGS ====================

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, authenticated: bool = Depends(get_current_user)):
    success = request.query_params.get("success") == "1"
    error = request.query_params.get("error")
    
    # Получаем список администраторов
    async with engine.begin() as conn:
        result = await conn.execute(text("SELECT id, username, created_at FROM admins ORDER BY created_at DESC"))
        admins = result.fetchall()
    
    return templates.TemplateResponse("settings.html", {
        "request": request, 
        "success": success, 
        "error": error,
        "admins": admins
    })


@app.post("/change-password")
async def change_password(request: Request, authenticated: bool = Depends(get_current_user)):
    form = await request.form()
    old_password = form.get("old_password", "")
    new_password = form.get("new_password", "")
    
    print(f"[CHANGE_PASSWORD] Попытка смены пароля")

    env_path = "/opt/super_kaizen/.env"
    current_password = ""
    try:
        with open(env_path, "r") as f:
            for line in f:
                if line.strip().startswith("ADMIN_PASSWORD="):
                    current_password = line.strip().split("=", 1)[1].strip()
                    break
    except Exception:
        pass

    if old_password != current_password:
        print(f"[CHANGE_PASSWORD] Неверный старый пароль!")
        return RedirectResponse(url="/settings?error=wrong_password", status_code=303)

    if len(new_password) < 6:
        return RedirectResponse(url="/settings?error=short_password", status_code=303)

    try:
        with open(env_path, "r") as f:
            lines = f.readlines()

        updated = False
        new_lines = []
        for line in lines:
            if line.strip().startswith("ADMIN_PASSWORD="):
                new_lines.append(f"ADMIN_PASSWORD={new_password}\n")
                updated = True
            else:
                new_lines.append(line)

        if not updated:
            new_lines.append(f"ADMIN_PASSWORD={new_password}\n")

        with open(env_path, "w") as f:
            f.writelines(new_lines)
        
        print(f"[CHANGE_PASSWORD] Пароль изменён. Перезапуск сервиса...")
        
        # Завершаем процесс, systemd автоматически перезапустит его
        import os
        os._exit(0)

    except Exception as e:
        print(f"[CHANGE_PASSWORD] Ошибка: {e}")
        return RedirectResponse(url=f"/settings?error={str(e)}", status_code=303)


@app.post("/add-admin")
async def add_admin(request: Request, authenticated: bool = Depends(get_current_user)):
    """Добавление нового администратора"""
    form = await request.form()
    username = form.get("username", "").strip()
    password = form.get("password", "").strip()
    
    if not username or not password:
        return RedirectResponse(url="/settings?error=missing_fields", status_code=303)
    
    if len(password) < 6:
        return RedirectResponse(url="/settings?error=short_password", status_code=303)
    
    # Хешируем пароль
    import hashlib
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    
    try:
        async with engine.begin() as conn:
            # Проверяем, существует ли уже такой username
            result = await conn.execute(
                text("SELECT id FROM admins WHERE username = :username"),
                {"username": username}
            )
            if result.fetchone():
                return RedirectResponse(url="/settings?error=admin_exists", status_code=303)
            
            # Добавляем нового администратора
            await conn.execute(
                text("INSERT INTO admins (username, password_hash) VALUES (:username, :password_hash)"),
                {"username": username, "password_hash": password_hash}
            )
        
        return RedirectResponse(url="/settings?success=admin_added", status_code=303)
    except Exception as e:
        print(f"[ERROR] Ошибка добавления админа: {e}")
        return RedirectResponse(url=f"/settings?error={str(e)}", status_code=303)


@app.post("/delete-admin/{admin_id}")
async def delete_admin(admin_id: int, request: Request, authenticated: bool = Depends(get_current_user)):
    """Удаление администратора"""
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM admins WHERE id = :id"),
                {"id": admin_id}
            )
        return RedirectResponse(url="/settings?success=admin_deleted", status_code=303)
    except Exception as e:
        print(f"[ERROR] Ошибка удаления админа: {e}")
        return RedirectResponse(url=f"/settings?error={str(e)}", status_code=303)



# ==================== SETTINGS ====================

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, authenticated: bool = Depends(get_current_user)):
    success = request.query_params.get("success") == "1"
    error = request.query_params.get("error")
    return templates.TemplateResponse("settings.html", {
        "request": request, "success": success, "error": error
    })


