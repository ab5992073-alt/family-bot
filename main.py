import telebot
from telebot import types
import json
import os

# --- НАСТРОЙКИ ---
BOT_TOKEN = 'ВАШ_ТОКЕН_БОТА'  # Замените на токен
OWNER_ID = 123456789          # Замените на ваш ID

# --- ХРАНИЛИЩЕ ДАННЫХ (автосохранение в JSON) ---
DATA_FILE = 'data.json'

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'admins': [OWNER_ID], 'zams': {}, 'applications': []}

def save_data():
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

data = load_data()
admins = data['admins']
zams = data['zams'] # {"ID": {"nickname": "Вася", "bank": 100}}
applications = data['applications'] # [{"id": 1, "user": "@user", "invited_by": "@zam", "invited_nickname": "Vasull"}]

bot = telebot.TeleBot(BOT_TOKEN)

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_username(user_id):
    """Возвращает @username, или имя, если username нет"""
    try:
        user = bot.get_chat(user_id)
        if user.username:
            return f"@{user.username}"
        return user.first_name
    except:
        return f"ID {user_id}" # На всякий случай, если не удалось получить

def get_user_id(username):
    """Превращает @username в ID"""
    try:
        user = bot.get_chat(username)
        return user.id
    except:
        return None

def is_admin(user_id):
    return user_id in admins

# --- ГЛАВНОЕ МЕНЮ ---
@bot.message_handler(commands=['start'])
def start(message):
    if not is_admin(message.from_user.id) and message.from_user.id not in zams:
        bot.reply_to(message, "У вас нет доступа к этому боту.")
        return
    
    # Убрана кнопка "Админы"
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn1 = types.InlineKeyboardButton("Все заявки", callback_data="all_apps")
    btn2 = types.InlineKeyboardButton("Активные", callback_data="active")
    btn3 = types.InlineKeyboardButton("Статистика", callback_data="stats")
    btn4 = types.InlineKeyboardButton("История", callback_data="history")
    btn5 = types.InlineKeyboardButton("Статус бота", callback_data="status")
    btn6 = types.InlineKeyboardButton("Обновить", callback_data="refresh")
    btn7 = types.InlineKeyboardButton("Банк замов", callback_data="bank_zams") # Изменено с "Замы"
    btn8 = types.InlineKeyboardButton("Управление админами", callback_data="admins_menu")
    
    markup.add(btn1, btn2, btn3, btn4, btn5, btn6, btn7, btn8)
    bot.send_message(message.chat.id, "Главное меню:", reply_markup=markup)

# --- КОМАНДА /add_admin ---
@bot.message_handler(commands=['add_admin'])
def add_admin(message):
    if not is_admin(message.from_user.id):
        return
    
    try:
        parts = message.text.split()
        # Формат: /add_admin <adm|zam> @username [Nik: Ник] [сумма]
        if len(parts) < 3:
            bot.reply_to(message, "❌ Формат: /add_admin <adm|zam> @username [Nik: Ник] [сумма]\nПример: /add_admin zam @dark Nik: Vasull")
            return
        
        role = parts[1]
        target_username = parts[2]
        
        target_id = get_user_id(target_username)
        if not target_id:
            bot.reply_to(message, "❌ Пользователь не найден.")
            return
        
        username = get_username(target_id)
        
        if role == 'adm':
            if target_id not in admins:
                admins.append(target_id)
                save_data()
                bot.reply_to(message, f"✅ {username} теперь Админ!")
            else:
                bot.reply_to(message, f"{username} уже Админ.")
                
        elif role == 'zam':
            nickname = "Без ника"
            amount = 100 # Минимум 100 по умолчанию
            
            # Поиск ника (Nik:)
            if 'Nik:' in parts:
                idx = parts.index('Nik:')
                if idx + 1 < len(parts):
                    nickname = parts[idx + 1]
            
            # Поиск суммы (если последнее слово число)
            if parts[-1].isdigit():
                amount = int(parts[-1])
                if amount < 100:
                    bot.reply_to(message, "❌ Минимальная сумма для зама 100.")
                    return
            
            # Добавляем в Банк замов
            zams[target_id] = {"nickname": nickname, "bank": amount}
            save_data()
            bot.reply_to(message, f"✅ {username} добавлен в Банк замов!\nНик: {nickname}\nСумма: {amount}")
        else:
            bot.reply_to(message, "❌ Роль должна быть 'adm' или 'zam'.")
            
    except Exception as e:
        bot.reply_to(message, f"Ошибка: {e}")

