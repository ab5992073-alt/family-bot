import asyncio
import json
import os
import threading
from datetime import datetime
from html import escape

from flask import Flask

from aiogram import BaseMiddleware, Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
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
# CONFIGURATION
# =========================================================

TOKEN = os.environ.get(
    "BOT_TOKEN",
    "",
).strip()

if not TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не найден. "
        "Добавь BOT_TOKEN в Render Environment."
    )


# ТВОЙ TELEGRAM ID
SUPER_ADMIN = 6166697485


# Существующие админы
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


# =========================================================
# BOT / DISPATCHER
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


def get_default_data():
    return {
        "users": {},
        "applications": {},
        "admins": list(ADMIN_IDS),
        "admin_usernames": {},
        "pending_admin_usernames": [],
        "zam_data": {},
        "zam_stats": {},
        "log_notify_enabled": False,
        "initial_zams_installed": False,
    }


def load_data():
    if not os.path.exists(DATA_FILE):
        return get_default_data()

    try:
        with open(
            DATA_FILE,
            "r",
            encoding="utf-8",
        ) as file:
            result = json.load(file)

        if isinstance(result, dict):
            return result

    except Exception as e:
        print(
            f"⚠️ Ошибка чтения data.json: {e}"
        )

    return get_default_data()


data = load_data()


def save_data():
    try:
        tmp = DATA_FILE + ".tmp"

        with open(
            tmp,
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=2,
            )

        os.replace(
            tmp,
            DATA_FILE,
        )

    except Exception as e:
        print(
            f"⚠️ Ошибка сохранения данных: {e}"
        )


# =========================================================
# MIGRATION
# =========================================================

changed = False

for key, value in get_default_data().items():
    if key not in data:
        data[key] = value
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
    data.get("admins"),
    list,
):
    data["admins"] = list(ADMIN_IDS)
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
    data.get("pending_admin_usernames"),
    list,
):
    data["pending_admin_usernames"] = []
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


# =========================================================
# INSTALL INITIAL ZAMS ONLY ONCE
# =========================================================

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
# ZAM MIGRATION
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
        continue

    if "tg_user_id" not in info:
        info["tg_user_id"] = None
        changed = True

    if "tg_username" not in info:
        info["tg_username"] = None
        changed = True


for nick in data["zam_data"]:
    if nick not in data["zam_stats"]:
        data["zam_stats"][nick] = {
            "count": 0,
            "withdrawn": 0,
            "history": [],
        }
        changed = True


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
    clean = set()

    for value in admins:
        try:
            clean.add(
                int(value)
            )
        except Exception:
            pass

    clean.add(
        SUPER_ADMIN
    )

    data["admins"] = sorted(
        clean
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
# AUTO-BIND PENDING ADMIN
# =========================================================

def auto_bind_pending_admin(
    message: Message,
):
    """
    Если владелец заранее добавил:
        /add_admin @username

    пользователь ещё не был известен боту.

    Когда пользователь пишет боту,
    его реальный Telegram ID автоматически
    привязывается к username.
    """

    user = message.from_user

    if not user:
        return False

    username = normalize_username(
        user.username
    )

    if not username:
        return False

    pending = {
        normalize_username(item)
        for item in data.get(
            "pending_admin_usernames",
            [],
        )
    }

    if username not in pending:
        return False

    admins = get_admins()

    already_admin = (
        user.id in admins
    )

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
        item
        for item in data.get(
            "pending_admin_usernames",
            [],
        )
        if normalize_username(item)
        != username
    ]

    save_data()

    print(
        f"✅ Автопривязка админа: "
        f"@{username} -> {user.id}"
    )

    return not already_admin


# =========================================================
# MESSAGE MIDDLEWARE
# =========================================================

class UserSyncMiddleware(
    BaseMiddleware
):
    async def __call__(
        self,
        handler,
        event,
        data_,
    ):
        if isinstance(
            event,
            Message,
        ):
            try:
                became_admin = (
                    auto_bind_pending_admin(
                        event
                    )
                )

                if became_admin:
                    try:
                        await event.answer(
                            "👑 Вы автоматически назначены администратором!"
                        )
                    except Exception:
                        pass

            except Exception as e:
                print(
                    f"⚠️ Ошибка автопривязки: {e}"
                )

        return await handler(
            event,
            data_,
        )


