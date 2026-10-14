import os
import re
import json
import time
import asyncio
import logging
import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from typing import Optional

from flask import Flask

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

import asyncpg

# Google Sheets
try:
    import gspread
    from google.oauth2.service_account import Credentials
    GOOGLE_AVAILABLE = True
except Exception:
    GOOGLE_AVAILABLE = False


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

GROUP_ID = int(os.getenv("GROUP_ID", "-1002409536359"))

ANNOUNCE_TOPIC_ID = int(os.getenv("ANNOUNCE_TOPIC_ID", "126387"))

TOPIC_ID = int(os.getenv("TOPIC_ID", str(ANNOUNCE_TOPIC_ID)))

OWNER_ID = 6166697485

BOT_NAME = "@Staff_Grand_Bot"

GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_JSON", ""
).strip()

GOOGLE_SHEET_ID = os.getenv(
    "GOOGLE_SHEET_ID", ""
).strip()

TIMEZONE = os.getenv(
    "BOT_TIMEZONE",
    "Europe/Moscow"
).strip()

PORT = int(os.getenv("PORT", "8000"))


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("staff-grand-bot")


# ============================================================
# FLASK
# ============================================================

flask_app = Flask(__name__)


@flask_app.route("/")
def health():
    return "Bot is running!"


@flask_app.route("/health")
def health2():
    return "OK"


def run_flask():
    try:
        flask_app.run(
            host="0.0.0.0",
            port=PORT,
            use_reloader=False
        )
    except Exception as e:
        logger.error("Flask failed: %s", e)


# ============================================================
# BOT / DISPATCHER
# ============================================================

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан в Render Environment")

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher(storage=MemoryStorage())


# ============================================================
# DATABASE
# ============================================================

db_pool: Optional[asyncpg.Pool] = None


