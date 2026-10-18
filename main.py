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
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    KeyboardButton,
    BotCommand,
    BotCommandScopeDefault,
    BotCommandScopeChat,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    ChatMemberUpdated,
    ErrorEvent,
    ChatPermissions,
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
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
# WEB-SERVER ДЛЯ RENDER
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

telegram_user_client = None
telegram_user_ready = False

SUPER_ADMIN = 6166697485
ADMIN_IDS = {
    SUPER_ADMIN,
    123456789,
    6863392923,
    1980341141,
}

GROUP_ID = -1002409536359
GROUP_LINK = "https://t.me/+DIWXSbc93A41YTA6"
BOT_NAME = "@Staff_Grand_Bot"
ANNOUNCE_TOPIC_ID = 126387
BOT_START_TIME = datetime.now()

GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "").strip()
GOOGLE_SHEET_TITLE = os.environ.get("GOOGLE_SHEET_TITLE", "Staff Grand — База семьи").strip()


RANK_LIST = [
    "НОВИЧОК",
    "БандИТ",
    "Стрелок",
    "ФРАЕР",
    "ОХРАНИК",
    "СТ. ОХРАНИК",
    "РЕШАЛО",
    "ПОЛОЖЕНЕЦ",
    "ВОР",
    "Союз",
    "Нейтраль",
]

ORG_LIST = [
    "Правительство",
    "Воинская часть",
    "Больница г. Арзамас",
    "Больница г. Южный",
    "Новостная сеть",
    "Полиция г. Арзамас",
    "Полиция г. Южный",
    "ФСБ",
    "МВД-А",
    "МВД-Ю",
    "МЗ-А",
    "МЗ-Ю",
    "Курганская ОПГ",
    "Ореховская ОПГ",
    "Тамбовская ОПГ",
    "Кавказская ОПГ",
    "Не в организации",
]

if not TOKEN:
    raise RuntimeError(
        "Не найден BOT_TOKEN. Добавь переменную BOT_TOKEN в Render Environment."
    )

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode="HTML"),
)
dp = Dispatcher(storage=MemoryStorage())


# =========================================================
# FSM STATES (СОСТОЯНИЯ)
# =========================================================

class ReportStates(StatesGroup):
    waiting_for_report = State()
    waiting_for_reply = State()


# =========================================================
# ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ОШИБОК
# =========================================================

@dp.errors()
async def global_error_handler(event: ErrorEvent):
    exception = event.exception
    update = event.update

    error_name = type(exception).__name__
    error_text = str(exception)[:800]

    source = "неизвестно"
    try:
        if update.message:
            source = f"сообщение от {update.message.from_user.id}"
        elif update.callback_query:
            source = f"кнопка от {update.callback_query.from_user.id} (data={update.callback_query.data})"
        elif update.my_chat_member:
            source = "изменение статуса бота в чате"
    except Exception:
        pass

    text = (
        f"🚨 <b>Ошибка в боте</b>\n\n"
        f"<b>Тип:</b> <code>{escape(error_name)}</code>\n"
        f"<b>Откуда:</b> {escape(source)}\n\n"
        f"<b>Текст ошибки:</b>\n<code>{escape(error_text)}</code>"
    )

    try:
        await bot.send_message(SUPER_ADMIN, text)
    except Exception as e:
        print(f"⚠️ Не удалось отправить ошибку владельцу: {e}")

    print(f"❌ ERROR [{error_name}]: {error_text}")


# =========================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И АДМИНКА
# =========================================================

def is_super_admin(user_id: int) -> bool:
    return user_id == SUPER_ADMIN

def get_admins() -> list:
    return data_global.get("admins", list(ADMIN_IDS))

def is_admin(user_id: int) -> bool:
    return user_id in get_admins()

def admin_can(user_id: int, perm: str) -> bool:
    if is_super_admin(user_id):
        return True
    perms = data_global.get("admin_permissions", {}).get(str(user_id), {})
    return perms.get(perm, True)

def permission_denied_text(perm: str) -> str:
    return f"⛔ У вас нет доступа к функции '{perm}'."


# =========================================================
# MIDDLEWARE ТЕХНИЧЕСКИХ РАБОТ
# =========================================================

