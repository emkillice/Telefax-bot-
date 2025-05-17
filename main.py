import argparse, json, logging, os, openai, requests
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackContext, filters

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or exit("🚨Error: TELEGRAM_TOKEN is not set.")
openai.api_key = os.getenv("OPENAI_API_KEY") or None
SESSION_DATA = {}

def load_configuration():
    with open("configuration.json", "r") as file:
        return json.load(file)

def get_session_id(func):
    async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        session_id = str(update.effective_chat.id if update.effective_chat.type in ["group", "supergroup"] else update.effective_user.id)
        return await func(update, context, session_id, *args, **kwargs)
    return wrapper

def initialize_session_data(func):
    async def wrapper(update: Update, context: CallbackContext, session_id, *args, **kwargs):
        if session_id not in SESSION_DATA:
            SESSION_DATA[session_id] = load_configuration()["default_session_values"]
        return await func(update, context, session_id, *args, **kwargs)
    return wrapper

def check_api_key(func):
    async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        if not openai.api_key:
            await update.message.reply_text("⚠️ Укажите OpenAI API ключ командой: /set openai_api_key КЛЮЧ")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

def relay_errors(func):
    async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        try:
            return await func(update, context, *args, **kwargs)
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
    return wrapper

CONFIGURATION = load_configuration()
VISION_MODELS = CONFIGURATION.get("vision_models", [])
VALID_MODELS = CONFIGURATION.get("VALID_MODELS", {})

@relay_errors
@get_session_id
@initialize_session_data
@check_api_key
async def handle_message(update: Update, context: CallbackContext, session_id):
    if update.message.voice:
        await update.message.reply_text("⚠️ Голосовые сообщения не поддерживаются. Напишите текстом.")
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    session_data = SESSION_DATA[session_id]
    if update.message.photo and session_data["model"] in VISION_MODELS:
        photo = update.message.photo[-1]
        photo_file = await context.bot.get_file(photo.file_id)
        photo_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{photo_file.file_path}"
        caption = update.message.caption or "Опиши изображение."
        session_data["chat_history"].append({
            "role": "user",
            "content": [
                {"type": "text", "text": caption},
                {"type": "image_url", "image_url": {"url": photo_url}}
            ]
        })
    else:
        user_message = update.message.text
        session_data["chat_history"].append({
            "role": "user",
            "content": user_message
        })

    response = await response_from_openai(
        session_data["model"],
        session_data["chat_history"],
        session_data["temperature"],
        session_data["max_tokens"]
    )
    session_data["chat_history"].append({
        "role": "assistant",
        "content": response
    })
    await update.message.reply_markdown(response)

async def response_from_openai(model, messages, temperature, max_tokens):
    params = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens:
        params["max_tokens"] = max_tokens
    return openai.chat.completions.create(**params).choices[0].message.content

async def command_start(update: Update, context: CallbackContext):
    await update.message.reply_text("ℹ️ Привет! Отправь сообщение, и я отвечу. Дополнительные команды: /help")

@get_session_id
async def command_reset(update: Update, context: CallbackContext, session_id):
    if session_id in SESSION_DATA:
        del SESSION_DATA[session_id]
        await update.message.reply_text("🔁 Настройки сброшены.")
    else:
        await update.message.reply_text("ℹ️ Нет данных для сброса.")

@get_session_id
async def command_clear(update: Update, context: CallbackContext, session_id):
    if session_id in SESSION_DATA:
        SESSION_DATA[session_id]["chat_history"] = []
        await update.message.reply_text("🧹 История чата очищена.")

@get_session_id
@initialize_session_data
async def command_set(update: Update, context: CallbackContext, session_id):
    args = context.args
    if not args:
        await update.message.reply_text("⚙️ Используйте: /set [model|temperature|max_tokens|system_prompt|openai_api_key] значение")
        return

    key, *rest = args
    value = " ".join(rest)
    if key == "openai_api_key":
        openai.api_key = value
        await update.message.reply_text("✅ API ключ установлен.")
    elif key == "temperature":
        try:
            SESSION_DATA[session_id]["temperature"] = float(value)
            await update.message.reply_text("✅ Temperature обновлен.")
        except ValueError:
            await update.message.reply_text("⚠️ Укажите число.")
    elif key == "max_tokens":
        if value.isdigit():
            SESSION_DATA[session_id]["max_tokens"] = int(value)
            await update.message.reply_text("✅ Max tokens обновлен.")
        else:
            await update.message.reply_text("⚠️ Укажите число.")
    elif key == "system_prompt":
        SESSION_DATA[session_id]["system_prompt"] = value
        await update.message.reply_text("✅ System prompt обновлен.")
    elif key == "model":
        if value in sum(VALID_MODELS.values(), []):
            model = next(k for k in VALID_MODELS if value in VALID_MODELS[k])
            SESSION_DATA[session_id]["model"] = model
            await update.message.reply_text(f"✅ Модель обновлена на {model}.")
        else:
            await update.message.reply_text("⚠️ Модель не найдена.")
    else:
        await update.message.reply_text("⚠️ Неизвестная настройка.")

@get_session_id
async def command_show(update: Update, context: CallbackContext, session_id):
    session = SESSION_DATA.get(session_id, {})
    summary = "**Session Data:**
"
    for k, v in session.items():
        if k != "chat_history":
            summary += f"{k}: {v}
"
    summary += "
**Chat History:**
"
    for entry in session.get("chat_history", []):
        role = entry["role"]
        content = entry["content"]
        if isinstance(content, list):
            for item in content:
                if item["type"] == "text":
                    summary += f"{role}: {item['text']}
"
                elif item["type"] == "image_url":
                    summary += f"{role}: <Image>
"
        else:
            summary += f"{role}: {content}
"
    for chunk in [summary[i:i+4000] for i in range(0, len(summary), 4000)]:
        await update.message.reply_text(chunk)

async def command_help(update: Update, context: CallbackContext):
    await update.message.reply_text(
        "<b>Команды:</b>
"
        "/start — начать
"
        "/reset — сбросить настройки
"
        "/clear — очистить историю
"
        "/set — изменить параметры
"
        "/show — показать текущие данные
"
        "/help — помощь",
        parse_mode=ParseMode.HTML
    )

def register_handlers(app):
    app.add_handlers(handlers={
        -1: [
            CommandHandler("start", command_start),
            CommandHandler("reset", command_reset),
            CommandHandler("clear", command_clear),
            CommandHandler("set", command_set),
            CommandHandler("show", command_show),
            CommandHandler("help", command_help)
        ],
        1: [MessageHandler(filters.ALL & ~filters.COMMAND, handle_message)]
    })

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING)

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    register_handlers(app)

    print("Бот запущен.")
    app.run_polling()

if __name__ == "__main__":
    main()
