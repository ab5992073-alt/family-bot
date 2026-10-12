import asyncio
import json
import os
import re
import traceback
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
    ErrorEvent,
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
# Render Environment: SUPER_ADMIN_ID=6166697485
try:
    SUPER_ADMIN = int(os.environ.get("SUPER_ADMIN_ID", "6166697485").strip())
except (TypeError, ValueError):
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
# АВТОМАТИЧЕСКИЕ ОТЧЁТЫ ОБ ОШИБКАХ ВЛАДЕЛЬЦУ
# =========================================================

_error_report_last = {}
_ERROR_REPORT_COOLDOWN = 60


def _error_ru(exc):
    name = type(exc).__name__
    text = str(exc or "").strip()

    explanations = {
        "NameError": "В коде используется имя, которое не определено. Частая причина — забытый import или опечатка.",
        "ImportError": "Не удалось импортировать нужный модуль или объект. Проверь импорт и зависимости.",
        "ModuleNotFoundError": "В окружении Render отсутствует нужный Python-модуль. Проверь requirements.txt.",
        "KeyError": "Бот запросил отсутствующий ключ словаря. Поле могло отсутствовать в данных.",
        "TypeError": "Бот получил данные неправильного типа или функция вызвана с неверными аргументами.",
        "ValueError": "Получено значение неправильного формата.",
        "AttributeError": "У объекта нет свойства или метода, к которому обратился код.",
        "IndexError": "Код обратился к элементу списка, которого не существует.",
        "TimeoutError": "Операция не успела завершиться. Возможна проблема с сетью, Telegram или базой.",
        "OperationalError": "Ошибка подключения или работы с базой данных/внешним сервисом.",
        "TelegramConflictError": "Запущен второй экземпляр бота, который одновременно получает Telegram updates.",
        "TelegramBadRequest": "Telegram отклонил запрос. Обычно это неверный chat_id, topic, сообщение или параметр.",
        "TelegramForbiddenError": "Telegram запретил действие: бот не имеет доступа, был заблокирован или не имеет нужного права.",
    }
    result = explanations.get(
        name,
        "Произошла необработанная ошибка. По стеку ниже можно определить точное место и причину."
    )

    if name == "NameError" and "re" in text and "not defined" in text:
        result = "Используется модуль re, но он не подключён. В начале main.py должен быть import re."

    return result


async def _send_error_report(exc, context="Обработка Telegram update"):
    try:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()
        fingerprint = f"{type(exc).__name__}|{str(exc)}|{tb}"
        import hashlib
        key = hashlib.sha256(fingerprint.encode("utf-8", "replace")).hexdigest()[:20]
        now = datetime.now().timestamp()

        if now - _error_report_last.get(key, 0) < _ERROR_REPORT_COOLDOWN:
            return
        _error_report_last[key] = now

        # Ищем последнюю строку main.py с номером строки.
        location = "не определено"
        matches = re.findall(r'File ".*?/main\.py", line (\d+), in ([^\n]+)', tb)
        if matches:
            line, func = matches[-1]
            location = f"main.py, строка {line}, функция {func.strip()}"

        report = (
            "🚨 <b>ОШИБКА БОТА</b>\n\n"
            f"📌 <b>Где:</b> {escape(str(context))}\n"
            f"📍 <b>Место:</b> <code>{escape(location)}</code>\n"
            f"❌ <b>Тип:</b> <code>{escape(type(exc).__name__)}</code>\n\n"
            f"🇷🇺 <b>Расшифровка:</b>\n{escape(_error_ru(exc))}\n\n"
            f"📄 <b>Оригинал:</b>\n<code>{escape(str(exc) or '(без текста)')[:1500]}</code>\n\n"
            f"🔎 <b>Стек:</b>\n<pre>{escape(tb[-5000:])}</pre>"
        )

        # Telegram: максимум около 4096 символов.
        for i in range(0, len(report), 3900):
            try:
                await bot.send_message(SUPER_ADMIN, report[i:i + 3900])
            except Exception as send_exc:
                print("❌ Не удалось отправить отчёт владельцу:", repr(send_exc))
                break
    except Exception as report_exc:
        print("❌ Ошибка формирования отчёта:", repr(report_exc))


async def _global_error_handler(event: ErrorEvent):
    exc = event.exception
    print("❌ Необработанная ошибка:", repr(exc))
    await _send_error_report(exc)
    return True


dp.errors.register(_global_error_handler)


def _asyncio_error_handler(loop, context):
    exc = context.get("exception")
    if exc is None:
        exc = RuntimeError(context.get("message", "Неизвестная ошибка asyncio"))
    print("❌ Ошибка фоновой задачи:", repr(exc))
    try:
        loop.create_task(_send_error_report(exc, "Фоновая задача asyncio"))
    except Exception as e:
        print("❌ Не удалось запланировать отчёт:", repr(e))



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




class MaintenanceModeMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data_ctx):
        uid = event.from_user.id if getattr(event, "from_user", None) else None
        enabled = bool(data.get("bot_settings", {}).get("maintenance_mode", False))
        if enabled and uid != SUPER_ADMIN:
            if isinstance(event, CallbackQuery):
                await event.answer("🔴 Бот временно выключен владельцем.", show_alert=True)
            elif isinstance(event, Message):
                await event.answer("🔴 <b>Бот временно выключен.</b>\n\nПопробуйте позже.")
            return
        return await handler(event, data_ctx)


