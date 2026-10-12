
import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import psycopg2
from psycopg2.extras import RealDictCursor
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, BotCommand,
    BotCommandScopeDefault, BotCommandScopeChat,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)

from flask import Flask
from threading import Thread

# ================= CONFIG =================

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TG_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SUPER_ADMIN = int(os.getenv("SUPER_ADMIN_ID", "6166697485"))
GROUP_ID = int(os.getenv("GROUP_ID", "0"))
TOPIC_ID = int(os.getenv("ANNOUNCE_TOPIC_ID", "126387"))
TIMEZONE = os.getenv("BOT_TIMEZONE", "Europe/Moscow")
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "staff-grand-bot")
PORT = int(os.getenv("PORT", "8000"))

if not BOT_TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN в Render Environment")

if not DATABASE_URL:
    raise RuntimeError("Не задан DATABASE_URL. Добавь PostgreSQL в Render.")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("staff-grand-bot")

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

web_app = Flask(__name__)

@web_app.get("/")
def health():
    return "Bot is running!", 200

def run_web():
    web_app.run(host="0.0.0.0", port=PORT, use_reloader=False)

Thread(target=run_web, daemon=True).start()


# ================= DATABASE =================

def connect_db():
    return psycopg2.connect(DATABASE_URL, connect_timeout=10)