dp.message.outer_middleware(
    UserSyncMiddleware()
)


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
            username = (
                f"@{chat.username}"
            )
        elif chat.full_name:
            username = chat.full_name
        else:
            username = str(user_id)

    except Exception:
        username = str(user_id)

    timestamp = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    try:
        with open(
            LOG_FILE,
            "a",
            encoding="utf-8",
        ) as file:
            file.write(
                f"[{timestamp}] "
                f"{username} -> "
                f"{action} "
                f"{details}\n"
            )
    except Exception:
        pass

    if data.get(
        "log_notify_enabled"
    ):
        try:
            await bot.send_message(
                SUPER_ADMIN,
                (
                    f"👤 <b>{escape(str(username))}</b>\n"
                    f"➡️ {escape(str(action))}\n"
                    f"📝 {escape(str(details))}\n"
                    f"🕐 {timestamp}"
                ),
            )
        except Exception:
            pass


# =========================================================
# MAIN KEYBOARD
# =========================================================

def main_keyboard(
    has_survey=False,
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


# =========================================================
# ADMIN PANEL KEYBOARD
# =========================================================

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


# =========================================================
# ZAM PANEL KEYBOARD
# =========================================================

def zams_panel_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Добавить зама",
                    callback_data="zam_add",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="➖ Удалить зама",
                    callback_data="zam_remove",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📊 Статистика",
                    callback_data="zam_stats",
                ),
            ],
        ]
    )


# =========================================================
# START
# =========================================================

@dp.message(
    CommandStart()
)
async def start_command(
    message: Message,
):
    uid = message.from_user.id

    has_survey = (
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
                has_survey,
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
                has_survey,
            ),
        )

    await log_action(
        uid,
        "start",
    )


# =========================================================
# SURVEY STATE
# =========================================================

user_surveys = {}


async def start_survey(
    message: Message,
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
            "1️⃣ Ваш Nickname в игре?"
        )
    )


@dp.message(
    F.text == "📝 Заполнить анкету"
)
async def survey_start(
    message: Message,
):
    uid = message.from_user.id

    if str(uid) in data[
        "users"
    ]:
        await message.answer(
            (
                "ℹ️ Вы уже заполняли анкету.\n"
                "Используйте "
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
async def survey_reset(
    message: Message,
):
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

    data[
        "users"
    ].pop(
        uid,
        None,
    )

    for application in data[
        "applications"
    ].values():
        if (
            str(
                application.get(
                    "user_id"
                )
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

    await start_survey(
        message
    )


@dp.message(
    lambda message:
    message.from_user.id
    in user_surveys
)
async def survey_handler(
    message: Message,
):
    uid = message.from_user.id

    state = user_surveys[
        uid
    ]

    text = (
        message.text
        or ""
    ).strip()

    if not text:
        await message.answer(
            "❌ Введите текст."
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

        username = (
            message.from_user.username
        )

        state[
            "answers"
        ][
            "tag"
        ] = (
            f"@{username}"
            if username
            else str(uid)
        )

        state[
            "step"
        ] = 1

        rows = []

        for rank in RANK_LIST:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=rank,
                        callback_data=(
                            f"rank_{rank}"
                        ),
                    )
                ]
            )

        await message.answer(
            "👤 Ваш ранг в фаме:",
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
                            f"zam_{nick}"
                        ),
                    )
                ]
            )

        await message.answer(
            "👤 Кто вас пригласил?",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=rows
            ),
        )


# =========================================================
# RANK
# =========================================================

@dp.callback_query(
    F.data.startswith("rank_")
)
async def rank_selected(
    callback: CallbackQuery,
):
    uid = callback.from_user.id

    if uid not in user_surveys:
        await callback.answer(
            "❌ Анкета не найдена."
        )
        return

    rank = callback.data[
        5:
    ]

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
                        f"org_{org}"
                    ),
                )
            ]
        )

    await callback.message.answer(
        "🏢 Ваша организация:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=rows
        ),
    )

    await callback.answer()


