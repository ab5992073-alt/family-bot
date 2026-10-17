import asyncio
import logging
from datetime import datetime, timedelta
import pytz
from dotenv import load_dotenv
import os
import uuid
import json
from flask import Flask, request
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardBuilder, InputMediaPhoto, InputMediaVideo, InputMediaDocument, LabeledPrice
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import Router
import psycopg2
from psycopg2.extras import RealDictCursor
import gspread
from google.oauth2.service_account import Credentials
import threading
import time
from telethon import TelegramClient
import random
import re
from urllib.parse import urlparse, parse_qs
import aiohttp
import aioschedule
import atexit

load_dotenv()

# ====================== НАСТРОЙКИ ======================
SUPER_ADMIN = 6166697485
TG_API_ID = int(os.getenv("TG_API_ID"))
TG_API_HASH = os.getenv("TG_API_HASH")
TG_SESSION_STRING = os.getenv("TG_SESSION_STRING")

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# ====================== ЛОГГИНГ ======================
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# ====================== БАЗА ДАННЫХ ======================
DB_CONFIG = {
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT", 5432))
}

def get_db_connection():
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    return conn

# ====================== TELEGRAM CLINET ======================
client = TelegramClient("session", TG_API_ID, TG_API_HASH, session_string=TG_SESSION_STRING) if TG_SESSION_STRING else None

# ====================== GOOGLE SHEETS ======================
SHEET_NAME = "FamilyBot"
SHEET_ID = "1J5V9vQe8vK0rL9pL2mN7kX9pL2mN7kX"  # вставь свой

creds = Credentials.from_service_account_file("creds.json", scopes=["https://www.googleapis.com/auth/spreadsheets"])
gc = gspread.authorize(creds)
sheet = gc.open(SHEET_NAME).sheet1

# ====================== FLASK ======================
app = Flask(__name__)

# ====================== AIORGRAM ======================
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# ====================== СЛОВАРИ ======================
users = {}
admins = {}
apps = {}
zams = {}
announcements = []
reminders = []
notify_status = {}
gathering_active = False
gathering_users = []
gathering_timer = None
gathering_task = None

# ====================== ПРАВА ДОСТУПА ======================
rights = {
    "applications": False, "users": False, "stats": False, "announcements": False,
    "gathering": False, "reminders": False, "zams": False, "audit": False,
    "admins": False, "settings": False, "sheets": False, "status": False
}

# ====================== СОСТОЯНИЯ FSM ======================
class FSM(StatesGroup):
    fill_survey = State()
    edit_survey = State()
    set_time = State()
    set_text = State()

# ====================== КОМАНДЫ ======================
@dp.message(Command("start"))
async def start_cmd(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or "unknown"
    nickname = users.get(user_id, {}).get("nickname", "Без имени")

    await message.answer(
        f"👋 Привет, {nickname}!\n\n"
        f"Твой Telegram: @{username}\n"
        f"ID: {user_id}\n\n"
        f"Добро пожаловать в @Staff_Grand_Bot",
        reply_markup=admin_keyboard(user_id)
    )

# ====================== АДМИНЫ ======================
@dp.message(Command("add_admin"))
async def add_admin_cmd(message: Message):
    if message.from_user.id != SUPER_ADMIN:
        await message.answer("❌ Только владелец может добавлять админов.")
        return

    text = message.text.replace("/add_admin ", "").strip()

    if text.startswith("@"):
        async for dialog in client.iter_dialogs():
            if dialog.name.lower() == text[1:].lower() or dialog.entity.username == text[1:]:
                user_id = dialog.entity.id
                admins[user_id] = True
                await message.answer(f"✅ Добавлен админ: @{text[1:]} (ID {user_id})")
                return
    elif text.isdigit():
        user_id = int(text)
        admins[user_id] = True
        await message.answer(f"✅ Добавлен админ: ID {user_id}")
    else:
        await message.answer("Использование: /add_admin @username или /add_admin 1234567890")

# ====================== БАН ======================
@dp.message(Command("ban"))
async def ban_cmd(message: Message):
    if message.from_user.id not in admins and message.from_user.id != SUPER_ADMIN:
        await message.answer("❌ Нет прав.")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Укажи ID или @username: /ban 1234567890 или /ban @user")
        return

    target = args[1]

    if target.startswith("@"):
        for uid, data in users.items():
            if data.get("username") == target[1:]:
                await block_user(uid)
                await message.answer(f"✅ Забанен: @{target[1:]}")
                return
    elif target.isdigit():
        await block_user(int(target))
        await message.answer(f"✅ Забанен: ID {target}")
    else:
        await message.answer("Ошибка")

# ====================== БЛОКировка ======================
async def block_user(user_id):
    if user_id in apps:
        apps[user_id]["blocked"] = True
    for u in users:
        if u == user_id:
            users[u]["blocked"] = True
    # Бан в группе (через Telethon)
    try:
        await client.edit_permissions(
            channel=MAIN_GROUP_ID,
            user=user_id,
            until_date=datetime.now() + timedelta(days=365),
            send_messages=False
        )
    except:
        pass

# ====================== ТЕХ.РАБОТЫ ======================
@dp.message(Command("tech"))
async def tech_cmd(message: Message):
    if message.from_user.id != SUPER_ADMIN:
        await message.answer("❌ Только владелец.")
        return

    global tech_works
    tech_works = not tech_works
    status = "ВКЛ" if tech_works else "ВЫКЛ"
    await message.answer(f"🛠 Тех. работы: {status}")

# ====================== ТЕХ.РАБОТЫ ======================
tech_works = False

@dp.message()
async def global_tech_handler(message: Message):
    if tech_works:
        await message.answer(
            "🛠 Ведутся технические работы\n"
            "Бот может лагать или тормозить.\n\n"
            "Спасибо за понимание."
        )
    else:
        await message.answer("🛠 Тех. работы включены. Бот может отвечать с задержкой.")

# ====================== МЕНЮ ======================
def admin_keyboard(user_id):
    b = ReplyKeyboardBuilder()
    rows = []

    if user_id in admins or user_id == SUPER_ADMIN:
        rows.append([KeyboardButton(text="📋 Заявки"), KeyboardButton(text="👥 Участники")])
        if user_id == SUPER_ADMIN:
            rows.append([KeyboardButton(text="🛠 Тех. работы")])

    if user_id == SUPER_ADMIN:
        rows.append([KeyboardButton(text="🏠 Панель управления")])

    for row in rows:
        b.row(*row)

    return b.as_markup(resize_keyboard=True)

# ====================== ЗАПУСК ======================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