class AdminPermissionMiddleware(BaseMiddleware):
    MESSAGE_PERMS = {
        "📋 Управление заявками": "applications",
        "⏳ Активные заявки": "applications",
        "👥 Список участников": "users",
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
        "📨 Report": "reports",
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
        if cd.startswith(("report:", "reports:")): return "reports"
        if cd.startswith("announce_target:"): return "announcements"
        if cd.startswith("dash:"):
            action=cd.split(":",1)[1]
            return {"apps":"applications","users":"users","zams":"zams","stats":"stats","announce":"announcements","sbor":"gathering","audit":"audit","sheets":"sheets","admins":"admins","settings":"settings","reminders":"reminders","reports":"reports"}.get(action)
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


dp.message.outer_middleware(MaintenanceModeMiddleware())
dp.callback_query.outer_middleware(MaintenanceModeMiddleware())
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
_google_sync_task = None
_google_sync_pending = False
_google_sync_running = False

async def _flush_google_sync():
    """Отложенная синхронизация Google Sheets после изменения данных.
    Несколько быстрых действий объединяются в один экспорт.
    """
    global _google_sync_task, _google_sync_pending, _google_sync_running
    try:
        while _google_sync_pending:
            _google_sync_pending = False
            await asyncio.sleep(2.0)
            if not GOOGLE_SERVICE_ACCOUNT_JSON or not gspread or not Credentials:
                continue
            _google_sync_running = True
            try:
                result = await asyncio.to_thread(sync_google_sheets_sync)
                if not result.get("ok"):
                    print("⚠️ Автосинхронизация Google Sheets:", result.get("error", "ошибка"))
            finally:
                _google_sync_running = False
    except asyncio.CancelledError:
        return
    except Exception as e:
        _google_sync_running = False
        print("⚠️ Ошибка автосинхронизации Google Sheets:", e)
    finally:
        _google_sync_task = None

def request_google_sync():
    global _google_sync_task, _google_sync_pending
    if not (GOOGLE_SERVICE_ACCOUNT_JSON and gspread and Credentials):
        return
    if _google_sync_running:
        _google_sync_pending = True
        return
    _google_sync_pending = True
    try:
        loop = asyncio.get_running_loop()
        if _google_sync_task is None or _google_sync_task.done():
            _google_sync_task = loop.create_task(_flush_google_sync())
    except RuntimeError:
        pass

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
    if not _google_sync_running:
        request_google_sync()
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
    "bot_settings": {"reminders_enabled": False, "pin_announcements": False, "maintenance_mode": False},
    "last_reminders": {},
    "reminders": [],
    "reports": [],
    "report_seq": 0,
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
    data["bot_settings"] = {"reminders_enabled": False, "pin_announcements": False, "maintenance_mode": False}
    changed = True
if not isinstance(data.get("last_reminders"), dict):
    data["last_reminders"] = {}
    changed = True
if not isinstance(data.get("reminders"), list):
    data["reminders"] = []
if not isinstance(data.get("reports"), list):
    data["reports"] = []
if not isinstance(data.get("report_seq"), int):
    data["report_seq"] = 0
if not data.setdefault("bot_settings", {}).get("timezone"):
    data["bot_settings"]["timezone"] = "Europe/Moscow"
    changed = True
if "maintenance_mode" not in data.setdefault("bot_settings", {}):
    data["bot_settings"]["maintenance_mode"] = False
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
    perms = data.setdefault("admin_permissions", {})
    for uid in data["admins"]:
        if int(uid) == SUPER_ADMIN:
            continue
        perms.setdefault(str(uid), dict(DEFAULT_ADMIN_PERMISSIONS))
    save_data()


def is_admin(user_id):
    return user_id in get_admins()


def is_super_admin(user_id):
    return user_id == SUPER_ADMIN


# =========================================================
# ПРАВА АДМИНИСТРАТОРОВ
# =========================================================

ADMIN_PERMISSION_DEFS = [
    ("applications", "📋 Управление заявками"),
    ("users", "👥 Участники"),
    ("announcements", "📢 Объявления"),
    ("gathering", "📢 Общий сбор"),
    ("zams", "👑 Замы"),
    ("stats", "📊 Статистика"),
    ("status", "🟢 Статус бота"),
    ("audit", "📜 Журнал действий"),
    ("admins", "🛡 Управление админами"),
    ("settings", "⚙️ Настройки"),
    ("sheets", "☁️ Google Таблица"),
    ("participant_message", "📨 Сообщения участникам"),
    ("reminders", "🔔 Напоминания"),
    ("reports", "📨 Report / обращения"),
]

ADMIN_PERMISSION_LABELS = dict(ADMIN_PERMISSION_DEFS)

# Базовый набор для обычного администратора. Владелец может включить/выключить
# любую отдельную функцию через меню прав.
DEFAULT_ADMIN_PERMISSIONS = {
    "applications": True,
    "users": True,
    "announcements": True,
    "gathering": True,
    "zams": False,
    "stats": True,
    "status": True,
    "audit": False,
    "admins": False,
    "settings": False,
    "sheets": False,
    "participant_message": True,
    "reminders": False,
    "reports": True,
}


def ensure_admin_permissions():
    perms = data.setdefault("admin_permissions", {})
    changed_local = False
    for uid in data.get("admins", []):
        suid = str(uid)
        if int(uid) == SUPER_ADMIN:
            continue
        if suid not in perms or not isinstance(perms.get(suid), dict):
            perms[suid] = dict(DEFAULT_ADMIN_PERMISSIONS)
            changed_local = True
        else:
            for key, value in DEFAULT_ADMIN_PERMISSIONS.items():
                if key not in perms[suid]:
                    perms[suid][key] = value
                    changed_local = True
    if changed_local:
        save_data()


def admin_can(user_id, permission):
    if is_super_admin(user_id):
        return True
    if not is_admin(user_id):
        return False
    ensure_admin_permissions()
    return bool(data.get("admin_permissions", {}).get(str(user_id), {}).get(permission, False))


def permission_denied_text(permission):
    return f"❌ У тебя нет права: <b>{escape(ADMIN_PERMISSION_LABELS.get(permission, permission))}</b>"


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
    b.row(
        KeyboardButton(text="📨 Report"),
    )

    return b.as_markup(resize_keyboard=True)


def admin_keyboard(user_id, has_survey=False):
    """Удобное компактное меню администратора: основные действия сверху,
    расширенные разделы — в панели управления."""
    b = ReplyKeyboardBuilder()
    rows = []
    if admin_can(user_id, "applications"):
        rows.append([KeyboardButton(text="📋 Заявки")])
    if admin_can(user_id, "users"):
        rows.append([KeyboardButton(text="👥 Участники"), KeyboardButton(text="📊 Статистика")]) if admin_can(user_id, "stats") else rows.append([KeyboardButton(text="👥 Участники")])
    elif admin_can(user_id, "stats"):
        rows.append([KeyboardButton(text="📊 Статистика")])
    if admin_can(user_id, "announcements"):
        rows.append([KeyboardButton(text="📢 Объявление")])
    if admin_can(user_id, "gathering"):
        rows.append([KeyboardButton(text="📢 Общий сбор")])
    if admin_can(user_id, "reminders"):
        rows.append([KeyboardButton(text="🔔 Напоминания")])
    if admin_can(user_id, "zams"):
        rows.append([KeyboardButton(text="👑 Замы")])
    if has_survey:
        rows.append([KeyboardButton(text="🔄 Перезаполнить анкету")])
    rows.append([KeyboardButton(text="📨 Report")])
    if any(admin_can(user_id, p) for p in ("audit","admins","settings","sheets","status")):
        rows.append([KeyboardButton(text="🏠 Панель управления")])
    if admin_can(user_id, "status"):
        rows.append([KeyboardButton(text="🟢 Статус бота")])
    for row in rows:
        b.row(*row)
    return b.as_markup(resize_keyboard=True)


def admin_panel_keyboard():
    rows = [
        [InlineKeyboardButton(text="➕ Добавить админа", callback_data="adm:add"), InlineKeyboardButton(text="➖ Удалить админа", callback_data="adm:remove")],
        [InlineKeyboardButton(text="👑 Список админов", callback_data="adm:list")],
    ]
    # Кнопка выдачи детальных прав — только владельцу.
    rows.append([InlineKeyboardButton(text="🔐 Права админов", callback_data="perm:list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def permissions_admin_list_keyboard():
    rows = []
    for uid in sorted(get_admins()):
        if uid == SUPER_ADMIN:
            continue
        rows.append([InlineKeyboardButton(text=f"🛡 {get_admin_display(uid)[:35]}", callback_data=f"perm:user:{uid}")])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="adm:list")])
    return InlineKeyboardMarkup(inline_keyboard=rows or [[InlineKeyboardButton(text="📭 Нет обычных админов", callback_data="adm:list")]])


def permissions_keyboard(uid):
    perms = data.setdefault("admin_permissions", {}).setdefault(str(uid), dict(DEFAULT_ADMIN_PERMISSIONS))
    rows = []
    for key, label in ADMIN_PERMISSION_DEFS:
        mark = "🟢" if perms.get(key, False) else "🔴"
        rows.append([InlineKeyboardButton(text=f"{mark} {label}", callback_data=f"perm:toggle:{uid}:{key}")])
    rows.append([InlineKeyboardButton(text="◀️ К списку админов", callback_data="perm:list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def permissions_text(uid):
    perms = data.setdefault("admin_permissions", {}).setdefault(str(uid), dict(DEFAULT_ADMIN_PERMISSIONS))
    lines = [f"🔐 <b>Права администратора</b>", f"👤 {escape(get_admin_display(uid))}", ""]
    for key, label in ADMIN_PERMISSION_DEFS:
        lines.append(f"{'🟢' if perms.get(key, False) else '🔴'} {escape(label)}")
    lines.append("\nНажимай на функцию, чтобы включить или выключить право.")
    return "\n".join(lines)


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
    if not admin_can(message.from_user.id, "users"):
        await message.answer(permission_denied_text("users"))
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
    if not admin_can(message.from_user.id, "applications"):
        await message.answer("❌")
        return
    await send_apps_page(message, "pending", 0)


@dp.message(F.text == "⏳ Активные заявки")
async def active_apps(message: Message):
    if not admin_can(message.from_user.id, "applications"):
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
    if not admin_can(message.from_user.id, "users"): 
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
    if not admin_can(message.from_user.id, "status"):
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
    if not admin_can(message.from_user.id, "admins"):
        await message.answer(permission_denied_text("admins"))
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
    if not admin_can(cb.from_user.id, "admins"):
        await cb.answer(permission_denied_text("admins"), show_alert=True)
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
    if not admin_can(cb.from_user.id, "admins"):
        await cb.answer("❌", show_alert=True); return
    users = await cached_owner_dialog_users()
    page = int(cb.data.split(":", 1)[1])
    await cb.answer()
    await cb.message.edit_reply_markup(reply_markup=owner_dialog_page_keyboard(users, page, prefix="select_admin"))

@dp.callback_query(F.data.startswith("select_admin:"))
async def select_admin_cb(cb: CallbackQuery):
    if not admin_can(cb.from_user.id, "admins"):
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
    if not admin_can(cb.from_user.id, "admins"):
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
    if not admin_can(cb.from_user.id, "admins"):
        await cb.answer(permission_denied_text("admins"), show_alert=True); return
    rows=[]
    for uid in sorted(get_admins()):
        if uid == SUPER_ADMIN: continue
        rows.append([InlineKeyboardButton(text=f"🛡 {get_admin_display(uid)[:35]}", callback_data=f"admin_remove_confirm:{uid}")])
    rows.append([InlineKeyboardButton(text="↩️ Назад", callback_data="adm:list")])
    await cb.answer()
    await cb.message.edit_text("➖ <b>Выберите администратора для удаления:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows or [[InlineKeyboardButton(text="📭 Удалять некого", callback_data="adm:list")]]))

@dp.callback_query(F.data.startswith("admin_remove_confirm:"))
async def admin_remove_confirm_cb(cb: CallbackQuery):
    if not admin_can(cb.from_user.id, "admins"):
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
    if not admin_can(cb.from_user.id, "admins"):
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
    if not admin_can(cb.from_user.id, "admins"):
        await cb.answer("❌", show_alert=True); return
    text="👑 <b>Администраторы</b>\n\n"
    for uid in sorted(get_admins()):
        mark="👑" if uid == SUPER_ADMIN else "🛡"
        text += f"{mark} {escape(get_admin_display(uid))}\n🆔 <code>{uid}</code>\n\n"
    await cb.answer()
    await cb.message.edit_text(text, reply_markup=admin_panel_keyboard())

@dp.callback_query(F.data == "perm:list")
async def permissions_list_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец", show_alert=True); return
    ensure_admin_permissions()
    await cb.answer()
    await cb.message.edit_text("🔐 <b>Права администраторов</b>\n\nВыберите администратора:", reply_markup=permissions_admin_list_keyboard())


@dp.callback_query(F.data.startswith("perm:user:"))
async def permissions_user_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец", show_alert=True); return
    uid=int(cb.data.split(":",2)[2])
    if uid not in get_admins() or uid == SUPER_ADMIN:
        await cb.answer("❌ Администратор не найден", show_alert=True); return
    ensure_admin_permissions()
    await cb.answer()
    await cb.message.edit_text(permissions_text(uid), reply_markup=permissions_keyboard(uid))


@dp.callback_query(F.data.startswith("perm:toggle:"))
async def permissions_toggle_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец", show_alert=True); return
    _,_,uid_raw,key=cb.data.split(":",3)
    uid=int(uid_raw)
    if uid not in get_admins() or uid == SUPER_ADMIN or key not in ADMIN_PERMISSION_LABELS:
        await cb.answer("❌ Неверные данные", show_alert=True); return
    perms=data.setdefault("admin_permissions",{}).setdefault(str(uid),dict(DEFAULT_ADMIN_PERMISSIONS))
    perms[key]=not bool(perms.get(key,False))
    save_data()
    await cb.answer("Право " + ("выдано" if perms[key] else "забрано"))
    await cb.message.edit_text(permissions_text(uid), reply_markup=permissions_keyboard(uid))


@dp.callback_query(F.data == "owner_select_cancel")
async def owner_select_cancel_cb(cb: CallbackQuery):
    if not admin_can(cb.from_user.id, "admins") and not is_super_admin(cb.from_user.id):
        await cb.answer("❌", show_alert=True); return
    await cb.message.edit_text("❌ Выбор отменён.", reply_markup=admin_panel_keyboard())
    await cb.answer()

@dp.message(Command("add_admin"))
async def add_admin_legacy(message: Message):
    if not admin_can(message.from_user.id, "admins"):
        await message.answer(permission_denied_text("admins"))
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
    if not admin_can(message.from_user.id, "admins"):
        await message.answer(permission_denied_text("admins"))
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
    if not admin_can(message.from_user.id, "admins"):
        await message.answer(permission_denied_text("admins"))
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
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет прав!")
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
    if mode == "admin" and not admin_can(message.from_user.id, "admins"):
        await message.answer(permission_denied_text("admins")); return
    if mode == "zam" and not admin_can(message.from_user.id, "zams"):
        await message.answer(permission_denied_text("zams")); return
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
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет прав!")
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 2:
        await message.answer("❌ <code>/remove admin @username</code> или <code>/remove zam Game_Nick</code>")
        return
    mode = args[1].lower()
    if mode == "admin" and not admin_can(message.from_user.id, "admins"):
        await message.answer(permission_denied_text("admins")); return
    if mode == "zam" and not admin_can(message.from_user.id, "zams"):
        await message.answer(permission_denied_text("zams")); return
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
    if not admin_can(message.from_user.id, "zams"):
        await message.answer(permission_denied_text("zams"))
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
    if not admin_can(cb.from_user.id, "zams"):
        await cb.answer(permission_denied_text("zams"), show_alert=True)
        return
    zam_edit_mode[cb.from_user.id] = {"action": "add"}
    await cb.message.answer("➕ Введите: <code>@username Game_Nick</code>")
    await cb.answer()


@dp.callback_query(F.data == "zam:remove")
async def zam_remove_cb(cb: CallbackQuery):
    if not admin_can(cb.from_user.id, "zams"):
        await cb.answer(permission_denied_text("zams"), show_alert=True)
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
    if not admin_can(message.from_user.id, "zams"):
        await message.answer(permission_denied_text("zams"))
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("❌ Использование: <code>/add_zam @username Game_Nick</code>")
        return
    await add_zam_by_username(message, args[1], args[2])


@dp.message(Command("remove_zam"))
async def remove_zam_command(message: Message):
    if not admin_can(message.from_user.id, "zams"):
        await message.answer(permission_denied_text("zams"))
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
    if not admin_can(cb.from_user.id, "zams"):
        await cb.answer(permission_denied_text("zams"), show_alert=True); return
    await cb.answer()
    await send_zam_stats(cb.message, int(cb.data.split(":")[1]))


@dp.callback_query(F.data == "zams_search")
async def zams_search_cb(cb: CallbackQuery):
    if not admin_can(cb.from_user.id, "zams"):
        await cb.answer(permission_denied_text("zams"), show_alert=True); return
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
    if not admin_can(cb.from_user.id, "zams"): await cb.answer("❌ Только владелец",show_alert=True); return
    nick=cb.data.split(":",1)[1]; info=data.get("zam_data",{}).get(nick)
    if not info: await cb.answer("❌ Не найден",show_alert=True); return
    username=info.get("tg_username") or "—"
    uid=info.get("tg_user_id") or "—"
    await cb.message.edit_text(f"👑 <b>{escape(nick)}</b>\n\n📱 @{escape(str(username).lstrip('@')) if username!='—' else '—'}\n🆔 <code>{escape(str(uid))}</code>\n📊 Приглашений: <b>{count_zam_answers(nick)}</b>",reply_markup=zam_card_keyboard(nick)); await cb.answer()

@dp.callback_query(F.data.startswith("zam_viewedit:"))
async def zam_viewedit_cb(cb: CallbackQuery):
    if not admin_can(cb.from_user.id, "zams"): await cb.answer("❌",show_alert=True); return
    nick=cb.data.split(":",1)[1]
    await cb.message.edit_text("✏️ <b>Редактирование зама</b>",reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Nickname",callback_data=f"zam_editnick:{nick}")],
        [InlineKeyboardButton(text="📱 @username",callback_data=f"zam_edituser:{nick}")],
        [InlineKeyboardButton(text="◀️ Назад",callback_data=f"zam_view:{nick}")],
    ])); await cb.answer()

@dp.callback_query(F.data.startswith("zam_edituser:"))
async def zam_edituser_cb(cb: CallbackQuery):
    if not admin_can(cb.from_user.id, "zams"): await cb.answer("❌",show_alert=True); return
    nick=cb.data.split(":",1)[1]; zam_edit_mode[cb.from_user.id]={"old_nick":nick,"field":"tg_username"}
    await cb.message.answer("📱 Введите новый @username зама или —:"); await cb.answer()

@dp.callback_query(F.data.startswith("zam_editnick:"))
async def zam_editnick_cb(cb: CallbackQuery):
    if not admin_can(cb.from_user.id, "zams"): await cb.answer("❌",show_alert=True); return
    nick=cb.data.split(":",1)[1]; zam_edit_mode[cb.from_user.id]={"old_nick":nick,"field":"nickname"}
    await cb.message.answer("👤 Введите новый игровой Nickname зама:"); await cb.answer()

@dp.callback_query(F.data.startswith("zam_confirmremove:"))
async def zam_confirmremove_cb(cb: CallbackQuery):
    if not admin_can(cb.from_user.id, "zams"): await cb.answer("❌",show_alert=True); return
    nick=cb.data.split(":",1)[1]
    await cb.message.edit_text(f"⚠️ Удалить <b>{escape(nick)}</b> из замов?",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Да, удалить",callback_data=f"zam_doremove:{nick}")],[InlineKeyboardButton(text="↩️ Отмена",callback_data=f"zam_view:{nick}")]])); await cb.answer()

@dp.callback_query(F.data == "zams_back")
async def zams_back_cb(cb: CallbackQuery):
    if not admin_can(cb.from_user.id, "zams"):
        await cb.answer(permission_denied_text("zams"), show_alert=True); return
    await cb.message.edit_text("👑 <b>Управление замами</b>", reply_markup=zams_panel_keyboard())
    await cb.answer()


@dp.callback_query(F.data.startswith("zam_doremove:"))
async def zam_doremove_cb(cb: CallbackQuery):
    if not admin_can(cb.from_user.id, "zams"): await cb.answer("❌",show_alert=True); return
    nick=cb.data.split(":",1)[1]
    if remove_zam_nick(nick):
        save_data(); await log_action(cb.from_user.id,"удалил зама",nick); await cb.message.edit_text("✅ Зам удалён."); await cb.answer()
    else: await cb.answer("❌ Не найден",show_alert=True)

@dp.message(lambda m: m.from_user.id in zam_edit_mode and bool(m.text))
async def zam_edit_text(message: Message):
    if not admin_can(message.from_user.id, "zams"): return
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
    if not admin_can(message.from_user.id, "audit"): await message.answer(permission_denied_text("audit")); return
    await send_audit_page(message)

@dp.message(F.text == "📜 Журнал действий")
async def logs_btn(message: Message):
    if not admin_can(message.from_user.id, "audit"): await message.answer("❌ Только владелец!"); return
    await send_audit_page(message)

@dp.callback_query(F.data.startswith("audit_cat:"))
async def audit_cat_cb(cb: CallbackQuery):
    if not admin_can(cb.from_user.id, "audit"): await cb.answer(permission_denied_text("audit"),show_alert=True); return
    cat=cb.data.split(":",1)[1]; await cb.answer(); await send_audit_page(cb.message,cat,0)

@dp.callback_query(F.data.startswith("audit_page:"))
async def audit_page_cb(cb: CallbackQuery):
    if not admin_can(cb.from_user.id, "audit"): await cb.answer(permission_denied_text("audit"),show_alert=True); return
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
    if not admin_can(message.from_user.id, "status"):
        await message.answer(permission_denied_text("status"))
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


def dashboard_keyboard(uid):
    rows = []
    if admin_can(uid, "applications"):
        rows.append([InlineKeyboardButton(text="📋 Заявки", callback_data="dash:apps")])
    if admin_can(uid, "users"):
        rows.append([InlineKeyboardButton(text="👥 Участники", callback_data="dash:users")])
    if admin_can(uid, "zams"):
        rows.append([InlineKeyboardButton(text="👑 Замы", callback_data="dash:zams")])
    if admin_can(uid, "stats"):
        rows.append([InlineKeyboardButton(text="📊 Статистика", callback_data="dash:stats")])
    if admin_can(uid, "announcements"):
        rows.append([InlineKeyboardButton(text="📢 Объявление", callback_data="dash:announce")])
    if admin_can(uid, "gathering"):
        rows.append([InlineKeyboardButton(text="📢 Общий сбор", callback_data="dash:sbor")])
    if admin_can(uid, "audit"):
        rows.append([InlineKeyboardButton(text="📜 Журнал", callback_data="dash:audit")])
    if admin_can(uid, "sheets"):
        rows.append([InlineKeyboardButton(text="☁️ Google Таблица", callback_data="dash:sheets")])
    if admin_can(uid, "admins"):
        rows.append([InlineKeyboardButton(text="🛡 Админы", callback_data="dash:admins")])
    if admin_can(uid, "settings"):
        rows.append([InlineKeyboardButton(text="⚙️ Настройки", callback_data="dash:settings")])
    if admin_can(uid, "reminders"):
        rows.append([InlineKeyboardButton(text="🔔 Напоминания", callback_data="dash:reminders")])
    if admin_can(uid, "reports"):
        rows.append([InlineKeyboardButton(text="📨 Report / обращения", callback_data="dash:reports")])
    return InlineKeyboardMarkup(inline_keyboard=rows or [[InlineKeyboardButton(text="📭 Нет доступных функций", callback_data="dash:none")]])


def settings_keyboard():
    r = data.setdefault("bot_settings", {})
    rem = "🟢" if r.get("reminders_enabled") else "🔴"
    pin = "🟢" if r.get("pin_announcements") else "🔴"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{rem} Напоминания об анкетах", callback_data="set:reminders")],
        [InlineKeyboardButton(text=f"{pin} Закреплять объявления", callback_data="set:pin")],
        [InlineKeyboardButton(text="🔔 Уведомления админа", callback_data="set:notify")],
        [InlineKeyboardButton(text="🔔 Управление напоминаниями", callback_data="rem:menu")],
        [InlineKeyboardButton(text=("🔴 Выключить бота для всех" if not r.get("maintenance_mode") else "🟢 Включить бота для всех"), callback_data="set:maintenance")],
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



def sheet_application_status(status):
    return {
        "pending": "🟠 Ожидает",
        "accepted": "🟢 Принята",
        "rejected": "🔴 Отклонена",
        "cancelled": "⚪ Отменена",
    }.get(str(status), "⚪ Неизвестно")


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
            "Напоминания": [["ID","Название","Текст","Время","Статус","Куда","Тема ID","Упоминать всех","Создал","Создано"]],
            "Репорты": [["ID","Дата","Пользователь ID","Пользователь","@username","Категория","Текст","Статус","Ответил","Ответ"]],
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
            rows.append([aid,a.get("user_id",""),d.get("nickname",""),d.get("tag",d.get("username","")),d.get("rank_fam",""),d.get("organization",""),d.get("inviter",""),sheet_application_status(a.get("status","")),a.get("created","" )])
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
        ws=sh.worksheet("Напоминания"); rows=[]
        for r in data.get("reminders",[]):
            rows.append([r.get("id",""),r.get("name",""),r.get("text",""),r.get("time",""),"Вкл" if r.get("enabled",True) else "Выкл",REMINDER_TARGETS.get(r.get("target","group"),r.get("target","")),r.get("topic_id",""), "Да" if r.get("mention_all") else "Нет",r.get("created_by",""),r.get("created_at","")])
        if rows: ws.update("A2",rows)
        ws=sh.worksheet("Репорты"); rows=[]
        for rp in data.get("reports",[]):
            rows.append([rp.get("id",""),rp.get("created_at",""),rp.get("user_id",""),rp.get("user_name",""),rp.get("username",""),rp.get("category",""),rp.get("text",""),rp.get("status","open"),rp.get("answered_by_name","") or "",rp.get("admin_reply","") or ""])
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
    if not admin_can(message.from_user.id, "stats"): return
    await message.answer(stats_text(), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🧹 Проверить дубли",callback_data="set:duplicates")],[InlineKeyboardButton(text="◀️ Панель",callback_data="dash:home")]]))

@dp.message(F.text == "☁️ Google Таблица")
async def sheets_btn(message: Message):
    if not admin_can(message.from_user.id, "sheets"): return
    url=google_sheet_url()
    text="☁️ <b>Google Таблица</b>\n\n" + (f"Последняя таблица:\n{escape(url)}" if url else "Таблица ещё не создана.") + "\n\n🔄 <b>Автосинхронизация:</b> включена — изменения отправляются автоматически."
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Синхронизировать",callback_data="sheets:sync")],[InlineKeyboardButton(text="◀️ Панель",callback_data="dash:home")]]))

@dp.message(F.text == "⚙️ Настройки")
async def settings_btn(message: Message):
    if not admin_can(message.from_user.id, "settings"): return
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
    elif action=="reminders": await cb.message.edit_text(reminders_text(), reply_markup=reminders_keyboard())
    elif action=="reports": await send_reports_page(cb.message)
    elif action=="sheets":
        url=google_sheet_url(); await cb.message.edit_text("☁️ <b>Google Таблица</b>\n\n"+(escape(url) if url else "Таблица ещё не создана."),reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Синхронизировать",callback_data="sheets:sync")],[InlineKeyboardButton(text="◀️ Панель",callback_data="dash:home")]]))
    elif action=="announce":
        announcement_mode[cb.from_user.id]={"pin":False}
        kb=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👤 Только в ЛС участникам",callback_data="announce_target:dm")],
            [InlineKeyboardButton(text="👥 Только в группу",callback_data="announce_target:group")],
            [InlineKeyboardButton(text="📢 Везде (ЛС + группа)",callback_data="announce_target:all")],
            [InlineKeyboardButton(text="❌ Отмена",callback_data="announce_target:cancel")],
        ])
        await cb.message.answer("📣 <b>Куда отправить объявление?</b>",reply_markup=kb)
    elif action=="sbor":
        await start_gather_from_button(cb.message)

@dp.callback_query(F.data.startswith("set:"))
async def settings_cb(cb: CallbackQuery):
    if not admin_can(cb.from_user.id, "settings"): return await cb.answer(permission_denied_text("settings"),show_alert=True)
    action=cb.data.split(":",1)[1]
    if action=="reminders": data.setdefault("bot_settings",{})["reminders_enabled"]=not data.setdefault("bot_settings",{}).get("reminders_enabled",False); save_data(); await cb.message.edit_text("⚙️ Настройки",reply_markup=settings_keyboard()); await cb.answer("Готово")
    elif action=="maintenance":
        if not is_super_admin(cb.from_user.id):
            return await cb.answer("❌ Только владелец", show_alert=True)
        enabled = not bool(data.setdefault("bot_settings", {}).get("maintenance_mode", False))
        data["bot_settings"]["maintenance_mode"] = enabled
        save_data()
        await cb.message.edit_text("⚙️ <b>Настройки бота</b>\n\n" + ("🔴 <b>Бот выключен для всех, кроме владельца.</b>" if enabled else "🟢 <b>Бот снова доступен всем.</b>"), reply_markup=settings_keyboard())
        await cb.answer("Режим изменён")
    elif action=="pin": data.setdefault("bot_settings",{})["pin_announcements"]=not data.setdefault("bot_settings",{}).get("pin_announcements",False); save_data(); await cb.message.edit_text("⚙️ Настройки",reply_markup=settings_keyboard()); await cb.answer("Готово")
    elif action=="notify":
        cur=data.setdefault("notify_settings",{}).get(str(cb.from_user.id),True); data["notify_settings"][str(cb.from_user.id)]=not cur; save_data(); await cb.message.edit_text("⚙️ Настройки",reply_markup=settings_keyboard()); await cb.answer("Уведомления " + ("включены" if not cur else "выключены"))
    elif action=="duplicates": await cb.message.edit_text(duplicate_report(),reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Настройки",callback_data="dash:settings")]])); await cb.answer()

@dp.callback_query(F.data=="sheets:sync")
async def sheets_sync_cb(cb: CallbackQuery):
    if not admin_can(cb.from_user.id, "sheets"): return await cb.answer(permission_denied_text("sheets"),show_alert=True)
    await cb.answer("Синхронизация запущена")
    result=await asyncio.to_thread(sync_google_sheets_sync)
    if result.get("ok"):
        await cb.message.edit_text("✅ <b>Google Таблица обновлена.</b>\n\n"+escape(result.get("url","")),reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Обновить ещё раз",callback_data="sheets:sync")],[InlineKeyboardButton(text="◀️ Панель",callback_data="dash:home")]]))
    else:
        await cb.message.edit_text("❌ <b>Google Таблица не настроена</b>\n\n"+escape(result.get("error","Неизвестная ошибка"))+"\n\nДобавь GOOGLE_SERVICE_ACCOUNT_JSON в Render и дай сервисному аккаунту доступ к таблице.",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Панель",callback_data="dash:home")]]))

# =========================================================
# REPORT / ОБРАЩЕНИЯ ПОЛЬЗОВАТЕЛЕЙ
# =========================================================

report_mode = {}
REPORT_CATEGORIES = {
    "bug": "🐞 Ошибка",
    "suggest": "💡 Предложение",
    "complaint": "🚨 Жалоба",
    "other": "❓ Другое",
}

def _next_report_id():
    return max([int(x.get("id", 0)) for x in data.get("reports", []) if str(x.get("id", "")).isdigit()] or [0]) + 1

def report_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🐞 Ошибка", callback_data="report:new:bug"), InlineKeyboardButton(text="💡 Предложение", callback_data="report:new:suggest")],
        [InlineKeyboardButton(text="🚨 Жалоба", callback_data="report:new:complaint"), InlineKeyboardButton(text="❓ Другое", callback_data="report:new:other")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="report:cancel")],
    ])

def report_admin_keyboard(rid):
    r = next((x for x in data.get("reports", []) if int(x.get("id", -1)) == int(rid)), None)
    if not r: return None
    if r.get("status") == "closed":
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Открыть", callback_data=f"report:reopen:{rid}")]])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Ответить", callback_data=f"report:reply:{rid}"), InlineKeyboardButton(text="✅ Закрыть", callback_data=f"report:close:{rid}")]
    ])

