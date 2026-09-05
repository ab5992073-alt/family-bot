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
SUPER_ADMIN = 6166697485
ADMIN_IDS = {6166697485, 123456789, 6863392923, 1980341141}
GROUP_ID = -1002409536359
GROUP_LINK = "https://t.me/+f_eKIP4gwcs0YTcy"
BOT_NAME = "@Staff_Grand_Bot"

# ID темы "Новости"
ANNOUNCE_TOPIC_ID = 126387

# Защита группы отключена
PROTECTED_GROUP_ID = 0

# ===== СПИСОК ЗАМОВ =====
ZAM_LIST = [
    "Vusal_Cantrell", "Sinax_Agressor", "Ganka_Gankovich",
    "Meglenes_Stemmust", "Egor_Vendetta", "Amina_Dropkin",
    "Milena_Guenot", "K1LLER", "Nikita_Pandemic",
    "Sergey_Darknes", "Gleb_Maestro", "Gosha_Pinkman"
]

# ===== СПИСОК РАНГОВ В ФАМЕ =====
RANK_LIST = [
    "НОВИЧОК", "БандИТ", "Стрелок", "ФРАЕР",
    "ОХРАНИК", "СТ. ОХРАНИК", "РЕШАЛО", "ПОЛОЖЕНЕЦ", "ВОР"
]

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# ===== БАЗА ДАННЫХ =====
DATA_FILE = "data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"users": {}, "applications": {}, "admins": list(ADMIN_IDS), "zam_stats": {}, "bot_token": TOKEN}

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

data = load_data()

if "zam_stats" not in data:
    data["zam_stats"] = {}
    save_data()
if "bot_token" not in data:
    data["bot_token"] = TOKEN
    save_data()

