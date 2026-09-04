from flask import Flask
import threading
import os
from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command
import asyncio

# ===== ВЕБ-СЕРВЕР ДЛЯ RENDER =====
app = Flask(__name__)

@app.route('/')
def health():
    return "OK", 200

def run_web():
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web, daemon=True).start()

# ===== ТВОЙ БОТ =====
TOKEN = "8768874617:AAGXy_Jk5x4hv583or1tGeJy__YJlpoU7vA"
bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def start(msg: Message):
    await msg.answer("✅ Бот работает!")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
