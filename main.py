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

# ID группы, куда бот отправляет объявления/напоминания
GROUP_ID = int(os.getenv("GROUP_ID", "-1002409536359"))

# Тема Новости
ANNOUNCE_TOPIC_ID = int(
    os.getenv("ANNOUNCE_TOPIC_ID", "126387")
)

# Также поддерживаем старое имя переменной
TOPIC_ID = int(
    os.getenv("TOPIC_ID", str(ANNOUNCE_TOPIC_ID))
)

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
    flask_app.run(
        host="0.0.0.0",
        port=PORT,
        use_reloader=False
    )


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

        # Миграции без удаления существующих данных.
        for column, definition in (
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
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
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


_sheet_sync_task = None

async def _delayed_google_sync():
    global _sheet_sync_task
    try:
        await asyncio.sleep(2)
        await sync_google_sheets()
    except Exception as e:
        logger.warning("Scheduled Google Sheets sync failed: %s", e)
    finally:
        _sheet_sync_task = None

def schedule_google_sync():
    global _sheet_sync_task
    if not GOOGLE_SHEET_ID or not GOOGLE_AVAILABLE:
        return
    if _sheet_sync_task is None or _sheet_sync_task.done():
        try:
            _sheet_sync_task = asyncio.create_task(_delayed_google_sync())
        except RuntimeError:
            pass

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

    # При повторном заполнении снимаем предыдущее начисление заму.
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
        nickname=message.text.strip()
    )

    await state.set_state(
        ApplicationForm.family_rank
    )

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
        family_rank=message.text.strip()
    )

    await state.set_state(
        ApplicationForm.organization
    )

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
        organization=message.text.strip()
    )

    await state.set_state(
        ApplicationForm.organization_rank
    )

    await message.answer(
        "Введите ранг в организации:"
    )


@dp.message(ApplicationForm.organization_rank)
async def application_org_rank(
    message: Message,
    state: FSMContext
):

    await state.update_data(
        organization_rank=message.text.strip()
    )

    await state.set_state(
        ApplicationForm.inviter
    )

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

    inviter = message.text.strip()

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

    row = await db_fetchrow("""
        SELECT *
        FROM applications
        WHERE user_id = $1
        ORDER BY id DESC
        LIMIT 1
    """, message.from_user.id)

    if not row:
        await message.answer(
            "❌ У вас пока нет анкеты."
        )
        return

    await message.answer(
        "👤 <b>Ваш профиль</b>\n\n"
        f"🎮 Ник: <b>{row['nickname']}</b>\n"
        f"⭐ Ранг: <b>{row['family_rank']}</b>\n"
        f"🏢 Организация: <b>{row['organization']}</b>\n"
        f"🎖 Ранг организации: <b>{row['organization_rank']}</b>\n"
        f"👤 Зам: <b>{row['inviter']}</b>\n"
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
        await message.answer(
            "❌ Заявка не найдена."
        )
        return

    await message.answer(
        "📋 <b>Ваша заявка</b>\n\n"
        f"ID: <b>#{row['id']}</b>\n"
        f"Ник: <b>{row['nickname']}</b>\n"
        f"Ранг: <b>{row['family_rank']}</b>\n"
        f"Организация: <b>{row['organization']}</b>\n"
        f"Ранг: <b>{row['organization_rank']}</b>\n"
        f"Зам: <b>{row['inviter']}</b>\n"
        f"Статус: <b>{row['status']}</b>"
    )


# ============================================================
# ADMIN APPLICATIONS
# ============================================================

@dp.message(F.text == "📋 Управление заявками")
async def manage_applications(message: Message):

    if not await check_permission(
        message.from_user.id,
        "can_applications"
    ):
        await message.answer(
            "❌ У вас нет права управлять заявками."
        )
        return

    rows = await db_fetch("""
        SELECT *
        FROM applications
        WHERE status = 'pending'
        ORDER BY id DESC
        LIMIT 20
    """)

    if not rows:
        await message.answer(
            "📭 Новых заявок нет."
        )
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
            f"👤 Пользователь: {row['username']}\n"
            f"🎮 Ник: <b>{row['nickname']}</b>\n"
            f"⭐ Ранг: {row['family_rank']}\n"
            f"🏢 Организация: {row['organization']}\n"
            f"🎖 Ранг: {row['organization_rank']}\n"
            f"👤 Зам: {row['inviter']}",
            reply_markup=kb
        )


@dp.callback_query(F.data.startswith("app_accept:"))
async def app_accept(callback: CallbackQuery):

    if not await check_permission(
        callback.from_user.id,
        "can_applications"
    ):
        await callback.answer(
            "Нет прав",
            show_alert=True
        )
        return

    app_id = int(
        callback.data.split(":")[1]
    )

    row = await db_fetchrow("""
        SELECT *
        FROM applications
        WHERE id = $1
    """, app_id)

    if not row:
        await callback.answer(
            "Заявка не найдена",
            show_alert=True
        )
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
        invite_text += f"\\n\\n🔗 Ссылка для вступления: {invite.invite_link}"
    except Exception as e:
        logger.warning("Не удалось создать одноразовую ссылку: %s", e)

    # Telegram позволяет задать custom title только администраторам группы.
    try:
        nickname = (row["nickname"] or "").strip()
        if nickname:
            await bot.set_chat_administrator_custom_title(
                chat_id=GROUP_ID,
                user_id=row["user_id"],
                custom_title=nickname[:16]
            )
    except Exception as e:
        logger.info("Custom title не установлен (возможно, пользователь не админ): %s", e)

    try:
        await bot.send_message(
            row["user_id"],
            "✅ <b>Ваша заявка принята!</b>\\n\\n" + invite_text
        )
    except Exception as e:
        logger.warning("Не удалось уведомить пользователя: %s", e)

    await callback.message.edit_reply_markup(
        reply_markup=None
    )

    await callback.message.answer(
        f"✅ Заявка #{app_id} принята."
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("app_reject:"))
async def app_reject(callback: CallbackQuery):

    if not await check_permission(
        callback.from_user.id,
        "can_applications"
    ):
        await callback.answer(
            "Нет прав",
            show_alert=True
        )
        return

    app_id = int(
        callback.data.split(":")[1]
    )

    row = await db_fetchrow("""
        SELECT *
        FROM applications
        WHERE id = $1
    """, app_id)

    if not row:
        await callback.answer(
            "Заявка не найдена",
            show_alert=True
        )
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

    await callback.message.edit_reply_markup(
        reply_markup=None
    )

    await callback.message.answer(
        f"❌ Заявка #{app_id} отклонена."
    )

    await callback.answer()