def get_admins():
    if "admins" in data:
        return set(data["admins"])
    return ADMIN_IDS

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
    log_entry = f"[{timestamp}] {username} ({user_id}) -> {action} {details}\n"
    
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_entry)
    
    try:
        await bot.send_message(
            SUPER_ADMIN,
            f"👤 <b>{username}</b> ({user_id})\n"
            f"⚡ {action}\n"
            f"📝 {details}\n"
            f"🕐 {timestamp}"
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

def admin_keyboard(user_id):
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📋 Все заявки"), KeyboardButton(text="⏳ Активные"))
    builder.row(KeyboardButton(text="📊 Статистика"), KeyboardButton(text="🔄 История"))
    builder.row(KeyboardButton(text="🟢 Статус бота"))
    if is_super_admin(user_id):
        builder.row(KeyboardButton(text="👑 Управление админами"))
        builder.row(KeyboardButton(text="📜 Логи"))
        builder.row(KeyboardButton(text="📋 Замы"))
    return builder.as_markup(resize_keyboard=True)

# ===== ДОБАВЛЕНИЕ/УДАЛЕНИЕ ИЗ ГРУППЫ =====
async def add_user_to_group(user_id: int) -> bool:
    try:
        invite_link = await bot.create_chat_invite_link(GROUP_ID, member_limit=1)
        await bot.send_message(
            user_id,
            f"🔗 <b>Вы приняты в семью!</b>\n\n"
            f"<b>Вступите в группу по ссылке:</b>\n"
            f"{invite_link.invite_link}\n\n"
            f"Или по основной ссылке:\n"
            f"{GROUP_LINK}"
        )
        return True
    except Exception as e:
        print(f"Ошибка при создании ссылки: {e}")
        try:
            await bot.send_message(
                user_id,
                f"🔗 <b>Вы приняты в семью!</b>\n\n"
                f"<b>Вступите по ссылке:</b>\n"
                f"{GROUP_LINK}"
            )
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
        await bot.set_chat_member_custom_title(
            chat_id=GROUP_ID,
            user_id=user_id,
            custom_title=nickname
        )
        return True
    except Exception as e:
        print(f"Ошибка при установке ника: {e}")
        return False

# ===== КОМАНДА /кто =====
@dp.message(Command("кто"))
async def who_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет прав!")
        return
    await log_action(message.from_user.id, "команда /кто", f"запросил анкету у {message.reply_to_message.from_user.id if message.reply_to_message else 'никого'}")
    if not message.reply_to_message:
        await message.answer("❌ Ответьте на сообщение участника командой /кто")
        return

    target_user_id = message.reply_to_message.from_user.id
    user_data = data["users"].get(str(target_user_id))
    if not user_data:
        await message.answer("❌ У этого пользователя нет заполненной анкеты.")
        return

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
    if is_admin(user_id):
        await message.answer("🛡️ <b>Панель администратора</b>", reply_markup=admin_keyboard(user_id))
    else:
        has_survey = str(user_id) in data["users"]
        await message.answer(
            "👋 <b>Добро пожаловать!</b>\n"
            "Для вступления в семью нажмите:\n"
            "📝 <b>Заполнить анкету</b>",
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
    if old_inviter and old_inviter in ZAM_LIST:
        if old_inviter in data["zam_stats"]:
            data["zam_stats"][old_inviter]["count"] -= 1
            data["zam_stats"][old_inviter]["earned"] -= 100000
            if "history" in data["zam_stats"][old_inviter]:
                data["zam_stats"][old_inviter]["history"] = [
                    h for h in data["zam_stats"][old_inviter]["history"]
                    if h["user_id"] != int(user_id)
                ]
            save_data()

    await log_action(int(user_id), "сброс анкеты", "начал перезаполнение")
    await message.answer("✅ Анкета сброшена. Вы можете заполнить её заново.")
    await show_main_menu(message)

# ===== АНКЕТА С ВЫБОРОМ РАНГА И ЗАМА (ТЕГ АВТОМАТИЧЕСКИ) =====
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
        # Автоматически заполняем тег
        user = message.from_user
        if user.username:
            answers["tag"] = f"@{user.username}"
        else:
            answers["tag"] = str(user.id)
        survey["step"] = 1
        await show_rank_choice(message)
    elif step == 1: # выбор ранга обрабатывается в колбэке
        pass
    elif step == 2:
        answers["organization"] = message.text
        survey["step"] = 3
        await message.answer("4️⃣ Ваш ранг в организации?")
    elif step == 3:
        answers["rank_org"] = message.text
        survey["step"] = 4
        await show_zam_choice(message)
    else:
        await message.answer("⚠️ Что-то пошло не так. Начните анкету заново /start")

async def show_rank_choice(message: Message):
    user_id = message.from_user.id
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
    survey["step"] = 2  # переходим к вопросу об организации
    await callback.answer(f"✅ Вы выбрали {rank}")
    await callback.message.answer("3️⃣ Ваша организация?")

async def show_zam_choice(message: Message):
    user_id = message.from_user.id
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=name, callback_data=f"zam_{name}")]
        for name in ZAM_LIST
    ])
    await message.answer("👤 Выберите, кто вас пригласил:", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("zam_"))