def report_user_label(r):
    u = r.get("user_name") or str(r.get("user_id"))
    un = f" @{r.get('username')}" if r.get("username") else ""
    return escape(u + un)

def report_card(r):
    status = "🟢 Открыт" if r.get("status") != "closed" else "⚫ Закрыт"
    reply = r.get("admin_reply")
    text = (f"📨 <b>Report #{r.get('id')}</b>\n\n"
            f"👤 {report_user_label(r)}\n"
            f"📂 {escape(REPORT_CATEGORIES.get(r.get('category'), r.get('category','Другое')))}\n"
            f"🕐 {escape(str(r.get('created_at','')))}\n"
            f"📌 {status}\n\n"
            f"💬 <b>Сообщение:</b>\n{escape(str(r.get('text','')))}")
    if reply:
        text += f"\n\n↩️ <b>Ответ:</b>\n{escape(str(reply))}"
    return text

def reports_keyboard():
    rows=[]
    reports=sorted(data.get("reports", []), key=lambda x:int(x.get("id",0)), reverse=True)
    for r in reports[:20]:
        status="🟢" if r.get("status") != "closed" else "⚫"
        rows.append([InlineKeyboardButton(text=f"{status} #{r.get('id')} — {REPORT_CATEGORIES.get(r.get('category'),'Другое')[:18]}", callback_data=f"reports:view:{r.get('id')}")])
    rows.append([InlineKeyboardButton(text="◀️ Панель", callback_data="dash:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def send_reports_page(message):
    if not admin_can(message.from_user.id, "reports"):
        await message.answer(permission_denied_text("reports")); return
    reports=data.get("reports", [])
    open_count=sum(1 for r in reports if r.get("status") != "closed")
    await message.answer(f"📨 <b>Report / обращения</b>\n\nВсего: <b>{len(reports)}</b>\nОткрытых: <b>{open_count}</b>\n\nВыберите обращение:", reply_markup=reports_keyboard())

@dp.message(F.text == "📨 Report")
async def report_button(message: Message):
    await message.answer("📨 <b>Связь с администрацией</b>\n\nВыберите тип обращения:", reply_markup=report_menu_keyboard())

@dp.callback_query(F.data.startswith("report:new:"))
async def report_new_cb(cb: CallbackQuery):
    category=cb.data.split(":",2)[2]
    if category not in REPORT_CATEGORIES: return await cb.answer("Ошибка",show_alert=True)
    report_mode[cb.from_user.id]={"category":category}
    await cb.message.edit_text(f"📨 <b>{escape(REPORT_CATEGORIES[category])}</b>\n\nОпишите проблему или предложение одним сообщением.\n\nДля отмены: /cancel_report")
    await cb.answer()

@dp.callback_query(F.data == "report:cancel")
async def report_cancel_cb(cb: CallbackQuery):
    report_mode.pop(cb.from_user.id,None)
    await cb.message.edit_text("❌ Создание обращения отменено.")
    await cb.answer()

@dp.message(Command("cancel_report"))
async def cancel_report_cmd(message: Message):
    report_mode.pop(message.from_user.id,None)
    await message.answer("❌ Обращение отменено.")

@dp.callback_query(F.data.startswith("reports:view:"))
async def report_view_cb(cb: CallbackQuery):
    if not admin_can(cb.from_user.id,"reports"): return await cb.answer(permission_denied_text("reports"),show_alert=True)
    rid=int(cb.data.split(":")[2]); r=next((x for x in data.get("reports",[]) if int(x.get("id",-1))==rid),None)
    if not r: return await cb.answer("Не найдено",show_alert=True)
    await cb.message.edit_text(report_card(r),reply_markup=report_admin_keyboard(rid)); await cb.answer()

@dp.callback_query(F.data.startswith("report:reply:"))
async def report_reply_cb(cb: CallbackQuery):
    if not admin_can(cb.from_user.id,"reports"): return await cb.answer(permission_denied_text("reports"),show_alert=True)
    rid=int(cb.data.split(":")[2]); r=next((x for x in data.get("reports",[]) if int(x.get("id",-1))==rid),None)
    if not r: return await cb.answer("Не найдено",show_alert=True)
    report_mode[cb.from_user.id]={"admin_reply":True,"report_id":rid}
    await cb.message.answer(f"💬 Напишите ответ для пользователя по Report #{rid}.\n\nДля отмены: /cancel_report")
    await cb.answer()

@dp.callback_query(F.data.startswith("report:close:"))
async def report_close_cb(cb: CallbackQuery):
    if not admin_can(cb.from_user.id,"reports"): return await cb.answer(permission_denied_text("reports"),show_alert=True)
    rid=int(cb.data.split(":")[2]); r=next((x for x in data.get("reports",[]) if int(x.get("id",-1))==rid),None)
    if not r: return await cb.answer("Не найдено",show_alert=True)
    r["status"]="closed"; r["closed_at"]=datetime.now().isoformat(timespec="seconds"); r["closed_by"]=cb.from_user.id
    save_data(); audit_record(cb.from_user.id,"commands","закрыл обращение Report",f"#{rid}")
    try: await bot.send_message(int(r["user_id"]),f"📨 Ваш Report <b>#{rid}</b> закрыт администрацией.")
    except Exception: pass
    await cb.message.edit_text(report_card(r),reply_markup=report_admin_keyboard(rid)); await cb.answer("Закрыто")

@dp.callback_query(F.data.startswith("report:reopen:"))
async def report_reopen_cb(cb: CallbackQuery):
    if not admin_can(cb.from_user.id,"reports"): return await cb.answer(permission_denied_text("reports"),show_alert=True)
    rid=int(cb.data.split(":")[2]); r=next((x for x in data.get("reports",[]) if int(x.get("id",-1))==rid),None)
    if not r: return await cb.answer("Не найдено",show_alert=True)
    r["status"]="open"; save_data(); audit_record(cb.from_user.id,"commands","открыл обращение Report",f"#{rid}")
    await cb.message.edit_text(report_card(r),reply_markup=report_admin_keyboard(rid)); await cb.answer("Открыто")

# admin reply handler must run before generic reminder/report handlers
@dp.message(lambda m: m.from_user.id in report_mode and report_mode[m.from_user.id].get("admin_reply") and bool(m.text) and not m.text.startswith("/"))
async def report_admin_reply_handler(message: Message):
    state=report_mode.pop(message.from_user.id,None)
    if not state: return
    if not admin_can(message.from_user.id,"reports"):
        return await message.answer(permission_denied_text("reports"))
    rid=int(state["report_id"]); r=next((x for x in data.get("reports",[]) if int(x.get("id",-1))==rid),None)
    if not r: return await message.answer("❌ Обращение не найдено.")
    reply=message.text.strip()
    if not reply or len(reply)>4000: return await message.answer("❌ Ответ: 1–4000 символов.")
    r["admin_reply"]=reply; r["answered_by"]=message.from_user.id; r["answered_by_name"]=get_admin_display(message.from_user.id); r["status"]="answered"
    save_data(); audit_record(message.from_user.id,"commands","ответил на Report",f"#{rid}")
    try:
        await bot.send_message(int(r["user_id"]), f"💬 <b>Ответ администрации на Report #{rid}</b>\n\n{escape(reply)}")
        sent="Пользователю отправлено."
    except Exception:
        sent="Не удалось отправить пользователю (возможно, он не открыл ЛС с ботом)."
    await message.answer(f"✅ Ответ сохранён. {sent}", reply_markup=reports_keyboard())

@dp.message(lambda m: m.from_user.id in report_mode and bool(m.text) and not m.text.startswith("/"))
async def report_text_handler(message: Message):
    state=report_mode.pop(message.from_user.id,None)
    if not state: return
    text=message.text.strip()
    if not text or len(text)>4000:
        report_mode[message.from_user.id]=state
        return await message.answer("❌ Сообщение должно быть от 1 до 4000 символов.")
    try:
        chat=await bot.get_chat(message.from_user.id)
        username=chat.username or ""
        user_name=chat.full_name or str(message.from_user.id)
    except Exception:
        username=message.from_user.username or ""
        user_name=message.from_user.full_name or str(message.from_user.id)
    rid=_next_report_id()
    report={"id":rid,"user_id":message.from_user.id,"user_name":user_name,"username":username,"category":state["category"],"text":text,"status":"open","created_at":datetime.now().isoformat(timespec="seconds"),"admin_reply":"","answered_by":"","answered_by_name":""}
    data.setdefault("reports",[]).append(report)
    data["report_seq"]=rid
    save_data(); audit_record(message.from_user.id,"commands","создал обращение Report",f"#{rid} {REPORT_CATEGORIES[state['category']]}")
    for admin_id in sorted(get_admins() | {SUPER_ADMIN}):
        try:
            await bot.send_message(admin_id, "📨 <b>Новое обращение</b>\n\n"+report_card(report), reply_markup=report_admin_keyboard(rid))
        except Exception: pass
    await message.answer(f"✅ Обращение <b>#{rid}</b> отправлено администрации.\n\nАдминистратор сможет ответить вам прямо через бота.")

# =========================================================
# ЕЖЕДНЕВНЫЕ НАПОМИНАНИЯ
# =========================================================

reminder_mode = {}

REMINDER_TARGETS = {
    "group": "👥 Группа",
    "topic": "🧵 Конкретная тема",
    "dm": "👤 ЛС всем участникам",
}

TIMEZONES = {
    "Europe/Moscow": "🇷🇺 Москва (МСК)",
    "Europe/Kaliningrad": "🇷🇺 Калининград",
    "Europe/Samara": "🇷🇺 Самара",
    "Europe/Volgograd": "🇷🇺 Волгоград",
    "Asia/Yekaterinburg": "🇷🇺 Екатеринбург",
    "Asia/Omsk": "🇷🇺 Омск",
    "Asia/Novosibirsk": "🇷🇺 Новосибирск",
    "Asia/Krasnoyarsk": "🇷🇺 Красноярск",
    "Asia/Irkutsk": "🇷🇺 Иркутск",
    "Asia/Yakutsk": "🇷🇺 Якутск",
    "Asia/Vladivostok": "🇷🇺 Владивосток",
    "Asia/Magadan": "🇷🇺 Магадан",
    "Asia/Kamchatka": "🇷🇺 Камчатка",
    "Europe/Berlin": "🇩🇪 Берлин",
}


def _next_reminder_id():
    ids = []
    for r in data.get("reminders", []):
        try: ids.append(int(r.get("id", 0)))
        except Exception: pass
    return max(ids, default=0) + 1


def _reminder_by_id(rid):
    try: rid = int(rid)
    except Exception: return None
    for r in data.get("reminders", []):
        try:
            if int(r.get("id", -1)) == rid: return r
        except Exception: pass
    return None


def _valid_hhmm(value):
    return bool(re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value.strip()))


def _bot_timezone_name():
    return str(data.setdefault("bot_settings", {}).get("timezone") or "Europe/Moscow")


def _bot_timezone_label():
    name = _bot_timezone_name()
    return TIMEZONES.get(name, name)


def reminder_draft_text(state):
    target = REMINDER_TARGETS.get(state.get("target", "group"), "👥 Группа")
    mention = "🔔 Да" if state.get("mention_all") else "🔕 Нет"
    topic = f"\n🧵 ID темы: <code>{escape(str(state.get('topic_id')))}</code>" if state.get("target") == "topic" and state.get("topic_id") else ""
    return (
        "➕ <b>Создание напоминания</b>\n\n"
        f"📝 Название: <b>{escape(str(state.get('name') or '—'))}</b>\n"
        f"💬 Текст: {escape(str(state.get('text') or '—'))}\n"
        f"⏰ Время: <code>{escape(str(state.get('time') or '--:--'))}</code>\n"
        f"📍 Куда: {target}{topic}\n"
        f"🔔 Упоминать всех: {mention}\n"
        f"🌍 Часовой пояс: <b>{escape(_bot_timezone_label())}</b>\n\n"
        "📢 <b>Предпросмотр сообщения:</b>\n"
        f"<blockquote>{escape(str(state.get('text') or '—'))}</blockquote>\n\n"
        "Проверь настройки и сохрани напоминание."
    )

def reminder_draft_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Название", callback_data="remdraft:name"), InlineKeyboardButton(text="💬 Текст", callback_data="remdraft:text")],
        [InlineKeyboardButton(text="⏰ Время", callback_data="remdraft:time"), InlineKeyboardButton(text="📍 Куда", callback_data="remdraft:target")],
        [InlineKeyboardButton(text="🔔 Упоминать всех", callback_data="remdraft:mention")],
        [InlineKeyboardButton(text="🌍 Часовой пояс", callback_data="remdraft:timezone")],
        [InlineKeyboardButton(text="💾 Сохранить", callback_data="remdraft:save")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="remdraft:cancel")],
    ])

