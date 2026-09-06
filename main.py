import asyncio
import json
import os
import sys
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    BotCommand
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

# ===== ВЕБ-СЕРВЕР ДЛЯ RENDER =====
from flask import Flask
import threading

flask_app = Flask(__name__)

@flask_app.route('/')
def health():
    return "Bot is running!", 200

def run_web():
    port = int(os.environ.get("PORT", 8000))
    flask_app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web, daemon=True).start()

# ===== КОНФИГУРАЦИЯ =====
TOKEN = "8768874617:AAGXy_Jk5x4hv583or1tGeJy__YJlpoU7vA"
SUPER_ADMIN = 6166697485  # владелец (твой ID)
GROUP_ID = -1002409536359
GROUP_LINK = "https://t.me/+f_eKIP4gwcs0YTcy"
BOT_NAME = "@Staff_Grand_Bot"

# Админы по юзернеймам (без @) – именно они будут иметь права админа в боте
ADMINS_USERNAMES = {"Eremey128", "VusalFatalitii", "da_rkknes"}

ANNOUNCE_TOPIC_ID = 126387
PROTECTED_GROUP_ID = 0

# ===== ВРЕМЯ ЗАПУСКА =====
BOT_START_TIME = datetime.now()

# ===== СПИСОК РАНГОВ =====
RANK_LIST = [
    "НОВИЧОК", "БандИТ", "Стрелок", "ФРАЕР",
    "ОХРАНИК", "СТ. ОХРАНИК", "РЕШАЛО", "ПОЛОЖЕНЕЦ", "ВОР"
]

# ===== СПИСОК ОРГАНИЗАЦИЙ =====
ORG_LIST = [
    "Правительство", "Воинская часть", "Больница г. Арзамас",
    "Больница г. Южный", "Новостная сеть", "Полиция г. Арзамас",
    "Полиция г. Южный", "ФСБ", "МВД-А", "МВД-Ю",
    "МЗ-А", "МЗ-Ю", "Курганская ОПГ", "Ореховская ОПГ",
    "Тамбовская ОПГ", "Кавказская ОПГ", "Не в организации"
]

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# ===== БАЗА ДАННЫХ =====
DATA_FILE = "data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "users": {},
        "applications": {},
        "admins": [],  # будет заполнено при старте из ADMINS_USERNAMES
        "zam_stats": {},
        "bot_token": TOKEN,
        "zam_data": {},
        "log_notify_enabled": False,
        "admin_usernames": {}  # user_id -> {"username": str, "full_name": str}
    }

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

data = load_data()
if "zam_data" not in data:
    data["zam_data"] = {}
if "zam_stats" not in data:
    data["zam_stats"] = {}
if "bot_token" not in data:
    data["bot_token"] = TOKEN
if "log_notify_enabled" not in data:
    data["log_notify_enabled"] = False
if "admin_usernames" not in data:
    data["admin_usernames"] = {}
if "admins" not in data or not data["admins"]:
    data["admins"] = []  # будут заполнены при инициализации
save_data()

# ===== ИНИЦИАЛИЗАЦИЯ АДМИНОВ ПО ЮЗЕРНЕЙМАМ =====
async def init_admins():
    """При запуске бота добавляет админов из ADMINS_USERNAMES, удаляя старых."""
    admin_ids = set()
    admin_info = {}
    for username in ADMINS_USERNAMES:
        try:
            user = await bot.get_user(username)
            if user:
                admin_ids.add(user.id)
                info = {}
                if user.username:
                    info["username"] = user.username
                if user.full_name:
                    info["full_name"] = user.full_name
                if not info:
                    info["full_name"] = str(user.id)
                admin_info[str(user.id)] = info
        except Exception as e:
            print(f"Не удалось найти пользователя @{username}: {e}")

    # Сохраняем админов в data
    data["admins"] = list(admin_ids)
    # Обновляем admin_usernames
    for uid, info in admin_info.items():
        data["admin_usernames"][uid] = info
    save_data()
    print(f"✅ Админы инициализированы: {[get_admin_display(int(uid)) for uid in admin_info]}")

def get_admin_display(admin_id):
    """Возвращает строку для отображения админа (с @ или имя)"""
    uid = str(admin_id)
    info = data.get("admin_usernames", {}).get(uid)
    if info:
        if info.get("username"):
            return f"@{info['username']}"
        elif info.get("full_name"):
            return info["full_name"]
    # fallback
    try:
        user = bot.get_user(admin_id)
        if user.username:
            return f"@{user.username}"
        elif user.full_name:
            return user.full_name
    except:
        pass
    return str(admin_id)

def get_zam_nicknames():
    return list(data["zam_data"].keys())

def get_zam_by_tg_username(tg_username):
    for nick, info in data["zam_data"].items():
        if info["tg_username"].lower() == tg_username.lower():
            return nick
    return None

def get_zam_user_id(game_nick):
    return data["zam_data"].get(game_nick, {}).get("tg_user_id")

def get_admins():
    if "admins" in data:
        return set(data["admins"])
    return set()

def save_admins(admins_set):
    data["admins"] = list(admins_set)
    save_data()

def is_admin(user_id: int) -> bool:
    return user_id in get_admins()

def is_super_admin(user_id: int) -> bool:
    return user_id == SUPER_ADMIN

# ===== ЛОГИРОВАНИЕ =====
LOG_FILE = "bot_activity.log"

