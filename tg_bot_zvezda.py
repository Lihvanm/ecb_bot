import logging
import re
import os
import psycopg2
import asyncio  
from psycopg2.extras import DictCursor
from datetime import datetime, timedelta
from telegram import Update, ChatPermissions
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ParseMode

# Конфигурация
DATABASE_URL = os.getenv('DATABASE_URL')
BOT_TOKEN = os.getenv('BOT_TOKEN')
TARGET_GROUP_ID = int(os.getenv('TARGET_GROUP_ID', '-1001234567890'))
ALLOWED_USER = os.getenv('ALLOWED_USER', '@Muzikant1429')[1:]  # Убираем @
PINNED_DURATION = 2700  # 45 минут
BANNED_WORDS = {"бляд", "хуй", "пизд", "наху", "гандон", "пидр", "пидорас", "пидар", "шалав", "шлюх", "мразь", "мразо", "ебат"}
MESSENGER_KEYWORDS = {"t.me", "telegram", "whatsapp", "viber", "discord", "vk.com", "instagram", "facebook", "twitter", "youtube", "http", "www", ".com", ".ru", ".net", "tiktok"}
SPAM_LIMIT = 4
SPAM_INTERVAL = 30
MUTE_DURATION = 300  # 5 минут

# Инициализация
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Глобальные структуры
last_pinned = {}  # {chat_id: (timestamp, user_id)}
spam_control = {}  # {user_id: (count, last_time)}
banned_users = set()

# База данных
def init_db():
    with get_db_cursor() as cur:
        cur.execute('''
            CREATE TABLE IF NOT EXISTS pinned_messages (
                id SERIAL PRIMARY KEY,
                chat_id BIGINT,
                user_id BIGINT,
                username TEXT,
                message_text TEXT,
                timestamp BIGINT
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS active_users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                delete_count INTEGER,
                last_activity BIGINT
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS birthdays (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                birth_date TEXT,
                last_congratulated INTEGER
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS ban_list (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                ban_time BIGINT
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS ban_history (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                username TEXT,
                reason TEXT,
                timestamp BIGINT
            )
        ''')

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def get_db_cursor():
    conn = get_db_connection()
    return conn.cursor(cursor_factory=DictCursor)

# Проверка прав
async def is_authorized(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user:
        return False
    if user.username == ALLOWED_USER:
        return True
    member = await context.bot.get_chat_member(update.message.chat.id, user.id)
    return member.status in ["administrator", "creator"]

# Системные функции
async def delete_after(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay: int = 10):
    try:
        await asyncio.sleep(delay)
        await context.bot.delete_message(chat_id, message_id)
    except Exception as e:
        logger.error(f"Ошибка удаления: {e}")

# Основные обработчики
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user = message.from_user
    chat = message.chat
    text = message.text.lower()

    # Проверка бана
    if user.id in banned_users:
        await message.delete()
        return

    # Антимат
    if any(word in text for word in BANNED_WORDS):
        await message.delete()
        await context.bot.send_message(chat.id, "Использование мата запрещено!")
        await add_ban_history(user.id, user.username, "Мат")
        return

    # Антиреклама
    if any(keyword in text for keyword in MESSENGER_KEYWORDS):
        await message.delete()
        await context.bot.send_message(chat.id, "Реклама запрещена!")
        await add_ban_history(user.id, user.username, "Реклама")
        return

    # Антиспам
    now = time.time()
    user_stat = spam_control.get(user.id, (0, now))
    if now - user_stat[1] < SPAM_INTERVAL:
        if user_stat[0] >= SPAM_LIMIT:
            await message.delete()
            await context.bot.restrict_chat_member(chat.id, user.id, ChatPermissions(), until_date=now+MUTE_DURATION)
            await context.bot.send_message(chat.id, f"{user.name} замьючен за спам!")
            await add_ban_history(user.id, user.username, "Спам")
            spam_control[user.id] = (0, now)
            return
        spam_control[user.id] = (user_stat[0]+1, now)
    else:
        spam_control[user.id] = (1, now)

    # Обработка звезды часа
    if text.startswith(("звезда", "зч")) or "🌟" in text:
        if chat.id in last_pinned:
            last_time, last_user = last_pinned[chat.id]
            if now - last_time < PINNED_DURATION and user.id != last_user:
                await message.delete()
                await update_active_users(user.id, user.username)
                await context.bot.send_message(chat.id, "Спасибо за бдительность! Звезда уже закреплена.")
                return

        # Закрепление нового сообщения
        try:
            pinned = await message.pin()
            last_pinned[chat.id] = (now, user.id)
            context.job_queue.run_once(unpin_message, PINNED_DURATION, data={'chat_id': chat.id, 'message_id': pinned.message_id})
            
            # Пересылка в целевую группу
            if chat.id != TARGET_GROUP_ID:
                new_text = text.replace("🌟", "").strip()
                forwarded = await context.bot.send_message(TARGET_GROUP_ID, new_text)
                await forwarded.pin()
                
            # Сохранение в БД
            with get_db_cursor() as cur:
                cur.execute('''
                    INSERT INTO pinned_messages 
                    (chat_id, user_id, username, message_text, timestamp) 
                    VALUES (%s, %s, %s, %s, %s)
                ''', (chat.id, user.id, user.username, message.text, int(now)))
                
        except Exception as e:
            logger.error(f"Ошибка закрепления: {e}")

async def unpin_message(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    try:
        await context.bot.unpin_chat_message(data['chat_id'], data['message_id'])
    except Exception as e:
        logger.error(f"Ошибка открепления: {e}")

async def add_ban_history(user_id: int, username: str, reason: str):
    with get_db_cursor() as cur:
        cur.execute('''
            INSERT INTO ban_history 
            (user_id, username, reason, timestamp) 
            VALUES (%s, %s, %s, %s)
        ''', (user_id, username, reason, int(time.time())))

async def update_active_users(user_id: int, username: str):
    with get_db_cursor() as cur:
        cur.execute('''
            INSERT INTO active_users 
            (user_id, username, delete_count, last_activity) 
            VALUES (%s, %s, 1, %s)
            ON CONFLICT (user_id) 
            DO UPDATE SET delete_count = active_users.delete_count + 1, last_activity = %s
        ''', (user_id, username, int(time.time()), int(time.time())))

# Команды
async def reset_pin_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update, context):
        await update.message.reply_text("Нет прав!")
        return

    chat = update.message.chat
    try:
        await context.bot.unpin_all_chat_messages(chat.id)
        last_pinned.pop(chat.id, None)
        await update.message.reply_text("Таймер сброшен!")
    except Exception as e:
        logger.error(f"Ошибка сброса таймера: {e}")

async def delete_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update, context):
        await update.message.reply_text("Нет прав!")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Ответьте на сообщение для удаления")
        return

    try:
        await update.message.reply_to_message.delete()
        await update.message.delete()
    except Exception as e:
        logger.error(f"Ошибка удаления: {e}")

