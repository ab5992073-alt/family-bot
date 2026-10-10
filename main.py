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


# =========================================================
# ОТСЛЕЖИВАНИЕ УЧАСТНИКОВ ГРУППЫ
# =========================================================

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



# =========================================================
# БАЗА ДАННЫХ
# =========================================================

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

# =========================================================
# ИСХОДНЫЕ ЗАМЫ ИЗ ПРЕДЫДУЩЕГО СПИСКА
# =========================================================
# Добавляются только если их ещё нет. Если владелец удалит такого зама,
# при следующем запуске он НЕ будет возвращён.
INITIAL_ZAM_NICKS = [
    "Vusal_Cantrell",
    "_Sinax_Agressor_",
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


# =========================================================
# TELEGRAM-АККАУНТ ВЛАДЕЛЬЦА
# =========================================================

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


# =========================================================
# АДМИНЫ
# =========================================================

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
    return set(data.get("admins", []))


def save_admins(admins):
    data["admins"] = list(admins)
    save_data()


def is_admin(user_id):
    return user_id in get_admins()


def is_super_admin(user_id):
    return user_id == SUPER_ADMIN


# =========================================================
# ЗАМЫ
# =========================================================

def get_zam_nicknames():
    return list(data.get("zam_data", {}).keys())


def get_zam_user_id(game_nick):
    info = data.get("zam_data", {}).get(game_nick)
    if not info:
        return None
    return info.get("tg_user_id")


def add_zam_nick(game_nick, tg_user_id=None, tg_username=None):
    game_nick = game_nick.strip()

    if not game_nick:
        return False, "Пустой ник."

    if game_nick in data["zam_data"]:
        return False, "Такой зам уже существует."

    data["zam_data"][game_nick] = {
        "tg_user_id": tg_user_id,
        "tg_username": tg_username,
    }

    if game_nick not in data["zam_stats"]:
        data["zam_stats"][game_nick] = {
            "count": 0,
            "withdrawn": 0,
            "history": [],
        }

    save_data()
    return True, "Зам добавлен."


def remove_zam_nick(game_nick):
    if game_nick not in data["zam_data"]:
        return False

    del data["zam_data"][game_nick]
    data["zam_stats"].pop(game_nick, None)
    save_data()
    return True


def count_zam_answers(game_nick):
    # Актуальное число приглашённых:
    # считаем только текущие анкеты пользователей.
    return sum(
        1
        for user in data.get("users", {}).values()
        if user.get("inviter") == game_nick
    )


def get_zam_withdrawn(game_nick):
    stat = data.get("zam_stats", {}).get(game_nick, {})
    try:
        return int(stat.get("withdrawn", 0))
    except (TypeError, ValueError):
        return 0


def get_zam_available(game_nick):
    return max(0, count_zam_answers(game_nick) - get_zam_withdrawn(game_nick))


def get_all_zam_counts():
    result = []

    for nick in get_zam_nicknames():
        current = count_zam_answers(nick)
        withdrawn = get_zam_withdrawn(nick)
        available = max(0, current - withdrawn)
        result.append((nick, current, withdrawn, available))

    result.sort(key=lambda x: (-x[3], x[0].lower()))
    return result


# =========================================================
# ЛОГИ
# =========================================================

async def log_action(user_id, action, details=""):
    try:
        chat = await bot.get_chat(user_id)
        username = (
            f"@{chat.username}"
            if chat.username
            else chat.full_name
        )
    except Exception:
        username = str(user_id)

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    append_log_line(
        f"[{ts}] {username} -> {action} {details}\n"
    )
    category = "zams" if "зам" in action.lower() else (
        "admins" if "админ" in action.lower() else (
        "applications" if "заяв" in action.lower() or "вердикт" in action.lower() else (
        "surveys" if "анк" in action.lower() else "other")))
    audit_record(user_id, category, action, details)

    if data.get("log_notify_enabled"):
        try:
            await bot.send_message(
                SUPER_ADMIN,
                f"👤 <b>{escape(username)}</b> -> "
                f"{escape(action)} {escape(details)}\n"
                f"🕐 {ts}",
            )
        except Exception:
            pass


# =========================================================
# КЛАВИАТУРЫ
# =========================================================

def main_keyboard(has_survey=False):
    b = ReplyKeyboardBuilder()

    b.row(
        KeyboardButton(text="📝 Заполнить анкету"),
    )

    if has_survey:
        b.row(
            KeyboardButton(text="🔄 Перезаполнить анкету"),
        )

    b.row(
        KeyboardButton(text="👤 Мой профиль"),
    )

    return b.as_markup(resize_keyboard=True)


def admin_keyboard(user_id, has_survey=False):
    b = ReplyKeyboardBuilder()

    b.row(
        KeyboardButton(text="📋 Управление заявками"),
        KeyboardButton(text="⏳ Активные заявки"),
    )
    b.row(
        KeyboardButton(text="👥 Список участников"),
        KeyboardButton(text="🟢 Статус бота"),
    )
    b.row(
        KeyboardButton(text="📢 Объявление"),
        KeyboardButton(text="📢 Общий сбор"),
    )
    b.row(
        KeyboardButton(text="🏠 Панель управления"),
        KeyboardButton(text="📊 Статистика"),
    )
    if is_super_admin(user_id):
        b.row(
            KeyboardButton(text="🛠 Админка"),
        )
    b.row(
        KeyboardButton(text="🛑 Остановить сбор"),
    )

    if has_survey:
        b.row(
            KeyboardButton(text="🔄 Перезаполнить анкету"),
        )

    if is_super_admin(user_id):
        b.row(
            KeyboardButton(text="👑 Замы"),
            KeyboardButton(text="📜 Журнал действий"),
        )
        b.row(KeyboardButton(text="☁️ Google Таблица"), KeyboardButton(text="⚙️ Настройки"))

    return b.as_markup(resize_keyboard=True)


def admin_panel_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Добавить админа",
                    callback_data="adm:add",
                ),
                InlineKeyboardButton(
                    text="➖ Удалить админа",
                    callback_data="adm:remove",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="👑 Список админов",
                    callback_data="adm:list",
                ),
            ],
        ]
    )


def zams_panel_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Добавить зама",
                    callback_data="zam:add",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="➖ Удалить зама",
                    callback_data="zam:remove",
                ),
            ],
        ]
    )


# =========================================================
# ДОБАВЛЕНИЕ В ГРУППУ
# =========================================================

async def add_user_to_group(user_id):
    # Используем только постоянную ссылку на нашу группу.
    # Дополнительные invite-ссылки Telegram больше не создаём.
    try:
        await bot.send_message(
            user_id,
            f"🔗 <b>Вы приняты в семью!</b>\n\n"
            f"Вступите в группу по ссылке:\n{GROUP_LINK}",
        )
        return True
    except Exception:
        return False


async def remove_user_from_group(user_id):
    try:
        await bot.ban_chat_member(GROUP_ID, user_id)
        await bot.unban_chat_member(GROUP_ID, user_id)
        return True
    except Exception:
        return False


async def set_user_nickname(user_id, nickname):
    try:
        await bot.set_chat_member_custom_title(
            chat_id=GROUP_ID,
            user_id=user_id,
            custom_title=nickname,
        )
        return True
    except Exception:
        return False


# =========================================================
# МЕНЮ
# =========================================================

@dp.message(CommandStart())
async def start_command(message: Message):
    await log_action(
        message.from_user.id,
        "start",
        "запустил бота",
    )
    await show_main_menu(message)


async def show_main_menu(message: Message):
    user_id = message.from_user.id
    has_survey = str(user_id) in data["users"]

    if is_admin(user_id):
        await message.answer(
            f"🛡️ <b>Панель управления</b>\n"
            f"Добро пожаловать в <b>{BOT_NAME}</b>.",
            reply_markup=admin_keyboard(user_id, has_survey),
        )
    else:
        await message.answer(
            f"👋 <b>Добро пожаловать в {BOT_NAME}!</b>\n"
            f"Заполните анкету для вступления в семью.",
            reply_markup=main_keyboard(has_survey),
        )


# =========================================================
# /КТО
# =========================================================

@dp.message(Command("кто"))
@dp.message(Command("kto"))
async def who_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет прав!")
        return

    await log_action(message.from_user.id, "команда /кто")

    if not message.reply_to_message:
        await message.answer("❌ Ответьте на сообщение участника.")
        return

    uid = message.reply_to_message.from_user.id
    u = data["users"].get(str(uid))

    if not u:
        await message.answer("❌ У этого пользователя нет анкеты.")
        return

    await message.answer(
        f"📋 <b>Анкета:</b>\n"
        f"Nickname: {escape(u.get('nickname', '—'))}\n"
        f"Тег: {escape(u.get('tag', '—'))}\n"
        f"Ранг: {escape(u.get('rank_fam', '—'))}\n"
        f"Орг: {escape(u.get('organization', '—'))}\n"
        f"Ранг в орг: {escape(u.get('rank_org', '—'))}\n"
        f"Пригласитель: {escape(u.get('inviter', '—'))}"
    )


# =========================================================
# ПЕРЕЗАПИСЬ АНКЕТЫ
# =========================================================

@dp.message(F.text == "🔄 Перезаполнить анкету")
async def reset_survey(message: Message):
    uid = str(message.from_user.id)

    if uid not in data["users"]:
        await message.answer("❌ У вас нет анкеты.")
        return

    # Старые ожидающие заявки больше не должны приниматься/отклоняться.
    for app in data["applications"].values():
        if (
            str(app.get("user_id")) == uid
            and app.get("status") == "pending"
        ):
            app["status"] = "cancelled"
            app.setdefault("history", []).append(
                {
                    "action": "cancelled_by_user",
                    "created": datetime.now().isoformat(),
                }
            )

    data["users"].pop(uid, None)
    save_data()

    await log_action(
        int(uid),
        "сброс анкеты",
        "перезаполнение",
    )

    await start_survey(message)


# =========================================================
# АНКЕТА
# =========================================================

user_surveys = {}
admin_actions = {}

# Активные созывы: для каждой группы только один одновременно.
gather_tasks = {}
pending_zam_users = {}


async def start_survey(message: Message, user_id=None):
    uid = user_id if user_id is not None else message.from_user.id

    user_surveys[uid] = {
        "step": 0,
        "answers": {},
    }

    await log_action(uid, "анкета", "начал")

    await message.answer(
        "📋 <b>Заполнение анкеты</b>\n\n"
        "1️⃣ Ваш Nickname в игре?",
        reply_markup=ReplyKeyboardRemove(),
    )


@dp.message(lambda m: m.from_user.id in user_surveys)
async def survey_handler(message: Message):
    uid = message.from_user.id
    s = user_surveys[uid]
    step = s["step"]

    if not message.text:
        await message.answer("❌ Введите текст.")
        return

    if step == 0:
        s["answers"]["nickname"] = message.text.strip()

        u = message.from_user
        s["answers"]["tag"] = (
            f"@{u.username}"
            if u.username
            else str(u.id)
        )

        s["step"] = 1

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=r,
                        callback_data=f"rank_{r}",
                    )
                ]
                for r in RANK_LIST
            ]
        )

        await message.answer(
            "👤 Ваш ранг в фаме:",
            reply_markup=kb,
        )

    elif step == 3:
        s["answers"]["rank_org"] = message.text.strip()
        s["step"] = 4

        zams = get_zam_nicknames()

        if not zams:
            await message.answer(
                "⚠️ Сейчас замов нет. Обратитесь к администрации."
            )
            user_surveys.pop(uid, None)
            return

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=z,
                        callback_data=f"survey_zam:{z}",
                    )
                ]
                for z in zams
            ]
        )

        await message.answer(
            "👤 Кто вас пригласил?",
            reply_markup=kb,
        )


# =========================================================
# ВЫБОР РАНГА
# =========================================================

