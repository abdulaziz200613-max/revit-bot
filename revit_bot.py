import os
import base64
import logging
from datetime import date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CommandHandler,
    CallbackQueryHandler, PreCheckoutQueryHandler,
    filters, ContextTypes
)
from telegram.constants import ParseMode
from groq import Groq

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GROQ_KEY = os.environ.get("GROQ_API_KEY")

if not TELEGRAM_TOKEN:
    raise ValueError("[ENV ERROR] TELEGRAM_BOT_TOKEN не задан!")
if not GROQ_KEY:
    raise ValueError("[ENV ERROR] GROQ_API_KEY не задан!")

groq_client = Groq(api_key=GROQ_KEY)

user_data = {}
user_histories = {}
FREE_LIMIT = 10
PREMIUM_PRICE_STARS = 150

SYSTEM_PROMPT = """Ты — RevitHelper, эксперт по Autodesk Revit.
Помогаешь архитекторам решать любые задачи в Revit, включая неофициальные версии.
Отвечай на языке пользователя: русский → по-русски, English → in English, O'zbek → o'zbekcha.
Давай пошаговые инструкции с эмодзи (📌 шаг, ✅ готово, ⚠️ важно, 💡 совет)."""

PROGRAMS = {
    "revit2024": {
        "name": "Autodesk Revit 2024",
        "size": "5 частей",
        "files": [
            "BQACAgIAAyEFAATGL8pEAAMdapbG2B2Amdb2pOYMvFf7hks7ZtsAAv6gAAIwA7lIp07c6mCf1O89BA",
            "BQACAgIAAyEFAATGL8pEAAMcapbG2IxxaaDnLgSm4eHCFDtYe3oAAvmgAAIwA7lIwjPD3QddK6A9BA",
            "BQACAgIAAyEFAATGL8pEAAMbapbG2DtYnqDXYM_pOTWRmgnN594AAvOgAAIwA7lICAHU2QQg-GA9BA",
            "BQACAgIAAyEFAATGL8pEAAMaapbG2CuRl2GpccZ9Mym_w1y12qYAAvCgAAIwA7lIzzExvuw2gg09BA",
            "BQACAgIAAyEFAATGL8pEAAMZapbG2FUn3-uZEKCRpFAzUH9B75oAAuygAAIwA7lIkXf1Io7GTAo9BA",
        ]
    },
    "autocad2024": {
        "name": "AutoCAD 2024",
        "size": "1 файл",
        "files": [
            "BQACAgIAAyEFAATGL8pEAAMXapa_RoUjxqrj92zViPkxCtKHURMAAn-gAAIwA7lIseQfX-YdcJg9BA",
        ]
    }
}

TEMPLATES = {
    "ar2019": {
        "name": "Шаблон АР 2019",
        "file_id": "BQACAgIAAyEFAATp6iuHAAMEapbI2u5jPC8VYWMzxycGPxbkgzIAAsabAALYG7lI7W3Vx12J4Sg9BA"
    },
    "interior": {
        "name": "Шаблон Интерьер",
        "file_id": "BQACAgIAAyEFAATp6iuHAAMFapbJdGQcAZ01pQ7tCkuOxWIykfAAAsmbAALYG7lIiYceZOYaKb89BA"
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


def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Скачать программы", callback_data="menu_programs")],
        [InlineKeyboardButton("📐 Шаблоны Revit", callback_data="menu_templates")],
        [InlineKeyboardButton("❓ Задать вопрос по Revit", callback_data="menu_ask")],
        [InlineKeyboardButton("⭐ Premium — безлимит", callback_data="buy_premium")],
        [InlineKeyboardButton("📊 Мой статус", callback_data="menu_status")],
    ])


def programs_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏗️ Autodesk Revit 2024", callback_data="dl_revit2024")],
        [InlineKeyboardButton("📐 AutoCAD 2024", callback_data="dl_autocad2024")],
        [InlineKeyboardButton("🔙 Назад", callback_data="menu_main")],
    ])


def templates_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏛️ Шаблон АР 2019", callback_data="tpl_ar2019")],
        [InlineKeyboardButton("🛋️ Шаблон Интерьер", callback_data="tpl_interior")],
        [InlineKeyboardButton("🔙 Назад", callback_data="menu_main")],
    ])


