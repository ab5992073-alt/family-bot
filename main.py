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
# RENDER WEB SERVER
# =========================================================

app = Flask(__name__)


@app.route("/")
def health():
    return "Bot is running!", 200


def run_web():
    port = int(os.environ.get("PORT", "10000"))
    app.run(
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
        "BOT_TOKEN не задан в Render Environment."
    )

# ВЛАДЕЛЕЦ
SUPER_ADMIN = 6166697485

# Старые админы
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
# CONSTANTS
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


INITIAL_ZAMS = [
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
# DATA
# =========================================================

DATA_FILE = "data.json"
LOG_FILE = "bot_activity.log"


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
            obj = json.load(f)

        if isinstance(obj, dict):
            return obj

    except Exception as e:
        print(
            f"⚠️ Ошибка data.json: {e}"
        )

    return default_data()


data = load_data()


def save_data():
    try:
        tmp_file = DATA_FILE + ".tmp"

        with open(
            tmp_file,
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2,
            )

        os.replace(
            tmp_file,
            DATA_FILE,
        )

    except Exception as e:
        print(
            f"⚠️ Ошибка сохранения data.json: {e}"
        )


# =========================================================
# DATA MIGRATION
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
    data.get("pending_admin_usernames"),
    list,
):
    data["pending_admin_usernames"] = []
    changed = True


# =========================================================
# INITIAL ZAMS
# =========================================================

if not data.get(
    "initial_zams_installed",
    False,
):
    for nick in INITIAL_ZAMS:
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


for nick, info in list(
    data["zam_data"].items()
):
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


for nick in data["zam_data"]:
    data["zam_stats"].setdefault(
        nick,
        {
            "count": 0,
            "withdrawn": 0,
            "history": [],
        },
    )


if changed:
    save_data()


# =========================================================
# HELPERS
# =========================================================

def normalize_username(
    username,
):
    return (
        str(username or "")
        .strip()
        .lstrip("@")
        .lower()
    )


def is_super_admin(
    user_id,
):
    try:
        return int(user_id) == SUPER_ADMIN
    except Exception:
        return False


def get_admins():
    result = set()

    for value in data.get(
        "admins",
        [],
    ):
        try:
            result.add(
                int(value)
            )
        except Exception:
            pass

    return result


def is_admin(
    user_id,
):
    try:
        return int(user_id) in get_admins()
    except Exception:
        return False


def save_admins(
    admins,
):
    data["admins"] = sorted(
        set(
            int(x)
            for x in admins
        )
    )

    if SUPER_ADMIN not in data["admins"]:
        data["admins"].append(
            SUPER_ADMIN
        )

    save_data()


def get_admin_display(
    admin_id,
):
    info = data.get(
        "admin_usernames",
        {},
    ).get(
        str(admin_id)
    )

    if isinstance(
        info,
        dict,
    ):
        username = normalize_username(
            info.get("username")
        )

        if username:
            return (
                f"@{username}"
            )

        full_name = info.get(
            "full_name"
        )

        if full_name:
            return str(
                full_name
            )

    return str(admin_id)


# =========================================================
# LOG
# =========================================================

async def log_action(
    user_id,
    action,
    details="",
):
    try:
        chat = await bot.get_chat(
            int(user_id)
        )

        if chat.username:
            who = (
                f"@{chat.username}"
            )
        elif chat.full_name:
            who = chat.full_name
        else:
            who = str(user_id)

    except Exception:
        who = str(user_id)

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    line = (
        f"[{now}] "
        f"{who} -> "
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
                    f"👤 <b>{escape(str(who))}</b>\n"
                    f"➡️ {escape(str(action))}\n"
                    f"📝 {escape(str(details))}\n"
                    f"🕐 {now}"
                ),
            )
        except Exception:
            pass


# =========================================================
# USER SAVE
# =========================================================

def remember_user(
    message: Message,
):
    user = message.from_user

    if not user:
        return

    username = normalize_username(
        user.username
    )

    if not username:
        return

    data.setdefault(
        "admin_usernames",
        {}
    )


# =========================================================
# KEYBOARDS
# =========================================================

def main_keyboard(
    has_profile=False,
):
    builder = ReplyKeyboardBuilder()

    builder.row(
        KeyboardButton(
            text="📝 Заполнить анкету"
        )
    )

    if has_profile:
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
    has_profile=False,
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

    if has_profile:
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
                    callback_data="adm_add",
                ),
                InlineKeyboardButton(
                    text="➖ Удалить админа",
                    callback_data="adm_remove",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="👑 Список админов",
                    callback_data="adm_list",
                ),
            ],
        ]
    )