MAINTENANCE_TEXT = "🛠 <b>Ведутся технические работы</b>\nБот временно недоступен. Попробуйте позже."

class MaintenanceMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data_ctx):
        user = None
        chat = None

        if isinstance(event, Message):
            user = event.from_user
            chat = event.chat
        elif isinstance(event, CallbackQuery):
            user = event.from_user
            chat = event.message.chat if event.message else None

        if user and is_super_admin(user.id):
            return await handler(event, data_ctx)

        is_maint = data_global.get("maintenance_mode", False)

        if is_maint:
            if chat and chat.type == "private":
                try:
                    if isinstance(event, Message):
                        await event.answer(MAINTENANCE_TEXT)
                    elif isinstance(event, CallbackQuery):
                        await event.answer(MAINTENANCE_TEXT, show_alert=True)
                except Exception:
                    pass
            return

        return await handler(event, data_ctx)


dp.message.outer_middleware(MaintenanceMiddleware())
dp.callback_query.outer_middleware(MaintenanceMiddleware())


# =========================================================
# АВТОПРИВЯЗКА ОЖИДАЮЩИХ АДМИНОВ
# =========================================================

def normalize_username(value):
    if not value:
        return ""
    return value.strip().lstrip("@").lower()


def find_user_id_by_username(username):
    wanted = normalize_username(username)
    if not wanted:
        return None

    for uid, info in data_global.get("group_members", {}).items():
        if normalize_username(info.get("username")) == wanted:
            try:
                return int(uid)
            except (TypeError, ValueError):
                pass

    for uid, info in data_global.get("admin_usernames", {}).items():
        if normalize_username(info.get("username")) == wanted:
            try:
                return int(uid)
            except (TypeError, ValueError):
                pass

    for nick, info in data_global.get("zam_data", {}).items():
        if normalize_username(info.get("tg_username")) == wanted and info.get("tg_user_id"):
            return int(info["tg_user_id"])

    for uid, user in data_global.get("users", {}).items():
        tag = str(user.get("tag", ""))
        if normalize_username(tag) == wanted:
            try:
                return int(uid)
            except (TypeError, ValueError):
                pass

    return None


async def bind_pending_admin_for_user(user):
    if not user or user.is_bot:
        return False

    username = normalize_username(user.username)
    if not username:
        return False

    pending = data_global.setdefault("pending_admin_usernames", {})
    if username not in pending:
        return False

    if user.id in get_admins():
        pending.pop(username, None)
        save_data()
        return False

    data_global.setdefault("admins", []).append(user.id)
    data_global["admins"] = list(dict.fromkeys(data_global["admins"]))
    data_global.setdefault("admin_usernames", {})[str(user.id)] = {
        "username": user.username,
        "full_name": user.full_name or str(user.id),
    }
    pending.pop(username, None)
    save_data()

    try:
        if getattr(user, "id", None):
            await bot.send_message(user.id, "👑 Вы назначены администратором!")
    except Exception:
        pass
    return True


# =========================================================
# ОТСЛЕЖИВАНИЕ УЧАСТНИКОВ ГРУППЫ
# =========================================================

class GroupMemberTrackerMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, Message):
            try:
                user = event.from_user
                if user and not user.is_bot:
                    await bind_pending_admin_for_user(user)

                    if event.chat.id == GROUP_ID:
                        uid = str(user.id)
                        username = user.username or None
                        full_name = user.full_name or str(user.id)
                        old = data_global.get("group_members", {}).get(uid, {})
                        new = {
                            "id": user.id,
                            "username": username,
                            "full_name": full_name,
                            "last_seen": datetime.now().isoformat(),
                        }
                        if (
                            old.get("username") != username
                            or old.get("full_name") != full_name
                            or uid not in data_global.get("group_members", {})
                        ):
                            data_global.setdefault("group_members", {})[uid] = new
                            save_data()
                        else:
                            data_global["group_members"][uid]["last_seen"] = new["last_seen"]
            except Exception as e:
                print(f"⚠️ Ошибка обработки пользователя: {e}")

        return await handler(event, data)


data_global = {}
dp.message.outer_middleware(GroupMemberTrackerMiddleware())


