import asyncio
import json
import os
from datetime import datetime
from html import escape

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
    BotCommandScopeChat
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


threading.Thread(
    target=run_web,
    daemon=True
).start()


# =========================================================
# КОНФИГУРАЦИЯ
# =========================================================

TOKEN = os.environ.get("BOT_TOKEN", "")

SUPER_ADMIN = 6166697485

ADMIN_IDS = {
    6166697485,
    123456789,
    6863392923,
    1980341141
}

GROUP_ID = -1002409536359

GROUP_LINK = "https://t.me/+f_eKIP4gwcs0YTcy"

BOT_NAME = "@Staff_Grand_Bot"

ANNOUNCE_TOPIC_ID = 126387

BOT_START_TIME = datetime.now()


# =========================================================
# СПИСКИ
# =========================================================

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


# =========================================================
# BOT / DISPATCHER
# =========================================================

if not TOKEN:
    raise RuntimeError(
        "Не найден BOT_TOKEN. "
        "Добавь переменную BOT_TOKEN в Render Environment."
    )


bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(
        parse_mode="HTML"
    )
)

dp = Dispatcher()


# =========================================================
# БАЗА ДАННЫХ
# =========================================================

DATA_FILE = "data.json"


def load_data():

    if os.path.exists(DATA_FILE):

        try:

            with open(
                DATA_FILE,
                "r",
                encoding="utf-8"
            ) as f:

                return json.load(f)

        except Exception:
            pass

    return {
        "users": {},
        "applications": {},
        "admins": list(ADMIN_IDS),
        "zam_stats": {},
        "bot_token": TOKEN,
        "zam_data": {},
        "log_notify_enabled": False,
        "admin_usernames": {}
    }


