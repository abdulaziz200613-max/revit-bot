import base64
import httpx
from datetime import date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CommandHandler,
    CallbackQueryHandler, PreCheckoutQueryHandler,
    filters, ContextTypes
)
from groq import Groq

# ─── ЗАМЕНИ НА СВОИ КЛЮЧИ ───
TELEGRAM_TOKEN = "7852802734:AAHiwDIQ81jzJTDwK99h4FfWiHG-qayqvWI"
GROQ_KEY       = "gsk_paXjeQ4jMioHlL16GTzlWGdyb3FYVhMLYAGinQ7L4ZkS8wZeR81"
# ────────────────────────────

groq_client = Groq(api_key=GROQ_KEY)

user_data = {}
user_histories = {}
FREE_LIMIT = 10
PREMIUM_PRICE_STARS = 150

SYSTEM_PROMPT = """Ты — RevitHelper, эксперт по Autodesk Revit.
Помогаешь архитекторам решать любые задачи в Revit, включая неофициальные версии.
Отвечай на языке пользователя: русский → по-русски, English → in English, O'zbek → o'zbekcha.
Давай пошаговые инструкции с эмодзи (📌 шаг, ✅ готово, ⚠️ важно, 💡 совет)."""

# ─── База программ и семейств ───
PROGRAMS = {
    "revit2024": {
        "name": "Autodesk Revit 2024",
        "size": "18 GB (2 части по 2 GB)",
        "files": []  # сюда добавим file_id
    },
    "autocad2024": {
        "name": "AutoCAD 2024",
        "size": "5 GB",
        "files": []  # сюда добавим file_id
    }
}


def get_user(uid):
    if uid not in user_data:
        user_data[uid] = {"premium": False, "questions_today": 0, "last_date": str(date.today())}
    u = user_data[uid]
    if u["last_date"] != str(date.today()):
        u["questions_today"] = 0
        u["last_date"] = str(date.today())
    return u


def premium_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⭐ Купить Premium — 150 Stars", callback_data="buy_premium")
    ]])


def programs_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Autodesk Revit 2024", callback_data="dl_revit2024")],
        [InlineKeyboardButton("📦 AutoCAD 2024", callback_data="dl_autocad2024")],
    ])


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    status = "⭐ Premium" if u["premium"] else f"🆓 Бесплатно ({FREE_LIMIT - u['questions_today']}/{FREE_LIMIT} вопросов)"
    await update.message.reply_text(
        f"🏗️ Привет! Я *RevitHelper* — AI помощник по Autodesk Revit.\n\n"
        f"✅ Отвечаю на вопросы по Revit\n"
        f"✅ Пошаговые инструкции\n"
        f"✅ Объясняю ошибки\n"
        f"✅ Читаю скриншоты\n"
        f"✅ Скачать Revit и AutoCAD\n"
        f"✅ Русский / English / O'zbek\n\n"
        f"Статус: {status}\n\n"
        f"Просто напиши вопрос или отправь скриншот ⬇️",
        parse_mode="Markdown"
    )


async def cmd_download(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📦 *Скачать программы*\n\nВыбери что хочешь скачать:",
        parse_mode="Markdown",
        reply_markup=programs_keyboard()
    )


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if u["premium"]:
        text = "⭐ *Premium активен* — безлимитные вопросы!"
    else:
        left = FREE_LIMIT - u["questions_today"]
        text = f"🆓 Осталось вопросов сегодня: *{left}/{FREE_LIMIT}*"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=premium_keyboard())


