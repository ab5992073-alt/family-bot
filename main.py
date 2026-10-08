import asyncio
import json
import os
import threading
from datetime import datetime
from html import escape
from pathlib import Path

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
    "Союз/Нейтраль",
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

DATA_FILE = "data.json"
LOG_FILE = "bot_activity.log"
BACKUP_DIR = Path("data_backups")
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

if not TOKEN:
    raise RuntimeError("Не найден BOT_TOKEN. Добавь переменную BOT_TOKEN в Render Environment.")

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

telegram_user_client = None
telegram_user_ready = False
_db_warned = False


# =========================================================
# УТИЛИТЫ
# =========================================================

def now_iso():
    return datetime.now().isoformat()


def normalize_username(value):
    if not value:
        return ""
    return str(value).strip().lstrip("@").lower()


def safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def unique_list(values):
    result = []
    seen = set()
    for value in values or []:
        try:
            key = int(value)
        except (TypeError, ValueError):
            key = str(value)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


# =========================================================
# POSTGRESQL
# =========================================================

def _db_connect():
    if psycopg2 is None:
        raise RuntimeError("Не установлен psycopg2-binary.")
    if not DATABASE_URL:
        raise RuntimeError("Не задан DATABASE_URL.")

    conninfo = DATABASE_URL
    if "sslmode=" not in conninfo.lower():
        conninfo += ("&" if "?" in conninfo else "?") + "sslmode=require"

    global _db_warned
    try:
        conn = psycopg2.connect(conninfo, connect_timeout=10)
        _db_warned = False
        return conn
    except Exception as e:
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
        with conn.cursor() as cur:
            cur.execute(
                "SELECT state_value FROM staff_grand_state WHERE state_key = %s",
                (key,),
            )
            row = cur.fetchone()
            return row[0] if row else None
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
    except Exception as e:
        print(f"⚠️ Не удалось прочитать {path}: {e}")
        return default


def _write_local_json(path, value):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"⚠️ Не удалось сохранить {path}: {e}")
        return False


def _has_real_data(value):
    if not isinstance(value, dict):
        return False
    keys = (
        "users", "applications", "admins", "zam_data", "zam_stats",
        "admin_usernames", "group_members", "pending_admin_usernames",
        "survey_history", "event_history",
    )
    return any(value.get(k) for k in keys)


def _merge_dicts_keep_db(db_value, local_value):
    """Безопасно объединяет старый data.json с PostgreSQL.
    Уже существующие значения PostgreSQL имеют приоритет.
    Отсутствующие записи из локального файла добавляются, а не удаляются.
    """
    if not isinstance(db_value, dict):
        return local_value if isinstance(local_value, dict) else {}
    if not isinstance(local_value, dict):
        return db_value

    merged = dict(db_value)
    dict_keys = {
        "users", "applications", "zam_data", "zam_stats", "admin_usernames",
        "group_members", "pending_admin_usernames", "survey_history",
    }

    for key in dict_keys:
        db_part = merged.get(key)
        local_part = local_value.get(key)
        if isinstance(db_part, dict) and isinstance(local_part, dict):
            copy_part = dict(db_part)
            for item_key, item_value in local_part.items():
                if item_key not in copy_part:
                    copy_part[item_key] = item_value
            merged[key] = copy_part
        elif not db_part and isinstance(local_part, dict):
            merged[key] = local_part

    for key, value in local_value.items():
        if key not in merged or merged.get(key) in (None, {}, [], ""):
            merged[key] = value

    if isinstance(db_value.get("admins"), list) or isinstance(local_value.get("admins"), list):
        merged["admins"] = unique_list(
            (db_value.get("admins") or []) + (local_value.get("admins") or [])
        )

    return merged


def load_data():
    local = _read_local_json(DATA_FILE, None)

    if DATABASE_URL and psycopg2 is not None:
        if not _db_init():
            raise RuntimeError("PostgreSQL недоступен. Бот не запускается, чтобы не потерять данные.")

        existing = _db_get("data")
        if isinstance(existing, dict) and isinstance(local, dict):
            merged = _merge_dicts_keep_db(existing, local)
            if merged != existing:
                print("🔄 PostgreSQL + локальный data.json объединены без удаления существующих записей.")
                _db_set("data", merged)
            return merged
        if isinstance(existing, dict):
            return existing
        if isinstance(local, dict):
            print("🔄 Первый импорт локального data.json в PostgreSQL.")
            if not _db_set("data", local):
                raise RuntimeError("Не удалось импортировать data.json в PostgreSQL.")
            return local
        return {}

    if isinstance(local, dict):
        return local

    raise RuntimeError("DATABASE_URL не задан и data.json отсутствует. Запуск остановлен ради сохранности данных.")


def save_data():
    _write_local_json(DATA_FILE, data)
    if DATABASE_URL and psycopg2 is not None:
        if not _db_set("data", data):
            print("⚠️ Данные сохранены локально, но PostgreSQL не принял запись.")


def load_logs():
    if DATABASE_URL and psycopg2 is not None:
        logs = _db_get("logs")
        if isinstance(logs, list):
            return [str(x) for x in logs]

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
    # Ограничиваем журнал, чтобы JSONB не разрастался бесконечно.
    lines = lines[-5000:]
    save_logs(lines)


