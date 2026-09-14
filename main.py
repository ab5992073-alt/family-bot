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
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from flask import Flask

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
# БАЗА ДАННЫХ
# =========================================================

DATA_FILE = "data.json"
LOG_FILE = "bot_activity.log"
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

_db_warned = False


def _db_connect():
    if not DATABASE_URL or psycopg2 is None:
        return None
    try:
        return psycopg2.connect(DATABASE_URL, connect_timeout=10)
    except Exception as e:
        global _db_warned
        if not _db_warned:
            print(f"⚠️ PostgreSQL недоступен, временно используется локальная база: {e}")
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


def save_data():
    # Локальный файл оставляем как аварийную копию.
    _write_local_json(DATA_FILE, data)

    # Основное постоянное хранилище.
    if DATABASE_URL and psycopg2 is not None:
        _db_set("data", data)


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
        KeyboardButton(text="🛠 Админка"),
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
            [
                InlineKeyboardButton(
                    text="📊 Статистика",
                    callback_data="zam:stats",
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


async def start_survey(message: Message):
    uid = message.from_user.id

    user_surveys[uid] = {
        "step": 0,
        "answers": {},
    }

    await log_action(uid, "анкета", "начал")

    await message.answer(
        "📋 <b>Заполнение анкеты</b>\n\n"
        "1️⃣ Ваш Nickname в игре?"
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
                        callback_data=f"zam_{z}",
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
    user_surveys[uid]["step"] = 3

    await cb.answer(f"✅ {org}")
    await cb.message.answer("📌 Ваш ранг в организации?")


# =========================================================
# ВЫБОР ЗАМА
# =========================================================

@dp.callback_query(F.data.startswith("zam_"))
async def zam_selected(cb: CallbackQuery):
    uid = cb.from_user.id

    if uid not in user_surveys:
        await cb.answer("❌ Анкета не найдена.")
        return

    zam = cb.data[4:]

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

    await message.answer("✅ <b>Анкета заполнена!</b>")

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


@dp.message(F.text == "📝 Заполнить анкету")
async def survey_button(message: Message):
    uid = message.from_user.id

    if str(uid) in data["users"]:
        await message.answer(
            "ℹ️ Вы уже заполнили. Используйте «🔄 Перезаполнить анкету»."
        )
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
    ok, text = await change_application_verdict(
        app_id,
        "accepted",
        cb.from_user.id,
    )
    await cb.answer("✅ Принят" if ok else text, show_alert=not ok)
    if ok:
        try:
            await cb.message.edit_text(
                application_text(data["applications"][app_id], None),
                reply_markup=application_keyboard(app_id),
            )
        except Exception:
            pass


@dp.callback_query(F.data.startswith("reject:"))
async def reject_app(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет прав!", show_alert=True)
        return

    app_id = cb.data.split(":", 1)[1]
    ok, text = await change_application_verdict(
        app_id,
        "rejected",
        cb.from_user.id,
    )
    await cb.answer("❌ Отклонён" if ok else text, show_alert=not ok)
    if ok:
        try:
            await cb.message.edit_text(
                application_text(data["applications"][app_id], None),
                reply_markup=application_keyboard(app_id),
            )
        except Exception:
            pass


def application_keyboard(app_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Принять",
                    callback_data=f"accept:{app_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"reject:{app_id}",
                ),
            ]
        ]
    )


def application_text(app, idx=None):
    u = app["data"]
    status = app.get("status", "pending")
    status_text = {
        "pending": "⏳ Ожидает решения",
        "accepted": "✅ Принята",
        "rejected": "❌ Отклонена",
        "cancelled": "🚫 Отменена",
    }.get(status, status)

    prefix = (
        f"<b>Заявка #{idx}</b>"
        if idx is not None
        else "<b>Заявка</b>"
    )

    return (
        f"{prefix}\n"
        f"Статус: <b>{status_text}</b>\n\n"
        f"Nickname: {escape(u.get('nickname', '—'))}\n"
        f"Тег: {escape(u.get('tag', '—'))}\n"
        f"Ранг: {escape(u.get('rank_fam', '—'))}\n"
        f"Орг: {escape(u.get('organization', '—'))}\n"
        f"Ранг в орг: {escape(u.get('rank_org', '—'))}\n"
        f"Пригласил: {escape(u.get('inviter', '—'))}"
    )


@dp.message(F.text == "📋 Управление заявками")
async def all_apps(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌")
        return

    apps = data["applications"]

    if not apps:
        await message.answer("📭 Заявок нет.")
        return

    idx = 1

    for app_id, app in apps.items():
        status = app.get("status", "pending")
        icon = {
            "pending": "⏳",
            "accepted": "✅",
            "rejected": "❌",
            "cancelled": "🚫",
        }.get(status, "❔")

        text = application_text(app, idx).replace(
            "⏳ <b>",
            f"{icon} <b>",
            1,
        )

        kb = application_keyboard(app_id) if status in {"pending", "accepted", "rejected"} else None

        await message.answer(text, reply_markup=kb)
        idx += 1


@dp.message(F.text == "⏳ Активные заявки")
async def active_apps(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌")
        return

    pend = {
        k: v
        for k, v in data["applications"].items()
        if v.get("status") == "pending"
    }

    if not pend:
        await message.answer("📭 Нет активных.")
        return

    idx = 1

    for app_id, app in pend.items():
        await message.answer(
            application_text(app, idx),
            reply_markup=application_keyboard(app_id),
        )
        idx += 1


# =========================================================
# СПИСОК УЧАСТНИКОВ
# =========================================================

@dp.message(F.text == "👥 Список участников")
async def list_users(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌")
        return

    users = list(data["users"].items())

    if not users:
        await message.answer("📭 Нет анкет.")
        return

    await send_users_page(message, users, 0)


async def send_users_page(message, users, page):
    per = 3
    total = len(users)
    pages = (total + per - 1) // per

    if page < 0 or page >= pages:
        return

    start = page * per
    end = min(page * per + per, total)

    text = "👥 <b>Список участников</b>\n\n"

    for i in range(start, end):
        uid, u = users[i]

        text += (
            f"<b>{i + 1}.</b> "
            f"{escape(u.get('nickname', '—'))} "
            f"— {escape(u.get('tag', uid))}\n"
            f"   Ранг: {escape(u.get('rank_fam', '—'))} | "
            f"Орг: {escape(u.get('organization', '—'))}\n"
            f"   Пригласил: {escape(u.get('inviter', '—'))}\n\n"
        )

    text += f"Стр. {page + 1} из {pages}"

    rows = []

    if page > 0:
        rows.append(
            [
                InlineKeyboardButton(
                    text="⬅️",
                    callback_data=f"up_{page - 1}",
                )
            ]
        )

    if page < pages - 1:
        rows.append(
            [
                InlineKeyboardButton(
                    text="➡️",
                    callback_data=f"up_{page + 1}",
                )
            ]
        )

    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=rows
        ) if rows else None,
    )


@dp.callback_query(F.data.startswith("up_"))
async def up_cb(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌")
        return

    users = list(data["users"].items())

    await send_users_page(
        cb.message,
        users,
        int(cb.data.split("_")[1]),
    )
    await cb.answer()


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
        "<code>/add_admin @username</code> — добавить\n"
        "<code>/remove_admin @username</code> — удалить\n\n"
        "Также работают:\n"
        "<code>/add admin @username</code>\n"
        "<code>/remove admin @username</code>\n\n"
        "Если Telegram ещё не сообщает ID пользователя, бот поставит его в ожидание и "
        "автоматически выдаст админку при первом замеченном сообщении этого пользователя."
    )


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
    zams = get_all_zam_counts()
    if not zams:
        text = "👑 <b>Управление замами</b>\n\n📭 Замов пока нет."
    else:
        text = "👑 <b>Управление замами</b>\n\n"
        for nick, current, withdrawn, available in zams:
            info = data["zam_data"].get(nick, {})
            tg = info.get("tg_username")
            tg_text = f" (@{escape(tg)})" if tg else ""
            text += (
                f"👤 <b>{escape(nick)}</b>{tg_text}\n"
                f"   📋 Анкет: {current}\n"
                f"   💸 Выведено: {withdrawn}\n"
                f"   🟢 Доступно: {available}\n\n"
            )
    await message.answer(text + "\n➕ <code>/add_zam @username Game_Nick</code>\n➖ <code>/remove_zam Game_Nick</code>")


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
    await cb.message.answer("➕ Используй: <code>/add_zam @username Game_Nick</code>")
    await cb.answer()


@dp.callback_query(F.data == "zam:remove")
async def zam_remove_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True)
        return
    await cb.message.answer("➖ Используй: <code>/remove_zam Game_Nick</code>")
    await cb.answer()


@dp.callback_query(F.data == "zam:stats")
async def zam_stats_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True)
        return
    await send_zam_stats(cb.message)
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
# СТАТИСТИКА ЗАМОВ
# =========================================================

