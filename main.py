import asyncio
import json
import os
from datetime import datetime
from html import escape
import threading
import re

try:
    import psycopg2
    from psycopg2.extras import Json
except ImportError:
    psycopg2 = None
    Json = None

from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    BotCommand, BotCommandScopeDefault, BotCommandScopeChat,
    ChatMemberUpdated, ErrorEvent,
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from flask import Flask

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    gspread = None
    Credentials = None

try:
    from telethon import TelegramClient, utils
    from telethon.sessions import StringSession
    from telethon.tl.types import User as TgUser
except ImportError:
    TelegramClient = None
    StringSession = None
    TgUser = None

# =========================================================
# WEB-SERVER
# =========================================================
flask_app = Flask(__name__)

@flask_app.route("/")
def health():
    return "Bot is running!", 200

def run_web():
    port = int(os.environ.get("PORT", 8000))
    flask_app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web, daemon=True).start()

# =========================================================
# КОНФИГУРАЦИЯ
# =========================================================
TOKEN = os.environ.get("BOT_TOKEN", "").strip()
TG_API_ID_RAW = os.environ.get("TG_API_ID", "").strip()
TG_API_HASH = os.environ.get("TG_API_HASH", "").strip()
TG_SESSION_STRING = os.environ.get("TG_SESSION_STRING", "").strip()

try:
    TG_API_ID = int(TG_API_ID_RAW) if TG_API_ID_RAW else 0
except ValueError:
    TG_API_ID = 0

SUPER_ADMIN = 6166697485
ADMIN_IDS = {SUPER_ADMIN, 123456789, 6863392923, 1980341141}
GROUP_ID = -1002409536359
GROUP_LINK = "https://t.me/+DIWXSbc93A41YTA6"
BOT_NAME = "@Staff_Grand_Bot"
ANNOUNCE_TOPIC_ID = 126387

GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "").strip()
GOOGLE_SHEET_TITLE = os.environ.get("GOOGLE_SHEET_TITLE", "Staff Grand — База семьи").strip()

if not TOKEN:
    raise RuntimeError("BOT_TOKEN не найден")

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# =========================================================
# GLOBAL ERROR
# =========================================================
@dp.errors()
async def global_error_handler(event: ErrorEvent):
    exception = event.exception
    update = event.update
    error_name = type(exception).__name__
    error_text = str(exception)[:800]
    source = "неизвестно"
    try:
        if update.message: source = f"сообщение от {update.message.from_user.id}"
        elif update.callback_query: source = f"кнопка от {update.callback_query.from_user.id}"
    except:
        pass
    text = f"🚨 <b>Ошибка в боте</b>\n\n<b>Тип:</b> <code>{escape(error_name)}</code>\n<b>Откуда:</b> {escape(source)}\n\n<b>Текст:</b>\n<code>{escape(error_text)}</code>"
    try:
        await bot.send_message(SUPER_ADMIN, text)
    except:
        pass
    print(f"❌ ERROR: {error_name} — {error_text}")

# =========================================================
# TECH WORKS
# =========================================================
MAINTENANCE_MODE = False

def is_maintenance():
    return MAINTENANCE_MODE

def set_maintenance(value):
    global MAINTENANCE_MODE
    MAINTENANCE_MODE = bool(value)
    save_data()

MAINTENANCE_TEXT = "🛠 <b>Ведутся технические работы</b>\nБот отвечает с небольшой задержкой."

class MaintenanceMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data_ctx):
        user = None
        if isinstance(event, Message) and event.from_user:
            user = event.from_user
        elif isinstance(event, CallbackQuery) and event.from_user:
            user = event.from_user
        if user and user.id == SUPER_ADMIN:
            return await handler(event, data_ctx)
        if MAINTENANCE_MODE:
            try:
                if isinstance(event, Message):
                    await event.answer(MAINTENANCE_TEXT)
                elif isinstance(event, CallbackQuery) and event.message:
                    await event.message.answer(MAINTENANCE_TEXT)
            except:
                pass
            return await handler(event, data_ctx)
        return await handler(event, data_ctx)

dp.message.outer_middleware(MaintenanceMiddleware())
dp.callback_query.outer_middleware(MaintenanceMiddleware())

