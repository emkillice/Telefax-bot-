import os
import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# Настройки
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ALLOWED_USER_ID = "5321458881"  # Кирилл — безлимит

# Временное хранилище количества сообщений
user_message_count = {}

# Логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я ИИ-бот. Задай мне вопрос.")

# Обработка сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)

    # Безлимит для Кирилла
    if user_id == ALLOWED_USER_ID:
        await update.message.reply_text("Ты в списке безлимитных. Обрабатываю запрос...")
        return

    # Учёт сообщений
    count = user_message_count.get(user_id, 0)
    if count >= 3:
        await update.message.reply_text("Доступ ограничен. Купи подписку для безлимита.")
        return

    user_message_count[user_id] = count + 1
    await update.message.reply_text(f"Ответ {count + 1} из 3. Обрабатываю...")

# Основной запуск
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling()
