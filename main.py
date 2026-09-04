from flask import Flask
import threading
import os
import asyncio
import json
from datetime import datetime
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ===== ВЕБ-СЕРВЕР ДЛЯ RENDER =====
app = Flask(__name__)

@app.route('/')
def health():
    return "Bot is running!", 200

def run_web():
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web, daemon=True).start()

# ===== КОНФИГУРАЦИЯ =====
TOKEN = "8768874617:AAGXy_Jk5x4hv583or1tGeJy__YJlpoU7vA"
ADMIN_IDS = {6166697485, 123456789, 6863392923, 1980341141}
GROUP_ID = -1002409536359
GROUP_LINK = "https://t.me/+f_eKIP4gwcs0YTcy"
BOT_NAME = "@Staff_Grand_Bot"

bot = Bot(token=TOKEN, default=DefaultBotProperties())
dp = Dispatcher()

# ===== КЛАВИАТУРЫ =====
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📝 Подать заявку")],
        [KeyboardButton(text="ℹ️ О боте")]
    ],
    resize_keyboard=True
)

cancel_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="❌ Отмена")]],
    resize_keyboard=True
)

# ===== СОСТОЯНИЯ ПОЛЬЗОВАТЕЛЕЙ =====
user_data = {}

# ===== ОБРАБОТЧИКИ =====
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        f"👋 Привет! Я бот для подачи заявок в семью {BOT_NAME}\n\n"
        "Нажми «📝 Подать заявку», чтобы начать.",
        reply_markup=main_kb
    )

@dp.message(lambda msg: msg.text == "📝 Подать заявку")
async def start_application(message: Message):
    user_id = message.from_user.id
    user_data[user_id] = {"step": "name"}
    await message.answer(
        "Введите ваше Имя и Фамилию:",
        reply_markup=cancel_kb
    )

@dp.message(lambda msg: msg.text == "❌ Отмена")
async def cancel_app(message: Message):
    user_id = message.from_user.id
    user_data.pop(user_id, None)
    await message.answer(
        "❌ Действие отменено.",
        reply_markup=main_kb
    )

@dp.message(lambda msg: msg.text == "ℹ️ О боте")
async def about(message: Message):
    await message.answer(
        f"🤖 Бот для подачи заявок в семью {BOT_NAME}\n\n"
        "Проект создан для удобного сбора заявок от кандидатов."
    )

@dp.message()
async def handle_application(message: Message):
    user_id = message.from_user.id
    if user_id not in user_data:
        return
    
    step = user_data[user_id].get("step")
    text = message.text
    
    if text == "❌ Отмена":
        user_data.pop(user_id, None)
        await message.answer("❌ Отменено.", reply_markup=main_kb)
        return
    
    if step == "name":
        user_data[user_id]["name"] = text
        user_data[user_id]["step"] = "age"
        await message.answer("Введите ваш возраст:")
    
    elif step == "age":
        user_data[user_id]["age"] = text
        user_data[user_id]["step"] = "about"
        await message.answer("Расскажите немного о себе (опыт, навыки):")
    
    elif step == "about":
        user_data[user_id]["about"] = text
        data = user_data[user_id]
        
        # Формируем заявку
        application = (
            f"🆕 Новая заявка!\n\n"
            f"👤 Имя: {data.get('name')}\n"
            f"📅 Возраст: {data.get('age')}\n"
            f"📝 О себе: {data.get('about')}\n"
            f"🆔 ID: {user_id}\n"
            f"👤 Юзер: @{message.from_user.username or 'Нет'}"
        )
        
        # Отправляем в группу
        try:
            await bot.send_message(GROUP_ID, application)
            await message.answer(
                "✅ Заявка успешно отправлена! Мы свяжемся с вами.",
                reply_markup=main_kb
            )
        except Exception:
            await message.answer(
                "❌ Ошибка при отправке заявки. Попробуйте позже.",
                reply_markup=main_kb
            )
        
        user_data.pop(user_id, None)

# ===== ЗАПУСК =====
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
