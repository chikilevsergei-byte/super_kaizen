from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
import secrets
from datetime import datetime
from sqlalchemy import select, func
from app.database import async_session
from app.models import User, Problem, Feedback, Store
from app.config import settings
import os

app = FastAPI(title="Super Kaizen Admin")

# Секретный ключ для сессий
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex(32))
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# Шаблоны и статика
templates = Jinja2Templates(directory="app/web/templates")
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")

# Пароль администратора из settings
ADMIN_PASSWORD = settings.ADMIN_PASSWORD

def get_current_user(request: Request):
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return True

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login(request: Request):
    form = await request.form()
    password = form.get("password")
    
    print(f"🔐 Попытка входа с паролем: {password}")
    print(f"🔐 Ожидаемый пароль: {ADMIN_PASSWORD}")
    print(f"🔐 Совпадение: {password == ADMIN_PASSWORD}")
    
    if password == ADMIN_PASSWORD:
        request.session["authenticated"] = True
        print(f"✅ Успешный вход! Сессия: {request.session}")
        return RedirectResponse(url="/", status_code=303)
    
    print(f"❌ Неверный пароль")
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": "Неверный пароль"
    })

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login")

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, authenticated: bool = Depends(get_current_user)):
    print(f"📊 Запрос к dashboard, сессия: {request.session}")
    async with async_session() as session:
        total_users = await session.execute(select(func.count(User.tg_id)))
        total_problems = await session.execute(select(func.count(Problem.id)))
        total_feedback = await session.execute(select(func.count(Feedback.id)))
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "total_users": total_users.scalar(),
        "total_problems": total_problems.scalar(),
        "total_feedback": total_feedback.scalar()
    })

@app.get("/problems", response_class=HTMLResponse)
async def problems_list(request: Request, authenticated: bool = Depends(get_current_user)):
    async with async_session() as session:
        result = await session.execute(
            select(Problem).order_by(Problem.created_at.desc())
        )
        problems = result.scalars().all()
    
    return templates.TemplateResponse("problems.html", {
        "request": request,
        "problems": problems
    })

@app.get("/feedback", response_class=HTMLResponse)
async def feedback_list(request: Request, authenticated: bool = Depends(get_current_user)):
    async with async_session() as session:
        result = await session.execute(
            select(Feedback).order_by(Feedback.created_at.desc())
        )
        feedbacks = result.scalars().all()
    
    return templates.TemplateResponse("feedback.html", {
        "request": request,
        "feedbacks": feedbacks
    })

@app.get("/users", response_class=HTMLResponse)
async def users_list(request: Request, authenticated: bool = Depends(get_current_user)):
    async with async_session() as session:
        result = await session.execute(
            select(User).order_by(User.tg_id.desc())
        )
        users = result.scalars().all()
    
    return templates.TemplateResponse("users.html", {
        "request": request,
        "users": users
    })

@app.get("/stores", response_class=HTMLResponse)
async def stores_list(request: Request, authenticated: bool = Depends(get_current_user)):
    async with async_session() as session:
        result = await session.execute(
            select(Store).order_by(Store.name)
        )
        stores = result.scalars().all()
    
    return templates.TemplateResponse("stores.html", {
        "request": request,
        "stores": stores
    })
