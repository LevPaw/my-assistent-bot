#!/usr/bin/env python3
"""
AI Personal Assistant + Колесо Фортуны (Gemini — БЕСПЛАТНО)
pip install python-telegram-bot google-generativeai apscheduler
"""

import logging, sqlite3, random, asyncio, os
from datetime import datetime, timedelta
import google.generativeai as genai
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# Ключи берутся из переменных окружения (Railway) или вписаны напрямую
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "СЮДА_ВСТАВЬ_ТОКЕН_ОТ_BOTFATHER")
GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY",  "СЮДА_ВСТАВЬ_КЛЮЧ_ОТ_GEMINI")

# ─────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
genai.configure(api_key=GEMINI_API_KEY)

# ──────────────── База данных ────────────────
def init_db():
    conn = sqlite3.connect("assistant.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, text TEXT, deadline TEXT,
        done INTEGER DEFAULT 0, created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, text TEXT, created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, role TEXT, content TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS wheel_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, text TEXT
    )""")
    conn.commit(); conn.close()

def db():
    return sqlite3.connect("assistant.db")

def get_open_tasks(user_id):
    conn = db()
    rows = conn.execute(
        "SELECT id, text, deadline FROM tasks WHERE user_id=? AND done=0 ORDER BY deadline",
        (user_id,)
    ).fetchall()
    conn.close()
    return rows

def get_wheel_items(user_id):
    conn = db()
    rows = conn.execute("SELECT id, text FROM wheel_items WHERE user_id=?", (user_id,)).fetchall()
    conn.close()
    return rows

# ──────────────── Gemini AI ──────────────────
def get_ai_response(user_id, user_message):
    conn = db()
    rows = conn.execute(
        "SELECT role, content FROM history WHERE user_id=? ORDER BY id DESC LIMIT 12",
        (user_id,)
    ).fetchall()[::-1]
    conn.close()

    tasks = get_open_tasks(user_id)
    task_list = "\n".join([f"- [{t[0]}] {t[1]} (дедлайн: {t[2] or 'нет'})" for t in tasks]) or "задач нет"

    system_prompt = f"""Ты личный ИИ-ассистент пользователя в Telegram.
