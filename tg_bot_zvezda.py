import logging
import re
import os
import time
import asyncio
import psycopg2
from psycopg2.extras import DictCursor
from datetime import datetime
from telegram import Update, ChatPermissions
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Получение переменных окружения
DATABASE_URL = os.getenv('DATABASE_URL')
BOT_TOKEN = os.getenv('BOT_TOKEN')
TARGET_GROUP_ID = int(os.getenv('TARGET_GROUP_ID'))

# Время в секундах (45 минут = 2700 секунд)
PINNED_DURATION = 2700

# Разрешенный пользователь для сброса таймера
ALLOWED_USER = "@Muzikant1429"

# Список запрещенных слов (антимат)
BANNED_WORDS = ["бляд", "хуй", "пизд", "наху", "гандон", "пидр", "пидорас", "пидар", "шалав", "шлюх", "мразь", "мразо", "ебат"]

# Ключевые слова для мессенджеров и ссылок
MESSENGER_KEYWORDS = [
    "t.me", "telegram", "whatsapp", "viber", "discord", "vk.com", "instagram",
    "facebook", "twitter", "youtube", "http", "www", ".com", ".ru", ".net", "tiktok"
]

# Лимиты для антиспама
SPAM_LIMIT = 4  # Максимальное количество сообщений
SPAM_INTERVAL = 30  # Интервал в секундах
MUTE_DURATION = 360  # Время мута в секундах (5 минут)

# Глобальные переменные
last_pinned_times = {}  # {chat_id: timestamp}
last_user_username = {}  # {chat_id: username}
last_zch_times = {}  # {chat_id: timestamp}
last_thanks_times = {}  # {chat_id: timestamp}
pinned_messages = {}  # {chat_id: message_id}
db_initialized = False  # Глобальный флаг
banned_users = set()  # Бан-лист

# Функция для подключения к базе данных
def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    conn.cursor_factory = DictCursor
    return conn