@dp.callback_query(F.data.startswith("rank_"))
async def rank_selected(cb: CallbackQuery):
    uid = cb.from_user.id

    if uid not in user_surveys:
        await cb.answer("❌ Анкета не найдена.")
        return

    rank = cb.data[5:]

    user_surveys[uid]["answers"]["rank_fam"] = rank
    user_surveys[uid]["step"] = 2

    await cb.answer(f"✅ {rank}")

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=o,
                    callback_data=f"org_{o}",
                )
            ]
            for o in ORG_LIST
        ]
    )

    await cb.message.answer(
        "🏢 Ваша организация:",
        reply_markup=kb,
    )


# =========================================================
# ВЫБОР ОРГАНИЗАЦИИ
# =========================================================

@dp.callback_query(F.data.startswith("org_"))
async def org_selected(cb: CallbackQuery):
    uid = cb.from_user.id

    if uid not in user_surveys:
        await cb.answer("❌ Анкета не найдена.")
        return

    org = cb.data[4:]

    user_surveys[uid]["answers"]["organization"] = org

    await cb.answer(f"✅ {org}")

    if org == "Не в организации":
        user_surveys[uid]["answers"]["rank_org"] = "/"
        user_surveys[uid]["step"] = 4
        zams = get_zam_nicknames()
        if not zams:
            user_surveys.pop(uid, None)
            await cb.message.answer("⚠️ Сейчас замов нет. Обратитесь к администрации.")
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=z, callback_data=f"survey_zam:{z}")] for z in zams])
        await cb.message.answer("👤 Кто вас пригласил?", reply_markup=kb)
        return

    user_surveys[uid]["step"] = 3
    await cb.message.answer("📌 Ваш ранг в организации?")


# =========================================================
# ВЫБОР ЗАМА
# =========================================================

@dp.callback_query(F.data.startswith("survey_zam:"))
async def zam_selected(cb: CallbackQuery):
    uid = cb.from_user.id

    if uid not in user_surveys:
        await cb.answer("❌ Анкета не найдена.")
        return

    zam = cb.data.split(":", 1)[1]

    if zam not in data["zam_data"]:
        await cb.answer(
            "❌ Этот зам больше не существует.",
            show_alert=True,
        )
        return

    user_surveys[uid]["answers"]["inviter"] = zam

    await cb.answer(f"✅ {zam}")
    await finish_survey(cb.message, uid)


# =========================================================
# ЗАВЕРШЕНИЕ АНКЕТЫ
# =========================================================

async def finish_survey(message, uid):
    s = user_surveys.pop(uid, None)

    if not s:
        return

    a = s["answers"]

    user_data = {
        "nickname": a.get("nickname", "—"),
        "tag": a.get("tag", "—"),
        "rank_fam": a.get("rank_fam", "—"),
        "organization": a.get("organization", "—"),
        "rank_org": a.get("rank_org", "—"),
        "inviter": a.get("inviter", "—"),
    }

    data["users"][str(uid)] = user_data

    app_id = f"app_{uid}_{int(datetime.now().timestamp())}"

    data["applications"][app_id] = {
        "user_id": uid,
        "data": user_data,
        "status": "pending",
        "created": datetime.now().isoformat(),
        "history": [],
    }

    save_data()

    await message.answer("✅ <b>Анкета заполнена!</b>", reply_markup=main_keyboard(has_survey=True))

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Принять",
                    callback_data=f"accept:{app_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"reject:{app_id}",
                )
            ],
        ]
    )

    text = (
        f"📩 <b>Новая заявка!</b>\n\n"
        f"Nickname: {escape(user_data['nickname'])}\n"
        f"Тег: {escape(user_data['tag'])}\n"
        f"Ранг: {escape(user_data['rank_fam'])}\n"
        f"Орг: {escape(user_data['organization'])}\n"
        f"Ранг в орг: {escape(user_data['rank_org'])}\n"
        f"Пригласитель: {escape(user_data['inviter'])}"
    )

    for admin in get_admins():
        try:
            await bot.send_message(
                admin,
                text,
                reply_markup=kb,
            )
        except Exception:
            pass


@dp.callback_query(F.data == "survey_refill")
async def survey_refill_cb(cb: CallbackQuery):
    if str(cb.from_user.id) not in data.get("users", {}):
        await cb.answer("Анкета не найдена.", show_alert=True); return
    await cb.answer("Начинаем заново")
    uid = str(cb.from_user.id)
    for app in data["applications"].values():
        if str(app.get("user_id")) == uid and app.get("status") == "pending":
            app["status"] = "cancelled"
            app.setdefault("history", []).append({"action": "cancelled_by_user", "created": datetime.now().isoformat()})
    data["users"].pop(uid, None)
    save_data()
    await start_survey(cb.message, cb.from_user.id)


@dp.callback_query(F.data == "survey_skip")
async def survey_skip_cb(cb: CallbackQuery):
    await cb.answer("Оставляем текущую анкету")
    try:
        await cb.message.delete()
    except Exception:
        pass
    await cb.message.answer("✅ Текущая анкета оставлена.", reply_markup=main_keyboard(has_survey=True) if not is_admin(cb.from_user.id) else admin_keyboard(cb.from_user.id, True))


@dp.message(F.text == "📝 Заполнить анкету")
async def survey_button(message: Message):
    uid = message.from_user.id

    if str(uid) in data["users"]:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔄 Перезаполнить", callback_data="survey_refill"),
            InlineKeyboardButton(text="⏭ Пропустить", callback_data="survey_skip"),
        ]])
        await message.answer("ℹ️ У вас уже есть заполненная анкета. Хотите изменить её?", reply_markup=kb)
        return

    await start_survey(message)


# =========================================================
# ЗАЯВКИ
# =========================================================

async def change_application_verdict(app_id, new_status, admin_id):
    app = data["applications"].get(app_id)
    if not app:
        return False, "❌ Заявка не найдена."

    old_status = app.get("status", "pending")
    if old_status == new_status:
        return False, "ℹ️ Этот вердикт уже установлен."

    app["status"] = new_status
    app.setdefault("history", []).append(
        {
            "action": new_status,
            "previous_status": old_status,
            "by": admin_id,
            "created": datetime.now().isoformat(),
        }
    )
    save_data()

    user_id = app.get("user_id")
    nickname = app.get("data", {}).get("nickname", "Участник")

    if new_status == "accepted":
        await add_user_to_group(user_id)
        await set_user_nickname(user_id, nickname)
        try:
            await bot.send_message(
                user_id,
                "✅ Ваша заявка принята администрацией!",
            )
        except Exception:
            pass
        await log_action(
            admin_id,
            "изменил вердикт заявки",
            f"{app_id}: {old_status} → accepted",
        )
        return True, "✅ Заявка отмечена как принята."

    if new_status == "rejected":
        await remove_user_from_group(user_id)
        try:
            await bot.send_message(
                user_id,
                "❌ Ваша заявка отклонена администрацией.",
            )
        except Exception:
            pass
        await log_action(
            admin_id,
            "изменил вердикт заявки",
            f"{app_id}: {old_status} → rejected",
        )
        return True, "❌ Заявка отмечена как отклонённая."

    return False, "❌ Недопустимый вердикт."


@dp.callback_query(F.data.startswith("accept:"))
async def accept_app(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет прав!", show_alert=True)
        return
    app_id = cb.data.split(":", 1)[1]
    app = data.get("applications", {}).get(app_id)
    if not app:
        await cb.answer("❌ Заявка не найдена.", show_alert=True)
        return
    if app.get("status") != "pending":
        await cb.answer("ℹ️ Заявка уже обработана.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, принять", callback_data=f"accept_confirm:{app_id}")],
        [InlineKeyboardButton(text="↩️ Отмена", callback_data=f"app_back:{app_id}")],
    ])
    await cb.message.edit_reply_markup(reply_markup=kb)
    await cb.answer("Подтвердите принятие")

@dp.callback_query(F.data.startswith("reject:"))
async def reject_app(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет прав!", show_alert=True)
        return
    app_id = cb.data.split(":", 1)[1]
    app = data.get("applications", {}).get(app_id)
    if not app:
        await cb.answer("❌ Заявка не найдена.", show_alert=True)
        return
    if app.get("status") != "pending":
        await cb.answer("ℹ️ Заявка уже обработана.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Да, отклонить", callback_data=f"reject_confirm:{app_id}")],
        [InlineKeyboardButton(text="↩️ Отмена", callback_data=f"app_back:{app_id}")],
    ])
    await cb.message.edit_reply_markup(reply_markup=kb)
    await cb.answer("Подтвердите отклонение")

@dp.callback_query(F.data.startswith("app_back:"))
async def app_back_cb(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет прав!", show_alert=True)
        return
    app_id = cb.data.split(":", 1)[1]
    if app_id not in data.get("applications", {}):
        await cb.answer("❌ Заявка не найдена.", show_alert=True)
        return
    await cb.message.edit_reply_markup(reply_markup=application_keyboard(app_id))
    await cb.answer("Отменено")

@dp.callback_query(F.data.startswith("accept_confirm:"))
async def accept_confirm_cb(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет прав!", show_alert=True)
        return
    app_id = cb.data.split(":", 1)[1]
    ok, text = await change_application_verdict(app_id, "accepted", cb.from_user.id)
    await cb.answer("✅ Принято" if ok else text, show_alert=not ok)
    if ok:
        await cb.message.edit_reply_markup(reply_markup=application_keyboard(app_id))

@dp.callback_query(F.data.startswith("reject_confirm:"))
async def reject_confirm_cb(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет прав!", show_alert=True)
        return
    app_id = cb.data.split(":", 1)[1]
    ok, text = await change_application_verdict(app_id, "rejected", cb.from_user.id)
    await cb.answer("❌ Отклонено" if ok else text, show_alert=not ok)
    if ok:
        await cb.message.edit_reply_markup(reply_markup=application_keyboard(app_id))

def application_keyboard(app_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Принять", callback_data=f"accept:{app_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{app_id}"),
        ],
    ])


def application_status_label(status):
    return {
        "pending": "🟠 Ожидает",
        "accepted": "🟢 Принята",
        "rejected": "🔴 Отклонена",
        "cancelled": "⚪ Отменена",
    }.get(status, "⚪ Неизвестно")


def application_text(app, idx=None):
    u = app.get("data", {})
    status = app.get("status", "pending")
    status_text = application_status_label(status)
    prefix = f"<b>Заявка #{idx}</b>" if idx is not None else "<b>Заявка</b>"
    return (
        f"{prefix}\n"
        f"Статус: <b>{status_text}</b>\n\n"
        f"👤 Nickname: {escape(str(u.get('nickname', '—')))}\n"
        f"📱 Тег: {escape(str(u.get('tag', '—')))}\n"
        f"🎖 Ранг: {escape(str(u.get('rank_fam', '—')))}\n"
        f"🏢 Орг: {escape(str(u.get('organization', '—')))}\n"
        f"📌 Ранг в орг: {escape(str(u.get('rank_org', '—')))}\n"
        f"👑 Пригласил: {escape(str(u.get('inviter', '—')))}"
    )


def apps_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟠 Ожидают", callback_data="apps_filter:pending"),
         InlineKeyboardButton(text="🟢 Приняты", callback_data="apps_filter:accepted")],
        [InlineKeyboardButton(text="🔴 Отклонены", callback_data="apps_filter:rejected"),
         InlineKeyboardButton(text="📋 Все", callback_data="apps_filter:all")],
        [InlineKeyboardButton(text="🔎 Поиск", callback_data="apps_search")],
    ])


def filtered_applications(status="pending", query=""):
    items = list(data.get("applications", {}).items())
    if status != "all":
        items = [(k, v) for k, v in items if v.get("status", "pending") == status]
    q = query.strip().lower()
    if q:
        result = []
        for app_id, app in items:
            d = app.get("data", {})
            hay = " ".join(str(d.get(x, "")) for x in ("nickname", "tag", "rank_fam", "organization", "inviter"))
            if q in hay.lower() or q in str(app_id).lower():
                result.append((app_id, app))
        items = result
    return items