# ============================================================
# ACTIVE APPLICATIONS
# ============================================================

@dp.message(F.text == "⏳ Активные заявки")
async def active_applications(message: Message):

    if not await check_permission(
        message.from_user.id,
        "can_applications"
    ):
        await message.answer(
            "❌ Нет прав."
        )
        return

    rows = await db_fetch("""
        SELECT id, username, nickname, status
        FROM applications
        WHERE status = 'pending'
        ORDER BY id DESC
    """)

    if not rows:
        await message.answer(
            "📭 Активных заявок нет."
        )
        return

    text = "⏳ <b>Активные заявки:</b>\n\n"

    for row in rows:
        text += (
            f"#{row['id']} — "
            f"{row['nickname']} — "
            f"{row['username']}\n"
        )

    await message.answer(text)


# ============================================================
# REPORT
# ============================================================

@dp.message(F.text == "📨 Report")
async def report_start(
    message: Message,
    state: FSMContext
):

    await state.set_state(
        ReportForm.text
    )

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
                f"👤 {username}\n"
                f"🆔 {message.from_user.id}\n\n"
                f"{message.text}"
            )
        except Exception as e:
            logger.warning(
                "Report admin notification: %s",
                e
            )

    await state.clear()

    await message.answer(
        "✅ Обращение отправлено администрации.",
        reply_markup=await main_menu(message.from_user.id)
    )


# ============================================================
# ANNOUNCEMENTS
# ============================================================

@dp.message(F.text == "📢 Объявления")
async def announcement_start(
    message: Message,
    state: FSMContext
):

    if not await check_permission(
        message.from_user.id,
        "can_announcements"
    ):
        await message.answer(
            "❌ У вас нет права создавать объявления."
        )
        return

    await state.set_state(
        AnnouncementForm.text
    )

    await message.answer(
        "📢 Введите текст объявления:"
    )


@dp.message(AnnouncementForm.text)
async def announcement_send(
    message: Message,
    state: FSMContext
):

    if not await check_permission(
        message.from_user.id,
        "can_announcements"
    ):
        await state.clear()
        await message.answer(
            "❌ Нет прав."
        )
        return

    if not GROUP_ID:
        await message.answer(
            "❌ GROUP_ID не настроен."
        )
        return

    try:

        await bot.send_message(
            chat_id=GROUP_ID,
            message_thread_id=TOPIC_ID,
            text=(
                "📢 <b>ОБЪЯВЛЕНИЕ</b>\n\n"
                f"{message.text}"
            )
        )

        await message.answer(
            "✅ Объявление отправлено."
        )

        await log_action(
            message.from_user.id,
            message.from_user.username or "",
            "announcement",
            message.text
        )

    except Exception as e:

        logger.exception(e)

        await message.answer(
            "❌ Не удалось отправить объявление:\n"
            f"<code>{e}</code>"
        )

    await state.clear()


# ============================================================
# GENERAL GATHER
# ============================================================

async def start_gather_from_button(
    message: Message
):

    if not await check_permission(
        message.from_user.id,
        "can_gather"
    ):
        await message.answer(
            "❌ У вас нет права запускать общий сбор."
        )
        return

    if not GROUP_ID:
        await message.answer(
            "❌ GROUP_ID не настроен."
        )
        return

    try:
        known_users = await db_fetch("""
            SELECT user_id, first_name, username
            FROM bot_users
            ORDER BY user_id
        """)
        mentions = []
        for member in known_users[:70]:
            label = member["first_name"] or member["username"] or str(member["user_id"])
            label = str(label).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            mentions.append(f'<a href="tg://user?id={member["user_id"]}">{label}</a>')
        mention_text = " ".join(mentions)
        gather_text = (
            "📢 <b>ОБЩИЙ СБОР</b>\n\n"
            + (mention_text + "\n\n" if mention_text else "")
            + "⚠️ Всем участникам необходимо подойти на общий сбор.\n\n"
            + "Замы обязаны заполнить анкеты."
        )
        await bot.send_message(
            chat_id=GROUP_ID,
            message_thread_id=TOPIC_ID,
            text=gather_text
        )

        await message.answer(
            "✅ Общий сбор запущен."
        )

        await log_action(
            message.from_user.id,
            message.from_user.username or "",
            "general_gather"
        )

    except Exception as e:

        logger.exception(e)

        await message.answer(
            "❌ Ошибка общего сбора:\n"
            f"<code>{e}</code>"
        )


@dp.message(F.text == "📢 Общий сбор")
async def gather_btn(message: Message):

    # ВАЖНО:
    # этот обработчик находится ПОСЛЕ создания dp.
    # Ошибки NameError: dp is not defined здесь больше нет.

    await start_gather_from_button(message)


# ============================================================
# STOP GATHER
# ============================================================

