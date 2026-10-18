import asyncio
import json
import os
from datetime import datetime
from html import escape
import threading
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
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    KeyboardButton,
    BotCommand,
    BotCommandScopeDefault,
    BotCommandScopeChat,
    ReplyKeyboardRemove,
    ChatMemberUpdated,
    ErrorEvent,
    ChatPermissions,
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

# =============
# WEB-SERVER ДЛЯ RENDER
# =============
flask_app = Flask(__name__)
@flask_app.route("/")
def health():
    return "Bot is running!", 200
def run_web():
    port = int(os.environ.get("PORT", 8000))
    flask_app.run(host="0.0.0.0", port=port)
threading.Thread(target=run_web, daemon=True).start()

# =============
# КОНФИГУРАЦИЯ
# =============
TOKEN = os.environ.get("BOT_TOKEN", "").strip()
# Telegram user-account API (для списка личных диалогов владельца).
# Получается на https://my.telegram.org → API development tools.
TG_API_ID_RAW = os.environ.get("TG_API_ID", "").strip()
TG_API_HASH = os.environ.get("TG_API_HASH", "").strip()
TG_SESSION_STRING = os.environ.get("TG_SESSION_STRING", "").strip()
try:
    TG_API_ID = int(TG_API_ID_RAW) if TG_API_ID_RAW else 0
except ValueError:
    TG_API_ID = 0
telegram_user_client = None
telegram_user_ready = False

# ВЛАДЕЛЕЦ БОТА — твой Telegram ID
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

# Google Sheets (необязательно). Для включения добавь в Render:
# GOOGLE_SERVICE_ACCOUNT_JSON — JSON сервисного аккаунта Google
# GOOGLE_SHEET_ID — ID существующей таблицы (необязательно: бот может создать новую)
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
dp = Dispatcher()

# =============
# ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ОШИБОК → только владельцу
# =============
@dp.errors()
async def global_error_handler(event: ErrorEvent):
    """Ловит любые необработанные ошибки и присылает только владельцу."""
    exception = event.exception
    update = event.update

    # Краткое описание на русском
    error_name = type(exception).__name__
    error_text = str(exception)[:800]

    # Откуда пришла ошибка
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

    # Печатаем в логи Render тоже
    print(f"❌ ERROR [{error_name}]: {error_text}")

# =============
# АВТОПРИВЯЗКА ОЖИДАЮЩИХ АДМИНОВ
# =============
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
        await set_command_scopes()
    except Exception:
        pass

    try:
        # Подтверждение только в личном чате, чтобы не засорять группу.
        if getattr(user, "id", None):
            # Telegram Bot API может отправить только если пользователь уже открыл чат с ботом.
            await bot.send_message(user.id, "👑 Вы назначены администратором!")
    except Exception:
        pass
    return True

# =============
# ОТСЛЕЖИВАНИЕ УЧАСТНИКОВ ГРУППЫ
# =============
class GroupMemberTrackerMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, Message):
            try:
                user = event.from_user
                if user and not user.is_bot:
                    # ВАЖНО: проверяем ожидающих админов для ВСЕХ сообщений,
                    # включая личные сообщения боту. Раньше проверка была только
                    # внутри группы, поэтому пользователь мог написать боту, а
                    # username так и оставался в ожидании.
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

# data создаётся ниже; здесь используем ссылку, которая будет назначена до polling.
data_global = {}
dp.message.outer_middleware(GroupMemberTrackerMiddleware())

# =============
# РАСШИРЕННЫЙ ЖУРНАЛ ДЕЙСТВИЙ
# =============
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
    """Уведомляет владельца о входе/добавлении и выходе/кике."""
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

# =============
# БАЗА ДАННЫХ
# =============
DATA_FILE = "data.json"
LOG_FILE = "bot_activity.log"
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
_db_warned = False

def _db_connect():
    if psycopg2 is None:
        raise RuntimeError("Не установлен psycopg2-binary. Добавь его в requirements.txt.")
    if not DATABASE_URL:
        raise RuntimeError("Не задан DATABASE_URL. Бот остановлен, чтобы не потерять данные.")

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

def _db_delete(key):
    conn = _db_connect()
    if not conn:
        return False
    try:
        _db_init()
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM staff_grand_state WHERE state_key = %s",
                    (key,),
                )
        return True
    except Exception as e:
        print(f"⚠️ Ошибка удаления PostgreSQL ({key}): {e}")
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
    if local.get("users"):
        return True
    if local.get("applications"):
        return True
    if local.get("admins") and set(local.get("admins", [])) - set(ADMIN_IDS):
        return True
    if local.get("zam_data"):
        return True
    if local.get("zam_stats"):
        return True
    if local.get("admin_usernames"):
        return True
    if local.get("group_members"):
        return True
    if local.get("pending_admin_usernames"):
        return True
    return False