async def log_action(user_id, action, details=""):
    try:
        user = await bot.get_user(user_id)
        username = f"@{user.username}" if user.username else user.full_name
    except:
        username = str(user_id)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {username} -> {action} {details}\n"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_entry)
    
    if data.get("log_notify_enabled", False):
        try:
            await bot.send_message(
                SUPER_ADMIN,
                f"👤 <b>{username}</b> -> {action} {details}\n🕐 {timestamp}"
            )
        except:
            pass

# ===== КНОПКИ =====
def main_keyboard(user_has_survey=False):
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📝 Заполнить анкету"))
    if user_has_survey:
        builder.row(KeyboardButton(text="🔄 Перезаполнить анкету"))
    builder.row(KeyboardButton(text="👤 Мой профиль"))
    return builder.as_markup(resize_keyboard=True)

def admin_keyboard(user_id, has_survey=False):
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="📋 Управление заявками"),
        KeyboardButton(text="⏳ Активные заявки")
    )
    builder.row(
        KeyboardButton(text="👥 Список участников"),
        KeyboardButton(text="🟢 Статус бота")
    )
    if has_survey:
        builder.row(KeyboardButton(text="🔄 Перезаполнить анкету"))
    if is_super_admin(user_id):
        builder.row(
            KeyboardButton(text="👑 Администрирование"),
            KeyboardButton(text="📜 Журнал действий")
        )
        builder.row(KeyboardButton(text="🏦 Банк замов"))
    return builder.as_markup(resize_keyboard=True)

# ===== ДОБАВЛЕНИЕ/УДАЛЕНИЕ ИЗ ГРУППЫ =====
async def add_user_to_group(user_id: int) -> bool:
    try:
        invite_link = await bot.create_chat_invite_link(GROUP_ID, member_limit=1)
        await bot.send_message(
            user_id,
            f"🔗 <b>Вы приняты в семью!</b>\n\nВступите в группу по ссылке:\n{invite_link.invite_link}\n\nИли по основной ссылке:\n{GROUP_LINK}"
        )
        return True
    except:
        try:
            await bot.send_message(user_id, f"🔗 <b>Вы приняты в семью!</b>\n\nВступите по ссылке:\n{GROUP_LINK}")
            return True
        except:
            return False

async def remove_user_from_group(user_id: int) -> bool:
    try:
        await bot.ban_chat_member(GROUP_ID, user_id)
        await bot.unban_chat_member(GROUP_ID, user_id)
        return True
    except:
        return False

async def set_user_nickname(user_id: int, nickname: str):
    try:
        await bot.set_chat_member_custom_title(chat_id=GROUP_ID, user_id=user_id, custom_title=nickname)
        return True
    except:
        return False

# ===== КОМАНДА /кто =====
@dp.message(Command("кто"))
async def who_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет прав!")
        return
    await log_action(message.from_user.id, "команда /кто", "")
    if not message.reply_to_message:
        await message.answer("❌ Ответьте на сообщение участника командой /кто")
        return
    target_user_id = message.reply_to_message.from_user.id
    user_data = data["users"].get(str(target_user_id))
    if not user_data:
        await message.answer("❌ У этого пользователя нет заполненной анкеты.")
        return
    try:
        user = await bot.get_user(target_user_id)
        tag = f"@{user.username}" if user.username else user.full_name
    except:
        tag = str(target_user_id)
    await message.answer(
        f"📋 <b>Анкета пользователя:</b>\n"
        f"Nickname: {user_data['nickname']}\n"
        f"Тег в ТГ: {user_data['tag']}\n"
        f"Ранг в фаме: {user_data['rank_fam']}\n"
        f"Организация: {user_data['organization']}\n"
        f"Ранг в организации: {user_data['rank_org']}\n"
        f"Пригласитель: {user_data['inviter']}"
    )

async def show_main_menu(message: Message):
    user_id = message.from_user.id
    has_survey = str(user_id) in data["users"]
    if is_admin(user_id):
        await message.answer(
            f"🛡️ <b>Панель управления</b>\n"
            f"Добро пожаловать в административный раздел бота <b>{BOT_NAME}</b>.\n"
            f"Используйте кнопки ниже для управления системой.",
            reply_markup=admin_keyboard(user_id, has_survey)
        )
    else:
        await message.answer(
            f"👋 <b>Добро пожаловать в {BOT_NAME}!</b>\n"
            f"Этот бот поможет вам подать заявку на вступление в семью.\n"
            f"Для начала заполните анкету, нажав кнопку ниже.",
            reply_markup=main_keyboard(has_survey)
        )

# ===== СБРОС АНКЕТЫ =====
@dp.message(F.text == "🔄 Перезаполнить анкету")
async def reset_survey(message: Message):
    user_id = str(message.from_user.id)
    if user_id not in data["users"]:
        await message.answer("❌ У вас нет заполненной анкеты.")
        return
    old_data = data["users"].pop(user_id)
    save_data()
    old_inviter = old_data.get("inviter")
    if old_inviter in data["zam_stats"]:
        data["zam_stats"][old_inviter]["count"] -= 1
        data["zam_stats"][old_inviter]["earned"] -= 100000
        if "history" in data["zam_stats"][old_inviter]:
            data["zam_stats"][old_inviter]["history"] = [
                h for h in data["zam_stats"][old_inviter]["history"]
                if h["user_id"] != int(user_id)
            ]
        save_data()
    await log_action(int(user_id), "сброс анкеты", "")
    await message.answer("✅ Анкета сброшена. Вы можете заполнить её заново.")
    await show_main_menu(message)