def apps_page_keyboard(status, page, pages):
    rows = [
        [InlineKeyboardButton(text="🟠", callback_data="apps_filter:pending"),
         InlineKeyboardButton(text="🟢", callback_data="apps_filter:accepted"),
         InlineKeyboardButton(text="🔴", callback_data="apps_filter:rejected"),
         InlineKeyboardButton(text="📋", callback_data="apps_filter:all")],
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"apps_page:{status}:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{pages}", callback_data="apps_noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"apps_page:{status}:{page+1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔎 Поиск", callback_data="apps_search")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_apps_page(message, status="pending", page=0, query=""):
    items = filtered_applications(status, query)
    per = 1
    pages = max(1, (len(items) + per - 1) // per)
    page = max(0, min(page, pages - 1))
    if not items:
        text = "📭 Заявок в выбранной категории нет."
        await message.answer(text, reply_markup=apps_menu_keyboard())
        return
    app_id, app = items[page]
    total = len(items)
    header = f"📋 <b>Управление заявками</b>\nКатегория: <b>{escape(application_status_label(status) if status != 'all' else '📋 Все')}</b> | Найдено: <b>{total}</b>\n\n"
    await message.answer(header + application_text(app, page + 1), reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", callback_data=f"accept:{app_id}"),
         InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{app_id}")],
        *apps_page_keyboard(status, page, pages).inline_keyboard,
    ]))


@dp.message(F.text == "📋 Управление заявками")
async def all_apps(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌")
        return
    await send_apps_page(message, "pending", 0)


@dp.message(F.text == "⏳ Активные заявки")
async def active_apps(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌")
        return
    await send_apps_page(message, "pending", 0)


@dp.callback_query(F.data.startswith("apps_filter:"))
async def apps_filter_cb(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет прав", show_alert=True); return
    status = cb.data.split(":", 1)[1]
    await cb.answer()
    await send_apps_page(cb.message, status, 0)


@dp.callback_query(F.data.startswith("apps_page:"))
async def apps_page_cb(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет прав", show_alert=True); return
    _, status, page = cb.data.split(":")
    await cb.answer()
    await send_apps_page(cb.message, status, int(page))


admin_search_mode = {}
announcement_mode = {}

@dp.callback_query(F.data == "apps_search")
async def apps_search_cb(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет прав", show_alert=True); return
    admin_search_mode[cb.from_user.id] = {"type": "apps"}
    await cb.message.answer("🔎 Введите Nickname, @username или номер заявки для поиска:")
    await cb.answer()


# =========================================================
# СПИСОК УЧАСТНИКОВ — единый стиль
# =========================================================

def participant_matches(uid, u, flt="all", query=""):
    rank = str(u.get("rank_fam", ""))
    org = str(u.get("organization", ""))
    if flt == "org" and org in ("Не в организации", ""):
        return False
    if flt == "union" and rank != "Союз":
        return False
    if flt == "neutral" and rank != "Нейтраль":
        return False
    if flt == "noorg" and org != "Не в организации":
        return False
    if flt == "filled" and not u:
        return False
    q = query.strip().lower()
    if q:
        hay = " ".join(str(u.get(k, "")) for k in ("nickname", "tag", "rank_fam", "organization", "rank_org", "inviter")) + f" {uid}"
        if q not in hay.lower():
            return False
    return True


def participant_items(flt="all", query=""):
    return [(uid, u) for uid, u in data.get("users", {}).items() if participant_matches(uid, u, flt, query)]


def users_filter_keyboard(flt, page, pages):
    rows = [
        [InlineKeyboardButton(text="👥 Все", callback_data="users_filter:all"),
         InlineKeyboardButton(text="🏢 Орг", callback_data="users_filter:org")],
        [InlineKeyboardButton(text="🤝 Союз", callback_data="users_filter:union"),
         InlineKeyboardButton(text="⚪ Нейтрал", callback_data="users_filter:neutral")],
        [InlineKeyboardButton(text="🚫 Не в орг", callback_data="users_filter:noorg"),
         InlineKeyboardButton(text="🔎 Поиск", callback_data="users_search")],
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"users_page:{flt}:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{pages}", callback_data="users_noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"users_page:{flt}:{page+1}"))
    rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_users_page(message, users=None, page=0, flt="all", query=""):
    items = participant_items(flt, query) if users is None else users
    per = 5
    pages = max(1, (len(items) + per - 1) // per)
    page = max(0, min(page, pages - 1))
    if not items:
        await message.answer("📭 Участников по этому фильтру нет.", reply_markup=users_filter_keyboard(flt, 0, 1))
        return
    start = page * per
    chunk = items[start:start+per]
    text = f"👥 <b>Список участников</b>\nФильтр: <b>{escape(flt)}</b> | Найдено: <b>{len(items)}</b>\n\n"
    rows=[]
    for n, (uid, u) in enumerate(chunk, start + 1):
        text += (
            f"<b>{n}. {escape(str(u.get('nickname', '—')))}</b>\n"
            f"   📱 {escape(str(u.get('tag', uid)))}\n"
            f"   🎖 {escape(str(u.get('rank_fam', '—')))} | 🏢 {escape(str(u.get('organization', '—')))}\n"
            f"   👑 {escape(str(u.get('inviter', '—')))}\n\n"
        )
        rows.append([InlineKeyboardButton(text=f"👤 {str(u.get('nickname','—'))[:24]}", callback_data=f"user_view:{uid}")])
    base=users_filter_keyboard(flt,page,pages).inline_keyboard
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows+base))


@dp.message(F.text == "👥 Список участников")
async def list_users(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌")
        return
    await send_users_page(message)


@dp.callback_query(F.data.startswith("users_filter:"))
async def users_filter_cb(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет прав", show_alert=True); return
    flt = cb.data.split(":", 1)[1]
    await cb.answer()
    await send_users_page(cb.message, page=0, flt=flt)


@dp.callback_query(F.data.startswith("users_page:"))
async def users_page_cb(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет прав", show_alert=True); return
    _, flt, page = cb.data.split(":")
    await cb.answer()
    await send_users_page(cb.message, page=int(page), flt=flt)


@dp.callback_query(F.data == "users_search")
async def users_search_cb(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет прав", show_alert=True); return
    admin_search_mode[cb.from_user.id] = {"type": "users"}
    await cb.message.answer("🔎 Введите Nickname, @username или Telegram ID:")
    await cb.answer()


@dp.callback_query(F.data.in_({"apps_noop", "users_noop"}))
async def pagination_noop(cb: CallbackQuery):
    await cb.answer()


@dp.message(lambda m: m.from_user.id in admin_search_mode and bool(m.text))
async def admin_search_handler(message: Message):
    if not is_admin(message.from_user.id):
        return
    state = admin_search_mode.pop(message.from_user.id, None)
    if not state:
        return
    query = message.text.strip()
    if state["type"] == "apps":
        await send_apps_page(message, "all", 0, query)
    elif state["type"] == "users":
        await send_users_page(message, page=0, flt="all", query=query)
    elif state["type"] == "zams":
        await send_zam_stats(message, 0, query)

# =========================================================
# РЕДАКТИРОВАНИЕ УЧАСТНИКОВ
# =========================================================

participant_edit_mode = {}

def user_card_keyboard(uid):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"user_edit:{uid}")],
        [InlineKeyboardButton(text="📜 История", callback_data=f"user_history:{uid}")],
    ])


def user_edit_keyboard(uid):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎖 Ранг фама", callback_data=f"user_edit_rank:{uid}"), InlineKeyboardButton(text="🏢 Организация", callback_data=f"user_edit_org:{uid}")],
        [InlineKeyboardButton(text="📌 Ранг в орг", callback_data=f"user_edit_rankorg:{uid}"), InlineKeyboardButton(text="👑 Пригласил", callback_data=f"user_edit_inviter:{uid}")],
        [InlineKeyboardButton(text="👤 Nickname", callback_data=f"user_edit_nick:{uid}"), InlineKeyboardButton(text="📱 @username", callback_data=f"user_edit_tag:{uid}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"user_view:{uid}")],
    ])


def user_text(uid):
    u=data.get("users",{}).get(str(uid), {})
    return (f"👤 <b>{escape(str(u.get('nickname','—')))}</b>\n\n"
            f"🆔 <code>{uid}</code>\n"
            f"📱 {escape(str(u.get('tag','—')))}\n"
            f"🎖 Ранг: <b>{escape(str(u.get('rank_fam','—')))}</b>\n"
            f"🏢 Организация: {escape(str(u.get('organization','—')))}\n"
            f"📌 Ранг в орг: {escape(str(u.get('rank_org','—')))}\n"
            f"👑 Пригласил: {escape(str(u.get('inviter','—')))}")


@dp.callback_query(F.data.startswith("user_view:"))
async def user_view_cb(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет прав", show_alert=True); return
    uid=cb.data.split(":",1)[1]
    if uid not in data.get("users",{}):
        await cb.answer("❌ Участник не найден", show_alert=True); return
    await cb.message.edit_text(user_text(uid), reply_markup=user_card_keyboard(uid))
    await cb.answer()


@dp.callback_query(F.data.startswith("user_edit:"))
async def user_edit_cb(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет прав", show_alert=True); return
    uid=cb.data.split(":",1)[1]
    if uid not in data.get("users",{}):
        await cb.answer("❌ Участник не найден", show_alert=True); return
    await cb.message.edit_text("✏️ <b>Редактирование анкеты</b>\n\nВыберите поле:", reply_markup=user_edit_keyboard(uid))
    await cb.answer()


@dp.callback_query(F.data.startswith("user_edit_rank:"))
async def user_edit_rank_cb(cb: CallbackQuery):
    uid=cb.data.split(":",1)[1]
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=r, callback_data=f"user_set_rank:{uid}:{i}")] for i,r in enumerate(RANK_LIST)])
    await cb.message.edit_text("🎖 <b>Выберите новый ранг:</b>", reply_markup=kb)
    await cb.answer()


@dp.callback_query(F.data.startswith("user_set_rank:"))
async def user_set_rank_cb(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌", show_alert=True); return
    _,uid,idx=cb.data.split(":")
    if uid not in data["users"]: await cb.answer("❌", show_alert=True); return
    new=RANK_LIST[int(idx)]; old=data["users"][uid].get("rank_fam","—")
    data["users"][uid]["rank_fam"]=new
    for app in data.get("applications",{}).values():
        if str(app.get("user_id"))==uid and app.get("status") in ("pending","accepted"):
            app.setdefault("data",{})["rank_fam"]=new
    save_data(); audit_record(cb.from_user.id,"users","изменил ранг участника",f"{uid}: {old} → {new}")
    await cb.message.edit_text(user_text(uid), reply_markup=user_card_keyboard(uid)); await cb.answer("✅ Ранг изменён")


@dp.callback_query(F.data.startswith("user_edit_org:"))
async def user_edit_org_cb(cb: CallbackQuery):
    uid=cb.data.split(":",1)[1]
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=o, callback_data=f"user_set_org:{uid}:{i}")] for i,o in enumerate(ORG_LIST)])
    await cb.message.edit_text("🏢 <b>Выберите организацию:</b>", reply_markup=kb); await cb.answer()


@dp.callback_query(F.data.startswith("user_set_org:"))
async def user_set_org_cb(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("❌",show_alert=True); return
    _,uid,idx=cb.data.split(":")
    if uid not in data["users"]: await cb.answer("❌",show_alert=True); return
    new=ORG_LIST[int(idx)]; old=data["users"][uid].get("organization","—")
    data["users"][uid]["organization"]=new
    if new=="Не в организации": data["users"][uid]["rank_org"]="/"
    for app in data.get("applications",{}).values():
        if str(app.get("user_id"))==uid and app.get("status") in ("pending","accepted"):
            app.setdefault("data",{})["organization"]=new; app["data"]["rank_org"]=data["users"][uid].get("rank_org","/")
    save_data(); audit_record(cb.from_user.id,"users","изменил организацию",f"{uid}: {old} → {new}")
    await cb.message.edit_text(user_text(uid), reply_markup=user_card_keyboard(uid)); await cb.answer("✅ Изменено")


@dp.callback_query(F.data.startswith("user_edit_rankorg:"))
async def user_edit_rankorg_cb(cb: CallbackQuery):
    uid=cb.data.split(":",1)[1]
    participant_edit_mode[cb.from_user.id]={"uid":uid,"field":"rank_org"}
    await cb.message.answer("📌 Введите новый ранг в организации (для «Не в организации» используйте /):")
    await cb.answer()


@dp.callback_query(F.data.startswith("user_edit_inviter:"))
async def user_edit_inviter_cb(cb: CallbackQuery):
    uid=cb.data.split(":",1)[1]
    zams=get_zam_nicknames()
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=z,callback_data=f"user_set_inv:{uid}:{i}")] for i,z in enumerate(zams)])
    await cb.message.edit_text("👑 <b>Кто пригласил?</b>", reply_markup=kb); await cb.answer()