# =========================================================
# DATA & DATABASE
# =========================================================
DATA_FILE = "data.json"
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

def _db_connect():
    if psycopg2 is None or not DATABASE_URL:
        return None
    conninfo = DATABASE_URL + ("&sslmode=require" if "?" not in DATABASE_URL.lower() else "")
    try:
        return psycopg2.connect(conninfo, connect_timeout=10)
    except Exception as e:
        print(f"Ошибка подключения к БД: {e}")
        return None

def _db_init():
    conn = _db_connect()
    if conn is None:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS staff_grand_state (
                state_key VARCHAR(255) PRIMARY KEY,
                state_value JSONB
            );
        """)
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Ошибка инициализации БД: {e}")
        if conn:
            conn.close()
        return False

def _db_get_sync(key):
    conn = _db_connect()
    if conn is None:
        return None
    try:
        cur = conn.cursor()
        cur.execute("SELECT state_value FROM staff_grand_state WHERE state_key = %s", (key,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return row[0] if row else None
    except:
        if conn: conn.close()
        return None

def _db_set_sync(key, value):
    conn = _db_connect()
    if conn is None:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO staff_grand_state (state_key, state_value)
            VALUES (%s, %s) ON CONFLICT (state_key) DO UPDATE SET state_value = EXCLUDED.state_value
        """, (key, Json(value)))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except:
        if conn: conn.close()
        return False

def _read_local_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default

def _write_local_json(path, value):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
    except:
        pass

def _has_real_local_data(d):
    return bool(d.get("users") or d.get("applications") or d.get("admins") or d.get("zam_data"))

def load_data():
    if DATABASE_URL and psycopg2 is not None:
        existing = _db_get_sync("data")
        if isinstance(existing, dict) and _has_real_local_data(existing):
            return existing

        local = _read_local_json(DATA_FILE, None)
        if isinstance(local, dict) and _has_real_local_data(local):
            _db_set_sync("data", local)
            return local

    default_data = {
        "users": {}, "applications": {}, "admins": list(ADMIN_IDS),
        "zam_data": {}, "zam_stats": {}, "admin_usernames": {},
        "pending_admin_usernames": {}, "group_members": {}, "audit_events": [],
        "log_notify_enabled": False, "bot_settings": {"reminders_enabled": False, "pin_announcements": False},
        "last_reminders": {}, "reminders": [], "maintenance_mode": False,
        "google_sheet_url": "", "google_sheet_url_time": 0,
        "report_log": []
    }
    return _read_local_json(DATA_FILE, default_data)

def save_data():
    _write_local_json(DATA_FILE, data)
    if DATABASE_URL and psycopg2 is not None:
        _db_set_sync("data", data)

data = load_data()
data_global = data

# =========================================================
# LOGS & AUDIT
# =========================================================
LOG_FILE = "bot_activity.log"

def append_log_line(line):
    lines = load_logs()
    lines.append(line)
    save_logs(lines)

def load_logs():
    if DATABASE_URL and psycopg2 is not None:
        logs = _db_get_sync("logs")
        if isinstance(logs, list):
            return logs
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "r", encoding="utf-8") as f:
                    return f.readlines()
            except:
                pass
        return []
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            return f.readlines()
    except:
        return []

def save_logs(lines):
    lines = [str(x) for x in lines]
    if DATABASE_URL and psycopg2 is not None:
        _db_set_sync("logs", lines)
    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except:
        pass

def get_admin_display(actor_id):
    return f"Admin ({actor_id})"

def audit_record(actor_id, category, action, details="", command=""):
    try:
        events = data.setdefault("audit_events", [])
        events.append({
            "time": datetime.now().isoformat(timespec="seconds"),
            "actor_id": int(actor_id) if actor_id is not None else None,
            "category": category,
            "action": action,
            "details": str(details or ""),
            "command": str(command or "")
        })
        if len(events) > 5000:
            del events[:-5000]
        save_data()

        if data.get("log_notify_enabled"):
            log_text = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {escape(get_admin_display(actor_id or 0))} -> {action} {details}"
            asyncio.create_task(send_report_to_owner(log_text))
    except:
        pass