@dp.message(F.text == "🛑 Остановить сбор")
async def gather_stop_btn(message: Message):

    if not await check_permission(
        message.from_user.id,
        "can_gather"
    ):
        await message.answer(
            "❌ Нет прав."
        )
        return

    try:

        await bot.send_message(
            chat_id=GROUP_ID,
            message_thread_id=TOPIC_ID,
            text="🛑 <b>ОБЩИЙ СБОР ОКОНЧЕН</b>"
        )

        await message.answer(
            "🛑 Сбор остановлен."
        )

    except Exception as e:

        await message.answer(
            f"❌ Ошибка: <code>{e}</code>"
        )


# ============================================================
# PING
# ============================================================

async def telegram_ping():

    started = time.perf_counter()

    await bot.get_me()

    return round(
        (time.perf_counter() - started) * 1000,
        2
    )


@dp.message(Command("ping"))
async def ping_command(message: Message):

    started = time.perf_counter()

    try:
        me = await bot.get_me()

        telegram_rtt = round(
            (time.perf_counter() - started) * 1000,
            2
        )

        msg_started = time.perf_counter()

        sent = await message.answer(
            "🏓 Проверяю..."
        )

        processing = round(
            (time.perf_counter() - msg_started) * 1000,
            2
        )

        await sent.edit_text(
            "🏓 <b>PING</b>\n\n"
            f"🌐 Telegram Bot API: "
            f"<b>{telegram_rtt} ms</b>\n"
            f"📨 Обработка сообщения: "
            f"<b>{processing} ms</b>\n"
            f"🤖 @{me.username}"
        )

    except Exception as e:

        await message.answer(
            "❌ Ошибка ping:\n"
            f"<code>{e}</code>"
        )


# ============================================================
# MY ID
# ============================================================

@dp.message(Command("myid"))
async def myid_command(message: Message):

    await message.answer(
        f"🆔 Ваш Telegram ID:\n"
        f"<code>{message.from_user.id}</code>"
    )


# ============================================================
# WHO
# ============================================================

@dp.message(Command("кто", "kto"))
async def kto_command(message: Message):

    if not message.reply_to_message:
        await message.answer(
            "❌ Используй /кто ответом на сообщение пользователя."
        )
        return

    target = message.reply_to_message.from_user

    if not target:
        await message.answer(
            "❌ Не удалось определить пользователя."
        )
        return

    row = await db_fetchrow("""
        SELECT *
        FROM applications
        WHERE user_id = $1
        ORDER BY id DESC
        LIMIT 1
    """, target.id)

    if not row:
        await message.answer(
            f"👤 Пользователь:\n"
            f"ID: <code>{target.id}</code>\n"
            f"Username: @{target.username or 'нет'}\n\n"
            "❌ Анкета не найдена."
        )
        return

    await message.answer(
        "👤 <b>Информация о пользователе</b>\n\n"
        f"ID: <code>{target.id}</code>\n"
        f"Username: @{target.username or 'нет'}\n"
        f"🎮 Ник: <b>{row['nickname']}</b>\n"
        f"⭐ Ранг: {row['family_rank']}\n"
        f"🏢 Организация: {row['organization']}\n"
        f"🎖 Ранг: {row['organization_rank']}\n"
        f"👤 Зам: {row['inviter']}\n"
        f"📌 Статус: {row['status']}"
    )


# ============================================================
# ADMINISTRATION
# ============================================================

@dp.message(F.text == "👑 Администрирование")
async def admin_panel(message: Message):

    if not await is_owner(message.from_user.id):
        await message.answer(
            "❌ Этот раздел доступен только владельцу."
        )
        return

    admins = await db_fetch("""
        SELECT *
        FROM admins
        ORDER BY is_owner DESC, user_id
    """)

    text = "👑 <b>Администрирование</b>\n\n"

    for admin in admins:

        text += (
            f"🆔 <code>{admin['user_id']}</code>\n"
            f"👤 {admin['username'] or '-'}\n"
            f"👑 Владелец: "
            f"{'да' if admin['is_owner'] else 'нет'}\n"
            f"📋 Заявки: "
            f"{'✅' if admin['can_applications'] else '❌'}\n"
            f"📢 Объявления: "
            f"{'✅' if admin['can_announcements'] else '❌'}\n"
            f"📨 Report: "
            f"{'✅' if admin['can_reports'] else '❌'}\n"
            f"⏰ Напоминания: "
            f"{'✅' if admin['can_reminders'] else '❌'}\n"
            f"📢 Сбор: "
            f"{'✅' if admin['can_gather'] else '❌'}\n\n"
        )

    text += (
        "Добавление администратора:\n"
        "<code>/add_admin 123456789</code>\n"
        "Настройка прав: <code>/set_admin_permission ID can_applications on</code>\n"
        "Для отключения используй <code>off</code>."
    )

    await message.answer(text)


@dp.message(Command("add_admin"))
async def add_admin(message: Message):

    if not await is_owner(message.from_user.id):
        await message.answer(
            "❌ Только владелец."
        )
        return

    parts = message.text.split()

    if len(parts) != 2:
        await message.answer(
            "Использование:\n"
            "<code>/add_admin 123456789</code>"
        )
        return

    try:
        user_id = int(parts[1])
    except ValueError:
        await message.answer(
            "❌ ID должен быть числом."
        )
        return

    await db_execute("""
        INSERT INTO admins (
            user_id,
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
            FALSE,
            TRUE,
            TRUE,
            TRUE,
            TRUE,
            TRUE,
            FALSE
        )
        ON CONFLICT (user_id)
        DO NOTHING
    """, user_id)

    await message.answer(
        f"✅ Администратор "
        f"<code>{user_id}</code> добавлен."
    )


