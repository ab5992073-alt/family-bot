import asyncio
import json
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    KeyboardButton,
    BotCommand
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from flask import Flask
import threading


# =========================================================
# ВЕБ-СЕРВЕР ДЛЯ RENDER
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

# Новый токен лучше хранить в Render -> Environment -> Environment Variables
TOKEN = os.environ.get("BOT_TOKEN", "").strip()

if not TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не установлен. Добавь новый токен в Render "
        "Environment Variables."
    )

SUPER_ADMIN = 6166697485

ADMIN_IDS = {
    6166697485,   # @da_rkknes
    123456789,    # @Gmaillok
    6863392923,   # @Eremey128
    1980341141    # @VusalFatalitii
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
    "ВОР"
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
    "Не в организации"
]


bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)

dp = Dispatcher()


# =========================================================
# БАЗА ДАННЫХ
# =========================================================

DATA_FILE = "data.json"


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
        "bot_token": "",
        "zam_data": {},
        "log_notify_enabled": False,
        "admin_usernames": {}
    }


def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


data = load_data()


for key, default in [
    ("zam_data", {}),
    ("zam_stats", {}),
    ("admin_usernames", {}),
    ("log_notify_enabled", False),
    ("bot_token", "")
]:
    if key not in data:
        data[key] = default


# Гарантируем наличие всех админов
current_admins = set(data.get("admins", []))
current_admins.update(ADMIN_IDS)
data["admins"] = list(current_admins)

save_data()


# =========================================================
# ИМЕНА АДМИНОВ
# =========================================================

KNOWN_ADMIN_USERNAMES = {
    6166697485: "da_rkknes",
    6863392923: "Eremey128",
    1980341141: "VusalFatalitii",
    123456789: "Gmaillok"
}


async def init_admins():
    admin_info = data.get("admin_usernames", {})
    changed = False

    for admin_id in ADMIN_IDS:
        # Сначала используем известные юзернеймы
        if admin_id in KNOWN_ADMIN_USERNAMES:
            new_info = {
                "username": KNOWN_ADMIN_USERNAMES[admin_id]
            }

            if admin_info.get(str(admin_id)) != new_info:
                admin_info[str(admin_id)] = new_info
                changed = True

            continue

        try:
            chat = await bot.get_chat(admin_id)

            info = {}

            if chat.username:
                info["username"] = chat.username

            if chat.full_name:
                info["full_name"] = chat.full_name

            if info:
                admin_info[str(admin_id)] = info
                changed = True

        except Exception:
            if str(admin_id) not in admin_info:
                admin_info[str(admin_id)] = {
                    "full_name": str(admin_id)
                }
                changed = True

    if changed:
        data["admin_usernames"] = admin_info
        save_data()


def get_admin_display(admin_id):
    # Известные юзернеймы всегда имеют приоритет
    if admin_id in KNOWN_ADMIN_USERNAMES:
        return f"@{KNOWN_ADMIN_USERNAMES[admin_id]}"

    info = data.get("admin_usernames", {}).get(str(admin_id))

    if info:
        if info.get("username"):
            return f"@{info['username']}"

        if (
            info.get("full_name")
            and info["full_name"] != str(admin_id)
        ):
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


def get_zam_nicknames():
    return list(data["zam_data"].keys())


def get_zam_user_id(game_nick):
    return data["zam_data"].get(game_nick, {}).get("tg_user_id")


# =========================================================
# ЛОГИРОВАНИЕ
# =========================================================

LOG_FILE = "bot_activity.log"


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
                f"👤 <b>{username}</b> -> "
                f"{action} {details}\n🕐 {ts}"
            )
        except Exception:
            pass


# =========================================================
# КНОПКИ
# =========================================================

def main_keyboard(has_survey=False):
    b = ReplyKeyboardBuilder()

    b.row(
        KeyboardButton(text="📝 Заполнить анкету")
    )

    if has_survey:
        b.row(
            KeyboardButton(text="🔄 Перезаполнить анкету")
        )

    b.row(
        KeyboardButton(text="👤 Мой профиль")
    )

    return b.as_markup(resize_keyboard=True)


def admin_keyboard(user_id, has_survey=False):
    b = ReplyKeyboardBuilder()

    b.row(
        KeyboardButton(text="📋 Управление заявками"),
        KeyboardButton(text="⏳ Активные заявки")
    )

    b.row(
        KeyboardButton(text="👥 Список участников"),
        KeyboardButton(text="🟢 Статус бота")
    )

    if has_survey:
        b.row(
            KeyboardButton(text="🔄 Перезаполнить анкету")
        )

    if is_super_admin(user_id):
        b.row(
            KeyboardButton(text="👑 Администрирование"),
            KeyboardButton(text="📜 Журнал действий")
        )

        b.row(
            KeyboardButton(text="🏦 Банк замов")
        )

    return b.as_markup(resize_keyboard=True)


