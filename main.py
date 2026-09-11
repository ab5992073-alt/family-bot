import asyncio
import json
import os
from datetime import datetime
from html import escape
import threading

from aiogram import Bot, Dispatcher, F
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

SUPER_ADMIN = 6166697485

ADMIN_IDS = {
    6166697485,
    123456789,
    6863392923,
    1980341141,
}

GROUP_ID = -1002409536359
GROUP_LINK = "https://t.me/+f_eKIP4gwcs0YTcy"
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
# БАЗА ДАННЫХ
# =========================================================

DATA_FILE = "data.json"
LOG_FILE = "bot_activity.log"


def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

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
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


data = load_data()

defaults = {
    "users": {},
    "applications": {},
    "admins": list(ADMIN_IDS),
    "zam_stats": {},
    "zam_data": {},
    "log_notify_enabled": False,
    "admin_usernames": {},
}

changed = False

for key, default in defaults.items():
    if key not in data:
        data[key] = default
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

if changed:
    save_data()


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

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(
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
    try:
        link = await bot.create_chat_invite_link(
            GROUP_ID,
            member_limit=1,
        )

        await bot.send_message(
            user_id,
            f"🔗 <b>Вы приняты в семью!</b>\n\n"
            f"Вступите по ссылке:\n{link.invite_link}\n\n"
            f"Или:\n{GROUP_LINK}",
        )
        return True

    except Exception:
        try:
            await bot.send_message(
                user_id,
                f"🔗 <b>Вы приняты в семью!</b>\n\n"
                f"Вступите:\n{GROUP_LINK}",
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

@dp.callback_query(F.data.startswith("accept:"))
async def accept_app(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет прав!")
        return

    app_id = cb.data.split(":", 1)[1]
    app = data["applications"].get(app_id)

    if not app:
        await cb.answer("❌ Заявка не найдена.")
        return

    if app.get("status") != "pending":
        await cb.answer("ℹ️ Заявка уже обработана.")
        return

    app["status"] = "accepted"
    app.setdefault("history", []).append(
        {
            "action": "accepted",
            "by": cb.from_user.id,
            "created": datetime.now().isoformat(),
        }
    )
    save_data()

    await add_user_to_group(app["user_id"])
    await set_user_nickname(
        app["user_id"],
        app["data"].get("nickname", "Участник"),
    )

    await log_action(
        cb.from_user.id,
        "принял заявку",
        app_id,
    )

    try:
        await bot.send_message(
            app["user_id"],
            "✅ Ваша заявка принята администрацией!",
        )
    except Exception:
        pass

    await cb.answer("✅ Принят")
    await cb.message.edit_reply_markup(reply_markup=None)


@dp.callback_query(F.data.startswith("reject:"))
async def reject_app(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет прав!")
        return

    app_id = cb.data.split(":", 1)[1]
    app = data["applications"].get(app_id)

    if not app:
        await cb.answer("❌ Заявка не найдена.")
        return

    if app.get("status") != "pending":
        await cb.answer("ℹ️ Заявка уже обработана.")
        return

    app["status"] = "rejected"
    app.setdefault("history", []).append(
        {
            "action": "rejected",
            "by": cb.from_user.id,
            "created": datetime.now().isoformat(),
        }
    )
    save_data()

    await remove_user_from_group(app["user_id"])

    await log_action(
        cb.from_user.id,
        "отклонил заявку",
        app_id,
    )

    try:
        await bot.send_message(
            app["user_id"],
            "❌ Ваша заявка отклонена администрацией.",
        )
    except Exception:
        pass

    await cb.answer("❌ Отклонён")
    await cb.message.edit_reply_markup(reply_markup=None)


def application_keyboard(app_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅",
                    callback_data=f"accept:{app_id}",
                ),
                InlineKeyboardButton(
                    text="❌",
                    callback_data=f"reject:{app_id}",
                ),
            ]
        ]
    )


def application_text(app, idx=None):
    u = app["data"]
    prefix = (
        f"⏳ <b>Заявка #{idx}</b>"
        if idx is not None
        else "⏳ <b>Заявка</b>"
    )

    return (
        f"{prefix}\n"
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

        kb = (
            application_keyboard(app_id)
            if status == "pending"
            else None
        )

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

@dp.message(F.text == "🛠 Админка")
async def admin_panel(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return

    await message.answer(
        "👑 <b>Управление администраторами</b>\n\n"
        "Здесь можно добавить или удалить админа.\n"
        "Команды /add_admin и /remove_admin также остаются рабочими.",
        reply_markup=admin_panel_keyboard(),
    )


@dp.callback_query(F.data == "adm:list")
async def adm_list_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True)
        return

    text = "👑 <b>Администраторы</b>\n\n"

    for admin_id in sorted(get_admins()):
        role = "Владелец" if admin_id == SUPER_ADMIN else "Админ"
        text += (
            f"• {escape(get_admin_display(admin_id))} "
            f"— {role}\n"
        )

    await cb.message.answer(text)
    await cb.answer()


@dp.callback_query(F.data == "adm:add")
async def adm_add_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True)
        return

    admin_actions[cb.from_user.id] = "add_admin"
    await cb.message.answer(
        "➕ Введите Telegram username нового админа:\n"
        "<code>@username</code>"
    )
    await cb.answer()


@dp.callback_query(F.data == "adm:remove")
async def adm_remove_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True)
        return

    admin_actions[cb.from_user.id] = "remove_admin"
    await cb.message.answer(
        "➖ Введите Telegram username админа:\n"
        "<code>@username</code>"
    )
    await cb.answer()