def reminders_text():
    reminders = data.get("reminders", [])
    lines = ["🔔 <b>Напоминания</b>", "", f"⏰ Часовой пояс: <b>{escape(_bot_timezone_label())}</b>", ""]
    if not reminders:
        lines.append("📭 Пока нет ни одного напоминания.")
    else:
        for r in sorted(reminders, key=lambda x: x.get("time", "99:99")):
            status = "🟢" if r.get("enabled", True) else "🔴"
            target = REMINDER_TARGETS.get(r.get("target", "group"), "👥 Группа")
            mention = " • 🔔 всех" if r.get("mention_all") else ""
            lines.append(f"{status} <b>{escape(str(r.get('name','Без названия')))}</b> — <code>{escape(str(r.get('time','--:--')))}</code>")
            lines.append(f"   {target}{mention}")
            lines.append(f"   {escape(str(r.get('text',''))[:140])}")
            lines.append("")
    return "\n".join(lines)


def reminders_keyboard():
    rows = []
    for r in sorted(data.get("reminders", []), key=lambda x: x.get("time", "99:99")):
        rid = int(r.get("id", 0)); status = "🟢" if r.get("enabled", True) else "🔴"
        name = str(r.get("name", "Без названия"))[:24]
        rows.append([InlineKeyboardButton(text=f"{status} {name} — {r.get('time','--:--')}", callback_data=f"rem:view:{rid}")])
    rows.append([InlineKeyboardButton(text="➕ Создать", callback_data="rem:create"), InlineKeyboardButton(text="⏰ Часовой пояс", callback_data="rem:timezone")])
    rows.append([InlineKeyboardButton(text="◀️ Панель", callback_data="dash:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reminder_edit_keyboard(rid):
    r = _reminder_by_id(rid)
    if not r: return reminders_keyboard()
    enabled = "⏸ Выключить" if r.get("enabled", True) else "▶️ Включить"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Название", callback_data=f"rem:name:{rid}"), InlineKeyboardButton(text="💬 Текст", callback_data=f"rem:text:{rid}")],
        [InlineKeyboardButton(text="🕐 Время", callback_data=f"rem:time:{rid}"), InlineKeyboardButton(text="📍 Куда", callback_data=f"rem:target:{rid}")],
        [InlineKeyboardButton(text="🔔 Упоминать всех", callback_data=f"rem:mention:{rid}")],
        [InlineKeyboardButton(text=enabled, callback_data=f"rem:toggle:{rid}")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"rem:delete:{rid}")],
        [InlineKeyboardButton(text="◀️ К списку", callback_data="rem:menu")],
    ])


