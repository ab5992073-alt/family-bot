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

try:
    from telethon import TelegramClient
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
    "initial_zams_installed": False,
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

async def show_owner_people_picker(message: Message, mode: str, page: int = 0):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return

    users = await get_owner_dialog_users(limit=200)
    if not users:
        if not telegram_user_is_ready():
            await message.answer(
                "⚠️ Не могу получить личные Telegram-диалоги владельца.\n\n"
                "Настрой TG_API_ID, TG_API_HASH и TG_SESSION_STRING в Render."
            )
        else:
            await message.answer("📭 В личных Telegram-диалогах подходящих пользователей не найдено.")
        return

    if mode == "add_admin":
        title = "👑 <b>Выберите человека для выдачи админки</b>\n\n"
        prefix = "select_admin"
    elif mode == "remove_admin":
        admin_ids = get_admins()
        users = [u for u in users if u["id"] in admin_ids and u["id"] != SUPER_ADMIN]
        title = "➖ <b>Выберите админа для удаления</b>\n\n"
        prefix = "remove_admin_user"
        if not users:
            await message.answer("📭 Нет админов, которых можно удалить.")
            return
    elif mode == "add_zam":
        title = "👑 <b>Выберите человека для назначения замом</b>\n\n"
        prefix = "select_zam"
    elif mode == "remove_zam":
        bound_ids = {info.get("tg_user_id") for info in data["zam_data"].values() if info.get("tg_user_id")}
        users = [u for u in users if u["id"] in bound_ids]
        title = "➖ <b>Выберите зама для удаления</b>\n\n"
        prefix = "remove_zam_user"
        if not users:
            await message.answer("📭 Среди твоих Telegram-диалогов нет привязанных замов.\nУдаление по игровому нику доступно через /remove_zam Ник")
            return
    else:
        return

    await message.answer(
        title + f"Найдено: <b>{len(users)}</b>\nВыберите человека кнопкой ниже.",
        reply_markup=owner_dialog_page_keyboard(users, page=page, prefix=prefix),
    )


@dp.message(F.text == "🛠 Админка")
async def admin_panel(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return

    await message.answer(
        "👑 <b>Управление администраторами</b>\n\n"
        "Теперь админы назначаются выбором человека из твоих личных Telegram-диалогов.\n\n"
        "Используй <code>/add admin</code> или кнопку ниже.",
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
        text += f"• {escape(get_admin_display(admin_id))} — {role}\n"

    await cb.message.answer(text)
    await cb.answer()


@dp.callback_query(F.data == "adm:add")
async def adm_add_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True)
        return
    await show_owner_people_picker(cb.message, "add_admin")
    await cb.answer()


@dp.callback_query(F.data == "adm:remove")
async def adm_remove_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True)
        return
    await show_owner_people_picker(cb.message, "remove_admin")
    await cb.answer()


@dp.callback_query(F.data.startswith("select_admin_page:"))
async def select_admin_page_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True)
        return
    page = int(cb.data.split(":", 1)[1])
    users = await get_owner_dialog_users(limit=200)
    await cb.message.edit_reply_markup(reply_markup=owner_dialog_page_keyboard(users, page, prefix="select_admin"))
    await cb.answer()


@dp.callback_query(F.data.startswith("select_admin:"))
async def select_admin_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True)
        return

    user_id = int(cb.data.split(":", 1)[1])
    users = await get_owner_dialog_users(limit=200)
    selected = next((u for u in users if u["id"] == user_id), None)
    if not selected:
        await cb.answer("❌ Человек не найден в диалогах.", show_alert=True)
        return

    if user_id in get_admins():
        await cb.answer("❌ Уже админ.", show_alert=True)
        return

    admins = get_admins()
    admins.add(user_id)
    save_admins(admins)

    data["admin_usernames"][str(user_id)] = {
        "username": selected.get("username"),
        "full_name": selected.get("name") or str(user_id),
    }
    save_data()

    await cb.message.edit_text(
        f"✅ <b>{owner_dialog_label(selected)}</b> назначен администратором."
    )
    await log_action(cb.from_user.id, "добавил администратора", owner_dialog_short_label(selected))

    # Бот не может начать диалог с пользователем, который никогда не открывал бота.
    try:
        await bot.send_message(user_id, "👑 Вы назначены администратором!")
    except Exception:
        pass

    await set_command_scopes()
    await cb.answer("Админ выдан")


@dp.callback_query(F.data.startswith("remove_admin_user_page:"))
async def remove_admin_page_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True)
        return
    page = int(cb.data.split(":", 1)[1])
    users = await get_owner_dialog_users(limit=200)
    users = [u for u in users if u["id"] in get_admins() and u["id"] != SUPER_ADMIN]
    await cb.message.edit_reply_markup(reply_markup=owner_dialog_page_keyboard(users, page, prefix="remove_admin_user"))
    await cb.answer()