# =========================================================
# ДОБАВЛЕНИЕ В ГРУППУ
# =========================================================

async def add_user_to_group(user_id):
    try:
        link = await bot.create_chat_invite_link(
            GROUP_ID,
            member_limit=1
        )

        await bot.send_message(
            user_id,
            f"🔗 <b>Вы приняты в семью!</b>\n\n"
            f"Вступите по ссылке:\n{link.invite_link}\n\n"
            f"Или:\n{GROUP_LINK}"
        )

        return True

    except Exception:
        try:
            await bot.send_message(
                user_id,
                f"🔗 <b>Вы приняты в семью!</b>\n\n"
                f"Вступите:\n{GROUP_LINK}"
            )

            return True

        except Exception:
            return False


async def remove_user_from_group(user_id):
    try:
        await bot.ban_chat_member(
            GROUP_ID,
            user_id
        )

        await bot.unban_chat_member(
            GROUP_ID,
            user_id
        )

        return True

    except Exception:
        return False


async def set_user_nickname(user_id, nickname):
    try:
        await bot.set_chat_member_custom_title(
            chat_id=GROUP_ID,
            user_id=user_id,
            custom_title=nickname
        )

        return True

    except Exception:
        return False


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def start_command(message: Message):
    await log_action(
        message.from_user.id,
        "start",
        "запустил бота"
    )

    await show_main_menu(message)


async def show_main_menu(message: Message):
    user_id = message.from_user.id

    has_survey = str(user_id) in data["users"]

    if is_admin(user_id):
        await message.answer(
            f"🛡️ <b>Панель управления</b>\n"
            f"Добро пожаловать в административный "
            f"раздел <b>{BOT_NAME}</b>.",
            reply_markup=admin_keyboard(
                user_id,
                has_survey
            )
        )

    else:
        await message.answer(
            f"👋 <b>Добро пожаловать в {BOT_NAME}!</b>\n"
            f"Заполните анкету для вступления в семью.",
            reply_markup=main_keyboard(
                has_survey
            )
        )


# =========================================================
# /КТО
# =========================================================

@dp.message(Command("кто"))
async def who_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет прав!")
        return

    await log_action(
        message.from_user.id,
        "команда /кто"
    )

    if not message.reply_to_message:
        await message.answer(
            "❌ Ответьте на сообщение участника."
        )
        return

    uid = message.reply_to_message.from_user.id

    u = data["users"].get(str(uid))

    if not u:
        await message.answer(
            "❌ У этого пользователя нет анкеты."
        )
        return

    await message.answer(
        f"📋 <b>Анкета:</b>\n"
        f"Nickname: {u['nickname']}\n"
        f"Тег: {u['tag']}\n"
        f"Ранг: {u['rank_fam']}\n"
        f"Орг: {u['organization']}\n"
        f"Ранг в орг: {u['rank_org']}\n"
        f"Пригласитель: {u['inviter']}"
    )


# =========================================================
# СБРОС АНКЕТЫ
# =========================================================

@dp.message(F.text == "🔄 Перезаполнить анкету")
async def reset_survey(message: Message):
    uid = str(message.from_user.id)

    if uid not in data["users"]:
        await message.answer(
            "❌ У вас нет анкеты."
        )
        return

    old = data["users"].pop(uid)

    inv = old.get("inviter")

    if inv in data["zam_stats"]:
        data["zam_stats"][inv]["count"] = max(
            0,
            data["zam_stats"][inv]["count"] - 1
        )

        data["zam_stats"][inv]["earned"] = max(
            0,
            data["zam_stats"][inv]["earned"] - 100000
        )

        if "history" in data["zam_stats"][inv]:
            data["zam_stats"][inv]["history"] = [
                h
                for h in data["zam_stats"][inv]["history"]
                if h["user_id"] != int(uid)
            ]

    save_data()

    await log_action(
        int(uid),
        "сброс анкеты"
    )

    await message.answer(
        "✅ Анкета сброшена. Заполните заново."
    )

    await show_main_menu(message)


# =========================================================
# АНКЕТА
# =========================================================

user_surveys = {}


async def start_survey(message: Message):
    uid = message.from_user.id

    user_surveys[uid] = {
        "step": 0,
        "answers": {}
    }

    await log_action(
        uid,
        "анкета",
        "начал"
    )

    await message.answer(
        "📋 <b>Заполнение анкеты</b>\n\n"
        "1️⃣ Ваш Nickname в игре?"
    )