def load_data():
    # PostgreSQL — главный источник. Никогда не заменяем существующую
    # непустую БД пустым локальным data.json после redeploy.
    if DATABASE_URL and psycopg2 is not None:
        existing = _db_get("data")
        if isinstance(existing, dict) and _has_real_local_data(existing):
            return existing

    local = _read_local_json(DATA_FILE, None)
    if isinstance(local, dict) and _has_real_local_data(local):
        print("🔄 Найден локальный data.json — выполняю однократный импорт в PostgreSQL...")
        if _db_set("data", local):
            return local

    if isinstance(existing, dict):
        return existing

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
    """Быстро сохраняет локальную копию, а PostgreSQL обновляет в фоне.
    Это убирает задержки на каждом нажатии кнопки/записи журнала.
    """
    global _db_save_task, _db_save_pending
    _write_local_json(DATA_FILE, data)
    if not (DATABASE_URL and psycopg2 is not None):
        return
    _db_save_pending = True
    try:
        loop = asyncio.get_running_loop()
        if _db_save_task is None or _db_save_task.done():
            _db_save_task = loop.create_task(_flush_db_save())
    except RuntimeError:
        # Вне event loop (например, при старте/миграции) сохраняем сразу.
        _db_set("data", json.loads(json.dumps(data, ensure_ascii=False)))

async def save_data_now():
    """Принудительно дождаться записи текущего состояния в PostgreSQL."""
    global _db_save_pending
    _db_save_pending = False
    if DATABASE_URL and psycopg2 is not None:
        snapshot = json.loads(json.dumps(data, ensure_ascii=False))
        await asyncio.to_thread(_db_set, "data", snapshot)

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

# Загружаем базу после объявления функций.
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
}

changed = False
for key, default in defaults.items():
    if key not in data:
        data[key] = default
        changed = True

# Список участников группы, которых бот уже видел в сообщениях.
if not isinstance(data.get("group_members"), dict):
    data["group_members"] = {}
    changed = True
if not isinstance(data.get("pending_admin_usernames"), dict):
    data["pending_admin_usernames"] = {}
    changed = True
if not isinstance(data.get("notify_settings"), dict):
    data["notify_settings"] = {}
    changed = True
if not isinstance(data.get("bot_settings"), dict):
    data["bot_settings"] = {"reminders_enabled": False, "pin_announcements": False}
    changed = True
if not isinstance(data.get("last_reminders"), dict):
    data["last_reminders"] = {}
    changed = True
if not isinstance(data.get("reminders"), list):
    data["reminders"] = []
if not data.setdefault("bot_settings", {}).get("timezone"):
    data["bot_settings"]["timezone"] = "Europe/Moscow"
    changed = True

if not data.get("admins"):
    data["admins"] = list(ADMIN_IDS)
    changed = True

# Сохраняем SUPER_ADMIN в списке админов всегда.
if SUPER_ADMIN not in data["admins"]:
    data["admins"].append(SUPER_ADMIN)
    changed = True

# Миграция замов.
for nick, info in list(data.get("zam_data", {}).items()):
    if not isinstance(info, dict):
        data["zam_data"][nick] = {
            "tg_user_id": None,
            "tg_username": None,
        }
        changed = True
        continue
    if "tg_user_id" not in info:
        info["tg_user_id"] = None
        changed = True

    if "tg_username" not in info:
        info["tg_username"] = None
        changed = True

# Миграция статистики замов.
for nick in data.get("zam_data", {}):
    stat = data["zam_stats"].setdefault(
        nick,
        {"count": 0, "withdrawn": 0, "history": []},
    )
    if "count" not in stat:
        stat["count"] = 0
        changed = True

    if "withdrawn" not in stat:
        stat["withdrawn"] = 0
        changed = True

    if "history" not in stat:
        stat["history"] = []
        changed = True