def init_db():
    with connect_db() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                profile JSONB NOT NULL DEFAULT '{}'::jsonb,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_admins (
                user_id BIGINT PRIMARY KEY,
                permissions JSONB NOT NULL DEFAULT '{}'::jsonb
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_logs (
                id BIGSERIAL PRIMARY KEY,
                actor_id BIGINT,
                action TEXT NOT NULL,
                details TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_reports (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                username TEXT,
                message TEXT NOT NULL,
                status TEXT DEFAULT 'new',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_reminders (
                id BIGSERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                time_hhmm TEXT NOT NULL,
                enabled BOOLEAN DEFAULT TRUE,
                last_sent_date DATE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        cur.execute("""
            INSERT INTO bot_admins(user_id, permissions)
            VALUES (%s, '{"all": true}'::jsonb)
            ON CONFLICT(user_id) DO NOTHING
        """, (SUPER_ADMIN,))
        cur.execute("""
            INSERT INTO bot_settings(key, value)
            VALUES ('reminders_enabled', 'true')
            ON CONFLICT(key) DO NOTHING
        """)

def log_action(user_id, action, details=""):
    try:
        with connect_db() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO bot_logs(actor_id, action, details) VALUES (%s,%s,%s)",
                (user_id, action, str(details)[:3000])
            )
    except Exception:
        log.exception("Не удалось записать журнал")

def get_user(user_id):
    with connect_db() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM bot_users WHERE user_id=%s", (user_id,))
        return cur.fetchone()

def get_admins():
    with connect_db() as conn, conn.cursor() as cur:
        cur.execute("SELECT user_id FROM bot_admins")
        return [r[0] for r in cur.fetchall()]

def admin_can(user_id, permission):
    if user_id == SUPER_ADMIN:
        return True
    with connect_db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT permissions FROM bot_admins WHERE user_id=%s",
            (user_id,)
        )
        row = cur.fetchone()
    if not row:
        return False
    perms = row[0]
    if isinstance(perms, str):
        perms = json.loads(perms)
    return perms.get("all") is True or perms.get(permission) is True

def set_setting(key, value):
    with connect_db() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO bot_settings(key,value) VALUES (%s,%s)
            ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value
        """, (key, str(value)))

def get_setting(key, default=""):
    with connect_db() as conn, conn.cursor() as cur:
        cur.execute("SELECT value FROM bot_settings WHERE key=%s", (key,))
        row = cur.fetchone()
    return row[0] if row else default


# ================= GOOGLE SHEETS =================

def sync_google_sheets():
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        return

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        credentials_data = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        credentials = Credentials.from_service_account_info(
            credentials_data,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]
        )
        client = gspread.authorize(credentials)
        spreadsheet = client.open(GOOGLE_SHEET_NAME)

        tables = [
            (
                "Анкеты",
                "SELECT user_id,username,full_name,profile,status,created_at "
                "FROM bot_users ORDER BY created_at"
            ),
            (
                "Журнал",
                "SELECT actor_id,action,details,created_at "
                "FROM bot_logs ORDER BY id DESC LIMIT 1000"
            ),
            (
                "Report",
                "SELECT user_id,username,message,status,created_at "
                "FROM bot_reports ORDER BY id DESC"
            ),
            (
                "Напоминания",
                "SELECT id,title,body,time_hhmm,enabled "
                "FROM bot_reminders ORDER BY id"
            )
        ]

        with connect_db() as conn:
            for title, query in tables:
                with conn.cursor() as cur:
                    cur.execute(query)
                    rows = cur.fetchall()
                    headers = [d[0] for d in cur.description]

                values = [headers]
                for row in rows:
                    values.append([
                        json.dumps(value, ensure_ascii=False, default=str)
                        if isinstance(value, (dict, list))
                        else str(value) if value is not None else ""
                        for value in row
                    ])

                try:
                    sheet = spreadsheet.worksheet(title)
                except gspread.WorksheetNotFound:
                    sheet = spreadsheet.add_worksheet(
                        title=title,
                        rows=max(100, len(values) + 10),
                        cols=max(10, len(headers) + 2)
                    )

                sheet.clear()
                sheet.update(range_name="A1", values=values)

    except Exception:
        log.exception("Ошибка синхронизации Google Sheets")

async def sync_sheets():
    await asyncio.to_thread(sync_google_sheets)


# ================= KEYBOARDS =================

def main_keyboard(uid):
    rows = [
        [KeyboardButton(text="📝 Заполнить анкету"),
         KeyboardButton(text="👤 Мой профиль")],
        [KeyboardButton(text="📨 Report / обращения")]
    ]

    if admin_can(uid, "applications"):
        rows.append([
            KeyboardButton(text="📋 Управление заявками"),
            KeyboardButton(text="⏳ Активные заявки")
        ])

    if admin_can(uid, "announcements"):
        rows.append([KeyboardButton(text="📢 Объявление")])

    if admin_can(uid, "gathering"):
        rows.append([
            KeyboardButton(text="📢 Общий сбор"),
            KeyboardButton(text="🛑 Остановить сбор")
        ])

    if admin_can(uid, "reminders"):
        rows.append([KeyboardButton(text="⏰ Напоминания")])

    if uid == SUPER_ADMIN:
        rows.append([
            KeyboardButton(text="👑 Администрирование"),
            KeyboardButton(text="📜 Журнал действий")
        ])

    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

def decision_keyboard(uid):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Принять", callback_data=f"app:accept:{uid}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"app:reject:{uid}")
    ]])


# ================= STATES =================

class Form(StatesGroup):
    nickname = State()
    rank = State()
    organization = State()
    org_rank = State()
    inviter = State()

class ReportForm(StatesGroup):
    body = State()

class AnnouncementForm(StatesGroup):
    body = State()

class ReminderForm(StatesGroup):
    title = State()
    body = State()
    time = State()

RANKS = [
    "НОВИЧОК", "БандИТ", "Стрелок", "ФРАЕР", "ОХРАНИК",
    "СТ. ОХРАНИК", "РЕШАЛО", "ПОЛОЖЕНЕЦ", "ВОР"
]

ORGANIZATIONS = [
    "Правительство", "Воинская часть", "Больница Арзамас",
    "Больница Южный", "Полиция Арзамас", "Полиция Южный",
    "ФСБ", "МВД-А", "МВД-Ю", "МЗ-А", "МЗ-Ю",
    "Банда", "Не в организации"
]


# ================= COMMANDS =================

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 <b>Добро пожаловать в Staff Grand Bot!</b>\nВыбери действие:",
        reply_markup=main_keyboard(message.from_user.id)
    )

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📖 <b>Команды</b>\n/start — меню\n/help — справка\n"
        "/myid — Telegram ID\n/ping — проверка связи"
    )

@dp.message(Command("myid"))
async def cmd_myid(message: Message):
    await message.answer(f"🆔 Твой ID: <code>{message.from_user.id}</code>")

@dp.message(Command("ping"))
async def cmd_ping(message: Message):
    started = time.perf_counter()
    try:
        me = await bot.get_me()
        api_ms = (time.perf_counter() - started) * 1000
        send_started = time.perf_counter()
        sent = await message.answer("🏓 Проверка...")
        send_ms = (time.perf_counter() - send_started) * 1000
        await sent.edit_text(
            f"🏓 <b>Пинг</b>\nTelegram API: <code>{api_ms:.0f} мс</code>\n"
            f"Отправка сообщения: <code>{send_ms:.0f} мс</code>\n"
            f"Бот: @{me.username}"
        )
    except Exception as exc:
        await message.answer(f"❌ Ошибка Telegram API: {type(exc).__name__}")

@dp.message(Command("ahelp"))
async def cmd_ahelp(message: Message):
    if message.from_user.id != SUPER_ADMIN:
        return await message.answer("⛔ Команда доступна только владельцу.")
    await message.answer(
        "<b>👑 Команды владельца</b>\n/start — меню\n/help — справка\n"
        "/myid — мой ID\n/ping — пинг\n/ahelp — список команд\n"
        "/add_admin ID — добавить администратора\n"
        "/remove_admin ID — удалить администратора\n"
        "/sync — синхронизация таблиц"
    )

@dp.message(Command("add_admin"))
async def cmd_add_admin(message: Message):
    if message.from_user.id != SUPER_ADMIN:
        return await message.answer("⛔ Только владелец.")
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        return await message.answer("Пример: <code>/add_admin 123456789</code>")

    uid = int(parts[1])
    permissions = {
        "applications": True,
        "announcements": True,
        "gathering": True,
        "reminders": True,
        "reports": True
    }
    with connect_db() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO bot_admins(user_id,permissions)
            VALUES (%s,%s::jsonb)
            ON CONFLICT(user_id) DO UPDATE
            SET permissions=EXCLUDED.permissions
        """, (uid, json.dumps(permissions)))
    log_action(message.from_user.id, "admin_added", uid)
    await message.answer(f"✅ Администратор {uid} добавлен.")
    await sync_sheets()

@dp.message(Command("remove_admin"))
async def cmd_remove_admin(message: Message):
    if message.from_user.id != SUPER_ADMIN:
        return await message.answer("⛔ Только владелец.")
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        return await message.answer("Пример: <code>/remove_admin 123456789</code>")
    uid = int(parts[1])
    if uid == SUPER_ADMIN:
        return await message.answer("Нельзя удалить владельца.")
    with connect_db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM bot_admins WHERE user_id=%s", (uid,))
    log_action(message.from_user.id, "admin_removed", uid)
    await message.answer("✅ Администратор удалён.")
    await sync_sheets()

@dp.message(Command("sync"))
async def cmd_sync(message: Message):
    if message.from_user.id != SUPER_ADMIN:
        return await message.answer("⛔ Только владелец.")
    await sync_sheets()
    await message.answer("✅ Синхронизация завершена. Если Google Sheets настроены, данные обновлены.")


# ================= QUESTIONNAIRE =================

@dp.message(F.text == "📝 Заполнить анкету")
async def form_start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Form.nickname)
    await message.answer("Введи игровой никнейм:")

