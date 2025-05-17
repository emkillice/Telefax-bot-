
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
            logging.debug(f"Initializing session data for session_id={session_id}")
            SESSION_DATA[session_id] = load_configuration()['default_session_values']
        else:
            logging.debug(f"Session data already exists for session_id={session_id}")
        logging.debug(f"SESSION_DATA[{session_id}]: {SESSION_DATA[session_id]}")
        return await func(update, context, session_id, *args, **kwargs)
    return wrapper

def check_api_key(func):
    async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        if not openai.api_key:
            await update.message.reply_text("⚠️Please configure your OpenAI API Key: /set openai_api_key THE_API_KEY")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

def relay_errors(func):
    async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        try:
            return await func(update, context, *args, **kwargs)
        except Exception as e:
            await update.message.reply_text(f"An error occurred. e: {e}")
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
        await update.message.reply_text("⚠️ Голосовые сообщения не поддерживаются. Пожалуйста, напишите текстом.")
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    session_data = SESSION_DATA[session_id]
    if update.message.photo and session_data['model'] in VISION_MODELS:
        photo = update.message.photo[-1]
        photo_file = await context.bot.get_file(photo.file_id)
        photo_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{photo_file.file_path}"
        caption = update.message.caption or "Describe this image."
        session_data['chat_history'].append({
            "role": "user",
            "content": [
                {"type": "text", "text": caption},
                {"type": "image_url", "image_url": {"url": photo_url}}
            ]
        })
    else:
        user_message = update.message.text
        session_data['chat_history'].append({
            "role": "user",
            "content": user_message
        })
    messages_for_api = [message for message in session_data['chat_history']]
    response = await response_from_openai(
        session_data['model'], 
        messages_for_api, 
        session_data['temperature'], 
        session_data['max_tokens']
    )
    session_data['chat_history'].append({
        'role': 'assistant',
        'content': response
    })
    await update.message.reply_markdown(response)

async def response_from_openai(model, messages, temperature, max_tokens):
    params = {'model': model, 'messages': messages, 'temperature': temperature}
    if model == "gpt-4-vision-preview":
        max_tokens = 4096
    if max_tokens is not None: 
        params['max_tokens'] = max_tokens
    return openai.chat.completions.create(**params).choices[0].message.content

async def command_start(update: Update, context: CallbackContext):
    await update.message.reply_text("ℹ️Welcome! Go ahead and say something to start the conversation. More features: /help")

@get_session_id
async def command_reset(update: Update, context: CallbackContext, session_id):
    if session_id in SESSION_DATA:
        del SESSION_DATA[session_id]
        await update.message.reply_text("ℹ️All settings have been reset.")
    else:
        await update.message.reply_text("ℹ️No session data to reset.")

@get_session_id
async def command_clear(update: Update, context: CallbackContext, session_id):
    if session_id in SESSION_DATA:
        SESSION_DATA[session_id]['chat_history'] = []
        await update.message.reply_text("ℹ️Chat history is now empty!")
    else:
        await update.message.reply_text("ℹ️No chat history found.")

@get_session_id
@initialize_session_data
async def command_set(update: Update, context: CallbackContext, session_id):
    args = context.args
    if not args:
        await update.message.reply_text("⚠️Please specify what to set (model, temperature, system_prompt, max_tokens, openai_api_key).")
        return
    preference, *rest = args
    preference = preference.lower()
    value = ' '.join(rest)
    if preference == 'openai_api_key':
        openai.api_key = value
        await update.message.reply_text("✅OpenAI API key has been set.")
    else:
        SESSION_DATA[session_id][preference] = value
        await update.message.reply_text(f"✅{preference} set to {value}")

@get_session_id
async def command_show(update: Update, context: CallbackContext, session_id):
    session_data = SESSION_DATA.get(session_id, {})
    message = "**Session Data:**\n"
    for key, value in session_data.items():
        if key != 'chat_history':
            message += f"{key}: {value}\n"
    await update.message.reply_text(message)

async def command_help(update: Update, context: CallbackContext):
    await update.message.reply_text(
        "/start - Старт\n"
        "/reset - Сброс\n"
        "/clear - Очистить историю\n"
        "/set - Настройки\n"
        "/show - Показать\n"
        "/help - Помощь"
    )

def register_handlers(application):
    application.add_handler(CommandHandler("start", command_start))
    application.add_handler(CommandHandler("reset", command_reset))
    application.add_handler(CommandHandler("clear", command_clear))
    application.add_handler(CommandHandler("set", command_set))
    application.add_handler(CommandHandler("show", command_show))
    application.add_handler(CommandHandler("help", command_help))
    application.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), handle_message))

def main():
    parser = argparse.ArgumentParser(description="Run the Telegram bot.")
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.disable(logging.WARNING)
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    register_handlers(application)
    application.run_polling()

if __name__ == '__main__':
    main()
