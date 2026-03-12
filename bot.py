import os
import logging
import sqlite3
import random
from datetime import datetime, date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, MessageHandler,
                           filters, ContextTypes, CallbackQueryHandler, ConversationHandler)
from google import genai
client = genai.Client(api_key=GEMINI_API_KEY)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")


logging.basicConfig(level=logging.INFO)

# Состояния для ConversationHandler
WAITING_TASK = 1
WAITING_MOOD = 2

# ─────────────────────────────────────────
# БАЗА ДАННЫХ
# ─────────────────────────────────────────

def init_db():
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            task TEXT,
            done INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (date('now')),
            done_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS mood (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            score INTEGER,
            note TEXT,
            created_at TEXT DEFAULT (date('now'))
        )
    """)
    conn.commit()
    conn.close()

def db():
    return sqlite3.connect("bot.db")

# ─────────────────────────────────────────
# ГЛАВНОЕ МЕНЮ
# ─────────────────────────────────────────

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Задачи", callback_data="tasks_menu"),
         InlineKeyboardButton("📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton("😴 Режим фокуса", callback_data="focus"),
         InlineKeyboardButton("🌡️ Настроение", callback_data="mood_menu")],
        [InlineKeyboardButton("🎡 Колесо фортуны", callback_data="wheel"),
         InlineKeyboardButton("🤖 Спросить ИИ", callback_data="ask_ai")],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я твой личный ассистент!\nЧто хочешь сделать?",
        reply_markup=main_menu_keyboard()
    )

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Главное меню:", reply_markup=main_menu_keyboard())

# ─────────────────────────────────────────
# ЗАДАЧИ
# ─────────────────────────────────────────

def tasks_keyboard(user_id):
    conn = db()
    tasks = conn.execute(
        "SELECT id, task FROM tasks WHERE user_id=? AND done=0 ORDER BY id DESC LIMIT 10",
        (user_id,)
    ).fetchall()
    conn.close()
    buttons = []
    for task_id, task_text in tasks:
        short = task_text[:30] + "..." if len(task_text) > 30 else task_text
        buttons.append([
            InlineKeyboardButton(f"✅ {short}", callback_data=f"done_{task_id}"),
            InlineKeyboardButton("🗑️", callback_data=f"del_{task_id}")
        ])
    buttons.append([InlineKeyboardButton("➕ Добавить задачу", callback_data="add_task")])
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(buttons)

async def show_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    conn = db()
    total = conn.execute("SELECT COUNT(*) FROM tasks WHERE user_id=? AND done=0", (user_id,)).fetchone()[0]
    conn.close()
    text = f"📋 *Твои активные задачи* ({total} шт.):" if total > 0 else "📋 У тебя нет активных задач!"
    await query.edit_message_text(text, reply_markup=tasks_keyboard(user_id), parse_mode="Markdown")

async def add_task_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("✏️ Напиши название задачи:")
    return WAITING_TASK

async def save_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    task_text = update.message.text
    conn = db()
    conn.execute("INSERT INTO tasks (user_id, task) VALUES (?, ?)", (user_id, task_text))
    conn.commit()
    conn.close()
    await update.message.reply_text(
        f"✅ Задача добавлена: *{task_text}*",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )
    return ConversationHandler.END

async def complete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    task_id = int(query.data.split("_")[1])
    user_id = query.from_user.id
    conn = db()
    conn.execute("UPDATE tasks SET done=1, done_at=date('now') WHERE id=?", (task_id,))
    conn.commit()
    conn.close()
    await query.edit_message_text(
        "🎉 Задача выполнена! Молодец! 💪",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 К задачам", callback_data="tasks_menu")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="back_main")]
        ])
    )

async def delete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    task_id = int(query.data.split("_")[1])
    user_id = query.from_user.id
    conn = db()
    conn.execute("DELETE FROM tasks WHERE id=? AND user_id=?", (task_id, user_id))
    conn.commit()
    conn.close()
    await query.edit_message_text(
        "🗑️ Задача удалена.",
        reply_markup=tasks_keyboard(user_id)
    )

# ─────────────────────────────────────────
# СТАТИСТИКА
# ─────────────────────────────────────────

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    conn = db()
    total_done = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id=? AND done=1", (user_id,)
    ).fetchone()[0]
    week_done = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id=? AND done=1 AND done_at >= date('now', '-7 days')",
        (user_id,)
    ).fetchone()[0]
    month_done = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id=? AND done=1 AND done_at >= date('now', '-30 days')",
        (user_id,)
    ).fetchone()[0]
    active = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id=? AND done=0", (user_id,)
    ).fetchone()[0]
    avg_mood = conn.execute(
        "SELECT AVG(score) FROM mood WHERE user_id=? AND created_at >= date('now', '-7 days')",
        (user_id,)
    ).fetchone()[0]
    conn.close()

    mood_text = f"{avg_mood:.1f}/5 😊" if avg_mood else "нет данных"
    bars_week = "🟩" * week_done + "⬜" * max(0, 7 - week_done)

    text = (
        f"📊 *Твоя статистика*\n\n"
        f"✅ За эту неделю: *{week_done}* задач\n"
        f"{bars_week}\n\n"
        f"📅 За месяц: *{month_done}* задач\n"
        f"🏆 Всего выполнено: *{total_done}* задач\n"
        f"📋 Активных задач: *{active}*\n\n"
        f"🌡️ Среднее настроение (7 дней): *{mood_text}*"
    )
    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]])
    )

# ─────────────────────────────────────────
# РЕЖИМ ФОКУСА
# ─────────────────────────────────────────

async def focus_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    conn = db()
    tasks = conn.execute(
        "SELECT task FROM tasks WHERE user_id=? AND done=0", (user_id,)
    ).fetchall()
    conn.close()

    if not tasks:
        await query.edit_message_text(
            "😴 У тебя нет активных задач!\nДобавь задачи через меню.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]])
        )
        return

    task_list = "\n".join([f"- {t[0]}" for t in tasks])
    await query.edit_message_text("⏳ ИИ выбирает главную задачу дня...")

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=f"Вот список задач пользователя:\n{task_list}\n\nВыбери ОДНУ самую важную задачу на сегодня и объясни в 2-3 предложениях почему именно её стоит сделать первой. Ответь на русском, мотивирующе и кратко."
        )

        text = f"😴 *Режим фокуса — задача дня:*\n\n{response.text}"
    except:
        chosen = random.choice(tasks)[0]
        text = f"😴 *Задача дня:*\n\n🎯 {chosen}\n\nСосредоточься на этом!"

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]])
    )

# ─────────────────────────────────────────
# НАСТРОЕНИЕ
# ─────────────────────────────────────────

async def mood_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("😞 1", callback_data="mood_1"),
            InlineKeyboardButton("😕 2", callback_data="mood_2"),
            InlineKeyboardButton("😐 3", callback_data="mood_3"),
            InlineKeyboardButton("😊 4", callback_data="mood_4"),
            InlineKeyboardButton("😄 5", callback_data="mood_5"),
        ],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_main")]
    ])
    await query.edit_message_text("🌡️ Как твоё настроение сегодня?\nОцени от 1 до 5:", reply_markup=keyboard)

async def save_mood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    score = int(query.data.split("_")[1])
    emojis = {1: "😞", 2: "😕", 3: "😐", 4: "😊", 5: "😄"}

    conn = db()
    conn.execute("INSERT INTO mood (user_id, score) VALUES (?, ?)", (user_id, score))
    conn.commit()
    conn.close()

    responses = {
        1: "Держись! Завтра будет лучше 💙",
        2: "Всё наладится, ты справишься 🙌",
        3: "Нейтральный день — тоже норм 👍",
        4: "Отлично, продолжай в том же духе! ⚡",
        5: "Ты в ударе сегодня! 🔥"
    }
    await query.edit_message_text(
        f"{emojis[score]} Настроение {score}/5 сохранено!\n\n{responses[score]}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]])
    )

# ─────────────────────────────────────────
# КОЛЕСО ФОРТУНЫ
# ─────────────────────────────────────────

async def wheel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    conn = db()
    tasks = conn.execute(
        "SELECT task FROM tasks WHERE user_id=? AND done=0", (user_id,)
    ).fetchall()
    conn.close()
    if tasks:
        chosen = random.choice(tasks)[0]
        text = f"🎡 Колесо фортуны выбрало:\n\n*{chosen}*\n\nВперёд! 💪"
    else:
        text = "Сначала добавь задачи!"
    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_main")]])
    )

# ─────────────────────────────────────────
# ИИ АССИСТЕНТ
# ─────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    await update.message.reply_text("⏳ Думаю...")
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=f"Ты личный ассистент. Отвечай кратко и по делу на русском. Вопрос: {user_text}"
        )
        await update.message.reply_text(response.text)
    except Exception as e:
        await update.message.reply_text("Ошибка ИИ. Попробуй позже.")


# ─────────────────────────────────────────
# НАВИГАЦИЯ
# ─────────────────────────────────────────

async def back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Главное меню:", reply_markup=main_menu_keyboard())

async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    if data == "tasks_menu":   await show_tasks(update, context)
    elif data == "stats":      await show_stats(update, context)
    elif data == "focus":      await focus_mode(update, context)
    elif data == "mood_menu":  await mood_menu(update, context)
    elif data == "wheel":      await wheel(update, context)
    elif data == "ask_ai":     await ask_ai_prompt(update, context)
    elif data == "back_main":  await back_main(update, context)
    elif data.startswith("done_"):   await complete_task(update, context)
    elif data.startswith("del_"):    await delete_task(update, context)
    elif data.startswith("mood_") and data[5:].isdigit(): await save_mood(update, context)

# ─────────────────────────────────────────
# ЗАПУСК
# ─────────────────────────────────────────

def main():
    init_db()
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_task_prompt, pattern="^add_task$")],
        states={WAITING_TASK: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_task)]},
        fallbacks=[CommandHandler("menu", menu)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(button_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