async def db_init():
    global db_pool

    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL не задан. "
            "Для этого бота нужна PostgreSQL база."
        )

    database_dsn = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    parsed_dsn = urlsplit(database_dsn)
    dsn_params = parse_qsl(parsed_dsn.query, keep_blank_values=True)
    sslmode = next((v for k, v in dsn_params if k == "sslmode"), None)
    dsn_params = [(k, v) for k, v in dsn_params if k != "sslmode"]
    database_dsn = urlunsplit((
        parsed_dsn.scheme, parsed_dsn.netloc, parsed_dsn.path,
        urlencode(dsn_params), parsed_dsn.fragment
    ))
    pool_options = {"min_size": 1, "max_size": 5}
    if sslmode and sslmode.lower() not in {"disable", "allow", "prefer"}:
        pool_options["ssl"] = "require"
    db_pool = await asyncpg.create_pool(database_dsn, **pool_options)

    async with db_pool.acquire() as conn:

        # ---------- bot_users ----------
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        # Миграции для случая, когда таблица была создана в старой версии.
        for column, definition in (
            ("username", "TEXT"),
            ("first_name", "TEXT"),
            ("last_name", "TEXT"),
            ("created_at", "TIMESTAMPTZ DEFAULT NOW()"),
            ("updated_at", "TIMESTAMPTZ DEFAULT NOW()"),
        ):
            await conn.execute(
                f"ALTER TABLE bot_users ADD COLUMN IF NOT EXISTS {column} {definition}"
            )

        # ---------- admins ----------
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                is_owner BOOLEAN DEFAULT FALSE,
                can_applications BOOLEAN DEFAULT TRUE,
                can_announcements BOOLEAN DEFAULT TRUE,
                can_reports BOOLEAN DEFAULT TRUE,
                can_reminders BOOLEAN DEFAULT TRUE,
                can_gather BOOLEAN DEFAULT TRUE,
                can_admins BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # ---------- applications ----------
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                username TEXT,
                nickname TEXT,
                family_rank TEXT,
                organization TEXT,
                organization_rank TEXT,
                inviter TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # ---------- reports ----------
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                username TEXT,
                text TEXT,
                status TEXT DEFAULT 'new',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # ---------- reminders ----------
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                message TEXT NOT NULL,
                time TEXT NOT NULL,
                destination TEXT DEFAULT 'group',
                topic_id BIGINT,
                user_id BIGINT,
                mention_all BOOLEAN DEFAULT FALSE,
                enabled BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # ---------- bot_logs ----------
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_logs (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                username TEXT,
                action TEXT,
                details TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # ---------- миграции admins ----------
        for column, definition in (
            ("username", "TEXT"),
            ("is_owner", "BOOLEAN DEFAULT FALSE"),
            ("can_applications", "BOOLEAN DEFAULT TRUE"),
            ("can_announcements", "BOOLEAN DEFAULT TRUE"),
            ("can_reports", "BOOLEAN DEFAULT TRUE"),
            ("can_reminders", "BOOLEAN DEFAULT TRUE"),
            ("can_gather", "BOOLEAN DEFAULT TRUE"),
            ("can_admins", "BOOLEAN DEFAULT FALSE"),
        ):
            await conn.execute(
                f"ALTER TABLE admins ADD COLUMN IF NOT EXISTS {column} {definition}"
            )

        # ---------- bot_settings ----------
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        # ---------- zam_bank ----------
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS zam_bank (
                id SERIAL PRIMARY KEY,
                inviter TEXT NOT NULL,
                invited_user_id BIGINT,
                amount BIGINT NOT NULL DEFAULT 100000,
                action TEXT NOT NULL DEFAULT 'credited',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # ---------- owner ----------
        await conn.execute("""
            INSERT INTO admins (
                user_id,
                username,
                is_owner,
                can_applications,
                can_announcements,
                can_reports,
                can_reminders,
                can_gather,
                can_admins
            )
            VALUES (
                $1,
                'owner',
                TRUE,
                TRUE,
                TRUE,
                TRUE,
                TRUE,
                TRUE,
                TRUE
            )
            ON CONFLICT (user_id)
            DO UPDATE SET
                is_owner = TRUE,
                can_applications = TRUE,
                can_announcements = TRUE,
                can_reports = TRUE,
                can_reminders = TRUE,
                can_gather = TRUE,
                can_admins = TRUE
        """, OWNER_ID)

    logger.info("PostgreSQL initialized")


# ============================================================
# GOOGLE SYNC SCHEDULER
# ============================================================

_sheet_sync_task = None
_sheet_sync_pending = False


async def _delayed_google_sync():
    global _sheet_sync_task, _sheet_sync_pending
    try:
        await asyncio.sleep(2)
        await sync_google_sheets()
    except Exception as e:
        logger.warning("Scheduled Google Sheets sync failed: %s", e)
    finally:
        _sheet_sync_task = None
        if _sheet_sync_pending:
            _sheet_sync_pending = False
            schedule_google_sync()


def schedule_google_sync():
    global _sheet_sync_task, _sheet_sync_pending
    if not GOOGLE_SHEET_ID or not GOOGLE_AVAILABLE:
        return
    if _sheet_sync_task is None or _sheet_sync_task.done():
        try:
            _sheet_sync_task = asyncio.create_task(_delayed_google_sync())
        except RuntimeError:
            pass
    else:
        _sheet_sync_pending = True


async def db_execute(query, *args):
    if not db_pool:
        return

    async with db_pool.acquire() as conn:
        result = await conn.execute(query, *args)
    schedule_google_sync()
    return result


async def db_fetch(query, *args):
    if not db_pool:
        return []

    async with db_pool.acquire() as conn:
        return await conn.fetch(query, *args)


async def db_fetchrow(query, *args):
    if not db_pool:
        return None

    async with db_pool.acquire() as conn:
        return await conn.fetchrow(query, *args)


# ============================================================
# USERS
# ============================================================

async def save_user(message: Message):
    user = message.from_user

    if not user:
        return

    try:
        await db_execute("""
            INSERT INTO bot_users (
                user_id,
                username,
                first_name,
                last_name,
                updated_at
            )
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (user_id)
            DO UPDATE SET
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                updated_at = NOW()
        """,
            user.id,
            user.username,
            user.first_name,
            user.last_name
        )
    except Exception as e:
        logger.warning("save_user failed: %s", e)


# ============================================================
# LOGGING ACTIONS
# ============================================================

async def log_action(
    user_id: int,
    username: str,
    action: str,
    details: str = ""
):
    try:
        await db_execute("""
            INSERT INTO bot_logs (
                user_id,
                username,
                action,
                details
            )
            VALUES ($1, $2, $3, $4)
        """,
            user_id,
            username,
            action,
            details
        )
    except Exception as e:
        logger.error("log_action: %s", e)


# ============================================================
# ADMIN PERMISSIONS
# ============================================================

async def get_admin(user_id: int):
    return await db_fetchrow("""
        SELECT *
        FROM admins
        WHERE user_id = $1
    """, user_id)


async def is_admin(user_id: int) -> bool:
    row = await get_admin(user_id)
    return row is not None


async def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID


async def check_permission(
    user_id: int,
    permission: str
) -> bool:

    if user_id == OWNER_ID:
        return True

    row = await get_admin(user_id)

    if not row:
        return False

    try:
        return bool(row[permission])
    except Exception:
        return False


# ============================================================
# KEYBOARDS
# ============================================================

async def main_menu(user_id: int) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="📝 Заполнить анкету"), KeyboardButton(text="🔄 Перезаполнить анкету")],
        [KeyboardButton(text="👤 Мой профиль"), KeyboardButton(text="📋 Моя заявка")],
        [KeyboardButton(text="📨 Report")],
    ]
    if await check_permission(user_id, "can_announcements"):
        rows.append([KeyboardButton(text="📢 Объявления")])
    if await check_permission(user_id, "can_gather"):
        rows.append([KeyboardButton(text="📢 Общий сбор"), KeyboardButton(text="🛑 Остановить сбор")])
    if await check_permission(user_id, "can_applications"):
        rows.append([KeyboardButton(text="📋 Управление заявками")])
    if await is_admin(user_id):
        rows.append([KeyboardButton(text="👥 Список участников"), KeyboardButton(text="🟢 Статус бота")])
    if await check_permission(user_id, "can_reminders"):
        rows.append([KeyboardButton(text="⏰ Напоминания")])
    if await is_owner(user_id):
        rows.append([KeyboardButton(text="👑 Администрирование"), KeyboardButton(text="📜 Журнал действий")])
        rows.append([KeyboardButton(text="🏦 Банк замов"), KeyboardButton(text="🌍 Часовой пояс")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def cancel_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="❌ Отмена")]
        ],
        resize_keyboard=True
    )