@dp.message(Command("set_admin_permission"))
async def set_admin_permission(message: Message):
    if not await is_owner(message.from_user.id):
        await message.answer("❌ Только владелец может менять права.")
        return
    parts = (message.text or "").split()
    if len(parts) != 4:
        await message.answer(
            "Формат: <code>/set_admin_permission ID permission on/off</code>\n"
            "Права: <code>can_applications</code>, <code>can_announcements</code>, "
            "<code>can_reports</code>, <code>can_reminders</code>, "
            "<code>can_gather</code>, <code>can_admins</code>."
        )
        return
    try:
        target_id = int(parts[1])
    except ValueError:
        await message.answer("❌ ID должен быть числом.")
        return
    permission = parts[2].strip()
    value_text = parts[3].lower()
    allowed_permissions = {
        "can_applications", "can_announcements", "can_reports",
        "can_reminders", "can_gather", "can_admins"
    }
    if permission not in allowed_permissions or value_text not in {"on", "off", "true", "false", "1", "0"}:
        await message.answer("❌ Проверь название права и значение on/off.")
        return
    if target_id == OWNER_ID:
        await message.answer("❌ Права владельца нельзя отключить.")
        return
    enabled = value_text in {"on", "true", "1"}
    result = await db_execute(
        f"UPDATE admins SET {permission} = $1 WHERE user_id = $2",
        enabled, target_id
    )
    if result == "UPDATE 0":
        await message.answer("❌ Такой администратор не найден. Сначала используй /add_admin ID.")
        return
    await log_action(message.from_user.id, message.from_user.username or "", "admin_permission_changed", f"{target_id}: {permission}={enabled}")
    await message.answer(f"✅ Право <code>{permission}</code> для <code>{target_id}</code>: {'включено' if enabled else 'выключено'}.")

@dp.message(Command("del_admin"))
async def del_admin(message: Message):

    if not await is_owner(message.from_user.id):
        await message.answer(
            "❌ Только владелец."
        )
        return

    parts = message.text.split()

    if len(parts) != 2:
        await message.answer(
            "Использование:\n"
            "<code>/del_admin 123456789</code>"
        )
        return

    try:
        user_id = int(parts[1])
    except ValueError:
        await message.answer(
            "❌ ID должен быть числом."
        )
        return

    if user_id == OWNER_ID:
        await message.answer(
            "❌ Нельзя удалить владельца."
        )
        return

    await db_execute("""
        DELETE FROM admins
        WHERE user_id = $1
    """, user_id)

    await message.answer(
        "✅ Администратор удалён."
    )


# ============================================================
# MEMBERS
# ============================================================

@dp.message(F.text == "👥 Список участников")
async def members_list(message: Message):

    if not await is_admin(message.from_user.id):
        await message.answer(
            "❌ Нет прав."
        )
        return

    rows = await db_fetch("""
        SELECT user_id, username, first_name
        FROM bot_users
        ORDER BY first_name
        LIMIT 100
    """)

    if not rows:
        await message.answer(
            "📭 Список пуст."
        )
        return

    text = "👥 <b>Пользователи бота:</b>\n\n"

    for row in rows:

        name = (
            row["first_name"]
            or row["username"]
            or str(row["user_id"])
        )

        text += (
            f"• {name} — "
            f"<code>{row['user_id']}</code>\n"
        )

    await message.answer(text)


# ============================================================
# BOT STATUS
# ============================================================

@dp.message(F.text == "🟢 Статус бота")
async def bot_status(message: Message):

    if not await is_admin(message.from_user.id):
        await message.answer(
            "❌ Нет прав."
        )
        return

    try:

        started = time.perf_counter()

        me = await bot.get_me()

        ping = round(
            (time.perf_counter() - started) * 1000,
            2
        )

        await message.answer(
            "🟢 <b>Бот работает</b>\n\n"
            f"🤖 @{me.username}\n"
            f"🌐 Telegram API: <b>{ping} ms</b>\n"
            f"🗄 PostgreSQL: <b>подключена</b>\n"
            f"📊 Google Sheets: "
            f"<b>{'подключена' if GOOGLE_AVAILABLE and GOOGLE_SHEET_ID else 'не настроена'}</b>\n"
            f"👥 GROUP_ID: <code>{GROUP_ID}</code>\n"
            f"📰 TOPIC_ID: <code>{TOPIC_ID}</code>"
        )

    except Exception as e:

        await message.answer(
            f"❌ Ошибка статуса:\n"
            f"<code>{e}</code>"
        )


# ============================================================
# LOG
# ============================================================

@dp.message(F.text == "📜 Журнал действий")
async def logs_handler(message: Message):

    if not await is_owner(message.from_user.id):
        await message.answer(
            "❌ Только владелец."
        )
        return

    rows = await db_fetch("""
        SELECT *
        FROM bot_logs
        ORDER BY id DESC
        LIMIT 30
    """)

    if not rows:
        await message.answer(
            "📭 Журнал пуст."
        )
        return

    text = "📜 <b>Последние действия</b>\n\n"

    for row in rows:

        created = row["created_at"]

        text += (
            f"#{row['id']} "
            f"{created:%d.%m %H:%M}\n"
            f"👤 {row['username'] or row['user_id']}\n"
            f"⚙️ {row['action']}\n"
        )

        if row["details"]:
            text += f"📝 {row['details'][:150]}\n"

        text += "\n"

    await message.answer(text)


# ============================================================
# REMINDERS
# ============================================================

async def get_bot_timezone():
    row = await db_fetchrow("SELECT value FROM bot_settings WHERE key = 'timezone'")
    name = row["value"] if row else TIMEZONE
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("Europe/Moscow")


