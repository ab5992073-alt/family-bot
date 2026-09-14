import asyncio
import json
import os
import threading
from datetime import datetime
from html import escape

from flask import Flask

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


# =========================================================
# WEB SERVER FOR RENDER
# =========================================================

flask_app = Flask(__name__)


@flask_app.route("/")
def health():
    return "Bot is running!", 200


def run_web():
    port = int(os.environ.get("PORT", 8000))
    flask_app.run(
        host="0.0.0.0",
        port=port,
    )


threading.Thread(
    target=run_web,
    daemon=True,
).start()


# =========================================================
# CONFIG
# =========================================================

TOKEN = os.environ.get(
    "BOT_TOKEN",
    "",
).strip()

if not TOKEN:
    raise RuntimeError(
        "Не найден BOT_TOKEN. "
        "Добавь BOT_TOKEN в Render Environment."
    )


# ТВОЙ ID ВЛАДЕЛЬЦА
SUPER_ADMIN = 6166697485


# Старые админы сохраняются.
ADMIN_IDS = {
    SUPER_ADMIN,
    123456789,
    6863392923,
    1980341141,
}


GROUP_ID = -1002409536359

GROUP_LINK = (
    "https://t.me/+f_eKIP4gwcs0YTcy"
)

BOT_NAME = "@Staff_Grand_Bot"

ANNOUNCE_TOPIC_ID = 126387

BOT_START_TIME = datetime.now()


# =========================================================
# RANKS
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
    "ВОР",
]


# =========================================================
# ORGANIZATIONS
# =========================================================

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


# =========================================================
# BOT
# =========================================================

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(
        parse_mode="HTML"
    ),
)

dp = Dispatcher()


# =========================================================
# FILES
# =========================================================

DATA_FILE = "data.json"
LOG_FILE = "bot_activity.log"


# =========================================================
# DATA
# =========================================================

def default_data():
    return {
        "users": {},
        "applications": {},
        "admins": list(ADMIN_IDS),
        "admin_usernames": {},
        "zam_data": {},
        "zam_stats": {},
        "log_notify_enabled": False,
        "initial_zams_installed": False,

        # Кто был назначен админом по username,
        # но ещё не взаимодействовал с ботом.
        "pending_admin_usernames": [],
    }


def load_data():
    if not os.path.exists(DATA_FILE):
        return default_data()

    try:
        with open(
            DATA_FILE,
            "r",
            encoding="utf-8",
        ) as f:
            loaded = json.load(f)

        if not isinstance(loaded, dict):
            return default_data()

        return loaded

    except Exception:
        return default_data()


data = load_data()


# =========================================================
# MIGRATION
# =========================================================

changed = False

for key, value in default_data().items():
    if key not in data:
        data[key] = value
        changed = True


if not isinstance(
    data.get("admins"),
    list,
):
    data["admins"] = list(
        ADMIN_IDS
    )
    changed = True


if SUPER_ADMIN not in data["admins"]:
    data["admins"].append(
        SUPER_ADMIN
    )
    changed = True


if not isinstance(
    data.get("admin_usernames"),
    dict,
):
    data["admin_usernames"] = {}
    changed = True


if not isinstance(
    data.get("zam_data"),
    dict,
):
    data["zam_data"] = {}
    changed = True


if not isinstance(
    data.get("zam_stats"),
    dict,
):
    data["zam_stats"] = {}
    changed = True


if not isinstance(
    data.get("users"),
    dict,
):
    data["users"] = {}
    changed = True


if not isinstance(
    data.get("applications"),
    dict,
):
    data["applications"] = {}
    changed = True


if not isinstance(
    data.get("pending_admin_usernames"),
    list,
):
    data["pending_admin_usernames"] = []
    changed = True


# =========================================================
# INITIAL ZAMS
# =========================================================

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


# Устанавливаем первоначальных замов только один раз.
if not data.get(
    "initial_zams_installed",
    False,
):
    for nick in INITIAL_ZAM_NICKS:
        if nick not in data["zam_data"]:
            data["zam_data"][nick] = {
                "tg_user_id": None,
                "tg_username": None,
            }

        data["zam_stats"].setdefault(
            nick,
            {
                "count": 0,
                "withdrawn": 0,
                "history": [],
            },
        )

    data["initial_zams_installed"] = True
    changed = True


# =========================================================
# ZAM DATA MIGRATION
# =========================================================

for nick, info in list(
    data["zam_data"].items()
):
    if not isinstance(info, dict):
        data["zam_data"][nick] = {
            "tg_user_id": None,
            "tg_username": None,
        }
        changed = True

    else:
        if "tg_user_id" not in info:
            info["tg_user_id"] = None
            changed = True

        if "tg_username" not in info:
            info["tg_username"] = None
            changed = True