# ===== АНКЕТА =====
user_surveys = {}

async def start_survey(message: Message):
    user_id = message.from_user.id
    user_surveys[user_id] = {"step": 0, "answers": {}}
    await log_action(user_id, "анкета", "начал заполнение")
    await message.answer("📋 <b>Заполнение анкеты для вступления в семью</b>\n\n1️⃣ Ваш Nickname в игре?")

@dp.message(lambda m: m.from_user.id in user_surveys)
async def survey_handler(message: Message):
    user_id = message.from_user.id
    survey = user_surveys[user_id]
    step = survey["step"]
    answers = survey["answers"]

    if step == 0:
        answers["nickname"] = message.text
        user = message.from_user
        answers["tag"] = f"@{user.username}" if user.username else str(user.id)
        survey["step"] = 1
        await show_rank_choice(message)
    elif step == 1:
        pass
    elif step == 2:
        pass
    elif step == 3:
        answers["rank_org"] = message.text
        survey["step"] = 4
        await show_zam_choice(message)
    elif step == 4:
        pass
    else:
        await message.answer("⚠️ Что-то пошло не так. Начните анкету заново /start")

async def show_rank_choice(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=rank, callback_data=f"rank_{rank}")]
        for rank in RANK_LIST
    ])
    await message.answer("👤 Выберите ваш ранг в фаме:", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("rank_"))
async def rank_selected(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in user_surveys:
        await callback.answer("❌ Анкета не найдена.")
        return
    rank = callback.data[5:]
    survey = user_surveys[user_id]
    survey["answers"]["rank_fam"] = rank
    survey["step"] = 2
    await callback.answer(f"✅ Вы выбрали {rank}")
    await show_org_choice(callback.message, user_id)

async def show_org_choice(message: Message, user_id: int):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=org, callback_data=f"org_{org}")]
        for org in ORG_LIST
    ])
    await message.answer("🏢 Выберите вашу организацию:", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("org_"))
async def org_selected(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in user_surveys:
        await callback.answer("❌ Анкета не найдена.")
        return
    org = callback.data[4:]
    survey = user_surveys[user_id]
    survey["answers"]["organization"] = org
    survey["step"] = 3
    await callback.answer(f"✅ Вы выбрали {org}")
    await callback.message.answer("📌 Ваш ранг в организации?")

async def show_zam_choice(message: Message):
    zams = get_zam_nicknames()
    if not zams:
        await message.answer("⚠️ Список замов пока пуст. Обратитесь к владельцу.")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=zam, callback_data=f"zam_{zam}")]
        for zam in zams
    ])
    await message.answer("👤 Выберите, кто вас пригласил:", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("zam_"))
async def zam_selected(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in user_surveys:
        await callback.answer("❌ Анкета не найдена.")
        return
    zam = callback.data[4:]
    survey = user_surveys[user_id]
    survey["answers"]["inviter"] = zam
    await finish_survey(callback.message, user_id)
    await callback.answer(f"✅ Вы выбрали {zam}")

async def finish_survey(message: Message, user_id: int):
    survey = user_surveys.pop(user_id, None)
    if not survey:
        return
    answers = survey["answers"]

    old_data = data["users"].get(str(user_id))
    if old_data:
        old_inviter = old_data.get("inviter")
        if old_inviter in data["zam_stats"]:
            data["zam_stats"][old_inviter]["count"] -= 1
            data["zam_stats"][old_inviter]["earned"] -= 100000
            if "history" in data["zam_stats"][old_inviter]:
                data["zam_stats"][old_inviter]["history"] = [
                    h for h in data["zam_stats"][old_inviter]["history"]
                    if h["user_id"] != user_id
                ]
            save_data()

    user_data = {
        "nickname": answers.get("nickname", "—"),
        "tag": answers.get("tag", "—"),
        "rank_fam": answers.get("rank_fam", "—"),
        "organization": answers.get("organization", "—"),
        "rank_org": answers.get("rank_org", "—"),
        "inviter": answers.get("inviter", "—")
    }

    data["users"][str(user_id)] = user_data
    save_data()

    app_id = f"app_{user_id}_{int(datetime.now().timestamp())}"
    data["applications"][app_id] = {
        "user_id": user_id,
        "data": user_data,
        "status": "pending",
        "created": datetime.now().isoformat(),
        "history": []
    }
    save_data()

    inviter = user_data["inviter"]
    if inviter in data["zam_stats"]:
        data["zam_stats"][inviter]["count"] += 1
        data["zam_stats"][inviter]["earned"] += 100000
        data["zam_stats"][inviter]["history"].append({
            "user_id": user_id,
            "nick": user_data["nickname"],
            "time": datetime.now().isoformat()
        })
        save_data()

        if data["zam_stats"][inviter]["count"] >= 5:
            zam_user_id = get_zam_user_id(inviter)
            if zam_user_id:
                try:
                    await bot.send_message(
                        zam_user_id,
                        f"🎉 <b>Поздравляем!</b>\nВы привели {data['zam_stats'][inviter]['count']} человек!\nТеперь вы можете вывести средства (минимум 100k).\nДля вывода обратитесь к владельцу."
                    )
                except:
                    pass

    await message.answer("✅ <b>Анкета заполнена! Ваша заявка отправлена администраторам.</b>")

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", callback_data=f"accept:{app_id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{app_id}")]
    ])
    user_name = message.from_user.full_name or message.from_user.username or "Пользователь"
    for admin_id in get_admins():
        try:
            await bot.send_message(
                admin_id,
                f"📩 <b>Новая заявка!</b>\n"
                f"От: {user_name}\n"
                f"Nickname: {user_data['nickname']}\n"
                f"Тег в ТГ: {user_data['tag']}\n"
                f"Ранг в фаме: {user_data['rank_fam']}\n"
                f"Организация: {user_data['organization']}\n"
                f"Ранг в организации: {user_data['rank_org']}\n"
                f"Пригласитель: {user_data['inviter']}",
                reply_markup=keyboard
            )
        except Exception as e:
            print(f"Не удалось уведомить админа {admin_id}: {e}")