def valid_hhmm(value: str) -> bool:

    value = value.strip()

    return bool(
        re.fullmatch(
            r"(?:[01]\d|2[0-3]):[0-5]\d",
            value
        )
    )


@dp.message(F.text == "⏰ Напоминания")
async def reminders_menu(message: Message):

    if not await check_permission(
        message.from_user.id,
        "can_reminders"
    ):
        await message.answer(
            "❌ Нет прав."
        )
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Создать",
                    callback_data="rem_create"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📋 Список",
                    callback_data="rem_list"
                )
            ]
        ]
    )

    await message.answer(
        "⏰ <b>Напоминания</b>",
        reply_markup=kb
    )


@dp.callback_query(F.data == "rem_create")
async def reminder_create(
    callback: CallbackQuery,
    state: FSMContext
):

    if not await check_permission(
        callback.from_user.id,
        "can_reminders"
    ):
        await callback.answer(
            "Нет прав",
            show_alert=True
        )
        return

    await state.set_state(
        ReminderForm.name
    )

    await callback.message.answer(
        "Введите название напоминания:"
    )

    await callback.answer()


@dp.message(ReminderForm.name)
async def reminder_name(
    message: Message,
    state: FSMContext
):

    await state.update_data(
        name=message.text.strip()
    )

    await state.set_state(
        ReminderForm.message
    )

    await message.answer(
        "Введите текст напоминания:"
    )


@dp.message(ReminderForm.message)
async def reminder_message(
    message: Message,
    state: FSMContext
):

    await state.update_data(
        message=message.text.strip()
    )

    await state.set_state(
        ReminderForm.time
    )

    await message.answer(
        "Введите время в формате <b>HH:MM</b>.\n\n"
        "Например: <code>15:00</code>"
    )


@dp.message(ReminderForm.time)
async def reminder_time(
    message: Message,
    state: FSMContext
):

    value = message.text.strip()

    if not valid_hhmm(value):

        await message.answer(
            "❌ Неверное время.\n\n"
            "Пример правильного формата:\n"
            "<code>15:00</code>"
        )

        return

    await state.update_data(
        time=value
    )

    await state.set_state(
        ReminderForm.destination
    )

    await message.answer(
        "Куда отправлять?\n\n"
        "Напишите:\n"
        "<b>группа</b>\n"
        "<b>личка</b>"
    )


@dp.message(ReminderForm.destination)
async def reminder_destination(
    message: Message,
    state: FSMContext
):

    value = message.text.strip().lower()

    if value not in ("группа", "личка"):

        await message.answer(
            "Напишите <b>группа</b> или <b>личка</b>."
        )

        return

    await state.update_data(
        destination=value
    )

    if value == "группа":

        await state.set_state(
            ReminderForm.topic
        )

        await message.answer(
            "Введите ID темы.\n\n"
            "Для новостей можно написать:\n"
            "<code>126387</code>\n\n"
            "Если без темы — <code>0</code>."
        )

    else:

        await state.set_state(
            ReminderForm.topic
        )

        await message.answer(
            "Введите Telegram ID пользователя,\n"
            "которому отправлять напоминание:"
        )


@dp.message(ReminderForm.topic)
async def reminder_topic(
    message: Message,
    state: FSMContext
):

    data = await state.get_data()

    try:
        topic = int(message.text.strip())
    except ValueError:

        await message.answer(
            "❌ Нужно указать число."
        )

        return

    await state.update_data(
        topic_id=topic
    )

    await state.set_state(
        ReminderForm.mention
    )

    await message.answer(
        "Упоминать всех?\n\n"
        "Напишите <b>да</b> или <b>нет</b>."
    )


@dp.message(ReminderForm.mention)
async def reminder_mention(
    message: Message,
    state: FSMContext
):

    value = message.text.strip().lower()

    if value not in ("да", "нет"):

        await message.answer(
            "Напишите <b>да</b> или <b>нет</b>."
        )

        return

    data = await state.get_data()

    mention_all = value == "да"

    if data.get("edit_id"):
        await db_execute("""
            UPDATE reminders
            SET name=$1, message=$2, time=$3, destination=$4,
                topic_id=$5, user_id=$6, mention_all=$7
            WHERE id=$8
        """,
            data["name"], data["message"], data["time"], data["destination"],
            data["topic_id"], message.from_user.id, mention_all, data["edit_id"]
        )
        result_word = "изменено"
    else:
        await db_execute("""
            INSERT INTO reminders (
                name, message, time, destination, topic_id, user_id, mention_all, enabled
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,TRUE)
        """,
            data["name"], data["message"], data["time"], data["destination"],
            data["topic_id"], message.from_user.id, mention_all
        )
        result_word = "создано"

    await state.clear()

    await message.answer(
        f"✅ <b>Напоминание {result_word}!</b>\n\n"
        f"Название: {data['name']}\n"
        f"Время: {data['time']}\n"
        f"Куда: {data['destination']}\n"
        f"Упоминать всех: "
        f"{'да' if mention_all else 'нет'}"
    )


@dp.callback_query(F.data == "rem_list")
async def reminder_list(
    callback: CallbackQuery
):

    if not await check_permission(
        callback.from_user.id,
        "can_reminders"
    ):
        await callback.answer(
            "Нет прав",
            show_alert=True
        )
        return

    rows = await db_fetch("""
        SELECT *
        FROM reminders
        ORDER BY id DESC
    """)

    if not rows:

        await callback.message.answer(
            "📭 Напоминаний нет."
        )

        await callback.answer()
        return

    for row in rows:

        status = "🟢" if row["enabled"] else "🔴"

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✏️ Изменить",
                        callback_data=f"rem_edit:{row['id']}"
                    ),
                    InlineKeyboardButton(
                        text="🔄 Вкл/выкл",
                        callback_data=f"rem_toggle:{row['id']}"
                    ),
                    InlineKeyboardButton(
                        text="🗑 Удалить",
                        callback_data=f"rem_delete:{row['id']}"
                    )
                ]
            ]
        )

        await callback.message.answer(
            f"{status} <b>{row['name']}</b>\n\n"
            f"⏰ {row['time']}\n"
            f"📝 {row['message']}\n"
            f"📍 {row['destination']}\n"
            f"👥 Упоминать всех: "
            f"{'да' if row['mention_all'] else 'нет'}",
            reply_markup=kb
        )

    await callback.answer()