@dp.callback_query(F.data.startswith("user_set_inv:"))
async def user_set_inv_cb(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer("❌",show_alert=True); return
    _,uid,idx=cb.data.split(":")
    zams=get_zam_nicknames()
    if uid not in data["users"] or int(idx)>=len(zams): await cb.answer("❌",show_alert=True); return
    old=data["users"][uid].get("inviter","—"); new=zams[int(idx)]
    data["users"][uid]["inviter"]=new
    for app in data.get("applications",{}).values():
        if str(app.get("user_id"))==uid and app.get("status") in ("pending","accepted"): app.setdefault("data",{})["inviter"]=new
    save_data(); audit_record(cb.from_user.id,"users","изменил пригласившего",f"{uid}: {old} → {new}")
    await cb.message.edit_text(user_text(uid),reply_markup=user_card_keyboard(uid)); await cb.answer("✅ Изменено")


@dp.callback_query(F.data.startswith("user_edit_nick:"))
async def user_edit_nick_cb(cb: CallbackQuery):
    uid=cb.data.split(":",1)[1]; participant_edit_mode[cb.from_user.id]={"uid":uid,"field":"nickname"}
    await cb.message.answer("👤 Введите новый игровой Nickname:"); await cb.answer()


@dp.callback_query(F.data.startswith("user_edit_tag:"))
async def user_edit_tag_cb(cb: CallbackQuery):
    uid=cb.data.split(":",1)[1]; participant_edit_mode[cb.from_user.id]={"uid":uid,"field":"tag"}
    await cb.message.answer("📱 Введите новый @username (или —):"); await cb.answer()


@dp.callback_query(F.data.startswith("user_history:"))
async def user_history_cb(cb: CallbackQuery):
    uid=cb.data.split(":",1)[1]
    hist=[]
    for aid,app in data.get("applications",{}).items():
        if str(app.get("user_id"))==uid:
            for h in app.get("history",[]): hist.append((h.get("created",""),h.get("action",""),h.get("by","")))
    hist.sort(reverse=True)
    text="📜 <b>История участника</b>\n\n"
    text += "\n".join(f"• {escape(str(t))[:19]} — {escape(str(a))} — {escape(str(b))}" for t,a,b in hist[-20:]) or "Нет истории."
    await cb.message.edit_text(text,reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад",callback_data=f"user_view:{uid}")]])); await cb.answer()


@dp.message(lambda m: m.from_user.id in participant_edit_mode and bool(m.text))
async def participant_edit_text(message: Message):
    if not is_admin(message.from_user.id): return
    state=participant_edit_mode.pop(message.from_user.id,None)
    if not state: return
    uid=state["uid"]; field=state["field"]
    if uid not in data.get("users",{}): await message.answer("❌ Участник не найден."); return
    val=message.text.strip()
    if field=="tag" and val=="—": val="—"
    old=data["users"][uid].get(field,"—"); data["users"][uid][field]=val
    for app in data.get("applications",{}).values():
        if str(app.get("user_id"))==uid and app.get("status") in ("pending","accepted"): app.setdefault("data",{})[field]=val
    save_data(); audit_record(message.from_user.id,"users",f"изменил {field}",f"{uid}: {old} → {val}")
    await message.answer("✅ Сохранено.")
    await message.answer(user_text(uid),reply_markup=user_card_keyboard(uid))


# =========================================================
# СТАТУС
# =========================================================

@dp.message(F.text == "🟢 Статус бота")
async def status_btn(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌")
        return

    total = len(data["users"])
    pend = sum(
        1
        for a in data["applications"].values()
        if a.get("status") == "pending"
    )
    rej = sum(
        1
        for a in data["applications"].values()
        if a.get("status") == "rejected"
    )
    acc = sum(
        1
        for a in data["applications"].values()
        if a.get("status") == "accepted"
    )

    admins = "\n".join(
        escape(get_admin_display(i))
        for i in sorted(get_admins())
    )

    await message.answer(
        f"🟢 <b>Бот работает!</b>\n\n"
        f"👥 Всего анкет: {total}\n"
        f"📩 Ожидают: {pend}\n"
        f"✅ Принято: {acc}\n"
        f"❌ Отклонено: {rej}\n\n"
        f"👑 <b>Админы:</b>\n{admins}"
    )


# =========================================================
# ПРОФИЛЬ
# =========================================================

@dp.message(F.text == "👤 Мой профиль")
async def my_profile(message: Message):
    uid = str(message.from_user.id)

    if uid in data["users"]:
        u = data["users"][uid]

        await message.answer(
            f"👤 <b>Профиль:</b>\n"
            f"Nickname: {escape(u.get('nickname', '—'))}\n"
            f"Тег: {escape(u.get('tag', '—'))}\n"
            f"Ранг: {escape(u.get('rank_fam', '—'))}\n"
            f"Орг: {escape(u.get('organization', '—'))}\n"
            f"Ранг в орг: {escape(u.get('rank_org', '—'))}\n"
            f"Пригласитель: {escape(u.get('inviter', '—'))}"
        )
    else:
        await message.answer("ℹ️ Вы ещё не заполнили анкету.")


# =========================================================
# АДМИНКА
# =========================================================

async def add_admin_by_username(message: Message, username: str):
    username = username.strip().lstrip("@")
    if not username:
        await message.answer("❌ Укажи username: <code>/add_admin @username</code>")
        return

    user_id = find_user_id_by_username(username)
    if user_id is not None:
        if user_id in get_admins():
            await message.answer("❌ Этот пользователь уже администратор.")
            return
        admins = get_admins()
        admins.add(user_id)
        save_admins(admins)
        try:
            chat = await bot.get_chat(user_id)
            data["admin_usernames"][str(user_id)] = {
                "username": chat.username or username,
                "full_name": chat.full_name or str(user_id),
            }
        except Exception:
            data["admin_usernames"][str(user_id)] = {
                "username": username,
                "full_name": username,
            }
        save_data()
        await set_command_scopes()
        await log_action(message.from_user.id, "добавил администратора", f"@{username}")
        await message.answer(f"✅ <b>@{escape(username)}</b> назначен администратором.")
        try:
            await bot.send_message(user_id, "👑 Вы назначены администратором!")
        except Exception:
            pass
        return

    pending = data.setdefault("pending_admin_usernames", {})
    pending[normalize_username(username)] = {
        "username": username,
        "added_by": message.from_user.id,
        "created": datetime.now().isoformat(),
    }
    save_data()
    await log_action(message.from_user.id, "добавил администратора в ожидание", f"@{username}")
    await message.answer(
        f"⏳ <b>@{escape(username)}</b> добавлен в ожидание.\n\n"
        "Telegram пока не дал боту его ID.\n"
        "Как только этот пользователь напишет боту или сообщение от него будет замечено в группе,\n"
        "бот автоматически привяжет его ID и выдаст права администратора."
    )


async def remove_admin_by_username(message: Message, username: str):
    username = username.strip().lstrip("@")
    if not username:
        await message.answer("❌ Укажи username: <code>/remove_admin @username</code>")
        return

    wanted = normalize_username(username)
    data.setdefault("pending_admin_usernames", {}).pop(wanted, None)
    user_id = find_user_id_by_username(username)
    if user_id is None:
        save_data()
        await message.answer(f"ℹ️ @<b>{escape(username)}</b> не найден среди текущих админов.")
        return

    if user_id == SUPER_ADMIN:
        await message.answer("❌ Владельца удалить нельзя.")
        return

    admins = get_admins()
    if user_id not in admins:
        await message.answer("❌ Этот пользователь не является администратором.")
        return

    admins.remove(user_id)
    save_admins(admins)
    display = get_admin_display(user_id)
    data["admin_usernames"].pop(str(user_id), None)
    save_data()
    await set_command_scopes()
    await log_action(message.from_user.id, "удалил администратора", display)
    await message.answer(f"✅ Админ <b>{escape(display)}</b> удалён.")


@dp.message(F.text == "🛠 Админка")
async def admin_panel(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return
    await message.answer(
        "👑 <b>Управление администраторами</b>\n\n"
        "Выберите действие:",
        reply_markup=admin_panel_keyboard(),
    )

# Быстрый кэш диалогов владельца: не обращаемся к Telethon при каждом открытии.
owner_dialog_cache = {"time": 0.0, "users": []}

async def cached_owner_dialog_users():
    now = asyncio.get_running_loop().time()
    if owner_dialog_cache["users"] and now - owner_dialog_cache["time"] < 60:
        return owner_dialog_cache["users"]
    users = await get_owner_dialog_users(limit=100)
    owner_dialog_cache["time"] = now
    owner_dialog_cache["users"] = users
    return users

@dp.callback_query(F.data == "adm:add")
async def admin_add_button_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True)
        return
    await cb.answer()
    users = await cached_owner_dialog_users()
    if not users:
        await cb.message.answer(
            "📭 Не удалось получить список личных диалогов.\n\n"
            "Проверь TG_API_ID, TG_API_HASH и TG_SESSION_STRING в Render."
        )
        return
    admins = get_admins()
    users = [u for u in users if int(u["id"]) not in admins and int(u["id"]) != SUPER_ADMIN]
    if not users:
        await cb.message.answer("📭 В доступных диалогах нет пользователей без админки.")
        return
    await cb.message.answer(
        "👑 <b>Выберите пользователя для выдачи админки</b>",
        reply_markup=owner_dialog_page_keyboard(users, 0, prefix="select_admin")
    )

@dp.callback_query(F.data.startswith("select_admin_page:"))
async def select_admin_page_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌", show_alert=True); return
    users = await cached_owner_dialog_users()
    page = int(cb.data.split(":", 1)[1])
    await cb.answer()
    await cb.message.edit_reply_markup(reply_markup=owner_dialog_page_keyboard(users, page, prefix="select_admin"))

@dp.callback_query(F.data.startswith("select_admin:"))
async def select_admin_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌", show_alert=True); return
    uid = int(cb.data.split(":", 1)[1])
    users = await cached_owner_dialog_users()
    user = next((u for u in users if int(u["id"]) == uid), None)
    if not user:
        await cb.answer("❌ Пользователь не найден", show_alert=True); return
    label = owner_dialog_short_label(user)
    await cb.message.edit_text(
        f"⚠️ Выдать админку пользователю:\n\n👤 <b>{escape(label)}</b>\n🆔 <code>{uid}</code>?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, выдать", callback_data=f"admin_grant_confirm:{uid}")],
            [InlineKeyboardButton(text="↩️ Отмена", callback_data="owner_select_cancel")],
        ])
    )
    await cb.answer()

@dp.callback_query(F.data.startswith("admin_grant_confirm:"))
async def admin_grant_confirm_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌", show_alert=True); return
    uid = int(cb.data.split(":", 1)[1])
    admins = get_admins()
    if uid in admins:
        await cb.answer("ℹ️ Уже администратор", show_alert=True); return
    admins.add(uid)
    save_admins(admins)
    users = await cached_owner_dialog_users()
    user = next((u for u in users if int(u["id"]) == uid), None)
    if user:
        data.setdefault("admin_usernames", {})[str(uid)] = {
            "username": user.get("username"),
            "full_name": user.get("name") or str(uid),
        }
    save_data()
    await set_command_scopes()
    display = owner_dialog_short_label(user) if user else str(uid)
    audit_record(cb.from_user.id, "admins", "выдал админку", f"{display} / ID {uid}")
    await cb.message.edit_text(f"✅ <b>Админка выдана</b>\n\n👤 {escape(display)}\n🆔 <code>{uid}</code>")
    await cb.answer("Готово")
    try:
        await bot.send_message(uid, "👑 Вы назначены администратором бота!\nИспользуйте /start для панели.")
    except Exception:
        pass