# ============================================================
# HELPERS
# ============================================================

async def safe_answer(message: Message, text: str, **kwargs):
    """Отправляет текст, разбивая его на куски < 4096 символов."""
    LIMIT = 4000
    if not text:
        return
    if len(text) <= LIMIT:
        try:
            await message.answer(text, **kwargs)
        except Exception as e:
            logger.warning("safe_answer failed: %s", e)
        return
    # Первый чанк с клавиатурой (если передана), остальные — без.
    first = True
    for i in range(0, len(text), LIMIT):
        chunk = text[i:i + LIMIT]
        try:
            if first:
                await message.answer(chunk, **kwargs)
                first = False
            else:
                await message.answer(chunk)
        except Exception as e:
            logger.warning("safe_answer chunk failed: %s", e)


def escape_html(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ============================================================
# STATES
# ============================================================

class ApplicationForm(StatesGroup):
    nickname = State()
    family_rank = State()
    organization = State()
    organization_rank = State()
    inviter = State()


class ReportForm(StatesGroup):
    text = State()


class AnnouncementForm(StatesGroup):
    text = State()


class ReminderForm(StatesGroup):
    name = State()
    message = State()
    time = State()
    destination = State()
    topic = State()
    mention = State()


class AddAdminForm(StatesGroup):
    user_id = State()


# ============================================================
# START
# ============================================================

@dp.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):

    await state.clear()
    await save_user(message)

    await message.answer(
        f"👋 Добро пожаловать в <b>{BOT_NAME}</b>!\n\n"
        "Выбери нужный раздел:",
        reply_markup=await main_menu(message.from_user.id)
    )


# ============================================================
# CANCEL
# ============================================================

@dp.message(F.text == "❌ Отмена")
async def cancel_handler(
    message: Message,
    state: FSMContext
):
    await state.clear()

    await message.answer(
        "❌ Действие отменено.",
        reply_markup=await main_menu(message.from_user.id)
    )


# ============================================================
# APPLICATION
# ============================================================

@dp.message(F.text.in_({"📝 Заполнить анкету", "🔄 Перезаполнить анкету"}))
async def application_start(
    message: Message,
    state: FSMContext
):

    await save_user(message)

    previous = await db_fetchrow("""
        SELECT id, inviter, status FROM applications
        WHERE user_id = $1
        ORDER BY id DESC LIMIT 1
    """, message.from_user.id)
    if previous and previous["status"] == "accepted" and (previous["inviter"] or "").strip():
        inviter_name = previous["inviter"].strip()
        credited = await db_fetchrow("""
            SELECT COALESCE(SUM(amount), 0) AS balance
            FROM zam_bank
            WHERE invited_user_id = $1 AND inviter = $2
        """, message.from_user.id, inviter_name)
        balance = int(credited["balance"] or 0) if credited else 0
        if balance > 0:
            await db_execute("""
                INSERT INTO zam_bank(inviter, invited_user_id, amount, action)
                VALUES ($1, $2, -100000, 'reversed')
            """, inviter_name, message.from_user.id)

    await state.set_state(ApplicationForm.nickname)

    await message.answer(
        "📝 <b>Заполнение анкеты</b>\n\n"
        "Введите игровой ник:",
        reply_markup=cancel_keyboard()
    )