@dp.callback_query(F.data.startswith("rem_edit:"))
async def reminder_edit(callback: CallbackQuery, state: FSMContext):
    if not await check_permission(callback.from_user.id, "can_reminders"):
        await callback.answer("Нет прав", show_alert=True)
        return
    reminder_id = int(callback.data.split(":")[1])
    row = await db_fetchrow("SELECT id FROM reminders WHERE id = $1", reminder_id)
    if not row:
        await callback.answer("Напоминание не найдено", show_alert=True)
        return
    await state.clear()
    await state.update_data(edit_id=reminder_id)
    await state.set_state(ReminderForm.name)
    await callback.message.answer(
        f"✏️ Изменение напоминания #{reminder_id}.\n"
        "Введи новое название. Далее бот попросит текст, время, место и упоминания."
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("rem_toggle:"))
async def reminder_toggle(
    callback: CallbackQuery
):

    if not await check_permission(
        callback.from_user.id,
        "can_reminders"
    ):
        await callback.answer(
            "Нет прав",
            show_alert=True
        )
        return

    reminder_id = int(
        callback.data.split(":")[1]
    )

    await db_execute("""
        UPDATE reminders
        SET enabled = NOT enabled
        WHERE id = $1
    """, reminder_id)

    await callback.answer(
        "Статус изменён."
    )


@dp.callback_query(F.data.startswith("rem_delete:"))
async def reminder_delete(
    callback: CallbackQuery
):

    if not await check_permission(
        callback.from_user.id,
        "can_reminders"
    ):
        await callback.answer(
            "Нет прав",
            show_alert=True
        )
        return

    reminder_id = int(
        callback.data.split(":")[1]
    )

    await db_execute("""
        DELETE FROM reminders
        WHERE id = $1
    """, reminder_id)

    await callback.message.edit_reply_markup(
        reply_markup=None
    )

    await callback.answer(
        "Напоминание удалено."
    )


# ============================================================
# REMINDER WORKER
# ============================================================

_last_reminder_minute = None


async def send_reminder(row):

    destination = row["destination"]

    text = (
        f"⏰ <b>{row['name']}</b>\n\n"
        f"{row['message']}"
    )

    if row["mention_all"]:
        known_users = await db_fetch("""
            SELECT user_id, first_name, username
            FROM bot_users
            ORDER BY user_id
        """)
        mention_links = []
        for member in known_users[:70]:
            label = member["first_name"] or member["username"] or str(member["user_id"])
            label = str(label).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            mention_links.append(f'<a href="tg://user?id={member["user_id"]}">{label}</a>')
        people = " ".join(mention_links)
        text = "📢 <b>ВНИМАНИЕ ВСЕМ</b>\n" + (people + "\n\n" if people else "\n") + text

    try:

        if destination == "группа":

            kwargs = {
                "chat_id": GROUP_ID,
                "text": text
            }

            if row["topic_id"]:
                kwargs["message_thread_id"] = row["topic_id"]

            await bot.send_message(**kwargs)

        elif destination == "личка":

            await bot.send_message(
                chat_id=row["topic_id"],
                text=text
            )

    except Exception as e:

        logger.exception(
            "Ошибка отправки reminder #%s: %s",
            row["id"],
            e
        )


async def reminder_worker():

    global _last_reminder_minute

    while True:

        try:

            bot_tz = await get_bot_timezone()
            now = datetime.now(bot_tz)
            current_hm = now.strftime("%H:%M")

            if current_hm != _last_reminder_minute:

                rows = await db_fetch("""
                    SELECT *
                    FROM reminders
                    WHERE enabled = TRUE
                      AND time = $1
                """, current_hm)

                for row in rows:
                    await send_reminder(row)

                _last_reminder_minute = current_hm

        except Exception as e:

            logger.exception(
                "reminder_worker: %s",
                e
            )

        await asyncio.sleep(20)


# ============================================================
# GOOGLE SHEETS
# ============================================================

def google_client():

    if not GOOGLE_AVAILABLE:
        return None

    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        return None

    try:

        info = json.loads(
            GOOGLE_SERVICE_ACCOUNT_JSON
        )

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]

        credentials = Credentials.from_service_account_info(
            info,
            scopes=scopes
        )

        return gspread.authorize(credentials)

    except Exception as e:

        logger.error(
            "Google credentials error: %s",
            e
        )

        return None


