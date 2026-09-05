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

# ID темы "Новости"
ANNOUNCE_TOPIC_ID = 126387

# Защита группы отключена
PROTECTED_GROUP_ID = 0

# ===== СПИСОК ЗАМОВ ДЛЯ КОНКУРСА =====
ZAM_LIST = [
    "Vusal_Cantrell", "Sinax_Agressor", "Ganka_Gankovich",
    "Meglenes_Stemmust", "Egor_Vendetta", "Amina_Dropkin",
    "Milena_Guenot", "K1LLER", "Nikita_Pandemic",
    "Sergey_Darknes", "Gleb_Maestro", "Gosha_Pinkman"
]

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# ===== БАЗА ДАННЫХ =====
DATA_FILE = "data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"users": {}, "applications": {}, "admins": list(ADMIN_IDS), "zam_stats": {}}

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

data = load_data()

# Инициализация статистики для замов, если ещё нет
if "zam_stats" not in data:
    data["zam_stats"] = {}
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
        builder.row(KeyboardButton(text="📋 Замы"))  # кнопка для статистики замов
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

# ===== АНКЕТА (С ВЫБОРОМ ЗАМА) =====
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
        ("rank_org", "6️⃣ Кто вас пригласил? (выберите из списка)")
    ]

    # Текстовые вопросы (первые 4)
    if step < 4:
        key, next_q = questions[step]
        answers[key] = message.text
        survey["step"] += 1
        if survey["step"] < 4:
            await message.answer(f"{next_q}")
        else:
            # После 4-го текстового вопроса переходим к выбору зама
            survey["step"] = "zam"
            await show_zam_choice(message)
        return

# ===== ВЫБОР ЗАМА =====
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

    # Получаем выбранного зама
    zam_name = callback.data[4:]
    answers = user_surveys[user_id]["answers"]
    answers["inviter"] = zam_name  # сохраняем в анкету

    # Завершаем анкету
    await finish_survey(callback.message, user_id)
    await callback.answer(f"✅ Вы выбрали {zam_name}")

async def finish_survey(message: Message, user_id: int):
    survey = user_surveys.pop(user_id, None)
    if not survey:
        return
    answers = survey["answers"]

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

    # Обновляем статистику зама
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

        # Проверяем, достиг ли зам 5 человек
        if data["zam_stats"][inviter]["count"] >= 5:
            # Ищем ID зама (по нику)
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
        await message.answer("ℹ️ Вы уже заполнили анкету. Ожидайте решения администрации.")
        return
    await log_action(user_id, "кнопка Заполнить анкету", "начал")
    await start_survey(message)

# ===== ПРИНЯТЬ / ОТКЛОНИТЬ (без изменений) =====
# ... (код приёма/отклонения заявок остаётся как раньше – я не буду дублировать, чтобы не перегружать, но в финальном коде он будет)

# ===== СТАТИСТИКА ЗАМОВ (ДЛЯ ВЛАДЕЛЬЦА) =====
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

# ===== ВЫВОД ДЕНЕГ (СНЯТИЕ 500K) =====
@dp.message(Command("withdraw"))
async def withdraw_command(message: Message):
    if not is_super_admin(message.from_user.id):
        await message.answer("❌ Только для владельца!")
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Использование: /withdraw @ник_зама")
        return

    zam_username = args[1].strip()
    # Убираем @ если есть
    if zam_username.startswith('@'):
        zam_username = zam_username[1:]

    # Ищем зама по нику
    zam_stats = data.get("zam_stats", {})
    if zam_username not in zam_stats:
        await message.answer(f"❌ Зам {zam_username} не найден в статистике.")
        return

    zam_info = zam_stats[zam_username]
    if zam_info["count"] < 5:
        await message.answer(f"❌ У {zam_username} недостаточно приглашённых ({zam_info['count']}). Нужно минимум 5.")
        return

    # Списываем 5 человек (500k)
    zam_info["count"] -= 5
    zam_info["earned"] -= 500000
    save_data()

    # Уведомляем зама
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

# ===== ОСТАЛЬНЫЕ КОМАНДЫ (ПИНГ, HELP, ЛОГИ, ЗАЩИТА ТЕМЫ) =====
# ... (они такие же как в предыдущей версии – я включу их в финальный код)

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
    ]
    await bot.set_my_commands(commands)
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