# =========================================================
# РАСШИРЕННЫЙ ЖУРНАЛ ДЕЙСТВИЙ
# =========================================================

def audit_category_for_text(text: str) -> str:
    t = (text or "").lower().strip()
    if t.startswith("/all"):
        return "commands"
    if "зам" in t or "👑" in t:
        return "zams"
    if "админ" in t or "🛠" in t or "👑 админ" in t:
        return "admins"
    if "заяв" in t or "📋" in t:
        return "applications"
    if "участ" in t or "👥" in t:
        return "users"
    if "анк" in t or "📝" in t:
        return "surveys"
    return "commands" if t.startswith("/") else "other"


def audit_record(actor_id, category, action, details="", command=""):
    try:
        events = data.setdefault("audit_events", [])
        events.append({
            "time": datetime.now().isoformat(timespec="seconds"),
            "actor_id": int(actor_id) if actor_id is not None else None,
            "category": category,
            "action": action,
            "details": str(details or ""),
            "command": str(command or ""),
        })
        if len(events) > 5000:
            del events[:-5000]
        save_data()
    except Exception as e:
        print(f"⚠️ Не удалось записать audit: {e}")


class AuditMessageMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data_ctx):
        if isinstance(event, Message) and event.from_user and is_admin(event.from_user.id):
            text = event.text or event.caption or ""
            if text:
                category = audit_category_for_text(text)
                action = "нажал кнопку" if not text.startswith("/") else "выполнил команду"
                audit_record(event.from_user.id, category, action, text, text if text.startswith("/") else "")
        return await handler(event, data_ctx)


class AuditCallbackMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data_ctx):
        if isinstance(event, CallbackQuery) and event.from_user and is_admin(event.from_user.id):
            cd = event.data or ""
            category = "zams" if cd.startswith("zam") or cd.startswith("zams") else (
                "applications" if cd.startswith("accept:") or cd.startswith("reject:") or cd.startswith("apps") else (
                "users" if cd.startswith("users") or cd.startswith("user_") else (
                "admins" if cd.startswith("adm") else "other")))
            audit_record(event.from_user.id, category, "нажал inline-кнопку", cd, cd)
        return await handler(event, data_ctx)


class AdminPermissionMiddleware(BaseMiddleware):
    MESSAGE_PERMS = {
        "📋 Заявки": "applications",
        "👥 Участники": "users",
        "🟢 Статус бота": "status",
        "📢 Объявление": "announcements",
        "📢 Общий сбор": "gathering",
        "📊 Статистика": "stats",
        "👑 Замы": "zams",
        "📜 Журнал действий": "audit",
        "🛠 Админка": "admins",
        "☁️ Google Таблица": "sheets",
        "⚙️ Настройки": "settings",
        "🔔 Напоминания": "reminders",
        "🏠 Панель управления": "settings",
    }

    def callback_permission(self, cd):
        if cd.startswith(("apps_", "accept:", "reject:", "app_")): return "applications"
        if cd.startswith("user_message:"): return "participant_message"
        if cd.startswith(("users_", "user_")): return "users"
        if cd.startswith(("zam:", "zams_")): return "zams"
        if cd.startswith("audit_"): return "audit"
        if cd.startswith(("adm:", "admin_", "select_admin")) or cd == "owner_select_cancel": return "admins"
        if cd.startswith("perm:"): return "admins"
        if cd.startswith("sheets:"): return "sheets"
        if cd.startswith("set:"): return "settings"
        if cd.startswith("rem:"): return "reminders"
        if cd.startswith("announce_target:"): return "announcements"
        if cd.startswith("dash:"):
            action=cd.split(":",1)[1]
            return {"apps":"applications","users":"users","zams":"zams","stats":"stats","announce":"announcements","sbor":"gathering","audit":"audit","sheets":"sheets","admins":"admins","settings":"settings","reminders":"reminders"}.get(action)
        return None

    async def __call__(self, handler, event, data_ctx):
        uid = event.from_user.id if getattr(event, "from_user", None) else None
        if uid and is_admin(uid) and not is_super_admin(uid):
            perm = None
            if isinstance(event, Message):
                perm = self.MESSAGE_PERMS.get((event.text or "").strip())
            elif isinstance(event, CallbackQuery):
                perm = self.callback_permission(event.data or "")
            if perm and not admin_can(uid, perm):
                if isinstance(event, CallbackQuery):
                    await event.answer(permission_denied_text(perm), show_alert=True)
                else:
                    await event.answer(permission_denied_text(perm))
                return
        return await handler(event, data_ctx)