@dp.message(Form.nickname)
async def form_nickname(message: Message, state: FSMContext):
    if not message.text:
        return await message.answer("Введи ник текстом.")
    await state.update_data(nickname=message.text[:100])
    await state.set_state(Form.rank)
    await message.answer(
        "Выбери ранг семьи:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=x)] for x in RANKS],
            resize_keyboard=True
        )
    )

@dp.message(Form.rank)
async def form_rank(message: Message, state: FSMContext):
    if message.text not in RANKS:
        return await message.answer("Выбери ранг кнопкой.")
    await state.update_data(rank=message.text)
    await state.set_state(Form.organization)
    await message.answer(
        "Выбери организацию:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=x)] for x in ORGANIZATIONS],
            resize_keyboard=True
        )
    )

@dp.message(Form.organization)
async def form_organization(message: Message, state: FSMContext):
    if message.text not in ORGANIZATIONS:
        return await message.answer("Выбери организацию кнопкой.")
    await state.update_data(organization=message.text)
    await state.set_state(Form.org_rank)
    await message.answer("Введи ранг в организации или напиши «Нет».")

@dp.message(Form.org_rank)
async def form_org_rank(message: Message, state: FSMContext):
    if not message.text:
        return await message.answer("Введи ранг текстом.")
    await state.update_data(org_rank=message.text[:100])
    await state.set_state(Form.inviter)
    await message.answer("Кто пригласил тебя? Если никто — напиши «Нет».")