@dp.message(ApplicationForm.nickname)
async def application_nickname(
    message: Message,
    state: FSMContext
):

    await state.update_data(
        nickname=(message.text or "").strip()
    )

    await state.set_state(ApplicationForm.family_rank)

    await message.answer(
        "Выберите семейный ранг:\n\n"
        "НОВИЧОК\n"
        "БАНДИТ\n"
        "СТРЕЛОК\n"
        "ФРАЕР\n"
        "ОХРАНИК\n"
        "СТ. ОХРАНИК\n"
        "РЕШАЛО\n"
        "ПОЛОЖЕНЕЦ\n"
        "ВОР"
    )


@dp.message(ApplicationForm.family_rank)
async def application_rank(
    message: Message,
    state: FSMContext
):

    await state.update_data(
        family_rank=(message.text or "").strip()
    )

    await state.set_state(ApplicationForm.organization)

    await message.answer(
        "Введите организацию:\n\n"
        "Правительство\n"
        "Воинская часть\n"
        "Больница Арзамас\n"
        "Больница Южный\n"
        "Полиция Арзамас\n"
        "Полиция Южный\n"
        "ФСБ\n"
        "МВД-А\n"
        "МВД-Ю\n"
        "МЗ-А\n"
        "МЗ-Ю\n"
        "Банда\n"
        "Не в организации"
    )


@dp.message(ApplicationForm.organization)
async def application_org(
    message: Message,
    state: FSMContext
):

    await state.update_data(
        organization=(message.text or "").strip()
    )

    await state.set_state(ApplicationForm.organization_rank)

    await message.answer(
        "Введите ранг в организации:"
    )


@dp.message(ApplicationForm.organization_rank)
async def application_org_rank(
    message: Message,
    state: FSMContext
):

    await state.update_data(
        organization_rank=(message.text or "").strip()
    )

    await state.set_state(ApplicationForm.inviter)

    await message.answer(
        "Введите ник пригласившего зама.\n\n"
        "Если вас никто не приглашал — напишите <b>нет</b>."
    )


@dp.message(ApplicationForm.inviter)
async def application_inviter(
    message: Message,
    state: FSMContext
):

    data = await state.get_data()

    required = ("nickname", "family_rank", "organization", "organization_rank")
    if not all(k in data and data[k] for k in required):
        await state.clear()
        await message.answer(
            "❌ Анкета повреждена, начните заново.",
            reply_markup=await main_menu(message.from_user.id)
        )
        return

    inviter = (message.text or "").strip()

    username = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else str(message.from_user.id)
    )

    old = await db_fetchrow("""
        SELECT id
        FROM applications
        WHERE user_id = $1
        ORDER BY id DESC
        LIMIT 1
    """, message.from_user.id)

    if old:
        await db_execute("""
            UPDATE applications
            SET
                username = $2,
                nickname = $3,
                family_rank = $4,
                organization = $5,
                organization_rank = $6,
                inviter = $7,
                status = 'pending',
                updated_at = NOW()
            WHERE id = $1
        """,
            old["id"],
            username,
            data["nickname"],
            data["family_rank"],
            data["organization"],
            data["organization_rank"],
            inviter
        )
    else:
        await db_execute("""
            INSERT INTO applications (
                user_id,
                username,
                nickname,
                family_rank,
                organization,
                organization_rank,
                inviter,
                status
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,'pending')
        """,
            message.from_user.id,
            username,
            data["nickname"],
            data["family_rank"],
            data["organization"],
            data["organization_rank"],
            inviter
        )

    await state.clear()

    await log_action(
        message.from_user.id,
        username,
        "application_created",
        data["nickname"]
    )

    await message.answer(
        "✅ <b>Анкета отправлена!</b>\n\n"
        "Ожидайте решения администрации.",
        reply_markup=await main_menu(message.from_user.id)
    )


# ============================================================
# MY PROFILE
# ============================================================