Помогай не забывать о делах, мотивируй, напоминай. Будь дружелюбным,
можешь пошутить, но всегда по делу. Отвечай кратко, по-русски.
Открытые задачи: {task_list}
Сейчас: {datetime.now().strftime("%d.%m.%Y %H:%M")}"""

    history = []
    for role, content in rows:
        history.append({"role": "user" if role == "user" else "model", "parts": [content]})

    model = genai.GenerativeModel(model_name="gemini-2.0-flash", system_instruction=system_prompt)
    chat = model.start_chat(history=history)
    reply = chat.send_message(user_message).text

    conn = db()
    conn.execute("INSERT INTO history (user_id, role, content) VALUES (?,?,?)", (user_id, "user", user_message))
    conn.execute("INSERT INTO history (user_id, role, content) VALUES (?,?,?)", (user_id, "assistant", reply))
    conn.commit(); conn.close()
    return reply

# ──────────────── Клавиатуры ─────────────────
def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Задачи",      callback_data="tasks"),
         InlineKeyboardButton("➕ Добавить",     callback_data="add_task")],
        [InlineKeyboardButton("✅ Закрыть задачу", callback_data="done_task"),
         InlineKeyboardButton("📝 Заметки",     callback_data="notes")],
        [InlineKeyboardButton("🎡 Колесо Фортуны", callback_data="wheel_menu")],
        [InlineKeyboardButton("💬 Чат с ИИ",    callback_data="chat")]
    ])

def wheel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎰 КРУТИТЬ!",         callback_data="wheel_spin")],
        [InlineKeyboardButton("➕ Добавить вариант",  callback_data="wheel_add"),
         InlineKeyboardButton("🗑 Очистить всё",      callback_data="wheel_clear")],
        [InlineKeyboardButton("📜 Мои варианты",      callback_data="wheel_list")],
        [InlineKeyboardButton("🏠 Меню",              callback_data="menu")]
    ])

# ──────────────── Анимация колеса ────────────
WHEEL_FRAMES = ["🎡", "🌀", "💫", "⭐", "🌟", "✨", "🎯"]

async def animate_wheel(message, items):
    """Красивая анимация вращения колеса"""
    text = message.text
    for i in range(8):
        frame = WHEEL_FRAMES[i % len(WHEEL_FRAMES)]
        dots = "." * ((i % 3) + 1)
        await message.edit_text(f"{frame} Колесо крутится{dots}\n\n" +
                                "\n".join([f"{'👉' if i%len(items)==idx else '  '} {item[1]}"
                                           for idx, item in enumerate(items)]))
        await asyncio.sleep(0.4)

# ──────────────── Хендлеры ───────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я твой личный ИИ-ассистент на базе *Gemini* 🤖\n\n"
        "• Напоминаю о делах и дедлайнах ⏰\n"
        "• Помогаю планировать задачи 📋\n"
        "• Крутю колесо фортуны, если не можешь выбрать 🎡\n\n"
        "Выбери действие или просто напиши мне:",
        parse_mode="Markdown", reply_markup=main_keyboard()
    )

async def menu_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Главное меню:", reply_markup=main_keyboard())

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data
    back_main = [[InlineKeyboardButton("🏠 Меню", callback_data="menu")]]

    # ── Главное меню ──
    if data == "menu":
        ctx.user_data["state"] = "chat"
        await query.edit_message_text("Главное меню:", reply_markup=main_keyboard())

    # ── Задачи ──
    elif data == "tasks":
        tasks = get_open_tasks(uid)
        if not tasks:
            text = "🎉 Открытых задач нет! Добавь новую."
        else:
            text = "📋 *Твои задачи:*\n\n"
            for t in tasks:
                dl = f"  ⏰ `{t[2]}`" if t[2] else ""
                text += f"*[{t[0]}]* {t[1]}{dl}\n"
        await query.edit_message_text(text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(back_main))

    elif data == "add_task":
        ctx.user_data["state"] = "waiting_task"
        await query.edit_message_text(
            "✏️ *Напиши задачу:*\n\n"
            "Без дедлайна:\n`Сходить в магазин`\n\n"
            "С дедлайном (через |):\n`Сдать отчёт | 25.03.2026 18:00`\n\n"
            "/menu — отмена", parse_mode="Markdown")

    elif data == "done_task":
        tasks = get_open_tasks(uid)
        if not tasks:
            await query.edit_message_text("Нет открытых задач 🎉",
                reply_markup=InlineKeyboardMarkup(back_main)); return
        kb = [[InlineKeyboardButton(f"✅ [{t[0]}] {t[1][:35]}", callback_data=f"close_{t[0]}")] for t in tasks]
        kb.append([InlineKeyboardButton("🏠 Меню", callback_data="menu")])
        await query.edit_message_text("Выбери задачу для закрытия:",
            reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("close_"):
        task_id = int(data.split("_")[1])
        conn = db()
        conn.execute("UPDATE tasks SET done=1 WHERE id=? AND user_id=?", (task_id, uid))
        conn.commit(); conn.close()
        praise = get_ai_response(uid, "Я только что выполнил задачу! Похвали меня в 1-2 предложения с эмодзи.")
        await query.edit_message_text(f"✅ Задача #{task_id} закрыта!\n\n{praise}",
            reply_markup=InlineKeyboardMarkup(back_main))

    elif data == "notes":
        conn = db()
        rows = conn.execute(
            "SELECT id, text, created_at FROM notes WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,)
        ).fetchall(); conn.close()
        if not rows:
            text = "📝 Заметок нет.\nДобавь: /note <текст>"
        else:
            text = "📝 *Заметки:*\n\n" + "\n".join([f"`{r[0]}.` {r[1]}" for r in rows])
        await query.edit_message_text(text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(back_main))

    elif data == "chat":
        ctx.user_data["state"] = "chat"
        await query.edit_message_text(
            "💬 Режим чата с Gemini!\n\nПиши что угодно. /menu — вернуться.")

    # ── Колесо Фортуны ──
    elif data == "wheel_menu":
        items = get_wheel_items(uid)
        count = len(items)
        text = f"🎡 *Колесо Фортуны*\n\n"
        text += f"Вариантов на колесе: *{count}*\n" if count else "Колесо пустое! Добавь варианты.\n"
        if items:
            text += "\n".join([f"• {item[1]}" for item in items[:8]])
            if count > 8: text += f"\n_...и ещё {count-8}_"
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=wheel_keyboard())

    elif data == "wheel_add":
        ctx.user_data["state"] = "waiting_wheel_item"
        await query.edit_message_text(
            "🎡 Напиши вариант для колеса\n\n"
            "Например: `Сделать зарядку` или `Выучить 10 слов`\n\n/menu — отмена",
            parse_mode="Markdown")

    elif data == "wheel_list":
        items = get_wheel_items(uid)
        if not items:
            text = "🎡 Колесо пустое! Добавь варианты через ➕"
        else:
            text = "🎡 *Варианты на колесе:*\n\n"
            text += "\n".join([f"`{i[0]}.` {i[1]}" for i in items])
            text += "\n\n_Чтобы удалить один: /delwheel <номер>_"
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=wheel_keyboard())

    elif data == "wheel_clear":
        conn = db()
        conn.execute("DELETE FROM wheel_items WHERE user_id=?", (uid,))
        conn.commit(); conn.close()
        await query.edit_message_text("🗑 Колесо очищено!", reply_markup=wheel_keyboard())

    elif data == "wheel_spin":
        items = get_wheel_items(uid)
        if not items:
            await query.edit_message_text(
                "🎡 Колесо пустое!\nДобавь варианты через ➕", reply_markup=wheel_keyboard()); return
        if len(items) < 2:
            await query.edit_message_text(
                "🎡 Добавь хотя бы 2 варианта!", reply_markup=wheel_keyboard()); return

        # Анимация
        await animate_wheel(query.message, items)

        # Результат
        winner = random.choice(items)
        comment = get_ai_response(uid,
            f'Колесо фортуны выбрало задачу: "{winner[1]}". '
            f'Прокомментируй в 1-2 предложениях с азартом и мотивацией!')
        result_text = (
            f"🎯 *Колесо остановилось на:*\n\n"
            f"🏆 *{winner[1]}*\n\n"
            f"{comment}"
        )
        await query.message.edit_text(result_text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎰 Крутить ещё!", callback_data="wheel_spin")],
                [InlineKeyboardButton("🎡 К колесу", callback_data="wheel_menu"),
                 InlineKeyboardButton("🏠 Меню", callback_data="menu")]
            ]))

# ──────────────── Текстовые сообщения ────────
async def message_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    state = ctx.user_data.get("state", "chat")

    if state == "waiting_task":
        ctx.user_data["state"] = "chat"
        parts = text.split("|")
        task_text = parts[0].strip()
        deadline = parts[1].strip() if len(parts) > 1 else None
        conn = db()
        conn.execute("INSERT INTO tasks (user_id, text, deadline, created_at) VALUES (?,?,?,?)",
                     (uid, task_text, deadline, datetime.now().strftime("%d.%m.%Y %H:%M")))
        conn.commit(); conn.close()
        dl_text = f"\n⏰ Дедлайн: `{deadline}`" if deadline else ""
        await update.message.reply_text(
            f"✅ Задача добавлена!\n*{task_text}*{dl_text}",
            parse_mode="Markdown", reply_markup=main_keyboard())

    elif state == "waiting_wheel_item":
        ctx.user_data["state"] = "chat"
        conn = db()
        conn.execute("INSERT INTO wheel_items (user_id, text) VALUES (?,?)", (uid, text.strip()))
        conn.commit(); conn.close()
        items = get_wheel_items(uid)
        await update.message.reply_text(
            f"🎡 Добавлено: *{text.strip()}*\nВсего на колесе: {len(items)} вариантов",
            parse_mode="Markdown", reply_markup=wheel_keyboard())

    else:
        await update.message.chat.send_action("typing")
        reply = get_ai_response(uid, text)
        await update.message.reply_text(reply)

async def note_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    note_text = " ".join(ctx.args)
    if not note_text:
        await update.message.reply_text("Напиши: /note <текст>"); return
    conn = db()
    conn.execute("INSERT INTO notes (user_id, text, created_at) VALUES (?,?,?)",
                 (uid, note_text, datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit(); conn.close()
    await update.message.reply_text(f"📝 Заметка сохранена: *{note_text}*", parse_mode="Markdown")

async def delwheel_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not ctx.args:
        await update.message.reply_text("Напиши: /delwheel <номер>"); return
    item_id = int(ctx.args[0])
    conn = db()
    conn.execute("DELETE FROM wheel_items WHERE id=? AND user_id=?", (item_id, uid))
    conn.commit(); conn.close()
    await update.message.reply_text(f"🗑 Вариант #{item_id} удалён!", reply_markup=wheel_keyboard())

# ──────────────── Напоминания ────────────────
async def send_reminders(app: Application):
    now = datetime.now()
    conn = db()
    tasks = conn.execute(
        "SELECT user_id, text, deadline FROM tasks WHERE done=0 AND deadline IS NOT NULL"
    ).fetchall(); conn.close()
    for user_id, text, deadline in tasks:
        try:
            dl = datetime.strptime(deadline, "%d.%m.%Y %H:%M")
            hours = (dl - now).total_seconds() / 3600
            if 0 < hours <= 2:
                msg = f"🚨 *Срочно!* Через ~{int(hours*60)} мин дедлайн:\n*{text}*"
            elif 2 < hours <= 24:
                msg = f"⏰ *Напоминание!* До дедлайна {int(hours)} ч.:\n*{text}*"
            elif -1 < hours <= 0:
                msg = f"😬 *Дедлайн прошёл!*\n*{text}*\n\nЧто там с этим?"
            else:
                continue
            await app.bot.send_message(chat_id=user_id, text=msg, parse_mode="Markdown")
        except Exception:
            continue

# ──────────────── Запуск ─────────────────────
def main():
    init_db()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",    start))
    app.add_handler(CommandHandler("menu",     menu_cmd))
    app.add_handler(CommandHandler("note",     note_cmd))
    app.add_handler(CommandHandler("delwheel", delwheel_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_reminders, "interval", minutes=30, args=[app])
    scheduler.start()

    print("✅ Бот запущен! Нажми Ctrl+C чтобы остановить.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