for nick in data["zam_data"]:
    stat = data["zam_stats"].setdefault(
        nick,
        {
            "count": 0,
            "withdrawn": 0,
            "history": [],
        },
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


def save_data():
    with open(
        DATA_FILE,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
        )


if changed:
    save_data()


# =========================================================
# ADMIN HELPERS
# =========================================================

def get_admins():
    return set(
        int(x)
        for x in data.get(
            "admins",
            [],
        )
    )


def save_admins(admins):
    data["admins"] = list(
        sorted(
            set(admins)
        )
    )
    save_data()


def is_super_admin(user_id):
    try:
        return int(user_id) == SUPER_ADMIN
    except Exception:
        return False


def is_admin(user_id):
    try:
        return int(user_id) in get_admins()
    except Exception:
        return False


def normalize_username(username):
    return (
        str(username or "")
        .strip()
        .lstrip("@")
        .lower()
    )


def get_admin_display(admin_id):
    info = data.get(
        "admin_usernames",
        {},
    ).get(
        str(admin_id)
    )

    if isinstance(info, dict):
        username = normalize_username(
            info.get("username")
        )

        if username:
            return (
                f"@{username}"
            )

        full_name = (
            info.get("full_name")
        )

        if full_name:
            return str(
                full_name
            )

    return str(admin_id)


# =========================================================
# USER SYNCHRONIZATION
# =========================================================

def sync_user_from_message(message):
    """
    Каждое входящее сообщение сохраняет username/id пользователя.

    Это позволяет назначить админа по username даже до того,
    как человек первый раз открыл бота.
    Когда он потом пишет боту, система автоматически
    привязывает его Telegram ID к выданной роли.
    """

    user = message.from_user

    if not user:
        return

    username = normalize_username(
        user.username
    )

    if not username:
        return

    pending = {
        normalize_username(x)
        for x in data.get(
            "pending_admin_usernames",
            [],
        )
    }

    if username in pending:
        admins = get_admins()

        if user.id not in admins:
            admins.add(
                user.id
            )
            save_admins(
                admins
            )

        data[
            "admin_usernames"
        ][
            str(user.id)
        ] = {
            "username": username,
            "full_name": (
                user.full_name
                or username
            ),
        }

        data[
            "pending_admin_usernames"
        ] = [
            x
            for x in data.get(
                "pending_admin_usernames",
                [],
            )
            if normalize_username(x)
            != username
        ]

        save_data()


@dp.message()
async def universal_user_sync(
    message: Message
):
    """
    Важный middleware-подобный обработчик.

    Он ничего не делает с обычным текстом кроме синхронизации
    пользователя и позволяет затем работать основным handlers.
    """

    sync_user_from_message(message)


# =========================================================
# LOGS
# =========================================================

async def log_action(
    user_id,
    action,
    details="",
):
    try:
        chat = await bot.get_chat(
            user_id
        )

        if chat.username:
            display = (
                f"@{chat.username}"
            )
        else:
            display = (
                chat.full_name
            )

    except Exception:
        display = str(
            user_id
        )

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    line = (
        f"[{now}] "
        f"{display} -> "
        f"{action} "
        f"{details}\n"
    )

    try:
        with open(
            LOG_FILE,
            "a",
            encoding="utf-8",
        ) as f:
            f.write(line)
    except Exception:
        pass

    if data.get(
        "log_notify_enabled"
    ):
        try:
            await bot.send_message(
                SUPER_ADMIN,
                (
                    f"👤 <b>"
                    f"{escape(display)}"
                    f"</b>\n"
                    f"➡️ {escape(action)}\n"
                    f"📝 {escape(details)}\n"
                    f"🕐 {now}"
                ),
            )
        except Exception:
            pass


# =========================================================
# KEYBOARDS
# =========================================================

def main_keyboard(
    has_survey=False
):
    builder = ReplyKeyboardBuilder()

    builder.row(
        KeyboardButton(
            text="📝 Заполнить анкету"
        )
    )

    if has_survey:
        builder.row(
            KeyboardButton(
                text="🔄 Перезаполнить анкету"
            )
        )

    builder.row(
        KeyboardButton(
            text="👤 Мой профиль"
        )
    )

    return builder.as_markup(
        resize_keyboard=True
    )


def admin_keyboard(
    user_id,
    has_survey=False,
):
    builder = ReplyKeyboardBuilder()

    builder.row(
        KeyboardButton(
            text="📋 Управление заявками"
        ),
        KeyboardButton(
            text="⏳ Активные заявки"
        ),
    )

    builder.row(
        KeyboardButton(
            text="👥 Список участников"
        ),
        KeyboardButton(
            text="🟢 Статус бота"
        ),
    )

    builder.row(
        KeyboardButton(
            text="🛠 Админка"
        )
    )

    if has_survey:
        builder.row(
            KeyboardButton(
                text="🔄 Перезаполнить анкету"
            )
        )

    if is_super_admin(
        user_id
    ):
        builder.row(
            KeyboardButton(
                text="👑 Замы"
            ),
            KeyboardButton(
                text="📜 Журнал действий"
            ),
        )

    return builder.as_markup(
        resize_keyboard=True
    )


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
# START
# =========================================================

@dp.message(CommandStart())
async def start_command(
    message: Message
):
    sync_user_from_message(
        message
    )

    await log_action(
        message.from_user.id,
        "start",
    )

    user_id = message.from_user.id

    has_survey = (
        str(user_id)
        in data["users"]
    )

    if is_admin(user_id):
        await message.answer(
            (
                "🛡️ <b>Панель управления</b>\n\n"
                f"Добро пожаловать в "
                f"<b>{BOT_NAME}</b>."
            ),
            reply_markup=admin_keyboard(
                user_id,
                has_survey,
            ),
        )
    else:
        await message.answer(
            (
                f"👋 <b>Добро пожаловать "
                f"в {BOT_NAME}!</b>\n\n"
                "Заполните анкету "
                "для вступления в семью."
            ),
            reply_markup=main_keyboard(
                has_survey
            ),
        )


# =========================================================
# SURVEY
# =========================================================

user_surveys = {}


async def start_survey(
    message: Message
):
    user_surveys[
        message.from_user.id
    ] = {
        "step": 0,
        "answers": {},
    }

    await message.answer(
        (
            "📋 <b>Заполнение анкеты</b>\n\n"
            "1️⃣ Напиши свой "
            "Nickname в игре:"
        )
    )


@dp.message(
    F.text == "📝 Заполнить анкету"
)
async def survey_button(
    message: Message
):
    sync_user_from_message(
        message
    )

    uid = message.from_user.id

    if str(uid) in data[
        "users"
    ]:
        await message.answer(
            (
                "ℹ️ Вы уже заполнили "
                "анкету.\n"
                "Используй "
                "«🔄 Перезаполнить анкету»."
            )
        )
        return

    await start_survey(
        message
    )


@dp.message(
    F.text == "🔄 Перезаполнить анкету"
)
async def reset_survey(
    message: Message
):
    sync_user_from_message(
        message
    )

    uid = str(
        message.from_user.id
    )

    if uid not in data[
        "users"
    ]:
        await message.answer(
            "❌ У вас нет анкеты."
        )
        return

    for app in data[
        "applications"
    ].values():
        if (
            str(
                app.get("user_id")
            )
            == uid
            and app.get(
                "status"
            )
            == "pending"
        ):
            app[
                "status"
            ] = "cancelled"

    data[
        "users"
    ].pop(
        uid,
        None,
    )

    save_data()

    await start_survey(
        message
    )


@dp.message(
    lambda message:
    message.from_user.id
    in user_surveys
)
async def survey_text_handler(
    message: Message
):
    sync_user_from_message(
        message
    )

    uid = message.from_user.id
    survey = user_surveys[uid]

    if not message.text:
        await message.answer(
            "❌ Нужен текст."
        )
        return

    text = message.text.strip()

    if survey["step"] == 0:
        survey[
            "answers"
        ][
            "nickname"
        ] = text

        survey[
            "answers"
        ][
            "tag"
        ] = (
            f"@{message.from_user.username}"
            if message.from_user.username
            else str(uid)
        )

        survey["step"] = 1

        rows = []

        for rank in RANK_LIST:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=rank,
                        callback_data=(
                            f"rank|{rank}"
                        ),
                    )
                ]
            )

        await message.answer(
            "👤 Выберите ранг:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=rows
            ),
        )

    elif survey["step"] == 3:
        survey[
            "answers"
        ][
            "rank_org"
        ] = text

        survey["step"] = 4

        zams = get_zam_nicknames()

        if not zams:
            await message.answer(
                "⚠️ Замов нет."
            )
            user_surveys.pop(
                uid,
                None,
            )
            return

        rows = []

        for nick in zams:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=nick,
                        callback_data=(
                            f"inviter|{nick}"
                        ),
                    )
                ]
            )

        await message.answer(
            "👑 Кто вас пригласил?",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=rows
            ),
        )


@dp.callback_query(
    F.data.startswith("rank|")
)
async def rank_callback(
    callback: CallbackQuery
):
    uid = callback.from_user.id

    if uid not in user_surveys:
        await callback.answer(
            "❌ Анкета не найдена.",
            show_alert=True,
        )
        return

    rank = callback.data.split(
        "|",
        1,
    )[1]

    user_surveys[
        uid
    ][
        "answers"
    ][
        "rank_fam"
    ] = rank

    user_surveys[
        uid
    ]["step"] = 2

    rows = []

    for org in ORG_LIST:
        rows.append(
            [
                InlineKeyboardButton(
                    text=org,
                    callback_data=(
                        f"org|{org}"
                    ),
                )
            ]
        )

    await callback.message.answer(
        "🏢 Выберите организацию:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=rows
        ),
    )

    await callback.answer()


@dp.callback_query(
    F.data.startswith("org|")
)
async def org_callback(
    callback: CallbackQuery
):
    uid = callback.from_user.id

    if uid not in user_surveys:
        await callback.answer(
            "❌ Анкета не найдена.",
            show_alert=True,
        )
        return

    org = callback.data.split(
        "|",
        1,
    )[1]

    user_surveys[
        uid
    ][
        "answers"
    ][
        "organization"
    ] = org

    user_surveys[
        uid
    ]["step"] = 3

    await callback.message.answer(
        "📌 Напишите свой ранг в организации:"
    )

    await callback.answer()