@dp.message(F.text == "👤 Мой профиль")
async def profile_handler(message: Message):

    await save_user(message)

    row = await db_fetchrow("""
        SELECT *
        FROM applications
        WHERE user_id = $1
        ORDER BY id DESC
        LIMIT 1
    """, message.from_user.id)

    if not row:
        await message.answer("❌ У вас пока нет анкеты.")
        return

    await message.answer(
        "👤 <b>Ваш профиль</b>\n\n"
        f"🎮 Ник: <b>{escape_html(row['nickname'] or '-')}</b>\n"
        f"⭐ Ранг: <b>{escape_html(row['family_rank'] or '-')}</b>\n"
        f"🏢 Организация: <b>{escape_html(row['organization'] or '-')}</b>\n"
        f"🎖 Ранг организации: <b>{escape_html(row['organization_rank'] or '-')}</b>\n"
        f"👤 Зам: <b>{escape_html(row['inviter'] or '-')}</b>\n"
        f"📌 Статус: <b>{row['status']}</b>"
    )


# ============================================================
# MY APPLICATION
# ============================================================

@dp.message(F.text == "📋 Моя заявка")
async def my_application(message: Message):

    row = await db_fetchrow("""
        SELECT *
        FROM applications
        WHERE user_id = $1
        ORDER BY id DESC
        LIMIT 1
    """, message.from_user.id)

    if not row:
        await message.answer("❌ Заявка не найдена.")
        return

    await message.answer(
        "📋 <b>Ваша заявка</b>\n\n"
        f"ID: <b>#{row['id']}</b>\n"
        f"Ник: <b>{escape_html(row['nickname'] or '-')}</b>\n"
        f"Ранг: <b>{escape_html(row['family_rank'] or '-')}</b>\n"
        f"Организация: <b>{escape_html(row['organization'] or '-')}</b>\n"
        f"Ранг: <b>{escape_html(row['organization_rank'] or '-')}</b>\n"
        f"Зам: <b>{escape_html(row['inviter'] or '-')}</b>\n"
        f"Статус: <b>{row['status']}</b>"
    )


# ============================================================
# ADMIN APPLICATIONS
# ============================================================

@dp.message(F.text == "📋 Управление заявками")
async def manage_applications(message: Message):

    if not await check_permission(message.from_user.id, "can_applications"):
        await message.answer("❌ У вас нет права управлять заявками.")
        return

    rows = await db_fetch("""
        SELECT *
        FROM applications
        WHERE status = 'pending'
        ORDER BY id DESC
        LIMIT 20
    """)

    if not rows:
        await message.answer("📭 Новых заявок нет.")
        return

    for row in rows:

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Принять",
                        callback_data=f"app_accept:{row['id']}"
                    ),
                    InlineKeyboardButton(
                        text="❌ Отклонить",
                        callback_data=f"app_reject:{row['id']}"
                    )
                ]
            ]
        )

        await message.answer(
            "📋 <b>Заявка</b>\n\n"
            f"ID: <b>#{row['id']}</b>\n"
            f"👤 Пользователь: {escape_html(row['username'] or '-')}\n"
            f"🎮 Ник: <b>{escape_html(row['nickname'] or '-')}</b>\n"
            f"⭐ Ранг: {escape_html(row['family_rank'] or '-')}\n"
            f"🏢 Организация: {escape_html(row['organization'] or '-')}\n"
            f"🎖 Ранг: {escape_html(row['organization_rank'] or '-')}\n"
            f"👤 Зам: {escape_html(row['inviter'] or '-')}",
            reply_markup=kb
        )