@dp.callback_query(F.data == "adm:remove")
async def admin_remove_button_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True); return
    rows=[]
    for uid in sorted(get_admins()):
        if uid == SUPER_ADMIN: continue
        rows.append([InlineKeyboardButton(text=f"🛡 {get_admin_display(uid)[:35]}", callback_data=f"admin_remove_confirm:{uid}")])
    rows.append([InlineKeyboardButton(text="↩️ Назад", callback_data="adm:list")])
    await cb.answer()
    await cb.message.edit_text("➖ <b>Выберите администратора для удаления:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows or [[InlineKeyboardButton(text="📭 Удалять некого", callback_data="adm:list")]]))

@dp.callback_query(F.data.startswith("admin_remove_confirm:"))
async def admin_remove_confirm_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌", show_alert=True); return
    uid = int(cb.data.split(":", 1)[1])
    if uid == SUPER_ADMIN:
        await cb.answer("❌ Владельца удалить нельзя", show_alert=True); return
    await cb.message.edit_text(
        f"⚠️ Удалить админку у <b>{escape(get_admin_display(uid))}</b>?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Да, удалить", callback_data=f"admin_remove_do:{uid}")],
            [InlineKeyboardButton(text="↩️ Отмена", callback_data="adm:list")],
        ])
    )
    await cb.answer()

@dp.callback_query(F.data.startswith("admin_remove_do:"))
async def admin_remove_do_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌", show_alert=True); return
    uid = int(cb.data.split(":", 1)[1])
    if uid == SUPER_ADMIN:
        await cb.answer("❌ Владельца удалить нельзя", show_alert=True); return
    admins = get_admins()
    if uid not in admins:
        await cb.answer("ℹ️ Уже удалён", show_alert=True); return
    display = get_admin_display(uid)
    admins.remove(uid)
    save_admins(admins)
    data.setdefault("admin_usernames", {}).pop(str(uid), None)
    save_data()
    await set_command_scopes()
    audit_record(cb.from_user.id, "admins", "снял админку", f"{display} / ID {uid}")
    await cb.message.edit_text(f"✅ Админка снята с <b>{escape(display)}</b>.")
    await cb.answer("Готово")

@dp.callback_query(F.data == "adm:list")
async def admin_list_button_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌", show_alert=True); return
    text="👑 <b>Администраторы</b>\n\n"
    for uid in sorted(get_admins()):
        mark="👑" if uid == SUPER_ADMIN else "🛡"
        text += f"{mark} {escape(get_admin_display(uid))}\n🆔 <code>{uid}</code>\n\n"
    await cb.answer()
    await cb.message.edit_text(text, reply_markup=admin_panel_keyboard())

@dp.callback_query(F.data == "owner_select_cancel")
async def owner_select_cancel_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌", show_alert=True); return
    await cb.message.edit_text("❌ Выбор отменён.", reply_markup=admin_panel_keyboard())
    await cb.answer()

@dp.message(Command("add_admin"))
async def add_admin_legacy(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return

    # Самый надёжный вариант: ответить на сообщение человека командой /add_admin.
    if message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        user_id = u.id
        if user_id == SUPER_ADMIN:
            await message.answer("ℹ️ Это владелец — права уже есть.")
            return
        admins = get_admins()
        if user_id in admins:
            await message.answer("❌ Этот пользователь уже администратор.")
            return
        admins.add(user_id)
        save_admins(admins)
        data.setdefault("admin_usernames", {})[str(user_id)] = {
            "username": u.username,
            "full_name": u.full_name or str(user_id),
        }
        data.setdefault("pending_admin_usernames", {}).pop(
            normalize_username(u.username), None
        ) if u.username else None
        save_data()
        await set_command_scopes()
        await log_action(message.from_user.id, "добавил администратора", f"{u.full_name} / @{u.username}" if u.username else u.full_name)
        display = f"@{u.username}" if u.username else (u.full_name or str(user_id))
        await message.answer(f"✅ <b>{escape(display)}</b> назначен администратором.\n🆔 ID: <code>{user_id}</code>")
        try:
            await bot.send_message(user_id, "👑 Вы назначены администратором бота!\nИспользуйте /start для панели.")
        except Exception:
            pass
        return

    args = message.text.split(maxsplit=1)
    if len(args) == 1:
        await message.answer(
            "❌ Используй один из вариантов:\n\n"
            "1) Ответь на сообщение человека: <code>/add_admin</code>\n"
            "2) <code>/add_admin @username</code>\n"
            "3) <code>/add_admin 123456789</code>"
        )
        return

    value = args[1].strip()
    if value.isdigit():
        user_id = int(value)
        if user_id == SUPER_ADMIN:
            await message.answer("ℹ️ Это владелец — права уже есть.")
            return
        if user_id in get_admins():
            await message.answer("❌ Этот пользователь уже администратор.")
            return
        # ID достаточно для выдачи внутренних прав бота.
        admins = get_admins()
        admins.add(user_id)
        save_admins(admins)
        try:
            chat = await bot.get_chat(user_id)
            username = chat.username
            full_name = chat.full_name
        except Exception:
            username = None
            full_name = str(user_id)
        data.setdefault("admin_usernames", {})[str(user_id)] = {
            "username": username,
            "full_name": full_name or str(user_id),
        }
        save_data()
        await set_command_scopes()
        await log_action(message.from_user.id, "добавил администратора", str(user_id))
        await message.answer(f"✅ Администратор выдан.\n🆔 ID: <code>{user_id}</code>")
        try:
            await bot.send_message(user_id, "👑 Вы назначены администратором бота!\nИспользуйте /start для панели.")
        except Exception:
            pass
        return

    await add_admin_by_username(message, value)


@dp.message(Command("pending_admins"))
async def pending_admins_command(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return
    pending = data.get("pending_admin_usernames", {})
    if not pending:
        await message.answer("📭 Ожидающих админов нет.")
        return
    text = "⏳ <b>Ожидают привязки:</b>\n\n"
    for key, item in pending.items():
        text += f"• @{escape(item.get('username', key))}\n"
    await message.answer(text)


@dp.message(Command("remove_admin"))
async def remove_admin_legacy(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return
    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        await remove_admin_by_username(message, args[1])
    elif message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        if u.username:
            await remove_admin_by_username(message, u.username)
        else:
            await message.answer(f"❌ У пользователя нет username. Его ID: <code>{u.id}</code>")
    else:
        await message.answer("❌ Использование: <code>/remove_admin @username</code>")


@dp.message(Command("add"))
async def add_command(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 2:
        await message.answer(
            "❌ Использование:\n"
            "<code>/add admin @username</code>\n"
            "или ответом на сообщение: <code>/add admin</code>\n"
            "или <code>/add admin 123456789</code>\n"
            "<code>/add zam @username Game_Nick</code>"
        )
        return
    mode = args[1].lower()
    if mode == "admin":
        if message.reply_to_message and message.reply_to_message.from_user:
            u = message.reply_to_message.from_user
            admins = get_admins()
            if u.id == SUPER_ADMIN:
                await message.answer("ℹ️ Это владелец — права уже есть.")
                return
            if u.id in admins:
                await message.answer("❌ Этот пользователь уже администратор.")
                return
            admins.add(u.id)
            save_admins(admins)
            data.setdefault("admin_usernames", {})[str(u.id)] = {"username": u.username, "full_name": u.full_name or str(u.id)}
            save_data()
            await set_command_scopes()
            display = f"@{u.username}" if u.username else (u.full_name or str(u.id))
            await log_action(message.from_user.id, "добавил администратора", display)
            await message.answer(f"✅ <b>{escape(display)}</b> назначен администратором.\n🆔 ID: <code>{u.id}</code>")
            return
        if len(args) < 3:
            await message.answer("❌ Укажи @username/ID или ответь на сообщение пользователя.")
            return
        value = args[2].strip()
        if value.isdigit():
            # Повторно используем основной обработчик через синтетический вызов не нужен.
            uid = int(value)
            if uid in get_admins():
                await message.answer("❌ Уже администратор.")
                return
            admins = get_admins(); admins.add(uid); save_admins(admins)
            data.setdefault("admin_usernames", {})[str(uid)] = {"username": None, "full_name": str(uid)}
            save_data(); await set_command_scopes()
            await log_action(message.from_user.id, "добавил администратора", str(uid))
            await message.answer(f"✅ Администратор выдан. ID: <code>{uid}</code>")
            return
        await add_admin_by_username(message, value)
    elif mode == "zam":
        if len(args) < 3:
            await message.answer("❌ <code>/add zam @username Game_Nick</code>")
            return
        parts = args[2].split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("❌ <code>/add zam @username Game_Nick</code>")
            return
        await add_zam_by_username(message, parts[0], parts[1])
    else:
        await message.answer("❌ Доступно: <code>admin</code> или <code>zam</code>.")


@dp.message(Command("remove"))
async def remove_command(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 2:
        await message.answer("❌ <code>/remove admin @username</code> или <code>/remove zam Game_Nick</code>")
        return
    mode = args[1].lower()
    if mode == "admin":
        if message.reply_to_message and message.reply_to_message.from_user:
            await remove_admin_by_username(message, str(message.reply_to_message.from_user.id))
        elif len(args) >= 3:
            await remove_admin_by_username(message, args[2])
        else:
            await message.answer("❌ Укажи @username/ID или ответь на сообщение админа.")
    elif mode == "zam":
        if len(args) < 3:
            await message.answer("❌ <code>/remove zam Game_Nick</code>")
            return
        nick = args[2].strip()
        if remove_zam_nick(nick):
            await log_action(message.from_user.id, "удалил зама", nick)
            await message.answer(f"✅ Зам <b>{escape(nick)}</b> удалён.")
        else:
            await message.answer("❌ Такой зам не найден.")
    else:
        await message.answer("❌ Доступно: <code>admin</code> или <code>zam</code>.")


# =========================================================
# УПРАВЛЕНИЕ ЗАМАМИ
# =========================================================


@dp.message(F.text == "👑 Замы")
async def zams_button(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return
    await send_zams_panel(message)


async def send_zams_panel(message: Message):
    await send_zam_stats(message)


async def add_zam_by_username(message: Message, username: str, game_nick: str):
    username = username.strip().lstrip("@")
    game_nick = game_nick.strip()
    if not username or not game_nick:
        await message.answer("❌ Использование: <code>/add_zam @username Game_Nick</code>")
        return

    user_id = find_user_id_by_username(username)
    tg_username = username
    if user_id is not None:
        try:
            chat = await bot.get_chat(user_id)
            tg_username = chat.username or username
        except Exception:
            pass

    ok, result = add_zam_nick(game_nick, user_id, tg_username)
    if not ok:
        await message.answer(f"❌ {escape(result)}")
        return

    await log_action(message.from_user.id, "добавил зама", f"{game_nick} / @{username}")
    if user_id:
        try:
            await bot.send_message(user_id, f"👑 Вы назначены замом!\nВаш игровой ник: {escape(game_nick)}")
        except Exception:
            pass
    await message.answer(
        f"✅ Зам <b>{escape(game_nick)}</b> назначен.\n"
        f"Telegram: @{escape(username)}" + (f"\nID: <code>{user_id}</code>" if user_id else "\n⏳ ID пока не найден, но Telegram username сохранён.")
    )


@dp.callback_query(F.data == "zam:add")
async def zam_add_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True)
        return
    zam_edit_mode[cb.from_user.id] = {"action": "add"}
    await cb.message.answer("➕ Введите: <code>@username Game_Nick</code>")
    await cb.answer()


@dp.callback_query(F.data == "zam:remove")
async def zam_remove_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True)
        return
    zams = get_zam_nicknames()
    if not zams:
        await cb.answer("Замов пока нет", show_alert=True)
        return
    rows = [[InlineKeyboardButton(text=f"👑 {z[:28]}", callback_data=f"zam_confirmremove:{z}")] for z in zams]
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="zams_back")])
    await cb.message.edit_text("➖ <b>Выберите зама для удаления:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer()


@dp.message(Command("add_zam"))
async def add_zam_command(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("❌ Использование: <code>/add_zam @username Game_Nick</code>")
        return
    await add_zam_by_username(message, args[1], args[2])


@dp.message(Command("remove_zam"))
async def remove_zam_command(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return
    args = message.text.split(maxsplit=1)
    if len(args) == 1:
        await message.answer("❌ Использование: <code>/remove_zam Game_Nick</code>")
        return
    nick = args[1].strip()
    if not remove_zam_nick(nick):
        await message.answer("❌ Такой зам не найден.")
        return
    await log_action(message.from_user.id, "удалил зама", nick)
    await message.answer(f"✅ Зам <b>{escape(nick)}</b> удалён.")


# =========================================================
# ЗАМЫ — единый стиль: страницы, поиск и фильтр
# =========================================================

def zam_items(query=""):
    q = query.strip().lower()
    items = []
    for nick in get_zam_nicknames():
        info = data.get("zam_data", {}).get(nick, {})
        tg = info.get("tg_username") or ""
        hay = f"{nick} {tg}".lower()
        if q and q not in hay:
            continue
        items.append((nick, info, count_zam_answers(nick)))
    items.sort(key=lambda x: (-x[2], x[0].lower()))
    return items


def zams_keyboard(page, pages):
    rows = [[InlineKeyboardButton(text="🔎 Поиск", callback_data="zams_search")]]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"zams_page:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{pages}", callback_data="zams_noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"zams_page:{page+1}"))
    rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_zam_stats(message: Message, page=0, query=""):
    items = zam_items(query)
    per = 8
    pages = max(1, (len(items) + per - 1) // per)
    page = max(0, min(page, pages - 1))
    if not items:
        await message.answer("📭 Замов по этому запросу нет.", reply_markup=zams_keyboard(0, 1))
        return
    chunk = items[page*per:(page+1)*per]
    text = f"👑 <b>Список замов</b>\nНайдено: <b>{len(items)}</b>\n\n"
    text += "<b>№ | Nickname | @username | Приглашений</b>\n"
    rows=[]
    for i, (nick, info, count) in enumerate(chunk, page*per + 1):
        username = info.get("tg_username")
        username = f"@{username}" if username else "—"
        text += f"<b>{i}</b> | {escape(nick)} | {escape(username)} | <b>{count}</b>\n"
        rows.append([InlineKeyboardButton(text=f"👑 {nick[:24]}",callback_data=f"zam_view:{nick}")])
    base=zams_keyboard(page,pages).inline_keyboard
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows+base))


@dp.callback_query(F.data.startswith("zams_page:"))
async def zams_page_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True); return
    await cb.answer()
    await send_zam_stats(cb.message, int(cb.data.split(":")[1]))


@dp.callback_query(F.data == "zams_search")
async def zams_search_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True); return
    admin_search_mode[cb.from_user.id] = {"type": "zams"}
    await cb.message.answer("🔎 Введите Nickname или @username зама:")
    await cb.answer()


@dp.callback_query(F.data == "zams_noop")
async def zams_noop_cb(cb: CallbackQuery):
    await cb.answer()

# =========================================================
# РЕДАКТИРОВАНИЕ ЗАМОВ
# =========================================================

zam_edit_mode = {}

def zam_card_keyboard(nick):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"zam_viewedit:{nick}")],
        [InlineKeyboardButton(text="🗑 Убрать из замов", callback_data=f"zam_confirmremove:{nick}")],
    ])