@dp.message(Form.inviter)
async def form_inviter(message: Message, state: FSMContext):
    if not message.text:
        return await message.answer("Введи ник пригласившего или «Нет».")
    profile = await state.get_data()
    profile["inviter"] = message.text[:100]
    user = message.from_user

    with connect_db() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO bot_users(user_id,username,full_name,profile,status)
            VALUES (%s,%s,%s,%s::jsonb,'pending')
            ON CONFLICT(user_id) DO UPDATE SET
                username=EXCLUDED.username,
                full_name=EXCLUDED.full_name,
                profile=EXCLUDED.profile,
                status='pending',
                updated_at=NOW()
        """, (
            user.id, user.username, user.full_name,
            json.dumps(profile, ensure_ascii=False)
        ))

    await state.clear()
    await message.answer(
        "✅ Анкета отправлена на рассмотрение.",
        reply_markup=main_keyboard(user.id)
    )

    text = (
        "📋 <b>Новая анкета</b>\n"
        f"Имя: {user.full_name}\nID: <code>{user.id}</code>\n"
        f"Ник: {profile.get('nickname')}\n"
        f"Ранг: {profile.get('rank')}\n"
        f"Организация: {profile.get('organization')}\n"
        f"Ранг организации: {profile.get('org_rank')}\n"
        f"Пригласил: {profile.get('inviter')}"
    )
    for admin_id in get_admins():
        try:
            await bot.send_message(admin_id, text, reply_markup=decision_keyboard(user.id))
        except Exception:
            log.exception("Не удалось отправить анкету админу %s", admin_id)

    log_action(user.id, "application_submitted", profile.get("nickname", ""))
    await sync_sheets()

@dp.message(F.text == "👤 Мой профиль")
async def profile_view(message: Message):
    user = get_user(message.from_user.id)
    if not user:
        return await message.answer("Анкета не найдена. Нажми «📝 Заполнить анкету».")
    p = user["profile"]
    if isinstance(p, str):
        p = json.loads(p)
    await message.answer(
        f"👤 <b>Мой профиль</b>\nНик: {p.get('nickname','—')}\n"
        f"Ранг: {p.get('rank','—')}\nОрганизация: {p.get('organization','—')}\n"
        f"Ранг организации: {p.get('org_rank','—')}\n"
        f"Пригласил: {p.get('inviter','—')}\nСтатус: {user['status']}"
    )

@dp.callback_query(F.data.startswith("app:"))
async def application_decision(callback: CallbackQuery):
    if not admin_can(callback.from_user.id, "applications"):
        return await callback.answer("Недостаточно прав.", show_alert=True)

    _, decision, uid_text = callback.data.split(":")
    uid = int(uid_text)
    status = "accepted" if decision == "accept" else "rejected"

    with connect_db() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE bot_users SET status=%s,updated_at=NOW() WHERE user_id=%s",
            (status, uid)
        )

    try:
        await bot.send_message(
            uid,
            "✅ Твоя анкета принята!" if status == "accepted"
            else "❌ Твоя анкета отклонена."
        )
    except Exception:
        pass

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Решение сохранено.")
    log_action(callback.from_user.id, "application_decision", f"{uid}:{status}")
    await sync_sheets()

@dp.message(F.text.in_({"📋 Управление заявками", "⏳ Активные заявки"}))
async def applications_list(message: Message):
    if not admin_can(message.from_user.id, "applications"):
        return await message.answer("⛔ Недостаточно прав.")
    with connect_db() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT user_id,full_name,profile,status FROM bot_users
            WHERE status='pending' ORDER BY created_at LIMIT 30
        """)
        rows = cur.fetchall()
    if not rows:
        return await message.answer("📭 Активных заявок нет.")
    for row in rows:
        p = row["profile"]
        if isinstance(p, str):
            p = json.loads(p)
        await message.answer(
            f"📋 <b>Анкета</b>\nID: <code>{row['user_id']}</code>\n"
            f"Имя: {row['full_name']}\nНик: {p.get('nickname','—')}\n"
            f"Ранг: {p.get('rank','—')}\nОрганизация: {p.get('organization','—')}",
            reply_markup=decision_keyboard(row["user_id"])
        )


