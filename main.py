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
        photo_url = photo_file.file_path
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
    await update.message.reply_text("ℹ️Welcome! Say something to begin. Use /help for more options.")

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
        logging.warning(f"No session data found for session_id={session_id}")

@get_session_id
@initialize_session_data
async def command_set(update: Update, context: CallbackContext, session_id):
    args = context.args
    if not args:
        await update.message.reply_text("⚠️Use: /set [model, temperature, max_tokens, openai_api_key]")
        return
    preference, *rest = args
    preference = preference.lower()
    value = ' '.join(rest)
    if preference == 'model':
        if not value:
            model_list ="
".join(f"{model}: {', '.join(sh)}" for model, sh in VALID_MODELS.items())
            await update.message.reply_text(f"Available models:
{model_list}")
            return
        if value in sum(VALID_MODELS.values(), []):
            actual_model = next(m for m in VALID_MODELS if value in VALID_MODELS[m])
            SESSION_DATA[session_id]['model'] = actual_model
            await command_clear(update, context)
            await update.message.reply_text(f"✅Model set to {actual_model}.")
        else:
            await update.message.reply_text("⚠️Invalid model.")
    elif preference == 'openai_api_key':
        openai.api_key = value
        await update.message.reply_text("✅OpenAI API key set.")
    elif preference == 'temperature':
        try:
            temp = float(value)
            if 0 <= temp <= 2.0:
                SESSION_DATA[session_id]['temperature'] = temp
                await update.message.reply_text(f"✅Temperature set to {temp}.")
            else:
                raise ValueError
        except:
            await update.message.reply_text("⚠️Invalid temperature. Use 0.0 - 2.0")
    elif preference == 'max_tokens':
        if value.isdigit():
            SESSION_DATA[session_id]['max_tokens'] = int(value)
            await update.message.reply_text(f"✅Max tokens set to {value}.")
        else:
            await update.message.reply_text("⚠️Invalid value.")
    else:
        await update.message.reply_text("⚠️Unsupported setting.")

@get_session_id
async def command_show(update: Update, context: CallbackContext, session_id):
    session_data = SESSION_DATA.get(session_id, {})
    message = "**Session Data:**
"
    if not session_data:
        message += "No session data.
"
    else:
        for key, value in session_data.items():
            if key != 'chat_history':
                message += f"{key}: {value}
"
    await update.message.reply_text(message)

async def command_help(update: Update, context: CallbackContext):
    help_text = "<b>📚 Commands:</b>
" +                 "/start - Start the bot
" +                 "/reset - Reset settings
" +                 "/clear - Clear chat
" +                 "/set - Set params
" +                 "/show - Show session
" +                 "/help - This menu"
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)

def register_handlers(app):
    app.add_handlers(handlers={
        -1: [
            CommandHandler("start", command_start),
            CommandHandler("reset", command_reset),
            CommandHandler("clear", command_clear),
            CommandHandler("set", command_set),
            CommandHandler("show", command_show),
            CommandHandler("help", command_help),
        ],
        1: [
            MessageHandler(filters.ALL & (~filters.COMMAND), handle_message)
        ]
    })

def railway_dns_workaround():
    from time import sleep
    sleep(1.3)
    for _ in range(3):
        try:
            if requests.get("https://api.telegram.org").status_code == 200:
                print("API reachable.")
                return
        except:
            print("Retrying connection...")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.disable(logging.WARNING)
    railway_dns_workaround()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    register_handlers(app)
    app.run_polling()

if __name__ == "__main__":
    main()