dp.message.outer_middleware(AdminPermissionMiddleware())
dp.callback_query.outer_middleware(AdminPermissionMiddleware())
dp.message.outer_middleware(AuditMessageMiddleware())
dp.callback_query.outer_middleware(AuditCallbackMiddleware())


@dp.chat_member()
async def group_member_update(event: ChatMemberUpdated):
    if event.chat.id != GROUP_ID:
        return

    member = event.new_chat_member.user
    if member.is_bot:
        return

    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status
    joined_from = {"left", "kicked"}
    active = {"member", "administrator", "creator", "restricted"}

    if old_status in joined_from and new_status in active:
        data_global.setdefault("group_members", {})[str(member.id)] = {
            "id": member.id,
            "username": member.username,
            "full_name": member.full_name,
            "joined_at": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat(),
            "status": new_status,
        }
        save_data()
        actor = event.from_user
        actor_text = f"@{actor.username}" if actor and actor.username else str(actor.id) if actor else "система"
        user_text = f"@{member.username}" if member.username else member.full_name
        try:
            await bot.send_message(
                SUPER_ADMIN,
                "🟢 <b>Новый участник в группе</b>\n\n"
                f"👤 {escape(user_text)}\n"
                f"🆔 <code>{member.id}</code>\n"
                f"➕ Добавил: {escape(actor_text)}"
            )
        except Exception:
            pass
        return

    if new_status in {"left", "kicked"} and old_status in active:
        info = data_global.setdefault("group_members", {}).setdefault(str(member.id), {})
        info.update({
            "id": member.id,
            "username": member.username,
            "full_name": member.full_name,
            "left_at": datetime.now().isoformat(),
            "status": new_status,
        })
        save_data()
        action = "кикнут" if new_status == "kicked" else "вышел из группы"
        actor = event.from_user
        actor_text = f"@{actor.username}" if actor and actor.username else str(actor.id) if actor else "система"
        user_text = f"@{member.username}" if member.username else member.full_name
        try:
            await bot.send_message(
                SUPER_ADMIN,
                f"🔴 <b>Участник {action}</b>\n\n"
                f"👤 {escape(user_text)}\n"
                f"🆔 <code>{member.id}</code>\n"
                f"👮 Действие от: {escape(actor_text)}"
            )
        except Exception:
            pass


# =========================================================
# БАЗА ДАННЫХ
# =========================================================

DATA_FILE = "data.json"
LOG_FILE = "bot_activity.log"
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

_db_warned = False


def _db_connect():
    if psycopg2 is None or not DATABASE_URL:
        return None

    conninfo = DATABASE_URL
    if "sslmode=" not in conninfo.lower():
        conninfo += ("&" if "?" in conninfo else "?") + "sslmode=require"

    try:
        return psycopg2.connect(conninfo, connect_timeout=10)
    except Exception as e:
        global _db_warned
        if not _db_warned:
            print(f"❌ PostgreSQL недоступен: {e}")
            _db_warned = True
        return None


def _db_init():
    conn = _db_connect()
    if not conn:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS staff_grand_state (
                        state_key TEXT PRIMARY KEY,
                        state_value JSONB NOT NULL
                    )
                """)
        return True
    except Exception as e:
        print(f"⚠️ Не удалось инициализировать PostgreSQL: {e}")
        return False
    finally:
        conn.close()


def _db_get(key):
    conn = _db_connect()
    if not conn:
        return None
    try:
        _db_init()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT state_value FROM staff_grand_state WHERE state_key = %s",
                (key,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return row[0]
    except Exception as e:
        print(f"⚠️ Ошибка чтения PostgreSQL ({key}): {e}")
        return None
    finally:
        conn.close()


def _db_set(key, value):
    conn = _db_connect()
    if not conn:
        return False
    try:
        _db_init()
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO staff_grand_state (state_key, state_value)
                    VALUES (%s, %s)
                    ON CONFLICT (state_key)
                    DO UPDATE SET state_value = EXCLUDED.state_value
                    """,
                    (key, Json(value)),
                )
        return True
    except Exception as e:
        print(f"⚠️ Ошибка записи PostgreSQL ({key}): {e}")
        return False
    finally:
        conn.close()