# Инициализация базы данных
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
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
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            username TEXT,
            delete_count INTEGER,
            timestamp BIGINT
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS birthdays (
            id SERIAL PRIMARY KEY,
            user_id BIGINT UNIQUE,
            username TEXT,
            birth_date TEXT,
            last_congratulated_year INTEGER
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS ban_list (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            username TEXT,
            phone TEXT,
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
    conn.commit()
    cur.close()
    conn.close()

# Проверка прав администратора
async def is_admin_or_musician(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.message.from_user
    chat_id = update.message.chat.id

    try:
        chat_member = await context.bot.get_chat_member(chat_id, user.id)
        if chat_member.status in ["administrator", "creator"]:
            return True
    except Exception as e:
        logger.error(f"Ошибка при проверке прав пользователя {user.id}: {e}")

    if user.username == ALLOWED_USER[1:]:
        return True

    return False

# Удаление системных сообщений через указанное время
async def delete_system_message(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    try:
        await context.bot.delete_message(chat_id=job.chat_id, message_id=job.data)
    except Exception as e:
        logger.error(f"Ошибка при удалении системного сообщения: {e}")

# Команда /timer
async def reset_pin_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat.id
    user = update.message.from_user

    if not await is_admin_or_musician(update, context):
        response = await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        context.job_queue.run_once(delete_system_message, 10, data=response.message_id, chat_id=chat_id)
        await update.message.delete()
        return

    last_pinned_times[chat_id] = 0

    try:
        await context.bot.unpin_all_chat_messages(chat_id=chat_id)
        logger.info(f"Откреплены все сообщения в группе {chat_id}.")
    except Exception as e:
        logger.error(f"Ошибка при откреплении сообщений в группе {chat_id}: {e}")

    success_message = await update.message.reply_text("Таймер закрепа успешно сброшен.")
    context.job_queue.run_once(delete_system_message, 10, data=success_message.message_id, chat_id=chat_id)
    await update.message.delete()

# Обработчик новых сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user = message.from_user
    chat_id = message.chat.id
    text = message.text
    current_time = int(time.time())

    # Проверка на бан в базе бота
    if user.id in banned_users:
        try:
            await message.delete()
        except Exception as e:
            logger.error(f"Ошибка удаления: {e}")
        return

    # Игнорируем сообщения не из групп/супергрупп
    if message.chat.type not in ['group', 'supergroup']:
        return

    # Проверка на маркер "зч" или "🌟"
    if not text.lower().startswith(("звезда", "зч")) and "🌟" not in text:
        return

    # Проверка на антимат и антирекламу
    if not await is_admin_or_musician(update, context):
        # Антимат
        if any(word in text.lower() for word in BANNED_WORDS):
            await message.delete()
            warning_message = await context.bot.send_message(
                chat_id=chat_id,
                text="Использование нецензурных выражений недопустимо!"
            )
            context.job_queue.run_once(delete_system_message, 10, data=warning_message.message_id, chat_id=chat_id)
            return

        # Антиреклама
        if any(re.search(rf"\b{re.escape(keyword)}\b", text.lower()) for keyword in MESSENGER_KEYWORDS):
            await message.delete()
            warning_message = await context.bot.send_message(
                chat_id=chat_id,
                text="Отправка ссылок и упоминаний мессенджеров недопустима!"
            )
            context.job_queue.run_once(delete_system_message, 10, data=warning_message.message_id, chat_id=chat_id)
            return

        # Антиспам
        user_id = user.id
        if user_id in last_zch_times:
            if current_time - last_zch_times[user_id] < SPAM_INTERVAL:
                await message.delete()
                warning_message = await context.bot.send_message(
                    chat_id=chat_id,
                    text="Слишком частое отправление сообщений! Вы замьючены на 5 минут."
                )
                context.job_queue.run_once(delete_system_message, 10, data=warning_message.message_id, chat_id=chat_id)

                # Мут пользователя на 5 минут
                try:
                    await context.bot.restrict_chat_member(
                        chat_id=chat_id,
                        user_id=user_id,
                        permissions=ChatPermissions(can_send_messages=False),
                        until_date=int(time.time()) + MUTE_DURATION
                    )
                    logger.info(f"Пользователь {user_id} замьючен на {MUTE_DURATION} секунд.")
                except Exception as e:
                    logger.error(f"Ошибка при мьюте пользователя {user_id}: {e}")
                return
        last_zch_times[user_id] = current_time

    # Проверка наличия закрепленного сообщения в группе
    try:
        chat = await context.bot.get_chat(chat_id)
        pinned_message = chat.pinned_message
    except Exception as e:
        logger.error(f"Ошибка при получении информации о закрепленном сообщении: {e}")
        pinned_message = None

    # Если закрепленного сообщения нет, разрешаем закрепление
    if pinned_message is None:
        try:
            await message.pin()
            last_pinned_times[chat_id] = current_time
            last_user_username[chat_id] = user.username if user.username else None

            conn = get_db_connection()
            cur = conn.cursor()
            try:
                cur.execute('''
                    INSERT INTO pinned_messages (chat_id, user_id, username, message_text, timestamp)
                    VALUES (%s, %s, %s, %s, %s)
                ''', (chat_id, user.id, user.username, text, current_time))
                conn.commit()
            except Exception as e:
                logger.error(f"Ошибка при добавлении закрепленного сообщения в базу данных: {e}")
                conn.rollback()
            finally:
                cur.close()
                conn.close()

            context.job_queue.run_once(unpin_last_message, PINNED_DURATION, chat_id=chat_id)

            if chat_id != TARGET_GROUP_ID:
                new_text = text.replace("🌟 ", "").strip()
                forwarded_message = await context.bot.send_message(chat_id=TARGET_GROUP_ID, text=new_text)
                await forwarded_message.pin()
        except Exception as e:
            logger.error(f"Ошибка при закреплении сообщения: {e}")
        return

    last_pinned_time = last_pinned_times.get(chat_id, 0)
    if current_time - last_pinned_time < PINNED_DURATION:
        if not await is_admin_or_musician(update, context):
            await message.delete()
            return
        else:
            try:
                await message.pin()
                last_pinned_times[chat_id] = current_time
                last_user_username[chat_id] = user.username if user.username else None

                conn = get_db_connection()
                cur = conn.cursor()
                try:
                    cur.execute('''
                        INSERT INTO pinned_messages (chat_id, user_id, username, message_text, timestamp)
                        VALUES (%s, %s, %s, %s, %s)
                    ''', (chat_id, user.id, user.username, text, current_time))
                    conn.commit()
                except Exception as e:
                    logger.error(f"Ошибка при добавлении закрепленного сообщения в базу данных: {e}")
                    conn.rollback()
                finally:
                    cur.close()
                    conn.close()

                correction_message = await context.bot.send_message(
                    chat_id=chat_id,
                    text="Корректировка звезды часа от Админа."
                )
                context.job_queue.run_once(delete_system_message, 10, data=correction_message.message_id, chat_id=chat_id)
            except Exception as e:
                logger.error(f"Ошибка при закреплении сообщения: {e}")
            return

    # Если время закрепления истекло, закрепляем новое сообщение
    try:
        await message.pin()
        last_pinned_times[chat_id] = current_time
        last_user_username[chat_id] = user.username if user.username else None

        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute('''
                INSERT INTO pinned_messages (chat_id, user_id, username, message_text, timestamp)
                VALUES (%s, %s, %s, %s, %s)
            ''', (chat_id, user.id, user.username or user.first_name, text, current_time))
            conn.commit()
        except Exception as e:
            logger.error(f"Ошибка при добавлении закрепленного сообщения в базу данных: {e}")
            conn.rollback()
        finally:
            cur.close()
            conn.close()

        if chat_id != TARGET_GROUP_ID:
            try:
                new_text = text.replace("🌟 ", "").strip()
                forwarded_message = await context.bot.send_message(chat_id=TARGET_GROUP_ID, text=new_text)
                await forwarded_message.pin()
            except Exception as e:
                logger.error(f"Ошибка при пересылке сообщения в целевую группу: {e}")

        context.job_queue.run_once(unpin_last_message, PINNED_DURATION, chat_id=chat_id)
    except Exception as e:
        logger.error(f"Ошибка при закреплении сообщения: {e}")

# Основная функция
async def main():
    global db_initialized
    if not db_initialized:
        init_db()
        db_initialized = True

    global banned_users
    banned_users = set()

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT user_id FROM ban_list')
        rows = cur.fetchall()
        banned_users = {row['user_id'] for row in rows}
    except Exception as e:
        logger.error(f"Ошибка при выполнении запроса: {e}")
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()

    application = Application.builder().token(BOT_TOKEN).build()

    # Добавляем обработчики команд
    application.add_handler(CommandHandler("timer", reset_pin_timer))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Запуск бота
    logger.info("Бот запущен. Ожидание сообщений...")
    await application.run_polling()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем.")
    finally:
        loop.close()