# =========================================================
# ORGANIZATION
# =========================================================

@dp.callback_query(
    F.data.startswith("org_")
)
async def org_selected(
    callback: CallbackQuery,
):
    uid = callback.from_user.id

    if uid not in user_surveys:
        await callback.answer(
            "❌ Анкета не найдена."
        )
        return

    org = callback.data[
        4:
    ]

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
        "📌 Ваш ранг в организации?"
    )

    await callback.answer()


# =========================================================
# INVITER
# =========================================================

@dp.callback_query(
    F.data.startswith("zam_")
)
async def zam_selected(
    callback: CallbackQuery,
):
    uid = callback.from_user.id

    if uid not in user_surveys:
        await callback.answer(
            "❌ Анкета не найдена."
        )
        return

    nick = callback.data[
        4:
    ]

    if nick not in data[
        "zam_data"
    ]:
        await callback.answer(
            "❌ Такой зам не существует.",
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


# =========================================================
# FINISH SURVEY
# =========================================================

async def finish_survey(
    message: Message,
    uid: int,
):
    state = user_surveys.pop(
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

    application_text = (
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
                    callback_data=(
                        f"accept_{app_id}"
                    ),
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=(
                        f"reject_{app_id}"
                    ),
                ),
            ]
        ]
    )

    for admin_id in get_admins():
        try:
            await bot.send_message(
                admin_id,
                application_text,
                reply_markup=keyboard,
            )
        except Exception:
            pass


# =========================================================
# APPLICATION ACCEPT
# =========================================================

