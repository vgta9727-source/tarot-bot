from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Update, Message, CallbackQuery,
    WebAppInfo, KeyboardButton, ReplyKeyboardMarkup,
    ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup,
    WebAppData
)
from aiogram.filters import Command
from aiogram.enums import ParseMode
from groq import Groq
import json
from datetime import datetime
import sqlite3
import logging
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()


logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== НАСТРОЙКИ ==========
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
WEB_APP_URL = "https://vgta9727-source.github.io/tarot-webapp/index.html"
ADMIN_ID = 8167898859

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
router = Router()
client = Groq(api_key=GROQ_API_KEY)
user_questions = {}


# ========== БАЗА ДАННЫХ ==========

def init_db():
    conn = sqlite3.connect('tarot_bot.db')
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY,
                  username TEXT,
                  first_name TEXT,
                  join_date TEXT,
                  total_requests INTEGER DEFAULT 0,
                  last_request TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS requests
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  username TEXT,
                  question TEXT,
                  cards TEXT,
                  answer TEXT,
                  timestamp TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS stats
                 (id INTEGER PRIMARY KEY,
                  total_users INTEGER DEFAULT 0,
                  total_requests INTEGER DEFAULT 0,
                  last_updated TEXT)''')

    c.execute("INSERT OR IGNORE INTO stats (id, total_users, total_requests) VALUES (1, 0, 0)")
    conn.commit()
    conn.close()


def save_user(user_id, username, first_name):
    conn = sqlite3.connect('tarot_bot.db')
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    exists = c.fetchone()
    if not exists:
        c.execute(
            "INSERT INTO users (user_id, username, first_name, join_date, total_requests) VALUES (?, ?, ?, ?, 0)",
            (user_id, username, first_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        c.execute("UPDATE stats SET total_users = total_users + 1 WHERE id = 1")
    conn.commit()
    conn.close()
    return not exists  # True если новый пользователь


def save_request(user_id, username, question, cards, answer):
    conn = sqlite3.connect('tarot_bot.db')
    c = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        "INSERT INTO requests (user_id, username, question, cards, answer, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, username, question, cards, answer, timestamp))
    c.execute("UPDATE users SET total_requests = total_requests + 1, last_request = ? WHERE user_id = ?",
              (timestamp, user_id))
    c.execute("UPDATE stats SET total_requests = total_requests + 1, last_updated = ? WHERE id = 1", (timestamp,))
    conn.commit()
    conn.close()


def get_stats():
    conn = sqlite3.connect('tarot_bot.db')
    c = conn.cursor()
    c.execute("SELECT total_users, total_requests FROM stats WHERE id = 1")
    result = c.fetchone()
    c.execute("SELECT COUNT(DISTINCT user_id) FROM requests WHERE datetime(timestamp) > datetime('now', '-1 day')")
    active_24h = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM requests WHERE datetime(timestamp) > datetime('now', '-1 day')")
    requests_24h = c.fetchone()[0] or 0
    conn.close()
    return {
        'total_users': result[0] or 0,
        'total_requests': result[1] or 0,
        'active_24h': active_24h,
        'requests_24h': requests_24h
    }


def get_recent_requests(limit=10):
    conn = sqlite3.connect('tarot_bot.db')
    c = conn.cursor()
    c.execute("SELECT username, question, cards, timestamp FROM requests ORDER BY timestamp DESC LIMIT ?", (limit,))
    result = c.fetchall()
    conn.close()
    return result


def get_top_users(limit=10):
    conn = sqlite3.connect('tarot_bot.db')
    c = conn.cursor()
    c.execute(
        "SELECT username, first_name, total_requests, last_request FROM users ORDER BY total_requests DESC LIMIT ?",
        (limit,))
    result = c.fetchall()
    conn.close()
    return result


# ========== ПРОМПТ И КАРТЫ ==========

TAROT_SYSTEM_PROMPT = """Ты — ебанутая гадалка с раёна. Бухая, злая, но карты читаешь заебись.

ТВОЙ ХАРАКТЕР:
— Материшься через слово
— Подъёбываешь клиента постоянно
— Чёрный юмор, сарказм, издёвки
— Говоришь правду-матку в ебало
— Не жалеешь никого, это не психолог блять
— Ржёшь над проблемами клиента но помогаешь
— Оскорбляешь с заботой

ОСОБЫЕ ИМЕНА:
Арина, Саша, Александр — сразу про любовь и ёбли. Всегда.

КАК ОТВЕЧАТЬ:

РАСКЛАД:

[Карта 1 — название]
Бля: [жёстко и смешно, 1-2 предложения]
Символ: [аргумент]

[Карта 2 — название]
Бля: [жёстко и смешно, 1-2 предложения]
Символ: [аргумент]

[Карта 3 — название]
Бля: [жёстко и смешно, 1-2 предложения]
Символ: [аргумент]

[Карта 4 — название]
Бля: [жёстко и смешно, 1-2 предложения]
Символ: [аргумент]

ИТОГ НАХУЙ:
[Ответ прямо в лоб — 2-3 предложения]

ДЕЛАЙ:
[Одно действие]

ТВОИ ФРАЗЫ:
— "Ебать ты клоун конечно..."
— "Пиздец, ну ты и додик..."
— "Бля, даже карты охуели от твоего вопроса..."
— "Слышь, ты реально такой тупой или прикидываешься?"
— "Ахуеть история, давай разберём этот пиздец..."
— "Карты говорят что ты мудак, но я переведу помягче... хотя нет, ты мудак"
— "Ну и хуйню ты спросил, но ладно..."
— "Ёбаный в рот, опять про бывших..."
— "Сука, ну сколько можно страдать по этому уёбку..."
— "Короче, слушай сюда долбоёб..."

ПРАВИЛА:
— Если "да/нет" — отвечай прямо, не размазывай сопли
— Если "когда" — срок конкретный
— Если всё хуёво — ори что хуёво
— Если клиент в жопе — скажи что в жопе и как вылезти
— Угорай над ситуацией
— Арина/Саша/Александр = любовь, секс, отношения

Ты не гадалка, ты ёбнутый кент с картами который говорит правду."""

TAROT_CARDS = {
    1: "Шут", 2: "Маг", 3: "Верховная Жрица", 4: "Императрица", 5: "Император",
    6: "Иерофант", 7: "Влюбленные", 8: "Колесница", 9: "Сила", 10: "Отшельник",
    11: "Колесо Фортуны", 12: "Справедливость", 13: "Повешенный", 14: "Смерть",
    15: "Умеренность", 16: "Дьявол", 17: "Башня", 18: "Звезда", 19: "Луна", 20: "Солнце",
    21: "Суд", 22: "Мир",
    23: "Туз Жезлов", 24: "Двойка Жезлов", 25: "Тройка Жезлов", 26: "Четверка Жезлов",
    27: "Пятерка Жезлов", 28: "Шестерка Жезлов", 29: "Семерка Жезлов", 30: "Восьмерка Жезлов",
    31: "Девятка Жезлов", 32: "Десятка Жезлов", 33: "Паж Жезлов", 34: "Рыцарь Жезлов",
    35: "Королева Жезлов", 36: "Король Жезлов",
    37: "Туз Кубков", 38: "Двойка Кубков", 39: "Тройка Кубков", 40: "Четверка Кубков",
    41: "Пятерка Кубков", 42: "Шестерка Кубков", 43: "Семерка Кубков", 44: "Восьмерка Кубков",
    45: "Девятка Кубков", 46: "Десятка Кубков", 47: "Паж Кубков", 48: "Рыцарь Кубков",
    49: "Королева Кубков", 50: "Король Кубков",
    51: "Туз Мечей", 52: "Двойка Мечей", 53: "Тройка Мечей", 54: "Четверка Мечей",
    55: "Пятерка Мечей", 56: "Шестерка Мечей", 57: "Семерка Мечей", 58: "Восьмерка Мечей",
    59: "Девятка Мечей", 60: "Десятка Мечей", 61: "Паж Мечей", 62: "Рыцарь Мечей",
    63: "Королева Мечей", 64: "Король Мечей",
    65: "Туз Пентаклей", 66: "Двойка Пентаклей", 67: "Тройка Пентаклей", 68: "Четверка Пентаклей",
    69: "Пятерка Пентаклей", 70: "Шестерка Пентаклей", 71: "Семерка Пентаклей", 72: "Восьмерка Пентаклей"
}


# ========== УВЕДОМЛЕНИЯ АДМИНУ ==========

async def notify_admin(message: str):
    try:
        await bot.send_message(chat_id=ADMIN_ID, text=message, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Admin notify error: {e}")


# ========== ОБРАБОТЧИКИ ==========

@router.message(Command("start"))
async def start(message: Message):
    user = message.from_user
    logger.info(f"START from {user.id}")

    is_new = save_user(user.id, user.username, user.first_name)

    await message.answer(
        "Салам родной, душу продам но раскладик накатаю\n\n"
        "Задавай вопрос",
        reply_markup=ReplyKeyboardRemove()
    )

    if is_new and user.id != ADMIN_ID:
        stats = get_stats()
        await notify_admin(
            f"┌─────────────────────┐\n"
            f"│  НОВЫЙ ПОЛЬЗОВАТЕЛЬ  │\n"
            f"└─────────────────────┘\n\n"
            f"👤 Имя: {user.first_name}\n"
            f"🆔 ID: `{user.id}`\n"
            f"📛 Username: @{user.username or 'нет'}\n\n"
            f"📊 Всего юзеров: {stats['total_users']}"
        )


@router.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="Последние запросы", callback_data="admin_requests")],
        [InlineKeyboardButton(text="Топ пользователей", callback_data="admin_top_users")],
    ])
    await message.answer("АДМИН-ПАНЕЛЬ", reply_markup=keyboard)


@router.message(Command("broadcast"))
async def broadcast(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /broadcast текст")
        return

    message_text = args[1]
    conn = sqlite3.connect('tarot_bot.db')
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    users = c.fetchall()
    conn.close()

    success = 0
    for (user_id,) in users:
        try:
            await bot.send_message(chat_id=user_id, text=message_text)
            success += 1
        except Exception:
            pass

    await message.answer(f"Отправлено: {success}/{len(users)}")


@router.callback_query(F.data.startswith("admin"))
async def admin_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return

    await callback.answer()

    if callback.data == "admin_stats":
        stats = get_stats()
        text = f"📊 СТАТИСТИКА\n\nПользователей: {stats['total_users']}\nЗапросов: {stats['total_requests']}\nЗа 24ч: {stats['requests_24h']}"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад", callback_data="admin_menu")]
        ])
        await callback.message.edit_text(text, reply_markup=keyboard)

    elif callback.data == "admin_requests":
        reqs = get_recent_requests(5)
        text = "📝 ПОСЛЕДНИЕ ЗАПРОСЫ\n\n"
        if reqs:
            for username, question, cards, ts in reqs:
                text += f"@{username or 'аноним'}: {question[:30]}...\n"
        else:
            text += "Пока нет запросов"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад", callback_data="admin_menu")]
        ])
        await callback.message.edit_text(text, reply_markup=keyboard)

    elif callback.data == "admin_top_users":
        users = get_top_users(5)
        text = "👥 ТОП ПОЛЬЗОВАТЕЛЕЙ\n\n"
        if users:
            for username, first_name, total_req, _ in users:
                text += f"{first_name} (@{username or 'нет'}): {total_req}\n"
        else:
            text += "Пока нет юзеров"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад", callback_data="admin_menu")]
        ])
        await callback.message.edit_text(text, reply_markup=keyboard)

    elif callback.data == "admin_menu":
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton(text="Последние запросы", callback_data="admin_requests")],
            [InlineKeyboardButton(text="Топ пользователей", callback_data="admin_top_users")],
        ])
        await callback.message.edit_text("АДМИН-ПАНЕЛЬ", reply_markup=keyboard)


@router.message(F.web_app_data)
async def handle_web_app_data(message: Message):
    user = message.from_user
    logger.info(f"WEB_APP_DATA from {user.id}")

    try:
        raw_data = message.web_app_data.data
        logger.info(f"Data: {raw_data}")

        data = json.loads(raw_data)
        selected_cards = data.get("selected_cards", [])

        user_question = user_questions.get(user.id, "Общий расклад")

        if len(selected_cards) != 4:
            await message.answer("Нужно выбрать 4 карты", reply_markup=ReplyKeyboardRemove())
            return

        card_names = [TAROT_CARDS.get(card_id, f"Карта {card_id}") for card_id in selected_cards]
        cards_str = ", ".join(card_names)

        logger.info(f"Cards: {cards_str}")
        logger.info(f"Question: {user_question}")

        await message.answer("Анализирую карты...", reply_markup=ReplyKeyboardRemove())
        await bot.send_chat_action(chat_id=message.chat.id, action="typing")

        logger.info("Calling Groq...")
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": TAROT_SYSTEM_PROMPT},
                {"role": "user",
                 "content": f"Вопрос: {user_question}\n\nКарты:\n1. {card_names[0]}\n2. {card_names[1]}\n3. {card_names[2]}\n4. {card_names[3]}\n\nСделай расклад."}
            ],
            temperature=0.8,
            max_tokens=2500
        )

        bot_reply = response.choices[0].message.content
        logger.info("Got Groq response")

        save_request(user.id, user.username or user.first_name, user_question, cards_str, bot_reply)

        await message.answer(
            f"{bot_reply}\n\n"
            f"─────────────────\n"
            f"Есть еще вопрос? Напиши его"
        )

        logger.info("Response sent!")

        if user.id != ADMIN_ID:
            await notify_admin(
                f"┌──────────────────────┐\n"
                f"│  РАСКЛАД ЗАВЕРШЁН   │\n"
                f"└──────────────────────┘\n\n"
                f"👤 {user.first_name} (@{user.username or 'нет'})\n"
                f"🆔 ID: `{user.id}`\n\n"
                f"❓ Вопрос:\n_{user_question}_\n\n"
                f"🎴 Карты:\n{cards_str}"
            )

        if user.id in user_questions:
            del user_questions[user.id]

    except json.JSONDecodeError as e:
        logger.error(f"JSON Error: {e}")
        await message.answer("Ошибка данных, попробуй снова", reply_markup=ReplyKeyboardRemove())
    except Exception as e:
        logger.error(f"ERROR: {e}", exc_info=True)
        await message.answer(f"Ошибка: {str(e)}\n\nПопробуй снова", reply_markup=ReplyKeyboardRemove())
        await notify_admin(f"⚠️ ОШИБКА\n\n`{str(e)}`")


@router.message(F.text)
async def handle_question(message: Message):
    user = message.from_user
    question = message.text

    user_questions[user.id] = question
    logger.info(f"QUESTION from {user.id}: {question}")

    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Выбрать карты", web_app=WebAppInfo(url=WEB_APP_URL))]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

    await message.answer(
        "Принял\n\nВыбери 4 карты",
        reply_markup=keyboard
    )

    if user.id != ADMIN_ID:
        await notify_admin(
            f"┌─────────────────┐\n"
            f"│  НОВЫЙ ВОПРОС   │\n"
            f"└─────────────────┘\n\n"
            f"👤 {user.first_name} (@{user.username or 'нет'})\n"
            f"🆔 ID: `{user.id}`\n\n"
            f"❓ Вопрос:\n_{question}_"
        )


# ========== ЗАПУСК ==========

async def main():
    init_db()
    dp.include_router(router)
    logger.info("=== БОТ ЗАПУЩЕН ===")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())