@dp.callback_query(F.data.startswith("remove_admin_user:"))
async def remove_admin_user_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True)
        return
    user_id = int(cb.data.split(":", 1)[1])
    if user_id == SUPER_ADMIN:
        await cb.answer("❌ Нельзя удалить владельца!", show_alert=True)
        return
    admins = get_admins()
    if user_id not in admins:
        await cb.answer("❌ Не админ.", show_alert=True)
        return
    admins.remove(user_id)
    save_admins(admins)
    display = get_admin_display(user_id)
    data["admin_usernames"].pop(str(user_id), None)
    save_data()
    await cb.message.edit_text(f"✅ Админ <b>{escape(display)}</b> удалён.")
    await log_action(cb.from_user.id, "удалил администратора", display)
    await set_command_scopes()
    await cb.answer("Удалён")


# =========================================================
# АДМИНСКИЕ КОМАНДЫ
# =========================================================

async def add_admin_by_user(message: Message, user_id: int):
    users = await get_owner_dialog_users(limit=200)
    selected = next((u for u in users if u["id"] == user_id), None)
    if not selected:
        await message.answer("❌ Пользователь не найден в твоих личных диалогах.")
        return
    if user_id in get_admins():
        await message.answer("❌ Уже админ.")
        return

    admins = get_admins()
    admins.add(user_id)
    save_admins(admins)
    data["admin_usernames"][str(user_id)] = {
        "username": selected.get("username"),
        "full_name": selected.get("name") or str(user_id),
    }
    save_data()
    await message.answer(f"✅ <b>{owner_dialog_label(selected)}</b> назначен администратором.")
    await log_action(message.from_user.id, "добавил администратора", owner_dialog_short_label(selected))
    try:
        await bot.send_message(user_id, "👑 Вы назначены администратором!")
    except Exception:
        pass
    await set_command_scopes()


@dp.message(Command("add"))
async def add_command(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return

    args = message.text.split(maxsplit=1)
    if len(args) == 1:
        await message.answer("❌ Использование: <code>/add admin</code> или <code>/add zam</code>")
        return

    mode = args[1].strip().lower()
    if mode == "admin":
        await show_owner_people_picker(message, "add_admin")
    elif mode == "zam":
        await show_owner_people_picker(message, "add_zam")
    else:
        await message.answer("❌ Доступно: <code>/add admin</code> или <code>/add zam</code>")


@dp.message(Command("remove"))
async def remove_command(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return

    args = message.text.split(maxsplit=1)
    if len(args) == 1:
        await message.answer("❌ Использование: <code>/remove admin</code> или <code>/remove zam</code>")
        return

    mode = args[1].strip().lower()
    if mode == "admin":
        await show_owner_people_picker(message, "remove_admin")
    elif mode == "zam":
        await show_owner_people_picker(message, "remove_zam")
    else:
        await message.answer("❌ Доступно: <code>/remove admin</code> или <code>/remove zam</code>")


# Старый /add_admin оставлен как совместимый алиас.
@dp.message(Command("add_admin"))
async def add_admin_legacy(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return
    await show_owner_people_picker(message, "add_admin")


@dp.message(Command("remove_admin"))
async def remove_admin_legacy(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return
    await show_owner_people_picker(message, "remove_admin")


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
    await message.answer(text, reply_markup=zams_panel_keyboard())


@dp.callback_query(F.data == "zam:add")
async def zam_add_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True)
        return
    await show_owner_people_picker(cb.message, "add_zam")
    await cb.answer()


@dp.callback_query(F.data == "zam:remove")
async def zam_remove_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True)
        return
    await show_owner_people_picker(cb.message, "remove_zam")
    await cb.answer()


@dp.callback_query(F.data == "zam:stats")
async def zam_stats_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True)
        return
    await send_zam_stats(cb.message)
    await cb.answer()


@dp.callback_query(F.data.startswith("select_zam_page:"))
async def select_zam_page_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True)
        return
    page = int(cb.data.split(":", 1)[1])
    users = await get_owner_dialog_users(limit=200)
    await cb.message.edit_reply_markup(reply_markup=owner_dialog_page_keyboard(users, page, prefix="select_zam"))
    await cb.answer()