def reminder_card(r):
    status = "🟢 включено" if r.get("enabled", True) else "🔴 выключено"
    target = REMINDER_TARGETS.get(r.get("target", "group"), "👥 Группа")
    extra = "\n🔔 Упоминание всех: <b>да</b>" if r.get("mention_all") else "\n🔔 Упоминание всех: <b>нет</b>"
    if r.get("target") == "topic": extra += f"\n🧵 ID темы: <code>{escape(str(r.get('topic_id','')))}</code>"
    return (f"🔔 <b>{escape(str(r.get('name','Без названия')))}</b>\n\n"
            f"💬 {escape(str(r.get('text','')))}\n\n"
            f"🕐 Каждый день в <code>{escape(str(r.get('time','--:--')))}</code>\n"
            f"📍 {target}{extra}\n"
            f"⏰ Часовой пояс: <b>{escape(_bot_timezone_label())}</b>\n"
            f"📌 Статус: {status}")


def reminder_target_keyboard(rid, creating=False):
    prefix = "remnewtarget" if creating else f"remtarget:{rid}"
    rows = [
        [InlineKeyboardButton(text="👥 Группа", callback_data=f"{prefix}:group")],
        [InlineKeyboardButton(text="🧵 Конкретная тема", callback_data=f"{prefix}:topic")],
        [InlineKeyboardButton(text="👤 ЛС всем участникам", callback_data=f"{prefix}:dm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="rem:menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reminder_mention_keyboard(rid=None):
    prefix = "remnewmention" if rid is None else f"remmentionset:{rid}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔔 Да, упоминать всех", callback_data=f"{prefix}:yes")],
        [InlineKeyboardButton(text="🔕 Нет", callback_data=f"{prefix}:no")],
    ])