@dp.callback_query(F.data.startswith("app_accept:"))
async def app_accept(callback: CallbackQuery):

    if not await check_permission(callback.from_user.id, "can_applications"):
        await callback.answer("Нет прав", show_alert=True)
        return

    app_id = int(callback.data.split(":")[1])

    row = await db_fetchrow("""
        SELECT *
        FROM applications
        WHERE id = $1
    """, app_id)

    if not row:
        await callback.answer("Заявка не найдена", show_alert=True)
        return

    await db_execute("""
        UPDATE applications
        SET status = 'accepted',
            updated_at = NOW()
        WHERE id = $1
    """, app_id)

    inviter = (row["inviter"] or "").strip()
    if inviter:
        await db_execute("""
            INSERT INTO zam_bank(inviter, invited_user_id, amount, action)
            SELECT $1, $2, 100000, 'credited'
            WHERE (
                SELECT COALESCE(SUM(amount), 0) FROM zam_bank
                WHERE invited_user_id = $2 AND inviter = $1
            ) <= 0
        """, inviter, row["user_id"])

    invite_text = "Добро пожаловать!"
    try:
        invite = await bot.create_chat_invite_link(
            chat_id=GROUP_ID,
            member_limit=1,
            name=f"Анкета #{app_id}"
        )
        invite_text += f"\n\n🔗 Ссылка для вступления: {invite.invite_link}"
    except Exception as e:
        logger.warning("Не удалось создать одноразовую ссылку: %s", e)

    try:
        nickname = (row["nickname"] or "").strip()
        if nickname:
            await bot.set_chat_administrator_custom_title(
                chat_id=GROUP_ID,
                user_id=row["user_id"],
                custom_title=nickname[:16]
            )
    except Exception as e:
        logger.info("Custom title не установлен: %s", e)

    try:
        await bot.send_message(
            row["user_id"],
            "✅ <b>Ваша заявка принята!</b>\n\n" + invite_text
        )
    except Exception as e:
        logger.warning("Не удалось уведомить пользователя: %s", e)

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await callback.message.answer(f"✅ Заявка #{app_id} принята.")
    await callback.answer()


@dp.callback_query(F.data.startswith("app_reject:"))
async def app_reject(callback: CallbackQuery):

    if not await check_permission(callback.from_user.id, "can_applications"):
        await callback.answer("Нет прав", show_alert=True)
        return

    app_id = int(callback.data.split(":")[1])

    row = await db_fetchrow("""
        SELECT *
        FROM applications
        WHERE id = $1
    """, app_id)

    if not row:
        await callback.answer("Заявка не найдена", show_alert=True)
        return

    await db_execute("""
        UPDATE applications
        SET status = 'rejected',
            updated_at = NOW()
        WHERE id = $1
    """, app_id)

    try:
        await bot.send_message(
            row["user_id"],
            "❌ <b>Ваша заявка отклонена.</b>"
        )
    except Exception:
        pass

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await callback.message.answer(f"❌ Заявка #{app_id} отклонена.")
    await callback.answer()


# ============================================================
# ACTIVE APPLICATIONS
# ============================================================

@dp.message(F.text == "⏳ Активные заявки")
async def active_applications(message: Message):

    if not await check_permission(message.from_user.id, "can_applications"):
        await message.answer("❌ Нет прав.")
        return

    rows = await db_fetch("""
        SELECT id, username, nickname, status
        FROM applications
        WHERE status = 'pending'
        ORDER BY id DESC
    """)

    if not rows:
        await message.answer("📭 Активных заявок нет.")
        return

    text = "⏳ <b>Активные заявки:</b>\n\n"

    for row in rows:
        text += (
            f"#{row['id']} — "
            f"{escape_html(row['nickname'] or '-')} — "
            f"{escape_html(row['username'] or '-')}\n"
        )

    await safe_answer(message, text)


# ============================================================
# REPORT
# ============================================================

@dp.message(F.text == "📨 Report")
async def report_start(
    message: Message,
    state: FSMContext
):

    await save_user(message)

    await state.set_state(ReportForm.text)

    await message.answer(
        "📨 <b>Report / Обращение</b>\n\n"
        "Напишите сообщение администрации:"
    )


@dp.message(ReportForm.text)
async def report_receive(
    message: Message,
    state: FSMContext
):

    username = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else str(message.from_user.id)
    )

    report_text = message.text or message.caption or "[пустое сообщение]"
    await db_execute("""
        INSERT INTO reports (
            user_id,
            username,
            text
        )
        VALUES ($1,$2,$3)
    """,
        message.from_user.id,
        username,
        report_text
    )

    admins = await db_fetch("""
        SELECT user_id
        FROM admins
        WHERE is_owner = TRUE OR can_reports = TRUE
    """)

    for admin in admins:
        try:
            await bot.send_message(
                admin["user_id"],
                "📨 <b>Новый Report</b>\n\n"
                f"👤 {escape_html(username)}\n"
                f"🆔 {message.from_user.id}\n\n"
                f"{escape_html(report_text)}"
            )
        except Exception as e:
            logger.warning("Report admin notification: %s", e)

    await state.clear()

    await message.answer(
        "✅ Обращение отправлено администрации.",
        reply_markup=await main_menu(message.from_user.id)
    )


# ============================================================
# ANNOUNCEMENTS
# ============================================================

@dp.message(F.text == "📢 Объявления")
async
