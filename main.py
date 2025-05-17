import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

TELEGRAM_TOKEN = os.getenv("TELEGRAMM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Список ID пользователей с безлимитным доступом
UNLIMITED_USERS = ["5321458881"]

user_message_counts = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Я твой ИИ-помощник. Задай любой вопрос.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_message_counts.setdefault(user_id, 0)
    user_message_counts[user_id] += 1

    if user_id in UNLIMITED_USERS or user_message_counts[user_id] <= 3:
        await update.message.reply_text(f"Ты в списке {'безлимитных' if user_id in UNLIMITED_USERS else 'обычных'}. Обрабатываю запрос...")
    else:
        await update.message.reply_text("Ты использовал 3 бесплатных сообщения. Для продолжения оформи подписку.")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    app.run_polling()
