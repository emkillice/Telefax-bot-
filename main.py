import argparse, json, logging, os, openai, requests
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackContext, filters

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN') or exit("🚨Error: TELEGRAM_TOKEN is not set.")
openai.api_key = os.getenv('OPENAI_API_KEY') or None
SESSION_DATA = {}

def load_configuration():
    with open('configuration.json', 'r') as file:
        return json.load(file)

def get_session_id(func):
    async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        session_id = str(update.effective_chat.id if update.effective_chat.type in ['group', 'supergroup'] else update.effective_user.id)
        return await func(update, context, session_id, *args, **kwargs)
    return wrapper

def initialize_session_data(func):
    async def wrapper(update: Update, context: CallbackContext, session_id, *args, **kwargs):
        if session_id not in SESSION_DATA:
            SESSION_DATA[session_id] = load_configuration()['default_session_values']
        return await func(update, context, session_id, *args, **kwargs)
    return wrapper

def check_api_key(func):
    async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        if not openai.api_key:
            await update.message.reply_text("⚠️ Не установлен OpenAI API ключ.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

def relay_errors(func):
    async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        try:
            return await func(update, context, *args, **kwargs)
        except Exception as e:
            await update.message.reply_text(f"⚠️ Ошибка: {e}")
    return wrapper

CONFIGURATION = load_configuration()
VISION_MODELS = CONFIGURATION.get('vision_models', [])
VALID_MODELS = CONFIGURATION.get('VALID_MODELS', {})

@relay_errors
@get_session_id
@initialize_session_data
@check_api_key
async def handle_message(update: Update, context: CallbackContext, session_id):
    if update.message.voice:
        await update.message.reply_text("⚠️ Голосовые сообщения не поддерживаются.")
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    session_data = SESSION_DATA[session_id]

    if update.message.photo and session_data['model'] in VISION_MODELS:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        photo_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file.file_path}"
        caption = update.message.caption or "Опиши изображение."
        session_data['chat_history'].append({
            "role": "user",
            "content": [
                {"type": "text", "text": caption},
                {"type": "image_url", "image_url": {"url": photo_url}}
            ]
        })
    elif update.message.text:
        session_data['chat_history'].append({
            "role": "user",
            "content": update.message.text
        })
    else:
        await update.message.reply_text("⚠️ Пустое сообщение.")
        return

    response = await response_from_openai(
        session_data['model'],
        session_data['chat_history'],
        session_data['temperature'],
        session_data['max_tokens']
    )
    session_data['chat_history'].append({
        "role": "assistant",
        "content": response
    })
    await update.message.reply_markdown(response)

async def response_from_openai(model, messages, temperature, max_tokens):
    params = {
        "model": model,
        "messages": messages,
        "temperature": temperature
    }
    if max_tokens:
        params["max_tokens"] = max_tokens
    return openai.chat.completions.create(**params).choices[0].message.content

async def command_start(update: Update, context: CallbackContext):
    await update.message.reply_text("Привет! Я ИИ-помощник. Напиши вопрос!")

@get_session_id
async def command_reset(update: Update, context: CallbackContext, session_id):
    if session_id in SESSION_DATA:
        del SESSION_DATA[session_id]
    await update.message.reply_text("Сессия сброшена.")

@get_session_id
async def command_clear(update: Update, context: CallbackContext, session_id):
    if session_id in SESSION_DATA:
        SESSION_DATA[session_id]["chat_history"] = []
    await update.message.reply_text("История очищена.")

@get_session_id
@initialize_session_data
async def command_set(update: Update, context: CallbackContext, session_id):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("⚠️ Использование: /set параметр значение")
        return
    key, value = args[0].lower(), " ".join(args[1:])
    session = SESSION_DATA[session_id]
    if key in session:
        session[key] = float(value) if key == "temperature" else value
        await update.message.reply_text(f"✅ {key} обновлено.")
    else:
        await update.message.reply_text("⚠️ Неизвестный параметр.")

@get_session_id
async def command_show(update: Update, context: CallbackContext, session_id):
    session = SESSION_DATA.get(session_id, {})
    text = "
".join(f"{k}: {v}" for k, v in session.items() if k != "chat_history")
    await update.message.reply_text(f"Текущие настройки:
{text}")

async def command_help(update: Update, context: CallbackContext):
    await update.message.reply_text("/start /help /set /show /reset /clear")

def register_handlers(app):
    app.add_handler(CommandHandler("start", command_start))
    app.add_handler(CommandHandler("help", command_help))
    app.add_handler(CommandHandler("reset", command_reset))
    app.add_handler(CommandHandler("clear", command_clear))
    app.add_handler(CommandHandler("set", command_set))
    app.add_handler(CommandHandler("show", command_show))
    app.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), handle_message))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    register_handlers(app)
    app.run_polling()

if __name__ == "__main__":
    main()