def zam_panel_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Добавить зама",
                    callback_data="zam_add",
                )
            ],
            [
                InlineKeyboardButton(
                    text="➖ Удалить зама",
                    callback_data="zam_remove",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Статистика",
                    callback_data="zam_stats",
                )
            ],
        ]
    )


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def start_handler(
    message: Message,
):
    remember_user(message)

    uid = message.from_user.id

    has_profile = (
        str(uid)
        in data["users"]
    )

    if is_admin(uid):
        await message.answer(
            (
                "🛡️ <b>Панель управления</b>\n\n"
                f"Добро пожаловать в "
                f"<b>{BOT_NAME}</b>!"
            ),
            reply_markup=admin_keyboard(
                uid,
                has_profile,
            ),
        )
    else:
        await message.answer(
            (
                f"👋 <b>Добро пожаловать "
                f"в {BOT_NAME}!</b>\n\n"
                "Заполните анкету "
                "для вступления."
            ),
            reply_markup=main_keyboard(
                has_profile,
            ),
        )

    await log_action(
        uid,
        "start",
    )


# =========================================================
# SURVEY
# =========================================================

survey_state = {}


async def begin_survey(
    message: Message,
):
    survey_state[
        message.from_user.id
    ] = {
        "step": 0,
        "answers": {},
    }

    await message.answer(
        (
            "📋 <b>Заполнение анкеты</b>\n\n"
            "Напишите ваш игровой Nickname:"
        )
    )


@dp.message(
    F.text == "📝 Заполнить анкету"
)
async def survey_start_button(
    message: Message,
):
    uid = message.from_user.id

    if str(uid) in data[
        "users"
    ]:
        await message.answer(
            (
                "ℹ️ Анкета уже заполнена.\n"
                "Используйте "
                "«🔄 Перезаполнить анкету»."
            )
        )
        return

    await begin_survey(
        message
    )


@dp.message(
    F.text == "🔄 Перезаполнить анкету"
)
async def survey_reset_button(
    message: Message,
):
    uid = str(
        message.from_user.id
    )

    data[
        "users"
    ].pop(
        uid,
        None,
    )

    for app_id, application in data[
        "applications"
    ].items():
        if (
            str(
                application.get("user_id")
            )
            == uid
            and application.get(
                "status"
            )
            == "pending"
        ):
            application[
                "status"
            ] = "cancelled"

    save_data()

    await begin_survey(
        message
    )


@dp.message(
    lambda message:
    message.from_user.id
    in survey_state
)
async def survey_text_handler(
    message: Message,
):
    state = survey_state[
        message.from_user.id
    ]

    text = (
        message.text
        or ""
    ).strip()

    if not text:
        await message.answer(
            "❌ Напишите текст."
        )
        return

    step = state[
        "step"
    ]

    if step == 0:
        state[
            "answers"
        ][
            "nickname"
        ] = text

        username = message.from_user.username

        state[
            "answers"
        ][
            "tag"
        ] = (
            f"@{username}"
            if username
            else str(
                message.from_user.id
            )
        )

        state[
            "step"
        ] = 1

        rows = [
            [
                InlineKeyboardButton(
                    text=rank,
                    callback_data=f"rank:{rank}",
                )
            ]
            for rank in RANK_LIST
        ]

        await message.answer(
            "👤 Выберите ваш ранг:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=rows
            ),
        )

    elif step == 3:
        state[
            "answers"
        ][
            "rank_org"
        ] = text

        state[
            "step"
        ] = 4

        zams = list(
            data[
                "zam_data"
            ].keys()
        )

        if not zams:
            await message.answer(
                "❌ Замов сейчас нет."
            )

            survey_state.pop(
                message.from_user.id,
                None,
            )

            return

        rows = [
            [
                InlineKeyboardButton(
                    text=nick,
                    callback_data=(
                        f"inviter:{nick}"
                    ),
                )
            ]
            for nick in zams
        ]

        await message.answer(
            "👑 Кто вас пригласил?",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=rows
            ),
        )


@dp.callback_query(
    F.data.startswith("rank:")
)
async def rank_callback(
    callback: CallbackQuery,
):
    uid = callback.from_user.id

    state = survey_state.get(
        uid
    )

    if not state:
        await callback.answer(
            "❌ Анкета не найдена.",
            show_alert=True,
        )
        return

    rank = callback.data.split(
        ":",
        1,
    )[1]

    state[
        "answers"
    ][
        "rank_fam"
    ] = rank

    state[
        "step"
    ] = 2

    rows = [
        [
            InlineKeyboardButton(
                text=org,
                callback_data=f"org:{org}",
            )
        ]
        for org in ORG_LIST
    ]

    await callback.message.answer(
        "🏢 Выберите организацию:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=rows
        ),
    )

    await callback.answer()