# =========================================================
# АДМИНСКИЕ КОМАНДЫ
# =========================================================

@dp.message(Command("add_admin"))
async def add_admin(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return

    args = message.text.split(maxsplit=1)

    if len(args) < 2:
        await message.answer(
            "❌ Формат:\n"
            "/add_admin adm @username\n"
            "/add_admin zam @username Nik: игровой_ник"
        )
        return

    parts = args[1].split()

    if len(parts) < 2:
        await message.answer("❌ Мало аргументов.")
        return

    type_ = parts[0].lower()
    username = parts[1].lstrip("@")

    if type_ == "adm":
        try:
            chat = await bot.get_chat(username)
        except Exception:
            await message.answer(
                f"❌ @{escape(username)} не найден."
            )
            return

        if chat.id in get_admins():
            await message.answer("❌ Уже админ.")
            return

        admins = get_admins()
        admins.add(chat.id)
        save_admins(admins)

        data["admin_usernames"][str(chat.id)] = {
            "username": chat.username or username,
            "full_name": chat.full_name or str(chat.id),
        }
        save_data()

        await message.answer(
            f"✅ Админ @{escape(username)} добавлен."
        )

        try:
            await bot.send_message(
                chat.id,
                "👑 Вы назначены администратором!",
            )
        except Exception:
            pass

        await set_command_scopes()
        return

    if type_ == "zam":
        if len(parts) < 4 or parts[2].lower() != "nik:":
            await message.answer(
                "❌ Формат:\n"
                "/add_admin zam @username Nik: игровой_ник"
            )
            return

        game_nick = " ".join(parts[3:]).strip()

        try:
            chat = await bot.get_chat(username)
        except Exception:
            await message.answer(
                f"❌ @{escape(username)} не найден."
            )
            return

        for nick, info in data["zam_data"].items():
            if info.get("tg_user_id") == chat.id:
                await message.answer(
                    f"❌ Уже зам ({escape(nick)})."
                )
                return

        ok, result = add_zam_nick(
            game_nick,
            chat.id,
            username,
        )

        if not ok:
            await message.answer(f"❌ {result}")
            return

        await message.answer(
            f"✅ Зам <b>{escape(game_nick)}</b> "
            f"(@{escape(username)}) добавлен."
        )

        try:
            await bot.send_message(
                chat.id,
                f"👑 Вы назначены замом!\n"
                f"Ваш игровой ник: {escape(game_nick)}",
            )
        except Exception:
            pass

        return

    await message.answer("❌ Тип: adm или zam")


@dp.message(Command("remove_admin"))
async def remove_admin(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return

    args = message.text.split(maxsplit=1)

    if len(args) < 2:
        await message.answer(
            "❌ Формат:\n"
            "/remove_admin adm @username\n"
            "/remove_admin zam @username"
        )
        return

    parts = args[1].split()

    if len(parts) < 2:
        await message.answer("❌ Мало аргументов.")
        return

    type_ = parts[0].lower()
    username = parts[1].lstrip("@")

    if type_ == "adm":
        try:
            chat = await bot.get_chat(username)
        except Exception:
            await message.answer(
                f"❌ @{escape(username)} не найден."
            )
            return

        if chat.id == SUPER_ADMIN:
            await message.answer("❌ Нельзя удалить владельца!")
            return

        if chat.id not in get_admins():
            await message.answer("❌ Не админ.")
            return

        admins = get_admins()
        admins.remove(chat.id)
        save_admins(admins)

        data["admin_usernames"].pop(str(chat.id), None)
        save_data()

        await message.answer(
            f"✅ Админ @{escape(username)} удалён."
        )

        await set_command_scopes()
        return

    if type_ == "zam":
        found_nick = None

        for nick, info in data["zam_data"].items():
            tg_username = info.get("tg_username")

            if (
                tg_username
                and tg_username.lower() == username.lower()
            ):
                found_nick = nick
                break

        if not found_nick:
            await message.answer(
                f"❌ Зам @{escape(username)} не найден."
            )
            return

        remove_zam_nick(found_nick)

        await message.answer(
            f"✅ Зам <b>{escape(found_nick)}</b> удалён."
        )
        return

    await message.answer("❌ Тип: adm или zam")


# =========================================================
# ДОБАВЛЕНИЕ/УДАЛЕНИЕ ЗАМОВ ЧЕРЕЗ МЕНЮ
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
        text = (
            "👑 <b>Управление замами</b>\n\n"
            "📭 Замов пока нет."
        )
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

    await message.answer(
        text,
        reply_markup=zams_panel_keyboard(),
    )


@dp.callback_query(F.data == "zam:add")
async def zam_add_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True)
        return

    admin_actions[cb.from_user.id] = "add_zam"
    await cb.message.answer(
        "➕ Введите игровой ник зама.\n\n"
        "Если хотите привязать Telegram, отправьте:\n"
        "<code>игровой_ник @username</code>\n\n"
        "Или только игровой ник."
    )
    await cb.answer()


@dp.callback_query(F.data == "zam:remove")
async def zam_remove_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True)
        return

    admin_actions[cb.from_user.id] = "remove_zam"
    await cb.message.answer(
        "➖ Введите игровой ник зама, которого нужно удалить."
    )
    await cb.answer()