def sync_google_sheets_sync(applications, reports, reminders, admins, logs, bank, users):

    if not GOOGLE_SHEET_ID:
        return

    client = google_client()

    if not client:
        return

    try:

        spreadsheet = client.open_by_key(
            GOOGLE_SHEET_ID
        )

        # ------------------------------------------------
        # APPLICATIONS
        # ------------------------------------------------

        try:
            ws = spreadsheet.worksheet(
                "Заявки"
            )
        except Exception:
            ws = spreadsheet.add_worksheet(
                title="Заявки",
                rows=1000,
                cols=15
            )

        rows = [
            [
                "ID",
                "User ID",
                "Username",
                "Ник",
                "Ранг",
                "Организация",
                "Ранг организации",
                "Зам",
                "Статус",
                "Создано"
            ]
        ]

        for row in applications:

            rows.append([
                str(row["id"]),
                str(row["user_id"]),
                str(row["username"] or ""),
                str(row["nickname"] or ""),
                str(row["family_rank"] or ""),
                str(row["organization"] or ""),
                str(row["organization_rank"] or ""),
                str(row["inviter"] or ""),
                str(row["status"] or ""),
                str(row["created_at"])
            ])

        ws.clear()

        # Новый синтаксис gspread
        ws.update(
            range_name="A1",
            values=rows
        )

        # ------------------------------------------------
        # REPORTS
        # ------------------------------------------------

        try:
            report_ws = spreadsheet.worksheet(
                "Report"
            )
        except Exception:
            report_ws = spreadsheet.add_worksheet(
                title="Report",
                rows=1000,
                cols=8
            )

        report_rows = [[
            "ID",
            "User ID",
            "Username",
            "Текст",
            "Статус",
            "Дата"
        ]]

        for row in reports:

            report_rows.append([
                str(row["id"]),
                str(row["user_id"]),
                str(row["username"] or ""),
                str(row["text"] or ""),
                str(row["status"] or ""),
                str(row["created_at"])
            ])

        report_ws.clear()

        report_ws.update(
            range_name="A1",
            values=report_rows
        )

        extra_sheets = {
            "Напоминания": (
                ["ID", "Название", "Текст", "Время", "Куда", "Тема/ID", "Упоминать", "Включено", "Создано"],
                [[str(r["id"]), str(r["name"] or ""), str(r["message"] or ""), str(r["time"] or ""),
                  str(r["destination"] or ""), str(r["topic_id"] or r["user_id"] or ""),
                  str(r["mention_all"]), str(r["enabled"]), str(r["created_at"])] for r in reminders]
            ),
            "Администраторы": (
                ["User ID", "Username", "Владелец", "Заявки", "Объявления", "Report", "Напоминания", "Сбор", "Права админов"],
                [[str(r["user_id"]), str(r["username"] or ""), str(r["is_owner"]),
                  str(r["can_applications"]), str(r["can_announcements"]), str(r["can_reports"]),
                  str(r["can_reminders"]), str(r["can_gather"]), str(r["can_admins"])] for r in admins]
            ),
            "Журнал": (
                ["ID", "User ID", "Username", "Действие", "Детали", "Дата"],
                [[str(r["id"]), str(r["user_id"] or ""), str(r["username"] or ""),
                  str(r["action"] or ""), str(r["details"] or ""), str(r["created_at"])] for r in logs]
            ),
            "Банк замов": (
                ["ID", "Зам", "Приглашённый User ID", "Сумма", "Действие", "Дата"],
                [[str(r["id"]), str(r["inviter"] or ""), str(r["invited_user_id"] or ""),
                  str(r["amount"]), str(r["action"] or ""), str(r["created_at"])] for r in bank]
            ),
            "Участники бота": (
                ["User ID", "Username", "Имя", "Фамилия", "Создан", "Обновлён"],
                [[str(r["user_id"]), str(r["username"] or ""), str(r["first_name"] or ""),
                  str(r["last_name"] or ""), str(r["created_at"]), str(r["updated_at"])] for r in users]
            ),
        }
        for title, (headers, body) in extra_sheets.items():
            try:
                extra_ws = spreadsheet.worksheet(title)
            except Exception:
                extra_ws = spreadsheet.add_worksheet(title=title, rows=1000, cols=max(10, len(headers)))
            extra_ws.clear()
            extra_ws.update(range_name="A1", values=[headers] + body)

        logger.info(
            "Google Sheets synchronized"
        )

    except Exception as e:

        logger.exception(
            "Google Sheets sync error: %s",
            e
        )


async def sync_google_sheets():
    if not GOOGLE_SHEET_ID or not GOOGLE_AVAILABLE:
        return
    try:
        applications = await db_fetch("""
            SELECT * FROM applications ORDER BY id DESC
        """)
        reports = await db_fetch("SELECT * FROM reports ORDER BY id DESC")
        reminders = await db_fetch("SELECT * FROM reminders ORDER BY id DESC")
        admins = await db_fetch("SELECT * FROM admins ORDER BY is_owner DESC, user_id")
        logs = await db_fetch("SELECT * FROM bot_logs ORDER BY id DESC LIMIT 2000")
        bank = await db_fetch("SELECT * FROM zam_bank ORDER BY id DESC")
        users = await db_fetch("SELECT * FROM bot_users ORDER BY user_id")
        await asyncio.to_thread(sync_google_sheets_sync, applications, reports, reminders, admins, logs, bank, users)
    except Exception as e:
        logger.exception("Google Sheets async sync error: %s", e)


# ============================================================
# OWNER SETTINGS: TIMEZONE
# ============================================================

@dp.message(F.text == "🌍 Часовой пояс")
async def timezone_menu(message: Message):
    if not await is_owner(message.from_user.id):
        await message.answer("❌ Настраивать часовой пояс может только владелец.")
        return
    row = await db_fetchrow("SELECT value FROM bot_settings WHERE key = 'timezone'")
    current = row["value"] if row else TIMEZONE
    await message.answer(
        f"🌍 Текущий часовой пояс: <code>{current}</code>\n"
        "Изменить: <code>/timezone Europe/Moscow</code>\n"
        "Пример другого пояса: <code>Europe/Amsterdam</code>."
    )