@dp.callback_query(
    F.data.startswith("org:")
)
async def org_callback(
    callback: CallbackQuery,
):
    uid = callback.from_user.id

    state = survey_state.get(
        uid
    )

    if not state:
        await callback.answer(
            "❌ Анкета не найдена.",
            show_alert=True,
        )
        return

    org = callback.data.split(
        ":",
        1,
    )[1]

    state[
        "answers"
    ][
        "organization"
    ] = org

    state[
        "step"
    ] = 3

    await callback.message.answer(
        "📌 Напишите ваш ранг в организации:"
    )

    await callback.answer()


@dp.callback_query(
    F.data.startswith("inviter:")
)
async def inviter_callback(
    callback: CallbackQuery,
):
    uid = callback.from_user.id

    state = survey_state.get(
        uid
    )

    if not state:
        await callback.answer(
            "❌ Анкета не найдена.",
            show_alert=True,
        )
        return

    nick = callback.data.split(
        ":",
        1,
    )[1]

    if nick not in data[
        "zam_data"
    ]:
        await callback.answer(
            "❌ Зам не найден.",
            show_alert=True,
        )
        return

    state[
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
    message: Message,
    uid: int,
):
    state = survey_state.pop(
        uid,
        None,
    )

    if not state:
        return

    answers = state[
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
        (
            "✅ <b>Анкета заполнена!</b>\n\n"
            "Ожидайте решения администрации."
        )
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
        f"Пригласитель: "
        f"{escape(user_data['inviter'])}"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Принять",
                    callback_data=f"accept:{app_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"reject:{app_id}",
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
# APPLICATION ACTIONS
# =========================================================

@dp.callback_query(
    F.data.startswith("accept:")
)
async def accept_callback(
    callback: CallbackQuery,
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
        ":",
        1,
    )[1]

    application = data[
        "applications"
    ].get(
        app_id
    )

    if not application:
        await callback.answer(
            "❌ Заявка не найдена.",
            show_alert=True,
        )
        return

    if application.get(
        "status"
    ) != "pending":
        await callback.answer(
            "ℹ️ Заявка уже обработана.",
            show_alert=True,
        )
        return

    application[
        "status"
    ] = "accepted"

    application.setdefault(
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

    user_id = int(
        application[
            "user_id"
        ]
    )

    try:
        invite = await bot.create_chat_invite_link(
            GROUP_ID,
            member_limit=1,
        )

        await bot.send_message(
            user_id,
            (
                "✅ <b>Ваша заявка принята!</b>\n\n"
                f"🔗 Ссылка для вступления:\n"
                f"{invite.invite_link}"
            ),
        )

    except Exception:
        try:
            await bot.send_message(
                user_id,
                (
                    "✅ <b>Ваша заявка принята!</b>\n\n"
                    f"{GROUP_LINK}"
                ),
            )
        except Exception:
            pass

    try:
        await bot.set_chat_member_custom_title(
            chat_id=GROUP_ID,
            user_id=user_id,
            custom_title=application[
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
        "✅ Принято"
    )


@dp.callback_query(
    F.data.startswith("reject:")
)
async def reject_callback(
    callback: CallbackQuery,
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
        ":",
        1,
    )[1]

    application = data[
        "applications"
    ].get(
        app_id
    )

    if not application:
        await callback.answer(
            "❌ Заявка не найдена.",
            show_alert=True,
        )
        return

    if application.get(
        "status"
    ) != "pending":
        await callback.answer(
            "ℹ️ Заявка уже обработана.",
            show_alert=True,
        )
        return

    application[
        "status"
    ] = "rejected"

    application.setdefault(
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

    try:
        await bot.send_message(
            application["user_id"],
            "❌ Ваша заявка отклонена.",
        )
    except Exception:
        pass

    await log_action(
        callback.from_user.id,
        "отклонил заявку",
        app_id,
    )

    await callback.message.edit_reply_markup(
        reply_markup=None
    )

    await callback.answer(
        "❌ Отклонено"
    )


# =========================================================
# APPLICATION MENUS
# =========================================================

@dp.message(
    F.text == "📋 Управление заявками"
)
async def all_applications(
    message: Message,
):
    if not is_admin(
        message.from_user.id
    ):
        await message.answer(
            "❌ Нет прав."
        )
        return

    applications = data[
        "applications"
    ]

    if not applications:
        await message.answer(
            "📭 Заявок нет."
        )
        return

    for app_id, application in applications.items():
        status = application.get(
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

        u = application[
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
                            text="✅ Принять",
                            callback_data=f"accept:{app_id}",
                        ),
                        InlineKeyboardButton(
                            text="❌ Отклонить",
                            callback_data=f"reject:{app_id}",
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
async def pending_applications_handler(
    message: Message,
):
    if not is_admin(
        message.from_user.id
    ):
        await message.answer(
            "❌ Нет прав."
        )
        return

    found = False

    for app_id, application in data[
        "applications"
    ].items():

        if application.get(
            "status"
        ) != "pending":
            continue

        found = True

        u = application[
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
                            callback_data=f"accept:{app_id}",
                        ),
                        InlineKeyboardButton(
                            text="❌ Отклонить",
                            callback_data=f"reject:{app_id}",
                        ),
                    ]
                ]
            ),
        )

    if not found:
        await message.answer(
            "📭 Активных заявок нет."
        )


# =========================================================
# PARTICIPANTS
# =========================================================

@dp.message(
    F.text == "👥 Список участников"
)
async def participants_handler(
    message: Message,
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
        "👥 <b>Список участников</b>\n\n"
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
            f"{escape(user.get('organization', '—'))}\n\n"
        )

        counter += 1

    if len(text) > 3900:
        text = text[:3900] + "\n..."

    await message.answer(
        text
    )


# =========================================================
# PROFILE
# =========================================================

@dp.message(
    F.text == "👤 Мой профиль"
)
async def profile_handler(
    message: Message,
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
            "ℹ️ У вас ещё нет анкеты."
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
# STATUS
# =========================================================

@dp.message(
    F.text == "🟢 Статус бота"
)
async def status_handler(
    message: Message,
):
    if not is_admin(
        message.from_user.id
    ):
        await message.answer(
            "❌ Нет прав."
        )
        return

    total = len(
        data["users"]
    )

    pending = sum(
        1
        for app in data[
            "applications"
        ].values()
        if app.get(
            "status"
        ) == "pending"
    )

    accepted = sum(
        1
        for app in data[
            "applications"
        ].values()
        if app.get(
            "status"
        ) == "accepted"
    )

    rejected = sum(
        1
        for app in data[
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
            "🟢 <b>Статус бота</b>\n\n"
            f"👥 Участников: {total}\n"
            f"⏳ Активных: {pending}\n"
            f"✅ Принято: {accepted}\n"
            f"❌ Отклонено: {rejected}\n"
            f"⏱ Аптайм: {uptime}"
        )
    )


# =========================================================
# WHO
# =========================================================

@dp.message(
    Command("кто")
)
async def who_handler(
    message: Message,
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
            "❌ Используйте /кто ответом "
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
            "❌ Анкета не найдена."
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
# RESOLVE USERNAME
# =========================================================

async def resolve_username(
    username,
):
    username = normalize_username(
        username
    )

    if not username:
        return None

    # Сначала ищем среди уже известных админов.
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
                    "name": info.get(
                        "full_name",
                        username,
                    ),
                }
            except Exception:
                pass

    # Затем ищем среди уже известных участников.
    for raw_id, user in data[
        "users"
    ].items():

        saved_tag = normalize_username(
            user.get("tag")
        )

        if saved_tag == username:
            try:
                return {
                    "id": int(raw_id),
                    "username": username,
                    "name": user.get(
                        "nickname",
                        username,
                    ),
                }
            except Exception:
                pass

    # Затем среди замов.
    for nick, info in data[
        "zam_data"
    ].items():

        saved = normalize_username(
            info.get(
                "tg_username"
            )
        )

        user_id = info.get(
            "tg_user_id"
        )

        if (
            saved == username
            and user_id
        ):
            return {
                "id": int(user_id),
                "username": username,
                "name": nick,
            }

    # И последний вариант — Bot API.
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
            "name": (
                chat.full_name
                or username
            ),
        }

    except Exception as e:
        print(
            f"Не удалось получить @{username}: {e}"
        )
        return None


# =========================================================
# ADD ADMIN
# =========================================================

@dp.message(
    Command("add_admin")
)
async def add_admin_handler(
    message: Message,
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

    username = normalize_username(
        parts[1]
    )

    if not username:
        await message.answer(
            "❌ Неверный username."
        )
        return

    if username == normalize_username(
        "6166697485"
    ):
        await message.answer(
            "ℹ️ Ты уже владелец."
        )
        return

    selected = await resolve_username(
        username
    )

    if selected:
        user_id = selected["id"]

        if user_id == SUPER_ADMIN:
            await message.answer(
                "ℹ️ Это владелец."
            )
            return

        admins = get_admins()

        if user_id in admins:
            await message.answer(
                "❌ Этот пользователь уже админ."
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
                "name",
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
            "добавил админа",
            f"@{username}",
        )

        try:
            await bot.send_message(
                user_id,
                "👑 Вы назначены администратором!",
            )
        except Exception:
            pass

        await set_commands()

        return

    # Если Bot API не может получить ID,
    # запоминаем username.
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
            f"✅ <b>@{escape(username)}</b> "
            "добавлен в список ожидающих.\n\n"
            "Telegram пока не дал боту ID этого пользователя. "
            "Когда пользователь напишет боту, "
            "его ID будет привязан автоматически."
        )
    )

    await log_action(
        message.from_user.id,
        "добавил админа по username",
        f"@{username}",
    )


# =========================================================
# REMOVE ADMIN
# =========================================================

@dp.message(
    Command("remove_admin")
)
async def remove_admin_handler(
    message: Message,
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

    username = normalize_username(
        parts[1]
    )

    selected = await resolve_username(
        username
    )

    if selected:
        user_id = selected[
            "id"
        ]

        if user_id == SUPER_ADMIN:
            await message.answer(
                "❌ Нельзя удалить владельца."
            )
            return

        admins = get_admins()

        if user_id not in admins:
            await message.answer(
                "❌ Пользователь не является админом."
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
            "удалил админа",
            f"@{username}",
        )

        await set_commands()

        return

    # Убираем из ожидающих.
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
            f"✅ Назначение "
            f"<b>@{escape(username)}</b> "
            "отменено."
        )
    )