def save_data():

    with open(
        DATA_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


data = load_data()


# =========================================================
# МИГРАЦИЯ
# =========================================================

defaults = {
    "users": {},
    "applications": {},
    "admins": list(ADMIN_IDS),
    "zam_stats": {},
    "bot_token": TOKEN,
    "zam_data": {},
    "log_notify_enabled": False,
    "admin_usernames": {}
}

changed = False


for key, default in defaults.items():

    if key not in data:

        data[key] = default
        changed = True


if not data.get("admins"):

    data["admins"] = list(ADMIN_IDS)
    changed = True


for nick, info in list(
    data.get("zam_data", {}).items()
):

    if not isinstance(info, dict):

        data["zam_data"][nick] = {
            "tg_user_id": None,
            "tg_username": None
        }

        changed = True

    else:

        if "tg_user_id" not in info:

            info["tg_user_id"] = None
            changed = True

        if "tg_username" not in info:

            info["tg_username"] = None
            changed = True


if changed:
    save_data()


# =========================================================
# АДМИНЫ
# =========================================================

async def init_admins():

    admin_info = data.get(
        "admin_usernames",
        {}
    )

    changed = False

    for admin_id in ADMIN_IDS:

        try:

            chat = await bot.get_chat(
                admin_id
            )

            info = {}

            if chat.username:
                info["username"] = chat.username

            if chat.full_name:
                info["full_name"] = chat.full_name

            if info:

                if (
                    admin_info.get(
                        str(admin_id)
                    ) != info
                ):

                    admin_info[
                        str(admin_id)
                    ] = info

                    changed = True

        except Exception:

            if str(admin_id) not in admin_info:

                admin_info[
                    str(admin_id)
                ] = {
                    "full_name": str(admin_id)
                }

                changed = True


    # Также обновляем всех админов,
    # которые были добавлены через бота

    for admin_id in data.get(
        "admins",
        []
    ):

        try:

            chat = await bot.get_chat(
                admin_id
            )

            info = {}

            if chat.username:
                info["username"] = chat.username

            if chat.full_name:
                info["full_name"] = chat.full_name

            if info:

                if (
                    admin_info.get(
                        str(admin_id)
                    ) != info
                ):

                    admin_info[
                        str(admin_id)
                    ] = info

                    changed = True

        except Exception:
            pass


    if changed:

        data["admin_usernames"] = admin_info
        save_data()


def get_admin_display(admin_id):

    info = data.get(
        "admin_usernames",
        {}
    ).get(
        str(admin_id)
    )

    if info:

        if info.get("username"):

            return (
                f"@{info['username']}"
            )

        if (
            info.get("full_name")
            and
            info["full_name"] != str(admin_id)
        ):

            return info["full_name"]

    return str(admin_id)


def get_admins():

    return set(
        data.get(
            "admins",
            []
        )
    )


def save_admins(admins):

    data["admins"] = list(admins)

    save_data()


def is_admin(user_id):

    return user_id in get_admins()


def is_super_admin(user_id):

    return user_id == SUPER_ADMIN


# =========================================================
# КОМАНДЫ TELEGRAM
# =========================================================

async def setup_commands():

    # -----------------------------------------------------
    # ОБЫЧНЫЕ ПОЛЬЗОВАТЕЛИ
    # -----------------------------------------------------

    public_commands = [

        BotCommand(
            command="start",
            description="🏠 Меню"
        ),

        BotCommand(
            command="help",
            description="📖 Помощь"
        )
    ]

    await bot.set_my_commands(
        public_commands,
        scope=BotCommandScopeDefault()
    )


    # -----------------------------------------------------
    # АДМИНЫ
    # -----------------------------------------------------

    admin_commands = [

        BotCommand(
            command="start",
            description="🏠 Меню"
        ),

        BotCommand(
            command="help",
            description="📖 Помощь"
        ),

        BotCommand(
            command="ping",
            description="📡 Пинг"
        ),

        BotCommand(
            command="all",
            description="📢 Объявление"
        )
    ]


    # -----------------------------------------------------
    # ВЛАДЕЛЕЦ
    # -----------------------------------------------------

    owner_commands = [

        BotCommand(
            command="start",
            description="🏠 Меню"
        ),

        BotCommand(
            command="help",
            description="📖 Помощь"
        ),

        BotCommand(
            command="ping",
            description="📡 Пинг"
        ),

        BotCommand(
            command="all",
            description="📢 Объявление"
        ),

        BotCommand(
            command="add_admin",
            description="➕ Добавить админа/зама"
        ),

        BotCommand(
            command="remove_admin",
            description="➖ Удалить админа/зама"
        ),

        BotCommand(
            command="add_zam",
            description="👤 Добавить зама"
        ),

        BotCommand(
            command="remove_zam",
            description="❌ Удалить зама"
        ),

        BotCommand(
            command="admins",
            description="👑 Список админов"
        ),

        BotCommand(
            command="zam_stats",
            description="👥 Статистика замов"
        ),

        BotCommand(
            command="withdraw",
            description="💰 Вывод"
        ),

        BotCommand(
            command="logs",
            description="📜 Журнал"
        ),

        BotCommand(
            command="clearlogs",
            description="🗑 Очистить журнал"
        ),

        BotCommand(
            command="log_on",
            description="🔔 Уведомления вкл"
        ),

        BotCommand(
            command="log_off",
            description="🔕 Уведомления выкл"
        ),

        BotCommand(
            command="set_token",
            description="🔑 Смена токена"
        ),

        BotCommand(
            command="topic_id",
            description="🆔 ID темы"
        )
    ]


    # -----------------------------------------------------
    # УСТАНАВЛИВАЕМ КОМАНДЫ ДЛЯ КАЖДОГО АДМИНА
    # -----------------------------------------------------

    for admin_id in get_admins():

        try:

            if is_super_admin(admin_id):

                await bot.set_my_commands(
                    owner_commands,
                    scope=BotCommandScopeChat(
                        chat_id=admin_id
                    )
                )

            else:

                await bot.set_my_commands(
                    admin_commands,
                    scope=BotCommandScopeChat(
                        chat_id=admin_id
                    )
                )

        except Exception as e:

            print(
                f"Не удалось установить команды "
                f"для {admin_id}: {e}"
            )


# =========================================================
# ЗАМЫ
# =========================================================

def get_zam_nicknames():

    return list(
        data.get(
            "zam_data",
            {}
        ).keys()
    )


def get_zam_user_id(game_nick):

    info = data.get(
        "zam_data",
        {}
    ).get(game_nick)

    if not info:
        return None

    return info.get(
        "tg_user_id"
    )


def add_zam_nick(
    game_nick,
    tg_user_id=None,
    tg_username=None
):

    game_nick = game_nick.strip()

    if not game_nick:

        return False, "Пустой ник."

    if game_nick in data["zam_data"]:

        return False, "Такой зам уже существует."

    data["zam_data"][game_nick] = {

        "tg_user_id": tg_user_id,

        "tg_username": tg_username
    }

    if game_nick not in data["zam_stats"]:

        data["zam_stats"][game_nick] = {

            "count": 0,

            "earned": 0,

            "history": []
        }

    save_data()

    return True, "Зам добавлен."


def remove_zam_nick(game_nick):

    if game_nick not in data["zam_data"]:

        return False

    del data["zam_data"][game_nick]

    if game_nick in data["zam_stats"]:

        del data["zam_stats"][game_nick]

    save_data()

    return True


def count_zam_answers(game_nick):

    count = 0

    for user in data.get(
        "users",
        {}
    ).values():

        if user.get(
            "inviter"
        ) == game_nick:

            count += 1

    return count


def get_all_zam_counts():

    result = []

    for nick in get_zam_nicknames():

        count = count_zam_answers(
            nick
        )

        result.append(
            (
                nick,
                count
            )
        )

    result.sort(
        key=lambda x: (
            -x[1],
            x[0].lower()
        )
    )

    return result


# =========================================================
# ЛОГИ
# =========================================================

LOG_FILE = "bot_activity.log"


async def log_action(
    user_id,
    action,
    details=""
):

    try:

        chat = await bot.get_chat(
            user_id
        )

        username = (

            f"@{chat.username}"

            if chat.username

            else chat.full_name
        )

    except Exception:

        username = str(user_id)


    ts = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


    with open(
        LOG_FILE,
        "a",
        encoding="utf-8"
    ) as f:

        f.write(
            f"[{ts}] "
            f"{username} -> "
            f"{action} "
            f"{details}\n"
        )


    if data.get(
        "log_notify_enabled"
    ):

        try:

            await bot.send_message(

                SUPER_ADMIN,

                f"👤 <b>{escape(username)}</b> "
                f"-> {escape(action)} "
                f"{escape(details)}\n"
                f"🕐 {ts}"
            )

        except Exception:
            pass


# =========================================================
# КНОПКИ
# =========================================================

def main_keyboard(
    has_survey=False
):

    b = ReplyKeyboardBuilder()

    b.row(
        KeyboardButton(
            text="📝 Заполнить анкету"
        )
    )

    if has_survey:

        b.row(
            KeyboardButton(
                text="🔄 Перезаполнить анкету"
            )
        )

    b.row(
        KeyboardButton(
            text="👤 Мой профиль"
        )
    )

    return b.as_markup(
        resize_keyboard=True
    )


def admin_keyboard(
    user_id,
    has_survey=False
):

    b = ReplyKeyboardBuilder()

    b.row(

        KeyboardButton(
            text="📋 Управление заявками"
        ),

        KeyboardButton(
            text="⏳ Активные заявки"
        )
    )

    b.row(

        KeyboardButton(
            text="👥 Список участников"
        ),

        KeyboardButton(
            text="🟢 Статус бота"
        )
    )

    if has_survey:

        b.row(
            KeyboardButton(
                text="🔄 Перезаполнить анкету"
            )
        )

    if is_super_admin(user_id):

        b.row(

            KeyboardButton(
                text="👑 Администрирование"
            ),

            KeyboardButton(
                text="📜 Журнал действий"
            )
        )

        b.row(
            KeyboardButton(
                text="👥 Замы"
            )
        )

    return b.as_markup(
        resize_keyboard=True
    )


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
            f"Вступите по ссылке:\n"
            f"{link.invite_link}\n\n"
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


async def set_user_nickname(
    user_id,
    nickname
):

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
async def start_command(
    message: Message
):

    await log_action(

        message.from_user.id,

        "start",

        "запустил бота"
    )

    await show_main_menu(
        message
    )


async def show_main_menu(
    message: Message
):

    user_id = message.from_user.id

    has_survey = (
        str(user_id)
        in data["users"]
    )

    if is_admin(user_id):

        await message.answer(

            f"🛡️ <b>Панель управления</b>\n"
            f"Добро пожаловать в "
            f"<b>{BOT_NAME}</b>.",

            reply_markup=admin_keyboard(

                user_id,

                has_survey
            )
        )

    else:

        await message.answer(

            f"👋 <b>Добро пожаловать "
            f"в {BOT_NAME}!</b>\n"
            f"Заполните анкету "
            f"для вступления в семью.",

            reply_markup=main_keyboard(
                has_survey
            )
        )


# =========================================================
# /КТО
# =========================================================

@dp.message(Command("кто"))
async def who_command(
    message: Message
):

    if not is_admin(
        message.from_user.id
    ):

        await message.answer(
            "❌ Нет прав!"
        )

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


    uid = (
        message.reply_to_message
        .from_user.id
    )

    u = data["users"].get(
        str(uid)
    )


    if not u:

        await message.answer(
            "❌ У этого пользователя нет анкеты."
        )

        return


    await message.answer(

        f"📋 <b>Анкета:</b>\n"

        f"Nickname: "
        f"{escape(u.get('nickname', '—'))}\n"

        f"Тег: "
        f"{escape(u.get('tag', '—'))}\n"

        f"Ранг: "
        f"{escape(u.get('rank_fam', '—'))}\n"

        f"Орг: "
        f"{escape(u.get('organization', '—'))}\n"

        f"Ранг в орг: "
        f"{escape(u.get('rank_org', '—'))}\n"

        f"Пригласитель: "
        f"{escape(u.get('inviter', '—'))}"
    )


# =========================================================
# ПЕРЕЗАПОЛНЕНИЕ АНКЕТЫ
# =========================================================

@dp.message(
    F.text == "🔄 Перезаполнить анкету"
)
async def reset_survey(
    message: Message
):

    uid = str(
        message.from_user.id
    )


    if uid not in data["users"]:

        await message.answer(
            "❌ У вас нет анкеты."
        )

        return


    # Удаляем старую анкету пользователя
    data["users"].pop(
        uid,
        None
    )


    # Также удаляем старые заявки этого пользователя,
    # чтобы новая анкета была новой заявкой

    for app_id in list(
        data["applications"].keys()
    ):

        app = data["applications"][app_id]

        if str(
            app.get("user_id")
        ) == uid:

            # Старые принятые/отклонённые заявки
            # оставляем в истории.
            #
            # Но pending удаляем,
            # чтобы не было двух активных заявок.

            if app.get("status") == "pending":

                del data["applications"][app_id]


    save_data()


    await log_action(

        int(uid),

        "сброс анкеты"
    )


    await message.answer(

        "✅ <b>Анкета сброшена!</b>\n\n"
        "Теперь заполните её заново."
    )


    await start_survey(
        message
    )


# =========================================================
# АНКЕТА
# =========================================================

user_surveys = {}


async def start_survey(
    message: Message
):

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


@dp.message(
    lambda m: (
        m.from_user.id
        in user_surveys
    )
)
async def survey_handler(
    message: Message
):

    uid = message.from_user.id

    s = user_surveys[uid]

    step = s["step"]


    if step == 0:

        s["answers"]["nickname"] = (
            message.text
        )


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

        s["answers"]["rank_org"] = (
            message.text
        )


        s["step"] = 4


        zams = get_zam_nicknames()


        if not zams:

            await message.answer(

                "⚠️ Сейчас замов нет.\n"
                "Обратитесь к администрации."
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

            "👤 <b>Кто вас пригласил?</b>\n\n"
            "Выберите своего зама:",

            reply_markup=kb
        )


# =========================================================
# ВЫБОР РАНГА
# =========================================================

@dp.callback_query(
    F.data.startswith("rank_")
)
async def rank_selected(
    cb: CallbackQuery
):

    uid = cb.from_user.id


    if uid not in user_surveys:

        await cb.answer("❌")

        return


    rank = cb.data[5:]


    user_surveys[uid]["answers"][
        "rank_fam"
    ] = rank


    user_surveys[uid]["step"] = 2


    await cb.answer(
        f"✅ {rank}"
    )


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
# ВЫБОР ОРГАНИЗАЦИИ
# =========================================================

@dp.callback_query(
    F.data.startswith("org_")
)
async def org_selected(
    cb: CallbackQuery
):

    uid = cb.from_user.id


    if uid not in user_surveys:

        await cb.answer("❌")

        return


    org = cb.data[4:]


    user_surveys[uid]["answers"][
        "organization"
    ] = org


    user_surveys[uid]["step"] = 3


    await cb.answer(
        f"✅ {org}"
    )


    await cb.message.answer(

        "📌 Ваш ранг в организации?"
    )


# =========================================================
# ВЫБОР ЗАМА
# =========================================================

@dp.callback_query(
    F.data.startswith("zam_")
)
async def zam_selected(
    cb: CallbackQuery
):

    uid = cb.from_user.id


    if uid not in user_surveys:

        await cb.answer("❌")

        return


    zam = cb.data[4:]


    if zam not in data["zam_data"]:

        await cb.answer(

            "❌ Этот зам больше не существует.",

            show_alert=True
        )

        return


    user_surveys[uid]["answers"][
        "inviter"
    ] = zam


    await cb.answer(
        f"✅ {zam}"
    )


    await finish_survey(

        cb.message,

        uid
    )


# =========================================================
# ЗАВЕРШЕНИЕ АНКЕТЫ
# =========================================================

async def finish_survey(
    message,
    uid
):

    s = user_surveys.pop(
        uid,
        None
    )


    if not s:
        return


    a = s["answers"]


    user_data = {

        "nickname": a.get(
            "nickname",
            "—"
        ),

        "tag": a.get(
            "tag",
            "—"
        ),

        "rank_fam": a.get(
            "rank_fam",
            "—"
        ),

        "organization": a.get(
            "organization",
            "—"
        ),

        "rank_org": a.get(
            "rank_org",
            "—"
        ),

        "inviter": a.get(
            "inviter",
            "—"
        )
    }


    # Сохраняем новую анкету
    data["users"][str(uid)] = user_data


    # Если пользователь перезаполняет анкету,
    # создаём новую заявку
    app_id = (

        f"app_{uid}_"
        f"{int(datetime.now().timestamp())}"
    )


    data["applications"][app_id] = {

        "user_id": uid,

        "data": user_data,

        "status": "pending",

        "created": (
            datetime.now().isoformat()
        ),

        "history": []
    }


    save_data()


    await message.answer(

        "✅ <b>Анкета заполнена!</b>\n\n"
        "📩 Она отправлена администрации "
        "на рассмотрение."
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

        f"📩 <b>Новая заявка!</b>\n\n"

        f"Nickname: "
        f"{escape(user_data['nickname'])}\n"

        f"Тег: "
        f"{escape(user_data['tag'])}\n"

        f"Ранг: "
        f"{escape(user_data['rank_fam'])}\n"

        f"Орг: "
        f"{escape(user_data['organization'])}\n"

        f"Ранг в орг: "
        f"{escape(user_data['rank_org'])}\n"

        f"Пригласитель: "
        f"{escape(user_data['inviter'])}"
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
# ЗАПОЛНИТЬ АНКЕТУ
# =========================================================

@dp.message(
    F.text == "📝 Заполнить анкету"
)
async def survey_button(
    message: Message
):

    uid = message.from_user.id


    if str(uid) in data["users"]:

        await message.answer(

            "ℹ️ Вы уже заполнили анкету.\n\n"
            "Чтобы изменить её, нажмите:\n"
            "🔄 <b>Перезаполнить анкету</b>"
        )

        return


    await start_survey(
        message
    )


# =========================================================
# ПРИНЯТЬ ЗАЯВКУ
# =========================================================

@dp.callback_query(
    F.data.startswith("accept:")
)
async def accept_app(
    cb: CallbackQuery
):

    if not is_admin(
        cb.from_user.id
    ):

        await cb.answer(
            "❌ Нет прав!"
        )

        return


    app_id = cb.data.split(
        ":",
        1
    )[1]


    app = data["applications"].get(
        app_id
    )


    if not app:

        await cb.answer(
            "❌ Заявка не найдена."
        )

        return


    app["status"] = "accepted"


    app.setdefault(
        "history",
        []
    ).append({

        "action": "accepted",

        "admin_id": cb.from_user.id,

        "time": datetime.now().isoformat()
    })


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


    await cb.answer(
        "✅ Принято"
    )


    await cb.message.edit_reply_markup(
        reply_markup=None
    )


# =========================================================
# ОТКЛОНИТЬ ЗАЯВКУ
# =========================================================

@dp.callback_query(
    F.data.startswith("reject:")
)
async def reject_app(
    cb: CallbackQuery
):

    if not is_admin(
        cb.from_user.id
    ):

        await cb.answer(
            "❌ Нет прав!"
        )

        return


    app_id = cb.data.split(
        ":",
        1
    )[1]


    app = data["applications"].get(
        app_id
    )


    if not app:

        await cb.answer(
            "❌ Заявка не найдена."
        )

        return


    app["status"] = "rejected"


    app.setdefault(
        "history",
        []
    ).append({

        "action": "rejected",

        "admin_id": cb.from_user.id,

        "time": datetime.now().isoformat()
    })


    save_data()


    await remove_user_from_group(
        app["user_id"]
    )


    await cb.answer(
        "❌ Отклонено"
    )


    await cb.message.edit_reply_markup(
        reply_markup=None
    )


# =========================================================
# ВСЕ ЗАЯВКИ
# =========================================================

@dp.message(
    F.text == "📋 Управление заявками"
)
async def all_apps(
    message: Message
):

    if not is_admin(
        message.from_user.id
    ):

        await message.answer("❌")

        return


    apps = data["applications"]


    if not apps:

        await message.answer(
            "📭 Заявок нет."
        )

        return


    idx = 1


    for app_id, app in apps.items():

        u = app["data"]

        status = app["status"]


        e = (

            "⏳"

            if status == "pending"

            else (

                "✅"

                if status == "accepted"

                else "❌"
            )
        )


        text = (

            f"{e} <b>Заявка #{idx}</b>\n"

            f"Nickname: "
            f"{escape(u.get('nickname', '—'))}\n"

            f"Тег: "
            f"{escape(u.get('tag', '—'))}\n"

            f"Ранг: "
            f"{escape(u.get('rank_fam', '—'))}\n"

            f"Орг: "
            f"{escape(u.get('organization', '—'))}\n"

            f"Ранг в орг: "
            f"{escape(u.get('rank_org', '—'))}\n"

            f"Пригласил: "
            f"{escape(u.get('inviter', '—'))}"
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

            text,

            reply_markup=kb
        )


        idx += 1


# =========================================================
# АКТИВНЫЕ ЗАЯВКИ
# =========================================================

@dp.message(
    F.text == "⏳ Активные заявки"
)
async def active_apps(
    message: Message
):

    if not is_admin(
        message.from_user.id
    ):

        await message.answer("❌")

        return


    pend = {

        k: v

        for k, v
        in data["applications"].items()

        if v["status"] == "pending"
    }


    if not pend:

        await message.answer(
            "📭 Нет активных заявок."
        )

        return


    idx = 1


    for app_id, app in pend.items():

        u = app["data"]


        text = (

            f"⏳ <b>Заявка #{idx}</b>\n"

            f"Nickname: "
            f"{escape(u.get('nickname', '—'))}\n"

            f"Тег: "
            f"{escape(u.get('tag', '—'))}\n"

            f"Ранг: "
            f"{escape(u.get('rank_fam', '—'))}\n"

            f"Орг: "
            f"{escape(u.get('organization', '—'))}\n"

            f"Ранг в орг: "
            f"{escape(u.get('rank_org', '—'))}\n"

            f"Пригласил: "
            f"{escape(u.get('inviter', '—'))}"
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

            text,

            reply_markup=kb
        )


        idx += 1


# =========================================================
# СПИСОК УЧАСТНИКОВ
# =========================================================

@dp.message(
    F.text == "👥 Список участников"
)
async def list_users(
    message: Message
):

    if not is_admin(
        message.from_user.id
    ):

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


async def send_users_page(
    message,
    users,
    page
):

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


    text = (
        "👥 <b>Список участников</b>\n\n"
    )


    for i in range(
        start,
        end
    ):

        uid, u = users[i]


        text += (

            f"<b>{i + 1}.</b> "

            f"{escape(u.get('nickname', '—'))} "

            f"— {escape(u.get('tag', uid))}\n"
        )


        text += (

            f"   Ранг: "
            f"{escape(u.get('rank_fam', '—'))} | "

            f"Орг: "
            f"{escape(u.get('organization', '—'))}\n"

            f"   Пригласил: "
            f"{escape(u.get('inviter', '—'))}\n\n"
        )


    text += (
        f"Стр. {page + 1} из {pages}"
    )


    rows = []


    if page > 0:

        rows.append([

            InlineKeyboardButton(

                text="⬅️",

                callback_data=f"up_{page - 1}"
            )
        ])


    if page < pages - 1:

        rows.append([

            InlineKeyboardButton(

                text="➡️",

                callback_data=f"up_{page + 1}"
            )
        ])


    await message.answer(

        text,

        reply_markup=(

            InlineKeyboardMarkup(
                inline_keyboard=rows
            )

            if rows

            else None
        )
    )


@dp.callback_query(
    F.data.startswith("up_")
)
async def up_cb(
    cb: CallbackQuery
):

    if not is_admin(
        cb.from_user.id
    ):

        await cb.answer(
            "❌ Нет прав!"
        )

        return


    users = list(
        data["users"].items()
    )


    await send_users_page(

        cb.message,

        users,

        int(
            cb.data.split("_")[1]
        )
    )


    await cb.answer()


# =========================================================
# СТАТУС БОТА
# =========================================================

@dp.message(
    F.text == "🟢 Статус бота"
)
async def status_btn(
    message: Message
):

    if not is_admin(
        message.from_user.id
    ):

        await message.answer("❌")

        return


    total = len(
        data["users"]
    )


    pend = sum(

        1

        for a
        in data["applications"].values()

        if a["status"] == "pending"
    )


    rej = sum(

        1

        for a
        in data["applications"].values()

        if a["status"] == "rejected"
    )


    acc = sum(

        1

        for a
        in data["applications"].values()

        if a["status"] == "accepted"
    )


    admins = "\n".join(

        escape(
            get_admin_display(i)
        )

        for i in get_admins()
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

@dp.message(
    F.text == "👤 Мой профиль"
)
async def my_profile(
    message: Message
):

    uid = str(
        message.from_user.id
    )


    if uid in data["users"]:

        u = data["users"][uid]


        await message.answer(

            f"👤 <b>Профиль:</b>\n"

            f"Nickname: "
            f"{escape(u.get('nickname', '—'))}\n"

            f"Тег: "
            f"{escape(u.get('tag', '—'))}\n"

            f"Ранг: "
            f"{escape(u.get('rank_fam', '—'))}\n"

            f"Орг: "
            f"{escape(u.get('organization', '—'))}\n"

            f"Ранг в орг: "
            f"{escape(u.get('rank_org', '—'))}\n"

            f"Пригласитель: "
            f"{escape(u.get('inviter', '—'))}"
        )

    else:

        await message.answer(

            "ℹ️ Вы ещё не заполнили анкету."
        )


# =========================================================
# АДМИНИСТРИРОВАНИЕ
# =========================================================

@dp.message(
    F.text == "👑 Администрирование"
)
async def manage(
    message: Message
):

    if not is_super_admin(
        message.from_user.id
    ):

        await message.answer(
            "❌ Только владелец!"
        )

        return


    text = (

        "👑 <b>Администрирование</b>\n\n"

        "📋 <b>Админы:</b>\n"
    )


    for i in get_admins():

        text += (

            f"• "
            f"{escape(get_admin_display(i))}\n"
        )


    text += (

        "\n<b>Команды:</b>\n"

        "/add_admin adm @username — "
        "добавить админа\n"

        "/remove_admin adm @username — "
        "удалить админа\n"

        "/add_admin zam @username Nik: игровой_ник — "
        "добавить зама с Telegram\n"

        "/remove_admin zam @username — "
        "удалить зама\n"

        "/add_zam игровой_ник — "
        "добавить зама без Telegram\n"

        "/remove_zam игровой_ник — "
        "удалить зама"
    )


    await message.answer(
        text
    )


# =========================================================
# /ADD_ADMIN
# =========================================================

@dp.message(
    Command("add_admin")
)
async def add_admin(
    message: Message
):

    if not is_super_admin(
        message.from_user.id
    ):

        await message.answer(
            "❌ Только владелец!"
        )

        return


    args = message.text.split(
        maxsplit=1
    )


    if len(args) < 2:

        await message.answer(

            "❌ Формат:\n"

            "/add_admin adm @username\n"

            "/add_admin zam @username Nik: игровой_ник"
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

                f"❌ @{escape(username)} "
                f"не найден."
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


        # Обновляем меню команд нового админа

        try:

            await bot.set_my_commands(

                [

                    BotCommand(
                        command="start",
                        description="🏠 Меню"
                    ),

                    BotCommand(
                        command="help",
                        description="📖 Помощь"
                    ),

                    BotCommand(
                        command="ping",
                        description="📡 Пинг"
                    ),

                    BotCommand(
                        command="all",
                        description="📢 Объявление"
                    )
                ],

                scope=BotCommandScopeChat(
                    chat_id=chat.id
                )
            )

        except Exception:
            pass


        await message.answer(

            f"✅ Админ "
            f"@{escape(username)} "
            f"добавлен."
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

                "/add_admin zam @username Nik: игровой_ник"
            )

            return


        game_nick = " ".join(
            parts[3:]
        ).strip()


        try:

            chat = await bot.get_chat(
                username
            )

        except Exception:

            await message.answer(

                f"❌ @{escape(username)} "
                f"не найден."
            )

            return


        if game_nick in data["zam_data"]:

            await message.answer(

                "❌ Такой игровой ник "
                "уже является замом."
            )

            return


        for nick, info in data[
            "zam_data"
        ].items():

            if info.get(
                "tg_user_id"
            ) == chat.id:

                await message.answer(

                    f"❌ Уже зам "
                    f"({escape(nick)})."
                )

                return


        ok, result = add_zam_nick(

            game_nick,

            chat.id,

            username
        )


        if not ok:

            await message.answer(
                f"❌ {result}"
            )

            return


        await message.answer(

            f"✅ Зам "
            f"<b>{escape(game_nick)}</b> "
            f"(@{escape(username)}) добавлен."
        )


        try:

            await bot.send_message(

                chat.id,

                f"👑 Вы назначены замом!\n"

                f"Ваш ник: "
                f"{escape(game_nick)}"
            )

        except Exception:

            pass


        return


    await message.answer(
        "❌ Тип: adm или zam"
    )


# =========================================================
# /ADD_ZAM
# =========================================================

@dp.message(
    Command("add_zam")
)
async def add_zam_command(
    message: Message
):

    if not is_super_admin(
        message.from_user.id
    ):

        await message.answer(
            "❌ Только владелец!"
        )

        return


    args = message.text.split(
        maxsplit=1
    )


    if len(args) < 2:

        await message.answer(

            "❌ Формат:\n"
            "/add_zam игровой_ник"
        )

        return


    game_nick = args[1].strip()


    ok, result = add_zam_nick(
        game_nick
    )


    if not ok:

        await message.answer(
            f"❌ {result}"
        )

        return


    await log_action(

        message.from_user.id,

        "добавил зама",

        game_nick
    )


    await message.answer(

        f"✅ Зам "
        f"<b>{escape(game_nick)}</b> "
        f"добавлен!\n\n"

        f"Теперь он сразу появится "
        f"в вопросе:\n"

        f"👤 Кто вас пригласил?"
    )


# =========================================================
# /REMOVE_ZAM
# =========================================================

@dp.message(
    Command("remove_zam")
)
async def remove_zam_command(
    message: Message
):

    if not is_super_admin(
        message.from_user.id
    ):

        await message.answer(
            "❌ Только владелец!"
        )

        return


    args = message.text.split(
        maxsplit=1
    )


    if len(args) < 2:

        await message.answer(

            "❌ Формат:\n"
            "/remove_zam игровой_ник"
        )

        return


    game_nick = args[1].strip()


    if not remove_zam_nick(
        game_nick
    ):

        await message.answer(

            "❌ Такой зам не найден."
        )

        return


    await log_action(

        message.from_user.id,

        "удалил зама",

        game_nick
    )


    await message.answer(

        f"✅ Зам "
        f"<b>{escape(game_nick)}</b> "
        f"удалён."
    )


# =========================================================
# /REMOVE_ADMIN
# =========================================================

@dp.message(
    Command("remove_admin")
)
async def remove_admin(
    message: Message
):

    if not is_super_admin(
        message.from_user.id
    ):

        await message.answer(
            "❌ Только владелец!"
        )

        return


    args = message.text.split(
        maxsplit=1
    )


    if len(args) < 2:

        await message.answer(

            "❌ Формат:\n"

            "/remove_admin adm @username\n"

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

                f"❌ @{escape(username)} "
                f"не найден."
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


        data["admin_usernames"].pop(
            str(chat.id),
            None
        )

        save_data()


        # Возвращаем обычное меню команд

        try:

            await bot.set_my_commands(

                [

                    BotCommand(
                        command="start",
                        description="🏠 Меню"
                    ),

                    BotCommand(
                        command="help",
                        description="📖 Помощь"
                    )
                ],

                scope=BotCommandScopeChat(
                    chat_id=chat.id
                )
            )

        except Exception:
            pass


        await message.answer(

            f"✅ Админ "
            f"@{escape(username)} "
            f"удалён."
        )

        return


    if type_ == "zam":

        found_nick = None


        for nick, info in data[
            "zam_data"
        ].items():

            tg_username = info.get(
                "tg_username"
            )


            if (

                tg_username

                and

                tg_username.lower()
                == username.lower()
            ):

                found_nick = nick

                break


        if not found_nick:

            await message.answer(

                f"❌ Зам "
                f"@{escape(username)} "
                f"не найден."
            )

            return


        remove_zam_nick(
            found_nick
        )


        await message.answer(

            f"✅ Зам "
            f"<b>{escape(found_nick)}</b> "
            f"удалён."
        )

        return


    await message.answer(
        "❌ Тип: adm или zam"
    )


# =========================================================
# КНОПКА "ЗАМЫ"
# =========================================================

@dp.message(
    F.text == "👥 Замы"
)
async def zams_button(
    message: Message
):

    if not is_super_admin(
        message.from_user.id
    ):

        await message.answer(

            "❌ Только владелец!"
        )

        return


    zams = get_all_zam_counts()


    if not zams:

        await message.answer(

            "👥 <b>ЗАМЫ</b>\n\n"

            "📭 Замов пока нет.\n\n"

            "Добавить можно командой:\n"

            "/add_zam игровой_ник"
        )

        return


    text = (
        "👥 <b>ЗАМЫ</b>\n\n"
    )


    for nick, count in zams:

        word = (

            "анкета"

            if count == 1

            else "анкет"
        )


        text += (

            f"👤 <b>{escape(nick)}</b> "
            f"— {count} {word}\n"
        )


    text += (

        "\n📊 Количество считается "
        "по ответам на вопрос "
        "«Кто вас пригласил?»."
    )


    await message.answer(
        text
    )


# =========================================================
# /ZAM_STATS
# =========================================================

@dp.message(
    Command("zam_stats")
)
async def zam_stats_cmd(
    message: Message
):

    if not is_super_admin(
        message.from_user.id
    ):

        await message.answer(
            "❌ Только владелец!"
        )

        return


    zams = get_all_zam_counts()


    if not zams:

        await message.answer(
            "📭 Замов нет."
        )

        return


    text = (
        "🏦 <b>СТАТИСТИКА ЗАМОВ</b>\n\n"
    )


    for nick, count in zams:

        text += (

            f"👤 <b>{escape(nick)}</b> "
            f"— {count} анкет\n"
        )


    await message.answer(
        text
    )


# =========================================================
# /WITHDRAW
# =========================================================

@dp.message(
    Command("withdraw")
)
async def withdraw(
    message: Message
):

    if not is_super_admin(
        message.from_user.id
    ):

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

        amount = int(
            args[2]
        )

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


    for nick, info in data[
        "zam_data"
    ].items():

        tg_username = info.get(
            "tg_username"
        )


        if (

            tg_username

            and

            tg_username.lower()
            == username.lower()
        ):

            gn = nick

            break


    if not gn:

        await message.answer(
            "❌ Зам не найден."
        )

        return


    count = count_zam_answers(
        gn
    )


    need = amount // 100


    if count < need:

        await message.answer(

            f"❌ Мало приглашённых "
            f"({count}/{need})."
        )

        return


    uid = get_zam_user_id(
        gn
    )


    if uid:

        try:

            await bot.send_message(

                uid,

                f"💰 Вам списано "
                f"{amount}k."
            )

        except Exception:

            pass


    await message.answer(

        f"✅ Снято {amount}k с "
        f"{escape(gn)}.\n"

        f"Осталось приглашённых: "
        f"{count - need}"
    )


# =========================================================
# ЛОГИ
# =========================================================

@dp.message(
    Command("logs")
)
async def logs_cmd(
    message: Message
):

    if not is_super_admin(
        message.from_user.id
    ):

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


async def send_logs_page(
    message,
    lines,
    page
):

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


    text = (

        f"📋 <b>Журнал "
        f"(стр. {page + 1}/{pages})</b>\n\n"

        + "".join(
            lines[start:end]
        )
    )


    if len(text) > 4000:

        text = (

            text[:3900]

            + "\n... (обрезано)"
        )


    rows = []


    if page > 0:

        rows.append([

            InlineKeyboardButton(

                text="⬅️",

                callback_data=f"lp_{page - 1}"
            )
        ])


    if page < pages - 1:

        rows.append([

            InlineKeyboardButton(

                text="➡️",

                callback_data=f"lp_{page + 1}"
            )
        ])


    await message.answer(

        text,

        reply_markup=(

            InlineKeyboardMarkup(
                inline_keyboard=rows
            )

            if rows

            else None
        )
    )


@dp.callback_query(
    F.data.startswith("lp_")
)
async def lp_cb(
    cb: CallbackQuery
):

    if not is_super_admin(
        cb.from_user.id
    ):

        await cb.answer(
            "❌ Нет прав!"
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


    await send_logs_page(

        cb.message,

        lines,

        int(
            cb.data.split("_")[1]
        )
    )


    await cb.answer()


@dp.message(
    F.text == "📜 Журнал действий"
)
async def logs_btn(
    message: Message
):

    await logs_cmd(
        message
    )


@dp.message(
    Command("clearlogs")
)
async def clear_logs(
    message: Message
):

    if not is_super_admin(
        message.from_user.id
    ):

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

@dp.message(
    Command("log_on")
)
async def log_on(
    message: Message
):

    if not is_super_admin(
        message.from_user.id
    ):

        await message.answer(
            "❌ Только владелец!"
        )

        return


    data["log_notify_enabled"] = True

    save_data()


    await message.answer(
        "✅ Уведомления включены."
    )


@dp.message(
    Command("log_off")
)
async def log_off(
    message: Message
):

    if not is_super_admin(
        message.from_user.id
    ):

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
# ПИНГ
# =========================================================

@dp.message(
    Command("ping")
)
async def ping(
    message: Message
):

    if not is_admin(
        message.from_user.id
    ):

        await message.answer(
            "❌ Только админы!"
        )

        return


    start = datetime.now()


    m = await message.answer(
        "🏓 ..."
    )


    d = (

        datetime.now() - start
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

@dp.message(
    Command("help")
)
async def help_cmd(
    message: Message
):

    user_id = message.from_user.id


    # -----------------------------------------------------
    # ОБЫЧНЫЙ ИГРОК
    # -----------------------------------------------------

    if not is_admin(user_id):

        text = (

            "📋 <b>Команды:</b>\n\n"

            "/start — меню\n"

            "/help — помощь"
        )


        await message.answer(
            text
        )

        return


    # -----------------------------------------------------
    # ОБЫЧНЫЙ АДМИН
    # -----------------------------------------------------

    if not is_super_admin(user_id):

        text = (

            "📋 <b>Команды администратора:</b>\n\n"

            "/start — меню\n"

            "/help — помощь\n"

            "/ping — пинг\n"

            "/all — объявление"
        )


        await message.answer(
            text
        )

        return


    # -----------------------------------------------------
    # ВЛАДЕЛЕЦ
    # -----------------------------------------------------

    text = (

        "📋 <b>Команды владельца:</b>\n\n"

        "/start — меню\n"

        "/help — помощь\n"

        "/ping — пинг\n"

        "/all — объявление\n\n"

        "👑 <b>Владелец:</b>\n"

        "/add_admin — добавить админа/зама\n"

        "/remove_admin — удалить админа/зама\n"

        "/add_zam — добавить зама\n"

        "/remove_zam — удалить зама\n"

        "/admins — список админов\n\n"

        "📊 <b>Замы:</b>\n"

        "/zam_stats — статистика замов\n"

        "/withdraw — вывод\n\n"

        "📜 <b>Логи:</b>\n"

        "/logs — журнал\n"

        "/clearlogs — очистить\n"

        "/log_on — уведомления вкл\n"

        "/log_off — уведомления выкл\n\n"

        "/set_token — смена токена\n"

        "/topic_id — ID темы"
    )


    await message.answer(
        text
    )


# =========================================================
# ЗАЩИТА ТЕМЫ НОВОСТИ
# =========================================================

@dp.message(
    F.chat.id == GROUP_ID
)
async def protect_topic(
    message: Message
):

    if (

        message.message_thread_id
        == ANNOUNCE_TOPIC_ID
    ):

        if not is_admin(
            message.from_user.id
        ):

            try:

                await message.delete()


                await bot.send_message(

                    GROUP_ID,

                    f"❌ "
                    f"{escape(message.from_user.full_name)}, "
                    f"только админы могут писать здесь!",

                    reply_to_message_id=message.message_id
                )

            except Exception:
                pass


# =========================================================
# /ALL
# =========================================================

@dp.message(
    Command("all")
)
async def all_cmd(
    message: Message
):

    if not is_admin(
        message.from_user.id
    ):

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

            f"{escape(args[1])}\n\n"

            f"@all",

            message_thread_id=ANNOUNCE_TOPIC_ID
        )


        await message.answer(
            "✅ Отправлено."
        )

    except Exception as e:

        await message.answer(

            f"❌ {escape(str(e))}"
        )


# =========================================================
# /TOPIC_ID
# =========================================================

@dp.message(
    Command("topic_id")
)
async def topic_id(
    message: Message
):

    # Теперь ID темы тоже только для админов

    if not is_admin(
        message.from_user.id
    ):

        await message.answer(
            "❌ Только админы!"
        )

        return


    if (

        message.chat.id == GROUP_ID

        and message.message_thread_id
    ):

        await message.answer(

            f"🆔 ID темы: "
            f"{message.message_thread_id}"
        )

    else:

        await message.answer(
            "❌ Используйте команду внутри темы."
        )


# =========================================================
# /ADMINS
# =========================================================

@dp.message(
    Command("admins")
)
async def admins_cmd(
    message: Message
):

    if not is_super_admin(
        message.from_user.id
    ):

        await message.answer(
            "❌ Только владелец!"
        )

        return


    text = (
        "👑 <b>Админы</b>\n\n"
    )


    for i in get_admins():

        text += (

            f"• "
            f"{escape(get_admin_display(i))}\n"
        )


    await message.answer(
        text
    )


# =========================================================
# /SET_TOKEN
# =========================================================

@dp.message(
    Command("set_token")
)
async def set_token(
    message: Message
):

    if not is_super_admin(
        message.from_user.id
    ):

        await message.answer(
            "❌ Только владелец!"
        )

        return


    args = message.text.split(
        maxsplit=1
    )


    if len(args) < 2:

        await message.answer(
            "❌ /set_token <токен>"
        )

        return


    new_token = args[1].strip()


    if ":" not in new_token:

        await message.answer(

            "❌ Похоже, это не Telegram Bot Token."
        )

        return


    data["bot_token"] = new_token

    save_data()


    await message.answer(

        "✅ Новый токен сохранён.\n"

        "Перезапускаю бота..."
    )


    os._exit(0)


# =========================================================
# ЗАПУСК
# =========================================================

async def main():

    print(
        "🤖 Бот запускается..."
    )


    await init_admins()


    # =====================================================
    # ГЛАВНОЕ ИЗМЕНЕНИЕ:
    # Устанавливаем команды по правам пользователя
    # =====================================================

    await setup_commands()


    # Удаляем webhook перед polling

    await bot.delete_webhook(
        drop_pending_updates=True
    )


    print(
        "🤖 Бот запущен!"
    )


    await dp.start_polling(
        bot
    )


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print(
            "🛑 Бот остановлен."
        )