# ===== КНОПКА "ЗАПОЛНИТЬ АНКЕТУ" =====
@dp.message(F.text == "📝 Заполнить анкету")
async def survey_button(message: Message):
    user_id = message.from_user.id
    if str(user_id) in data["users"]:
        await log_action(user_id, "кнопка Заполнить анкету", "уже заполнил анкету")
        await message.answer("ℹ️ Вы уже заполнили анкету. Используйте «🔄 Перезаполнить анкету», чтобы начать заново.")
        return
    await log_action(user_id, "кнопка Заполнить анкету", "начал")
    await start_survey(message)

# ===== ПРИНЯТЬ =====
@dp.callback_query(F.data.startswith("accept:"))
async def accept_application(callback: CallbackQuery):
    app_id = callback.data.split(":")[1]
    admin_id = callback.from_user.id
    admin_name = callback.from_user.full_name or callback.from_user.username or str(admin_id)
    await log_action(admin_id, "принятие", f"заявка {app_id}")
    if not is_admin(admin_id):
        await callback.answer("❌ Нет прав!")
        return
    app = data["applications"].get(app_id)
    if not app:
        await callback.answer("❌ Заявка не найдена!")
        return
    user_id = app["user_id"]
    nickname = app["data"].get("nickname", "Участник")
    app["status"] = "accepted"
    app["last_changed_by"] = admin_id
    app["last_changed_at"] = datetime.now().isoformat()
    if "history" not in app:
        app["history"] = []
    app["history"].append({
        "action": "accepted",
        "by": admin_id,
        "by_name": admin_name,
        "at": datetime.now().isoformat()
    })
    save_data()
    await add_user_to_group(user_id)
    await set_user_nickname(user_id, nickname)
    try:
        await bot.send_message(GROUP_ID, f"🎉 Добро пожаловать в семью, {nickname}! Будь как дома.")
    except:
        pass
    await callback.answer(f"✅ Заявка принята! Ник '{nickname}' установлен.")
    await callback.message.edit_reply_markup(reply_markup=None)
    for admin in get_admins():
        try:
            await bot.send_message(
                admin,
                f"🔄 <b>Вердикт изменён!</b>\nАдмин: {admin_name}\nПользователь: {app['data']['nickname']}\nНовый статус: ✅ ПРИНЯТ\nНик в группе: {nickname}"
            )
        except:
            pass

# ===== ОТКЛОНИТЬ =====
@dp.callback_query(F.data.startswith("reject:"))
async def reject_application(callback: CallbackQuery):
    app_id = callback.data.split(":")[1]
    admin_id = callback.from_user.id
    admin_name = callback.from_user.full_name or callback.from_user.username or str(admin_id)
    await log_action(admin_id, "отклонение", f"заявка {app_id}")
    if not is_admin(admin_id):
        await callback.answer("❌ Нет прав!")
        return
    app = data["applications"].get(app_id)
    if not app:
        await callback.answer("❌ Заявка не найдена!")
        return
    user_id = app["user_id"]
    app["status"] = "rejected"
    app["last_changed_by"] = admin_id
    app["last_changed_at"] = datetime.now().isoformat()
    if "history" not in app:
        app["history"] = []
    app["history"].append({
        "action": "rejected",
        "by": admin_id,
        "by_name": admin_name,
        "at": datetime.now().isoformat()
    })
    save_data()
    await remove_user_from_group(user_id)
    try:
        await bot.send_message(user_id, "❌ <b>Ваша заявка отклонена.</b>")
    except:
        pass
    await callback.answer("❌ Заявка отклонена!")
    await callback.message.edit_reply_markup(reply_markup=None)
    for admin in get_admins():
        try:
            await bot.send_message(
                admin,
                f"🔄 <b>Вердикт изменён!</b>\nАдмин: {admin_name}\nПользователь: {app['data']['nickname']}\nНовый статус: ❌ ОТКЛОНЕН"
            )
        except:
            pass