@dp.callback_query(
    F.data.startswith("inviter|")
)
async def inviter_callback(
    callback: CallbackQuery
):
    uid = callback.from_user.id

    if uid not in user_surveys:
        await callback.answer(
            "❌ Анкета не найдена.",
            show_alert=True,
        )
        return

    nick = callback.data.split(
        "|",
        1,
    )[1]

    if nick not in data[
        "zam_data"
    ]:
        await callback.answer(
            "❌ Такой зам больше не существует.",
            show_alert=True,
        )
        return

    user_surveys[
        uid
    ][
        "answers"
    ][
        "inviter"
    ] = nick

    await finish_survey(
        callback.message,
        uid,
    )

    await callback.answer()


async def finish_survey(
    message,
    uid,
):
    survey = user_surveys.pop(
        uid,
        None,
    )

    if not survey:
        return

    answers = survey[
        "answers"
    ]

    user_data = {
        "nickname": answers.get(
            "nickname",
            "—",
        ),
        "tag": answers.get(
            "tag",
            "—",
        ),
        "rank_fam": answers.get(
            "rank_fam",
            "—",
        ),
        "organization": answers.get(
            "organization",
            "—",
        ),
        "rank_org": answers.get(
            "rank_org",
            "—",
        ),
        "inviter": answers.get(
            "inviter",
            "—",
        ),
    }

    data[
        "users"
    ][
        str(uid)
    ] = user_data

    app_id = (
        f"app_{uid}_"
        f"{int(datetime.now().timestamp())}"
    )

    data[
        "applications"
    ][
        app_id
    ] = {
        "user_id": uid,
        "data": user_data,
        "status": "pending",
        "created": datetime.now().isoformat(),
        "history": [],
    }

    save_data()

    await message.answer(
        "✅ <b>Анкета заполнена!</b>\n"
        "Ожидайте решения администрации."
    )

    text = (
        "📩 <b>Новая заявка!</b>\n\n"
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
        f"Пригласил: "
        f"{escape(user_data['inviter'])}"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Принять",
                    callback_data=(
                        f"accept|{app_id}"
                    ),
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=(
                        f"reject|{app_id}"
                    ),
                ),
            ]
        ]
    )

    for admin_id in get_admins():
        try:
            await bot.send_message(
                admin_id,
                text,
                reply_markup=keyboard,
            )
        except Exception:
            pass


# =========================================================
# APPLICATIONS
# =========================================================

@dp.callback_query(
    F.data.startswith("accept|")
)
async def accept_application(
    callback: CallbackQuery
):
    if not is_admin(
        callback.from_user.id
    ):
        await callback.answer(
            "❌ Нет прав.",
            show_alert=True,
        )
        return

    app_id = callback.data.split(
        "|",
        1,
    )[1]

    app = data[
        "applications"
    ].get(
        app_id
    )

    if not app:
        await callback.answer(
            "❌ Заявка не найдена.",
            show_alert=True,
        )
        return

    if app.get(
        "status"
    ) != "pending":
        await callback.answer(
            "ℹ️ Уже обработано.",
            show_alert=True,
        )
        return

    app[
        "status"
    ] = "accepted"

    app.setdefault(
        "history",
        []
    ).append(
        {
            "action": "accepted",
            "by": callback.from_user.id,
            "created": datetime.now().isoformat(),
        }
    )

    save_data()

    user_id = app[
        "user_id"
    ]

    # Принимаем в группу.
    try:
        await bot.ban_chat_member(
            GROUP_ID,
            user_id,
        )
        await bot.unban_chat_member(
            GROUP_ID,
            user_id,
        )
    except Exception:
        pass

    try:
        invite = await bot.create_chat_invite_link(
            GROUP_ID,
            member_limit=1,
        )

        await bot.send_message(
            user_id,
            (
                "✅ <b>Ваша заявка принята!</b>\n\n"
                f"🔗 Вступите в группу:\n"
                f"{invite.invite_link}"
            ),
        )

    except Exception:
        try:
            await bot.send_message(
                user_id,
                (
                    "✅ <b>Ваша заявка принята!</b>\n\n"
                    f"🔗 {GROUP_LINK}"
                ),
            )
        except Exception:
            pass

    try:
        await bot.set_chat_member_custom_title(
            chat_id=GROUP_ID,
            user_id=user_id,
            custom_title=app[
                "data"
            ].get(
                "nickname",
                "Участник",
            ),
        )
    except Exception:
        pass

    await log_action(
        callback.from_user.id,
        "принял заявку",
        app_id,
    )

    await callback.message.edit_reply_markup(
        reply_markup=None
    )

    await callback.answer(
        "✅ Заявка принята."
    )


@dp.callback_query(
    F.data.startswith("reject|")
)
async def reject_application(
    callback: CallbackQuery
):
    if not is_admin(
        callback.from_user.id
    ):
        await callback.answer(
            "❌ Нет прав.",
            show_alert=True,
        )
        return

    app_id = callback.data.split(
        "|",
        1,
    )[1]

    app = data[
        "applications"
    ].get(
        app_id
    )

    if not app:
        await callback.answer(
            "❌ Заявка не найдена.",
            show_alert=True,
        )
        return

    if app.get(
        "status"
    ) != "pending":
        await callback.answer(
            "ℹ️ Уже обработано.",
            show_alert=True,
        )
        return

    app[
        "status"
    ] = "rejected"

    app.setdefault(
        "history",
        []
    ).append(
        {
            "action": "rejected",
            "by": callback.from_user.id,
            "created": datetime.now().isoformat(),
        }
    )

    save_data()

    await log_action(
        callback.from_user.id,
        "отклонил заявку",
        app_id,
    )

    try:
        await bot.send_message(
            app["user_id"],
            "❌ Ваша заявка отклонена.",
        )
    except Exception:
        pass

    await callback.message.edit_reply_markup(
        reply_markup=None
    )

    await callback.answer(
        "❌ Заявка отклонена."
    )


def pending_applications():
    return [
        (app_id, app)
        for app_id, app
        in data[
            "applications"
        ].items()
        if app.get(
            "status"
        ) == "pending"
    ]


# =========================================================
# APPLICATION BUTTONS
# =========================================================

@dp.message(
    F.text == "📋 Управление заявками"
)
async def applications_button(
    message: Message
):
    if not is_admin(
        message.from_user.id
    ):
        await message.answer(
            "❌ Нет прав."
        )
        return

    if not data[
        "applications"
    ]:
        await message.answer(
            "📭 Заявок нет."
        )
        return

    for app_id, app in data[
        "applications"
    ].items():

        status = app.get(
            "status",
            "pending",
        )

        icon = {
            "pending": "⏳",
            "accepted": "✅",
            "rejected": "❌",
            "cancelled": "🚫",
        }.get(
            status,
            "❔",
        )

        u = app[
            "data"
        ]

        text = (
            f"{icon} <b>Заявка</b>\n\n"
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

        keyboard = None

        if status == "pending":
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅",
                            callback_data=(
                                f"accept|{app_id}"
                            ),
                        ),
                        InlineKeyboardButton(
                            text="❌",
                            callback_data=(
                                f"reject|{app_id}"
                            ),
                        ),
                    ]
                ]
            )

        await message.answer(
            text,
            reply_markup=keyboard,
        )


@dp.message(
    F.text == "⏳ Активные заявки"
)
async def active_applications_button(
    message: Message
):
    if not is_admin(
        message.from_user.id
    ):
        await message.answer(
            "❌ Нет прав."
        )
        return

    apps = pending_applications()

    if not apps:
        await message.answer(
            "📭 Активных заявок нет."
        )
        return

    for app_id, app in apps:
        u = app[
            "data"
        ]

        text = (
            "⏳ <b>Активная заявка</b>\n\n"
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

        await message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ Принять",
                            callback_data=(
                                f"accept|{app_id}"
                            ),
                        ),
                        InlineKeyboardButton(
                            text="❌ Отклонить",
                            callback_data=(
                                f"reject|{app_id}"
                            ),
                        ),
                    ]
                ]
            ),
        )