# =========================================================
# ADD ZAM
# =========================================================

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
            "❌ Неверный username."
        )
        return

    if not game_nick:
        await message.answer(
            "❌ Нужен игровой ник."
        )
        return

    if game_nick in data[
        "zam_data"
    ]:
        await message.answer(
            "❌ Такой игровой ник уже существует."
        )
        return

    selected = await resolve_username(
        username
    )

    user_id = None

    if selected:
        user_id = selected[
            "id"
        ]

    for nick, info in data[
        "zam_data"
    ].items():

        if (
            user_id
            and info.get(
                "tg_user_id"
            )
            == user_id
        ):
            await message.answer(
                (
                    "❌ Этот Telegram-пользователь "
                    f"уже зам: <b>{escape(nick)}</b>."
                )
            )
            return

    data[
        "zam_data"
    ][
        game_nick
    ] = {
        "tg_user_id": user_id,
        "tg_username": username,
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

    await message.answer(
        (
            f"✅ Зам <b>{escape(game_nick)}</b> "
            f"назначен.\n"
            f"👤 Telegram: "
            f"@{escape(username)}"
        )
    )

    await log_action(
        message.from_user.id,
        "добавил зама",
        f"{game_nick} / @{username}",
    )

    if user_id:
        try:
            await bot.send_message(
                user_id,
                (
                    "👑 Вы назначены замом!\n\n"
                    f"Игровой ник: "
                    f"<b>{escape(game_nick)}</b>"
                ),
            )
        except Exception:
            pass


@dp.message(
    Command("add_zam")
)
async def add_zam_handler(
    message: Message,
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

    if len(parts) < 3:
        await message.answer(
            (
                "❌ Формат:\n"
                "<code>/add_zam @username Game_Nick</code>\n\n"
                "или:\n"
                "<code>/add_zam Game_Nick: @username</code>"
            )
        )
        return

    # /add_zam Game_Nick: @username
    if ":" in parts[1]:
        game_nick = (
            parts[1]
            .rstrip(":")
            .strip()
        )

        username = parts[2]

        await add_zam_by_username(
            message,
            username,
            game_nick,
        )

        return

    # /add_zam @username Game_Nick
    username = parts[1]

    game_nick = " ".join(
        parts[2:]
    )

    await add_zam_by_username(
        message,
        username,
        game_nick,
    )


# =========================================================
# REMOVE ZAM
# =========================================================

@dp.message(
    Command("remove_zam")
)
async def remove_zam_handler(
    message: Message,
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

    if len(parts) != 2:
        await message.answer(
            (
                "❌ Формат:\n"
                "<code>/remove_zam Game_Nick</code>"
            )
        )
        return

    nick = parts[1].strip()

    if nick not in data[
        "zam_data"
    ]:
        await message.answer(
            "❌ Такой зам не найден."
        )
        return

    data[
        "zam_data"
    ].pop(
        nick,
        None,
    )

    data[
        "zam_stats"
    ].pop(
        nick,
        None,
    )

    save_data()

    await message.answer(
        (
            f"✅ Зам <b>{escape(nick)}</b> "
            "удалён."
        )
    )

    await log_action(
        message.from_user.id,
        "удалил зама",
        nick,
    )


# =========================================================
# ADD / REMOVE ALIASES
# =========================================================

@dp.message(
    Command("add")
)
async def add_alias(
    message: Message,
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
                "Использование:\n"
                "<code>/add admin @username</code>\n"
                "<code>/add zam @username Game_Nick</code>"
            )
        )
        return

    mode = parts[1].lower()

    if mode == "admin":
        if len(parts) != 3:
            await message.answer(
                "<code>/add admin @username</code>"
            )
            return

        # Повторяем логику напрямую.
        username = parts[2]

        fake_text = (
            f"/add_admin {username}"
        )

        # Найдём username и вызовем helper.
        selected = await resolve_username(
            username
        )

        if selected:
            user_id = selected[
                "id"
            ]

            if user_id == SUPER_ADMIN:
                await message.answer(
                    "ℹ️ Это владелец."
                )
                return

            admins = get_admins()

            if user_id in admins:
                await message.answer(
                    "❌ Уже админ."
                )
                return

            admins.add(
                user_id
            )
            save_admins(
                admins
            )

            normalized = normalize_username(
                username
            )

            data[
                "admin_usernames"
            ][
                str(user_id)
            ] = {
                "username": normalized,
                "full_name": selected.get(
                    "name",
                    normalized,
                ),
            }

            save_data()

            await message.answer(
                (
                    f"✅ <b>@{escape(normalized)}</b> "
                    "назначен администратором."
                )
            )

            await log_action(
                message.from_user.id,
                "добавил админа",
                f"@{normalized}",
            )

            await set_commands()

        else:
            normalized = normalize_username(
                username
            )

            pending = {
                normalize_username(x)
                for x in data.get(
                    "pending_admin_usernames",
                    [],
                )
            }

            pending.add(
                normalized
            )

            data[
                "pending_admin_usernames"
            ] = sorted(
                pending
            )

            save_data()

            await message.answer(
                (
                    f"✅ @{escape(normalized)} "
                    "записан как ожидающий админ."
                )
            )

        return

    if mode == "zam":
        if len(parts) < 4:
            await message.answer(
                (
                    "<code>/add zam "
                    "@username Game_Nick</code>"
                )
            )
            return

        await add_zam_by_username(
            message,
            parts[2],
            " ".join(parts[3:]),
        )
        return

    await message.answer(
        "❌ Неизвестный тип."
    )


@dp.message(
    Command("remove")
)
async def remove_alias(
    message: Message,
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
                "Использование:\n"
                "<code>/remove admin @username</code>\n"
                "<code>/remove zam Game_Nick</code>"
            )
        )
        return

    mode = parts[1].lower()

    if mode == "admin":
        username = normalize_username(
            parts[2]
        )

        selected = await resolve_username(
            username
        )

        if not selected:
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
                f"✅ @{escape(username)} удалён из ожидающих."
            )
            return

        user_id = selected[
            "id"
        ]

        if user_id == SUPER_ADMIN:
            await message.answer(
                "❌ Нельзя удалить владельца."
            )
            return

        admins = get_admins()

        if user_id not in admins:
            await message.answer(
                "❌ Это не админ."
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
                f"@{escape(username)}."
            )
        )

        await log_action(
            message.from_user.id,
            "удалил админа",
            f"@{username}",
        )

        await set_commands()
        return

    if mode == "zam":
        nick = parts[2]

        if nick not in data[
            "zam_data"
        ]:
            await message.answer(
                "❌ Зам не найден."
            )
            return

        data[
            "zam_data"
        ].pop(
            nick,
            None,
        )

        data[
            "zam_stats"
        ].pop(
            nick,
            None,
        )

        save_data()

        await message.answer(
            (
                f"✅ Зам <b>{escape(nick)}</b> "
                "удалён."
            )
        )

        await log_action(
            message.from_user.id,
            "удалил зама",
            nick,
        )

        return

    await message.answer(
        "❌ Неизвестный тип."
    )