# --- ОБРАБОТКА КНОПОК (CALLBACKS) ---
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    if call.data == "all_apps":
        show_all_apps(call)
    elif call.data == "bank_zams":
        show_bank_zams(call)
    elif call.data == "admins_menu":
        show_admin_panel(call)
    elif call.data == "refresh":
        bot.answer_callback_query(call.id, "Данные обновлены")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        start(call.message)

def show_all_apps(call):
    if not applications:
        bot.edit_message_text("📭 Заявок пока нет.", chat_id=call.message.chat.id, message_id=call.message.message_id)
        return
        
    text = "📋 Все заявки:\n\n"
    for app in applications:
        # Используем пронумерованный ID (1, 2, 3...)
        text += f"Анкета (id: {app['id']})\n"
        text += f"Игрок: {app['user']}\n"
        text += f"Пригласил: {app['invited_by']} (Ник: {app['invited_nickname']})\n"
        text += "--------------------\n"
        
    bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id)

def show_bank_zams(call):
    if not zams:
        bot.edit_message_text("Банк замов пуст.", chat_id=call.message.chat.id, message_id=call.message.message_id)
        return
        
    text = "🏦 Банк замов:\n"
    for user_id, info in zams.items():
        username = get_username(user_id)
        text += f"• {username} (Ник: {info['nickname']}) - Банк: {info['bank']}\n"
        
    bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id)

def show_admin_panel(call):
    if call.from_user.id not in admins:
        return
        
    text = "👑 Админы:\n"
    for uid in admins:
        text += f"• {get_username(uid)}\n"
    
    text += "\n🏦 Замы (не админы):\n"
    for uid, info in zams.items():
        text += f"• {get_username(uid)} (Ник: {info['nickname']})\n"
        
    bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id)


# --- ПРОЦЕСС АНКЕТЫ (Демонстрация работы "Кто пригласил") ---
user_states = {}

@bot.message_handler(commands=['anketa'])
def start_anketa(message):
    user_states[message.from_user.id] = "waiting_invited"
    bot.reply_to(message, "Введите @username того, кто вас пригласил (зам):")

@bot.message_handler(func=lambda message: user_states.get(message.from_user.id) == "waiting_invited")
def process_invited(message):
    invited_username = message.text
    if not invited_username.startswith('@'):
        invited_username = '@' + invited_username
    
    invited_user_id = get_user_id(invited_username)
    
    # Проверяем, есть ли этот пригласивший в базе замов
    if invited_user_id and invited_user_id in zams:
        invite_info = zams[invited_user_id]
        nickname = invite_info['nickname']
        
        # Создаем анкету с последовательным ID
        new_app = {
            "id": len(applications) + 1,
            "user": get_username(message.from_user.id),
            "invited_by": invited_username,
            "invited_nickname": nickname
        }
        applications.append(new_app)
        save_data()
        
        bot.reply_to(message, f"✅ Анкета создана!\nID: {new_app['id']}\nПригласивший: {invited_username}\nНик пригласившего: {nickname}")
        
        del user_states[message.from_user.id]
    else:
        bot.reply_to(message, "❌ Этот пользователь не найден в базе замов. Попробуйте еще раз.")

# --- ЗАПУСК БОТА ---
if __name__ == '__main__':
    print("Бот успешно запущен...")
    bot.infinity_polling()