# =============
# ИСХОДНЫЕ ЗАМЫ ИЗ ПРЕДЫДУЩЕГО СПИСКА
# =============
# Добавляются только если их ещё нет. Если владелец удалит такого зама,
# при следующем запуске он НЕ будет возвращён.
INITIAL_ZAM_NICKS = [
    "Vusal_Cantrell",
    "Sinax_Agressor",
    "K1LLER",
    "Milena_Guenot",
    "Meglenes_Stemmust",
    "Sergey_Darknes",
    "Gleb_Maestro",
    "Ganka_Gankovich",
    "Gosha_Pinkman",
    "Nikita_Pandemic",
    "Egor_Vendetta",
    "Victoria_Sergeevna",
]
if not data.get("initial_zams_installed", False):
    for initial_nick in INITIAL_ZAM_NICKS:
        if initial_nick not in data["zam_data"]:
            data["zam_data"][initial_nick] = {
                "tg_user_id": None,
                "tg_username": None,
            }
            data["zam_stats"].setdefault(
                initial_nick,
                {"count": 0, "withdrawn": 0, "history": []},
            )
            changed = True
    data["initial_zams_installed"] = True
    changed = True

if changed:
    save_data()

# =============
# TELEGRAM-АККАУНТ ВЛАДЕЛЬЦА
# =============
async def init_telegram_user_client():
    """Подключает пользовательскую Telegram-сессию для чтения диалогов владельца."""
    global telegram_user_client, telegram_user_ready

    if TelegramClient is None:
        print("⚠️ Telethon не установлен. Добавь telethon в requirements.txt")
        return False

    if not (TG_API_ID and TG_API_HASH and TG_SESSION_STRING):
        print("⚠️ TG_API_ID/TG_API_HASH/TG_SESSION_STRING не настроены.")
        return False

    try:
        telegram_user_client = TelegramClient(
            StringSession(TG_SESSION_STRING),
            TG_API_ID,
            TG_API_HASH,
        )
        await telegram_user_client.connect()

        if not await telegram_user_client.is_user_authorized():
            print("⚠️ TG_SESSION_STRING не авторизован.")
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

def telegram_user_is_ready():
    return telegram_user_client is not None and telegram_user_ready

async def get_owner_dialog_users(limit=100):
    """Возвращает людей из личных диалогов владельца, включая тех, кто не запускал бота."""
    if not telegram_user_is_ready():
        return []

    result = []
    try:
        async for dialog in telegram_user_client.iter_dialogs(limit=limit):
            entity = dialog.entity
            if TgUser is not None and isinstance(entity, TgUser):
                if getattr(entity, "self", False):
                    continue
                if getattr(entity, "bot", False):
                    continue

                first = getattr(entity, "first_name", None) or ""
                last = getattr(entity, "last_name", None) or ""
                full_name = f"{first} {last}".strip() or "Без имени"
                username = getattr(entity, "username", None)
                result.append({
                    "id": int(entity.id),
                    "name": full_name,
                    "username": username,
                    "phone": getattr(entity, "phone", None),
                })
    except Exception as e:
        print(f"⚠️ Ошибка чтения Telegram-диалогов: {e}")

    return result

def owner_dialog_label(user):
    name = escape(user.get("name") or "Без имени")
    username = user.get("username")
    return f"{name} — @{escape(username)}" if username else name

def owner_dialog_short_label(user):
    name = user.get("name") or "Без имени"
    username = user.get("username")
    return f"{name} (@{username})" if username else name

def owner_dialog_page_keyboard(users, page=0, page_size=20, prefix="select_admin"):
    start = page * page_size
    chunk = users[start:start + page_size]
    rows = []

    for user in chunk:
        label = owner_dialog_short_label(user)
        if len(label) > 48:
            label = label[:45] + "..."
        rows.append([InlineKeyboardButton(
            text=f"👤 {label}",
            callback_data=f"{prefix}:{user['id']}",
        )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"{prefix}_page:{page-1}"))
    if (page + 1) * page_size < len(users):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"{prefix}_page:{page+1}"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="owner_select_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

# =============
# АДМИНЫ
# =============
async def init_admins():
    admin_info = data.get("admin_usernames", {})
    changed_local = False

    for admin_id in get_admins():
        try:
            chat = await bot.get_chat(admin_id)

            info = {}
            if chat.username:
                info["username"] = chat.username
            if chat.full_name:
                info["full_name"] = chat.full_name

            if info and admin_info.get(str(admin_id)) != info:
                admin_info[str(admin_id)] = info
                changed_local = True

        except Exception:
            if str(admin_id) not in admin_info:
                admin_info[str(admin_id)] = {"full_name": str(admin_id)}
                changed_local = True

    if changed_local:
        data["admin_usernames"] = admin_info
        save_data()

def get_admin_display(admin_id):
    info = data.get("admin_usernames", {}).get(str(admin_id))
    if info:
        if info.get("username"):
            return f"@{info['username']}"

        if info.get("full_name") and info["full_name"] != str(admin_id):
            return info["full_name"]

    return str(admin_id)

def get_admins():
    """Возвращает список ID всех администраторов."""
    return data.get("admins", [])