@dp.callback_query(
    F.data.startswith("accept_")
)
async def accept_application(
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

    app_id = callback.data[
        7:
    ]

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
            "ℹ️ Уже обработано.",
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


# =========================================================
# APPLICATION REJECT
# =========================================================

@dp.callback_query(
    F.data.startswith("reject_")
)
async def reject_application(
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

    app_id = callback.data[
        7:
    ]

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
            "ℹ️ Уже обработано.",
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
            application[
                "user_id"
            ],
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
# APPLICATION LIST
# =========================================================

@dp.message(
    F.text == "📋 Управление заявками"
)
async def applications_handler(
    message: Message,
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

    for app_id, application in data[
        "applications"
    ].items():

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
                            callback_data=(
                                f"accept_{app_id}"
                            ),
                        ),
                        InlineKeyboardButton(
                            text="❌ Отклонить",
                            callback_data=(
                                f"reject_{app_id}"
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
async def active_applications(
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
                            callback_data=(
                                f"accept_{app_id}"
                            ),
                        ),
                        InlineKeyboardButton(
                            text="❌ Отклонить",
                            callback_data=(
                                f"reject_{app_id}"
                            ),
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

    for index, (
        uid,
        user,
    ) in enumerate(
        users.items(),
        start=1,
    ):
        text += (
            f"<b>{index}.</b> "
            f"{escape(user.get('nickname', '—'))}\n"
            f"   Тег: "
            f"{escape(user.get('tag', uid))}\n"
            f"   Ранг: "
            f"{escape(user.get('rank_fam', '—'))}\n"
            f"   Орг: "
            f"{escape(user.get('organization', '—'))}\n\n"
        )

        if index >= 100:
            break

    await message.answer(
        text[:4000]
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
        for item in data[
            "applications"
        ].values()
        if item.get(
            "status"
        ) == "pending"
    )

    accepted = sum(
        1
        for item in data[
            "applications"
        ].values()
        if item.get(
            "status"
        ) == "accepted"
    )

    rejected = sum(
        1
        for item in data[
            "applications"
        ].values()
        if item.get(
            "status"
        ) == "rejected"
    )

    uptime = (
        datetime.now()
        - BOT_START_TIME
    )

    await message.answer(
        (
            "🟢 <b>Статус</b>\n\n"
            f"👥 Участников: {total}\n"
            f"⏳ Активных заявок: {pending}\n"
            f"✅ Принято: {accepted}\n"
            f"❌ Отклонено: {rejected}\n"
            f"⏱ Аптайм: {uptime}"
        )
    )


# =========================================================
# /KTO AND /КТО
# =========================================================

@dp.message(
    Command("kto")
)
async def kto_command(
    message: Message,
):
    await show_user_info(
        message
    )


@dp.message(
    Command("кто")
)
async def kto_command_ru(
    message: Message,
):
    await show_user_info(
        message
    )


async def show_user_info(
    message: Message,
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
        "команда /kto",
    )

    if not message.reply_to_message:
        await message.answer(
            (
                "❌ Ответьте командой "
                "<code>/kto</code> "
                "на сообщение участника."
            )
        )
        return

    target = (
        message.reply_to_message
        .from_user
    )

    if not target:
        await message.answer(
            "❌ Не удалось определить пользователя."
        )
        return

    uid = str(
        target.id
    )

    user = data[
        "users"
    ].get(
        uid
    )

    if not user:
        await message.answer(
            (
                "❌ У этого пользователя "
                "нет анкеты."
            )
        )
        return

    await message.answer(
        (
            "📋 <b>Анкета</b>\n\n"
            f"🆔 Telegram ID: "
            f"<code>{target.id}</code>\n"
            f"👤 Nickname: "
            f"{escape(user.get('nickname', '—'))}\n"
            f"🏷 Тег: "
            f"{escape(user.get('tag', '—'))}\n"
            f"⭐ Ранг: "
            f"{escape(user.get('rank_fam', '—'))}\n"
            f"🏢 Организация: "
            f"{escape(user.get('organization', '—'))}\n"
            f"📌 Ранг в орг: "
            f"{escape(user.get('rank_org', '—'))}\n"
            f"👑 Пригласитель: "
            f"{escape(user.get('inviter', '—'))}"
        )
    )


# =========================================================
# ADMIN PANEL
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
            "Добавить:\n"
            "<code>/add_admin @username</code>\n\n"
            "Удалить:\n"
            "<code>/remove_admin @username</code>\n\n"
            "Также:\n"
            "<code>/add admin @username</code>\n"
            "<code>/remove admin @username</code>"
        ),
        reply_markup=admin_panel_keyboard(),
    )


@dp.callback_query(
    F.data == "adm_add"
)
async def adm_add(
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
            "➕ Введи:\n"
            "<code>/add_admin @username</code>"
        )
    )

    await callback.answer()


@dp.callback_query(
    F.data == "adm_remove"
)
async def adm_remove(
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
            "➖ Введи:\n"
            "<code>/remove_admin @username</code>"
        )
    )

    await callback.answer()


@dp.callback_query(
    F.data == "adm_list"
)
async def adm_list(
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
        role = (
            "👑 Владелец"
            if admin_id == SUPER_ADMIN
            else "🛡 Админ"
        )

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
            "сообщения:</b>\n"
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
# USERNAME RESOLUTION
# =========================================================

async def resolve_username(
    username,
):
    username = normalize_username(
        username
    )

    if not username:
        return None

    # Уже известные админы
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
                    "name": (
                        info.get(
                            "full_name"
                        )
                        or username
                    ),
                }
            except Exception:
                pass

    # Уже известные замы
    for nick, info in data[
        "zam_data"
    ].items():

        saved = normalize_username(
            info.get("tg_username")
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

    # Уже известные пользователи бота
    for raw_id, info in data[
        "users"
    ].items():

        saved = normalize_username(
            info.get("tag")
        )

        if saved == username:
            try:
                return {
                    "id": int(raw_id),
                    "username": username,
                    "name": (
                        info.get(
                            "nickname"
                        )
                        or username
                    ),
                }
            except Exception:
                pass

    # Telegram Bot API
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
            f"⚠️ get_chat @{username}: {e}"
        )

    return None


# =========================================================
# ADD ADMIN
# =========================================================

async def add_admin_username(
    message: Message,
    username,
):
    username = normalize_username(
        username
    )

    if not username:
        await message.answer(
            "❌ Укажи username."
        )
        return

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
            "full_name": (
                selected.get(
                    "name"
                )
                or username
            ),
        }

        # Если он был ожидающим — удаляем.
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

    # Если ID невозможно получить сейчас,
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
            "добавлен в ожидающие.\n\n"
            "Когда этот пользователь "
            "напишет боту, его Telegram ID "
            "будет автоматически привязан "
            "и админка активируется."
        )
    )

    await log_action(
        message.from_user.id,
        "добавил админа по username",
        f"@{username}",
    )