def _read_local_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_local_json(path, value):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Не удалось сохранить {path}: {e}")


def _has_real_local_data(local):
    if not isinstance(local, dict):
        return False
    if local.get("users") or local.get("applications") or local.get("zam_data"):
        return True
    return False


def load_data():
    if DATABASE_URL and psycopg2 is not None:
        existing = _db_get("data")
        if isinstance(existing, dict) and _has_real_local_data(existing):
            return existing

        local = _read_local_json(DATA_FILE, None)
        if isinstance(local, dict) and _has_real_local_data(local):
            print("🔄 Найден локальный data.json — выполняю импорт в PostgreSQL...")
            if _db_set("data", local):
                return local

        if isinstance(existing, dict):
            return existing

    local = _read_local_json(DATA_FILE, None)
    if isinstance(local, dict):
        return local

    return {
        "users": {},
        "applications": {},
        "admins": list(ADMIN_IDS),
        "zam_stats": {},
        "zam_data": {},
        "log_notify_enabled": False,
        "admin_usernames": {},
    }


_db_save_task = None
_db_save_pending = False

async def _flush_db_save():
    global _db_save_task, _db_save_pending
    try:
        while _db_save_pending:
            _db_save_pending = False
            await asyncio.sleep(0.25)
            snapshot = json.loads(json.dumps(data, ensure_ascii=False))
            if DATABASE_URL and psycopg2 is not None:
                await asyncio.to_thread(_db_set, "data", snapshot)
    except Exception as e:
        print(f"⚠️ Ошибка фонового сохранения PostgreSQL: {e}")
    finally:
        _db_save_task = None


def save_data():
    global _db_save_task, _db_save_pending
    _write_local_json(DATA_FILE, data)
    
    # Автоматическая синхронизация убрана, чтобы не превышать лимиты Google API.
    # Таблица обновляется вручную через кнопку «☁️ Google Таблица».

    if not (DATABASE_URL and psycopg2 is not None):
        return
    _db_save_pending = True
    try:
        loop = asyncio.get_running_loop()
        if _db_save_task is None or _db_save_task.done():
            _db_save_task = loop.create_task(_flush_db_save())
    except RuntimeError:
        _db_set("data", json.loads(json.dumps(data, ensure_ascii=False)))


def load_logs():
    if DATABASE_URL and psycopg2 is not None:
        logs = _db_get("logs")
        if isinstance(logs, list):
            return [str(x) for x in logs]
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                if lines:
                    _db_set("logs", lines)
                    return lines
            except Exception:
                pass
        return []

    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            return f.readlines()
    except Exception:
        return []


def save_logs(lines):
    lines = [str(x) for x in lines]
    if DATABASE_URL and psycopg2 is not None:
        _db_set("logs", lines)

    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except Exception:
        pass


def append_log_line(line):
    lines = load_logs()
    lines.append(line)
    save_logs(lines)


data = load_data()
data_global = data

defaults = {
    "users": {},
    "applications": {},
    "admins": list(ADMIN_IDS),
    "zam_stats": {},
    "zam_data": {},
    "log_notify_enabled": False,
    "admin_usernames": {},
    "pending_admin_usernames": {},
    "group_members": {},
    "initial_zams_installed": False,
    "audit_events": [],
    "notify_settings": {},
    "bot_settings": {"reminders_enabled": False, "pin_announcements": False},
    "last_reminders": {},
    "reminders": [],
    "admin_permissions": {},
    "maintenance_mode": False,
    "reports": {},
}

changed = False
for key, default in defaults.items():
    if key not in data:
        data[key] = default
        changed = True

if SUPER_ADMIN not in data["admins"]:
    data["admins"].append(SUPER_ADMIN)
    changed = True

if changed:
    save_data()


# =========================================================
# TELEGRAM-АККАУНТ ВЛАДЕЛЬЦА
# =========================================================