# =========================================================
# USERS LIST
# =========================================================

@dp.message(
    F.text == "👥 Список участников"
)
async def users_list(
    message: Message
):
    if not is_admin(
        message.from_user.id
    ):
        await message.answer(
            "❌ Нет прав."
        )
        return

    users = data[
        "users"
    ]

    if not users:
        await message.answer(
            "📭 Участников нет."
        )
        return

    text = (
        "👥 <b>Участники</b>\n\n"
    )

    counter = 1

    for uid, user in users.items():
        text += (
            f"<b>{counter}.</b> "
            f"{escape(user.get('nickname', '—'))}\n"
            f"   {escape(user.get('tag', uid))}\n"
            f"   Ранг: "
            f"{escape(user.get('rank_fam', '—'))}\n"
            f"   Организация: "
            f"{escape(user.get('organization', '—'))}\n"
            f"   Пригласитель: "
            f"{escape(user.get('inviter', '—'))}\n\n"
        )

        counter += 1

        if counter > 100:
            break

    await message.answer(
        text
    )


# =========================================================
# PROFILE
# =========================================================

@dp.message(
    F.text == "👤 Мой профиль"
)
async def profile_button(
    message: Message
):
    uid = str(
        message.from_user.id
    )

    user = data[
        "users"
    ].get(
        uid
    )

    if not user:
        await message.answer(
            "ℹ️ Вы ещё не заполнили анкету."
        )
        return

    await message.answer(
        (
            "👤 <b>Мой профиль</b>\n\n"
            f"Nickname: "
            f"{escape(user.get('nickname', '—'))}\n"
            f"Тег: "
            f"{escape(user.get('tag', '—'))}\n"
            f"Ранг: "
            f"{escape(user.get('rank_fam', '—'))}\n"
            f"Организация: "
            f"{escape(user.get('organization', '—'))}\n"
            f"Ранг в организации: "
            f"{escape(user.get('rank_org', '—'))}\n"
            f"Пригласитель: "
            f"{escape(user.get('inviter', '—'))}"
        )
    )


# =========================================================
# WHO
# =========================================================

@dp.message(
    Command("кто")
)
async def who_command(
    message: Message
):
    if not is_admin(
        message.from_user.id
    ):
        await message.answer(
            "❌ Нет прав."
        )
        return

    if not message.reply_to_message:
        await message.answer(
            "❌ Используй /кто ответом "
            "на сообщение участника."
        )
        return

    uid = str(
        message.reply_to_message
        .from_user
        .id
    )

    user = data[
        "users"
    ].get(
        uid
    )

    if not user:
        await message.answer(
            "❌ Анкета пользователя не найдена."
        )
        return

    await message.answer(
        (
            "📋 <b>Информация</b>\n\n"
            f"Nickname: "
            f"{escape(user.get('nickname', '—'))}\n"
            f"Тег: "
            f"{escape(user.get('tag', uid))}\n"
            f"Ранг: "
            f"{escape(user.get('rank_fam', '—'))}\n"
            f"Организация: "
            f"{escape(user.get('organization', '—'))}\n"
            f"Ранг в организации: "
            f"{escape(user.get('rank_org', '—'))}\n"
            f"Пригласитель: "
            f"{escape(user.get('inviter', '—'))}"
        )
    )


# =========================================================
# USERNAME RESOLUTION
# =========================================================

async def resolve_user_by_username(
    username
):
    username = normalize_username(
        username
    )

    if not username:
        return None

    # 1. Уже известные пользователи.
    for raw_id, user in data[
        "users"
    ].items():
        tag = normalize_username(
            user.get("tag")
        )

        if tag == username:
            try:
                return {
                    "id": int(raw_id),
                    "username": username,
                    "full_name": user.get(
                        "nickname",
                        username,
                    ),
                }
            except Exception:
                pass

    # 2. Сохранённые админы.
    for raw_id, info in data[
        "admin_usernames"
    ].items():
        if not isinstance(
            info,
            dict,
        ):
            continue

        saved = normalize_username(
            info.get("username")
        )

        if saved == username:
            try:
                return {
                    "id": int(raw_id),
                    "username": username,
                    "full_name": info.get(
                        "full_name",
                        username,
                    ),
                }
            except Exception:
                pass

    # 3. Сохранённые замы.
    for nick, info in data[
        "zam_data"
    ].items():
        if not isinstance(
            info,
            dict,
        ):
            continue

        saved = normalize_username(
            info.get("tg_username")
        )

        if (
            saved == username
            and info.get(
                "tg_user_id"
            )
        ):
            return {
                "id": int(
                    info["tg_user_id"]
                ),
                "username": username,
                "full_name": nick,
            }

    # 4. Bot API.
    try:
        chat = await bot.get_chat(
            f"@{username}"
        )

        return {
            "id": int(chat.id),
            "username": (
                chat.username
                or username
            ),
            "full_name": (
                chat.full_name
                or username
            ),
        }

    except Exception:
        return None


# =========================================================
# ADMIN MANAGEMENT
# =========================================================

async def add_admin_by_username(
    message: Message,
    username: str,
):
    username = normalize_username(
        username
    )

    if not username:
        await message.answer(
            "❌ Укажи username."
        )
        return

    selected = await resolve_user_by_username(
        username
    )

    if selected:
        user_id = selected["id"]

        if user_id == SUPER_ADMIN:
            await message.answer(
                "ℹ️ Это и так владелец."
            )
            return

        admins = get_admins()

        if user_id in admins:
            await message.answer(
                "❌ Этот человек уже админ."
            )
            return

        admins.add(
            user_id
        )

        save_admins(
            admins
        )

        data[
            "admin_usernames"
        ][
            str(user_id)
        ] = {
            "username": username,
            "full_name": selected.get(
                "full_name",
                username,
            ),
        }

        save_data()

        await message.answer(
            (
                f"✅ <b>@{escape(username)}</b> "
                "назначен администратором."
            )
        )

        await log_action(
            message.from_user.id,
            "добавил администратора",
            f"@{username}",
        )

        try:
            await bot.send_message(
                user_id,
                "👑 Вы назначены администратором!"
            )
        except Exception:
            pass

        await set_command_scopes()
        return

    # Если Bot API пока не знает пользователя,
    # всё равно сохраняем username.
    pending = {
        normalize_username(x)
        for x in data.get(
            "pending_admin_usernames",
            [],
        )
    }

    pending.add(
        username
    )

    data[
        "pending_admin_usernames"
    ] = sorted(
        pending
    )

    save_data()

    await message.answer(
        (
            f"✅ Админ <b>@{escape(username)}</b> "
            "записан по username.\n\n"
            "Telegram пока не дал боту ID этого пользователя. "
            "Когда он напишет боту, система автоматически "
            "привяжет его Telegram ID и выдаст права."
        )
    )

    await log_action(
        message.from_user.id,
        "назначил админа по username",
        f"@{username}",
    )