@dp.message(
    Command("add_admin")
)
async def add_admin_command(
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

    await add_admin_username(
        message,
        parts[1],
    )


# =========================================================
# REMOVE ADMIN
# =========================================================

async def remove_admin_username(
    message: Message,
    username,
):
    username = normalize_username(
        username
    )

    if not username:
        await message.answer(
            "❌ Укажи username."
        )
        return

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
                "❌ Этот пользователь не админ."
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

    # Отменяем ожидающее назначение.
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


@dp.message(
    Command("remove_admin")
)
async def remove_admin_command(
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

    await remove_admin_username(
        message,
        parts[1],
    )


# =========================================================
# /ADD ALIAS
# =========================================================

@dp.message(
    Command("add")
)
async def add_command(
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

        await add_admin_username(
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
# /REMOVE ALIAS
# =========================================================

@dp.message(
    Command("remove")
)
async def remove_command(
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
                "❌ Формат:\n\n"
                "<code>/remove admin @username</code>\n"
                "<code>/remove zam Game_Nick</code>"
            )
        )
        return

    mode = parts[1].lower()

    if mode == "admin":
        await remove_admin_username(
            message,
            parts[2],
        )
        return

    if mode == "zam":
        await remove_zam_command_logic(
            message,
            parts[2],
        )
        return

    await message.answer(
        "❌ Используй admin или zam."
    )


# =========================================================
# ZAM MANAGEMENT
# =========================================================

def get_zam_nicknames():
    return list(
        data[
            "zam_data"
        ].keys()
    )


def count_zam_invites(
    nick,
):
    return sum(
        1
        for user in data[
            "users"
        ].values()
        if user.get(
            "inviter"
        ) == nick
    )


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


async def add_zam_by_username(
    message: Message,
    username,
    game_nick,
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

    if user_id:
        for nick, info in data[
            "zam_data"
        ].items():

            if info.get(
                "tg_user_id"
            ) == user_id:

                await message.answer(
                    (
                        "❌ Этот Telegram-пользователь "
                        f"уже зам: "
                        f"<b>{escape(nick)}</b>"
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

    if user_id:
        await message.answer(
            (
                f"✅ Зам <b>{escape(game_nick)}</b> "
                f"назначен.\n"
                f"👤 Telegram: "
                f"@{escape(username)}"
            )
        )

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

    else:
        await message.answer(
            (
                f"✅ Зам <b>{escape(game_nick)}</b> "
                f"назначен по username "
                f"<b>@{escape(username)}</b>.\n\n"
                "Telegram ID пока не известен боту."
            )
        )

    await log_action(
        message.from_user.id,
        "добавил зама",
        (
            f"{game_nick} / "
            f"@{username}"
        ),
    )


@dp.message(
    Command("add_zam")
)
async def add_zam_command(
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
                "<code>/add_zam @username Game_Nick</code>"
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


async def remove_zam_command_logic(
    message: Message,
    nick,
):
    nick = (
        nick
        or ""
    ).strip()

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


@dp.message(
    Command("remove_zam")
)
async def remove_zam_command(
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

    await remove_zam_command_logic(
        message,
        parts[1],
    )


# =========================================================
# ZAMS BUTTON
# =========================================================

@dp.message(
    F.text == "👑 Замы"
)
async def zams_button(
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

            available = get_zam_available(
                nick
            )

            username = normalize_username(
                info.get(
                    "tg_username"
                )
            )

            if username:
                tg_text = (
                    f" — @{escape(username)}"
                )
            else:
                tg_text = ""

            text += (
                f"👤 <b>{escape(nick)}</b>"
                f"{tg_text}\n"
                f"   📋 Анкет: {invited}\n"
                f"   💸 Выведено: {withdrawn}\n"
                f"   🟢 Доступно: {available}\n\n"
            )

    await message.answer(
        text,
        reply_markup=zams_panel_keyboard(),
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
# ZAM STATS
# =========================================================

async def send_zam_stats(
    message: Message,
):
    zams = data[
        "zam_data"
    ]

    if not zams:
        await message.answer(
            "📭 Замов нет."
        )
        return

    text = (
        "📊 <b>Статистика замов</b>\n\n"
    )

    for nick in zams:
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


@dp.message(
    Command("zam_stats")
)
async def zam_stats_command(
    message: Message,
):
    if not is_super_admin(
        message.from_user.id
    ):
        await message.answer(
            "❌ Только владелец."
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

    nick = None

    for zam_nick, info in data[
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
            nick = zam_nick
            break

    if not nick:
        await message.answer(
            "❌ Зам не найден."
        )
        return

    need = amount // 100

    available = get_zam_available(
        nick
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
        nick,
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
        nick
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
            f"👤 {escape(nick)}\n"
            f"💰 {amount}k\n"
            f"🟢 Осталось: "
            f"{get_zam_available(nick)}"
        )
    )

    await log_action(
        message.from_user.id,
        "вывод",
        f"{nick}: {amount}k",
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
    await logs_command(
        message
    )


@dp.message(
    Command("logs")
)
async def logs_command(
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
        ) as file:
            text = file.read()

    except Exception:
        text = ""

    if not text:
        await message.answer(
            "📭 Логи пустые."
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
async def clearlogs_command(
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
        ) as file:
            file.write("")
    except Exception:
        pass

    await message.answer(
        "✅ Логи очищены."
    )


@dp.message(
    Command("log_on")
)
async def log_on_command(
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
        "✅ Уведомления логов включены."
    )


@dp.message(
    Command("log_off")
)
async def log_off_command(
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
        "❌ Уведомления логов выключены."
    )


# =========================================================
# /ALL
# =========================================================

@dp.message(
    Command("all")
)
async def all_command(
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

    try:
        await bot.send_message(
            GROUP_ID,
            (
                "⚠️ <b>ВАЖНОЕ ОБЪЯВЛЕНИЕ</b>\n\n"
                f"{escape(parts[1])}\n\n"
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
            "❌ Используй команду внутри темы."
        )


# =========================================================
# GROUP TOPIC PROTECTION
# =========================================================

@dp.message(
    F.chat.id == GROUP_ID
)
async def protect_topic(
    message: Message,
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
# ADMINS
# =========================================================

@dp.message(
    Command("admins")
)
async def admins_command(
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
            "/admins — список\n\n"

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
            "/kto — информация по reply\n"
            "/кто — то же самое\n"
            "/all текст\n"
            "/logs\n"
            "/clearlogs\n"
            "/log_on\n"
            "/log_off\n"
            "/topic_id"
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
            "/kto\n"
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
# MY ID
# =========================================================

@dp.message(
    Command("myid")
)
async def myid_command(
    message: Message,
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
# PING
# =========================================================

@dp.message(
    Command("ping")
)
async def ping_command(
    message: Message,
):
    if not is_admin(
        message.from_user.id
    ):
        await message.answer(
            "❌ Только админы."
        )
        return

    started = datetime.now()

    msg = await message.answer(
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

    await msg.edit_text(
        (
            f"🏓 <b>Понг!</b>\n"
            f"📡 {elapsed:.1f} мс\n"
            f"⏱ Аптайм: {uptime}"
        )
    )


# =========================================================
# COMMANDS
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
        command="kto",
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
        description="👑 Админы",
    ),
    BotCommand(
        command="zam_stats",
        description="📊 Статистика",
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
            f"⚠️ Commands default: {e}"
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
            f"⚠️ Commands owner: {e}"
        )


# =========================================================
# STARTUP
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

    try:
        await bot.delete_webhook(
            drop_pending_updates=True
        )
    except Exception as e:
        print(
            f"⚠️ delete_webhook: {e}"
        )

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
