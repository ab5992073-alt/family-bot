import asyncio
import logging
from datetime import datetime, timedelta
import pytz
import os
import uuid
import json
import time
import threading
import psycopg2
from psycopg2.extras import RealDictCursor
import gspread
from google.oauth2.service_account import Credentials
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
from telethon import TelegramClient
import aiohttp
import aioschedule
import random
import re
from urllib.parse import urlparse, parse_qs

load_dotenv()

# ====================== НАСТРОЙКИ ======================
SUPER_ADMIN = 6166697485
TG_API_ID = int(os.getenv("TG_API_ID"))
TG_API_HASH = os.getenv("TG_API_HASH")
TG_SESSION_STRING = os.getenv("TG_SESSION_STRING")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ====================== ЛОГГИНГ ======================
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# ====================== БАЗА ======================
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

# ====================== TELEGRAM ======================
client = TelegramClient("session", TG_API_ID, TG_API_HASH, session_string=TG_SESSION_STRING) if TG_SESSION_STRING else None

# ====================== GOOGLE SHEETS ======================
SHEET_NAME = "FamilyBot"
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

# ====================== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ======================
users = {}
admins = {}
apps = {}
zams = {}
announcements = []
reminders = []
gathering_active = False
gathering_users = []
tech_works = False
uptime_start = datetime.now()
ping = 0
last_ping = datetime.now()

# ====================== ПРАВА ======================
rights = {
    "applications": False, "users": False, "stats": False, "announcements": False,
    "gathering": False, "reminders": False, "zams": False, "audit": False,
    "admins": False, "settings": False, "sheets": False, "status": False
}

# ====================== КОМАНДЯ /STATUS ======================
@dp.message(Command("status"))
async def status_cmd(message: Message):
    user_id = message.from_user.id

    if user_id != SUPER_ADMIN and user_id not in admins:
        await message.answer("❌ Нет прав на просмотр статуса.")
        return

    uptime = datetime.now() - uptime_start
    uptime_str = str(uptime).split(".")[0]

    global ping, last_ping
    ping = int((datetime.now() - last_ping).total_seconds() * 1000)

    rights_text = "\n".join([f"✅ {k}" if v else f"❌ {k}" for k, v in rights.items()])

    await message.answer(
        f"<b>📊 СТАТУС БОТА</b>\n\n"
        f"• <b>Версия:</b> 1.0.0\n"
        f"• <b>Пинг:</b> {ping} мс\n"
        f"• <b>Работает:</b> {uptime_str}\n"
        f"• <b>Последний деплои:</b> {uptime_start.strftime('%H:%M:%S')}\n"
        f"• <b>Тех. работы:</b> {'🟢 ВКЛ' if tech_works else '🔴 ВЫКЛ'}\n\n"
        f"<b>Права:</b>\n{rights_text}",
        parse_mode=ParseMode.HTML
    )

# ====================== ПИНГ ======================
async def update_ping():
    global ping, last_ping
    while True:
        try:
            start = time.time()
            await bot.get_me()
            ping = int((time.time() - start) * 1000)
            last_ping = datetime.now()
        except:
            ping = 999
        await asyncio.sleep(5)

# ====================== ТЕХ.РАБОТЫ ======================
@dp.message(Command("tech"))
async def tech_cmd(message: Message):
    if message.from_user.id != SUPER_ADMIN:
        await message.answer("❌ Только владелец.")
        return

    global tech_works
    tech_works = not tech_works
    await message.answer(f"🛠 Тех. работы: {'ВКЛ' if tech_works else 'ВЫКЛ'}")

# ====================== ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ======================
@dp.message()
async def global_handler(message: Message):
    if tech_works:
        await message.answer(
            "🛠 Ведутся технические работы\n"
            "Бот может отвечать с задержкой."
        )
    else:
        await message.answer("🛠 Тех. работы включены. Бот может лагать.")

# ====================== ЗАПУСК ======================
async def main():
    asyncio.create_task(update_ping())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
