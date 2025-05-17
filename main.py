import argparse, json, logging, os, openai, requests
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackContext, filters
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN') or exit('No TELEGRAM_TOKEN')
openai.api_key = os.getenv('OPENAI_API_KEY')
SESSION_DATA = {}
FREE_LIMIT = 3
UNLIMITED_USER_IDS = ['5321458881']

def load_configuration():
    with open('configuration.json', 'r') as f:
        return json.load(f)
CONFIGURATION = load_configuration()
VISION_MODELS = CONFIGURATION.get('vision_models', [])
VALID_MODELS = CONFIGURATION.get('VALID_MODELS', {})
def get_session_id(func):
    async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        session_id = str(update.effective_user.id)
        return await func(update, context, session_id, *args, **kwargs)
    return wrapper

def initialize_session_data(func):
    async def wrapper(update: Update, context: CallbackContext, session_id, *args, **kwargs):
        if session_id not in SESSION_DATA:
            SESSION_DATA[session_id] = load_configuration()['default_session_values']
            SESSION_DATA[session_id]['usage'] = 0
        return await func(update, context, session_id, *args, **kwargs)
    return wrapper

def check_api_key(func):
    async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        if not openai.api_key:
            await update.message.reply_text('API ключ не установлен.')
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

def relay_errors(func):
    async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        try:
            return await func(update, context, *args, **kwargs)
        except Exception as e:
            await update.message.reply_text(f'❌ Ошибка: {e}')
    return wrapper
@relay_errors
@get_session_id
@initialize_session_data
@check_api_key
async def handle_message(update: Update, context: CallbackContext, session_id):
    if update.message.voice:
        await update.message.reply_text('Голосовые сообщения не поддерживаются.')
        return
    user_id = str(update.effective_user.id)
    session = SESSION_DATA[session_id]
    if user_id not in UNLIMITED_USER_IDS:
        if session['usage'] >= FREE_LIMIT:
            await update.message.reply_text('🔒 Лимит исчерпан. /subscribe чтобы получить доступ.')
            return
        session['usage'] += 1
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    if update.message.photo and session['model'] in VISION_MODELS:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        url = f'https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file.file_path}'
        caption = update.message.caption or 'Опиши это.'
        session['chat_history'].append({
            'role': 'user',
            'content': [
                {'type': 'text', 'text': caption},
                {'type': 'image_url', 'image_url': {'url': url}}
            ]
        })
    else:
        session['chat_history'].append({'role': 'user', 'content': update.message.text})
    reply = await ask_openai(session['model'], session['chat_history'], session['temperature'], session['max_tokens'])
    session['chat_history'].append({'role': 'assistant', 'content': reply})
    await update.message.reply_text(reply[:4096])
async def ask_openai(model, messages, temperature, max_tokens):
    res = openai.chat.completions.create(model=model, messages=messages, temperature=temperature, max_tokens=max_tokens)
    return res.choices[0].message.content

@get_session_id
async def command_reset(update: Update, context: CallbackContext, session_id):
    SESSION_DATA.pop(session_id, None)
    await update.message.reply_text('♻️ Сброшено.')

@get_session_id
async def command_clear(update: Update, context: CallbackContext, session_id):
    SESSION_DATA[session_id]['chat_history'] = []
    SESSION_DATA[session_id]['usage'] = 0
    await update.message.reply_text('🧹 Очищено.')

@get_session_id
@initialize_session_data
async def command_set(update: Update, context: CallbackContext, session_id):
    args = context.args
    if not args:
        await update.message.reply_text('Пример: /set model gpt-4')
        return
    key, *rest = args
    value = ' '.join(rest)
    session = SESSION_DATA[session_id]
    if key == 'model' and value:
        for m, aliases in VALID_MODELS.items():
            if value in aliases:
                session['model'] = m
                await update.message.reply_text(f'✅ Модель: {m}')
                return
        await update.message.reply_text('❌ Модель не найдена.')
    elif key == 'temperature':
        try:
            session['temperature'] = float(value)
            await update.message.reply_text(f'Температура: {value}')
        except: await update.message.reply_text('Ошибка температуры')
    elif key == 'max_tokens':
        if value.isdigit():
            session['max_tokens'] = int(value)
            await update.message.reply_text(f'Макс токенов: {value}')
    elif key == 'openai_api_key':
        openai.api_key = value
        await update.message.reply_text('🔑 Установлен новый ключ.')
@get_session_id
async def command_show(update: Update, context: CallbackContext, session_id):
    session = SESSION_DATA.get(session_id, {})
    msg = '\n'.join([f'{k}: {v}' for k, v in session.items() if k != 'chat_history'])
    await update.message.reply_text(msg or 'Нет данных.')

async def command_start(update: Update, context: CallbackContext):
    await update.message.reply_text('👋 Привет! Я ИИ-бот. Напиши что-нибудь.')

async def command_help(update: Update, context: CallbackContext):
    await update.message.reply_text('/start /set /show /clear /reset /help')
def register_handlers(app):
    app.add_handler(CommandHandler('start', command_start))
    app.add_handler(CommandHandler('reset', command_reset))
    app.add_handler(CommandHandler('clear', command_clear))
    app.add_handler(CommandHandler('set', command_set))
    app.add_handler(CommandHandler('show', command_show))
    app.add_handler(CommandHandler('help', command_help))
    app.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), handle_message))

def railway_dns_workaround():
    import time
    time.sleep(1.3)
    try:
        requests.get('https://api.telegram.org', timeout=3)
    except: pass

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.disable(logging.WARNING)
    railway_dns_workaround()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    register_handlers(app)
    app.run_polling()

if __name__ == '__main__':
    main()
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