@dp.message(lambda m: m.from_user.id in user_surveys)
async def survey_handler(message: Message):
    uid = message.from_user.id

    s = user_surveys[uid]
    step = s["step"]

    if step == 0:
        s["answers"]["nickname"] = message.text

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
                        callback_data=f"rank_{r}"
                    )
                ]
                for r in RANK_LIST
            ]
        )

        await message.answer(
            "👤 Ваш ранг в фаме:",
            reply_markup=kb
        )

    elif step == 3:
        s["answers"]["rank_org"] = message.text

        s["step"] = 4

        zams = get_zam_nicknames()

        if not zams:
            await message.answer(
                "⚠️ Замов нет."
            )
            return

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=z,
                        callback_data=f"zam_{z}"
                    )
                ]
                for z in zams
            ]
        )

        await message.answer(
            "👤 Кто вас пригласил:",
            reply_markup=kb
        )


# =========================================================
# РАНГ
# =========================================================

@dp.callback_query(F.data.startswith("rank_"))
async def rank_selected(cb: CallbackQuery):
    uid = cb.from_user.id

    if uid not in user_surveys:
        await cb.answer("❌")
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
                    callback_data=f"org_{o}"
                )
            ]
            for o in ORG_LIST
        ]
    )

    await cb.message.answer(
        "🏢 Ваша организация:",
        reply_markup=kb
    )


# =========================================================
# ОРГАНИЗАЦИЯ
# =========================================================

@dp.callback_query(F.data.startswith("org_"))
async def org_selected(cb: CallbackQuery):
    uid = cb.from_user.id

    if uid not in user_surveys:
        await cb.answer("❌")
        return

    organization = cb.data[4:]

    user_surveys[uid]["answers"]["organization"] = organization
    user_surveys[uid]["step"] = 3

    await cb.answer(f"✅ {organization}")

    await cb.message.answer(
        "📌 Ваш ранг в организации?"
    )


# =========================================================
# ЗАМ
# =========================================================

@dp.callback_query(F.data.startswith("zam_"))
async def zam_selected(cb: CallbackQuery):
    uid = cb.from_user.id

    if uid not in user_surveys:
        await cb.answer("❌")
        return

    inviter = cb.data[4:]

    user_surveys[uid]["answers"]["inviter"] = inviter

    await cb.answer(f"✅ {inviter}")

    await finish_survey(
        cb.message,
        uid
    )


# =========================================================
# ЗАВЕРШЕНИЕ АНКЕТЫ
# =========================================================

async def finish_survey(message, uid):
    s = user_surveys.pop(uid, None)

    if not s:
        return

    a = s["answers"]

    old = data["users"].get(str(uid))

    if old:
        inv = old.get("inviter")

        if inv in data["zam_stats"]:
            data["zam_stats"][inv]["count"] = max(
                0,
                data["zam_stats"][inv]["count"] - 1
            )

            data["zam_stats"][inv]["earned"] = max(
                0,
                data["zam_stats"][inv]["earned"] - 100000
            )

            if "history" in data["zam_stats"][inv]:
                data["zam_stats"][inv]["history"] = [
                    h
                    for h in data["zam_stats"][inv]["history"]
                    if h["user_id"] != uid
                ]

    user_data = {
        "nickname": a.get("nickname", "—"),
        "tag": a.get("tag", "—"),
        "rank_fam": a.get("rank_fam", "—"),
        "organization": a.get("organization", "—"),
        "rank_org": a.get("rank_org", "—"),
        "inviter": a.get("inviter", "—")
    }

    data["users"][str(uid)] = user_data

    app_id = (
        f"app_{uid}_"
        f"{int(datetime.now().timestamp())}"
    )

    data["applications"][app_id] = {
        "user_id": uid,
        "data": user_data,
        "status": "pending",
        "created": datetime.now().isoformat(),
        "history": []
    }

    inv = user_data["inviter"]

    if inv in data["zam_stats"]:
        data["zam_stats"][inv]["count"] += 1

        data["zam_stats"][inv]["earned"] += 100000

        data["zam_stats"][inv]["history"].append(
            {
                "user_id": uid,
                "nick": user_data["nickname"],
                "time": datetime.now().isoformat()
            }
        )

    save_data()

    await message.answer(
        "✅ <b>Анкета заполнена!</b>"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Принять",
                    callback_data=f"accept:{app_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"reject:{app_id}"
                )
            ]
        ]
    )

    text = (
        f"📩 <b>Новая заявка!</b>\n"
        f"Nickname: {user_data['nickname']}\n"
        f"Тег: {user_data['tag']}\n"
        f"Ранг: {user_data['rank_fam']}\n"
        f"Орг: {user_data['organization']}\n"
        f"Ранг в орг: {user_data['rank_org']}\n"
        f"Пригласитель: {user_data['inviter']}"
    )

    for admin in get_admins():
        try:
            await bot.send_message(
                admin,
                text,
                reply_markup=kb
            )
        except Exception:
            pass