async def init_telegram_user_client():
    global telegram_user_client, telegram_user_ready

    if TelegramClient is None or not (TG_API_ID and TG_API_HASH and TG_SESSION_STRING):
        return False

    try:
        telegram_user_client = TelegramClient(
            StringSession(TG_SESSION_STRING),
            TG_API_ID,
            TG_API_HASH,
        )
        await telegram_user_client.connect()

        if not await telegram_user_client.is_user_authorized():
            await telegram_user_client.disconnect()
            telegram_user_client = None
            return False

        me = await telegram_user_client.get_me()
        print(f"✅ Telegram user-session подключена: {getattr(me, 'username', None) or me.id}")
        telegram_user_ready = True
        return True
    except Exception as e:
        print(f"⚠️ Не удалось подключить Telegram user-session: {e}")
        telegram_user_client = None
        telegram_user_ready = False
        return False


def count_zam_answers(nick):
    return data.get("zam_stats", {}).get(nick, {}).get("count", 0)


# =========================================================
# GOOGLE SHEETS
# =========================================================

def google_client():
    if not gspread or not Credentials or not GOOGLE_SERVICE_ACCOUNT_JSON:
        return None
    try:
        info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        creds = Credentials.from_service_account_info(
            info,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ],
        )
        return gspread.authorize(creds)
    except Exception as e:
        print(f"⚠️ Ошибка авторизации Google: {e}")
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
            "Участники": [["ID", "Nickname", "@username", "Ранг", "Орг", "Пригласил", "Статус"]],
            "Заявки": [["ID", "TG ID", "Nickname", "@username", "Ранг", "Орг", "Пригласил", "Статус", "Создано"]],
            "Замы": [["№", "Nickname", "@username", "Приглашений"]],
            "Статистика": [["Показатель", "Значение"]],
            "Журнал": [["Время", "Кто", "Действие", "Подробности"]],
        }

        for title, values in sheets.items():
            try:
                ws = sh.worksheet(title)
                ws.clear()
            except Exception:
                ws = sh.add_worksheet(title=title, rows=1000, cols=12)
            ws.update(range_name="A1", values=values)

        rows = []
        for uid, u in data.get("users", {}).items():
            rows.append([uid, u.get("nickname"), u.get("tag"), u.get("rank_fam"), u.get("organization"), u.get("inviter"), "принят"])
        if rows:
            ws = sh.worksheet("Участники")
            ws.update(range_name="A2", values=rows)

        rows = []
        for aid, a in data.get("applications", {}).items():
            d = a.get("data", {})
            rows.append([aid, a.get("user_id"), d.get("nickname"), d.get("tag"), d.get("rank_fam"), d.get("organization"), d.get("inviter"), a.get("status"), a.get("created")])
        if rows:
            ws = sh.worksheet("Заявки")
            ws.update(range_name="A2", values=rows)

        rows = []
        for i, (nick, info) in enumerate(data.get("zam_data", {}).items(), 1):
            rows.append([i, nick, info.get("tg_username"), count_zam_answers(nick)])
        if rows:
            ws = sh.worksheet("Замы")
            ws.update(range_name="A2", values=rows)

        data["google_sheet_url"] = sh.url
        data["google_sheet_url_time"] = datetime.now().timestamp()
        return True, sh.url
    except Exception as e:
        return False, str(e)[:500]


# =========================================================
# КЛАВИАТУРЫ
# =========================================================

def get_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    if is_admin(user_id):
        builder.row(KeyboardButton(text="📋 Заявки"), KeyboardButton(text="👥 Участники"))
        builder.row(KeyboardButton(text="🟢 Статус бота"), KeyboardButton(text="📢 Объявление"))
        builder.row(KeyboardButton(text="📢 Общий сбор"), KeyboardButton(text="📊 Статистика"))
        builder.row(KeyboardButton(text="👑 Замы"), KeyboardButton(text="📜 Журнал действий"))
        builder.row(KeyboardButton(text="🛠 Админка"), KeyboardButton(text="☁️ Google Таблица"))
        builder.row(KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="🔔 Напоминания"))
    else:
        builder.row(KeyboardButton(text="📝 Подать заявку"))
        builder.row(KeyboardButton(text="📩 Репорт / Связь"))
        builder.row(KeyboardButton(text="📊 Мой статус"))
    return builder.as_markup(resize_keyboard=True)