async def remove_admin_by_username(
    message: Message,
    username: str,
):
    username = normalize_username(
        username
    )

    if not username:
        await message.answer(
            "❌ Укажи username."
        )
        return

    selected = await resolve_user_by_username(
        username
    )

    if selected:
        user_id = selected["id"]

        if user_id == SUPER_ADMIN:
            await message.answer(
                "❌ Нельзя удалить владельца."
            )
            return

        admins = get_admins()

        if user_id not in admins:
            await message.answer(
                "❌ Этот человек не админ."
            )
            return

        admins.remove(
            user_id
        )

        save_admins(
            admins
        )

        data[
            "admin_usernames"
        ].pop(
            str(user_id),
            None,
        )

        save_data()

        await message.answer(
            (
                f"✅ Админка снята с "
                f"<b>@{escape(username)}</b>."
            )
        )

        await log_action(
            message.from_user.id,
            "снял админку",
            f"@{username}",
        )

        await set_command_scopes()
        return

    # Удаляем ещё и отложенное назначение.
    data[
        "pending_admin_usernames"
    ] = [
        x
        for x in data.get(
            "pending_admin_usernames",
            [],
        )
        if normalize_username(x)
        != username
    ]

    save_data()

    await message.answer(
        (
            f"✅ Если <b>@{escape(username)}</b> "
            "был отложенно назначен админом, "
            "назначение отменено."
        )
    )


@dp.message(
    Command("add_admin")
)
async def add_admin_command(
    message: Message
):
    if not is_super_admin(
        message.from_user.id
    ):
        await message.answer(
            "❌ Только владелец!"
        )
        return

    parts = (
        message.text
        or ""
    ).split()

    if len(parts) != 2:
        await message.answer(
            (
                "❌ Формат:\n"
                "<code>/add_admin @username</code>"
            )
        )
        return

    await add_admin_by_username(
        message,
        parts[1],
    )


@dp.message(
    Command("remove_admin")
)
async def remove_admin_command(
    message: Message
):
    if not is_super_admin(
        message.from_user.id
    ):
        await message.answer(
            "❌ Только владелец!"
        )
        return

    parts = (
        message.text
        or ""
    ).split()

    if len(parts) != 2:
        await message.answer(
            (
                "❌ Формат:\n"
                "<code>/remove_admin @username</code>"
            )
        )
        return

    await remove_admin_by_username(
        message,
        parts[1],
    )


# =========================================================
# /ADD COMMAND
# =========================================================

@dp.message(
    Command("add")
)
async def add_command(
    message: Message
):
    if not is_super_admin(
        message.from_user.id
    ):
        await message.answer(
            "❌ Только владелец!"
        )
        return

    parts = (
        message.text
        or ""
    ).split()

    if len(parts) < 2:
        await message.answer(
            (
                "❌ Формат:\n\n"
                "<code>/add admin @username</code>\n"
                "<code>/add zam @username Game_Nick</code>"
            )
        )
        return

    mode = parts[1].lower()

    if mode == "admin":
        if len(parts) != 3:
            await message.answer(
                (
                    "❌ Формат:\n"
                    "<code>/add admin @username</code>"
                )
            )
            return

        await add_admin_by_username(
            message,
            parts[2],
        )
        return

    if mode == "zam":
        if len(parts) < 4:
            await message.answer(
                (
                    "❌ Формат:\n"
                    "<code>/add zam @username Game_Nick</code>"
                )
            )
            return

        await add_zam_by_username(
            message,
            parts[2],
            " ".join(
                parts[3:]
            ),
        )
        return

    await message.answer(
        "❌ Используй admin или zam."
    )


# =========================================================
# ZAMS
# =========================================================

def get_zam_nicknames():
    return list(
        data[
            "zam_data"
        ].keys()
    )


def add_zam_nick(
    game_nick,
    tg_user_id=None,
    tg_username=None,
):
    game_nick = (
        game_nick
        or ""
    ).strip()

    if not game_nick:
        return False, "Пустой игровой ник."

    if game_nick in data[
        "zam_data"
    ]:
        return False, "Такой игровой ник уже есть."

    data[
        "zam_data"
    ][
        game_nick
    ] = {
        "tg_user_id": tg_user_id,
        "tg_username": tg_username,
    }

    data[
        "zam_stats"
    ][
        game_nick
    ] = {
        "count": 0,
        "withdrawn": 0,
        "history": [],
    }

    save_data()

    return True, "Зам добавлен."


def remove_zam_nick(
    game_nick
):
    if game_nick not in data[
        "zam_data"
    ]:
        return False

    data[
        "zam_data"
    ].pop(
        game_nick,
        None,
    )

    data[
        "zam_stats"
    ].pop(
        game_nick,
        None,
    )

    save_data()

    return True


def get_zam_user_id(
    game_nick
):
    info = data[
        "zam_data"
    ].get(
        game_nick
    )

    if not info:
        return None

    return info.get(
        "tg_user_id"
    )


def count_zam_answers(
    game_nick
):
    total = 0

    for user in data[
        "users"
    ].values():

        if user.get(
            "inviter"
        ) == game_nick:
            total += 1

    return total


def get_zam_withdrawn(
    game_nick
):
    stat = data[
        "zam_stats"
    ].get(
        game_nick,
        {},
    )

    try:
        return int(
            stat.get(
                "withdrawn",
                0,
            )
        )
    except Exception:
        return 0


def get_zam_available(
    game_nick
):
    return max(
        0,
        count_zam_answers(
            game_nick
        )
        - get_zam_withdrawn(
            game_nick
        ),
    )


def get_all_zam_counts():
    result = []

    for nick in get_zam_nicknames():
        invited = (
            count_zam_answers(
                nick
            )
        )

        withdrawn = (
            get_zam_withdrawn(
                nick
            )
        )

        available = max(
            0,
            invited - withdrawn,
        )

        result.append(
            (
                nick,
                invited,
                withdrawn,
                available,
            )
        )

    result.sort(
        key=lambda item: (
            -item[3],
            item[0].lower(),
        )
    )

    return result


async def add_zam_by_username(
    message: Message,
    username: str,
    game_nick: str,
):
    username = normalize_username(
        username
    )

    game_nick = (
        game_nick
        or ""
    ).strip()

    if not username:
        await message.answer(
            "❌ Укажи username."
        )
        return

    if not game_nick:
        await message.answer(
            "❌ Укажи игровой ник."
        )
        return

    if game_nick in data[
        "zam_data"
    ]:
        await message.answer(
            "❌ Такой игровой ник уже существует."
        )
        return

    selected = await resolve_user_by_username(
        username
    )

    user_id = (
        selected["id"]
        if selected
        else None
    )

    tg_username = username

    # Нельзя привязать одного Telegram-пользователя к двум замам.
    if user_id:
        for nick, info in data[
            "zam_data"
        ].items():
            if (
                info.get(
                    "tg_user_id"
                )
                == user_id
            ):
                await message.answer(
                    (
                        "❌ Этот Telegram-пользователь "
                        f"уже привязан к заму "
                        f"<b>{escape(nick)}</b>."
                    )
                )
                return

    ok, result = add_zam_nick(
        game_nick,
        user_id,
        tg_username,
    )

    if not ok:
        await message.answer(
            f"❌ {escape(result)}"
        )
        return

    await log_action(
        message.from_user.id,
        "добавил зама",
        (
            f"{game_nick} "
            f"/ @{username}"
        ),
    )

    if user_id:
        await message.answer(
            (
                f"✅ Зам <b>{escape(game_nick)}</b> "
                f"назначен:\n"
                f"👤 @{escape(username)}"
            )
        )

        try:
            await bot.send_message(
                user_id,
                (
                    "👑 Вы назначены замом!\n"
                    f"Игровой ник: "
                    f"<b>{escape(game_nick)}</b>"
                ),
            )
        except Exception:
            pass

    else:
        await message.answer(
            (
                f"✅ Зам <b>{escape(game_nick)}</b> "
                f"назначен по username "
                f"<b>@{escape(username)}</b>.\n\n"
                "Telegram пока не дал ID пользователя. "
                "Если он напишет боту, его Telegram ID "
                "можно будет автоматически привязать."
            )
        )