# =========================================================
# КНОПКА АНКЕТЫ
# =========================================================

@dp.message(F.text == "📝 Заполнить анкету")
async def survey_button(message: Message):
    uid = message.from_user.id

    if str(uid) in data["users"]:
        await message.answer(
            "ℹ️ Вы уже заполнили. "
            "Используйте «🔄»."
        )
        return

    await start_survey(message)


# =========================================================
# ПРИНЯТЬ
# =========================================================

@dp.callback_query(F.data.startswith("accept:"))
async def accept_app(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет прав!")
        return

    app_id = cb.data.split(":", 1)[1]

    app = data["applications"].get(app_id)

    if not app:
        await cb.answer("❌ Не найдена")
        return

    app["status"] = "accepted"

    save_data()

    await add_user_to_group(
        app["user_id"]
    )

    await set_user_nickname(
        app["user_id"],
        app["data"].get(
            "nickname",
            "Участник"
        )
    )

    await cb.answer("✅ Принят")

    await cb.message.edit_reply_markup(
        reply_markup=None
    )


# =========================================================
# ОТКЛОНИТЬ
# =========================================================

@dp.callback_query(F.data.startswith("reject:"))
async def reject_app(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        await cb.answer("❌ Нет прав!")
        return

    app_id = cb.data.split(":", 1)[1]

    app = data["applications"].get(app_id)

    if not app:
        await cb.answer("❌ Не найдена")
        return

    app["status"] = "rejected"

    save_data()

    await remove_user_from_group(
        app["user_id"]
    )

    await cb.answer("❌ Отклонён")

    await cb.message.edit_reply_markup(
        reply_markup=None
    )


# =========================================================
# ВСЕ ЗАЯВКИ
# =========================================================

@dp.message(F.text == "📋 Управление заявками")
async def all_apps(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌")
        return

    apps = data["applications"]

    if not apps:
        await message.answer(
            "📭 Заявок нет."
        )
        return

    q = [
        ("Nickname", "nickname"),
        ("Тег", "tag"),
        ("Ранг", "rank_fam"),
        ("Орг", "organization"),
        ("Ранг в орг", "rank_org"),
        ("Пригласил", "inviter")
    ]

    idx = 1

    for app_id, app in apps.items():
        u = app["data"]

        e = (
            "⏳"
            if app["status"] == "pending"
            else (
                "✅"
                if app["status"] == "accepted"
                else "❌"
            )
        )

        t = (
            f"{e} <b>Заявка #{idx}</b>\n"
        )

        for name, k in q:
            t += (
                f"{name}: "
                f"{u.get(k, '—')}\n"
            )

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅",
                        callback_data=f"accept:{app_id}"
                    ),
                    InlineKeyboardButton(
                        text="❌",
                        callback_data=f"reject:{app_id}"
                    )
                ]
            ]
        )

        await message.answer(
            t,
            reply_markup=kb
        )

        idx += 1


# =========================================================
# АКТИВНЫЕ ЗАЯВКИ
# =========================================================