# =========================================================
# СИСТЕМА РЕПОРТОВ (ЖАЛОБЫ И ОБРАЩЕНИЯ)
# =========================================================

@dp.message(F.text == "📩 Репорт / Связь")
async def cmd_report_start(message: Message, state: FSMContext):
    await state.set_state(ReportStates.waiting_for_report)
    await message.answer(
        "✍️ <b>Напишите ваше сообщение или жалобу для администрации:</b>\n\n"
        "Опишите суть вопроса максимально подробно. Для отмены введите /cancel."
    )


@dp.message(Command("cancel"), StateFilter(ReportStates))
async def cmd_report_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Действие отменено.", reply_markup=get_main_keyboard(message.from_user.id))


@dp.message(ReportStates.waiting_for_report)
async def process_report_text(message: Message, state: FSMContext):
    user = message.from_user
    text = message.text or message.caption or ""

    if not text:
        await message.answer("⚠️ Пожалуйста, отправьте текстовое сообщение.")
        return

    report_id = str(int(datetime.now().timestamp()))
    data.setdefault("reports", {})[report_id] = {
        "user_id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "text": text,
        "status": "open",
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    save_data()
    await state.clear()

    await message.answer(
        "✅ <b>Ваше обращение отправлено администрации!</b>\n"
        "Вам ответят в ближайшее время.",
        reply_markup=get_main_keyboard(user.id)
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💬 Ответить", callback_data=f"reply_report:{report_id}"),
            InlineKeyboardButton(text="❌ Закрыть", callback_data=f"close_report:{report_id}")
        ]
    ])

    user_info = f"@{user.username}" if user.username else f"ID: {user.id}"
    admin_msg = (
        f"📩 <b>Новое обращение #{report_id}</b>\n\n"
        f"<b>От кого:</b> {escape(user.full_name)} ({user_info})\n"
        f"<b>Текст:</b>\n{escape(text)}"
    )

    for admin_id in get_admins():
        try:
            await bot.send_message(admin_id, admin_msg, reply_markup=kb)
        except Exception:
            pass


@dp.callback_query(F.data.startswith("reply_report:"))
async def cb_reply_report(callback: CallbackQuery, state: FSMContext):
    report_id = callback.data.split(":")[1]
    rep = data.get("reports", {}).get(report_id)

    if not rep:
        await callback.answer("Репорт не найден.", show_alert=True)
        return

    await state.update_data(reply_report_id=report_id)
    await state.set_state(ReportStates.waiting_for_reply)

    await callback.message.answer(
        f"✍️ <b>Введите ответ на обращение #{report_id} для {escape(rep['full_name'])}:</b>"
    )
    await callback.answer()


@dp.message(ReportStates.waiting_for_reply)
async def process_report_reply(message: Message, state: FSMContext):
    state_data = await state.get_data()
    report_id = state_data.get("reply_report_id")
    rep = data.get("reports", {}).get(report_id)

    if not rep:
        await message.answer("⚠️ Обращение не найдено.")
        await state.clear()
        return

    reply_text = message.text or ""
    try:
        await bot.send_message(
            rep["user_id"],
            f"📩 <b>Ответ администрации на ваше обращение:</b>\n\n{escape(reply_text)}"
        )
        await message.answer(f"✅ Ответ успешно отправлен пользователю.")
        rep["status"] = "answered"
        save_data()
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить ответ пользователю: {e}")

    await state.clear()


@dp.callback_query(F.data.startswith("close_report:"))
async def cb_close_report(callback: CallbackQuery):
    report_id = callback.data.split(":")[1]
    rep = data.get("reports", {}).get(report_id)

    if rep:
        rep["status"] = "closed"
        save_data()

    await callback.message.edit_text(
        f"{callback.message.text}\n\n🔒 <b>Обращение закрыто ({escape(callback.from_user.full_name)})</b>"
    )
    await callback.answer("Обращение закрыто.")