# ================= REPORT =================

@dp.message(F.text == "📨 Report / обращения")
async def report_start(message: Message, state: FSMContext):
    await state.set_state(ReportForm.body)
    await message.answer("Напиши обращение одним сообщением:")

@dp.message(ReportForm.body)
async def report_submit(message: Message, state: FSMContext):
    if not message.text:
        return await message.answer("Отправь обращение текстом.")
    user = message.from_user
    with connect_db() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO bot_reports(user_id,username,message)
            VALUES (%s,%s,%s) RETURNING id
        """, (user.id, user.username, message.text[:4000]))
        report_id = cur.fetchone()[0]

    await state.clear()
    await message.answer("✅ Обращение отправлено администраторам.", reply_markup=main_keyboard(user.id))
    for admin_id in get_admins():
        try:
            await bot.send_message(
                admin_id,
                f"📨 <b>Report #{report_id}</b>\n"
                f"От: {user.full_name} (<code>{user.id}</code>)\n\n"
                f"{message.text[:3500]}"
            )
        except Exception:
            pass
    log_action(user.id, "report_submitted", report_id)
    await sync_sheets()


# ================= ANNOUNCEMENTS =================

class AnnouncementForm(StatesGroup):
    body = State()

@dp.message(F.text == "📢 Объявление")
async def announcement_start(message: Message, state: FSMContext):
    if not admin_can(message.from_user.id, "announcements"):
        return await message.answer("⛔ Недостаточно прав.")
    await state.set_state(AnnouncementForm.body)
    await message.answer("Введи текст объявления:")

@dp.message(AnnouncementForm.body)
async def announcement_send(message: Message, state: FSMContext):
    if not admin_can(message.from_user.id, "announcements"):
        await state.clear()
        return await message.answer("⛔ Недостаточно прав.")
    if not GROUP_ID:
        return await message.answer("❌ Задай GROUP_ID в Render Environment.")
    try:
        await bot.send_message(
            GROUP_ID,
            f"📢 <b>Объявление</b>\n\n{message.text}",
            message_thread_id=TOPIC_ID or None
        )
        await state.clear()
        await message.answer("✅ Объявление отправлено.", reply_markup=main_keyboard(message.from_user.id))
        log_action(message.from_user.id, "announcement_sent", (message.text or "")[:200])
        await sync_sheets()
    except Exception as exc:
        await message.answer(f"❌ Не удалось отправить: {type(exc).__name__}")


# ================= GATHERING =================

gather_tasks = {}
gather_active = set()

async def start_gather_from_button(message: Message):
    uid = message.from_user.id
    if not admin_can(uid, "gathering"):
        return await message.answer("⛔ Недостаточно прав.")
    if not GROUP_ID:
        return await message.answer("❌ Задай GROUP_ID в Render Environment.")
    if uid in gather_active:
        return await message.answer("Сбор уже идёт.")

    gather_active.add(uid)

    async def worker():
        try:
            for number in range(6):
                if uid not in gather_active:
                    break
                await bot.send_message(
                    GROUP_ID,
                    f"📢 <b>ОБЩИЙ СБОР</b>\nВсе участники, просьба собраться! ({number + 1}/6)",
                    message_thread_id=TOPIC_ID or None
                )
                await asyncio.sleep(15)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Ошибка общего сбора")
        finally:
            gather_active.discard(uid)
            gather_tasks.pop(uid, None)

    gather_tasks[uid] = asyncio.create_task(worker())
    await message.answer("📢 Общий сбор запущен примерно на 1–2 минуты.")
    log_action(uid, "gather_started")

@dp.message(F.text == "📢 Общий сбор")
async def gather_btn(message: Message):
    await start_gather_from_button(message)

@dp.message(F.text == "🛑 Остановить сбор")
async def gather_stop_btn(message: Message):
    uid = message.from_user.id
    if not admin_can(uid, "gathering"):
        return await message.answer("⛔ Недостаточно прав.")
    gather_active.discard(uid)
    task = gather_tasks.get(uid)
    if task and not task.done():
        task.cancel()
    await message.answer("🛑 Общий сбор остановлен.")


# ================= REMINDERS =================

@dp.message(F.text == "⏰ Напоминания")
async def reminder_menu(message: Message):
    if not admin_can(message.from_user.id, "reminders"):
        return await message.answer("⛔ Недостаточно прав.")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать", callback_data="rem:new")],
        [InlineKeyboardButton(text="📋 Список", callback_data="rem:list")],
        [InlineKeyboardButton(text="🔔 Вкл/выкл", callback_data="rem:toggle")]
    ])
    await message.answer(f"⏰ Напоминания. Часовой пояс: {TIMEZONE}", reply_markup=keyboard)

@dp.callback_query(F.data == "rem:new")
async def reminder_new(callback: CallbackQuery, state: FSMContext):
    if not admin_can(callback.from_user.id, "reminders"):
        return await callback.answer("Недостаточно прав.", show_alert=True)
    await state.set_state(ReminderForm.title)
    await callback.message.answer("Название напоминания:")
    await callback.answer()

@dp.message(ReminderForm.title)
async def reminder_title(message: Message, state: FSMContext):
    await state.update_data(title=(message.text or "Напоминание")[:100])
    await state.set_state(ReminderForm.body)
    await message.answer("Текст напоминания:")

@dp.message(ReminderForm.body)
async def reminder_body(message: Message, state: FSMContext):
    await state.update_data(body=(message.text or "")[:3000])
    await state.set_state(ReminderForm.time)
    await message.answer("Время каждый день в формате ЧЧ:ММ, например 15:00:")

@dp.message(ReminderForm.time)
async def reminder_time(message: Message, state: FSMContext):
    value = (message.text or "").strip()
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        return await message.answer("Неверное время. Пример: 15:00")
    data = await state.get_data()
    with connect_db() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO bot_reminders(title,body,time_hhmm) VALUES (%s,%s,%s)",
            (data["title"], data["body"], value)
        )
    await state.clear()
    await message.answer(
        f"✅ Напоминание «{data['title']}» создано на {value}.",
        reply_markup=main_keyboard(message.from_user.id)
    )
    log_action(message.from_user.id, "reminder_created", f"{data['title']} {value}")
    await sync_sheets()

@dp.callback_query(F.data == "rem:list")
async def reminder_list(callback: CallbackQuery):
    if not admin_can(callback.from_user.id, "reminders"):
        return await callback.answer("Недостаточно прав.", show_alert=True)
    with connect_db() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id,title,time_hhmm,enabled FROM bot_reminders ORDER BY id")
        rows = cur.fetchall()
    if not rows:
        await callback.message.answer("Напоминаний нет.")
    else:
        await callback.message.answer("\n".join(
            f"#{r['id']} {r['title']} — {r['time_hhmm']} — {'включено' if r['enabled'] else 'выключено'}"
            for r in rows
        ))
    await callback.answer()

@dp.callback_query(F.data == "rem:toggle")
async def reminder_toggle(callback: CallbackQuery):
    if not admin_can(callback.from_user.id, "reminders"):
        return await callback.answer("Недостаточно прав.", show_alert=True)
    old = get_setting("reminders_enabled", "true").lower() == "true"
    set_setting("reminders_enabled", "false" if old else "true")
    await callback.message.answer("🔕 Напоминания выключены." if old else "🔔 Напоминания включены.")
    await callback.answer()
    await sync_sheets()

def current_time():
    return datetime.now(ZoneInfo(TIMEZONE))

async def scheduled_reminder_worker():
    while True:
        try:
            now = current_time()
            if get_setting("reminders_enabled", "true").lower() == "true":
                with connect_db() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT * FROM bot_reminders
                        WHERE enabled=TRUE AND time_hhmm=%s
                        AND (last_sent_date IS NULL OR last_sent_date < %s)
                    """, (now.strftime("%H:%M"), now.date()))
                    reminders = cur.fetchall()

                for reminder in reminders:
                    if not GROUP_ID:
                        continue
                    try:
                        await bot.send_message(
                            GROUP_ID,
                            f"⏰ <b>{reminder['title']}</b>\n\n{reminder['body']}",
                            message_thread_id=TOPIC_ID or None
                        )
                        with connect_db() as conn, conn.cursor() as cur:
                            cur.execute(
                                "UPDATE bot_reminders SET last_sent_date=%s WHERE id=%s",
                                (now.date(), reminder["id"])
                            )
                        await sync_sheets()
                    except Exception:
                        log.exception("Не удалось отправить напоминание")
        except asyncio.CancelledError:
            return
        except Exception:
            log.exception("Ошибка фоновых напоминаний")
        await asyncio.sleep(30)