def premium_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ Купить Premium — 150 Stars", callback_data="buy_premium")],
        [InlineKeyboardButton("🔙 Главное меню", callback_data="menu_main")],
    ])


async def safe_reply_text(msg, text, **kwargs):
    try:
        return await msg.reply_text(text, parse_mode=ParseMode.MARKDOWN, **kwargs)
    except Exception as e:
        logger.warning(f"[Markdown error] {e}")
        return await msg.reply_text(text, **kwargs)


async def safe_edit_text(msg, text, **kwargs):
    try:
        return await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN, **kwargs)
    except Exception as e:
        logger.warning(f"[Markdown edit error] {e}")
        return await msg.edit_text(text, **kwargs)


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = get_user(uid)
    status = "⭐ Premium" if u["premium"] else f"🆓 Бесплатно ({FREE_LIMIT - u['questions_today']}/{FREE_LIMIT} вопросов)"
    await safe_reply_text(
        update.message,
        f"🏗️ Привет! Я *RevitHelper* — AI помощник по Autodesk Revit.\n\n"
        f"Я умею:\n"
        f"✅ Отвечать на вопросы по Revit\n"
        f"✅ Давать пошаговые инструкции\n"
        f"✅ Объяснять ошибки\n"
        f"✅ Читать скриншоты\n"
        f"✅ Давать шаблоны Revit\n"
        f"✅ Скачать Revit и AutoCAD\n"
        f"✅ Русский / English / O'zbek\n\n"
        f"📊 Статус: {status}\n\n"
        f"Выбери что тебе нужно 👇",
        reply_markup=main_keyboard()
    )


async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await safe_reply_text(
        update.message,
        "🏗️ *Главное меню RevitHelper*\n\nВыбери что тебе нужно 👇",
        reply_markup=main_keyboard()
    )


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    if u["premium"]:
        text = "⭐ *Premium активен* — безлимитные вопросы!"
    else:
        left = FREE_LIMIT - u["questions_today"]
        text = f"🆓 Осталось вопросов сегодня: *{left}/{FREE_LIMIT}*"
    await safe_reply_text(update.message, text, reply_markup=premium_keyboard())