async def zam_selected(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in user_surveys:
        await callback.answer("❌ Анкета не найдена.")
        return

    zam_name = callback.data[4:]
    survey = user_surveys[user_id]
    survey["answers"]["inviter"] = zam_name
    await finish_survey(callback.message, user_id)
    await callback.answer(f"✅ Вы выбрали {zam_name}")

async def finish_survey(message: Message, user_id: int):
    survey = user_surveys.pop(user_id, None)
    if not survey:
        return
    answers = survey["answers"]

    # Удаляем старую анкету, если была
    old_data = data["users"].get(str(user_id))
    if old_data:
        old_inviter = old_data.get("inviter")
        if old_inviter and old_inviter in ZAM_LIST:
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
        "tag": answers.get("tag", "—"),  # уже автоматически заполнен
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
    if inviter in ZAM_LIST:
        if inviter not in data["zam_stats"]:
            data["zam_stats"][inviter] = {"count": 0, "earned": 0, "history": []}
        data["zam_stats"][inviter]["count"] += 1
        data["zam_stats"][inviter]["earned"] += 100000
        data["zam_stats"][inviter]["history"].append({
            "user_id": user_id,
            "nick": user_data["nickname"],
            "time": datetime.now().isoformat()
        })
        save_data()

        if data["zam_stats"][inviter]["count"] >= 5:
            zam_user_id = None
            for uid, udata in data["users"].items():
                if udata.get("nickname") == inviter:
                    zam_user_id = int(uid)
                    break
            if zam_user_id:
                try:
                    await bot.send_message(
                        zam_user_id,
                        f"🎉 <b>Поздравляем!</b>\n"
                        f"Вы привели {data['zam_stats'][inviter]['count']} человек!\n"
                        f"Теперь вы можете вывести 500k (5 человек).\n"
                        f"Для вывода обратитесь к владельцу."
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
                f"🔄 <b>Вердикт изменён!</b>\n"
                f"Админ: {admin_name}\n"
                f"Пользователь: {app['data']['nickname']}\n"
                f"Новый статус: ✅ ПРИНЯТ\n"
                f"Ник в группе: {nickname}"
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
                f"🔄 <b>Вердикт изменён!</b>\n"
                f"Админ: {admin_name}\n"
                f"Пользователь: {app['data']['nickname']}\n"
                f"Новый статус: ❌ ОТКЛОНЕН"
            )
        except:
            pass

# ===== ВСЕ ЗАЯВКИ =====
@dp.message(F.text == "📋 Все заявки")
async def all_applications(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет прав!")
        return

    await log_action(message.from_user.id, "кнопка Все заявки", "")
    apps = data["applications"]
    if not apps:
        await message.answer("📭 Заявок нет.")
        return

    for app_id, app in apps.items():
        u = app["data"]
        status = app["status"]
        status_emoji = "⏳" if status == "pending" else ("✅" if status == "accepted" else "❌")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять", callback_data=f"accept:{app_id}")],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{app_id}")]
        ])
        await message.answer(
            f"{status_emoji} <b>Заявка</b>\n"
            f"Nickname: {u['nickname']}\n"
            f"Тег в ТГ: {u['tag']}\n"
            f"Ранг в фаме: {u['rank_fam']}\n"
            f"Организация: {u['organization']}\n"
            f"Ранг в организации: {u['rank_org']}\n"
            f"Пригласитель: {u['inviter']}\n"
            f"Статус: {status}\n"
            f"ID: {app_id}",
            reply_markup=keyboard
        )

# ===== АКТИВНЫЕ ЗАЯВКИ =====
@dp.message(F.text == "⏳ Активные")
async def active_applications(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет прав!")
        return

    await log_action(message.from_user.id, "кнопка Активные", "")
    pending_apps = {k: v for k, v in data["applications"].items() if v["status"] == "pending"}
    if not pending_apps:
        await message.answer("📭 Активных заявок нет.")
        return

    for app_id, app in pending_apps.items():
        u = app["data"]
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять", callback_data=f"accept:{app_id}")],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{app_id}")]
        ])
        await message.answer(
            f"⏳ <b>Активная заявка</b>\n"
            f"Nickname: {u['nickname']}\n"
            f"Тег в ТГ: {u['tag']}\n"
            f"Ранг в фаме: {u['rank_fam']}\n"
            f"Организация: {u['organization']}\n"
            f"Ранг в организации: {u['rank_org']}\n"
            f"Пригласитель: {u['inviter']}\n"
            f"ID: {app_id}",
            reply_markup=keyboard
        )