# =========================================================
# ADMINS PANEL
# =========================================================

@dp.message(
    F.text == "🛠 Админка"
)
async def admin_panel(
    message: Message,
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
            "➕ Добавить:\n"
            "<code>/add_admin @username</code>\n\n"
            "➖ Удалить:\n"
            "<code>/remove_admin @username</code>\n\n"
            "Также доступны:\n"
            "<code>/add admin @username</code>\n"
            "<code>/remove admin @username</code>"
        ),
        reply_markup=admin_panel_keyboard(),
    )


@dp.callback_query(
    F.data == "adm_add"
)
async def admin_panel_add(
    callback: CallbackQuery,
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
            "➕ Введите:\n"
            "<code>/add_admin @username</code>"
        )
    )

    await callback.answer()


@dp.callback_query(
    F.data == "adm_remove"
)
async def admin_panel_remove(
    callback: CallbackQuery,
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
            "➖ Введите:\n"
            "<code>/remove_admin @username</code>"
        )
    )

    await callback.answer()


@dp.callback_query(
    F.data == "adm_list"
)
async def admin_panel_list(
    callback: CallbackQuery,
):
    if not is_super_admin(
        callback.from_user.id
    ):
        await callback.answer(
            "❌ Только владелец!",
            show_alert=True,
        )
        return

    text = (
        "👑 <b>Администраторы</b>\n\n"
    )

    for admin_id in sorted(
        get_admins()
    ):
        if admin_id == SUPER_ADMIN:
            role = "👑 Владелец"
        else:
            role = "🛡 Админ"

        text += (
            f"• {escape(get_admin_display(admin_id))}"
            f" — {role}\n"
        )

    pending = data.get(
        "pending_admin_usernames",
        [],
    )

    if pending:
        text += (
            "\n🕓 <b>Ожидают первого "
            "контакта:</b>\n"
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
async def zams_panel_handler(
    message: Message,
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
    message: Message,
):
    zams = data[
        "zam_data"
    ]

    text = (
        "👑 <b>Замы</b>\n\n"
    )

    if not zams:
        text += "📭 Замов нет."

    else:
        for nick, info in zams.items():
            invited = count_zam_invites(
                nick
            )

            withdrawn = get_zam_withdrawn(
                nick
            )

            available = max(
                0,
                invited - withdrawn,
            )

            username = normalize_username(
                info.get(
                    "tg_username"
                )
            )

            tg_text = (
                f" — @{escape(username)}"
                if username
                else ""
            )

            text += (
                f"👤 <b>{escape(nick)}</b>"
                f"{tg_text}\n"
                f"   📋 Анкет: {invited}\n"
                f"   💸 Выведено: {withdrawn}\n"
                f"   🟢 Доступно: {available}\n\n"
            )

    await message.answer(
        text,
        reply_markup=zam_panel_keyboard(),
    )


@dp.callback_query(
    F.data == "zam_add"
)
async def zam_add_button(
    callback: CallbackQuery,
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
    F.data == "zam_remove"
)
async def zam_remove_button(
    callback: CallbackQuery,
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
    F.data == "zam_stats"
)
async def zam_stats_button(
    callback: CallbackQuery,
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


# =========================================================
# ZAM STATISTICS
# =========================================================

def count_zam_invites(
    nick,
):
    result = 0

    for user in data[
        "users"
    ].values():
        if user.get(
            "inviter"
        ) == nick:
            result += 1

    return result


def get_zam_withdrawn(
    nick,
):
    stat = data[
        "zam_stats"
    ].get(
        nick,
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
    nick,
):
    return max(
        0,
        count_zam_invites(
            nick
        )
        - get_zam_withdrawn(
            nick
        ),
    )


async def send_zam_stats(
    message: Message,
):
    if not data[
        "zam_data"
    ]:
        await message.answer(
            "📭 Замов нет."
        )
        return

    text = (
        "📊 <b>Статистика замов</b>\n\n"
    )

    for nick in data[
        "zam_data"
    ]:

        invited = count_zam_invites(
            nick
        )

        withdrawn = get_zam_withdrawn(
            nick
        )

        available = get_zam_available(
            nick
        )

        text += (
            f"👤 <b>{escape(nick)}</b>\n"
            f"📋 Приглашено: {invited}\n"
            f"💸 Выведено: {withdrawn}\n"
            f"🟢 Доступно: {available}\n\n"
        )

    await message.answer(
        text
    )


# =========================================================
# WITHDRAW
# =========================================================

@dp.message(
    Command("withdraw")
)
async def withdraw_handler(
    message: Message,
):
    if not is_super_admin(
        message.from_user.id
    ):
        await message.answer(
            "❌ Только владелец."
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

        if (
            normalize_username(
                info.get(
                    "tg_username"
                )
            )
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

    user_id = data[
        "zam_data"
    ][
        game_nick
    ].get(
        "tg_user_id"
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

    await message.answer(
        (
            f"✅ Вывод оформлен.\n"
            f"👤 {escape(game_nick)}\n"
            f"💰 {amount}k\n"
            f"🟢 Осталось: "
            f"{get_zam_available(game_nick)}"
        )
    )

    await log_action(
        message.from_user.id,
        "вывод",
        f"{game_nick}: {amount}k",
    )


# =========================================================
# LOGS
# =========================================================

@dp.message(
    F.text == "📜 Журнал действий"
)
async def logs_button(
    message: Message,
):
    await logs_handler(
        message
    )


@dp.message(
    Command("logs")
)
async def logs_handler(
    message: Message,
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
            text = f.read()

    except Exception:
        text = ""

    if not text:
        await message.answer(
            "📭 Журнал пуст."
        )
        return

    if len(text) > 3800:
        text = text[
            -3800:
        ]

    await message.answer(
        (
            "📜 <b>Журнал действий</b>\n\n"
            f"<pre>{escape(text)}</pre>"
        )
    )


@dp.message(
    Command("clearlogs")
)
async def clear_logs(
    message: Message,
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
        "✅ Журнал очищен."
    )


@dp.message(
    Command("log_on")
)
async def log_on(
    message: Message,
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
        "✅ Уведомления включены."
    )


@dp.message(
    Command("log_off")
)
async def log_off(
    message: Message,
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
        "❌ Уведомления выключены."
    )


# =========================================================
# PING
# =========================================================

@dp.message(
    Command("ping")
)
async def ping_handler(
    message: Message,
):
    if not is_admin(
        message.from_user.id
    ):
        await message.answer(
            "❌ Только админы."
        )
        return

    start = datetime.now()

    msg = await message.answer(
        "🏓 Проверяю..."
    )

    ms = (
        datetime.now()
        - start
    ).total_seconds() * 1000

    uptime = (
        datetime.now()
        - BOT_START_TIME
    )

    await msg.edit_text(
        (
            f"🏓 <b>Понг!</b>\n"
            f"📡 {ms:.1f} мс\n"
            f"⏱ Аптайм: {uptime}"
        )
    )


# =========================================================
# MY ID
# =========================================================

@dp.message(
    Command("myid")
)
async def myid_handler(
    message: Message,
):
    await message.answer(
        (
            f"🆔 Твой ID:\n"
            f"<code>{message.from_user.id}</code>\n\n"
            f"👑 ID владельца:\n"
            f"<code>{SUPER_ADMIN}</code>"
        )
    )


# =========================================================
# ALL
# =========================================================

@dp.message(
    Command("all")
)
async def all_handler(
    message: Message,
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
            "❌ Формат: /all текст"
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
async def topic_id_handler(
    message: Message,
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
            "❌ Команду нужно использовать внутри темы."
        )


# =========================================================
# ADMINS
# =========================================================

@dp.message(
    Command("admins")
)
async def admins_handler(
    message: Message,
):
    if not is_super_admin(
        message.from_user.id
    ):
        await message.answer(
            "❌ Только владелец."
        )
        return

    text = (
        "👑 <b>Администраторы</b>\n\n"
    )

    for admin_id in sorted(
        get_admins()
    ):
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

    await message.answer(
        text
    )


# =========================================================
# HELP
# =========================================================

@dp.message(
    Command("help")
)
async def help_handler(
    message: Message,
):
    if is_super_admin(
        message.from_user.id
    ):
        text = (
            "📖 <b>Команды владельца</b>\n\n"

            "/start — меню\n"
            "/help — помощь\n"
            "/myid — мой ID\n"
            "/ping — проверка\n\n"

            "<b>Админы</b>\n"
            "/add_admin @username\n"
            "/remove_admin @username\n"
            "/admins\n\n"

            "<b>Замы</b>\n"
            "/add_zam @username Game_Nick\n"
            "/remove_zam Game_Nick\n"
            "/zam_stats\n"
            "/withdraw @username сумма\n\n"

            "<b>Алиасы</b>\n"
            "/add admin @username\n"
            "/remove admin @username\n"
            "/add zam @username Game_Nick\n"
            "/remove zam Game_Nick\n\n"

            "<b>Прочее</b>\n"
            "/all текст\n"
            "/logs\n"
            "/clearlogs\n"
            "/log_on\n"
            "/log_off\n"
            "/topic_id\n"
            "/кто"
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
    *DEFAULT_COMMANDS,
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
        description="👤 Информация",
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
        description="🔔 Логи вкл",
    ),
    BotCommand(
        command="log_off",
        description="🔕 Логи выкл",
    ),
]


async def set_commands():
    try:
        await bot.set_my_commands(
            DEFAULT_COMMANDS,
            scope=BotCommandScopeDefault(),
        )
    except Exception as e:
        print(
            f"⚠️ Default commands: {e}"
        )

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
    except Exception as e:
        print(
            f"⚠️ Owner commands: {e}"
        )


# =========================================================
# DUPLICATE BOT PROTECTION
# =========================================================

async def prepare_bot():
    try:
        await bot.delete_webhook(
            drop_pending_updates=True
        )
    except Exception as e:
        print(
            f"⚠️ delete_webhook: {e}"
        )


# =========================================================
# START
# =========================================================

async def main():
    print(
        "🤖 Бот запускается..."
    )

    print(
        f"👑 Владелец: {SUPER_ADMIN}"
    )

    print(
        f"👥 Админов: {len(get_admins())}"
    )

    print(
        f"👑 Замов: {len(data['zam_data'])}"
    )

    await prepare_bot()

    await set_commands()

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