@dp.callback_query(F.data.startswith("select_zam:"))
async def select_zam_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True)
        return
    user_id = int(cb.data.split(":", 1)[1])
    users = await get_owner_dialog_users(limit=200)
    selected = next((u for u in users if u["id"] == user_id), None)
    if not selected:
        await cb.answer("❌ Пользователь не найден.", show_alert=True)
        return

    for nick, info in data["zam_data"].items():
        if info.get("tg_user_id") == user_id:
            await cb.answer(f"❌ Уже зам: {nick}", show_alert=True)
            return

    pending_zam_users[cb.from_user.id] = user_id
    await cb.message.answer(
        f"👑 Выбран: <b>{owner_dialog_label(selected)}</b>\n\n"
        "Теперь отправь <b>игровой ник</b> этого зама одним сообщением.\n"
        "Например: <code>Sergey_Darknes</code>"
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("remove_zam_user_page:"))
async def remove_zam_page_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True)
        return
    page = int(cb.data.split(":", 1)[1])
    users = await get_owner_dialog_users(limit=200)
    bound_ids = {info.get("tg_user_id") for info in data["zam_data"].values() if info.get("tg_user_id")}
    users = [u for u in users if u["id"] in bound_ids]
    await cb.message.edit_reply_markup(reply_markup=owner_dialog_page_keyboard(users, page, prefix="remove_zam_user"))
    await cb.answer()


@dp.callback_query(F.data.startswith("remove_zam_user:"))
async def remove_zam_user_cb(cb: CallbackQuery):
    if not is_super_admin(cb.from_user.id):
        await cb.answer("❌ Только владелец!", show_alert=True)
        return
    user_id = int(cb.data.split(":", 1)[1])
    found_nick = None
    for nick, info in data["zam_data"].items():
        if info.get("tg_user_id") == user_id:
            found_nick = nick
            break
    if not found_nick:
        await cb.answer("❌ Зам не найден.", show_alert=True)
        return
    remove_zam_nick(found_nick)
    await cb.message.edit_text(f"✅ Зам <b>{escape(found_nick)}</b> удалён.")
    await log_action(cb.from_user.id, "удалил зама", found_nick)
    await cb.answer("Удалён")


@dp.message(Command("add_zam"))
async def add_zam_command(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return
    await show_owner_people_picker(message, "add_zam")


@dp.message(Command("remove_zam"))
async def remove_zam_command(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return
    args = message.text.split(maxsplit=1)
    if len(args) == 1:
        await show_owner_people_picker(message, "remove_zam")
        return
    nick = args[1].strip()
    if not remove_zam_nick(nick):
        await message.answer("❌ Такой зам не найден.")
        return
    await log_action(message.from_user.id, "удалил зама", nick)
    await message.answer(f"✅ Зам <b>{escape(nick)}</b> удалён.")


@dp.callback_query(F.data == "owner_select_cancel")
async def owner_select_cancel_cb(cb: CallbackQuery):
    pending_zam_users.pop(cb.from_user.id, None)
    await cb.message.edit_text("❌ Выбор отменён.")
    await cb.answer()


@dp.message(lambda m: m.from_user.id in pending_zam_users)
async def pending_zam_nick_handler(message: Message):
    if not is_super_admin(message.from_user.id):
        pending_zam_users.pop(message.from_user.id, None)
        return
    if not message.text:
        await message.answer("❌ Отправь игровой ник текстом.")
        return

    user_id = pending_zam_users.pop(message.from_user.id)
    game_nick = message.text.strip()
    users = await get_owner_dialog_users(limit=200)
    selected = next((u for u in users if u["id"] == user_id), None)
    if not selected:
        await message.answer("❌ Не удалось найти выбранного пользователя.")
        return

    for nick, info in data["zam_data"].items():
        if info.get("tg_user_id") == user_id:
            await message.answer(f"❌ Уже зам: <b>{escape(nick)}</b>")
            return

    ok, result = add_zam_nick(game_nick, user_id, selected.get("username"))
    if not ok:
        await message.answer(f"❌ {result}")
        return

    await log_action(message.from_user.id, "добавил зама", f"{game_nick} / {owner_dialog_short_label(selected)}")
    await message.answer(
        f"✅ Зам <b>{escape(game_nick)}</b> назначен:\n"
        f"👤 {owner_dialog_label(selected)}"
    )
    try:
        await bot.send_message(
            user_id,
            f"👑 Вы назначены замом!\nВаш игровой ник: {escape(game_nick)}",
        )
    except Exception:
        pass


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
    BotCommand(command="myid", description="🆔 Мой Telegram ID"),
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
    BotCommand(command="add", description="➕ Выдать админа/зама"),
    BotCommand(command="remove", description="➖ Убрать админа/зама"),
    BotCommand(command="add_admin", description="➕ Админ (алиас)"),
    BotCommand(command="remove_admin", description="➖ Админ (алиас)"),
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

    await init_telegram_user_client()
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