async def remove_zam_by_nick(
    message: Message,
    game_nick: str,
):
    game_nick = (
        game_nick
        or ""
    ).strip()

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
        game_nick,
    )

    await message.answer(
        (
            f"✅ Зам <b>{escape(game_nick)}</b> "
            "удалён."
        )
    )


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

    raw = (
        message.text
        or ""
    ).strip()

    parts = raw.split(
        maxsplit=1
    )

    if len(parts) < 2:
        await message.answer(
            (
                "❌ Формат:\n"
                "<code>/add_zam @username Game_Nick</code>\n\n"
                "Можно также:\n"
                "<code>/add_zam Game_Nick: @username</code>"
            )
        )
        return

    rest = parts[1].strip()

    # Game_Nick: @username
    if ":" in rest:
        left, right = rest.split(
            ":",
            1,
        )

        game_nick = left.strip()
        username = right.strip().split()[0]

        if username.startswith("@"):
            await add_zam_by_username(
                message,
                username,
                game_nick,
            )
            return

    # @username Game_Nick
    words = rest.split()

    if (
        len(words) >= 2
        and words[0].startswith("@")
    ):
        await add_zam_by_username(
            message,
            words[0],
            " ".join(
                words[1:]
            ),
        )
        return

    await message.answer(
        (
            "❌ Формат:\n"
            "<code>/add_zam @username Game_Nick</code>"
        )
    )


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

    parts = (
        message.text
        or ""
    ).split(
        maxsplit=1
    )

    if len(parts) < 2:
        await message.answer(
            (
                "❌ Формат:\n"
                "<code>/remove_zam Game_Nick</code>"
            )
        )
        return

    await remove_zam_by_nick(
        message,
        parts[1],
    )


# =========================================================
# /REMOVE
# =========================================================

@dp.message(
    Command("remove")
)
async def remove_command(
    message: Message
):
    if not is_super_admin(
        message.from_user.id
    ):
        await message.answer(
            "❌ Только владелец!"
        )
        return

    parts = (
        message.text
        or ""
    ).split()

    if len(parts) != 3:
        await message.answer(
            (
                "❌ Формат:\n\n"
                "<code>/remove admin @username</code>\n"
                "<code>/remove zam Game_Nick</code>"
            )
        )
        return

    mode = parts[1].lower()

    if mode == "admin":
        await remove_admin_by_username(
            message,
            parts[2],
        )
        return

    if mode == "zam":
        await remove_zam_by_nick(
            message,
            parts[2],
        )
        return

    await message.answer(
        "❌ Используй admin или zam."
    )


# =========================================================
# ADMIN PANEL
# =========================================================

@dp.message(
    F.text == "🛠 Админка"
)
async def admin_panel(
    message: Message
):
    if not is_super_admin(
        message.from_user.id
    ):
        await message.answer(
            "❌ Только владелец!"
        )
        return

    await message.answer(
        (
            "👑 <b>Админка</b>\n\n"
            "Добавление:\n"
            "<code>/add_admin @username</code>\n\n"
            "Удаление:\n"
            "<code>/remove_admin @username</code>\n\n"
            "Можно также использовать:\n"
            "<code>/add admin @username</code>"
        ),
        reply_markup=admin_panel_keyboard(),
    )


@dp.callback_query(
    F.data == "adm:add"
)
async def admin_add_button(
    callback: CallbackQuery
):
    if not is_super_admin(
        callback.from_user.id
    ):
        await callback.answer(
            "❌ Только владелец!",
            show_alert=True,
        )
        return

    await callback.message.answer(
        "➕ Напиши:\n"
        "<code>/add_admin @username</code>"
    )

    await callback.answer()


@dp.callback_query(
    F.data == "adm:remove"
)
async def admin_remove_button(
    callback: CallbackQuery
):
    if not is_super_admin(
        callback.from_user.id
    ):
        await callback.answer(
            "❌ Только владелец!",
            show_alert=True,
        )
        return

    await callback.message.answer(
        "➖ Напиши:\n"
        "<code>/remove_admin @username</code>"
    )

    await callback.answer()


@dp.callback_query(
    F.data == "adm:list"
)
async def admin_list_button(
    callback: CallbackQuery
):
    if not is_super_admin(
        callback.from_user.id
    ):
        await callback.answer(
            "❌ Только владелец!",
            show_alert=True,
        )
        return

    admins = sorted(
        get_admins()
    )

    text = (
        "👑 <b>Администраторы</b>\n\n"
    )

    for admin_id in admins:
        role = (
            "Владелец"
            if admin_id == SUPER_ADMIN
            else "Админ"
        )

        text += (
            f"• "
            f"{escape(get_admin_display(admin_id))}"
            f" — {role}\n"
        )

    pending = data.get(
        "pending_admin_usernames",
        [],
    )

    if pending:
        text += (
            "\n🕓 <b>Ожидают первого контакта:</b>\n"
        )

        for username in pending:
            text += (
                f"• @{escape(username)}\n"
            )

    await callback.message.answer(
        text
    )

    await callback.answer()


# =========================================================
# ZAMS PANEL
# =========================================================