async def send_report_to_owner(log_text: str):
    try:
        await bot.send_message(SUPER_ADMIN, f"📜 <b>Новое действие в боте:</b>\n{log_text}")
    except:
        pass

def count_zam_answers(nick):
    return data.get("zam_stats", {}).get(nick, 0)

# =========================================================
# GOOGLE SHEETS
# =========================================================
def google_client():
    if not gspread or not Credentials or not GOOGLE_SERVICE_ACCOUNT_JSON:
        return None
    try:
        info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
        return gspread.authorize(creds)
    except:
        return None

def sync_google_sheets():
    client = google_client()
    if not client:
        return False, "Google Sheets не настроен"
    try:
        if GOOGLE_SHEET_ID:
            sh = client.open_by_key(GOOGLE_SHEET_ID)
        else:
            sh = client.create(GOOGLE_SHEET_TITLE)
        sheets = {
            "Участники": [["ID","Nickname","@username","Ранг","Орг","Ранг в орг","Пригласил","Статус"]],
            "Заявки": [["ID","TG ID","Nickname","@username","Ранг","Орг","Пригласил","Статус","Создано"]],
            "Замы": [["№","Nickname","@username","Приглашений"]],
            "Статистика": [["Показатель","Значение"]],
            "Журнал": [["Время","Кто","Действие","Подробности"]],
        }

        for title, values in sheets.items():
            try: 
                ws = sh.worksheet(title)
                ws.clear()
            except: 
                ws = sh.add_worksheet(title=title, rows=1000, cols=12)
            ws.update("A1", values)

        rows = []
        for uid, u in data.get("users", {}).items():
            rows.append([uid, u.get("nickname"), u.get("tag"), u.get("rank_fam"), u.get("organization"), u.get("rank_org"), u.get("inviter"), "принят"])
        if rows:
            ws = sh.worksheet("Участники")
            ws.update("A2", rows)

        rows = []
        for aid, a in data.get("applications", {}).items():
            d = a.get("data", {})
            rows.append([aid, a.get("user_id"), d.get("nickname"), d.get("tag"), d.get("rank_fam"), d.get("organization"), d.get("inviter"), a.get("status"), a.get("created")])
        if rows:
            ws = sh.worksheet("Заявки")
            ws.update("A2", rows)

        rows = []
        for i, (nick, info) in enumerate(data.get("zam_data", {}).items(), 1):
            rows.append([i, nick, info.get("tg_username"), count_zam_answers(nick)])
        if rows:
            ws = sh.worksheet("Замы")
            ws.update("A2", rows)

        data["google_sheet_url"] = sh.url
        data["google_sheet_url_time"] = datetime.now().timestamp()
        save_data()
        return True, sh.url
    except Exception as e:
        return False, str(e)[:500]

# =========================================================
# HANDLERS & HELPERS
# =========================================================
@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer("Привет! Добро пожаловать в бота семьи Staff Grand.")

async def init_telegram_user_client():
    pass

async def init_admins():
    pass

def ensure_admin_permissions():
    pass

async def set_command_scopes():
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Запустить бота"),
            BotCommand(command="help", description="Справка")
        ], scope=BotCommandScopeDefault())
    except Exception as e:
        print(f"Ошибка установки команд: {e}")

async def scheduled_reminder_worker():
    while True:
        await asyncio.sleep(3600)

async def reminder_worker():
    while True:
        await asyncio.sleep(60)

# =========================================================
# MAIN
# =========================================================
async def main():
    print("🤖 Бот запускается...")
    if not DATABASE_URL or not psycopg2:
        print("⚠️ DATABASE_URL не задан или psycopg2 не установлен, работаем на локальном JSON")
    else:
        if not _db_init():
            print("⚠️ Не удалось подключиться к PostgreSQL, fallback на JSON")

    await init_telegram_user_client()
    await init_admins()
    ensure_admin_permissions()
    await set_command_scopes()

    await bot.delete_webhook(drop_pending_updates=True)
    print("✅ Бот запущен!")

    asyncio.create_task(scheduled_reminder_worker())
    asyncio.create_task(reminder_worker())

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