# ===== УПРАВЛЕНИЕ ЗАЯВКАМИ =====
@dp.message(F.text == "📋 Управление заявками")
async def all_applications(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет прав!")
        return
    await log_action(message.from_user.id, "кнопка Управление заявками", "")
    apps = data["applications"]
    if not apps:
        await message.answer("📭 Заявок нет.")
        return

    question_map = [
        ("Nickname", "nickname"),
        ("Тег в ТГ", "tag"),
        ("Ранг в фаме", "rank_fam"),
        ("Организация", "organization"),
        ("Ранг в организации", "rank_org"),
        ("Пригласитель", "inviter")
    ]

    idx = 1
    for app_id, app in apps.items():
        u = app["data"]
        status = app["status"]
        status_emoji = "⏳" if status == "pending" else ("✅" if status == "accepted" else "❌")
        text = f"{status_emoji} <b>Заявка #{idx}</b>\n"
        for q, key in question_map:
            answer = u.get(key, "—")
            text += f"{q}: {answer}\n"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять", callback_data=f"accept:{app_id}")],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{app_id}")]
        ])
        await message.answer(text, reply_markup=keyboard)
        idx += 1

@dp.message(F.text == "⏳ Активные заявки")
async def active_applications(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет прав!")
        return
    await log_action(message.from_user.id, "кнопка Активные заявки", "")
    pending_apps = {k: v for k, v in data["applications"].items() if v["status"] == "pending"}
    if not pending_apps:
        await message.answer("📭 Активных заявок нет.")
        return

    question_map = [
        ("Nickname", "nickname"),
        ("Тег в ТГ", "tag"),
        ("Ранг в фаме", "rank_fam"),
        ("Организация", "organization"),
        ("Ранг в организации", "rank_org"),
        ("Пригласитель", "inviter")
    ]

    idx = 1
    for app_id, app in pending_apps.items():
        u = app["data"]
        text = f"⏳ <b>Активная заявка #{idx}</b>\n"
        for q, key in question_map:
            answer = u.get(key, "—")
            text += f"{q}: {answer}\n"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять", callback_data=f"accept:{app_id}")],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{app_id}")]
        ])
        await message.answer(text, reply_markup=keyboard)
        idx += 1

# ===== СПИСОК УЧАСТНИКОВ =====
@dp.message(F.text == "👥 Список участников")
async def list_users(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет прав!")
        return
    await log_action(message.from_user.id, "кнопка Список участников", "")
    users = list(data["users"].items())
    if not users:
        await message.answer("📭 Нет заполненных анкет.")
        return
    page = 0
    await send_users_page(message, users, page)

async def send_users_page(message: Message, users, page):
    per_page = 3
    total = len(users)
    pages = (total + per_page - 1) // per_page
    if page < 0 or page >= pages:
        return
    start = page * per_page
    end = min(start + per_page, total)
    text = "👥 <b>Список участников (заполнившие анкету)</b>\n\n"
    for i in range(start, end):
        user_id, u = users[i]
        try:
            user = await bot.get_user(int(user_id))
            tag = f"@{user.username}" if user.username else user.full_name
        except:
            tag = str(user_id)
        text += f"<b>{i+1}.</b> {u['nickname']} — {tag}\n"
        text += f"   Ранг: {u['rank_fam']} | Орг: {u['organization']} | Пригласил: {u['inviter']}\n\n"
    text += f"Страница {page+1} из {pages}"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    if page > 0:
        keyboard.inline_keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"userpage_{page-1}")])
    if page < pages - 1:
        keyboard.inline_keyboard.append([InlineKeyboardButton("➡️ Вперёд", callback_data=f"userpage_{page+1}")])
    await message.answer(text, reply_markup=keyboard)

@dp.callback_query(F.data.startswith("userpage_"))
async def userpage_callback(callback: CallbackQuery):
    page = int(callback.data.split("_")[1])
    users = list(data["users"].items())
    await send_users_page(callback.message, users, page)
    await callback.answer()