@dp.callback_query(F.data == "zam:stats")
async def zam_stats_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True)
        return

    await send_zam_stats(cb.message)
    await cb.answer()


@dp.message(lambda m: m.from_user.id in admin_actions)
async def admin_action_handler(message: Message):
    uid = message.from_user.id

    if not is_super_admin(uid):
        admin_actions.pop(uid, None)
        return

    action = admin_actions.pop(uid)

    if not message.text:
        await message.answer("❌ Введите текст.")
        return

    value = message.text.strip()

    # Добавление админа через кнопку.
    if action == "add_admin":
        username = value.lstrip("@")

        try:
            chat = await bot.get_chat(username)
        except Exception:
            await message.answer(
                f"❌ @{escape(username)} не найден."
            )
            return

        if chat.id in get_admins():
            await message.answer("❌ Уже админ.")
            return

        admins = get_admins()
        admins.add(chat.id)
        save_admins(admins)

        data["admin_usernames"][str(chat.id)] = {
            "username": chat.username or username,
            "full_name": chat.full_name or str(chat.id),
        }
        save_data()

        await message.answer(
            f"✅ Админ <b>@{escape(username)}</b> добавлен."
        )

        try:
            await bot.send_message(
                chat.id,
                "👑 Вы назначены администратором!",
            )
        except Exception:
            pass

        await set_command_scopes()
        return

    # Удаление админа через кнопку.
    if action == "remove_admin":
        username = value.lstrip("@")

        try:
            chat = await bot.get_chat(username)
        except Exception:
            await message.answer(
                f"❌ @{escape(username)} не найден."
            )
            return

        if chat.id == SUPER_ADMIN:
            await message.answer("❌ Нельзя удалить владельца!")
            return

        if chat.id not in get_admins():
            await message.answer("❌ Не админ.")
            return

        admins = get_admins()
        admins.remove(chat.id)
        save_admins(admins)

        data["admin_usernames"].pop(str(chat.id), None)
        save_data()

        await message.answer(
            f"✅ Админ <b>@{escape(username)}</b> удалён."
        )

        await set_command_scopes()
        return

    # Добавление зама через кнопку.
    if action == "add_zam":
        parts = value.split()

        if len(parts) == 1:
            game_nick = parts[0]
            tg_username = None
            tg_user_id = None

        elif len(parts) == 2:
            game_nick = parts[0]
            tg_username = parts[1].lstrip("@")

            try:
                chat = await bot.get_chat(tg_username)
            except Exception:
                await message.answer(
                    f"❌ @{escape(tg_username)} не найден."
                )
                return

            tg_user_id = chat.id
        else:
            await message.answer(
                "❌ Формат:\n"
                "<code>игровой_ник</code>\n"
                "или\n"
                "<code>игровой_ник @username</code>"
            )
            return

        ok, result = add_zam_nick(
            game_nick,
            tg_user_id,
            tg_username,
        )

        if not ok:
            await message.answer(f"❌ {result}")
            return

        await log_action(
            uid,
            "добавил зама",
            game_nick,
        )

        await message.answer(
            f"✅ Зам <b>{escape(game_nick)}</b> добавлен."
        )

        if tg_user_id:
            try:
                await bot.send_message(
                    tg_user_id,
                    f"👑 Вы назначены замом!\n"
                    f"Ваш игровой ник: {escape(game_nick)}",
                )
            except Exception:
                pass

        return

    # Удаление зама через кнопку.
    if action == "remove_zam":
        game_nick = value

        if not remove_zam_nick(game_nick):
            await message.answer("❌ Такой зам не найден.")
            return

        await log_action(
            uid,
            "удалил зама",
            game_nick,
        )

        await message.answer(
            f"✅ Зам <b>{escape(game_nick)}</b> удалён."
        )
        return


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

    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        lines = []

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

    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        lines = []

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

    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("")

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
            "/add_admin — добавить админа/зама\n"
            "/remove_admin — удалить админа/зама\n"
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
        )
    else:
        text = (
            "📋 <b>Команды:</b>\n\n"
            "/start — меню\n"
            "/help — справка\n"
        )

    await message.answer(text)


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
        await message.answer("❌ /all <текст>")
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
]

ADMIN_COMMANDS = [
    BotCommand(command="start", description="🏠 Меню"),
    BotCommand(command="help", description="📖 Справка"),
    BotCommand(command="ping", description="📡 Пинг"),
    BotCommand(command="all", description="📢 Объявление"),
    BotCommand(command="кто", description="👤 Информация об участнике"),
    BotCommand(command="topic_id", description="🆔 ID темы"),
]

OWNER_COMMANDS = ADMIN_COMMANDS + [
    BotCommand(command="add_admin", description="➕ Админ/зам"),
    BotCommand(command="remove_admin", description="➖ Убрать админа/зама"),
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

    await init_admins()
    await set_command_scopes()

    await bot.delete_webhook(drop_pending_updates=True)

    print("🤖 Бот запущен!")

    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Бот остановлен.")