@dp.message(F.text == "⏳ Активные заявки")
async def active_apps(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌")
        return

    pend = {
        k: v
        for k, v in data["applications"].items()
        if v["status"] == "pending"
    }

    if not pend:
        await message.answer(
            "📭 Нет активных."
        )
        return

    q = [
        ("Nickname", "nickname"),
        ("Тег", "tag"),
        ("Ранг", "rank_fam"),
        ("Орг", "organization"),
        ("Ранг в орг", "rank_org"),
        ("Пригласил", "inviter")
    ]

    idx = 1

    for app_id, app in pend.items():
        u = app["data"]

        t = (
            f"⏳ <b>Заявка #{idx}</b>\n"
        )

        for name, k in q:
            t += (
                f"{name}: "
                f"{u.get(k, '—')}\n"
            )

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅",
                        callback_data=f"accept:{app_id}"
                    ),
                    InlineKeyboardButton(
                        text="❌",
                        callback_data=f"reject:{app_id}"
                    )
                ]
            ]
        )

        await message.answer(
            t,
            reply_markup=kb
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

    users = list(
        data["users"].items()
    )

    if not users:
        await message.answer(
            "📭 Нет анкет."
        )
        return

    await send_users_page(
        message,
        users,
        0
    )


async def send_users_page(message, users, page):
    per = 3

    total = len(users)

    pages = (
        total + per - 1
    ) // per

    if page < 0 or page >= pages:
        return

    start = page * per

    end = min(
        page * per + per,
        total
    )

    t = (
        "👥 <b>Список участников</b>\n\n"
    )

    for i in range(start, end):
        uid, u = users[i]

        t += (
            f"<b>{i+1}.</b> "
            f"{u['nickname']} — "
            f"{u.get('tag', uid)}\n"
        )

        t += (
            f"   Ранг: {u['rank_fam']} | "
            f"Орг: {u['organization']} | "
            f"Пригласил: {u['inviter']}\n\n"
        )

    t += (
        f"Стр. {page+1} из {pages}"
    )

    rows = []

    if page > 0:
        rows.append(
            [
                InlineKeyboardButton(
                    text="⬅️",
                    callback_data=f"up_{page-1}"
                )
            ]
        )

    if page < pages - 1:
        rows.append(
            [
                InlineKeyboardButton(
                    text="➡️",
                    callback_data=f"up_{page+1}"
                )
            ]
        )

    await message.answer(
        t,
        reply_markup=(
            InlineKeyboardMarkup(
                inline_keyboard=rows
            )
            if rows
            else None
        )
    )


@dp.callback_query(F.data.startswith("up_"))
async def up_cb(cb: CallbackQuery):
    users = list(
        data["users"].items()
    )

    await send_users_page(
        cb.message,
        users,
        int(cb.data.split("_")[1])
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
        if a["status"] == "pending"
    )

    rej = sum(
        1
        for a in data["applications"].values()
        if a["status"] == "rejected"
    )

    acc = sum(
        1
        for a in data["applications"].values()
        if a["status"] == "accepted"
    )

    admins = "\n".join(
        get_admin_display(i)
        for i in sorted(get_admins())
    )

    await message.answer(
        f"🟢 <b>Бот работает!</b>\n\n"
        f"👥 Всего: {total}\n"
        f"📩 Ожидают: {pend}\n"
        f"✅ Принято: {acc}\n"
        f"❌ Отклонено: {rej}\n\n"
        f"👑 <b>Админы:</b>\n"
        f"{admins}"
    )


# =========================================================
# МОЙ ПРОФИЛЬ
# =========================================================

@dp.message(F.text == "👤 Мой профиль")
async def my_profile(message: Message):
    uid = str(message.from_user.id)

    if uid in data["users"]:
        u = data["users"][uid]

        await message.answer(
            f"👤 <b>Профиль:</b>\n"
            f"Nickname: {u['nickname']}\n"
            f"Тег: {u['tag']}\n"
            f"Ранг: {u['rank_fam']}\n"
            f"Орг: {u['organization']}\n"
            f"Ранг в орг: {u['rank_org']}\n"
            f"Пригласитель: {u['inviter']}"
        )

    else:
        await message.answer(
            "ℹ️ Вы ещё не заполнили анкету."
        )


# =========================================================
# АДМИНИСТРИРОВАНИЕ
# =========================================================

@dp.message(F.text == "👑 Администрирование")
async def manage(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer(
            "❌ Только владелец!"
        )
        return

    t = (
        "👑 <b>Администрирование</b>\n\n"
        "📋 <b>Админы:</b>\n"
    )

    for i in sorted(get_admins()):
        t += (
            f"• {get_admin_display(i)}\n"
        )

    t += (
        "\n<b>Команды:</b>\n"
        "/add_admin adm @username — "
        "добавить админа\n"
        "/remove_admin adm @username — "
        "удалить админа\n"
        "/add_admin zam @username "
        "Nik: игровой_ник — добавить зама\n"
        "/remove_admin zam @username — "
        "удалить зама"
    )

    await message.answer(t)


# =========================================================
# ДОБАВИТЬ АДМИНА / ЗАМА
# =========================================================

@dp.message(Command("add_admin"))
async def add_admin(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer(
            "❌ Только владелец!"
        )
        return

    args = message.text.split(
        maxsplit=1
    )

    if len(args) < 2:
        await message.answer(
            "❌ /add_admin adm @username\n"
            "или\n"
            "/add_admin zam @username "
            "Nik: ник"
        )
        return

    parts = args[1].split()

    if len(parts) < 2:
        await message.answer(
            "❌ Мало аргументов."
        )
        return

    type_ = parts[0].lower()
    username = parts[1].lstrip("@")

    if type_ == "adm":
        try:
            chat = await bot.get_chat(
                username
            )
        except Exception:
            await message.answer(
                f"❌ @{username} не найден."
            )
            return

        if chat.id in get_admins():
            await message.answer(
                "❌ Уже админ."
            )
            return

        admins = get_admins()

        admins.add(chat.id)

        save_admins(admins)

        info = {}

        if chat.username:
            info["username"] = chat.username

        if chat.full_name:
            info["full_name"] = chat.full_name

        if not info:
            info["full_name"] = str(chat.id)

        data["admin_usernames"][
            str(chat.id)
        ] = info

        save_data()

        await message.answer(
            f"✅ Админ @{username} добавлен."
        )

        try:
            await bot.send_message(
                chat.id,
                "👑 Вы назначены администратором!"
            )
        except Exception:
            pass

        return

    if type_ == "zam":
        if (
            len(parts) < 4
            or parts[2].lower() != "nik:"
        ):
            await message.answer(
                "❌ Формат:\n"
                "/add_admin zam @username "
                "Nik: игровой_ник"
            )
            return

        game_nick = " ".join(
            parts[3:]
        )

        try:
            chat = await bot.get_chat(
                username
            )
        except Exception:
            await message.answer(
                f"❌ @{username} не найден."
            )
            return

        if game_nick in data["zam_data"]:
            await message.answer(
                "❌ Ник занят."
            )
            return

        for nick, info in data["zam_data"].items():
            if info["tg_user_id"] == chat.id:
                await message.answer(
                    f"❌ Уже зам ({nick})."
                )
                return

        data["zam_data"][game_nick] = {
            "tg_user_id": chat.id,
            "tg_username": username
        }

        if game_nick not in data["zam_stats"]:
            data["zam_stats"][game_nick] = {
                "count": 0,
                "earned": 0,
                "history": []
            }

        save_data()

        await message.answer(
            f"✅ Зам '{game_nick}' "
            f"(@{username}) добавлен."
        )

        try:
            await bot.send_message(
                chat.id,
                f"👑 Вы назначены замом!\n"
                f"Ваш ник: {game_nick}"
            )
        except Exception:
            pass

        return

    await message.answer(
        "❌ Тип: adm или zam"
    )


# =========================================================
# УДАЛИТЬ АДМИНА / ЗАМА
# =========================================================

@dp.message(Command("remove_admin"))
async def remove_admin(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer(
            "❌ Только владелец!"
        )
        return

    args = message.text.split(
        maxsplit=1
    )

    if len(args) < 2:
        await message.answer(
            "❌ /remove_admin adm @username\n"
            "или\n"
            "/remove_admin zam @username"
        )
        return

    parts = args[1].split()

    if len(parts) < 2:
        await message.answer(
            "❌ Мало аргументов."
        )
        return

    type_ = parts[0].lower()
    username = parts[1].lstrip("@")

    if type_ == "adm":
        try:
            chat = await bot.get_chat(
                username
            )
        except Exception:
            await message.answer(
                f"❌ @{username} не найден."
            )
            return

        if chat.id == SUPER_ADMIN:
            await message.answer(
                "❌ Нельзя удалить владельца!"
            )
            return

        if chat.id not in get_admins():
            await message.answer(
                "❌ Не админ."
            )
            return

        admins = get_admins()

        admins.remove(chat.id)

        save_admins(admins)

        if (
            "admin_usernames" in data
            and str(chat.id)
            in data["admin_usernames"]
        ):
            del data["admin_usernames"][
                str(chat.id)
            ]

        save_data()

        await message.answer(
            f"✅ Админ @{username} удалён."
        )

        return

    if type_ == "zam":
        gn = None

        for nick, info in data["zam_data"].items():
            if (
                info["tg_username"].lower()
                == username.lower()
            ):
                gn = nick
                break

        if not gn:
            await message.answer(
                f"❌ Зам @{username} не найден."
            )
            return

        del data["zam_data"][gn]

        if gn in data["zam_stats"]:
            del data["zam_stats"][gn]

        save_data()

        await message.answer(
            f"✅ Зам '{gn}' удалён."
        )

        return

    await message.answer(
        "❌ Тип: adm или zam"
    )


# =========================================================
# БАНК ЗАМОВ
# =========================================================

@dp.message(Command("zam_stats"))
async def zam_stats_cmd(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer(
            "❌ Только владелец!"
        )
        return

    s = data.get(
        "zam_stats",
        {}
    )

    if not s:
        await message.answer(
            "📭 Пусто."
        )
        return

    t = (
        "🏦 <b>БАНК ЗАМОВ</b>\n\n"
    )

    for zam, info in s.items():
        t += (
            f"<b>{zam}</b> → "
            f"{info['count']} чел. | "
            f"{info['earned']:,} $\n"
        )

    await message.answer(t)


@dp.message(F.text == "🏦 Банк замов")
async def zam_stats_btn(message: Message):
    await zam_stats_cmd(message)


# =========================================================
# ВЫВОД
# =========================================================

@dp.message(Command("withdraw"))
async def withdraw(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer(
            "❌ Только владелец!"
        )
        return

    args = message.text.split(
        maxsplit=2
    )

    if len(args) < 3:
        await message.answer(
            "❌ /withdraw @ник сумма (тыс.)"
        )
        return

    username = args[1].lstrip("@")

    try:
        amount = int(args[2])
    except Exception:
        await message.answer(
            "❌ Сумма числом."
        )
        return

    if amount < 100 or amount % 100 != 0:
        await message.answer(
            "❌ Мин. 100 и кратна 100."
        )
        return

    gn = None

    for nick, info in data["zam_data"].items():
        if (
            info["tg_username"].lower()
            == username.lower()
        ):
            gn = nick
            break

    if not gn:
        await message.answer(
            "❌ Зам не найден."
        )
        return

    info = data["zam_stats"].get(gn)

    if not info:
        await message.answer(
            "❌ Нет статистики."
        )
        return

    need = amount // 100

    if info["count"] < need:
        await message.answer(
            f"❌ Мало приглашённых "
            f"({info['count']}/{need})."
        )
        return

    info["count"] -= need

    info["earned"] = max(
        0,
        info["earned"] - amount * 1000
    )

    save_data()

    uid = get_zam_user_id(gn)

    if uid:
        try:
            await bot.send_message(
                uid,
                f"💰 Списано {amount}k.\n"
                f"Остаток: {info['count']} чел."
            )
        except Exception:
            pass

    await message.answer(
        f"✅ Снято {amount}k с {gn}.\n"
        f"Остаток: {info['count']}."
    )


# =========================================================
# ЛОГИ
# =========================================================

@dp.message(Command("logs"))
async def logs_cmd(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer(
            "❌ Только владелец!"
        )
        return

    try:
        with open(
            LOG_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            lines = f.readlines()

    except Exception:
        lines = []

    if not lines:
        await message.answer(
            "📭 Пусто."
        )
        return

    await send_logs_page(
        message,
        lines,
        0
    )


async def send_logs_page(message, lines, page):
    per = 10

    total = len(lines)

    pages = max(
        1,
        (total + per - 1) // per
    )

    if page < 0 or page >= pages:
        return

    start = page * per

    end = min(
        page * per + per,
        total
    )

    t = (
        f"📋 <b>Журнал "
        f"(стр. {page+1}/{pages})</b>\n\n"
        + "".join(lines[start:end])
    )

    if len(t) > 4000:
        t = (
            t[:3900]
            + "\n... (обрезано)"
        )

    rows = []

    if page > 0:
        rows.append(
            [
                InlineKeyboardButton(
                    text="⬅️",
                    callback_data=f"lp_{page-1}"
                )
            ]
        )

    if page < pages - 1:
        rows.append(
            [
                InlineKeyboardButton(
                    text="➡️",
                    callback_data=f"lp_{page+1}"
                )
            ]
        )

    await message.answer(
        t,
        reply_markup=(
            InlineKeyboardMarkup(
                inline_keyboard=rows
            )
            if rows
            else None
        )
    )


@dp.callback_query(F.data.startswith("lp_"))
async def lp_cb(cb: CallbackQuery):
    try:
        with open(
            LOG_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            lines = f.readlines()

    except Exception:
        lines = []

    await send_logs_page(
        cb.message,
        lines,
        int(cb.data.split("_")[1])
    )

    await cb.answer()


@dp.message(F.text == "📜 Журнал действий")
async def logs_btn(message: Message):
    await logs_cmd(message)


@dp.message(Command("clearlogs"))
async def clear_logs(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer(
            "❌ Только владелец!"
        )
        return

    with open(
        LOG_FILE,
        "w",
        encoding="utf-8"
    ) as f:
        f.write("")

    await message.answer(
        "✅ Логи очищены."
    )


# =========================================================
# УВЕДОМЛЕНИЯ
# =========================================================

@dp.message(Command("log_on"))
async def log_on(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer(
            "❌ Только владелец!"
        )
        return

    data["log_notify_enabled"] = True

    save_data()

    await message.answer(
        "✅ Уведомления включены."
    )


@dp.message(Command("log_off"))
async def log_off(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer(
            "❌ Только владелец!"
        )
        return

    data["log_notify_enabled"] = False

    save_data()

    await message.answer(
        "❌ Уведомления выключены."
    )


# =========================================================
# PING
# =========================================================

@dp.message(Command("ping"))
async def ping(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer(
            "❌ Только админы!"
        )
        return

    s = datetime.now()

    m = await message.answer(
        "🏓 ..."
    )

    d = (
        datetime.now() - s
    ).total_seconds() * 1000

    up = (
        datetime.now()
        - BOT_START_TIME
    )

    days = up.days
    sec = up.seconds

    h, rem = divmod(
        sec,
        3600
    )

    mn, sc = divmod(
        rem,
        60
    )

    await m.edit_text(
        f"🏓 Понг! {d:.1f} мс\n"
        f"⏱ Аптайм: "
        f"{days}д {h}ч {mn}м {sc}с"
    )


# =========================================================
# HELP
# =========================================================

@dp.message(Command("help"))
async def help_cmd(message: Message):
    t = (
        "📋 <b>Команды:</b>\n\n"
        "/start — меню\n"
        "/ping — пинг (админы)\n"
        "/all — объявление (админы)\n"
        "/add_admin, /remove_admin — "
        "управление (владелец)\n"
        "/logs, /clearlogs — "
        "журнал (владелец)\n"
        "/zam_stats, /withdraw — "
        "банк замов (владелец)\n"
        "/log_on, /log_off — "
        "уведомления (владелец)\n"
        "/set_token — смена токена (владелец)"
    )

    await message.answer(t)


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
                    f"❌ "
                    f"{message.from_user.full_name}, "
                    f"только админы могут писать здесь!",
                    reply_to_message_id=message.message_id
                )

            except Exception:
                pass


# =========================================================
# /ALL
# =========================================================

@dp.message(Command("all"))
async def all_cmd(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer(
            "❌ Только админы!"
        )
        return

    args = message.text.split(
        maxsplit=1
    )

    if len(args) < 2:
        await message.answer(
            "❌ /all <текст>"
        )
        return

    try:
        await bot.send_message(
            GROUP_ID,
            f"⚠️ <b>ВАЖНОЕ ОБЪЯВЛЕНИЕ</b>\n\n"
            f"{args[1]}\n\n"
            f"@all",
            message_thread_id=ANNOUNCE_TOPIC_ID
        )

        await message.answer(
            "✅ Отправлено."
        )

    except Exception as e:
        await message.answer(
            f"❌ {e}"
        )


# =========================================================
# /TOPIC_ID
# =========================================================

@dp.message(Command("topic_id"))
async def topic_id(message: Message):
    if (
        message.chat.id == GROUP_ID
        and message.message_thread_id
    ):
        await message.answer(
            f"ID: {message.message_thread_id}"
        )

    else:
        await message.answer(
            "❌ Не в теме."
        )


# =========================================================
# /ADMINS
# =========================================================

@dp.message(Command("admins"))
async def admins_cmd(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer(
            "❌ Только владелец!"
        )
        return

    t = "👑 <b>Админы</b>\n\n"

    for i in sorted(get_admins()):
        t += (
            f"• {get_admin_display(i)}\n"
        )

    await message.answer(t)


# =========================================================
# ЗАПУСК
# =========================================================

async def main():
    print("🤖 Бот запускается...")

    await init_admins()

    cmds = [
        BotCommand(
            command="start",
            description="🏠 Меню"
        ),
        BotCommand(
            command="help",
            description="📖 Справка"
        ),
        BotCommand(
            command="ping",
            description="📡 Пинг (админы)"
        ),
        BotCommand(
            command="all",
            description="📢 Объявление (админы)"
        ),
        BotCommand(
            command="add_admin",
            description="➕ Админ/зам (владелец)"
        ),
        BotCommand(
            command="remove_admin",
            description="➖ Убрать (владелец)"
        ),
        BotCommand(
            command="admins",
            description="👑 Админы (владелец)"
        ),
        BotCommand(
            command="logs",
            description="📜 Журнал (владелец)"
        ),
        BotCommand(
            command="zam_stats",
            description="🏦 Банк (владелец)"
        ),
        BotCommand(
            command="withdraw",
            description="💰 Вывод (владелец)"
        ),
        BotCommand(
            command="topic_id",
            description="🆔 ID темы"
        ),
        BotCommand(
            command="log_on",
            description="🔔 Уведомления вкл"
        ),
        BotCommand(
            command="log_off",
            description="🔕 Уведомления выкл"
        )
    ]

    await bot.set_my_commands(cmds)

    # Убираем старый webhook перед polling
    await bot.delete_webhook(
        drop_pending_updates=True
    )

    print("🤖 Бот запущен!")

    await dp.start_polling(
        bot
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Бот остановлен.")