async def lider(update: Update, context: ContextTypes.DEFAULT_TYPE):
    days = int(context.args[0]) if context.args else 1
    with get_db_cursor() as cur:
        cur.execute('''
            SELECT user_id, username, COUNT(*) as count 
            FROM pinned_messages 
            WHERE timestamp > %s 
            GROUP BY user_id 
            ORDER BY count DESC 
            LIMIT 3
        ''', (int(time.time()) - days*86400,))
        results = cur.fetchall()

    text = f"Топ за {days} дней:\n"
    for idx, row in enumerate(results, 1):
        text += f"{idx}. @{row['username']} — {row['count']} звезд\n"
    await update.message.reply_text(text)

async def zh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = int(context.args[0]) if context.args else 10
    with get_db_cursor() as cur:
        cur.execute('''
            SELECT username, message_text 
            FROM pinned_messages 
            ORDER BY timestamp DESC 
            LIMIT %s
        ''', (count,))
        results = cur.fetchall()

    text = "Последние звезды:\n"
    for idx, row in enumerate(results, 1):
        text += f"{idx}. @{row['username']}: {row['message_text']}\n"
    await update.message.reply_text(text)

async def active(update: Update, context: ContextTypes.DEFAULT_TYPE):
    days = int(context.args[0]) if context.args else 1
    with get_db_cursor() as cur:
        cur.execute('''
            SELECT user_id, username, SUM(delete_count) as total 
            FROM active_users 
            WHERE last_activity > %s 
            GROUP BY user_id 
            ORDER BY total DESC 
            LIMIT 3
        ''', (int(time.time()) - days*86400,))
        results = cur.fetchall()

    text = f"Активные за {days} дней:\n"
    for idx, row in enumerate(results, 1):
        text += f"{idx}. @{row['username']} — {row['total']} удалений\n"
    await update.message.reply_text(text)

async def dr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not re.match(r"\d{2}\.\d{2}\.\d{4}", context.args[0]):
        await update.message.reply_text("Используйте: /dr ДД.ММ.ГГГГ")
        return

    birth_date = context.args[0]
    user = update.message.from_user
    with get_db_cursor() as cur:
        cur.execute('''
            INSERT INTO birthdays 
            (user_id, username, birth_date) 
            VALUES (%s, %s, %s) 
            ON CONFLICT (user_id) 
            DO UPDATE SET birth_date = %s
        ''', (user.id, user.username, birth_date, birth_date))
    await update.message.reply_text("Дата сохранена!")