@dp.message(
    F.text == "👑 Замы"
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

    await send_zams_panel(
        message
    )


async def send_zams_panel(
    message: Message
):
    zams = get_all_zam_counts()

    text = (
        "👑 <b>Замы</b>\n\n"
    )

    if not zams:
        text += "📭 Замов нет."

    else:
        for (
            nick,
            invited,
            withdrawn,
            available,
        ) in zams:

            info = data[
                "zam_data"
            ].get(
                nick,
                {},
            )

            tg_username = normalize_username(
                info.get(
                    "tg_username"
                )
            )

            tg_part = (
                f" — @{escape(tg_username)}"
                if tg_username
                else ""
            )

            text += (
                f"👤 <b>{escape(nick)}</b>"
                f"{tg_part}\n"
                f"   📋 Приглашено: {invited}\n"
                f"   💸 Выведено: {withdrawn}\n"
                f"   🟢 Доступно: {available}\n\n"
            )

    await message.answer(
        text,
        reply_markup=zams_panel_keyboard(),
    )


@dp.callback_query(
    F.data == "zam:add"
)
async def zam_add_button(
    callback: CallbackQuery
):
    if not is_super_admin(
        callback.from_user.id
    ):
        await callback.answer(
            "❌ Только владелец!",
            show_alert=True,
        )
        return

    await callback.message.answer(
        (
            "➕ Добавить зама:\n\n"
            "<code>/add_zam @username Game_Nick</code>"
        )
    )

    await callback.answer()


@dp.callback_query(
    F.data == "zam:remove"
)
async def zam_remove_button(
    callback: CallbackQuery
):
    if not is_super_admin(
        callback.from_user.id
    ):
        await callback.answer(
            "❌ Только владелец!",
            show_alert=True,
        )
        return

    await callback.message.answer(
        (
            "➖ Удалить зама:\n\n"
            "<code>/remove_zam Game_Nick</code>"
        )
    )

    await callback.answer()


@dp.callback_query(
    F.data == "zam:stats"
)
async def zam_stats_button(
    callback: CallbackQuery
):
    if not is_super_admin(
        callback.from_user.id
    ):
        await callback.answer(
            "❌ Только владелец!",
            show_alert=True,
        )
        return

    await send_zam_stats(
        callback.message
    )

    await callback.answer()


async def send_zam_stats(
    message: Message
):
    zams = get_all_zam_counts()

    if not zams:
        await message.answer(
            "📭 Замов нет."
        )
        return

    text = (
        "📊 <b>Статистика замов</b>\n\n"
    )

    for (
        nick,
        invited,
        withdrawn,
        available,
    ) in zams:

        text += (
            f"👤 <b>{escape(nick)}</b>\n"
            f"   📋 Приглашено: {invited}\n"
            f"   💸 Выведено: {withdrawn}\n"
            f"   🟢 Доступно: {available}\n\n"
        )

    await message.answer(
        text
    )


@dp.message(
    Command("zam_stats")
)
async def zam_stats_command(
    message: Message
):
    if not is_super_admin(
        message.from_user.id
    ):
        await message.answer(
            "❌ Только владелец!"
        )
        return

    await send_zam_stats(
        message
    )


# =========================================================
# WITHDRAW
# =========================================================

@dp.message(
    Command("withdraw")
)
async def withdraw_command(
    message: Message
):
    if not is_super_admin(
        message.from_user.id
    ):
        await message.answer(
            "❌ Только владелец!"
        )
        return

    parts = (
        message.text
        or ""
    ).split(
        maxsplit=2
    )

    if len(parts) != 3:
        await message.answer(
            (
                "❌ Формат:\n"
                "<code>/withdraw @username сумма</code>"
            )
        )
        return

    username = normalize_username(
        parts[1]
    )

    try:
        amount = int(
            parts[2]
        )
    except Exception:
        await message.answer(
            "❌ Сумма должна быть числом."
        )
        return

    if amount < 100:
        await message.answer(
            "❌ Минимум 100."
        )
        return

    if amount % 100 != 0:
        await message.answer(
            "❌ Сумма должна быть кратна 100."
        )
        return

    game_nick = None

    for nick, info in data[
        "zam_data"
    ].items():
        saved_username = normalize_username(
            info.get(
                "tg_username"
            )
        )

        if (
            saved_username
            == username
        ):
            game_nick = nick
            break

    if not game_nick:
        await message.answer(
            "❌ Зам не найден."
        )
        return

    need = amount // 100

    available = get_zam_available(
        game_nick
    )

    if available < need:
        await message.answer(
            (
                f"❌ Недостаточно приглашений.\n"
                f"Доступно: {available}\n"
                f"Нужно: {need}"
            )
        )
        return

    stat = data[
        "zam_stats"
    ].setdefault(
        game_nick,
        {
            "count": 0,
            "withdrawn": 0,
            "history": [],
        },
    )

    stat[
        "withdrawn"
    ] = (
        int(
            stat.get(
                "withdrawn",
                0,
            )
        )
        + need
    )

    stat.setdefault(
        "history",
        []
    ).append(
        {
            "amount": amount,
            "invites": need,
            "by": message.from_user.id,
            "created": datetime.now().isoformat(),
        }
    )

    save_data()

    user_id = get_zam_user_id(
        game_nick
    )

    if user_id:
        try:
            await bot.send_message(
                user_id,
                (
                    f"💰 Вывод: "
                    f"<b>{amount}k</b>\n"
                    f"Использовано приглашений: "
                    f"{need}"
                ),
            )
        except Exception:
            pass

    await log_action(
        message.from_user.id,
        "вывод",
        f"{game_nick}: {amount}k",
    )

    await message.answer(
        (
            f"✅ Вывод оформлен.\n"
            f"👤 {escape(game_nick)}\n"
            f"💰 {amount}k\n"
            f"🟢 Осталось: "
            f"{get_zam_available(game_nick)}"
        )
    )


# =========================================================
# STATUS
# =========================================================

@dp.message(
    F.text == "🟢 Статус бота"
)
async def bot_status(
    message: Message
):
    if not is_admin(
        message.from_user.id
    ):
        await message.answer(
            "❌ Нет прав."
        )
        return

    total_users = len(
        data["users"]
    )

    pending = len(
        pending_applications()
    )

    accepted = sum(
        1
        for app
        in data[
            "applications"
        ].values()
        if app.get(
            "status"
        ) == "accepted"
    )

    rejected = sum(
        1
        for app
        in data[
            "applications"
        ].values()
        if app.get(
            "status"
        ) == "rejected"
    )

    uptime = (
        datetime.now()
        - BOT_START_TIME
    )

    await message.answer(
        (
            "🟢 <b>Бот работает</b>\n\n"
            f"👥 Участников: {total_users}\n"
            f"⏳ Активных заявок: {pending}\n"
            f"✅ Принято: {accepted}\n"
            f"❌ Отклонено: {rejected}\n"
            f"⏱ Аптайм: {uptime}"
        )
    )


# =========================================================
# PING
# =========================================================

@dp.message(
    Command("ping")
)
async def ping_command(
    message: Message
):
    if not is_admin(
        message.from_user.id
    ):
        await message.answer(
            "❌ Только админы."
        )
        return

    started = datetime.now()

    sent = await message.answer(
        "🏓 Проверяю..."
    )

    elapsed = (
        datetime.now()
        - started
    ).total_seconds() * 1000

    uptime = (
        datetime.now()
        - BOT_START_TIME
    )

    await sent.edit_text(
        (
            f"🏓 <b>Понг!</b>\n"
            f"📡 {elapsed:.1f} мс\n"
            f"⏱ Аптайм: {uptime}"
        )
    )


# =========================================================
# MY ID
# =========================================================

@dp.message(
    Command("myid")
)
async def myid_command(
    message: Message
):
    await message.answer(
        (
            f"🆔 Твой Telegram ID:\n"
            f"<code>{message.from_user.id}</code>\n\n"
            f"👑 ID владельца:\n"
            f"<code>{SUPER_ADMIN}</code>"
        )
    )


# =========================================================
# LOGS
# =========================================================

@dp.message(
    Command("logs")
)
async def logs_command(
    message: Message
):
    if not is_super_admin(
        message.from_user.id
    ):
        await message.answer(
            "❌ Только владелец."
        )
        return

    try:
        with open(
            LOG_FILE,
            "r",
            encoding="utf-8",
        ) as f:
            content = f.read()

    except Exception:
        content = ""

    if not content:
        await message.answer(
            "📭 Логи пустые."
        )
        return

    if len(content) > 3800:
        content = content[
            -3800:
        ]

    await message.answer(
        (
            "📜 <b>Последние логи</b>\n\n"
            f"<pre>{escape(content)}</pre>"
        )
    )


@dp.message(
    F.text == "📜 Журнал действий"
)
async def logs_button(
    message: Message
):
    await logs_command(
        message
    )


@dp.message(
    Command("clearlogs")
)
async def clear_logs_command(
    message: Message
):
    if not is_super_admin(
        message.from_user.id
    ):
        await message.answer(
            "❌ Только владелец."
        )
        return

    try:
        with open(
            LOG_FILE,
            "w",
            encoding="utf-8",
        ) as f:
            f.write("")

    except Exception:
        pass

    await message.answer(
        "✅ Логи очищены."
    )


# =========================================================
# LOG NOTIFICATIONS
# =========================================================

@dp.message(
    Command("log_on")
)
async def log_on_command(
    message: Message
):
    if not is_super_admin(
        message.from_user.id
    ):
        await message.answer(
            "❌ Только владелец."
        )
        return

    data[
        "log_notify_enabled"
    ] = True

    save_data()

    await message.answer(
        "✅ Уведомления логов включены."
    )


@dp.message(
    Command("log_off")
)
async def log_off_command(
    message: Message
):
    if not is_super_admin(
        message.from_user.id
    ):
        await message.answer(
            "❌ Только владелец."
        )
        return

    data[
        "log_notify_enabled"
    ] = False

    save_data()

    await message.answer(
        "❌ Уведомления логов выключены."
    )


# =========================================================
# ALL
# =========================================================

@dp.message(
    Command("all")
)
async def all_command(
    message: Message
):
    if not is_admin(
        message.from_user.id
    ):
        await message.answer(
            "❌ Только админы."
        )
        return

    parts = (
        message.text
        or ""
    ).split(
        maxsplit=1
    )

    if len(parts) < 2:
        await message.answer(
            (
                "❌ Формат:\n"
                "<code>/all текст</code>"
            )
        )
        return

    text = escape(
        parts[1]
    )

    try:
        await bot.send_message(
            GROUP_ID,
            (
                "⚠️ <b>ВАЖНОЕ ОБЪЯВЛЕНИЕ</b>\n\n"
                f"{text}\n\n"
                "@all"
            ),
            message_thread_id=ANNOUNCE_TOPIC_ID,
        )

        await message.answer(
            "✅ Объявление отправлено."
        )

    except Exception as e:
        await message.answer(
            (
                "❌ Ошибка:\n"
                f"<code>{escape(str(e))}</code>"
            )
        )


# =========================================================
# TOPIC ID
# =========================================================

@dp.message(
    Command("topic_id")
)
async def topic_id_command(
    message: Message
):
    if (
        message.chat.id
        == GROUP_ID
        and message.message_thread_id
    ):
        await message.answer(
            (
                f"🆔 ID темы:\n"
                f"<code>{message.message_thread_id}</code>"
            )
        )
    else:
        await message.answer(
            "❌ Используй команду внутри темы."
        )


# =========================================================
# GROUP TOPIC PROTECTION
# =========================================================

@dp.message(
    F.chat.id == GROUP_ID
)
async def protect_topic(
    message: Message
):
    if (
        message.message_thread_id
        != ANNOUNCE_TOPIC_ID
    ):
        return

    if is_admin(
        message.from_user.id
    ):
        return

    try:
        await message.delete()
    except Exception:
        pass


# =========================================================
# ADMINS COMMAND
# =========================================================

@dp.message(
    Command("admins")
)
async def admins_command(
    message: Message
):
    if not is_super_admin(
        message.from_user.id
    ):
        await message.answer(
            "❌ Только владелец."
        )
        return

    admins = sorted(
        get_admins()
    )

    text = (
        "👑 <b>Список админов</b>\n\n"
    )

    for admin_id in admins:
        role = (
            "Владелец"
            if admin_id == SUPER_ADMIN
            else "Админ"
        )

        text += (
            f"• "
            f"{escape(get_admin_display(admin_id))}"
            f" — {role}\n"
        )

    pending = data.get(
        "pending_admin_usernames",
        [],
    )

    if pending:
        text += (
            "\n🕓 <b>Назначены по username "
            "и ещё не активировались:</b>\n"
        )

        for username in pending:
            text += (
                f"• @{escape(username)}\n"
            )

    await message.answer(
        text
    )


# =========================================================
# HELP
# =========================================================

@dp.message(
    Command("help")
)
async def help_command(
    message: Message
):
    if is_super_admin(
        message.from_user.id
    ):
        text = (
            "📖 <b>Команды владельца</b>\n\n"

            "/start — меню\n"
            "/help — помощь\n"
            "/myid — мой ID\n"
            "/ping — проверка бота\n\n"

            "<b>Админы</b>\n"
            "/add_admin @username\n"
            "/remove_admin @username\n"
            "/add admin @username\n"
            "/remove admin @username\n"
            "/admins — список админов\n\n"

            "<b>Замы</b>\n"
            "/add_zam @username Game_Nick\n"
            "/add_zam Game_Nick: @username\n"
            "/remove_zam Game_Nick\n"
            "/add zam @username Game_Nick\n"
            "/remove zam Game_Nick\n"
            "/zam_stats — статистика\n"
            "/withdraw @username сумма\n\n"

            "<b>Прочее</b>\n"
            "/all текст\n"
            "/logs\n"
            "/clearlogs\n"
            "/log_on\n"
            "/log_off\n"
            "/topic_id\n"
            "/кто — ответом на сообщение"
        )

    elif is_admin(
        message.from_user.id
    ):
        text = (
            "📖 <b>Команды администратора</b>\n\n"
            "/start\n"
            "/help\n"
            "/myid\n"
            "/ping\n"
            "/all текст\n"
            "/кто\n"
            "/topic_id"
        )

    else:
        text = (
            "📖 <b>Команды</b>\n\n"
            "/start\n"
            "/help\n"
            "/myid"
        )

    await message.answer(
        text
    )


# =========================================================
# COMMAND SCOPES
# =========================================================

DEFAULT_COMMANDS = [
    BotCommand(
        command="start",
        description="🏠 Меню",
    ),
    BotCommand(
        command="help",
        description="📖 Помощь",
    ),
    BotCommand(
        command="myid",
        description="🆔 Мой ID",
    ),
]


ADMIN_COMMANDS = [
    BotCommand(
        command="start",
        description="🏠 Меню",
    ),
    BotCommand(
        command="help",
        description="📖 Помощь",
    ),
    BotCommand(
        command="myid",
        description="🆔 Мой ID",
    ),
    BotCommand(
        command="ping",
        description="📡 Пинг",
    ),
    BotCommand(
        command="all",
        description="📢 Объявление",
    ),
    BotCommand(
        command="кто",
        description="👤 Кто",
    ),
    BotCommand(
        command="topic_id",
        description="🆔 ID темы",
    ),
]


OWNER_COMMANDS = [
    *ADMIN_COMMANDS,

    BotCommand(
        command="add_admin",
        description="➕ Добавить админа",
    ),
    BotCommand(
        command="remove_admin",
        description="➖ Удалить админа",
    ),
    BotCommand(
        command="add_zam",
        description="👑 Добавить зама",
    ),
    BotCommand(
        command="remove_zam",
        description="❌ Удалить зама",
    ),
    BotCommand(
        command="admins",
        description="👑 Список админов",
    ),
    BotCommand(
        command="zam_stats",
        description="📊 Статистика замов",
    ),
    BotCommand(
        command="withdraw",
        description="💰 Вывод",
    ),
    BotCommand(
        command="logs",
        description="📜 Логи",
    ),
    BotCommand(
        command="clearlogs",
        description="🧹 Очистить логи",
    ),
    BotCommand(
        command="log_on",
        description="🔔 Включить логи",
    ),
    BotCommand(
        command="log_off",
        description="🔕 Выключить логи",
    ),
]


async def set_command_scopes():
    try:
        await bot.set_my_commands(
            DEFAULT_COMMANDS,
            scope=BotCommandScopeDefault(),
        )
    except Exception:
        pass

    for admin_id in get_admins():
        if admin_id == SUPER_ADMIN:
            continue

        try:
            await bot.set_my_commands(
                ADMIN_COMMANDS,
                scope=BotCommandScopeChat(
                    chat_id=admin_id
                ),
            )
        except Exception:
            pass

    try:
        await bot.set_my_commands(
            OWNER_COMMANDS,
            scope=BotCommandScopeChat(
                chat_id=SUPER_ADMIN
            ),
        )
    except Exception:
        pass


# =========================================================
# MAIN
# =========================================================

async def main():
    print(
        "🤖 Бот запускается..."
    )

    print(
        f"👑 Владелец: {SUPER_ADMIN}"
    )

    print(
        "ℹ️ Режим управления: username-команды"
    )

    await set_command_scopes()

    # Webhook отключаем перед polling.
    await bot.delete_webhook(
        drop_pending_updates=True
    )

    print(
        "🤖 Бот запущен!"
    )

    await dp.start_polling(
        bot
    )


if __name__ == "__main__":
    try:
        asyncio.run(
            main()
        )
    except KeyboardInterrupt:
        print(
            "🛑 Бот остановлен."
        )