def timezone_keyboard():
    rows=[]
    items=list(TIMEZONES.items())
    for i in range(0,len(items),2):
        row=[]
        for name,label in items[i:i+2]:
            row.append(InlineKeyboardButton(text=label, callback_data=f"remtz:{name}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="rem:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.message(F.text == "🔔 Напоминания")
async def reminders_btn(message: Message):
    if not admin_can(message.from_user.id, "reminders"):
        await message.answer(permission_denied_text("reminders")); return
    await message.answer(reminders_text(), reply_markup=reminders_keyboard())


@dp.callback_query(F.data.startswith("remtz:"))
async def reminder_timezone_cb(cb: CallbackQuery):
    if not admin_can(cb.from_user.id, "reminders"):
        return await cb.answer(permission_denied_text("reminders"), show_alert=True)
    tz = cb.data.split(":",1)[1]
    if tz not in TIMEZONES:
        return await cb.answer("Неизвестный часовой пояс", show_alert=True)
    data.setdefault("bot_settings", {})["timezone"] = tz
    save_data()
    if cb.from_user.id in reminder_mode and reminder_mode[cb.from_user.id].get("step") not in {"edit_name","edit_text","edit_time","edit_topic"}:
        await cb.message.edit_text(reminder_draft_text(reminder_mode[cb.from_user.id]), reply_markup=reminder_draft_keyboard())
    else:
        await cb.message.edit_text(reminders_text(), reply_markup=reminders_keyboard())
    await cb.answer("Часовой пояс сохранён")


@dp.callback_query(F.data.startswith("rem:"))
async def reminders_cb(cb: CallbackQuery):
    if not admin_can(cb.from_user.id, "reminders"):
        return await cb.answer(permission_denied_text("reminders"), show_alert=True)
    parts = cb.data.split(":")
    action = parts[1] if len(parts)>1 else "menu"

    if action == "menu":
        await cb.message.edit_text(reminders_text(), reply_markup=reminders_keyboard()); return await cb.answer()
    if action == "timezone":
        await cb.message.edit_text("⏰ <b>Часовой пояс бота</b>\n\nВыбери, по какому времени должны срабатывать ежедневные напоминания:", reply_markup=timezone_keyboard()); return await cb.answer()
    if action == "create":
        reminder_mode[cb.from_user.id] = {"step":"name"}
        await cb.message.edit_text("➕ <b>Создание напоминания</b>\n\nСначала напиши название.\nНапример: <b>Утренний сбор</b>\n\nПосле заполнения будет показан полный предпросмотр.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="rem:menu")]]))
        return await cb.answer()

    if len(parts) < 3: return await cb.answer()
    try: rid=int(parts[2])
    except Exception: return await cb.answer("Ошибка", show_alert=True)
    r=_reminder_by_id(rid)
    if not r: return await cb.answer("Напоминание не найдено", show_alert=True)

    if action == "view":
        await cb.message.edit_text(reminder_card(r), reply_markup=reminder_edit_keyboard(rid)); return await cb.answer()
    if action == "name":
        reminder_mode[cb.from_user.id]={"step":"edit_name","id":rid}; await cb.message.answer("✏️ Напиши новое название.\nДля отмены: /cancel"); return await cb.answer()
    if action == "text":
        reminder_mode[cb.from_user.id]={"step":"edit_text","id":rid}; await cb.message.answer("💬 Напиши новый текст.\nДля отмены: /cancel"); return await cb.answer()
    if action == "time":
        reminder_mode[cb.from_user.id]={"step":"edit_time","id":rid}; await cb.message.answer("🕐 Новое время в формате <code>HH:MM</code>.\nНапример: <code>18:30</code>"); return await cb.answer()
    if action == "target":
        await cb.message.edit_text("📍 <b>Куда отправлять?</b>", reply_markup=reminder_target_keyboard(rid)); return await cb.answer()
    if action == "mention":
        r["mention_all"] = not bool(r.get("mention_all"))
        save_data(); await cb.message.edit_text(reminder_card(r), reply_markup=reminder_edit_keyboard(rid)); return await cb.answer("Изменено")
    if action == "toggle":
        r["enabled"]=not bool(r.get("enabled",True)); r["last_sent_date"]=None; save_data()
        await cb.message.edit_text(reminder_card(r), reply_markup=reminder_edit_keyboard(rid)); return await cb.answer("Статус изменён")
    if action == "delete":
        data["reminders"]=[x for x in data.get("reminders",[]) if int(x.get("id",-1))!=rid]; save_data()
        await cb.message.edit_text(reminders_text(), reply_markup=reminders_keyboard()); return await cb.answer("Удалено")


@dp.callback_query(F.data.startswith("remdraft:"))
async def reminder_draft_cb(cb: CallbackQuery):
    if not admin_can(cb.from_user.id, "reminders"):
        return await cb.answer(permission_denied_text("reminders"), show_alert=True)
    state = reminder_mode.get(cb.from_user.id)
    if not state:
        return await cb.answer("Черновик не найден", show_alert=True)
    action = cb.data.split(":",1)[1]
    if action == "save":
        if not state.get("name") or not state.get("text") or not _valid_hhmm(str(state.get("time",""))):
            return await cb.answer("Заполни название, текст и время", show_alert=True)
        rid=_next_reminder_id()
        data.setdefault("reminders",[]).append({"id":rid,"name":state["name"],"text":state["text"],"time":state["time"],"enabled":True,"target":state.get("target","group"),"topic_id":state.get("topic_id"),"mention_all":bool(state.get("mention_all")),"last_sent_date":None,"created_by":cb.from_user.id,"created_at":datetime.now().isoformat(timespec="seconds")})
        save_data(); audit_record(cb.from_user.id,"commands","создал ежедневное напоминание",f"{state['name']} — {state['time']}")
        reminder_mode.pop(cb.from_user.id,None)
        await cb.message.edit_text("✅ <b>Напоминание сохранено!</b>\n\n"+reminders_text(), reply_markup=reminders_keyboard())
        return await cb.answer("Сохранено")
    if action == "cancel":
        reminder_mode.pop(cb.from_user.id,None)
        await cb.message.edit_text(reminders_text(), reply_markup=reminders_keyboard())
        return await cb.answer("Отменено")
    if action == "name":
        state["step"]="draft_name"; await cb.message.answer("📝 Напиши новое название для черновика."); return await cb.answer()
    if action == "text":
        state["step"]="draft_text"; await cb.message.answer("💬 Напиши текст сообщения для черновика."); return await cb.answer()
    if action == "time":
        state["step"]="draft_time"; await cb.message.answer("⏰ Напиши время в формате <code>HH:MM</code>."); return await cb.answer()
    if action == "target":
        await cb.message.edit_text("📍 <b>Куда отправлять?</b>", reply_markup=reminder_target_keyboard(0, creating=True)); return await cb.answer()
    if action == "mention":
        await cb.message.edit_text("🔔 <b>Упоминать всех участников?</b>", reply_markup=reminder_mention_keyboard()); return await cb.answer()
    if action == "timezone":
        await cb.message.edit_text("🌍 <b>Часовой пояс</b>", reply_markup=timezone_keyboard()); return await cb.answer()
    return await cb.answer()

@dp.callback_query(F.data == "remdraft:preview")
async def reminder_draft_preview_cb(cb: CallbackQuery):
    state=reminder_mode.get(cb.from_user.id)
    if not state: return await cb.answer("Черновик не найден",show_alert=True)
    await cb.message.edit_text(reminder_draft_text(state), reply_markup=reminder_draft_keyboard()); await cb.answer()

@dp.callback_query(F.data.startswith("remtarget:"))
async def reminder_target_cb(cb: CallbackQuery):
    if not admin_can(cb.from_user.id,"reminders"): return await cb.answer("❌ Нет прав",show_alert=True)
    _,rid,target=cb.data.split(":",2); r=_reminder_by_id(rid)
    if not r: return await cb.answer("Не найдено",show_alert=True)
    if target not in REMINDER_TARGETS: return await cb.answer("Ошибка",show_alert=True)
    r["target"]=target
    if target != "topic": r.pop("topic_id",None)
    save_data()
    if target == "topic":
        reminder_mode[cb.from_user.id]={"step":"edit_topic","id":int(rid)}
        await cb.message.answer("🧵 Напиши <b>ID темы</b> (message_thread_id).\nЕго можно получить командой /topic_id в нужной теме.\nДля отмены: /cancel")
    else:
        await cb.message.edit_text(reminder_card(r), reply_markup=reminder_edit_keyboard(int(rid)))
    await cb.answer("Место отправки изменено")


@dp.callback_query(F.data.startswith("remnewtarget:"))
async def reminder_new_target_cb(cb: CallbackQuery):
    if not admin_can(cb.from_user.id,"reminders"): return await cb.answer("❌ Нет прав",show_alert=True)
    target=cb.data.split(":",1)[1]
    if target not in REMINDER_TARGETS: return await cb.answer("Ошибка",show_alert=True)
    state=reminder_mode.get(cb.from_user.id)
    if not state: return await cb.answer("Создание уже отменено",show_alert=True)
    state["target"]=target
    if target=="topic":
        state["step"]="topic"
        await cb.message.edit_text("🧵 <b>Шаг 4/5</b> — напиши ID темы (message_thread_id).\nНапример: <code>126387</code>\nДля отмены: /cancel")
    else:
        state["step"]="mention"
        await cb.message.edit_text("🔔 <b>Упоминать всех участников?</b>", reply_markup=reminder_mention_keyboard())
    await cb.answer()


@dp.callback_query(F.data.startswith("remnewmention:"))
async def reminder_new_mention_cb(cb: CallbackQuery):
    if not admin_can(cb.from_user.id,"reminders"): return await cb.answer("❌ Нет прав",show_alert=True)
    choice=cb.data.split(":",1)[1]; state=reminder_mode.get(cb.from_user.id)
    if not state: return await cb.answer("Создание уже отменено",show_alert=True)
    state["mention_all"]=(choice=="yes"); state["step"]="time"
    await cb.message.edit_text("⏰ <b>Теперь укажи время</b> в формате <code>HH:MM</code>.\nНапример: <code>20:30</code>")
    await cb.answer()


@dp.callback_query(F.data.startswith("remmentionset:"))
async def reminder_mention_set_cb(cb: CallbackQuery):
    if not admin_can(cb.from_user.id,"reminders"): return await cb.answer("❌ Нет прав",show_alert=True)
    _,rid,choice=cb.data.split(":",2); r=_reminder_by_id(rid)
    if not r: return await cb.answer("Не найдено",show_alert=True)
    r["mention_all"]=(choice=="yes"); save_data()
    await cb.message.edit_text(reminder_card(r),reply_markup=reminder_edit_keyboard(int(rid))); await cb.answer("Сохранено")


@dp.message(Command("cancel"))
async def reminder_cancel_cmd(message: Message):
    if message.from_user.id in reminder_mode:
        reminder_mode.pop(message.from_user.id,None)
        await message.answer("❌ Действие отменено.", reply_markup=reminders_keyboard() if admin_can(message.from_user.id,"reminders") else None)


@dp.message(lambda m: m.from_user.id in reminder_mode and bool(m.text) and not m.text.startswith("/"))
async def reminder_text_handler(message: Message):
    if not admin_can(message.from_user.id,"reminders"):
        reminder_mode.pop(message.from_user.id,None); return
    state=reminder_mode.get(message.from_user.id,{}); step=state.get("step"); value=message.text.strip()

    if step=="draft_name":
        if not 1<=len(value)<=100: return await message.answer("❌ Название: 1–100 символов.")
        state["name"]=value; state["step"]="preview"
        return await message.answer(reminder_draft_text(state), reply_markup=reminder_draft_keyboard())
    if step=="draft_text":
        if not 1<=len(value)<=4000: return await message.answer("❌ Текст: 1–4000 символов.")
        state["text"]=value; state["step"]="preview"
        return await message.answer(reminder_draft_text(state), reply_markup=reminder_draft_keyboard())
    if step=="draft_time":
        if not _valid_hhmm(value): return await message.answer("❌ Время должно быть в формате <code>HH:MM</code>.")
        state["time"]=value; state["step"]="preview"
        return await message.answer(reminder_draft_text(state), reply_markup=reminder_draft_keyboard())
    if step=="name":
        if not 1<=len(value)<=100: return await message.answer("❌ Название: 1–100 символов.")
        state["name"]=value; state["step"]="text"
        return await message.answer("💬 <b>Шаг 2/5</b> — напиши текст сообщения.")
    if step=="text":
        if not 1<=len(value)<=4000: return await message.answer("❌ Текст: 1–4000 символов.")
        state["text"]=value; state["step"]="target"
        return await message.answer("📍 <b>Шаг 3/5</b> — выбери место отправки:",reply_markup=reminder_target_keyboard(0,creating=True))
    if step=="topic":
        if not value.isdigit() or int(value)<=0: return await message.answer("❌ ID темы должен быть положительным числом.")
        state["topic_id"]=int(value); state["step"]="mention"
        return await message.answer("🔔 <b>Упоминать всех участников?</b>",reply_markup=reminder_mention_keyboard())
    if step=="time":
        if not _valid_hhmm(value): return await message.answer("❌ Время должно быть в формате <code>HH:MM</code>.")
        state["time"] = value
        state["step"] = "preview"
        return await message.answer(reminder_draft_text(state), reply_markup=reminder_draft_keyboard())

    rid=state.get("id"); r=_reminder_by_id(rid)
    if not r:
        reminder_mode.pop(message.from_user.id,None); return await message.answer("❌ Напоминание уже удалено.")
    if step=="edit_name":
        if not 1<=len(value)<=100: return await message.answer("❌ Название: 1–100 символов.")
        r["name"]=value
    elif step=="edit_text":
        if not 1<=len(value)<=4000: return await message.answer("❌ Текст: 1–4000 символов.")
        r["text"]=value
    elif step=="edit_time":
        if not _valid_hhmm(value): return await message.answer("❌ Время должно быть в формате <code>HH:MM</code>.")
        r["time"]=value; r["last_sent_date"]=None
    elif step=="edit_topic":
        if not value.isdigit() or int(value)<=0: return await message.answer("❌ ID темы должен быть положительным числом.")
        r["topic_id"]=int(value)
    else: return
    save_data(); reminder_mode.pop(message.from_user.id,None)
    audit_record(message.from_user.id,"commands","изменил ежедневное напоминание",f"{r.get('name')} — {r.get('time')}")
    await message.answer("✅ Изменения сохранены.",reply_markup=reminders_keyboard())


async def _reminder_members():
    try:
        members=await get_gather_members()
        if members: return members
    except Exception as e:
        print("⚠️ Не удалось получить участников для напоминания:",e)
    members=[]
    seen=set()
    for uid,info in data.get("group_members",{}).items():
        try: iid=int(uid)
        except Exception: continue
        if iid in seen: continue
        if info.get("status") in {"left","kicked"}: continue
        name=info.get("full_name") or info.get("username") or str(iid)
        members.append({"id":iid,"name":name,"username":info.get("username")}); seen.add(iid)
    for uid,info in data.get("users",{}).items():
        try: iid=int(uid)
        except Exception: continue
        if iid in seen: continue
        members.append({"id":iid,"name":info.get("nickname") or info.get("tag") or str(iid),"username":str(info.get("tag","")).lstrip("@") or None}); seen.add(iid)
    return members


def _mention(member):
    return f'<a href="tg://user?id={int(member["id"])}">{escape(str(member.get("name") or member.get("username") or member["id"]))}</a>'


async def send_scheduled_reminder(r):
    target=r.get("target","group")
    mention_all=bool(r.get("mention_all"))
    base=str(r.get("text", ""))
    topic_id=r.get("topic_id")
    if target in ("group","topic"):
        kwargs={}
        if target=="topic": kwargs["message_thread_id"]=int(topic_id)
        if mention_all:
            members=await _reminder_members()
            mentions=" ".join(_mention(m) for m in members)
            if mentions:
                # Telegram message limit — разбиваем упоминания на несколько сообщений.
                chunks=[]; cur=base+"\n\n"; limit=3800
                for m in mentions.split(" "):
                    if len(cur)+len(m)+1>limit:
                        chunks.append(cur); cur=m+" "
                    else: cur+=m+" "
                if cur.strip(): chunks.append(cur)
                for chunk in chunks:
                    await bot.send_message(GROUP_ID,chunk,**kwargs)
            else:
                await bot.send_message(GROUP_ID,base,**kwargs)
        else:
            await bot.send_message(GROUP_ID,base,**kwargs)
        return True
    if target=="dm":
        members=await _reminder_members()
        ok=0
        for member in members:
            text=base
            if mention_all: text += "\n\n"+_mention(member)
            try:
                await bot.send_message(int(member["id"]),text); ok+=1; await asyncio.sleep(0.06)
            except Exception: pass
        return ok>0
    return False


async def scheduled_reminder_worker():
    """Ежедневный планировщик с часовым поясом, заданным в самом боте."""
    from zoneinfo import ZoneInfo
    while True:
        try:
            tz_name=_bot_timezone_name()
            try: tz=ZoneInfo(tz_name)
            except Exception: tz=ZoneInfo("Europe/Moscow")
            now=datetime.now(tz); hhmm=now.strftime("%H:%M"); today=now.strftime("%Y-%m-%d")
            changed=False
            for r in list(data.get("reminders",[])):
                if not r.get("enabled",True) or str(r.get("time",""))!=hhmm or r.get("last_sent_date")==today: continue
                try:
                    if await send_scheduled_reminder(r):
                        r["last_sent_date"]=today; changed=True
                        audit_record(SUPER_ADMIN,"commands","автоматически отправил ежедневное напоминание",str(r.get("name","")),command="scheduler")
                except Exception as e:
                    print(f"⚠️ Не удалось отправить напоминание {r.get('id')}: {e}")
                    await _send_error_report(e, f"Автоматическое напоминание #{r.get('id')}")
            if changed: save_data()
            await asyncio.sleep(max(1,61-datetime.now(tz).second))
        except asyncio.CancelledError: return
        except Exception as e:
            print("scheduled_reminder_worker:",e); await asyncio.sleep(30)

# Выбор направления объявления.
@dp.callback_query(F.data.startswith("announce_target:"))
async def announcement_target_cb(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return await cb.answer("❌ Нет прав", show_alert=True)
    target = cb.data.split(":",1)[1]
    if target == "cancel":
        announcement_mode.pop(cb.from_user.id, None)
        await cb.message.edit_text("❌ Создание объявления отменено.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Панель", callback_data="dash:home")]]))
        return await cb.answer("Отменено")
    announcement_mode[cb.from_user.id] = {"target": target}
    labels = {"dm":"👤 только в ЛС участникам", "group":"👥 только в группу", "all":"📢 в ЛС + группу"}
    await cb.message.edit_text(
        f"📣 Выбрано: <b>{labels.get(target, target)}</b>\n\nНапишите текст объявления одним сообщением.\nДля отмены: /cancel"
    )
    await cb.answer("Выбрано")