@dp.callback_query(F.data.startswith("zam_view:"))
async def zam_view_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id): await cb.answer("❌ Только владелец",show_alert=True); return
    nick=cb.data.split(":",1)[1]; info=data.get("zam_data",{}).get(nick)
    if not info: await cb.answer("❌ Не найден",show_alert=True); return
    username=info.get("tg_username") or "—"
    uid=info.get("tg_user_id") or "—"
    await cb.message.edit_text(f"👑 <b>{escape(nick)}</b>\n\n📱 @{escape(str(username).lstrip('@')) if username!='—' else '—'}\n🆔 <code>{escape(str(uid))}</code>\n📊 Приглашений: <b>{count_zam_answers(nick)}</b>",reply_markup=zam_card_keyboard(nick)); await cb.answer()

@dp.callback_query(F.data.startswith("zam_viewedit:"))
async def zam_viewedit_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id): await cb.answer("❌",show_alert=True); return
    nick=cb.data.split(":",1)[1]
    await cb.message.edit_text("✏️ <b>Редактирование зама</b>",reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Nickname",callback_data=f"zam_editnick:{nick}")],
        [InlineKeyboardButton(text="📱 @username",callback_data=f"zam_edituser:{nick}")],
        [InlineKeyboardButton(text="◀️ Назад",callback_data=f"zam_view:{nick}")],
    ])); await cb.answer()

@dp.callback_query(F.data.startswith("zam_edituser:"))
async def zam_edituser_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id): await cb.answer("❌",show_alert=True); return
    nick=cb.data.split(":",1)[1]; zam_edit_mode[cb.from_user.id]={"old_nick":nick,"field":"tg_username"}
    await cb.message.answer("📱 Введите новый @username зама или —:"); await cb.answer()

@dp.callback_query(F.data.startswith("zam_editnick:"))
async def zam_editnick_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id): await cb.answer("❌",show_alert=True); return
    nick=cb.data.split(":",1)[1]; zam_edit_mode[cb.from_user.id]={"old_nick":nick,"field":"nickname"}
    await cb.message.answer("👤 Введите новый игровой Nickname зама:"); await cb.answer()

@dp.callback_query(F.data.startswith("zam_confirmremove:"))
async def zam_confirmremove_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id): await cb.answer("❌",show_alert=True); return
    nick=cb.data.split(":",1)[1]
    await cb.message.edit_text(f"⚠️ Удалить <b>{escape(nick)}</b> из замов?",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Да, удалить",callback_data=f"zam_doremove:{nick}")],[InlineKeyboardButton(text="↩️ Отмена",callback_data=f"zam_view:{nick}")]])); await cb.answer()

@dp.callback_query(F.data == "zams_back")
async def zams_back_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True); return
    await cb.message.edit_text("👑 <b>Управление замами</b>", reply_markup=zams_panel_keyboard())
    await cb.answer()


@dp.callback_query(F.data.startswith("zam_doremove:"))
async def zam_doremove_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id): await cb.answer("❌",show_alert=True); return
    nick=cb.data.split(":",1)[1]
    if remove_zam_nick(nick):
        save_data(); await log_action(cb.from_user.id,"удалил зама",nick); await cb.message.edit_text("✅ Зам удалён."); await cb.answer()
    else: await cb.answer("❌ Не найден",show_alert=True)

@dp.message(lambda m: m.from_user.id in zam_edit_mode and bool(m.text))
async def zam_edit_text(message: Message):
    if not is_super_admin(message.from_user.id): return
    state=zam_edit_mode.pop(message.from_user.id,None)
    if not state: return
    if state.get("action") == "add":
        args = message.text.strip().split(maxsplit=1)
        if len(args) < 2:
            await message.answer("❌ Формат: <code>@username Game_Nick</code>")
            return
        await add_zam_by_username(message, args[0], args[1])
        await send_zam_stats(message, 0)
        return
    old=state["old_nick"]; field=state["field"]
    if old not in data.get("zam_data",{}): await message.answer("❌ Зам не найден."); return
    val=message.text.strip()
    if field=="tg_username":
        val=val.lstrip("@").strip() if val!="—" else None
        data["zam_data"][old]["tg_username"]=val
        audit_record(message.from_user.id,"zams","изменил @username зама",f"{old} → @{val}" if val else f"{old} → —")
        save_data(); await message.answer("✅ @username обновлён.")
    else:
        if not val: await message.answer("❌ Nickname не может быть пустым."); return
        if val!=old and val in data.get("zam_data",{}): await message.answer("❌ Такой зам уже существует."); return
        info=data["zam_data"].pop(old); stat=data.get("zam_stats",{}).pop(old,{"count":0,"withdrawn":0,"history":[]})
        data["zam_data"][val]=info; data["zam_stats"][val]=stat
        save_data(); await log_action(message.from_user.id,"изменил nickname зама",f"{old} → {val}"); await message.answer("✅ Nickname зама изменён.")
    await send_zam_stats(message,0)


# =========================================================
# ВЫВОД
# =========================================================

# Старый вывод из банка замов отключён. Исторические поля в data.json сохраняются для совместимости.


# =========================================================
# ЛОГИ / АУДИТ
# =========================================================

AUDIT_CATEGORIES = [
    ("all", "📋 Все"),
    ("zams", "👑 Замы"),
    ("admins", "🛡 Админка"),
    ("applications", "📝 Заявки"),
    ("users", "👥 Участники"),
    ("surveys", "📋 Анкеты"),
    ("commands", "⌨️ Команды"),
]

def audit_name(actor_id):
    return get_admin_display(actor_id) if actor_id else "система"

def audit_keyboard(category, page, pages):
    rows=[]
    rows.append([InlineKeyboardButton(text=label,callback_data=f"audit_cat:{key}") for key,label in AUDIT_CATEGORIES[:4]])
    rows.append([InlineKeyboardButton(text=label,callback_data=f"audit_cat:{key}") for key,label in AUDIT_CATEGORIES[4:]])
    nav=[]
    if page>0: nav.append(InlineKeyboardButton(text="⬅️",callback_data=f"audit_page:{category}:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{pages}",callback_data="audit_noop"))
    if page<pages-1: nav.append(InlineKeyboardButton(text="➡️",callback_data=f"audit_page:{category}:{page+1}"))
    rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)

def filtered_audit(category):
    events=data.get("audit_events",[])
    if category=="all": return list(reversed(events))
    return list(reversed([e for e in events if e.get("category")==category]))

async def send_audit_page(message, category="all", page=0):
    events=filtered_audit(category); per=8; pages=max(1,(len(events)+per-1)//per); page=max(0,min(page,pages-1))
    chunk=events[page*per:(page+1)*per]
    label=dict(AUDIT_CATEGORIES).get(category,"📋 Все")
    text=f"📜 <b>Журнал действий</b>\nКатегория: <b>{label}</b>\nВсего: <b>{len(events)}</b>\n\n"
    if not chunk: text += "📭 Записей нет."
    for e in chunk:
        t=str(e.get("time","")); actor=escape(audit_name(e.get("actor_id"))); action=escape(str(e.get("action",""))); details=escape(str(e.get("details","")))
        text += f"🕐 <b>{escape(t.replace('T',' '))}</b>\n👤 {actor}\n➡️ {action}\n{details}\n\n"
    await message.answer(text[:4000],reply_markup=audit_keyboard(category,page,pages))

@dp.message(Command("logs"))
async def logs_cmd(message: Message):
    if not is_super_admin(message.from_user.id): await message.answer("❌ Только владелец!"); return
    await send_audit_page(message)

@dp.message(F.text == "📜 Журнал действий")
async def logs_btn(message: Message):
    if not is_super_admin(message.from_user.id): await message.answer("❌ Только владелец!"); return
    await send_audit_page(message)

@dp.callback_query(F.data.startswith("audit_cat:"))
async def audit_cat_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id): await cb.answer("❌",show_alert=True); return
    cat=cb.data.split(":",1)[1]; await cb.answer(); await send_audit_page(cb.message,cat,0)

@dp.callback_query(F.data.startswith("audit_page:"))
async def audit_page_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id): await cb.answer("❌",show_alert=True); return
    _,cat,page=cb.data.split(":"); await cb.answer(); await send_audit_page(cb.message,cat,int(page))

