import asyncio
import json
import os
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

# ID темы "Новости" – замени на реальный ID после получения через /topic_id
ANNOUNCE_TOPIC_ID = 0  # <-- сюда вставь ID темы

# Группа, которую защищаем (только админы могут писать) – можно использовать ту же группу
PROTECTED_GROUP_ID = -1002409536359

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# ===== БАЗА ДАННЫХ =====
DATA_FILE = "data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"users": {}, "applications": {}, "admins": list(ADMIN_IDS)}

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

data = load_data()

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

# ===== ЛОГИРОВАНИЕ ДЕЙСТВИЙ =====
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
def main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📝 Заполнить анкету"))
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
    return builder.as_markup(resize_keyboard=True)

# ===== ДОБАВЛЕНИЕ ЧЕРЕЗ ССЫЛКУ =====
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
        await message.answer(
            "👋 <b>Добро пожаловать!</b>\n"
            "Для вступления в семью нажмите:\n"
            "📝 <b>Заполнить анкету</b>",
            reply_markup=main_keyboard()
        )

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

    questions = [
        ("nickname", "2️⃣ Ваш Тег в Telegram @ ?"),
        ("tag", "3️⃣ Ваш ранг в фаме (актуальный)?"),
        ("rank_fam", "4️⃣ Ваша организация?"),
        ("organization", "5️⃣ Ваш ранг в организации?"),
        ("rank_org", "6️⃣ Кто вас пригласил в фаму (Nickname)?")
    ]

    if step < len(questions):
        key, next_q = questions[step]
        answers[key] = message.text
        survey["step"] += 1
        if survey["step"] < len(questions):
            await message.answer(f"{next_q}")
        else:
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

            await log_action(user_id, "анкета", f"заполнил анкету (app {app_id})")
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

            del user_surveys[user_id]

# ===== КНОПКА "ЗАПОЛНИТЬ АНКЕТУ" =====
@dp.message(F.text == "📝 Заполнить анкету")
async def survey_button(message: Message):
    user_id = message.from_user.id
    if str(user_id) in data["users"]:
        await log_action(user_id, "кнопка Заполнить анкету", "уже заполнил анкету")
        await message.answer("ℹ️ Вы уже заполнили анкету. Ожидайте решения администрации.")
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
        text += f"• {admin_id}\n"

    text += "\n<b>Команды:</b>\n"
    text += "/add_admin 123456789 — добавить админа\n"
    text += "/remove_admin 123456789 — удалить админа\n"

    await message.answer(text)

@dp.message(Command("add_admin"))
async def add_admin_command(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только владелец может добавлять админов!")
        return

    await log_action(message.from_user.id, "команда add_admin", "")
    args = message.text.split()
    if len(args) != 2:
        await message.answer("❌ Использование: /add_admin 123456789")
        return

    try:
        new_admin_id = int(args[1])
    except ValueError:
        await message.answer("❌ ID должен быть числом!")
        return

    current_admins = get_admins()
    if new_admin_id in current_admins:
        await message.answer(f"❌ Пользователь {new_admin_id} уже является админом.")
        return

    current_admins.add(new_admin_id)
    save_admins(current_admins)

    await message.answer(f"✅ Пользователь {new_admin_id} добавлен в список админов!")

    try:
        await bot.send_message(
            new_admin_id,
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
    args = message.text.split()
    if len(args) != 2:
        await message.answer("❌ Использование: /remove_admin 123456789")
        return

    try:
        admin_id_to_remove = int(args[1])
    except ValueError:
        await message.answer("❌ ID должен быть числом!")
        return

    if admin_id_to_remove == SUPER_ADMIN:
        await message.answer("❌ Нельзя удалить владельца!")
        return

    current_admins = get_admins()
    if admin_id_to_remove not in current_admins:
        await message.answer(f"❌ Пользователь {admin_id_to_remove} не является админом.")
        return

    current_admins.remove(admin_id_to_remove)
    save_admins(current_admins)

    await message.answer(f"✅ Пользователь {admin_id_to_remove} удалён из списка админов.")

    try:
        await bot.send_message(
            admin_id_to_remove,
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
        ("/add_admin", "Добавить админа (владелец)"),
        ("/remove_admin", "Удалить админа (владелец)"),
        ("/logs", "Показать логи (владелец)"),
        ("/clearlogs", "Очистить логи (владелец)"),
    ]
    text = "📋 <b>Доступные команды:</b>\n\n"
    for cmd, desc in commands:
        text += f"{cmd} — {desc}\n"
    await message.answer(text)

# ===== ЗАЩИТА ГРУППЫ (только админы могут писать) =====
@dp.message(F.chat.id == PROTECTED_GROUP_ID)
async def protect_group(message: Message):
    if not is_admin(message.from_user.id):
        await message.delete()
        await bot.send_message(
            PROTECTED_GROUP_ID,
            f"❌ {message.from_user.full_name}, только администраторы могут писать в эту группу!",
            reply_to_message_id=message.message_id
        )

# ===== КОМАНДА /all (отправить объявление в тему "Новости") =====
@dp.message(Command("all"))
async def all_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Только для админов!")
        return
    if ANNOUNCE_TOPIC_ID == 0:
        await message.answer("❌ ID темы 'Новости' не настроен. Используйте /topic_id в теме, чтобы узнать ID.")
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
    ]
    await bot.set_my_commands(commands)
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