# Объявление через кнопку.
@dp.message(lambda m: m.from_user.id in announcement_mode and bool(m.text) and not m.text.startswith("/"))
async def announcement_text_handler(message: Message):
    if not is_admin(message.from_user.id): return
    mode = announcement_mode.pop(message.from_user.id, {})
    target = mode.get("target", "group")
    text = message.text
    sent_group = False
    dm_sent = 0
    dm_failed = 0
    try:
        if target in ("group", "all"):
            sent = await bot.send_message(GROUP_ID, text, message_thread_id=ANNOUNCE_TOPIC_ID)
            sent_group = True
            if data.setdefault("bot_settings",{}).get("pin_announcements"):
                try: await bot.pin_chat_message(GROUP_ID, sent.message_id, disable_notification=True)
                except Exception: pass

        if target in ("dm", "all"):
            members = data.get("group_members", {})
            active_statuses = {"member", "administrator", "creator", "restricted"}
            for uid, info in list(members.items()):
                if info.get("status") not in active_statuses:
                    continue
                try:
                    await bot.send_message(int(uid), text)
                    dm_sent += 1
                    await asyncio.sleep(0.05)
                except Exception:
                    dm_failed += 1

        audit_record(message.from_user.id,"commands","отправил объявление",text,command=f"кнопка: объявление:{target}")
        parts=[]
        if sent_group: parts.append("в группу")
        if target in ("dm", "all"): parts.append(f"в ЛС: {dm_sent} отправлено")
        if dm_failed: parts.append(f"ошибок ЛС: {dm_failed}")
        await message.answer("✅ Объявление отправлено — " + ", ".join(parts) + ".")
    except Exception as e:
        await _send_error_report(e, "Отправка объявления")
        await message.answer("❌ Не удалось отправить объявление. Подробная ошибка отправлена владельцу.")

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