@dp.callback_query(F.data=="audit_noop")
async def audit_noop_cb(cb: CallbackQuery): await cb.answer()

@dp.message(Command("clearlogs"))
async def clear_logs(message: Message):
    if not is_super_admin(message.from_user.id): await message.answer("❌ Только владелец!"); return
    save_logs([]); data["audit_events"]=[]; save_data(); audit_record(message.from_user.id,"commands","очистил журнал")
    await message.answer("✅ Журнал очищен.")


# =========================================================
# УВЕДОМЛЕНИЯ
# =========================================================

@dp.message(Command("log_on"))
async def log_on(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return

    data["log_notify_enabled"] = True
    save_data()

    await message.answer("✅ Уведомления включены.")


@dp.message(Command("log_off"))
async def log_off(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return

    data["log_notify_enabled"] = False
    save_data()

    await message.answer("❌ Уведомления выключены.")


# =========================================================
# СТАТУС БАЗЫ
# =========================================================

@dp.message(Command("db_status"))
async def db_status_cmd(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return

    if DATABASE_URL and psycopg2 is not None and _db_init():
        saved = _db_get("data")
        logs = _db_get("logs")
        await message.answer(
            "✅ <b>Постоянная база подключена</b>\n\n"
            f"👥 Пользователей: <b>{len(saved.get('users', {})) if isinstance(saved, dict) else len(data.get('users', {}))}</b>\n"
            f"📋 Заявок: <b>{len(saved.get('applications', {})) if isinstance(saved, dict) else len(data.get('applications', {}))}</b>\n"
            f"📜 Логов: <b>{len(logs) if isinstance(logs, list) else 0}</b>"
        )
    else:
        await message.answer(
            "⚠️ <b>PostgreSQL не подключён.</b>\n\n"
            "Добавь DATABASE_URL в Render, иначе локальная база может исчезнуть после redeploy/restart."
        )


# =========================================================
# ПИНГ
# =========================================================

@dp.message(Command("ping"))
async def ping(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Только админы!")
        return

    start = datetime.now()

    m = await message.answer("🏓 ...")

    d = (datetime.now() - start).total_seconds() * 1000
    up = datetime.now() - BOT_START_TIME

    days = up.days
    sec = up.seconds

    h, rem = divmod(sec, 3600)
    mn, sc = divmod(rem, 60)

    await m.edit_text(
        f"🏓 Понг! {d:.1f} мс\n"
        f"⏱ Аптайм: {days}д {h}ч {mn}м {sc}с"
    )


@dp.message(Command("myid"))
async def myid_cmd(message: Message):
    await message.answer(
        f"🆔 Твой Telegram ID: <code>{message.from_user.id}</code>\n\n"
        "Для владельца этот ID должен быть указан в переменной <code>SUPER_ADMIN_ID</code>."
    )


# =========================================================
# HELP
# =========================================================

@dp.message(Command("help"))
async def help_cmd(message: Message):
    if is_super_admin(message.from_user.id):
        text = "📋 <b>Управление ботом</b>\n\nВсе основные действия доступны через кнопки меню.\n\n👑 Владелец: управление админами, замами, заявками, участниками и журналом.\n🛡 Админы: заявки, участники, объявления и общий сбор."
    elif is_admin(message.from_user.id):
        text = "📋 <b>Панель администратора</b>\n\nВсе основные действия доступны через кнопки меню.\n\n📝 Заявки • 👥 Участники • 📢 Объявления • 📢 Общий сбор"
    else:
        text = "📋 <b>Меню</b>\n\nЗаполнение анкеты и просмотр профиля доступны через кнопки ниже."
    await message.answer(text)


# =========================================================
# РАСШИРЕННАЯ ПАНЕЛЬ УПРАВЛЕНИЯ / СТАТИСТИКА / GOOGLE SHEETS
# =========================================================

def owner_only(uid):
    return is_super_admin(uid)


def admin_can(uid, permission="manage"):
    if is_super_admin(uid):
        return True
    if not is_admin(uid):
        return False
    perms = data.setdefault("admin_permissions", {})
    current = perms.get(str(uid))
    if current is None:
        return True
    if permission in current:
        return bool(current[permission])
    return True


def dashboard_keyboard(uid):
    rows = [
        [InlineKeyboardButton(text="📋 Заявки", callback_data="dash:apps"), InlineKeyboardButton(text="👥 Участники", callback_data="dash:users")],
        [InlineKeyboardButton(text="👑 Замы", callback_data="dash:zams"), InlineKeyboardButton(text="📊 Статистика", callback_data="dash:stats")],
        [InlineKeyboardButton(text="📢 Объявление", callback_data="dash:announce"), InlineKeyboardButton(text="📢 Общий сбор", callback_data="dash:sbor")],
        [InlineKeyboardButton(text="📜 Журнал", callback_data="dash:audit"), InlineKeyboardButton(text="☁️ Google Таблица", callback_data="dash:sheets")],
    ]
    if is_super_admin(uid):
        rows.append([InlineKeyboardButton(text="🛡 Админы", callback_data="dash:admins"), InlineKeyboardButton(text="⚙️ Настройки", callback_data="dash:settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_keyboard():
    r = data.setdefault("bot_settings", {})
    rem = "🟢" if r.get("reminders_enabled") else "🔴"
    pin = "🟢" if r.get("pin_announcements") else "🔴"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{rem} Напоминания об анкетах", callback_data="set:reminders")],
        [InlineKeyboardButton(text=f"{pin} Закреплять объявления", callback_data="set:pin")],
        [InlineKeyboardButton(text="🔔 Уведомления админа", callback_data="set:notify")],
        [InlineKeyboardButton(text="🧹 Проверить дубли", callback_data="set:duplicates")],
        [InlineKeyboardButton(text="◀️ Панель", callback_data="dash:home")],
    ])


def stats_text():
    users = data.get("users", {})
    apps = data.get("applications", {})
    pending = sum(1 for x in apps.values() if x.get("status") == "pending")
    accepted = sum(1 for x in apps.values() if x.get("status") == "accepted")
    rejected = sum(1 for x in apps.values() if x.get("status") == "rejected")
    active_group = sum(1 for x in data.get("group_members", {}).values() if x.get("status") in ("member", "administrator", "creator"))
    orgs = {}
    for u in users.values():
        org = u.get("organization") or "Не указано"
        orgs[org] = orgs.get(org, 0) + 1
    top_orgs = sorted(orgs.items(), key=lambda x: (-x[1], x[0]))[:8]
    zams = get_all_zam_counts()
    top_zams = sorted(zams, key=lambda x: (-x[1], x[0].lower()))[:5]
    lines = [
        "📊 <b>Статистика семьи</b>",
        "",
        f"👥 Анкет: <b>{len(users)}</b>",
        f"🟢 Принятых заявок: <b>{accepted}</b>",
        f"🟠 Ожидающих: <b>{pending}</b>",
        f"🔴 Отклонённых: <b>{rejected}</b>",
        f"👥 Видимых участников группы: <b>{active_group}</b>",
        f"👑 Замов: <b>{len(data.get('zam_data', {}))}</b>",
        "",
        "🏢 <b>Организации:</b>",
    ]
    lines += [f"• {escape(k)} — <b>{v}</b>" for k,v in top_orgs] or ["• Нет данных"]
    lines += ["", "🏆 <b>Замы по приглашениям:</b>"]
    lines += [f"• {escape(n)} — <b>{c}</b>" for n,c,_,_ in top_zams] or ["• Нет данных"]
    return "\n".join(lines)


def duplicate_report():
    users = data.get("users", {})
    by_nick, by_tag = {}, {}
    for uid,u in users.items():
        nick = str(u.get("nickname") or "").strip().lower()
        tag = str(u.get("tag") or "").strip().lower().lstrip("@")
        if nick: by_nick.setdefault(nick, []).append(uid)
        if tag and tag != "—": by_tag.setdefault(tag, []).append(uid)
    dup_nick = [(k,v) for k,v in by_nick.items() if len(v)>1]
    dup_tag = [(k,v) for k,v in by_tag.items() if len(v)>1]
    lines=["🧹 <b>Проверка дублей</b>",""]
    lines.append(f"Nickname-дубли: <b>{len(dup_nick)}</b>")
    for k,v in dup_nick[:10]: lines.append(f"• {escape(k)} → {', '.join(v)}")
    lines.append(f"@username-дубли: <b>{len(dup_tag)}</b>")
    for k,v in dup_tag[:10]: lines.append(f"• @{escape(k)} → {', '.join(v)}")
    if not dup_nick and not dup_tag: lines.append("\n✅ Дубликатов не найдено.")
    return "\n".join(lines)


def google_client():
    if not gspread or not Credentials or not GOOGLE_SERVICE_ACCOUNT_JSON:
        return None
    try:
        info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(info, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        print(f"Google Sheets init error: {e}")
        return None


def sync_google_sheets_sync():
    client = google_client()
    if client is None:
        return {"ok": False, "error": "Не настроен GOOGLE_SERVICE_ACCOUNT_JSON или отсутствует gspread."}
    try:
        if GOOGLE_SHEET_ID:
            sh = client.open_by_key(GOOGLE_SHEET_ID)
        else:
            sh = client.create(GOOGLE_SHEET_TITLE)
        sheets = {
            "Участники": [["Telegram ID","Nickname","@username","Ранг","Организация","Ранг в орг","Пригласил","Статус"]],
            "Заявки": [["ID","Telegram ID","Nickname","@username","Ранг","Организация","Пригласил","Статус","Создано"]],
            "Замы": [["№","Nickname","@username","Приглашений"]],
            "Статистика": [["Показатель","Значение"]],
            "Журнал": [["Время","Кто","Действие","Подробности"]],
        }
        for title, values in sheets.items():
            try: ws = sh.worksheet(title); ws.clear()
            except Exception: ws = sh.add_worksheet(title=title, rows=1000, cols=12)
            ws.update("A1", values)
        ws=sh.worksheet("Участники")
        rows=[]
        for uid,u in data.get("users",{}).items():
            rows.append([uid,u.get("nickname",""),u.get("tag",""),u.get("rank_fam",""),u.get("organization",""),u.get("rank_org",""),u.get("inviter",""),u.get("status","accepted")])
        if rows: ws.update("A2", rows)
        ws=sh.worksheet("Заявки"); rows=[]
        for aid,a in data.get("applications",{}).items():
            d=a.get("data",a)
            rows.append([aid,a.get("user_id",""),d.get("nickname",""),d.get("tag",d.get("username","")),d.get("rank_fam",""),d.get("organization",""),d.get("inviter",""),a.get("status",""),a.get("created","" )])
        if rows: ws.update("A2", rows)
        ws=sh.worksheet("Замы"); rows=[]
        for i,(nick,info) in enumerate(data.get("zam_data",{}).items(),1): rows.append([i,nick,info.get("tg_username") or "",count_zam_answers(nick)])
        if rows: ws.update("A2", rows)
        ws=sh.worksheet("Статистика"); rows=[
            ["Анкет",len(data.get("users",{}))],
            ["Ожидающих заявок",sum(1 for a in data.get("applications",{}).values() if a.get("status")=="pending")],
            ["Принятых заявок",sum(1 for a in data.get("applications",{}).values() if a.get("status")=="accepted")],
            ["Отклонённых заявок",sum(1 for a in data.get("applications",{}).values() if a.get("status")=="rejected")],
            ["Замов",len(data.get("zam_data",{}))],
        ]; ws.update("A2",rows)
        ws=sh.worksheet("Журнал"); rows=[]
        for e in data.get("audit_events",[])[-1000:]: rows.append([e.get("time",""),audit_name(e.get("actor_id")),e.get("action",""),e.get("details","")])
        if rows: ws.update("A2",rows)
        data["google_sheet_url"] = sh.url
        save_data()
        return {"ok": True, "url": sh.url}
    except Exception as e:
        return {"ok": False, "error": str(e)[:500]}


def google_sheet_url():
    return data.get("google_sheet_url") or (f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/edit" if GOOGLE_SHEET_ID else "")


@dp.message(F.text == "🏠 Панель управления")
async def dashboard_btn(message: Message):
    if not is_admin(message.from_user.id): return
    await message.answer("🏠 <b>Панель управления</b>\nВыберите действие:", reply_markup=dashboard_keyboard(message.from_user.id))

@dp.message(F.text == "📊 Статистика")
async def stats_btn(message: Message):
    if not is_admin(message.from_user.id): return
    await message.answer(stats_text(), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🧹 Проверить дубли",callback_data="set:duplicates")],[InlineKeyboardButton(text="◀️ Панель",callback_data="dash:home")]]))

@dp.message(F.text == "☁️ Google Таблица")
async def sheets_btn(message: Message):
    if not is_super_admin(message.from_user.id): return
    url=google_sheet_url()
    text="☁️ <b>Google Таблица</b>\n\n" + (f"Последняя таблица:\n{escape(url)}" if url else "Таблица ещё не создана.")
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Синхронизировать",callback_data="sheets:sync")],[InlineKeyboardButton(text="◀️ Панель",callback_data="dash:home")]]))

@dp.message(F.text == "⚙️ Настройки")
async def settings_btn(message: Message):
    if not is_super_admin(message.from_user.id): return
    await message.answer("⚙️ <b>Настройки бота</b>",reply_markup=settings_keyboard())

@dp.callback_query(F.data.startswith("dash:"))
async def dashboard_cb(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌ Нет прав",show_alert=True)
    action=cb.data.split(":",1)[1]
    await cb.answer()
    if action=="home": await cb.message.edit_text("🏠 <b>Панель управления</b>\nВыберите действие:",reply_markup=dashboard_keyboard(cb.from_user.id))
    elif action=="apps": await send_apps_page(cb.message,"pending",0)
    elif action=="users": await send_users_page(cb.message,"all",0)
    elif action=="zams": await send_zam_stats(cb.message,0)
    elif action=="stats": await cb.message.edit_text(stats_text(),reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🧹 Дубли",callback_data="set:duplicates")],[InlineKeyboardButton(text="◀️ Панель",callback_data="dash:home")]]))
    elif action=="audit": await send_audit_page(cb.message)
    elif action=="admins": await cb.message.edit_text("🛡 <b>Админка</b>",reply_markup=admin_panel_keyboard())
    elif action=="settings": await cb.message.edit_text("⚙️ <b>Настройки бота</b>",reply_markup=settings_keyboard())
    elif action=="sheets":
        url=google_sheet_url(); await cb.message.edit_text("☁️ <b>Google Таблица</b>\n\n"+(escape(url) if url else "Таблица ещё не создана."),reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Синхронизировать",callback_data="sheets:sync")],[InlineKeyboardButton(text="◀️ Панель",callback_data="dash:home")]]))
    elif action=="announce":
        announcement_mode[cb.from_user.id]={"pin":False}; await cb.message.answer("📣 Напишите текст объявления одним сообщением.\nДля отмены: /cancel")
    elif action=="sbor":
        await start_gather_from_button(cb.message)

@dp.callback_query(F.data.startswith("set:"))
async def settings_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id): return await cb.answer("❌ Только владелец",show_alert=True)
    action=cb.data.split(":",1)[1]
    if action=="reminders": data.setdefault("bot_settings",{})["reminders_enabled"]=not data.setdefault("bot_settings",{}).get("reminders_enabled",False); save_data(); await cb.message.edit_text("⚙️ Настройки",reply_markup=settings_keyboard()); await cb.answer("Готово")
    elif action=="pin": data.setdefault("bot_settings",{})["pin_announcements"]=not data.setdefault("bot_settings",{}).get("pin_announcements",False); save_data(); await cb.message.edit_text("⚙️ Настройки",reply_markup=settings_keyboard()); await cb.answer("Готово")
    elif action=="notify":
        cur=data.setdefault("notify_settings",{}).get(str(cb.from_user.id),True); data["notify_settings"][str(cb.from_user.id)]=not cur; save_data(); await cb.message.edit_text("⚙️ Настройки",reply_markup=settings_keyboard()); await cb.answer("Уведомления " + ("включены" if not cur else "выключены"))
    elif action=="duplicates": await cb.message.edit_text(duplicate_report(),reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Настройки",callback_data="dash:settings")]])); await cb.answer()

@dp.callback_query(F.data=="sheets:sync")
async def sheets_sync_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id): return await cb.answer("❌ Только владелец",show_alert=True)
    await cb.answer("Синхронизация запущена")
    result=await asyncio.to_thread(sync_google_sheets_sync)
    if result.get("ok"):
        await cb.message.edit_text("✅ <b>Google Таблица обновлена.</b>\n\n"+escape(result.get("url","")),reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Обновить ещё раз",callback_data="sheets:sync")],[InlineKeyboardButton(text="◀️ Панель",callback_data="dash:home")]]))
    else:
        await cb.message.edit_text("❌ <b>Google Таблица не настроена</b>\n\n"+escape(result.get("error","Неизвестная ошибка"))+"\n\nДобавь GOOGLE_SERVICE_ACCOUNT_JSON в Render и дай сервисному аккаунту доступ к таблице.",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Панель",callback_data="dash:home")]]))

# Объявление через кнопку.
@dp.message(lambda m: m.from_user.id in announcement_mode and bool(m.text) and not m.text.startswith("/"))
async def announcement_text_handler(message: Message):
    if not is_admin(message.from_user.id): return
    announcement_mode.pop(message.from_user.id,None)
    try:
        sent=await bot.send_message(GROUP_ID,message.text,message_thread_id=ANNOUNCE_TOPIC_ID)
        if data.setdefault("bot_settings",{}).get("pin_announcements"):
            try: await bot.pin_chat_message(GROUP_ID,sent.message_id,disable_notification=True)
            except Exception: pass
        audit_record(message.from_user.id,"commands","отправил объявление",message.text,command="кнопка: объявление")
        await message.answer("✅ Объявление отправлено.")
    except Exception as e:
        await message.answer("❌ Не удалось отправить объявление: "+escape(str(e)[:300]))

# Сообщение участнику из карточки.
participant_message_mode = {}
@dp.callback_query(F.data.startswith("user_message:"))
async def user_message_cb(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌ Нет прав",show_alert=True)
    uid=cb.data.split(":",1)[1]
    if uid not in data.get("users",{}): return await cb.answer("Участник не найден",show_alert=True)
    participant_message_mode[cb.from_user.id]=uid
    await cb.message.answer("📨 Напишите сообщение участнику одним сообщением.\nДля отмены: /cancel")
    await cb.answer()

@dp.message(lambda m: m.from_user.id in participant_message_mode and bool(m.text))
async def user_message_handler(message: Message):
    uid=participant_message_mode.pop(message.from_user.id,None)
    if not uid or not is_admin(message.from_user.id): return
    try:
        await bot.send_message(int(uid),"📨 <b>Сообщение от администрации:</b>\n\n"+escape(message.text))
        await message.answer("✅ Сообщение отправлено.")
        audit_record(message.from_user.id,"users","отправил сообщение участнику",f"{uid}: {message.text[:500]}")
    except Exception as e: await message.answer("❌ Не удалось отправить сообщение: "+escape(str(e)[:300]))

# Добавляем кнопку сообщения в карточку участника, если функция уже существует.
try:
    _old_user_card_keyboard = user_card_keyboard
    def user_card_keyboard(uid):
        kb=_old_user_card_keyboard(uid)
        rows=list(kb.inline_keyboard)
        rows.insert(-1,[InlineKeyboardButton(text="📨 Написать сообщение",callback_data=f"user_message:{uid}")])
        return InlineKeyboardMarkup(inline_keyboard=rows)
except Exception:
    pass

# Общий сбор: короткий режим через кнопку. Отправляет упоминания известных участников.
async def start_gather_from_button(message: Message):
    if not is_admin(message.from_user.id): return await message.answer("❌ Нет прав")
    members=[]
    for uid,u in data.get("users",{}).items():
        tag=u.get("tag")
        if tag and tag != "—": members.append("@"+str(tag).lstrip("@"))
    if not members:
        return await message.answer("❌ Нет участников с @username.")
    text="📢 <b>ОБЩИЙ СБОР!</b>\n\n"+" ".join(members)
    try:
        await bot.send_message(GROUP_ID,text,message_thread_id=ANNOUNCE_TOPIC_ID)
        await message.answer(f"✅ Общий сбор отправлен. Упомянуто: {len(members)}")
        audit_record(message.from_user.id,"commands","запустил общий сбор",f"Упомянуто: {len(members)}",command="кнопка: общий сбор")
    except Exception as e: await message.answer("❌ Ошибка: "+escape(str(e)[:300]))

@dp.message(F.text == "📢 Объявление")
async def announcement_btn(message: Message):
    if not is_admin(message.from_user.id): return
    announcement_mode[message.from_user.id]={"pin":False}
    await message.answer("📣 Напишите текст объявления одним сообщением.")

@dp.message(F.text == "📢 Общий сбор")
async def gather_btn(message: Message):
    await start_gather_from_button(message)

# Ежедневное напоминание тем, кого бот знает по группе, но у кого нет анкеты.
async def reminder_worker():
    while True:
        try:
            await asyncio.sleep(3600)
            if not data.setdefault("bot_settings",{}).get("reminders_enabled"): continue
            now=datetime.now()
            for uid,info in list(data.get("group_members",{}).items()):
                if str(uid) in data.get("users",{}): continue
                last=data.setdefault("last_reminders",{}).get(str(uid))
                if last:
                    try:
                        if (now-datetime.fromisoformat(last)).total_seconds()<86400: continue
                    except Exception: pass
                try:
                    await bot.send_message(int(uid),"📋 Напоминание: пожалуйста, перейдите в бота и заполните анкету.")
                    data["last_reminders"][str(uid)]=now.isoformat(); save_data()
                except Exception: pass
        except asyncio.CancelledError: return
        except Exception as e: print("reminder_worker:",e)

# =========================================================
# КОМАНДЫ TELEGRAM ПО РОЛЯМ
# =========================================================

DEFAULT_COMMANDS = [
    BotCommand(command="start", description="🏠 Меню"),
    BotCommand(command="help", description="📖 Справка"),
    BotCommand(command="myid", description="🆔 Мой Telegram ID"),
]

ADMIN_COMMANDS = [
    BotCommand(command="start", description="🏠 Меню"),
    BotCommand(command="help", description="📖 Справка"),
]

OWNER_COMMANDS = ADMIN_COMMANDS

async def set_command_scopes():
    # Все основные действия остаются в кнопках; команды — только резерв.
    try:
        await bot.set_my_commands(DEFAULT_COMMANDS, scope=BotCommandScopeDefault())
    except Exception as e:
        print(f"⚠️ Не удалось установить базовые команды: {e}")
    for admin_id in get_admins():
        try:
            await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=int(admin_id)))
        except Exception as e:
            print(f"⚠️ Не удалось установить команды для {admin_id}: {e}")
    try:
        await bot.set_my_commands(OWNER_COMMANDS, scope=BotCommandScopeChat(chat_id=SUPER_ADMIN))
    except Exception as e:
        print(f"⚠️ Не удалось установить команды владельца: {e}")

async def main():
    print("🤖 Бот запускается...")

    if not DATABASE_URL:
        raise RuntimeError(
            "❌ DATABASE_URL не задан. Добавь URL Supabase в Render Environment. "
            "Бот намеренно не запускается без постоянной базы, чтобы не потерять данные."
        )

    if not _db_init():
        raise RuntimeError(
            "❌ Не удалось подключиться к постоянной PostgreSQL базе. "
            "Проверь DATABASE_URL в Render Environment."
        )

    print("✅ Постоянная база PostgreSQL подключена. Локальный data.json больше не является источником истины.")

    await init_telegram_user_client()
    await init_admins()
    await set_command_scopes()

    await bot.delete_webhook(drop_pending_updates=True)

    print("🤖 Бот запущен!")
    print("📌 Основная группа:", GROUP_LINK)

    asyncio.create_task(reminder_worker())
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Бот остановлен.")