# =========================================================
# ОСНОВНЫЕ КОМАНДЫ И ОБРАБОТЧИКИ
# =========================================================

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    
    user = message.from_user
    await bind_pending_admin_for_user(user)

    text = (
        f"👋 <b>Привет, {escape(user.full_name)}!</b> ✨\n\n"
        f"👑 Добро пожаловать в официальный бот семьи <b>Staff Grand</b>! 🏆\n\n"
        f"⚡ Выберите нужный раздел в меню ниже, чтобы продолжить: 👇"
    )

    await message.answer(
        text,
        reply_markup=get_main_keyboard(user.id)
    )


@dp.message(F.text == "🟢 Статус бота")
async def cmd_status(message: Message):
    if not is_admin(message.from_user.id):
        return

    uptime = str(datetime.now() - BOT_START_TIME).split('.')[0]
    maint = "Включен 🛠" if data.get("maintenance_mode") else "Выключен 🟢"

    text = (
        f"📊 <b>Статус бота</b>\n\n"
        f"<b>Время работы:</b> {uptime}\n"
        f"<b>Режим тех. работ:</b> {maint}\n"
        f"<b>Всего участников:</b> {len(data.get('users', {}))}\n"
        f"<b>Всего заявок:</b> {len(data.get('applications', {}))}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🛠 Переключить тех. работы",
            callback_query_data="toggle_maintenance"
        )]
    ])

    await message.answer(text, reply_markup=kb)


@dp.callback_query(F.data == "toggle_maintenance")
async def cb_toggle_maintenance(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Только владелец может переключать тех. работы!", show_alert=True)
        return

    current = data.get("maintenance_mode", False)
    data["maintenance_mode"] = not current
    save_data()

    status_str = "ВКЛЮЧЕН 🛠" if data["maintenance_mode"] else "ВЫКЛЮЧЕН 🟢"
    await callback.answer(f"Режим тех. работ: {status_str}", show_alert=True)
    
    uptime = str(datetime.now() - BOT_START_TIME).split('.')[0]
    maint = "Включен 🛠" if data.get("maintenance_mode") else "Выключен 🟢"

    text = (
        f"📊 <b>Статус бота</b>\n\n"
        f"<b>Время работы:</b> {uptime}\n"
        f"<b>Режим тех. работ:</b> {maint}\n"
        f"<b>Всего участников:</b> {len(data.get('users', {}))}\n"
        f"<b>Всего заявок:</b> {len(data.get('applications', {}))}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🛠 Переключить тех. работы",
            callback_query_data="toggle_maintenance"
        )]
    ])

    await callback.message.edit_text(text, reply_markup=kb)


@dp.message(F.text == "☁️ Google Таблица")
async def cmd_google_sheets(message: Message):
    if not is_admin(message.from_user.id):
        return

    msg = await message.answer("🔄 Выполняю синхронизацию с Google Таблицей...")
    ok, url_or_err = sync_google_sheets()

    if ok:
        await msg.edit_text(
            f"✅ <b>Google Таблица успешно обновлена!</b>\n\n🔗 <a href='{url_or_err}'>Открыть таблицу</a>"
        )
    else:
        await msg.edit_text(f"❌ <b>Ошибка синхронизации:</b>\n<code>{escape(url_or_err)}</code>")


# =========================================================
# ИНИЦИАЛИЗАЦИЯ И ЗАПУСК
# =========================================================

async def set_command_scopes():
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Запустить бота"),
            BotCommand(command="cancel", description="Отмена действия"),
        ], scope=BotCommandScopeDefault())
    except Exception as e:
        print(f"Ошибка установки команд: {e}")


async def scheduled_reminder_worker():
    while True:
        await asyncio.sleep(3600)


async def reminder_worker():
    while True:
        await asyncio.sleep(60)


async def main():
    print("🤖 Бот запускается...")

    if DATABASE_URL and psycopg2:
        if _db_init():
            print("✅ Подключение к PostgreSQL выполнено.")
        else:
            print("⚠️ Ошибка инициализации PostgreSQL.")
    else:
        print("ℹ️ Работаем в режиме локального сохранения.")

    await init_telegram_user_client()
    await set_command_scopes()

    await bot.delete_webhook(drop_pending_updates=True)
    print("✅ Бот запущен и готов к работе!")

    asyncio.create_task(scheduled_reminder_worker())
    asyncio.create_task(reminder_worker())

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