def create_backup(reason="manual"):
    """Создаёт локальный и PostgreSQL backup без изменения основной базы."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    path = BACKUP_DIR / f"data_backup_{stamp}_{reason}.json"
    ok_local = _write_local_json(path, data)

    key = f"backup_{stamp}_{reason}"
    ok_db = True
    if DATABASE_URL and psycopg2 is not None:
        ok_db = _db_set(key, data)

    data["last_backup_at"] = now_iso()
    save_data()
    return ok_local and ok_db, str(path)


# =========================================================
# ЗАГРУЗКА И МИГРАЦИЯ
# =========================================================

data = load_data()
data_global = data


def ensure_data_structure():
    original_snapshot = json.loads(json.dumps(data, ensure_ascii=False))
    changed = False
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
        "survey_history": {},
        "event_history": [],
        "last_backup_at": None,
    }

    for key, default in defaults.items():
        if key not in data:
            data[key] = default
            changed = True

    for key in ("users", "applications", "zam_data", "zam_stats", "admin_usernames",
                "pending_admin_usernames", "group_members", "survey_history"):
        if not isinstance(data.get(key), dict):
            data[key] = {}
            changed = True

    if not isinstance(data.get("event_history"), list):
        data["event_history"] = []
        changed = True

    if not isinstance(data.get("admins"), list):
        data["admins"] = []
        changed = True

    old_admins = list(data["admins"])
    data["admins"] = unique_list(data["admins"] + list(ADMIN_IDS) + [SUPER_ADMIN])
    if data["admins"] != old_admins:
        changed = True

    # Миграция старых полей анкет без удаления данных.
    for uid, user in data["users"].items():
        if not isinstance(user, dict):
            continue
        user.setdefault("nickname", "—")
        user.setdefault("tag", "—")
        user.setdefault("rank_fam", "—")
        user.setdefault("organization", "—")
        if user.get("organization") == "Нету":
            user["organization"] = "Не в организации"
            changed = True
        if user.get("organization") == "Не в организации":
            if user.get("rank_org") != "/":
                user["rank_org"] = "/"
                changed = True
        else:
            user.setdefault("rank_org", "—")
        user.setdefault("inviter", "—")

    # Миграция замов.
    for nick, info in list(data["zam_data"].items()):
        if not isinstance(info, dict):
            data["zam_data"][nick] = {"tg_user_id": None, "tg_username": None}
            changed = True
            continue
        if "tg_user_id" not in info:
            info["tg_user_id"] = None
            changed = True
        if "tg_username" not in info:
            info["tg_username"] = None
            changed = True
        data["zam_stats"].setdefault(nick, {"count": 0, "withdrawn": 0, "history": []})

    # Старые данные о замах из предыдущей версии.
    initial_zams = [
        "Vusal_Cantrell", "_Sinax_Agressor_", "K1LLER", "Milena_Guenot",
        "Meglenes_Stemmust", "Sergey_Darknes", "Gleb_Maestro", "Ganka_Gankovich",
        "Gosha_Pinkman", "Nikita_Pandemic", "Egor_Vendetta", "Victoria_Sergeevna",
    ]
    if not data.get("initial_zams_installed", False):
        for nick in initial_zams:
            if nick not in data["zam_data"]:
                data["zam_data"][nick] = {"tg_user_id": None, "tg_username": None}
                data["zam_stats"][nick] = {"count": 0, "withdrawn": 0, "history": []}
                changed = True
        data["initial_zams_installed"] = True
        changed = True

    if changed:
        # Резервная копия исходного состояния ДО применения миграции.
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        _write_local_json(BACKUP_DIR / f"pre_update_{stamp}.json", original_snapshot)
        if DATABASE_URL and psycopg2 is not None:
            _db_set(f"pre_update_{stamp}", original_snapshot)
        save_data()


ensure_data_structure()


# =========================================================
# АДМИНЫ / ЗАМЫ
# =========================================================

def get_admins():
    return set(int(x) for x in data.get("admins", []) if safe_int(x) is not None)


def is_admin(user_id):
    return user_id in get_admins()


def is_super_admin(user_id):
    return user_id == SUPER_ADMIN


def save_admins(admins):
    data["admins"] = unique_list(list(admins) + [SUPER_ADMIN])
    save_data()


def get_admin_display(admin_id):
    info = data.get("admin_usernames", {}).get(str(admin_id), {})
    if info.get("username"):
        return f"@{info['username']}"
    if info.get("full_name"):
        return info["full_name"]
    return str(admin_id)


def get_zam_nicknames():
    return list(data.get("zam_data", {}).keys())


def add_zam_nick(game_nick, tg_user_id=None, tg_username=None):
    game_nick = game_nick.strip()
    if not game_nick:
        return False, "Пустой ник."
    if game_nick in data["zam_data"]:
        return False, "Такой зам уже существует."

    data["zam_data"][game_nick] = {
        "tg_user_id": tg_user_id,
        "tg_username": tg_username,
        "created_at": now_iso(),
    }
    data["zam_stats"].setdefault(game_nick, {"count": 0, "withdrawn": 0, "history": []})
    save_data()
    return True, "Зам добавлен."


def remove_zam_nick(game_nick):
    if game_nick not in data["zam_data"]:
        return False
    del data["zam_data"][game_nick]
    # Старую статистику сохраняем для истории, но активный список исчезает.
    save_data()
    return True


def count_zam_answers(game_nick):
    return sum(
        1 for user in data.get("users", {}).values()
        if str(user.get("inviter", "")).strip() == game_nick
    )


def get_all_zam_counts():
    result = []
    for nick in get_zam_nicknames():
        result.append((nick, count_zam_answers(nick)))
    result.sort(key=lambda x: (-x[1], x[0].lower()))
    return result


def find_user_id_by_username(username):
    wanted = normalize_username(username)
    if not wanted:
        return None

    for uid, info in data.get("group_members", {}).items():
        if normalize_username(info.get("username")) == wanted:
            return safe_int(uid)

    for uid, info in data.get("admin_usernames", {}).items():
        if normalize_username(info.get("username")) == wanted:
            return safe_int(uid)

    for nick, info in data.get("zam_data", {}).items():
        if normalize_username(info.get("tg_username")) == wanted:
            return safe_int(info.get("tg_user_id"))

    for uid, user in data.get("users", {}).items():
        if normalize_username(user.get("tag")) == wanted:
            return safe_int(uid)

    return None


# =========================================================
# TELETHON — ЛИЧНЫЕ ДИАЛОГИ ВЛАДЕЛЬЦА
# =========================================================

async def init_telegram_user_client():
    global telegram_user_client, telegram_user_ready

    if TelegramClient is None:
        print("⚠️ Telethon не установлен.")
        return False
    if not (TG_API_ID and TG_API_HASH and TG_SESSION_STRING):
        print("⚠️ TG_API_ID/TG_API_HASH/TG_SESSION_STRING не настроены.")
        return False

    try:
        telegram_user_client = TelegramClient(StringSession(TG_SESSION_STRING), TG_API_ID, TG_API_HASH)
        await telegram_user_client.connect()
        if not await telegram_user_client.is_user_authorized():
            print("⚠️ TG_SESSION_STRING не авторизован.")
            await telegram_user_client.disconnect()
            telegram_user_client = None
            return False
        me = await telegram_user_client.get_me()
        print(f"✅ Telegram user-session: {getattr(me, 'username', None) or me.id}")
        telegram_user_ready = True
        return True
    except Exception as e:
        print(f"⚠️ Не удалось подключить Telegram user-session: {e}")
        telegram_user_client = None
        telegram_user_ready = False
        return False


def telegram_user_is_ready():
    return telegram_user_client is not None and telegram_user_ready


async def get_owner_dialog_users(limit=200):
    if not telegram_user_is_ready():
        return []

    result = []
    try:
        async for dialog in telegram_user_client.iter_dialogs(limit=limit):
            entity = dialog.entity
            if TgUser is None or not isinstance(entity, TgUser):
                continue
            if getattr(entity, "self", False) or getattr(entity, "bot", False):
                continue

            first = getattr(entity, "first_name", None) or ""
            last = getattr(entity, "last_name", None) or ""
            full_name = f"{first} {last}".strip() or "Без имени"
            result.append({
                "id": int(entity.id),
                "name": full_name,
                "username": getattr(entity, "username", None),
            })
    except Exception as e:
        print(f"⚠️ Ошибка чтения диалогов владельца: {e}")

    return result


def owner_dialog_short_label(user):
    name = user.get("name") or "Без имени"
    username = user.get("username")
    return f"{name} (@{username})" if username else name


def owner_dialog_page_keyboard(users, page=0, page_size=15, prefix="select_admin"):
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


async def init_admins():
    changed = False
    for admin_id in get_admins():
        try:
            chat = await bot.get_chat(admin_id)
            info = {
                "username": chat.username,
                "full_name": chat.full_name or str(admin_id),
            }
            if data["admin_usernames"].get(str(admin_id)) != info:
                data["admin_usernames"][str(admin_id)] = info
                changed = True
        except Exception:
            data["admin_usernames"].setdefault(str(admin_id), {"full_name": str(admin_id)})
    if changed:
        save_data()


# =========================================================
# ЛОГИ И УВЕДОМЛЕНИЯ
# =========================================================

async def owner_notify(text):
    try:
        await bot.send_message(SUPER_ADMIN, text)
        return True
    except Exception as e:
        print(f"⚠️ Не удалось отправить ЛС владельцу: {e}")
        return False


async def log_action(user_id, action, details="", notify=True):
    try:
        chat = await bot.get_chat(user_id)
        username = f"@{chat.username}" if chat.username else (chat.full_name or str(user_id))
    except Exception:
        username = str(user_id)

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    append_log_line(f"[{ts}] {username} -> {action} {details}\n")

    if notify and data.get("log_notify_enabled"):
        await owner_notify(
            f"👤 <b>{escape(username)}</b> → {escape(action)} {escape(details)}\n🕐 {ts}"
        )


def add_event(event_type, user_id=None, name=None, details=""):
    event = {
        "type": event_type,
        "user_id": user_id,
        "name": name,
        "details": details,
        "created": now_iso(),
    }
    data.setdefault("event_history", []).append(event)
    data["event_history"] = data["event_history"][-2000:]
    save_data()


# =========================================================
# УЧАСТНИКИ ГРУППЫ — ДОБАВЛЕНИЕ / КИК / ЛС ВЛАДЕЛЬЦУ
# =========================================================

async def bind_pending_admin_for_user(user):
    if not user or user.is_bot or not user.username:
        return False
    wanted = normalize_username(user.username)
    pending = data.setdefault("pending_admin_usernames", {})
    if wanted not in pending:
        return False
    if user.id in get_admins():
        pending.pop(wanted, None)
        save_data()
        return False

    admins = get_admins()
    admins.add(user.id)
    data["admins"] = unique_list(list(admins) + [SUPER_ADMIN])
    data.setdefault("admin_usernames", {})[str(user.id)] = {
        "username": user.username,
        "full_name": user.full_name or str(user.id),
    }
    pending.pop(wanted, None)
    save_data()
    try:
        await set_command_scopes()
    except Exception:
        pass
    try:
        await bot.send_message(user.id, "👑 Вы назначены администратором бота!\nИспользуйте /start для панели.")
    except Exception:
        pass
    return True


class GroupMemberTrackerMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data_context):
        if isinstance(event, Message):
            try:
                user = event.from_user
                if user and not user.is_bot:
                    await bind_pending_admin_for_user(user)
                    if event.chat.id == GROUP_ID:
                        data.setdefault("group_members", {})[str(user.id)] = {
                            "id": user.id,
                            "username": user.username,
                            "full_name": user.full_name or str(user.id),
                            "last_seen": now_iso(),
                        }
                        save_data()
            except Exception as e:
                print(f"⚠️ Ошибка обработки участника: {e}")
        return await handler(event, data_context)


dp.message.outer_middleware(GroupMemberTrackerMiddleware())


@dp.chat_member()
async def group_member_update(event: ChatMemberUpdated):
    if event.chat.id != GROUP_ID:
        return

    user = event.new_chat_member.user
    if not user or user.is_bot:
        return

    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status
    joined_statuses = {"member", "administrator", "creator", "restricted"}
    left_statuses = {"left", "kicked"}

    was_member = old_status in joined_statuses
    is_member = new_status in joined_statuses

    uid = str(user.id)
    member_info = {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name or str(user.id),
        "last_seen": now_iso(),
    }

    if not was_member and is_member:
        data.setdefault("group_members", {})[uid] = member_info
        save_data()
        add_event("joined_group", user.id, user.full_name, f"@{user.username}" if user.username else "")
        await owner_notify(
            "🟢 <b>Человек добавлен/вошёл в группу</b>\n\n"
            f"👤 {escape(user.full_name or 'Без имени')}\n"
            f"🔗 {('@' + escape(user.username)) if user.username else 'без username'}\n"
            f"🆔 <code>{user.id}</code>"
        )

    elif was_member and not is_member:
        # Данные НЕ удаляем: история анкеты должна сохраниться.
        if uid in data.get("group_members", {}):
            data["group_members"][uid]["left_at"] = now_iso()
            data["group_members"][uid]["left_status"] = new_status
        else:
            data.setdefault("group_members", {})[uid] = member_info
        save_data()
        add_event("kicked_from_group" if new_status == "kicked" else "left_group", user.id, user.full_name, new_status)
        action = "🔴 <b>Человек кикнут из группы</b>" if new_status == "kicked" else "🔴 <b>Человек вышел из группы</b>"
        await owner_notify(
            f"{action}\n\n"
            f"👤 {escape(user.full_name or 'Без имени')}\n"
            f"🔗 {('@' + escape(user.username)) if user.username else 'без username'}\n"
            f"🆔 <code>{user.id}</code>"
        )


# =========================================================
# КЛАВИАТУРЫ
# =========================================================

def main_keyboard(has_survey=False):
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="📝 Заполнить анкету"))
    if has_survey:
        b.row(KeyboardButton(text="🔄 Перезаполнить анкету"))
    b.row(KeyboardButton(text="👤 Мой профиль"))
    return b.as_markup(resize_keyboard=True)


def admin_keyboard(user_id, has_survey=False):
    b = ReplyKeyboardBuilder()
    b.row(KeyboardButton(text="📋 Управление заявками"), KeyboardButton(text="⏳ Активные заявки"))
    b.row(KeyboardButton(text="👥 Список участников"), KeyboardButton(text="🟢 Статус бота"))
    b.row(KeyboardButton(text="🛠 Админка"))
    if has_survey:
        b.row(KeyboardButton(text="🔄 Перезаполнить анкету"))
    if is_super_admin(user_id):
        b.row(KeyboardButton(text="👑 Замы"), KeyboardButton(text="📜 Журнал действий"))
    return b.as_markup(resize_keyboard=True)


def admin_panel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить админа", callback_data="adm:add")],
        [InlineKeyboardButton(text="➖ Удалить админа", callback_data="adm:remove")],
        [InlineKeyboardButton(text="👑 Список админов", callback_data="adm:list")],
    ])


def survey_exists(user_id):
    return str(user_id) in data.get("users", {})


def survey_already_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Перезаполнить", callback_data="survey:refill")],
        [InlineKeyboardButton(text="➡️ Пропустить", callback_data="survey:skip")],
    ])


# =========================================================
# МЕНЮ
# =========================================================

@dp.message(CommandStart())
async def start_command(message: Message):
    await log_action(message.from_user.id, "start", "запустил бота")
    await show_main_menu(message)


async def show_main_menu(message: Message):
    user_id = message.from_user.id
    has_survey = survey_exists(user_id)
    if is_admin(user_id):
        await message.answer(
            f"🛡️ <b>Панель управления</b>\nДобро пожаловать в <b>{BOT_NAME}</b>.",
            reply_markup=admin_keyboard(user_id, has_survey),
        )
    else:
        await message.answer(
            f"👋 <b>Добро пожаловать в {BOT_NAME}!</b>\nЗаполните анкету для вступления в семью.",
            reply_markup=main_keyboard(has_survey),
        )


# =========================================================
# АНКЕТА
# =========================================================

user_surveys = {}
gather_tasks = {}
GATHER_DURATION_SECONDS = 90
GATHER_INTERVAL_SECONDS = 20
GATHER_CHUNK_SIZE = 25


async def start_survey(message: Message, preserve_old=True):
    uid = message.from_user.id
    user_surveys[uid] = {"step": 0, "answers": {}, "preserve_old": preserve_old}
    await log_action(uid, "анкета", "начал")
    await message.answer(
        "📋 <b>Заполнение анкеты</b>\n\n1️⃣ Ваш Nickname в игре?",
        reply_markup=ReplyKeyboardRemove(),
    )


async def begin_survey_or_offer_refill(message: Message):
    if survey_exists(message.from_user.id):
        await message.answer(
            "ℹ️ <b>У вас уже есть заполненная анкета.</b>\n\nВыберите действие:",
            reply_markup=survey_already_keyboard(),
        )
        return
    await start_survey(message, preserve_old=False)


@dp.message(F.text == "📝 Заполнить анкету")
async def survey_button(message: Message):
    await begin_survey_or_offer_refill(message)


@dp.callback_query(F.data == "survey:refill")
async def survey_refill_cb(cb: CallbackQuery):
    await cb.answer()
    await start_survey(cb.message, preserve_old=True)


@dp.callback_query(F.data == "survey:skip")
async def survey_skip_cb(cb: CallbackQuery):
    await cb.answer()
    await cb.message.answer("👍 Хорошо, оставляем текущую анкету.")
    await show_main_menu(cb.message)


@dp.message(F.text == "🔄 Перезаполнить анкету")
async def reset_survey(message: Message):
    if not survey_exists(message.from_user.id):
        await message.answer("❌ У вас нет анкеты.")
        return
    await start_survey(message, preserve_old=True)


@dp.message(lambda m: m.from_user.id in user_surveys)
async def survey_handler(message: Message):
    uid = message.from_user.id
    s = user_surveys[uid]
    step = s["step"]

    if not message.text:
        await message.answer("❌ Введите текст.")
        return

    if step == 0:
        nickname = message.text.strip()
        if not nickname:
            await message.answer("❌ Nickname не может быть пустым.")
            return
        s["answers"]["nickname"] = nickname
        u = message.from_user
        s["answers"]["tag"] = f"@{u.username}" if u.username else str(u.id)
        s["step"] = 1
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=r, callback_data=f"rank_{r}")] for r in RANK_LIST
        ])
        await message.answer("👤 Ваш ранг в фаме:", reply_markup=kb)

    elif step == 3:
        # Старые сценарии без организации-кнопки оставляем рабочими.
        s["answers"]["rank_org"] = message.text.strip()
        await ask_inviter(message, uid)


async def ask_inviter(message: Message, uid: int):
    user_surveys[uid]["step"] = 4
    zams = get_zam_nicknames()
    if not zams:
        await message.answer("⚠️ Сейчас замов нет. Обратитесь к администрации.")
        user_surveys.pop(uid, None)
        await show_main_menu(message)
        return

    rows = []
    for z in zams:
        rows.append([InlineKeyboardButton(text=z, callback_data=f"zam_{z}")])
    await message.answer("👤 Кто вас пригласил?", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.callback_query(F.data.startswith("rank_"))
async def rank_selected(cb: CallbackQuery):
    uid = cb.from_user.id
    if uid not in user_surveys:
        await cb.answer("❌ Анкета не найдена.")
        return
    rank = cb.data[5:]
    if rank not in RANK_LIST:
        await cb.answer("❌ Недопустимый ранг.", show_alert=True)
        return
    user_surveys[uid]["answers"]["rank_fam"] = rank
    user_surveys[uid]["step"] = 2
    await cb.answer(f"✅ {rank}")
    rows = [[InlineKeyboardButton(text=o, callback_data=f"org_{o}")] for o in ORG_LIST]
    await cb.message.answer("🏢 Ваша организация:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.callback_query(F.data.startswith("org_"))
async def org_selected(cb: CallbackQuery):
    uid = cb.from_user.id
    if uid not in user_surveys:
        await cb.answer("❌ Анкета не найдена.")
        return
    org = cb.data[4:]
    if org not in ORG_LIST:
        await cb.answer("❌ Недопустимая организация.", show_alert=True)
        return

    user_surveys[uid]["answers"]["organization"] = org
    await cb.answer(f"✅ {org}")

    if org == "Не в организации":
        user_surveys[uid]["answers"]["rank_org"] = "/"
        await ask_inviter(cb.message, uid)
    else:
        user_surveys[uid]["step"] = 3
        await cb.message.answer("📌 Ваш ранг в организации?")


@dp.callback_query(F.data.startswith("zam_"))
async def zam_selected(cb: CallbackQuery):
    uid = cb.from_user.id
    if uid not in user_surveys:
        await cb.answer("❌ Анкета не найдена.")
        return
    zam = cb.data[4:]
    if zam not in data["zam_data"]:
        await cb.answer("❌ Этот зам больше не существует.", show_alert=True)
        return
    user_surveys[uid]["answers"]["inviter"] = zam
    await cb.answer(f"✅ {zam}")
    await finish_survey(cb.message, uid)


async def finish_survey(message, uid):
    s = user_surveys.pop(uid, None)
    if not s:
        return
    a = s["answers"]
    org = a.get("organization", "—")
    rank_org = "/" if org == "Не в организации" else a.get("rank_org", "—")

    user_data = {
        "nickname": a.get("nickname", "—"),
        "tag": a.get("tag", "—"),
        "rank_fam": a.get("rank_fam", "—"),
        "organization": org,
        "rank_org": rank_org,
        "inviter": a.get("inviter", "—"),
        "updated_at": now_iso(),
    }

    uid_key = str(uid)
    old_user = data["users"].get(uid_key)
    if old_user:
        data.setdefault("survey_history", {}).setdefault(uid_key, []).append({
            "changed_at": now_iso(),
            "previous": old_user,
            "reason": "refill",
        })
        data["survey_history"][uid_key] = data["survey_history"][uid_key][-50:]

        for app in data["applications"].values():
            if str(app.get("user_id")) == uid_key and app.get("status") == "pending":
                app["status"] = "cancelled"
                app.setdefault("history", []).append({
                    "action": "cancelled_by_refill",
                    "created": now_iso(),
                    "by": uid,
                })

    data["users"][uid_key] = user_data
    app_id = f"app_{uid}_{int(datetime.now().timestamp())}"
    data["applications"][app_id] = {
        "user_id": uid,
        "data": user_data.copy(),
        "status": "pending",
        "created": now_iso(),
        "history": [],
    }
    save_data()

    await message.answer("✅ <b>Анкета заполнена!</b>", reply_markup=main_keyboard(True) if not is_admin(uid) else admin_keyboard(uid, True))

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", callback_data=f"accept:{app_id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{app_id}")],
    ])
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
            await bot.send_message(admin, text, reply_markup=kb)
        except Exception:
            pass


# =========================================================
# ПРОФИЛЬ / КТО / ПОИСК
# =========================================================

@dp.message(F.text == "👤 Мой профиль")
async def my_profile(message: Message):
    uid = str(message.from_user.id)
    u = data["users"].get(uid)
    if not u:
        await message.answer("ℹ️ Вы ещё не заполнили анкету.")
        return
    await message.answer(format_user_card(u, uid))


def format_user_card(u, uid=None):
    return (
        "👤 <b>Профиль</b>\n"
        f"Nickname: {escape(u.get('nickname', '—'))}\n"
        f"Тег: {escape(u.get('tag', '—'))}\n"
        f"Ранг: {escape(u.get('rank_fam', '—'))}\n"
        f"Орг: {escape(u.get('organization', '—'))}\n"
        f"Ранг в орг: {escape(u.get('rank_org', '—'))}\n"
        f"Пригласил: {escape(u.get('inviter', '—'))}"
        + (f"\n🆔 ID: <code>{uid}</code>" if uid else "")
    )


@dp.message(Command("кто"))
@dp.message(Command("kto"))
async def who_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет прав!")
        return
    if not message.reply_to_message:
        await message.answer("❌ Ответьте на сообщение участника.")
        return
    uid = message.reply_to_message.from_user.id
    u = data["users"].get(str(uid))
    if not u:
        await message.answer("❌ У этого пользователя нет анкеты.")
        return
    await message.answer(format_user_card(u, str(uid)))


@dp.message(Command("поиск"))
async def search_user_cmd(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Только админы!")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Использование: <code>/поиск Nickname или @username</code>")
        return
    query = args[1].strip().lstrip("@").lower()
    found = []
    for uid, u in data.get("users", {}).items():
        hay = " ".join(str(u.get(k, "")) for k in ("nickname", "tag", "organization", "inviter")).lower()
        if query in hay or query == str(uid).lower():
            found.append((uid, u))
    for uid, info in data.get("group_members", {}).items():
        hay = f"{info.get('username','')} {info.get('full_name','')} {uid}".lower()
        if query in hay and str(uid) not in {x[0] for x in found}:
            found.append((uid, {
                "nickname": info.get("full_name", "—"),
                "tag": f"@{info.get('username')}" if info.get('username') else "—",
                "rank_fam": "—",
                "organization": "—",
                "rank_org": "—",
                "inviter": "—",
            }))
    if not found:
        await message.answer("🔎 Ничего не найдено.")
        return
    text = "🔎 <b>Результаты поиска</b>\n\n"
    for uid, u in found[:20]:
        text += f"<b>{escape(u.get('nickname','—'))}</b> — {escape(u.get('tag','—'))}\nID: <code>{uid}</code>\n\n"
    await message.answer(text)


@dp.message(Command("history"))
async def history_cmd(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Только админы!")
        return
    target = None
    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        target = args[1].strip().lstrip("@")
    elif message.reply_to_message:
        target = str(message.reply_to_message.from_user.id)
    if not target:
        await message.answer("❌ Использование: <code>/history ID</code> или ответом на сообщение.")
        return

    uid = target if target.isdigit() else None
    if uid is None:
        uid = str(find_user_id_by_username(target) or "")
    history = data.get("survey_history", {}).get(str(uid), [])
    if not history:
        await message.answer("📭 Истории перезаполнений нет.")
        return
    text = f"📜 <b>История анкеты {escape(str(uid))}</b>\n\n"
    for item in history[-10:][::-1]:
        prev = item.get("previous", {})
        text += f"🕐 {escape(item.get('changed_at','—'))}\n"
        text += f"Nickname: {escape(prev.get('nickname','—'))}\n"
        text += f"Ранг: {escape(prev.get('rank_fam','—'))}\n"
        text += f"Орг: {escape(prev.get('organization','—'))}\n"
        text += f"Зам: {escape(prev.get('inviter','—'))}\n\n"
    await message.answer(text[:4000])


# =========================================================
# ЗАЯВКИ
# =========================================================

def application_keyboard(app_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Принять", callback_data=f"accept:{app_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{app_id}"),
        ]
    ])


def application_text(app, idx=None):
    u = app.get("data", {})
    status = app.get("status", "pending")
    status_text = {
        "pending": "⏳ Ожидает решения",
        "accepted": "✅ Принята",
        "rejected": "❌ Отклонена",
        "cancelled": "🚫 Отменена",
    }.get(status, status)
    prefix = f"<b>Заявка #{idx}</b>" if idx is not None else "<b>Заявка</b>"
    return (
        f"{prefix}\nСтатус: <b>{status_text}</b>\n\n"
        f"Nickname: {escape(u.get('nickname','—'))}\n"
        f"Тег: {escape(u.get('tag','—'))}\n"
        f"Ранг: {escape(u.get('rank_fam','—'))}\n"
        f"Орг: {escape(u.get('organization','—'))}\n"
        f"Ранг в орг: {escape(u.get('rank_org','—'))}\n"
        f"Пригласил: {escape(u.get('inviter','—'))}"
    )


async def add_user_to_group(user_id):
    try:
        await bot.send_message(user_id, f"🔗 <b>Вы приняты в семью!</b>\n\nВступите в группу:\n{GROUP_LINK}")
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
        await bot.set_chat_member_custom_title(chat_id=GROUP_ID, user_id=user_id, custom_title=nickname)
        return True
    except Exception:
        return False


async def change_application_verdict(app_id, new_status, admin_id):
    app = data["applications"].get(app_id)
    if not app:
        return False, "❌ Заявка не найдена."
    old_status = app.get("status", "pending")
    if old_status == new_status:
        return False, "ℹ️ Этот вердикт уже установлен."

    app["status"] = new_status
    app["last_changed_by"] = admin_id
    app["last_changed_at"] = now_iso()
    app.setdefault("history", []).append({
        "action": new_status,
        "previous_status": old_status,
        "by": admin_id,
        "created": now_iso(),
    })
    save_data()

    user_id = safe_int(app.get("user_id"))
    nickname = app.get("data", {}).get("nickname", "Участник")

    if new_status == "accepted":
        await add_user_to_group(user_id)
        await set_user_nickname(user_id, nickname)
        try:
            await bot.send_message(user_id, "✅ Ваша заявка принята администрацией!")
        except Exception:
            pass
    elif new_status == "rejected":
        await remove_user_from_group(user_id)
        try:
            await bot.send_message(user_id, "❌ Ваша заявка отклонена администрацией.")
        except Exception:
            pass

    await log_action(admin_id, "изменил вердикт заявки", f"{app_id}: {old_status} → {new_status}")
    await owner_notify(
        f"📋 <b>Изменён вердикт заявки</b>\n"
        f"👤 {escape(nickname)}\n"
        f"📝 {escape(old_status)} → <b>{escape(new_status)}</b>\n"
        f"🛡 Админ: <code>{admin_id}</code>"
    )
    return True, "✅ Готово."


@dp.callback_query(F.data.startswith("accept:"))
async def accept_app(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет прав!", show_alert=True)
        return
    app_id = cb.data.split(":", 1)[1]
    ok, text = await change_application_verdict(app_id, "accepted", cb.from_user.id)
    await cb.answer("✅ Принят" if ok else text, show_alert=not ok)
    if ok:
        try:
            await cb.message.edit_text(application_text(data["applications"][app_id]), reply_markup=application_keyboard(app_id))
        except Exception:
            pass


@dp.callback_query(F.data.startswith("reject:"))
async def reject_app(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет прав!", show_alert=True)
        return
    app_id = cb.data.split(":", 1)[1]
    ok, text = await change_application_verdict(app_id, "rejected", cb.from_user.id)
    await cb.answer("❌ Отклонён" if ok else text, show_alert=not ok)
    if ok:
        try:
            await cb.message.edit_text(application_text(data["applications"][app_id]), reply_markup=application_keyboard(app_id))
        except Exception:
            pass


@dp.message(F.text == "📋 Управление заявками")
async def all_apps(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌")
        return
    if not data["applications"]:
        await message.answer("📭 Заявок нет.")
        return
    for idx, (app_id, app) in enumerate(data["applications"].items(), 1):
        status = app.get("status", "pending")
        kb = application_keyboard(app_id) if status in {"pending", "accepted", "rejected"} else None
        await message.answer(application_text(app, idx), reply_markup=kb)


@dp.message(F.text == "⏳ Активные заявки")
async def active_apps(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌")
        return
    pend = [(k, v) for k, v in data["applications"].items() if v.get("status") == "pending"]
    if not pend:
        await message.answer("📭 Нет активных.")
        return
    for idx, (app_id, app) in enumerate(pend, 1):
        await message.answer(application_text(app, idx), reply_markup=application_keyboard(app_id))


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
    per = 5
    total = len(users)
    pages = max(1, (total + per - 1) // per)
    if page < 0 or page >= pages:
        return
    start = page * per
    end = min(start + per, total)
    text = "👥 <b>Список участников</b>\n\n"
    for i in range(start, end):
        uid, u = users[i]
        text += (
            f"<b>{i + 1}.</b> {escape(u.get('nickname','—'))} — {escape(u.get('tag', uid))}\n"
            f"   Ранг: {escape(u.get('rank_fam','—'))} | Орг: {escape(u.get('organization','—'))}\n"
            f"   Пригласил: {escape(u.get('inviter','—'))}\n\n"
        )
    text += f"Стр. {page + 1} из {pages}"
    rows = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"up_{page-1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"up_{page+1}"))
    if nav:
        rows.append(nav)
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows) if rows else None)


@dp.callback_query(F.data.startswith("up_"))
async def up_cb(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌")
        return
    await send_users_page(cb.message, list(data["users"].items()), int(cb.data.split("_")[1]))
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
    pend = sum(1 for a in data["applications"].values() if a.get("status") == "pending")
    rej = sum(1 for a in data["applications"].values() if a.get("status") == "rejected")
    acc = sum(1 for a in data["applications"].values() if a.get("status") == "accepted")
    admins = "\n".join(escape(get_admin_display(i)) for i in sorted(get_admins()))
    await message.answer(
        f"🟢 <b>Бот работает!</b>\n\n👥 Всего анкет: {total}\n📩 Ожидают: {pend}\n"
        f"✅ Принято: {acc}\n❌ Отклонено: {rej}\n\n👑 <b>Админы:</b>\n{admins}"
    )


# =========================================================
# АДМИНКА
# =========================================================

async def assign_admin(user_id, username=None, full_name=None, by=None):
    if user_id == SUPER_ADMIN:
        return False, "Это владелец — права уже есть."
    admins = get_admins()
    if user_id in admins:
        return False, "Этот пользователь уже администратор."
    admins.add(user_id)
    save_admins(admins)
    data["admin_usernames"][str(user_id)] = {
        "username": username,
        "full_name": full_name or str(user_id),
    }
    if username:
        data["pending_admin_usernames"].pop(normalize_username(username), None)
    save_data()
    await set_command_scopes()
    if by:
        await log_action(by, "добавил администратора", f"{full_name or ''} / @{username or ''}")
    try:
        await bot.send_message(user_id, "👑 Вы назначены администратором бота!\nИспользуйте /start для панели.")
    except Exception:
        pass
    return True, "Администратор назначен."


async def show_admin_selector(message, mode="add", page=0):
    users = await get_owner_dialog_users()
    if not users:
        if not telegram_user_is_ready():
            await message.answer(
                "⚠️ Список личных диалогов пока недоступен.\n\n"
                "Для этого нужны TG_API_ID, TG_API_HASH и TG_SESSION_STRING в Render.\n"
                "Либо используй команду ответом на сообщение: <code>/add admin</code>."
            )
        else:
            await message.answer("📭 В личных диалогах не найдено подходящих пользователей.")
        return

    prefix = "select_admin" if mode == "add" else "select_remove_admin"
    await message.answer(
        "👑 <b>Выбери пользователя</b>\n"
        f"Действие: {'выдать админку' if mode == 'add' else 'забрать админку'}",
        reply_markup=owner_dialog_page_keyboard(users, page, prefix=prefix),
    )


@dp.message(F.text == "🛠 Админка")
async def admin_panel(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return
    await message.answer(
        "👑 <b>Управление администраторами</b>\n\n"
        "Можно выбрать человека из твоих личных Telegram-диалогов, даже если он никогда не пользовался ботом.",
        reply_markup=admin_panel_keyboard(),
    )


@dp.callback_query(F.data == "adm:add")
async def adm_add_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True)
        return
    await cb.answer()
    await show_admin_selector(cb.message, "add")


@dp.callback_query(F.data == "adm:remove")
async def adm_remove_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True)
        return
    admins = []
    for uid in sorted(get_admins()):
        if uid == SUPER_ADMIN:
            continue
        info = data["admin_usernames"].get(str(uid), {})
        admins.append({"id": uid, "name": info.get("full_name", str(uid)), "username": info.get("username")})
    if not admins:
        await cb.answer("Админов для удаления нет.", show_alert=True)
        return
    await cb.answer()
    await cb.message.answer(
        "➖ <b>Выбери админа:</b>",
        reply_markup=owner_dialog_page_keyboard(admins, 0, prefix="remove_known_admin"),
    )


@dp.callback_query(F.data == "adm:list")
async def adm_list_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True)
        return
    text = "👑 <b>Админы</b>\n\n"
    for i, uid in enumerate(sorted(get_admins()), 1):
        text += f"{i}. {escape(get_admin_display(uid))} — <code>{uid}</code>\n"
    await cb.message.answer(text)
    await cb.answer()


@dp.callback_query(F.data.startswith("select_admin_page:"))
async def select_admin_page_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌", show_alert=True)
        return
    page = int(cb.data.split(":", 1)[1])
    users = await get_owner_dialog_users()
    await cb.message.edit_reply_markup(reply_markup=owner_dialog_page_keyboard(users, page, prefix="select_admin"))
    await cb.answer()


@dp.callback_query(F.data.startswith("select_admin:"))
async def select_admin_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌", show_alert=True)
        return
    uid = int(cb.data.split(":", 1)[1])
    users = await get_owner_dialog_users()
    selected = next((x for x in users if x["id"] == uid), None)
    if not selected:
        await cb.answer("Пользователь не найден.", show_alert=True)
        return
    ok, result = await assign_admin(uid, selected.get("username"), selected.get("name"), cb.from_user.id)
    await cb.answer("✅ Готово" if ok else result, show_alert=not ok)
    await cb.message.answer(("✅ " if ok else "❌ ") + escape(result))


@dp.callback_query(F.data.startswith("select_remove_admin_page:"))
async def select_remove_admin_page_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌", show_alert=True)
        return
    page = int(cb.data.split(":", 1)[1])
    users = await get_owner_dialog_users()
    await cb.message.edit_reply_markup(reply_markup=owner_dialog_page_keyboard(users, page, prefix="select_remove_admin"))
    await cb.answer()


@dp.callback_query(F.data.startswith("select_remove_admin:"))
async def select_remove_admin_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌", show_alert=True)
        return
    uid = int(cb.data.split(":", 1)[1])
    if uid == SUPER_ADMIN:
        await cb.answer("Владельца удалить нельзя.", show_alert=True)
        return
    if uid not in get_admins():
        await cb.answer("Уже не админ.", show_alert=True)
        return
    display = get_admin_display(uid)
    admins = get_admins()
    admins.remove(uid)
    save_admins(admins)
    data["admin_usernames"].pop(str(uid), None)
    save_data()
    await set_command_scopes()
    await log_action(cb.from_user.id, "удалил администратора", display)
    await cb.answer("✅ Удалён")
    await cb.message.answer(f"✅ Админ <b>{escape(display)}</b> удалён.")


@dp.callback_query(F.data == "owner_select_cancel")
async def owner_select_cancel(cb: CallbackQuery):
    await cb.answer("Отменено")
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


@dp.message(Command("add"))
async def add_command(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 2:
        await message.answer("❌ Использование: <code>/add admin</code> или <code>/add zam @username Game_Nick</code>")
        return
    mode = args[1].lower()
    if mode == "admin":
        if message.reply_to_message and message.reply_to_message.from_user:
            u = message.reply_to_message.from_user
            ok, result = await assign_admin(u.id, u.username, u.full_name, message.from_user.id)
            await message.answer(("✅ " if ok else "❌ ") + escape(result))
            return
        if len(args) == 2:
            await show_admin_selector(message, "add")
            return
        value = args[2].strip()
        if value.isdigit():
            uid = int(value)
            ok, result = await assign_admin(uid, None, str(uid), message.from_user.id)
            await message.answer(("✅ " if ok else "❌ ") + escape(result))
            return
        uid = find_user_id_by_username(value)
        if uid:
            ok, result = await assign_admin(uid, value.lstrip("@"), value, message.from_user.id)
            await message.answer(("✅ " if ok else "❌ ") + escape(result))
            return
        pending = data["pending_admin_usernames"]
        pending[normalize_username(value)] = {"username": value.lstrip("@"), "added_by": message.from_user.id, "created": now_iso()}
        save_data()
        await message.answer(
            f"⏳ <b>@{escape(value.lstrip('@'))}</b> добавлен в ожидание.\n"
            "Если пользователь напишет боту или его сообщение попадёт боту, ID будет привязан автоматически."
        )
        return
    if mode == "zam":
        if len(args) < 3:
            await message.answer("❌ <code>/add zam @username Game_Nick</code>")
            return
        parts = args[2].split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("❌ <code>/add zam @username Game_Nick</code>")
            return
        await add_zam_by_username(message, parts[0], parts[1])
        return
    await message.answer("❌ Доступно: <code>admin</code> или <code>zam</code>.")


@dp.message(Command("remove"))
async def remove_command(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 2:
        await message.answer("❌ <code>/remove admin</code> или <code>/remove zam Game_Nick</code>")
        return
    mode = args[1].lower()
    if mode == "admin":
        if message.reply_to_message and message.reply_to_message.from_user:
            uid = message.reply_to_message.from_user.id
            if uid == SUPER_ADMIN:
                await message.answer("❌ Владельца удалить нельзя.")
                return
            if uid not in get_admins():
                await message.answer("❌ Это не админ.")
                return
            display = get_admin_display(uid)
            admins = get_admins(); admins.remove(uid); save_admins(admins)
            data["admin_usernames"].pop(str(uid), None); save_data(); await set_command_scopes()
            await message.answer(f"✅ Админ <b>{escape(display)}</b> удалён.")
            return
        if len(args) == 2:
            await show_admin_selector(message, "remove")
            return
        value = args[2].strip()
        uid = int(value) if value.isdigit() else find_user_id_by_username(value)
        if uid is None:
            await message.answer("❌ Админ не найден.")
            return
        if uid == SUPER_ADMIN:
            await message.answer("❌ Владельца удалить нельзя.")
            return
        if uid not in get_admins():
            await message.answer("❌ Это не админ.")
            return
        display = get_admin_display(uid)
        admins = get_admins(); admins.remove(uid); save_admins(admins)
        data["admin_usernames"].pop(str(uid), None); save_data(); await set_command_scopes()
        await message.answer(f"✅ Админ <b>{escape(display)}</b> удалён.")
        return
    if mode == "zam":
        if len(args) < 3:
            await message.answer("❌ <code>/remove zam Game_Nick</code>")
            return
        nick = args[2].strip()
        if remove_zam_nick(nick):
            await log_action(message.from_user.id, "удалил зама", nick)
            await message.answer(f"✅ Зам <b>{escape(nick)}</b> удалён.")
        else:
            await message.answer("❌ Такой зам не найден.")
        return
    await message.answer("❌ Доступно: <code>admin</code> или <code>zam</code>.")


@dp.message(Command("add_admin"))
async def add_admin_legacy(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return
    args = message.text.split(maxsplit=1)
    if len(args) == 1 and message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        ok, result = await assign_admin(u.id, u.username, u.full_name, message.from_user.id)
        await message.answer(("✅ " if ok else "❌ ") + escape(result))
        return
    if len(args) == 1:
        await show_admin_selector(message, "add")
        return
    value = args[1].strip()
    uid = int(value) if value.isdigit() else find_user_id_by_username(value)
    if uid:
        ok, result = await assign_admin(uid, value.lstrip("@"), value, message.from_user.id)
        await message.answer(("✅ " if ok else "❌ ") + escape(result))
    else:
        data["pending_admin_usernames"][normalize_username(value)] = {"username": value.lstrip("@"), "added_by": message.from_user.id, "created": now_iso()}
        save_data()
        await message.answer(f"⏳ @{escape(value.lstrip('@'))} добавлен в ожидание.")


@dp.message(Command("remove_admin"))
async def remove_admin_legacy(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return
    args = message.text.split(maxsplit=1)
    if len(args) == 1:
        await show_admin_selector(message, "remove")
        return
    value = args[1].strip()
    uid = int(value) if value.isdigit() else find_user_id_by_username(value)
    if uid is None:
        await message.answer("❌ Админ не найден.")
        return
    if uid == SUPER_ADMIN:
        await message.answer("❌ Владельца удалить нельзя.")
        return
    if uid not in get_admins():
        await message.answer("❌ Это не админ.")
        return
    display = get_admin_display(uid)
    admins = get_admins(); admins.remove(uid); save_admins(admins)
    data["admin_usernames"].pop(str(uid), None); save_data(); await set_command_scopes()
    await message.answer(f"✅ Админ <b>{escape(display)}</b> удалён.")


@dp.message(Command("pending_admins"))
async def pending_admins_command(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return
    pending = data.get("pending_admin_usernames", {})
    if not pending:
        await message.answer("📭 Ожидающих админов нет.")
        return
    text = "⏳ <b>Ожидают привязки:</b>\n\n" + "\n".join(f"• @{escape(v.get('username', k))}" for k, v in pending.items())
    await message.answer(text)


# =========================================================
# ЗАМЫ — БЕЗ БАНКА ЗАМОВ
# =========================================================

@dp.message(F.text == "👑 Замы")
async def zams_button(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return
    await send_zams_table(message)


async def send_zams_table(message):
    zams = get_all_zam_counts()
    if not zams:
        await message.answer("👑 <b>Замы</b>\n\n📭 Замов нет.")
        return
    text = "👑 <b>Замы</b>\n\n"
    text += "<pre>№  Nickname              @username        Пригласил</pre>"
    for i, (nick, count) in enumerate(zams, 1):
        info = data["zam_data"].get(nick, {})
        username = info.get("tg_username")
        nick_s = nick[:18]
        user_s = ("@" + username)[:15] if username else "—"
        text += f"<pre>{i:<3}{nick_s:<20}{user_s:<17}{count}</pre>"
    text += "\n📌 Количество приглашений считается автоматически по заполненным анкетам."
    text += "\n\n➕ <code>/add zam @username Game_Nick</code>\n➖ <code>/remove zam Game_Nick</code>"
    await message.answer(text)


async def add_zam_by_username(message: Message, username: str, game_nick: str):
    username = username.strip().lstrip("@")
    game_nick = game_nick.strip()
    if not username or not game_nick:
        await message.answer("❌ Использование: <code>/add zam @username Game_Nick</code>")
        return
    user_id = find_user_id_by_username(username)
    ok, result = add_zam_nick(game_nick, user_id, username)
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
        f"Telegram: @{escape(username)}" +
        (f"\nID: <code>{user_id}</code>" if user_id else "\n⏳ ID пока не найден.")
    )


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
# ЛОГИ / УВЕДОМЛЕНИЯ / BACKUP
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
    pages = max(1, (len(lines) + per - 1) // per)
    if page < 0 or page >= pages:
        return
    start = page * per
    text = f"📋 <b>Журнал ({page+1}/{pages})</b>\n\n" + "".join(lines[start:start+per])
    rows = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"lp_{page-1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"lp_{page+1}"))
    if nav:
        rows.append(nav)
    await message.answer(text[:4000], reply_markup=InlineKeyboardMarkup(inline_keyboard=rows) if rows else None)


@dp.callback_query(F.data.startswith("lp_"))
async def lp_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌")
        return
    await send_logs_page(cb.message, load_logs(), int(cb.data.split("_")[1]))
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


@dp.message(Command("log_on"))
async def log_on(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return
    data["log_notify_enabled"] = True
    save_data()
    await message.answer("✅ Уведомления о действиях включены.")


@dp.message(Command("log_off"))
async def log_off(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return
    data["log_notify_enabled"] = False
    save_data()
    await message.answer("❌ Уведомления о действиях выключены.")


@dp.message(Command("backup"))
async def backup_cmd(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return
    ok, path = create_backup("manual")
    await message.answer(
        ("✅ Резервная копия создана." if ok else "⚠️ Резервная копия создана частично.") +
        f"\n📁 <code>{escape(path)}</code>"
    )


@dp.message(Command("db_status"))
async def db_status_cmd(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return
    if DATABASE_URL and psycopg2 is not None and _db_init():
        saved = _db_get("data")
        logs = _db_get("logs")
        await message.answer(
            "✅ <b>PostgreSQL подключён</b>\n\n"
            f"👥 Пользователей: <b>{len(saved.get('users', {})) if isinstance(saved, dict) else len(data['users'])}</b>\n"
            f"📋 Заявок: <b>{len(saved.get('applications', {})) if isinstance(saved, dict) else len(data['applications'])}</b>\n"
            f"👑 Замов: <b>{len(saved.get('zam_data', {})) if isinstance(saved, dict) else len(data['zam_data'])}</b>\n"
            f"📜 Логов: <b>{len(logs) if isinstance(logs, list) else 0}</b>\n"
            f"💾 Последний backup: <b>{escape(str(data.get('last_backup_at') or 'ещё не создавался'))}</b>"
        )
    else:
        await message.answer("⚠️ PostgreSQL не подключён.")


# =========================================================
# PING / HELP
# =========================================================

@dp.message(Command("ping"))
async def ping(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Только админы!")
        return
    start = datetime.now()
    m = await message.answer("🏓 ...")
    ms = (datetime.now() - start).total_seconds() * 1000
    up = datetime.now() - BOT_START_TIME
    h, rem = divmod(up.seconds, 3600)
    mn, sc = divmod(rem, 60)
    await m.edit_text(f"🏓 Понг! {ms:.1f} мс\n⏱ Аптайм: {up.days}д {h}ч {mn}м {sc}с")


@dp.message(Command("myid"))
async def myid_cmd(message: Message):
    await message.answer(f"🆔 Твой Telegram ID: <code>{message.from_user.id}</code>")


@dp.message(Command("admins"))
async def admins_cmd(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return
    text = "👑 <b>Админы</b>\n\n"
    for i, uid in enumerate(sorted(get_admins()), 1):
        text += f"{i}. {escape(get_admin_display(uid))} — <code>{uid}</code>\n"
    await message.answer(text)


@dp.message(Command("help"))
async def help_cmd(message: Message):
    if is_super_admin(message.from_user.id):
        text = (
            "📋 <b>Команды владельца</b>\n\n"
            "/start — меню\n/help — справка\n/ping — пинг\n/all текст — объявление\n"
            "/кто — информация об участнике\n/поиск — поиск участника\n/history — история анкеты\n"
            "/add admin — выбрать админа из личных диалогов\n/remove admin — убрать админа\n"
            "/add zam @username Game_Nick — добавить зама\n/remove zam Game_Nick — убрать зама\n"
            "/admins — список админов\n/logs — журнал\n/backup — резервная копия\n/db_status — статус БД\n"
            "/log_on /log_off — уведомления о действиях\n/sbor — общий сбор\n/stopsbor — остановить сбор\n/topic_id — ID темы"
        )
    elif is_admin(message.from_user.id):
        text = (
            "📋 <b>Команды администратора</b>\n\n"
            "/start\n/help\n/ping\n/all текст\n/кто\n/поиск\n/history\n/topic_id\n/sbor\n/stopsbor"
        )
    else:
        text = "📋 <b>Команды</b>\n\n/start — меню\n/help — справка"
    await message.answer(text)


# =========================================================
# ОБЩИЙ СБОР
# =========================================================

def mention_html(member):
    name = member.get("name") or member.get("username") or str(member["id"])
    return f'<a href="tg://user?id={member["id"]}">{escape(name)}</a>'


def chunk_mentions(members, size=GATHER_CHUNK_SIZE):
    for i in range(0, len(members), size):
        yield members[i:i+size]


async def get_gather_members():
    members = []
    if telegram_user_is_ready():
        try:
            entity = None
            async for dialog in telegram_user_client.iter_dialogs():
                try:
                    if utils.get_peer_id(dialog.entity) == GROUP_ID:
                        entity = dialog.entity
                        break
                except Exception:
                    pass
            if entity is None:
                try:
                    entity = await telegram_user_client.get_entity(GROUP_ID)
                except Exception:
                    entity = None
            if entity is not None:
                async for user in telegram_user_client.iter_participants(entity):
                    if getattr(user, "bot", False) or getattr(user, "deleted", False):
                        continue
                    name = f"{getattr(user,'first_name',None) or ''} {getattr(user,'last_name',None) or ''}".strip()
                    username = getattr(user, "username", None)
                    members.append({"id": int(user.id), "name": name or username or str(user.id), "username": username})
                # Обновляем кэш, не удаляя старых людей.
                for member in members:
                    data["group_members"][str(member["id"])] = {
                        "id": member["id"], "username": member.get("username"),
                        "full_name": member.get("name"), "last_seen": now_iso()
                    }
                save_data()
                return members
        except Exception as e:
            print(f"⚠️ Telethon общий сбор: {e}")

    # Без Telethon используем только тех, кого бот уже видел.
    for uid, info in data.get("group_members", {}).items():
        iid = safe_int(uid)
        if iid:
            members.append({"id": iid, "name": info.get("full_name") or info.get("username") or uid, "username": info.get("username")})
    return list({m["id"]: m for m in members}.values())


async def send_gather_wave(members, wave_no, total_waves):
    if not members:
        return False
    for index, chunk in enumerate(chunk_mentions(members)):
        header = f"📢 <b>ОБЩИЙ СБОР</b>\nСозыв: <b>{wave_no}/{total_waves}</b>\n\n" if index == 0 else "📢 <b>ОБЩИЙ СБОР — продолжение</b>\n\n"
        try:
            await bot.send_message(GROUP_ID, header + " ".join(mention_html(m) for m in chunk))
        except Exception as e:
            print(f"⚠️ Ошибка общего сбора: {e}")
    return True


async def run_gather():
    try:
        total_waves = (GATHER_DURATION_SECONDS // GATHER_INTERVAL_SECONDS) + 1
        for wave in range(total_waves):
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
        await message.answer("❌ Только админы!")
        return
    current = gather_tasks.get(GROUP_ID)
    if current and not current.done():
        await message.answer("📢 <b>Общий сбор уже идёт.</b>")
        return
    gather_tasks[GROUP_ID] = asyncio.create_task(run_gather())
    await message.answer("🚨 <b>ОБЩИЙ СБОР ЗАПУЩЕН!</b>")


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


@dp.message(F.chat.id == GROUP_ID, F.text.func(lambda text: bool(text and text.strip().lower() == "общий сбор")))
async def gather_phrase(message: Message):
    await gather_command(message)


# =========================================================
# ЗАЩИТА ТЕМЫ / ALL / TOPIC
# =========================================================

@dp.message(F.chat.id == GROUP_ID)
async def protect_topic(message: Message):
    if message.message_thread_id == ANNOUNCE_TOPIC_ID and not is_admin(message.from_user.id):
        try:
            await message.delete()
            await bot.send_message(
                GROUP_ID,
                f"❌ {escape(message.from_user.full_name)}, только админы могут писать здесь!",
                reply_to_message_id=message.message_id,
            )
        except Exception:
            pass


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
        await bot.send_message(GROUP_ID, f"⚠️ <b>ВАЖНОЕ ОБЪЯВЛЕНИЕ</b>\n\n{escape(args[1])}\n\n@all", message_thread_id=ANNOUNCE_TOPIC_ID)
        await message.answer("✅ Отправлено.")
    except Exception as e:
        await message.answer(f"❌ {escape(str(e))}")


@dp.message(Command("topic_id"))
async def topic_id(message: Message):
    if message.chat.id == GROUP_ID and message.message_thread_id:
        await message.answer(f"ID: {message.message_thread_id}")
    else:
        await message.answer("❌ Не в теме.")


# =========================================================
# TELEGRAM COMMAND SCOPES
# =========================================================

DEFAULT_COMMANDS = [
    BotCommand(command="start", description="🏠 Меню"),
    BotCommand(command="help", description="📖 Справка"),
    BotCommand(command="myid", description="🆔 Мой Telegram ID"),
]

ADMIN_COMMANDS = DEFAULT_COMMANDS + [
    BotCommand(command="ping", description="📡 Пинг"),
    BotCommand(command="all", description="📢 Объявление"),
    BotCommand(command="кто", description="👤 Информация об участнике"),
    BotCommand(command="поиск", description="🔎 Поиск участника"),
    BotCommand(command="history", description="📜 История анкеты"),
    BotCommand(command="topic_id", description="🆔 ID темы"),
    BotCommand(command="sbor", description="📢 Общий сбор"),
    BotCommand(command="stopsbor", description="🛑 Остановить сбор"),
]

OWNER_COMMANDS = ADMIN_COMMANDS + [
    BotCommand(command="add", description="➕ Выдать админа/зама"),
    BotCommand(command="remove", description="➖ Убрать админа/зама"),
    BotCommand(command="add_admin", description="➕ Админ"),
    BotCommand(command="remove_admin", description="➖ Админ"),
    BotCommand(command="pending_admins", description="⏳ Ожидающие админы"),
    BotCommand(command="add_zam", description="👤 Добавить зама"),
    BotCommand(command="remove_zam", description="❌ Удалить зама"),
    BotCommand(command="admins", description="👑 Админы"),
    BotCommand(command="logs", description="📜 Журнал"),
    BotCommand(command="clearlogs", description="🧹 Очистить журнал"),
    BotCommand(command="log_on", description="🔔 Уведомления вкл"),
    BotCommand(command="log_off", description="🔕 Уведомления выкл"),
    BotCommand(command="backup", description="💾 Резервная копия"),
    BotCommand(command="db_status", description="🗄️ Статус базы"),
]


async def set_command_scopes():
    await bot.set_my_commands(DEFAULT_COMMANDS, scope=BotCommandScopeDefault())
    for admin_id in get_admins():
        if admin_id == SUPER_ADMIN:
            continue
        try:
            await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception:
            pass
    try:
        await bot.set_my_commands(OWNER_COMMANDS, scope=BotCommandScopeChat(chat_id=SUPER_ADMIN))
    except Exception:
        pass


# =========================================================
# ЗАПУСК
# =========================================================

async def main():
    print("🤖 Бот запускается...")
    if not DATABASE_URL:
        raise RuntimeError("❌ DATABASE_URL не задан. Бот намеренно не запускается без постоянной базы.")
    if not _db_init():
        raise RuntimeError("❌ Не удалось подключиться к PostgreSQL. Проверь DATABASE_URL.")

    await init_telegram_user_client()
    await init_admins()
    await set_command_scopes()
    await bot.delete_webhook(drop_pending_updates=True)

    print("🤖 Бот запущен!")
    print("📌 Основная группа:", GROUP_LINK)
    print("📌 Постоянная база PostgreSQL подключена.")
    print("📌 Уведомления о входе/выходе настроены на владельца:", SUPER_ADMIN)

    allowed_updates = dp.resolve_used_update_types()
    if "chat_member" not in allowed_updates:
        allowed_updates.append("chat_member")
    await dp.start_polling(bot, allowed_updates=allowed_updates)


if __name__ == "__main__":
    asyncio.run(main())