# ===== СТАТУС БОТА =====
@dp.message(F.text == "🟢 Статус бота")
async def status_button(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет прав!")
        return
    await log_action(message.from_user.id, "кнопка Статус бота", "")
    total = len(data["users"])
    pending = sum(1 for app in data["applications"].values() if app["status"] == "pending")
    rejected = sum(1 for app in data["applications"].values() if app["status"] == "rejected")
    accepted = sum(1 for app in data["applications"].values() if app["status"] == "accepted")
    admins_list = []
    for admin_id in get_admins():
        admins_list.append(get_admin_display(admin_id))
    admins_text = "\n".join(admins_list) if admins_list else "Нет"
    await message.answer(
        f"🟢 <b>Бот работает!</b>\n\n📊 <b>Статистика:</b>\n👥 Всего пользователей: {total}\n📩 Ожидают заявки: {pending}\n✅ Принято: {accepted}\n❌ Отклонено: {rejected}\n\n👑 <b>Админы:</b>\n{admins_text}"
    )

# ===== МОЙ ПРОФИЛЬ =====
@dp.message(F.text == "👤 Мой профиль")
async def my_profile(message: Message):
    user_id = str(message.from_user.id)
    await log_action(message.from_user.id, "кнопка Мой профиль", "")
    if user_id in data["users"]:
        u = data["users"][user_id]
        await message.answer(
            f"👤 <b>Ваш профиль:</b>\nNickname: {u['nickname']}\nТег в ТГ: {u['tag']}\nРанг в фаме: {u['rank_fam']}\nОрганизация: {u['organization']}\nРанг в организации: {u['rank_org']}\nПригласитель: {u['inviter']}"
        )
    else:
        await message.answer("ℹ️ Вы ещё не заполнили анкету. Нажмите «📝 Заполнить анкету».")

# ===== АДМИНИСТРИРОВАНИЕ =====
@dp.message(F.text == "👑 Администрирование")
async def manage_admins(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец может управлять админами!")
        return
    await log_action(message.from_user.id, "кнопка Администрирование", "")
    current_admins = get_admins()
    text = "👑 <b>Администрирование</b>\n\n📋 <b>Текущие админы:</b>\n"
    for admin_id in current_admins:
        text += f"• {get_admin_display(admin_id)}\n"
    text += "\n<b>Команды:</b>\n"
    text += "/add_admin adm @username — добавить админа\n"
    text += "/remove_admin adm @username — удалить админа\n"
    text += "/add_admin zam @username Nik: игровой_ник — добавить зама\n"
    text += "/remove_admin zam @username — удалить зама\n"
    await message.answer(text)

# ===== ДОБАВЛЕНИЕ/УДАЛЕНИЕ АДМИНОВ И ЗАМОВ =====
@dp.message(Command("add_admin"))
async def add_admin_command(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Использование: /add_admin adm @username  или /add_admin zam @username Nik: игровой_ник")
        return
    parts = args[1].split()
    if len(parts) < 2:
        await message.answer("❌ Недостаточно аргументов.")
        return
    type_ = parts[0].lower()
    username = parts[1].lstrip('@')
    if type_ == "adm":
        try:
            user = await bot.get_user(username)
            user_id = user.id
        except:
            await message.answer(f"❌ Пользователь @{username} не найден.")
            return
        current_admins = get_admins()
        if user_id in current_admins:
            await message.answer(f"❌ @{username} уже является админом.")
            return
        current_admins.add(user_id)
        save_admins(current_admins)
        # Сохраняем информацию об админе
        if "admin_usernames" not in data:
            data["admin_usernames"] = {}
        info = {}
        if user.username:
            info["username"] = user.username
        if user.full_name:
            info["full_name"] = user.full_name
        if not info:
            info["full_name"] = str(user_id)
        data["admin_usernames"][str(user_id)] = info
        save_data()
        await message.answer(f"✅ Админ @{username} добавлен.")
        try:
            await bot.send_message(user_id, "👑 <b>Вы назначены администратором!</b>")
        except:
            pass
        return
    elif type_ == "zam":
        if len(parts) < 4 or parts[2].lower() != "nik:":
            await message.answer("❌ Формат: /add_admin zam @username Nik: игровой_ник")
            return
        game_nick = " ".join(parts[3:])
        if not game_nick:
            await message.answer("❌ Игровой ник не может быть пустым.")
            return
        try:
            user = await bot.get_user(username)
            user_id = user.id
        except:
            await message.answer(f"❌ Пользователь @{username} не найден.")
            return
        if game_nick in data["zam_data"]:
            await message.answer(f"❌ Игровой ник '{game_nick}' уже используется.")
            return
        for nick, info in data["zam_data"].items():
            if info["tg_user_id"] == user_id:
                await message.answer(f"❌ @{username} уже является замом (ник '{nick}').")
                return
        data["zam_data"][game_nick] = {"tg_user_id": user_id, "tg_username": username}
        if game_nick not in data["zam_stats"]:
            data["zam_stats"][game_nick] = {"count": 0, "earned": 0, "history": []}
        save_data()
        await message.answer(f"✅ Зам '{game_nick}' (@{username}) добавлен.")
        try:
            await bot.send_message(user_id, f"👑 <b>Вы назначены замом!</b>\nВаш игровой ник: {game_nick}")
        except:
            pass
        return
    else:
        await message.answer("❌ Неизвестный тип. Используйте adm или zam.")

@dp.message(Command("remove_admin"))
async def remove_admin_command(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец!")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Использование: /remove_admin adm @username  или /remove_admin zam @username")
        return
    parts = args[1].split()
    if len(parts) < 2:
        await message.answer("❌ Недостаточно аргументов.")
        return
    type_ = parts[0].lower()
    username = parts[1].lstrip('@')
    if type_ == "adm":
        try:
            user = await bot.get_user(username)
            user_id = user.id
        except:
            await message.answer(f"❌ Пользователь @{username} не найден.")
            return
        if user_id == SUPER_ADMIN:
            await message.answer("❌ Нельзя удалить владельца!")
            return
        current_admins = get_admins()
        if user_id not in current_admins:
            await message.answer(f"❌ @{username} не является админом.")
            return
        current_admins.remove(user_id)
        save_admins(current_admins)
        if "admin_usernames" in data and str(user_id) in data["admin_usernames"]:
            del data["admin_usernames"][str(user_id)]
            save_data()
        await message.answer(f"✅ Админ @{username} удалён.")
        try:
            await bot.send_message(user_id, "❌ <b>Вы больше не администратор.</b>")
        except:
            pass
        return
    elif type_ == "zam":
        game_nick = None
        for nick, info in data["zam_data"].items():
            if info["tg_username"].lower() == username.lower():
                game_nick = nick
                break
        if not game_nick:
            await message.answer(f"❌ Зам с @{username} не найден.")
            return
        del data["zam_data"][game_nick]
        if game_nick in data["zam_stats"]:
            del data["zam_stats"][game_nick]
        save_data()
        await message.answer(f"✅ Зам '{game_nick}' (@{username}) удалён.")
        return
    else:
        await message.answer("❌ Неизвестный тип. Используйте adm или zam.")

# ===== БАНК ЗАМОВ =====
@dp.message(Command("zam_stats"))
async def zam_stats_command(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только для владельца!")
        return
    stats = data.get("zam_stats", {})
    if not stats:
        await message.answer("📭 Банк замов пуст.")
        return
    text = "🏦 <b>БАНК ЗАМОВ</b>\n\n"
    for zam, info in stats.items():
        count = info["count"]
        earned = info["earned"]
        text += f"<b>{zam}</b> → {count} чел. | {earned:,} $\n"
    await message.answer(text)

@dp.message(F.text == "🏦 Банк замов")
async def zam_stats_button(message: Message):
    await zam_stats_command(message)

# ===== ВЫВОД ДЕНЕГ =====
@dp.message(Command("withdraw"))
async def withdraw_command(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только для владельца!")
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("❌ Использование: /withdraw @ник_зама сумма (в тыс., например 100)")
        return
    username = args[1].lstrip('@')
    try:
        amount = int(args[2])
    except ValueError:
        await message.answer("❌ Сумма должна быть числом (тыс.).")
        return
    if amount < 100:
        await message.answer("❌ Минимальная сумма 100 тыс.")
        return
    if amount % 100 != 0:
        await message.answer("❌ Сумма должна быть кратна 100 тыс.")
        return
    game_nick = None
    for nick, info in data["zam_data"].items():
        if info["tg_username"].lower() == username.lower():
            game_nick = nick
            break
    if not game_nick:
        await message.answer(f"❌ Зам с @{username} не найден.")
        return
    zam_stats = data.get("zam_stats", {})
    if game_nick not in zam_stats:
        await message.answer(f"❌ Статистика для зама {game_nick} отсутствует.")
        return
    info = zam_stats[game_nick]
    required_people = amount // 100
    if info["count"] < required_people:
        await message.answer(f"❌ У зама {game_nick} недостаточно приглашённых ({info['count']}). Нужно {required_people} человек.")
        return
    info["count"] -= required_people
    info["earned"] -= amount * 1000
    save_data()
    zam_user_id = get_zam_user_id(game_nick)
    if zam_user_id:
        try:
            await bot.send_message(
                zam_user_id,
                f"💰 <b>С вашего счёта списано {amount}k.</b>\nОстаток приглашённых: {info['count']}\nДоступно для вывода: {info['count']*100}k"
            )
        except:
            pass
    await message.answer(f"✅ Снято {amount}k с {game_nick}. Остаток: {info['count']} чел.")

# ===== ЖУРНАЛ ДЕЙСТВИЙ =====
@dp.message(Command("logs"))
async def get_logs(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только для владельца!")
        return
    await log_action(message.from_user.id, "команда /logs", "")
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        lines = []
    if not lines:
        await message.answer("📭 Лог-файл пока не создан.")
        return
    page = 0
    await send_logs_page(message, lines, page)

async def send_logs_page(message: Message, lines, page):
    per_page = 10
    total = len(lines)
    pages = (total + per_page - 1) // per_page
    if page < 0 or page >= pages:
        return
    start = page * per_page
    end = min(start + per_page, total)
    text = "📋 <b>Журнал действий (последние записи)</b>\n\n" + "".join(lines[start:end])
    if len(text) > 4000:
        text = text[:3900] + "\n... (обрезано)"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    if page > 0:
        keyboard.inline_keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"logpage_{page-1}")])
    if page < pages - 1:
        keyboard.inline_keyboard.append([InlineKeyboardButton("➡️ Вперёд", callback_data=f"logpage_{page+1}")])
    await message.answer(text, reply_markup=keyboard)

@dp.callback_query(F.data.startswith("logpage_"))
async def logpage_callback(callback: CallbackQuery):
    page = int(callback.data.split("_")[1])
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        lines = []
    await send_logs_page(callback.message, lines, page)
    await callback.answer()

@dp.message(F.text == "📜 Журнал действий")
async def logs_button(message: Message):
    await get_logs(message)

# ===== ВКЛЮЧЕНИЕ/ВЫКЛЮЧЕНИЕ УВЕДОМЛЕНИЙ =====
@dp.message(Command("log_on"))
async def log_on(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только для владельца!")
        return
    data["log_notify_enabled"] = True
    save_data()
    await message.answer("✅ Уведомления о действиях включены. Теперь вы будете получать сообщения о каждом действии в боте.")

@dp.message(Command("log_off"))
async def log_off(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только для владельца!")
        return
    data["log_notify_enabled"] = False
    save_data()
    await message.answer("❌ Уведомления о действиях выключены.")

# ===== ПИНГ С UPTIME =====
@dp.message(Command("ping"))
@dp.message(Command("info"))
async def ping_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Только для админов!")
        return
    start = datetime.now()
    msg = await message.answer("🏓 Понг...")
    delta = (datetime.now() - start).microseconds / 1000
    uptime = datetime.now() - BOT_START_TIME
    days = uptime.days
    hours, rem = divmod(uptime.seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    uptime_str = f"{days}д {hours}ч {minutes}м {seconds}с"
    await msg.edit_text(
        f"🏓 Понг! Задержка: {delta:.1f} мс\n"
        f"⏱ Время работы бота: {uptime_str}"
    )

# ===== HELP =====
@dp.message(Command("help"))
async def help_command(message: Message):
    commands = [
        ("/start", "🏠 Главное меню"),
        ("/help", "📖 Справка"),
        ("/кто", "👤 Информация о пользователе (ответить на сообщение)"),
        ("/ping", "📡 Пинг и время работы (админы)"),
        ("/info", "📡 Пинг и время работы (админы)"),
        ("/all", "📢 Объявление (админы)"),
        ("/add_admin", "➕ Добавить админа/зама (владелец)"),
        ("/remove_admin", "➖ Удалить админа/зама (владелец)"),
        ("/admins", "👑 Список админов (владелец)"),
        ("/logs", "📜 Журнал действий (владелец)"),
        ("/clearlogs", "🗑 Очистить журнал (владелец)"),
        ("/zam_stats", "🏦 Банк замов (владелец)"),
        ("/withdraw", "💰 Вывод денег (владелец)"),
        ("/set_token", "🔑 Смена токена (владелец)"),
        ("/topic_id", "🆔 ID темы"),
        ("/log_on", "🔔 Включить уведомления (владелец)"),
        ("/log_off", "🔕 Выключить уведомления (владелец)"),
    ]
    text = "📋 <b>Доступные команды:</b>\n\n"
    for cmd, desc in commands:
        text += f"{cmd} — {desc}\n"
    await message.answer(text)

# ===== ЗАЩИТА ТЕМЫ "НОВОСТИ" =====
@dp.message(F.chat.id == GROUP_ID)
async def protect_announce_topic(message: Message):
    if message.message_thread_id == ANNOUNCE_TOPIC_ID:
        if not is_admin(message.from_user.id):
            await message.delete()
            await bot.send_message(
                GROUP_ID,
                f"❌ {message.from_user.full_name}, в этой теме могут писать только администраторы!",
                reply_to_message_id=message.message_id
            )

# ===== /all =====
@dp.message(Command("all"))
async def all_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Только для админов!")
        return
    if ANNOUNCE_TOPIC_ID == 0:
        await message.answer("❌ ID темы 'Новости' не настроен.")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Использование: /all <текст объявления>")
        return
    msg_text = args[1]
    try:
        await bot.send_message(
            GROUP_ID,
            f"⚠️ <b>ВНИМАНИЕ! ВАЖНОЕ ОБЪЯВЛЕНИЕ</b>\n\n{msg_text}\n\n@all",
            message_thread_id=ANNOUNCE_TOPIC_ID
        )
        await message.answer("✅ Объявление отправлено в тему 'Новости'.")
    except Exception as e:
        await message.answer(f"❌ Ошибка при отправке: {e}")

# ===== /topic_id =====
@dp.message(Command("topic_id"))
async def get_topic_id(message: Message):
    if message.chat.id == GROUP_ID and message.message_thread_id:
        await message.answer(f"ID этой темы: {message.message_thread_id}")
    else:
        await message.answer("❌ Это сообщение не в теме, или ID не найден.")

# ===== /admins =====
@dp.message(Command("admins"))
async def admins_command(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только для владельца!")
        return
    await log_action(message.from_user.id, "команда /admins", "")
    admins = get_admins()
    if not admins:
        await message.answer("📭 Админов нет.")
        return
    text = "👑 <b>Список админов</b>\n\n"
    for admin_id in admins:
        text += f"• {get_admin_display(admin_id)}\n"
    await message.answer(text)

# ===== /set_token =====
@dp.message(Command("set_token"))
async def set_token_command(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только для владельца!")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Использование: /set_token <новый_токен>")
        return
    new_token = args[1].strip()
    if not new_token.startswith("876"):
        await message.answer("❌ Неверный формат токена.")
        return
    data["bot_token"] = new_token
    save_data()
    await message.answer("✅ Токен обновлён! Бот перезапускается...")
    os._exit(0)

# ===== /start =====
@dp.message(CommandStart())
async def start_command(message: Message):
    await log_action(message.from_user.id, "start", "запустил бота")
    await show_main_menu(message)

# ===== /clearlogs =====
@dp.message(Command("clearlogs"))
async def clear_logs(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только для владельца!")
        return
    await log_action(message.from_user.id, "команда /clearlogs", "")
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("")
    await message.answer("✅ Логи очищены.")

# ===== ЗАПУСК =====
async def main():
    print("🤖 Бот запущен!")
    # Инициализируем админов из ADMINS_USERNAMES
    await init_admins()
    
    commands = [
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="help", description="📖 Справка"),
        BotCommand(command="ping", description="📡 Пинг (админы)"),
        BotCommand(command="info", description="📡 Информация (админы)"),
        BotCommand(command="all", description="📢 Объявление (админы)"),
        BotCommand(command="add_admin", description="➕ Добавить админа/зама (владелец)"),
        BotCommand(command="remove_admin", description="➖ Удалить админа/зама (владелец)"),
        BotCommand(command="admins", description="👑 Список админов (владелец)"),
        BotCommand(command="logs", description="📜 Журнал (владелец)"),
        BotCommand(command="clearlogs", description="🗑 Очистить журнал (владелец)"),
        BotCommand(command="zam_stats", description="🏦 Банк замов (владелец)"),
        BotCommand(command="withdraw", description="💰 Вывод денег (владелец)"),
        BotCommand(command="set_token", description="🔑 Смена токена (владелец)"),
        BotCommand(command="topic_id", description="🆔 ID темы"),
        BotCommand(command="log_on", description="🔔 Включить уведомления (владелец)"),
        BotCommand(command="log_off", description="🔕 Выключить уведомления (владелец)"),
    ]
    await bot.set_my_commands(commands)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