async def druser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update, context):
        await update.message.reply_text("Нет прав!")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Ответьте на сообщение пользователя")
        return

    target = update.message.reply_to_message.from_user
    if not context.args or not re.match(r"\d{2}\.\d{2}\.\d{4}", context.args[0]):
        await update.message.reply_text("Укажите дату: /druser ДД.ММ.ГГГГ")
        return

    birth_date = context.args[0]
    with get_db_cursor() as cur:
        cur.execute('''
            INSERT INTO birthdays 
            (user_id, username, birth_date) 
            VALUES (%s, %s, %s) 
            ON CONFLICT (user_id) 
            DO UPDATE SET birth_date = %s
        ''', (target.id, target.username, birth_date, birth_date))
    await update.message.reply_text(f"Дата для {target.name} сохранена!")

async def get_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update, context):
        await update.message.reply_text("Нет прав!")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("Ответьте на сообщение пользователя")
        return

    user = update.message.reply_to_message.from_user
    await update.message.reply_text(f"ID: {user.id}\nUsername: @{user.username}")

async def birthday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = datetime.now().strftime("%d.%m")
    with get_db_cursor() as cur:
        cur.execute('''
            SELECT username FROM birthdays 
            WHERE SUBSTR(birth_date, 1, 5) = %s
        ''', (today,))
        users = cur.fetchall()

    if users:
        await update.message.reply_text(f"ДР сегодня у: {', '.join([u[0] for u in users])}")
    else:
        await update.message.reply_text("Сегодня ДР ни у кого нет.")

async def check_all_birthdays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_db_cursor() as cur:
        cur.execute('SELECT username, birth_date FROM birthdays')
        results = cur.fetchall()

    text = "Все ДР:\n"
    for row in results:
        text += f"@{row['username']} — {row['birth_date']}\n"
    await update.message.reply_text(text)

async def ban_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_db_cursor() as cur:
        cur.execute('SELECT username FROM ban_list')
        users = cur.fetchall()

    if users:
        await update.message.reply_text(f"Бан-лист: {', '.join([u[0] for u in users])}")
    else:
        await update.message.reply_text("Бан-лист пуст")

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update, context):
        await update.message.reply_text("Нет прав!")
        return

    user_id = None
    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
    elif context.args:
        user_id = int(context.args[0])

    if not user_id:
        await update.message.reply_text("Укажите пользователя")
        return

    try:
        await context.bot.ban_chat_member(update.message.chat.id, user_id)
        banned_users.add(user_id)
        with get_db_cursor() as cur:
            cur.execute('''
                INSERT INTO ban_list (user_id, username) 
                VALUES (%s, %s)
            ''', (user_id, update.message.reply_to_message.from_user.username))
        await update.message.reply_text("Пользователь забанен")
    except Exception as e:
        logger.error(f"Ошибка бана: {e}")

async def deban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_authorized(update, context):
        await update.message.reply_text("Нет прав!")
        return

    user_id = None
    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
    elif context.args:
        user_id = int(context.args[0])

    if not user_id:
        await update.message.reply_text("Укажите пользователя")
        return

    try:
        await context.bot.unban_chat_member(update.message.chat.id, user_id)
        banned_users.discard(user_id)
        with get_db_cursor() as cur:
            cur.execute('DELETE FROM ban_list WHERE user_id = %s', (user_id,))
        await update.message.reply_text("Пользователь разбанен")
    except Exception as e:
        logger.error(f"Ошибка разбана: {e}")

async def ban_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    days = int(context.args[0]) if context.args else 1
    with get_db_cursor() as cur:
        cur.execute('''
            SELECT username, reason, timestamp 
            FROM ban_history 
            WHERE timestamp > %s
        ''', (int(time.time()) - days*86400,))
        results = cur.fetchall()

    text = f"Баны за {days} дней:\n"
    for row in results:
        dt = datetime.fromtimestamp(row['timestamp']).strftime("%d.%m %H:%M")
        text += f"@{row['username']} — {row['reason']} ({dt})\n"
    await update.message.reply_text(text)

# Основная функция
async def main():
    init_db()
    application = Application.builder().token(BOT_TOKEN).build()

    # Регистрация всех команд
    application.add_handler(CommandHandler("timer", reset_pin_timer))
    application.add_handler(CommandHandler("del", delete_message))
    application.add_handler(CommandHandler("lider", lider))
    application.add_handler(CommandHandler("zh", zh))
    application.add_handler(CommandHandler("active", active))
    application.add_handler(CommandHandler("dr", dr))
    application.add_handler(CommandHandler("druser", druser))
    application.add_handler(CommandHandler("id", get_user_id))
    application.add_handler(CommandHandler("birthday", birthday))
    application.add_handler(CommandHandler("check_birthdays", check_all_birthdays))
    application.add_handler(CommandHandler("ban_list", ban_list))
    application.add_handler(CommandHandler("ban", ban_user))
    application.add_handler(CommandHandler("deban", deban_user))
    application.add_handler(CommandHandler("ban_history", ban_history))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Запуск бота
    await application.start()
    await application.updater.start_polling()
    logger.info("Бот запущен")

if __name__ == '__main__':
    asyncio.run(main())