# ===== СТАТИСТИКА =====
@dp.message(F.text == "📊 Статистика")
async def stats_button(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет прав!")
        return

    await log_action(message.from_user.id, "кнопка Статистика", "")
    total = len(data["users"])
    pending = sum(1 for app in data["applications"].values() if app["status"] == "pending")
    rejected = sum(1 for app in data["applications"].values() if app["status"] == "rejected")
    accepted = sum(1 for app in data["applications"].values() if app["status"] == "accepted")
    await message.answer(
        f"📊 <b>Статистика</b>\n"
        f"👥 Пользователей: {total}\n"
        f"📩 Ожидают: {pending}\n"
        f"✅ Принято: {accepted}\n"
        f"❌ Отклонено: {rejected}"
    )

# ===== ИСТОРИЯ =====
@dp.message(F.text == "🔄 История")
async def history_button(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Нет прав!")
        return

    await log_action(message.from_user.id, "кнопка История", "")
    apps = data["applications"]
    if not apps:
        await message.answer("📭 Заявок нет.")
        return
    for app_id, app in apps.items():
        history = app.get("history", [])
        if not history:
            continue
        text = f"📋 <b>История {app_id}</b>\n\n"
        for entry in history[-5:]:
            action = "✅" if entry["action"] == "accepted" else "❌"
            text += f"{action} {entry['by_name']} — {entry['at'][:16]}\n"
        await message.answer(text)

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
    admins_list = ", ".join([str(a) for a in get_admins()])
    await message.answer(
        f"🟢 <b>Бот работает!</b>\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"👥 Всего пользователей: {total}\n"
        f"📩 Ожидают заявки: {pending}\n"
        f"✅ Принято: {accepted}\n"
        f"❌ Отклонено: {rejected}\n\n"
        f"👑 <b>Админы:</b>\n"
        f"{admins_list}"
    )

# ===== МОЙ ПРОФИЛЬ =====
@dp.message(F.text == "👤 Мой профиль")
async def my_profile(message: Message):
    user_id = str(message.from_user.id)
    await log_action(message.from_user.id, "кнопка Мой профиль", "")
    if user_id in data["users"]:
        u = data["users"][user_id]
        await message.answer(
            f"👤 <b>Ваш профиль:</b>\n"
            f"Nickname: {u['nickname']}\n"
            f"Тег в ТГ: {u['tag']}\n"
            f"Ранг в фаме: {u['rank_fam']}\n"
            f"Организация: {u['organization']}\n"
            f"Ранг в организации: {u['rank_org']}\n"
            f"Пригласитель: {u['inviter']}"
        )
    else:
        await message.answer("ℹ️ Вы ещё не заполнили анкету. Нажмите «📝 Заполнить анкету».")

# ===== УПРАВЛЕНИЕ АДМИНАМИ =====
@dp.message(F.text == "👑 Управление админами")
async def manage_admins(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец может управлять админами!")
        return

    await log_action(message.from_user.id, "кнопка Управление админами", "")
    current_admins = get_admins()
    text = "👑 <b>Управление админами</b>\n\n"
    text += "📋 <b>Текущие админы (ID):</b>\n"
    for admin_id in current_admins:
        try:
            user = await bot.get_user(admin_id)
            username = f"@{user.username}" if user.username else user.full_name
        except:
            username = str(admin_id)
        text += f"• {username} ({admin_id})\n"

    text += "\n<b>Команды:</b>\n"
    text += "/add_admin 123456789 — добавить по ID\n"
    text += "/add_admin @username — добавить по тегу\n"
    text += "/remove_admin 123456789 — удалить по ID\n"
    text += "/remove_admin @username — удалить по тегу\n"

    await message.answer(text)

@dp.message(Command("add_admin"))
async def add_admin_command(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец может добавлять админов!")
        return

    await log_action(message.from_user.id, "команда add_admin", "")
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Использование: /add_admin <ID или @username>")
        return

    arg = args[1].strip()
    user_id = None

    if arg.startswith('@'):
        username = arg[1:]
        try:
            user = await bot.get_user(username)
            user_id = user.id
        except Exception:
            await message.answer(f"❌ Пользователь {arg} не найден.")
            return
    else:
        try:
            user_id = int(arg)
        except ValueError:
            await message.answer("❌ Неверный формат. Укажите ID (число) или @username.")
            return

    if user_id is None:
        await message.answer("❌ Не удалось определить пользователя.")
        return

    current_admins = get_admins()
    if user_id in current_admins:
        await message.answer(f"❌ Пользователь {user_id} уже является админом.")
        return

    current_admins.add(user_id)
    save_admins(current_admins)

    await message.answer(f"✅ Пользователь {user_id} добавлен в список админов!")

    try:
        user = await bot.get_user(user_id)
        name = f"@{user.username}" if user.username else user.full_name
        await bot.send_message(
            user_id,
            f"👑 <b>Вы назначены администратором!</b>\n\n"
            f"Теперь вам доступна админ-панель бота."
        )
    except:
        pass

@dp.message(Command("remove_admin"))
async def remove_admin_command(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец может удалять админов!")
        return

    await log_action(message.from_user.id, "команда remove_admin", "")
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Использование: /remove_admin <ID или @username>")
        return

    arg = args[1].strip()
    user_id = None

    if arg.startswith('@'):
        username = arg[1:]
        try:
            user = await bot.get_user(username)
            user_id = user.id
        except Exception:
            await message.answer(f"❌ Пользователь {arg} не найден.")
            return
    else:
        try:
            user_id = int(arg)
        except ValueError:
            await message.answer("❌ Неверный формат. Укажите ID (число) или @username.")
            return

    if user_id is None:
        await message.answer("❌ Не удалось определить пользователя.")
        return

    if user_id == SUPER_ADMIN:
        await message.answer("❌ Нельзя удалить владельца!")
        return

    current_admins = get_admins()
    if user_id not in current_admins:
        await message.answer(f"❌ Пользователь {user_id} не является админом.")
        return

    current_admins.remove(user_id)
    save_admins(current_admins)

    await message.answer(f"✅ Пользователь {user_id} удалён из списка админов.")

    try:
        await bot.send_message(
            user_id,
            f"❌ <b>Вы больше не администратор.</b>"
        )
    except:
        pass

# ===== ЛОГИ (команды для владельца) =====
@dp.message(Command("logs"))
async def get_logs(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только для владельца!")
        return

    await log_action(message.from_user.id, "команда /logs", "просмотр логов")
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        last_lines = lines[-30:] if lines else ["📭 Логов пока нет."]
        text = "📋 <b>Последние действия в боте:</b>\n\n"
        text += "".join(last_lines)
        if len(text) > 4000:
            text = text[:3900] + "\n... (обрезано)"
        await message.answer(text)
    except FileNotFoundError:
        await message.answer("📭 Лог-файл пока не создан.")

@dp.message(Command("clearlogs"))
async def clear_logs(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только для владельца!")
        return

    await log_action(message.from_user.id, "команда /clearlogs", "очистка логов")
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("")
    await message.answer("✅ Логи очищены.")

@dp.message(F.text == "📜 Логи")
async def logs_button(message: Message):
    await get_logs(message)

# ===== ПИНГ (для админов) =====
@dp.message(Command("ping"))
async def ping_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Только для админов!")
        return
    
    start = datetime.now()
    msg = await message.answer("🏓 Понг...")
    delta = (datetime.now() - start).microseconds / 1000
    await msg.edit_text(f"🏓 Понг! Задержка: {delta:.1f} мс")

# ===== ПОМОЩЬ (список команд) =====
@dp.message(Command("help"))
async def help_command(message: Message):
    commands = [
        ("/start", "Запустить бота / главное меню"),
        ("/help", "Показать список команд"),
        ("/кто", "Информация о пользователе (ответить на сообщение)"),
        ("/ping", "Проверить задержку (админы)"),
        ("/all", "Отправить важное объявление (админы)"),
        ("/add_admin", "Добавить админа по ID или @username (владелец)"),
        ("/remove_admin", "Удалить админа по ID или @username (владелец)"),
        ("/logs", "Показать логи (владелец)"),
        ("/clearlogs", "Очистить логи (владелец)"),
        ("/zam_stats", "Статистика замов (владелец)"),
        ("/withdraw", "Снять 500k с зама (владелец)"),
        ("/set_token", "Сменить токен бота (владелец)"),
    ]
    text = "📋 <b>Доступные команды:</b>\n\n"
    for cmd, desc in commands:
        text += f"{cmd} — {desc}\n"
    await message.answer(text)

# ===== ЗАЩИТА ТЕМЫ "НОВОСТИ" (только админы) =====
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

# ===== КОМАНДА /all (отправляет в тему "Новости") =====
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

# ===== КОМАНДА ДЛЯ ПОЛУЧЕНИЯ ID ТЕМЫ =====
@dp.message(Command("topic_id"))
async def get_topic_id(message: Message):
    if message.chat.id == GROUP_ID and message.message_thread_id:
        await message.answer(f"ID этой темы: {message.message_thread_id}")
    else:
        await message.answer("❌ Это сообщение не в теме, или ID не найден.")

# ===== СТАТИСТИКА ЗАМОВ =====
@dp.message(Command("zam_stats"))
async def zam_stats_command(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только для владельца!")
        return

    stats = data.get("zam_stats", {})
    if not stats:
        await message.answer("📭 Статистика замов пока пуста.")
        return

    text = "👑 <b>СТАТИСТИКА ЗАМОВ</b>\n\n"
    for zam, info in stats.items():
        count = info["count"]
        earned = info["earned"]
        text += f"<b>{zam}</b> → {count} чел. | {earned:,} $\n"
    await message.answer(text)

@dp.message(F.text == "📋 Замы")
async def zam_stats_button(message: Message):
    await zam_stats_command(message)

# ===== ВЫВОД ДЕНЕГ =====
@dp.message(Command("withdraw"))
async def withdraw_command(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только для владельца!")
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Использование: /withdraw @ник_зама")
        return

    zam_username = args[1].strip().lstrip('@')
    zam_stats = data.get("zam_stats", {})
    if zam_username not in zam_stats:
        await message.answer(f"❌ Зам {zam_username} не найден.")
        return

    zam_info = zam_stats[zam_username]
    if zam_info["count"] < 5:
        await message.answer(f"❌ У {zam_username} недостаточно приглашённых ({zam_info['count']}). Нужно минимум 5.")
        return

    zam_info["count"] -= 5
    zam_info["earned"] -= 500000
    save_data()

    zam_user_id = None
    for uid, udata in data["users"].items():
        if udata.get("nickname") == zam_username:
            zam_user_id = int(uid)
            break
    if zam_user_id:
        try:
            await bot.send_message(
                zam_user_id,
                f"💰 <b>С вашего счёта списано 500k.</b>\n"
                f"Остаток приглашённых: {zam_info['count']}\n"
                f"Доступно для следующего вывода: {zam_info['count'] * 100000:,} $"
            )
        except:
            pass

    await message.answer(f"✅ Снято 500k с {zam_username}. Остаток: {zam_info['count']} чел.")

# ===== СМЕНА ТОКЕНА (для владельца) =====
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

# ===== /START =====
@dp.message(CommandStart())
async def start_command(message: Message):
    await log_action(message.from_user.id, "start", "запустил бота")
    await show_main_menu(message)

# ===== ЗАПУСК =====
async def main():
    print("🤖 Бот запущен!")
    
    commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="help", description="Список команд"),
        BotCommand(command="ping", description="Проверить задержку (админы)"),
        BotCommand(command="all", description="Отправить важное объявление (админы)"),
        BotCommand(command="topic_id", description="Узнать ID текущей темы"),
        BotCommand(command="add_admin", description="Добавить админа (владелец)"),
        BotCommand(command="remove_admin", description="Удалить админа (владелец)"),
        BotCommand(command="logs", description="Показать логи (владелец)"),
        BotCommand(command="clearlogs", description="Очистить логи (владелец)"),
        BotCommand(command="zam_stats", description="Статистика замов (владелец)"),
        BotCommand(command="withdraw", description="Снять 500k с зама (владелец)"),
        BotCommand(command="set_token", description="Сменить токен бота (владелец)"),
    ]
    await bot.set_my_commands(commands)
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