async def send_zam_stats(message: Message):
    zams = get_all_zam_counts()

    if not zams:
        await message.answer("📭 Замов нет.")
        return

    text = "📊 <b>АКТУАЛЬНАЯ СТАТИСТИКА ЗАМОВ</b>\n\n"

    for nick, current, withdrawn, available in zams:
        text += (
            f"👤 <b>{escape(nick)}</b>\n"
            f"   📋 Приглашено сейчас: {current}\n"
            f"   💸 Уже выведено: {withdrawn}\n"
            f"   🟢 Доступно для вывода: {available}\n\n"
        )

    text += (
        "ℹ️ Статистика считается по текущим анкетам.\n"
        "После вывода использованные приглашения повторно не начисляются."
    )

    await message.answer(text)


@dp.message(Command("zam_stats"))
async def zam_stats_cmd(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return

    await send_zam_stats(message)


# =========================================================
# ВЫВОД
# =========================================================

@dp.message(Command("withdraw"))
async def withdraw(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return

    args = message.text.split(maxsplit=2)

    if len(args) < 3:
        await message.answer("❌ /withdraw @ник сумма (тыс.)")
        return

    username = args[1].lstrip("@")

    try:
        amount = int(args[2])
    except Exception:
        await message.answer("❌ Сумма числом.")
        return

    if amount < 100 or amount % 100 != 0:
        await message.answer("❌ Мин. 100 и кратна 100.")
        return

    game_nick = None

    for nick, info in data["zam_data"].items():
        tg_username = info.get("tg_username")

        if (
            tg_username
            and tg_username.lower() == username.lower()
        ):
            game_nick = nick
            break

    if not game_nick:
        await message.answer("❌ Зам не найден.")
        return

    available = get_zam_available(game_nick)
    need = amount // 100

    if available < need:
        await message.answer(
            f"❌ Недостаточно доступных приглашений "
            f"({available}/{need})."
        )
        return

    stat = data["zam_stats"].setdefault(
        game_nick,
        {"count": 0, "withdrawn": 0, "history": []},
    )

    stat["withdrawn"] = int(stat.get("withdrawn", 0)) + need
    stat.setdefault("history", []).append(
        {
            "amount": amount,
            "invites": need,
            "by": message.from_user.id,
            "created": datetime.now().isoformat(),
        }
    )

    save_data()

    uid = get_zam_user_id(game_nick)

    if uid:
        try:
            await bot.send_message(
                uid,
                f"💰 Вам начислено списание {amount}k.\n"
                f"Использовано приглашений: {need}.",
            )
        except Exception:
            pass

    await log_action(
        message.from_user.id,
        "вывод зама",
        f"{game_nick}: {amount}k",
    )

    await message.answer(
        f"✅ Снято {amount}k с <b>{escape(game_nick)}</b>.\n"
        f"Использовано приглашений: {need}.\n"
        f"Осталось доступных: {get_zam_available(game_nick)}"
    )


# =========================================================
# ЛОГИ
# =========================================================

@dp.message(Command("logs"))
async def logs_cmd(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return

    lines = load_logs()

    if not lines:
        await message.answer("📭 Пусто.")
        return

    await send_logs_page(message, lines, 0)


async def send_logs_page(message, lines, page):
    per = 10
    total = len(lines)
    pages = max(1, (total + per - 1) // per)

    if page < 0 or page >= pages:
        return

    start = page * per
    end = min(page * per + per, total)

    text = (
        f"📋 <b>Журнал (стр. {page + 1}/{pages})</b>\n\n"
        + "".join(lines[start:end])
    )

    if len(text) > 4000:
        text = text[:3900] + "\n... (обрезано)"

    rows = []

    if page > 0:
        rows.append(
            [
                InlineKeyboardButton(
                    text="⬅️",
                    callback_data=f"lp_{page - 1}",
                )
            ]
        )

    if page < pages - 1:
        rows.append(
            [
                InlineKeyboardButton(
                    text="➡️",
                    callback_data=f"lp_{page + 1}",
                )
            ]
        )

    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=rows
        ) if rows else None,
    )


@dp.callback_query(F.data.startswith("lp_"))
async def lp_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌")
        return

    lines = load_logs()

    await send_logs_page(
        cb.message,
        lines,
        int(cb.data.split("_")[1]),
    )
    await cb.answer()


@dp.message(F.text == "📜 Журнал действий")
async def logs_btn(message: Message):
    await logs_cmd(message)


@dp.message(Command("clearlogs"))
async def clear_logs(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return

    save_logs([])

    await message.answer("✅ Логи очищены.")


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
        text = (
            "📋 <b>Команды владельца:</b>\n\n"
            "/start — меню\n"
            "/help — справка\n"
            "/ping — пинг\n"
            "/all — объявление\n"
            "/add admin — выдать админа\n"
            "/add zam — добавить зама\n"
            "/remove admin — удалить админа\n"
            "/remove zam — удалить зама\n"
            "/add_zam — добавить зама\n"
            "/remove_zam — удалить зама\n"
            "/admins — список админов\n"
            "/zam_stats — статистика замов\n"
            "/withdraw — вывод\n"
            "/logs — журнал\n"
            "/clearlogs — очистить журнал\n"
            "/log_on — уведомления вкл\n"
            "/log_off — уведомления выкл\n"
            "/topic_id — ID темы\n"
            "/sbor — общий сбор\n"
            "/stopsbor — остановить сбор\n"
            "/set_token — смена токена\n"
        )
    elif is_admin(message.from_user.id):
        text = (
            "📋 <b>Команды администратора:</b>\n\n"
            "/start — меню\n"
            "/help — справка\n"
            "/ping — пинг\n"
            "/all — объявление\n"
            "/кто — информация об участнике\n"
            "/topic_id — ID темы\n"
            "/sbor — общий сбор\n"
            "/stopsbor — остановить сбор\n"
        )
    else:
        text = (
            "📋 <b>Команды:</b>\n\n"
            "/start — меню\n"
            "/help — справка\n"
        )

    await message.answer(text)


# =========================================================
# ОБЩИЙ СБОР
# =========================================================

GATHER_DURATION_SECONDS = 90
GATHER_INTERVAL_SECONDS = 20
GATHER_CHUNK_SIZE = 25


def _is_known_group_member(user_id):
    uid = str(user_id)
    if uid in data.get("group_members", {}):
        return True

    # Пользователи с заполненной анкетой считаются кандидатами для созыва
    # только после того, как бот видел их в группе. Это не даёт тегать людей,
    # которых мог уже не быть в чате.
    return False


async def get_gather_members():
    """
    Получает АКТУАЛЬНЫЙ полный список участников группы через
    пользовательскую Telegram-сессию Telethon.

    Bot API не умеет выдавать полный список участников супергруппы,
    поэтому для команды «общий сбор» используется именно user-session.
    Если Telethon не подключен, используем сохранённых участников как
    безопасный fallback и явно сообщаем об этом в логи.
    """
    members = []

    if telegram_user_is_ready():
        try:
            entity = None

            # Сначала пытаемся найти группу среди диалогов пользовательской сессии.
            async for dialog in telegram_user_client.iter_dialogs():
                try:
                    peer_id = utils.get_peer_id(dialog.entity)
                    if peer_id == GROUP_ID:
                        entity = dialog.entity
                        break
                except Exception:
                    continue

            # Если в диалогах не нашли — пробуем получить сущность напрямую.
            if entity is None:
                try:
                    entity = await telegram_user_client.get_entity(GROUP_ID)
                except Exception:
                    entity = None

            if entity is not None:
                seen = set()

                async for user in telegram_user_client.iter_participants(entity):
                    try:
                        user_id = int(user.id)
                    except (TypeError, ValueError):
                        continue

                    if user_id in seen:
                        continue
                    seen.add(user_id)

                    if getattr(user, "bot", False):
                        continue
                    if getattr(user, "deleted", False):
                        continue

                    first = getattr(user, "first_name", None) or ""
                    last = getattr(user, "last_name", None) or ""
                    full_name = f"{first} {last}".strip()
                    username = getattr(user, "username", None)

                    if not full_name:
                        full_name = username or str(user_id)

                    member = {
                        "id": user_id,
                        "name": full_name,
                        "username": username,
                    }
                    members.append(member)

                    # Обновляем локальный кэш тоже: тогда /список участников
                    # и другие функции знают актуальных людей.
                    data.setdefault("group_members", {})[str(user_id)] = {
                        "id": user_id,
                        "username": username,
                        "full_name": full_name,
                        "last_seen": datetime.now().isoformat(),
                    }

                save_data()
                print(f"✅ Общий сбор: Telethon получил {len(members)} участников группы.")
                return members

            print("⚠️ Telethon подключен, но группа не найдена в пользовательской сессии.")

        except Exception as e:
            print(f"⚠️ Не удалось получить полный список участников через Telethon: {e}")

    # Fallback — только ранее известных боту участников.
    # Это не является полным списком, поэтому без user-session полный созыв
    # сделать технически невозможно.
    for uid, info in data.get("group_members", {}).items():
        try:
            user_id = int(uid)
        except (TypeError, ValueError):
            continue

        full_name = (
            info.get("full_name")
            or info.get("username")
            or str(user_id)
        ).strip()

        members.append({
            "id": user_id,
            "name": full_name,
            "username": info.get("username"),
        })

    # Дополнительно подтягиваем принятых участников из анкет — если Bot API
    # может подтвердить, что конкретный пользователь сейчас в группе.
    known_ids = {m["id"] for m in members}
    for app in data.get("applications", {}).values():
        if app.get("status") != "accepted":
            continue
        try:
            user_id = int(app.get("user_id"))
        except (TypeError, ValueError):
            continue
        if user_id in known_ids:
            continue

        try:
            member = await bot.get_chat_member(GROUP_ID, user_id)
            status = getattr(member, "status", "")
            is_member = status in {"member", "administrator", "creator"}
            if status == "restricted":
                is_member = bool(getattr(member, "is_member", False))
            if not is_member:
                continue

            user = getattr(member, "user", None)
            if not user or user.is_bot:
                continue

            members.append({
                "id": user.id,
                "name": user.full_name or user.username or str(user.id),
                "username": user.username or None,
            })
            known_ids.add(user.id)
        except Exception:
            continue

    unique = {}
    for member in members:
        unique[member["id"]] = member

    return list(unique.values())

def mention_html(member):
    name = member.get("name") or member.get("username") or str(member["id"])
    return f'<a href="tg://user?id={member["id"]}">{escape(name)}</a>'


def chunk_mentions(members, size=GATHER_CHUNK_SIZE):
    for i in range(0, len(members), size):
        yield members[i:i + size]


async def send_gather_wave(members, wave_no, total_waves):
    header = (
        f"📢 <b>ОБЩИЙ СБОР</b>\n\n"
        f"Созыв: <b>{wave_no}/{total_waves}</b>\n"
        f"⏱️ Необходимо собраться всем участникам.\n\n"
    )

    chunks = list(chunk_mentions(members))
    if not chunks:
        return False

    for index, chunk in enumerate(chunks):
        body = " ".join(mention_html(member) for member in chunk)
        text = header if index == 0 else "📢 <b>ОБЩИЙ СБОР — продолжение</b>\n\n"
        text += body

        try:
            await bot.send_message(
                GROUP_ID,
                text,
            )
        except Exception as e:
            print(f"⚠️ Ошибка общего сбора: {e}")

    return True


async def run_gather():
    try:
        members = await get_gather_members()
        if not members:
            print("⚠️ Общий сбор: нет известных участников для упоминания.")
            return

        total_waves = (GATHER_DURATION_SECONDS // GATHER_INTERVAL_SECONDS) + 1

        for wave in range(total_waves):
            # Заново собираем список перед каждой волной: новые люди, написавшие
            # в чат во время сбора, автоматически попадут в следующую волну.
            members = await get_gather_members()
            if not members:
                break

            await send_gather_wave(members, wave + 1, total_waves)

            if wave < total_waves - 1:
                await asyncio.sleep(GATHER_INTERVAL_SECONDS)

    finally:
        gather_tasks.pop(GROUP_ID, None)


@dp.message(Command("sbor"))
async def gather_command(message: Message):
    if message.chat.id != GROUP_ID:
        await message.answer("❌ Команду «сбор» нужно запускать в группе.")
        return

    if not is_admin(message.from_user.id):
        await message.answer("❌ Только админы могут объявлять общий сбор!")
        return

    current = gather_tasks.get(GROUP_ID)
    if current and not current.done():
        await message.answer(
            "📢 <b>Общий сбор уже идёт.</b>\n"
            "Участники продолжают получать призывы в течение ближайшей минуты."
        )
        return

    task = asyncio.create_task(run_gather())
    gather_tasks[GROUP_ID] = task

    await message.answer(
        "🚨 <b>ОБЩИЙ СБОР ЗАПУЩЕН!</b>\n\n"
        "Всех известных боту участников начну повторно призывать каждые "
        f"{GATHER_INTERVAL_SECONDS} сек. в течение {GATHER_DURATION_SECONDS} сек."
    )


@dp.message(Command("stopsbor"))
async def stop_gather_command(message: Message):
    if message.chat.id != GROUP_ID:
        await message.answer("❌ Команду нужно запускать в группе.")
        return

    if not is_admin(message.from_user.id):
        await message.answer("❌ Только админы!")
        return

    task = gather_tasks.get(GROUP_ID)
    if not task or task.done():
        await message.answer("ℹ️ Сейчас общий сбор не идёт.")
        return

    task.cancel()
    gather_tasks.pop(GROUP_ID, None)
    await message.answer("🛑 <b>Общий сбор остановлен.</b>")


# Команда без слеша: «общий сбор» или «Общий сбор».
@dp.message(F.chat.id == GROUP_ID, F.text.func(lambda text: bool(text and text.strip().lower() == "общий сбор")))
async def gather_phrase(message: Message):
    await gather_command(message)


# =========================================================
# ЗАЩИТА ТЕМЫ НОВОСТИ
# =========================================================

@dp.message(F.chat.id == GROUP_ID)
async def protect_topic(message: Message):
    if message.message_thread_id == ANNOUNCE_TOPIC_ID:
        if not is_admin(message.from_user.id):
            try:
                await message.delete()

                await bot.send_message(
                    GROUP_ID,
                    f"❌ {escape(message.from_user.full_name)}, "
                    f"только админы могут писать здесь!",
                    reply_to_message_id=message.message_id,
                )
            except Exception:
                pass


# =========================================================
# /ALL
# =========================================================

@dp.message(Command("all"))
async def all_cmd(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Только админы!")
        return

    args = message.text.split(maxsplit=1)

    if len(args) < 2:
        await message.answer("❌ Использование: <code>/all текст</code>")
        return

    try:
        await bot.send_message(
            GROUP_ID,
            f"⚠️ <b>ВАЖНОЕ ОБЪЯВЛЕНИЕ</b>\n\n"
            f"{escape(args[1])}\n\n"
            f"@all",
            message_thread_id=ANNOUNCE_TOPIC_ID,
        )

        await message.answer("✅ Отправлено.")

    except Exception as e:
        await message.answer(f"❌ {escape(str(e))}")


# =========================================================
# /TOPIC_ID
# =========================================================

@dp.message(Command("topic_id"))
async def topic_id(message: Message):
    if message.chat.id == GROUP_ID and message.message_thread_id:
        await message.answer(
            f"ID: {message.message_thread_id}"
        )
    else:
        await message.answer("❌ Не в теме.")


# =========================================================
# /ADMINS
# =========================================================

@dp.message(Command("admins"))
async def admins_cmd(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return

    text = "👑 <b>Админы</b>\n\n"

    for i in sorted(get_admins()):
        text += f"• {escape(get_admin_display(i))}\n"

    await message.answer(text)


# =========================================================
# /SET_TOKEN
# =========================================================

@dp.message(Command("set_token"))
async def set_token(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return

    await message.answer(
        "🔐 Смена токена отключена в этой версии.\n"
        "Токен должен храниться только в Render → Environment → BOT_TOKEN.\n\n"
        "После изменения BOT_TOKEN в Render перезапусти сервис."
    )


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
    BotCommand(command="ping", description="📡 Пинг"),
    BotCommand(command="all", description="📢 Объявление"),
    BotCommand(command="кто", description="👤 Информация об участнике"),
    BotCommand(command="topic_id", description="🆔 ID темы"),
    BotCommand(command="sbor", description="📢 Общий сбор"),
    BotCommand(command="stopsbor", description="🛑 Остановить сбор"),
]

OWNER_COMMANDS = ADMIN_COMMANDS + [
    BotCommand(command="add", description="➕ Выдать админа/зама"),
    BotCommand(command="remove", description="➖ Убрать админа/зама"),
    BotCommand(command="add_admin", description="➕ Админ (алиас)"),
    BotCommand(command="remove_admin", description="➖ Админ (алиас)"),
    BotCommand(command="pending_admins", description="⏳ Ожидающие админы"),
    BotCommand(command="db_status", description="🗄️ Статус базы"),
    BotCommand(command="add_zam", description="👤 Добавить зама"),
    BotCommand(command="remove_zam", description="❌ Удалить зама"),
    BotCommand(command="admins", description="👑 Админы"),
    BotCommand(command="zam_stats", description="📊 Статистика замов"),
    BotCommand(command="withdraw", description="💰 Вывод"),
    BotCommand(command="logs", description="📜 Журнал"),
    BotCommand(command="clearlogs", description="🧹 Очистить журнал"),
    BotCommand(command="log_on", description="🔔 Логи вкл"),
    BotCommand(command="log_off", description="🔕 Логи выкл"),
    BotCommand(command="set_token", description="🔑 Информация о токене"),
]


async def set_command_scopes():
    # Обычным игрокам — только базовые команды.
    await bot.set_my_commands(
        DEFAULT_COMMANDS,
        scope=BotCommandScopeDefault(),
    )

    # Админам — админские команды.
    for admin_id in get_admins():
        if admin_id == SUPER_ADMIN:
            continue

        try:
            await bot.set_my_commands(
                ADMIN_COMMANDS,
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except Exception:
            pass

    # Владельцу — полный набор.
    try:
        await bot.set_my_commands(
            OWNER_COMMANDS,
            scope=BotCommandScopeChat(chat_id=SUPER_ADMIN),
        )
    except Exception:
        pass


# =========================================================
# ЗАПУСК
# =========================================================

async def main():
    print("🤖 Бот запускается...")

    if DATABASE_URL and psycopg2 is not None:
        if _db_init():
            print("✅ Постоянная база PostgreSQL подключена.")
        else:
            print("⚠️ PostgreSQL указан, но подключение не удалось. Проверь DATABASE_URL.")
    elif os.environ.get("RENDER"):
        print("⚠️ ВНИМАНИЕ: DATABASE_URL не задан. На Render локальная база не гарантирует сохранность после deploy/restart.")

    await init_telegram_user_client()
    await init_admins()
    await set_command_scopes()

    await bot.delete_webhook(drop_pending_updates=True)

    print("🤖 Бот запущен!")
    print("📌 Основная группа:", GROUP_LINK)

    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Бот остановлен.")
