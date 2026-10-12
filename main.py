async def gather_stop_btn(message: Message):
    uid = message.from_user.id
    if not admin_can(uid, "gathering"):
        await message.answer(permission_denied_text("gathering"))
        return

    task = gather_tasks.get(uid)
    gather_active.discard(uid)
    if task and not task.done():
        task.cancel()
    await message.answer("🛑 <b>Общий сбор остановлен.</b>")


@dp.message(F.text == "📢 Общий сбор")
async def gather_btn(message: Message):
    await start_gather_from_button(message)


# Ежедневное напоминание тем, кого бот знает по группе, но у кого нет анкеты.
async def reminder_worker():
    while True:
        try:
            await asyncio.sleep(3600)
            if not data.setdefault("bot_settings",{}).get("reminders_enabled"): continue
            now=datetime.now()
            for uid,info in list(data.get("group_members",{}).items()):
                if str(uid) in data.get("users",{}): continue
                last=data.setdefault("last_reminders",{}).get(str(uid))
                if last:
                    try:
                        if (now-datetime.fromisoformat(last)).total_seconds()<86400: continue
                    except Exception: pass
                try:
                    await bot.send_message(int(uid),"📋 Напоминание: пожалуйста, перейдите в бота и заполните анкету.")
                    data["last_reminders"][str(uid)]=now.isoformat(); save_data()
                except Exception: pass
        except asyncio.CancelledError: return
        except Exception as e:
            print("reminder_worker:", e)
            await _send_error_report(e, "Фоновое напоминание анкет")

# =========================================================
# КОМАНДЫ TELEGRAM ПО РОЛЯМ
# =========================================================

DEFAULT_COMMANDS = [
    BotCommand(command="start", description="🏠 Меню"),
    BotCommand(command="help", description="📖 Справка"),
    BotCommand(command="myid", description="🆔 Мой Telegram ID"),
]

ADMIN_COMMANDS = [
    BotCommand(command="start", description="🏠 Меню"),
    BotCommand(command="help", description="📖 Справка"),
    BotCommand(command="ping", description="🏓 Реальный пинг"),
]

OWNER_COMMANDS = ADMIN_COMMANDS + [
    BotCommand(command="ahelp", description="👑 Все команды владельца"),
    BotCommand(command="ping", description="🏓 Реальный пинг"),
]

async def set_command_scopes():
    # Все основные действия остаются в кнопках; команды — только резерв.
    try:
        await bot.set_my_commands(DEFAULT_COMMANDS, scope=BotCommandScopeDefault())
    except Exception as e:
        print(f"⚠️ Не удалось установить базовые команды: {e}")
    for admin_id in get_admins():
        try:
            await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=int(admin_id)))
        except Exception as e:
            print(f"⚠️ Не удалось установить команды для {admin_id}: {e}")
    try:
        await bot.set_my_commands(OWNER_COMMANDS, scope=BotCommandScopeChat(chat_id=SUPER_ADMIN))
    except Exception as e:
        print(f"⚠️ Не удалось установить команды владельца: {e}")

async def main():
    print("🤖 Бот запускается...")

    try:
        asyncio.get_running_loop().set_exception_handler(_asyncio_error_handler)
    except Exception as e:
        print("⚠️ Не удалось установить обработчик asyncio:", repr(e))

    if not DATABASE_URL:
        raise RuntimeError(
            "❌ DATABASE_URL не задан. Добавь URL Supabase в Render Environment. "
            "Бот намеренно не запускается без постоянной базы, чтобы не потерять данные."
        )

    if not _db_init():
        raise RuntimeError(
            "❌ Не удалось подключиться к постоянной PostgreSQL базе. "
            "Проверь DATABASE_URL в Render Environment."
        )

    print("✅ Постоянная база PostgreSQL подключена. Локальный data.json больше не является источником истины.")

    await init_telegram_user_client()
    await init_admins()
    ensure_admin_permissions()
    await set_command_scopes()

    await bot.delete_webhook(drop_pending_updates=True)

    print("🤖 Бот запущен!")
    print("📌 Основная группа:", GROUP_LINK)

    asyncio.create_task(reminder_worker())
    asyncio.create_task(scheduled_reminder_worker())
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Бот остановлен.")
    except Exception as e:
        print("❌ Критическая ошибка запуска:", repr(e))
        try:
            asyncio.run(_send_error_report(e, "Критическая ошибка запуска"))
        except Exception as report_exc:
            print("❌ Не удалось отправить отчёт:", repr(report_exc))