async def get_file_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    await update.message.reply_text(
        f"📁 *{doc.file_name}*\n\n`{doc.file_id}`",
        parse_mode="Markdown"
    )


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = get_user(uid)
    text = update.message.text.lower()

    # Проверка на запрос скачивания
    if any(word in text for word in ["скачать", "download", "revit", "autocad"]):
        await update.message.reply_text(
            "📦 Выбери программу для скачивания:",
            reply_markup=programs_keyboard()
        )
        return

    if not u["premium"] and u["questions_today"] >= FREE_LIMIT:
        await update.message.reply_text(
            "⛔ *Лимит исчерпан!*\n\nБесплатно: 10 вопросов в день.\nПерейди на Premium 👇",
            parse_mode="Markdown", reply_markup=premium_keyboard()
        )
        return

    if uid not in user_histories:
        user_histories[uid] = []

    user_histories[uid].append({"role": "user", "content": update.message.text})
    history = user_histories[uid][-10:]

    msg = await update.message.reply_text("⏳ Думаю...")
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + history,
            max_tokens=1024
        )
        answer = response.choices[0].message.content
        user_histories[uid].append({"role": "assistant", "content": answer})
        u["questions_today"] += 1

        if not u["premium"]:
            left = FREE_LIMIT - u["questions_today"]
            if left <= 3:
                answer += f"\n\n_💡 Осталось вопросов: {left}/10_"

        await msg.delete()
        await update.message.reply_text(answer, parse_mode="Markdown")
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")


async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = get_user(uid)

    if not u["premium"] and u["questions_today"] >= FREE_LIMIT:
        await update.message.reply_text(
            "⛔ *Лимит исчерпан!*\n\nПерейди на Premium 👇",
            parse_mode="Markdown", reply_markup=premium_keyboard()
        )
        return

    msg = await update.message.reply_text("⏳ Анализирую скриншот...")
    try:
        photo = update.message.photo[-1]
        tg_file = await ctx.bot.get_file(photo.file_id)

        async with httpx.AsyncClient() as client:
            resp = await client.get(tg_file.file_path)
            image_data = base64.b64encode(resp.content).decode()

        caption = update.message.caption or "Что изображено? Это связано с Revit? Помоги разобраться."

        response = groq_client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": SYSTEM_PROMPT + "\n\n" + caption},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}}
                ]
            }],
            max_tokens=1024
        )
        answer = response.choices[0].message.content
        u["questions_today"] += 1
        await msg.delete()
        await update.message.reply_text(answer, parse_mode="Markdown")
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")


async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "buy_premium":
        await ctx.bot.send_invoice(
            chat_id=q.from_user.id,
            title="RevitHelper Premium",
            description="Безлимитные вопросы по Revit",
            payload="premium",
            currency="XTR",
            prices=[LabeledPrice("Premium", PREMIUM_PRICE_STARS)],
            provider_token=""
        )

    elif q.data == "dl_revit2024":
        prog = PROGRAMS["revit2024"]
        if not prog["files"]:
            await q.message.reply_text("⏳ Файлы скоро будут добавлены! Следи за обновлениями.")
        else:
            await q.message.reply_text(f"📦 *{prog['name']}*\n💾 Размер: {prog['size']}\n\nОтправляю файлы...", parse_mode="Markdown")
            for file_id in prog["files"]:
                await ctx.bot.send_document(chat_id=q.from_user.id, document=file_id)

    elif q.data == "dl_autocad2024":
        prog = PROGRAMS["autocad2024"]
        if not prog["files"]:
            await q.message.reply_text("⏳ Файлы скоро будут добавлены! Следи за обновлениями.")
        else:
            await q.message.reply_text(f"📦 *{prog['name']}*\n💾 Размер: {prog['size']}\n\nОтправляю файлы...", parse_mode="Markdown")
            for file_id in prog["files"]:
                await ctx.bot.send_document(chat_id=q.from_user.id, document=file_id)


async def pre_checkout(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)


async def payment_success(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    get_user(update.effective_user.id)["premium"] = True
    await update.message.reply_text("🎉 *Premium активирован!* Теперь вопросы без лимита!", parse_mode="Markdown")


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("download", cmd_download))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, get_file_id))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, payment_success))
    print("🚀 RevitHelper запущен!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