@dp.message(Command("timezone"))
async def timezone_set(message: Message):
    if not await is_owner(message.from_user.id):
        await message.answer("❌ Только владелец может менять часовой пояс.")
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        row = await db_fetchrow("SELECT value FROM bot_settings WHERE key = 'timezone'")
        current = row["value"] if row else TIMEZONE
        await message.answer(f"Использование: <code>/timezone Europe/Moscow</code>\nТекущий: <code>{current}</code>")
        return
    name = parts[1].strip()
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        await message.answer("❌ Неизвестный часовой пояс. Пример: <code>Europe/Moscow</code>.")
        return
    await db_execute(
        """INSERT INTO bot_settings(key, value) VALUES ('timezone', $1)
           ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value""",
        name
    )
    await log_action(message.from_user.id, message.from_user.username or "", "timezone_changed", name)
    await message.answer(f"✅ Часовой пояс установлен: <code>{name}</code>")

# ============================================================
# ZAM BANK
# ============================================================

@dp.message(F.text == "🏦 Банк замов")
async def zam_bank_menu(message: Message):
    if not await is_owner(message.from_user.id):
        await message.answer("❌ Раздел доступен только владельцу.")
        return
    rows = await db_fetch("""
        SELECT inviter, COUNT(*) FILTER (WHERE action = 'credited') AS entries,
               COALESCE(SUM(amount), 0) AS total
        FROM zam_bank
        GROUP BY inviter
        ORDER BY total DESC, inviter
    """)
    text = "🏦 <b>Банк замов</b>\n\n"
    if not rows:
        text += "Начислений пока нет."
    else:
        for row in rows:
            text += f"👤 {row['inviter']}: {row['entries']} начисл. — {row['total']:,}\n"
    await message.answer(text)

# ============================================================
# /AHELP
# ============================================================

@dp.message(Command("ahelp"))
async def ahelp(message: Message):

    if message.from_user.id != OWNER_ID:
        await message.answer(
            "❌ Эта команда доступна только владельцу."
        )
        return

    await message.answer(
        "👑 <b>ПОЛНЫЙ СПИСОК КОМАНД</b>\n\n"

        "<b>Основные:</b>\n"
        "/start — главное меню\n"
        "/myid — узнать свой Telegram ID\n"
        "/ping — реальный ping Telegram API\n"
        "/кто — информация о пользователе "
        "ответом на его сообщение\n"
        "/kto — то же самое\n\n"

        "<b>Администрирование:</b>\n"
        "/add_admin ID — добавить администратора\n"
        "/del_admin ID — удалить администратора\n"
        "/set_admin_permission ID право on/off — настроить права\n"
        "/timezone Europe/Moscow — часовой пояс напоминаний\n"
        "/ahelp — эта справка\n\n"

        "<b>Разделы меню:</b>\n"
        "📝 Заполнить анкету\n"
        "👤 Мой профиль\n"
        "📋 Моя заявка\n"
        "📋 Управление заявками\n"
        "📨 Report\n"
        "📢 Объявления\n"
        "📢 Общий сбор\n"
        "👥 Список участников\n"
        "🟢 Статус бота\n"
        "👑 Администрирование\n"
        "⏰ Напоминания\n"
        "📜 Журнал действий"
    )


# ============================================================
# COMMAND MENU
# ============================================================

async def set_commands():

    from aiogram.types import (
        BotCommand,
        BotCommandScopeChat
    )

    commands = [
        BotCommand(
            command="start",
            description="Главное меню"
        ),
        BotCommand(
            command="myid",
            description="Мой Telegram ID"
        ),
        BotCommand(
            command="ping",
            description="Проверить ping"
        ),
        BotCommand(
            command="кто",
            description="Информация о пользователе"
        ),
    ]

    try:

        await bot.set_my_commands(
            commands
        )

        await bot.set_my_commands(
            commands + [
                BotCommand(
                    command="ahelp",
                    description="Полная справка"
                ),
                BotCommand(
                    command="add_admin",
                    description="Добавить администратора"
                ),
                BotCommand(
                    command="del_admin",
                    description="Удалить администратора"
                ),
            ],
            scope=BotCommandScopeChat(
                chat_id=OWNER_ID
            )
        )

    except Exception as e:

        logger.warning(
            "set_commands: %s",
            e
        )


# ============================================================
# ERROR HANDLER
# ============================================================

@dp.errors()
async def global_error(event):

    logger.exception(
        "Unhandled bot error: %s",
        event.exception
    )


# ============================================================
# MAIN
# ============================================================

async def main():

    logger.info(
        "Starting %s",
        BOT_NAME
    )

    logger.info(
        "GROUP_ID = %s",
        GROUP_ID
    )

    logger.info(
        "TOPIC_ID = %s",
        TOPIC_ID
    )

    await db_init()

    if GOOGLE_SHEET_ID:
        await sync_google_sheets()

    await set_commands()

    # Удаляем webhook перед polling
    try:
        await bot.delete_webhook(
            drop_pending_updates=True
        )
    except Exception as e:
        logger.warning(
            "delete_webhook: %s",
            e
        )

    # Flask запускается отдельным потоком
    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True
    )

    flask_thread.start()

    logger.info(
        "Flask health server started on port %s",
        PORT
    )

    # Worker напоминаний
    asyncio.create_task(
        reminder_worker()
    )

    # Проверка Google
    if GOOGLE_SHEET_ID:
        logger.info(
            "Google Sheets configured"
        )
    else:
        logger.warning(
            "GOOGLE_SHEET_ID is not configured"
        )

    me = await bot.get_me()

    logger.info(
        "Bot @%s started",
        me.username
    )

    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types()
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    try:
        asyncio.run(main())

    except KeyboardInterrupt:

        logger.info(
            "Bot stopped manually"
        )

    except Exception as e:

        logger.exception(
            "FATAL ERROR: %s",
            e
        )