# ================= OWNER / LOG =================

@dp.message(F.text == "👑 Администрирование")
async def owner_panel(message: Message):
    if message.from_user.id != SUPER_ADMIN:
        return await message.answer("⛔ Только владелец.")
    await message.answer(
        "👑 <b>Администрирование</b>\n"
        "/add_admin ID — добавить администратора\n"
        "/remove_admin ID — удалить администратора\n"
        "/sync — обновить Google Таблицы\n"
        "/ahelp — команды владельца"
    )

@dp.message(F.text == "📜 Журнал действий")
async def show_logs(message: Message):
    if message.from_user.id != SUPER_ADMIN:
        return await message.answer("⛔ Только владелец.")
    with connect_db() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM bot_logs ORDER BY id DESC LIMIT 20")
        rows = cur.fetchall()
    if not rows:
        return await message.answer("Журнал пуст.")
    text = "<b>📜 Журнал действий</b>\n\n" + "\n".join(
        f"{r['created_at']:%d.%m %H:%M} | {r['actor_id']} | {r['action']} | {r['details'] or ''}"
        for r in rows
    )
    await message.answer(text[:4000])

@dp.message(F.text == "❌ Отмена")
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_keyboard(message.from_user.id))


# ================= COMMAND SCOPES =================

async def set_command_scopes():
    defaults = [
        BotCommand(command="start", description="🏠 Меню"),
        BotCommand(command="help", description="📖 Справка"),
        BotCommand(command="myid", description="🆔 Мой ID")
    ]
    admins = defaults + [BotCommand(command="ping", description="🏓 Пинг")]
    owners = admins + [BotCommand(command="ahelp", description="👑 Команды владельца")]

    try:
        await bot.set_my_commands(defaults, scope=BotCommandScopeDefault())
    except Exception:
        log.exception("Не удалось задать базовые команды")

    for admin_id in get_admins():
        try:
            await bot.set_my_commands(
                admins,
                scope=BotCommandScopeChat(chat_id=int(admin_id))
            )
        except Exception:
            pass

    try:
        await bot.set_my_commands(
            owners,
            scope=BotCommandScopeChat(chat_id=SUPER_ADMIN)
        )
    except Exception:
        log.exception("Не удалось задать команды владельца")


# ================= MAIN =================

async def main():
    init_db()
    await set_command_scopes()
    await bot.delete_webhook(drop_pending_updates=False)
    asyncio.create_task(scheduled_reminder_worker())
    log.info("Бот запускается. Owner ID: %s", SUPER_ADMIN)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Бот остановлен")