# =========================================================
# ОБЩИЙ СБОР — с реальными упоминаниями и кнопкой ОСТАНОВИТЬ
# =========================================================

gather_tasks = {}
gather_active = set()


def _gather_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛑 Остановить сбор", callback_data="gather:stop")]
    ])


def _mention_user(uid, info):
    name = str(
        info.get("full_name")
        or info.get("nickname")
        or info.get("tag")
        or uid
    ).strip()
    return f'<a href="tg://user?id={int(uid)}">{escape(name[:60])}</a>'


def _gather_members():
    result = {}
    # Сначала реальные участники группы — можно упомянуть даже без username.
    for uid, info in data.get("group_members", {}).items():
        try:
            if str(info.get("status", "member")) not in {"member", "administrator", "creator", "restricted"}:
                continue
            result[str(uid)] = info
        except Exception:
            continue

    # Дополняем пользователями, которых бот знает по анкетам.
    for uid, info in data.get("users", {}).items():
        result.setdefault(str(uid), {
            "full_name": info.get("full_name") or info.get("nickname") or info.get("tag") or str(uid),
            "username": info.get("tag"),
            "status": "member",
        })

    return list(result.items())


async def _run_gather(owner_id, control_message):
    try:
        members = _gather_members()
        if not members:
            await control_message.answer("❌ Бот пока не знает участников группы.")
            return

        # Разбиваем на небольшие сообщения, чтобы Telegram не отклонял длинное сообщение.
        batch_size = 15
        total = len(members)

        for pos in range(0, total, batch_size):
            if owner_id not in gather_active:
                await control_message.answer("🛑 <b>Общий сбор остановлен.</b>")
                return

            batch = members[pos:pos + batch_size]
            mentions = " ".join(_mention_user(uid, info) for uid, info in batch)
            text = (
                "📢 <b>ОБЩИЙ СБОР!</b>\n\n"
                f"{mentions}\n\n"
                f"📋 Участники: {pos + len(batch)}/{total}"
            )

            await bot.send_message(
                GROUP_ID,
                text,
                message_thread_id=ANNOUNCE_TOPIC_ID,
                reply_markup=_gather_keyboard() if pos + len(batch) < total else None,
            )

            if pos + batch_size < total:
                # Около 1–2 минут на большой сбор.
                await asyncio.sleep(5)

        await control_message.answer(f"✅ <b>Общий сбор завершён.</b>\nУпомянуто: {total}")
        audit_record(owner_id, "commands", "запустил общий сбор", f"Упомянуто: {total}", command="кнопка: общий сбор")
    except asyncio.CancelledError:
        return
    except Exception as e:
        await _send_error_report(e, "Общий сбор")
        try:
            await control_message.answer("❌ <b>Общий сбор не удалось выполнить.</b>\nОшибка отправлена владельцу.")
        except Exception:
            pass
    finally:
        gather_active.discard(owner_id)
        gather_tasks.pop(owner_id, None)


async def start_gather_from_button(message: Message):
    uid = message.from_user.id
    if not admin_can(uid, "gathering"):
        return await message.answer(permission_denied_text("gathering"))

    if uid in gather_active:
        return await message.answer(
            "⚠️ <b>Общий сбор уже идёт.</b>\nОстановить его можно кнопкой «🛑 Остановить сбор»."
        )

    gather_active.add(uid)
    task = asyncio.create_task(_run_gather(uid, message))
    gather_tasks[uid] = task

    await message.answer(
        "📢 <b>Общий сбор запущен.</b>\n"
        "Бот начал отправлять реальные упоминания участников в тему объявлений.",
        reply_markup=_gather_keyboard(),
    )


@dp.callback_query(F.data == "gather:stop")
async def gather_stop_cb(cb: CallbackQuery):
    uid = cb.from_user.id
    if not admin_can(uid, "gathering"):
        return await cb.answer(permission_denied_text("gathering"), show_alert=True)

    task = gather_tasks.get(uid)
    gather_active.discard(uid)

    if task and not task.done():
        task.cancel()

    await cb.answer("🛑 Сбор остановлен")
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await cb.message.answer("🛑 <b>Общий сбор остановлен.</b>")


@dp.message(F.text == "🛑 Остановить сбор")
async def gather_stop_btn(message: Message):
    uid = message.from_user.id
    if not admin_can(uid, "gathering"):
        await message.answer(permission_denied_text("gathering"))
        return

    task = gather_tasks.get(uid)
    gather_active.discard(uid)
    if task and not task.done():
        task.cancel()
    await message.answer("🛑 <b>Общий сбор остановлен.</b>")


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
        except Exception as e:
            print("reminder_worker:", e)
            await _send_error_report(e, "Фоновое напоминание анкет")

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

    try:
        asyncio.get_running_loop().set_exception_handler(_asyncio_error_handler)
    except Exception as e:
        print("⚠️ Не удалось установить обработчик asyncio:", repr(e))

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
    ensure_admin_permissions()
    await set_command_scopes()

    await bot.delete_webhook(drop_pending_updates=True)

    print("🤖 Бот запущен!")
    print("📌 Основная группа:", GROUP_LINK)

    asyncio.create_task(reminder_worker())
    asyncio.create_task(scheduled_reminder_worker())
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Бот остановлен.")
    except Exception as e:
        print("❌ Критическая ошибка запуска:", repr(e))
        try:
            asyncio.run(_send_error_report(e, "Критическая ошибка запуска"))
        except Exception as report_exc:
            print("❌ Не удалось отправить отчёт:", repr(report_exc))
