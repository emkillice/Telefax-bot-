import argparse, json, logging, os, openai, requests
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackContext, filters

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN') or exit("🚨Error: TELEGRAM_TOKEN is not set.")
openai.api_key = os.getenv('OPENAI_API_KEY') or None
SESSION_DATA = {}
user_whitelist = ["5321458881"]
free_limit = 3
usage_counter = {}

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
            await update.message.reply_text("⚠️ Установите OpenAI API Key командой: /set openai_api_key YOUR_KEY")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

def relay_errors(func):
    async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        try:
            return await func(update, context, *args, **kwargs)
        except Exception as e:
            await update.message.reply_text(f"Ошибка: {e}")
    return wrapper

CONFIGURATION = load_configuration()
VISION_MODELS = CONFIGURATION.get('vision_models', [])
VALID_MODELS = CONFIGURATION.get('VALID_MODELS', {})

@relay_errors
@get_session_id
@initialize_session_data
@check_api_key
async def handle_message(update: Update, context: CallbackContext, session_id):
    user_id = str(update.effective_user.id)
    if user_id not in user_whitelist:
        usage_counter[user_id] = usage_counter.get(user_id, 0) + 1
        if usage_counter[user_id] > free_limit:
            await update.message.reply_text("Доступ ограничен. Купите подписку для продолжения.")
            return

    if update.message.voice:
        await update.message.reply_text("⚠️ Голосовые сообщения не поддерживаются. Напишите текст.")
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    session_data = SESSION_DATA[session_id]

    if update.message.photo and session_data['model'] in VISION_MODELS:
        photo = update.message.photo[-1]
        photo_file = await context.bot.get_file(photo.file_id)
        photo_url = photo_file.file_path
        caption = update.message.caption or "Что на изображении?"
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
    params = {'model': model, 'messages': messages, 'temperature': temperature}
    if model == "gpt-4-vision-preview":
        max_tokens = 4096
    if max_tokens:
        params['max_tokens'] = max_tokens
    return openai.chat.completions.create(**params).choices[0].message.content

@get_session_id
async def command_reset(update: Update, context: CallbackContext, session_id):
    if session_id in SESSION_DATA:
        del SESSION_DATA[session_id]
    await update.message.reply_text("Сессия сброшена.")

@get_session_id
async def command_clear(update: Update, context: CallbackContext, session_id):
    if session_id in SESSION_DATA:
        SESSION_DATA[session_id]['chat_history'] = []
    await update.message.reply_text("История очищена.")

@get_session_id
async def command_show(update: Update, context: CallbackContext, session_id):
    session_data = SESSION_DATA.get(session_id, {})
    summary = "**Данные сеанса:**\n"
    for k, v in session_data.items():
        if k != 'chat_history':
            summary += f"{k}: {v}\n"
    summary += "**История:**\n"
    for m in session_data.get('chat_history', []):
        summary += f"{m['role']}: {m['content']}\n"
    await update.message.reply_text(summary[:4096])

@get_session_id
@initialize_session_data
async def command_set(update: Update, context: CallbackContext, session_id):
    args = context.args
    if not args:
        await update.message.reply_text("Формат: /set [параметр] [значение]")
        return
    key, *rest = args
    value = ' '.join(rest)
    if key == 'model':
        if value in sum(VALID_MODELS.values(), []):
            model = next(k for k in VALID_MODELS if value in VALID_MODELS[k])
            SESSION_DATA[session_id]['model'] = model
            await update.message.reply_text(f"Модель установлена: {model}")
    elif key == 'openai_api_key':
        openai.api_key = value
        await update.message.reply_text("Ключ API обновлён.")
    elif key == 'temperature':
        try:
            SESSION_DATA[session_id]['temperature'] = float(value)
            await update.message.reply_text(f"Temperature установлена: {value}")
        except:
            await update.message.reply_text("Некорректное значение.")
    elif key == 'max_tokens':
        if value.isdigit():
            SESSION_DATA[session_id]['max_tokens'] = int(value)
            await update.message.reply_text(f"Max tokens установлен: {value}")
    else:
        await update.message.reply_text("Неизвестный параметр.")

async def command_help(update: Update, context: CallbackContext):
    help_text = (
        "/set - изменить параметры\n"
        "/reset - сбросить сессию\n"
        "/clear - очистить историю\n"
        "/show - показать текущие настройки\n"
        "/help - помощь"
    )
    await update.message.reply_text(help_text)

async def command_start(update: Update, context: CallbackContext):
    await update.message.reply_text("Привет! Я GPT-бот. Напиши сообщение, чтобы начать.")

def register_handlers(app):
    app.add_handler(CommandHandler('start', command_start))
    app.add_handler(CommandHandler('reset', command_reset))
    app.add_handler(CommandHandler('clear', command_clear))
    app.add_handler(CommandHandler('show', command_show))
    app.add_handler(CommandHandler('help', command_help))
    app.add_handler(CommandHandler('set', command_set))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

def railway_dns_workaround():
    from time import sleep
    for _ in range(3):
        try:
            if requests.get("https://api.telegram.org", timeout=3).ok:
                return
        except: sleep(1)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.disable(logging.CRITICAL)
    railway_dns_workaround()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    register_handlers(app)
    app.run_polling()

if __name__ == '__main__':
    main()