async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    u = get_user(uid)

    if q.data == "menu_main":
        status = "⭐ Premium" if u["premium"] else f"🆓 ({FREE_LIMIT - u['questions_today']}/{FREE_LIMIT} вопросов)"
        await safe_edit_text(
            q.message,
            f"🏗️ *Главное меню RevitHelper*\n📊 Статус: {status}\n\nВыбери что тебе нужно 👇",
            reply_markup=main_keyboard()
        )

    elif q.data == "menu_programs":
        await safe_edit_text(
            q.message,
            "📦 *Скачать программы*\n\nВыбери программу:",
            reply_markup=programs_keyboard()
        )

    elif q.data == "menu_templates":
        await safe_edit_text(
            q.message,
            "📐 *Шаблоны Revit*\n\nГотовые шаблоны для работы:\n\n"
            "🏛️ *АР 2019* — стандартный шаблон архитектурных решений\n"
            "🛋️ *Интерьер* — шаблон для интерьерных проектов\n\n"
            "Выбери шаблон 👇",
            reply_markup=templates_keyboard()
        )

    elif q.data == "menu_ask":
        await safe_edit_text(
            q.message,
            "❓ *Задать вопрос по Revit*\n\nПросто напиши свой вопрос или отправь скриншот — отвечу! 💬"
        )

    elif q.data == "menu_status":
        if u["premium"]:
            text = "⭐ *Premium активен* — безлимитные вопросы!"
        else:
            left = FREE_LIMIT - u["questions_today"]
            text = f"🆓 Осталось вопросов сегодня: *{left}/{FREE_LIMIT}*\n\nХочешь безлимит? 👇"
        await safe_edit_text(q.message, text, reply_markup=premium_keyboard())

    elif q.data == "dl_revit2024":
        prog = PROGRAMS["revit2024"]
        await safe_edit_text(
            q.message,
            f"📦 *{prog['name']}*\n📁 Состоит из {prog['size']}\n\n⏳ Отправляю файлы, подожди..."
        )
        for file_id in prog["files"]:
            await ctx.bot.send_document(chat_id=uid, document=file_id)
        await ctx.bot.send_message(
            chat_id=uid,
            text="✅ *Все части отправлены!*\n\n💡 Распакуй все части в одну папку и запусти установщик.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_keyboard()
        )

    elif q.data == "dl_autocad2024":
        prog = PROGRAMS["autocad2024"]
        await safe_edit_text(q.message, f"📦 *{prog['name']}*\n\n⏳ Отправляю файл...")
        for file_id in prog["files"]:
            await ctx.bot.send_document(chat_id=uid, document=file_id)
        await ctx.bot.send_message(
            chat_id=uid,
            text="✅ *Файл отправлен!*\n\n💡 Распакуй архив и запусти установщик.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_keyboard()
        )

    elif q.data == "tpl_ar2019":
        tpl = TEMPLATES["ar2019"]
        await safe_edit_text(q.message, f"📐 *{tpl['name']}*\n\n⏳ Отправляю...")
        await ctx.bot.send_document(chat_id=uid, document=tpl["file_id"])
        await ctx.bot.send_message(
            chat_id=uid,
            text="✅ *Шаблон отправлен!*\n\n💡 Скопируй файл в папку шаблонов Revit:\n`C:\\ProgramData\\Autodesk\\RVT 2024\\Templates\\Russian`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_keyboard()
        )

    elif q.data == "tpl_interior":
        tpl = TEMPLATES["interior"]
        await safe_edit_text(q.message, f"🛋️ *{tpl['name']}*\n\n⏳ Отправляю...")
        await ctx.bot.send_document(chat_id=uid, document=tpl["file_id"])
        await ctx.bot.send_message(
            chat_id=uid,
            text="✅ *Шаблон отправлен!*\n\n💡 Скопируй файл в папку шаблонов Revit:\n`C:\\ProgramData\\Autodesk\\RVT 2024\\Templates\\Russian`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_keyboard()
        )

    elif q.data == "buy_premium":
        await ctx.bot.send_invoice(
            chat_id=uid,
            title="RevitHelper Premium",
            description="Безлимитные вопросы по Revit навсегда",
            payload="premium",
            currency="XTR",
            prices=[LabeledPrice("Premium", PREMIUM_PRICE_STARS)],
            provider_token=""
        )


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = get_user(uid)

    if not u["premium"] and u["questions_today"] >= FREE_LIMIT:
        await safe_reply_text(
            update.message,
            "⛔ *Лимит исчерпан!*\n\nБесплатно: 10 вопросов в день.\nПерейди на Premium 👇",
            reply_markup=premium_keyboard()
        )
        return

    if uid not in user_histories:
        user_histories[uid] = []

    user_histories[uid].append({"role": "user", "content": update.message.text})
    history = user_histories[uid][-10:]

    msg = await update.message.reply_text("⏳ Думаю...")
    try:
        response = groq_client.chat.completions.create(
            model="openai/gpt-oss-120b",
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
        await safe_reply_text(update.message, answer, reply_markup=main_keyboard())
    except Exception as e:
        logger.error(f"[Groq error] {e}", exc_info=True)
        await msg.edit_text(f"❌ Ошибка: {e}")


async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = get_user(uid)

    if not u["premium"] and u["questions_today"] >= FREE_LIMIT:
        await safe_reply_text(
            update.message,
            "⛔ *Лимит исчерпан!*\n\nПерейди на Premium 👇",
            reply_markup=premium_keyboard()
        )
        return

    msg = await update.message.reply_text("⏳ Анализирую скриншот...")
    try:
        photo = update.message.photo[-1]
        tg_file = await ctx.bot.get_file(photo.file_id)

        import httpx
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
        await safe_reply_text(update.message, answer, reply_markup=main_keyboard())
    except Exception as e:
        logger.error(f"[Photo error] {e}", exc_info=True)
        await msg.edit_text(f"❌ Ошибка: {e}")


async def get_file_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    await safe_reply_text(update.message, f"📁 *{doc.file_name}*\n\n`{doc.file_id}`")


async def pre_checkout(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)


async def payment_success(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    get_user(update.effective_user.id)["premium"] = True
    await safe_reply_text(
        update.message,
        "🎉 *Premium активирован!*\n\nТеперь вопросы без лимита! 🚀",
        reply_markup=main_keyboard()
    )


def main():
    logger.info("[Startup] Запуск RevitHelper...")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, get_file_id))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, payment_success))
    logger.info("🚀 RevitHelper запущен!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
