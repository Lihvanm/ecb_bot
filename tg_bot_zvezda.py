from telegram import Update
from telegram.ext import Application, MessageHandler, filters, CommandHandler, ContextTypes
import logging
import time

# Глобальная переменная для хранения username последнего пользователя, который закрепил звезду (по группам)
last_user_username = {}  # {chat_id: username}

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токен вашего бота
BOT_TOKEN = '8095859951:AAFGrYc5flFZk2EU8NNnsqpVWRJTGn009D4'

# ID целевой группы (если нужно пересылать сообщения)
TARGET_GROUP_ID = -1002437528572

# Время в секундах (45 минут = 2700 секунд)
PINNED_DURATION = 2700  # Изменено на 45 минут

# Глобальная переменная для хранения времени последнего закрепления (по группам)
last_pinned_times = {}  # {chat_id: timestamp}

# Разрешенный пользователь для сброса таймера
ALLOWED_USER = "@Muzikant1429"

# Список запрещенных слов (антимат)
BANNED_WORDS = ["бля", "хуй", "пизд", "наху", "гандон", "пидр", "пидорас", "шалав", "шлюх", "мразь"]

# Лимиты для антиспама
SPAM_LIMIT = 5  # Максимальное количество сообщений
SPAM_INTERVAL = 10  # Интервал в секундах
user_message_counts = {}  # {user_id: [timestamp1, timestamp2, ...]}

# Функция для проверки прав администратора
async def check_admin_rights(context, chat_id):
    try:
        chat_member = await context.bot.get_chat_member(chat_id=chat_id, user_id=context.bot.id)
        return chat_member.status in ["administrator", "creator"]
    except Exception as e:
        logger.error(f"Ошибка при проверке прав администратора в чате {chat_id}: {e}")
        return False

# Функция для проверки, является ли пользователь администратором или разрешенным пользователем
async def is_admin_or_allowed_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    chat_id = update.message.chat.id
    if user.username == ALLOWED_USER[1:]:  # Убираем "@" из ALLOWED_USER
        return True
    try:
        chat_member = await context.bot.get_chat_member(chat_id=chat_id, user_id=user.id)
        return chat_member.status in ["administrator", "creator"]
    except Exception as e:
        logger.error(f"Ошибка при проверке прав пользователя {user.id} в чате {chat_id}: {e}")
        return False

# Функция для удаления системных сообщений через указанное время
async def delete_system_message(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    try:
        await context.bot.delete_message(chat_id=job.chat_id, message_id=job.data)
    except Exception as e:
        logger.error(f"Ошибка при удалении системного сообщения: {e}")

# Обработчик новых сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message = update.message
        if not message:
            logger.warning("Сообщение не содержит текста.")
            return

        chat_id = message.chat.id
        text = message.text
        user = message.from_user
        current_time = time.time()

        logger.info(f"Получено новое сообщение в чате {chat_id} от пользователя {user.username}: {text}")

        # Антиспам
        if user.id not in user_message_counts:
            user_message_counts[user.id] = []
        user_message_counts[user.id] = [t for t in user_message_counts[user.id] if current_time - t < SPAM_INTERVAL]
        user_message_counts[user.id].append(current_time)

        if len(user_message_counts[user.id]) > SPAM_LIMIT:
            await message.delete()
            warning_message = await update.message.reply_text(f"{user.username}, пожалуйста, не спамьте!")
            logger.info(f"Спам обнаружен от пользователя {user.username} в чате {chat_id}.")
            # Удаляем предупреждение через 3 минуты
            context.job_queue.run_once(delete_system_message, 180, data=warning_message.message_id, chat_id=chat_id)
            return

        # Антимат
        if any(word in text.lower() for word in BANNED_WORDS):
            await message.delete()
            warning_message = await context.bot.send_message(
                chat_id=chat_id,
                text="Использование нецензурных выражений недопустимо! Пожалуйста, соблюдайте правила общения."
            )
            logger.info(f"Обнаружен мат в чате {chat_id}.")
            # Удаляем предупреждение через 1 минуту
            context.job_queue.run_once(delete_system_message, 60, data=warning_message.message_id, chat_id=chat_id)
            return

        # Проверяем, что сообщение пришло из группы или супергруппы
        if message.chat.type not in ['group', 'supergroup']:
            logger.info("Сообщение не из группы. Игнорируем.")
            return

        # Проверяем, начинается ли сообщение с "звезда", "зч" или содержит 🌟
        if not text or (
            not text.lower().startswith("звезда") and
            not text.lower().startswith("зч") and
            "🌟" not in text
        ):
            logger.info("Сообщение не соответствует условиям. Игнорируем.")
            return

        # Если прошло менее 45 минут с момента последнего закрепления
        last_pinned_time = last_pinned_times.get(chat_id, 0)
        if current_time - last_pinned_time < PINNED_DURATION:
            logger.info(f"Прошло {current_time - last_pinned_time} секунд. Удаляем сообщение.")
            await message.delete()

            # Проверяем, прошло ли менее 3 минут с момента последнего закрепа
            if current_time - last_pinned_time < 180:
                last_user = last_user_username.get(chat_id, "")  # Получаем username последнего пользователя
                thanks_message = await context.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"Спасибо за вашу бдительность! Звезда часа уже замечена пользователем "
                        f"{'@' + last_user if last_user else 'до Вас'} и закреплена в группе. "
                        f"Надеюсь, в следующий раз именно Вы станете нашей 🌟!!!"
                    )
                )
                logger.info(f"Отправлено сообщение с благодарностью в чате {chat_id}.")
                # Удаляем сообщение с благодарностью через 3 минуты
                context.job_queue.run_once(delete_system_message, 180, data=thanks_message.message_id, chat_id=chat_id)
            return

        # Проверяем права администратора в текущей группе
        if not await check_admin_rights(context, chat_id):
            logger.warning(f"Бот не имеет прав администратора в группе {chat_id}.")
            return

        # Открепляем предыдущее закрепленное сообщение
        try:
            await context.bot.unpin_chat_message(chat_id=chat_id)
            logger.info(f"Откреплено последнее закрепленное сообщение в группе {chat_id}.")
        except Exception as e:
            logger.error(f"Ошибка при откреплении сообщения в группе {chat_id}: {e}")

        # Закрепляем текущее сообщение
        try:
            await message.pin()
            logger.info(f"Сообщение закреплено в группе {chat_id}.")
            last_pinned_times[chat_id] = current_time  # Обновляем время последнего закрепления
            last_user_username[chat_id] = user.username if user.username else None  # Сохраняем username

            # Пересылаем сообщение в целевую группу
            if chat_id != TARGET_GROUP_ID:
                if not await check_admin_rights(context, TARGET_GROUP_ID):
                    logger.warning("Бот не имеет прав администратора в целевой группе.")
                    return

                # Удаляем маркер "зч" или "звезда" и пробел
                if text.lower().startswith("зч"):
                    new_text = text[len("зч"):].strip()
                elif text.lower().startswith("звезда"):
                    new_text = text[len("звезда"):].strip()
                else:
                    new_text = text.replace("🌟", "").strip()  # Убираем смайлик 🌟

                # Пересылаем сообщение в целевую группу
                try:
                    forwarded_message = await context.bot.send_message(chat_id=TARGET_GROUP_ID, text=new_text)
                    logger.info(f"Сообщение переслано в целевую группу {TARGET_GROUP_ID}.")
                    await forwarded_message.pin()
                    logger.info(f"Пересланное сообщение закреплено в целевой группе {TARGET_GROUP_ID}.")
                except Exception as e:
                    logger.error(f"Ошибка при пересылке сообщения в целевую группу {TARGET_GROUP_ID}: {e}")
        except Exception as e:
            logger.error(f"Ошибка при закреплении сообщения в группе {chat_id}: {e}")

    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения: {e}")

# Обработчик команды /reset_pin_timer
async def reset_pin_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat.id
    user = update.message.from_user

    # Проверяем права пользователя
    if not await is_admin_or_allowed_user(update, context):
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    # Сбрасываем таймер
    last_pinned_times[chat_id] = 0
    logger.info(f"Таймер закрепа сброшен пользователем {user.username} в чате {chat_id}.")
    success_message = await update.message.reply_text("Таймер закрепа успешно сброшен.")

    # Удаляем команду и уведомление через 3 минуты
    try:
        await update.message.delete()
        context.job_queue.run_once(delete_system_message, 180, data=success_message.message_id, chat_id=chat_id)
    except Exception as e:
        logger.error(f"Ошибка при удалении команды: {e}")

# Обработчик команды /ban
async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    chat_id = update.message.chat.id

    # Проверяем права пользователя
    if not await is_admin_or_allowed_user(update, context):
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    # Получаем ID пользователя, которого нужно забанить
    target_user = None
    reply_to_message = update.message.reply_to_message

    # Если команда отправлена в ответ на сообщение
    if reply_to_message:
        target_user = reply_to_message.from_user
    else:
        # Если команда содержит упоминание пользователя
        if context.args and context.args[0].startswith("@"):
            username = context.args[0][1:]  # Убираем "@" из имени пользователя
            try:
                chat_members = await context.bot.get_chat_member(chat_id=chat_id, user_id=user.id)
                for member in chat_members:
                    if member.user.username.lower() == username.lower():
                        target_user = member.user
                        break
            except Exception as e:
                logger.error(f"Ошибка при поиске пользователя {username}: {e}")
                await update.message.reply_text(f"Не удалось найти пользователя @{username}.")
                return

    # Если целевой пользователь не найден
    if not target_user:
        await update.message.reply_text("Пожалуйста, укажите пользователя через упоминание или отправьте команду в ответ на его сообщение.")
        return

    # Баним пользователя
    try:
        await context.bot.ban_chat_member(chat_id=chat_id, user_id=target_user.id)
        logger.info(f"Пользователь {target_user.username} забанен в чате {chat_id} пользователем {user.username}.")
        await update.message.reply_text(f"Пользователь @{target_user.username} был забанен.")
    except Exception as e:
        logger.error(f"Ошибка при бане пользователя {target_user.id} в чате {chat_id}: {e}")
        await update.message.reply_text("Не удалось забанить пользователя. Проверьте права бота.")

    # Удаляем команду из чата
    try:
        await update.message.delete()
    except Exception as e:
        logger.error(f"Ошибка при удалении команды: {e}")

# Обработчик команды /mute
async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    chat_id = update.message.chat.id

    # Проверяем права пользователя
    if not await is_admin_or_allowed_user(update, context):
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    # Получаем ID пользователя, которого нужно замутить
    target_user = None
    reply_to_message = update.message.reply_to_message

    # Если команда отправлена в ответ на сообщение
    if reply_to_message:
        target_user = reply_to_message.from_user
    else:
        # Если команда содержит упоминание пользователя
        if context.args and context.args[0].startswith("@"):
            username = context.args[0][1:]  # Убираем "@" из имени пользователя
            try:
                chat_members = await context.bot.get_chat_member(chat_id=chat_id, user_id=user.id)
                for member in chat_members:
                    if member.user.username.lower() == username.lower():
                        target_user = member.user
                        break
            except Exception as e:
                logger.error(f"Ошибка при поиске пользователя {username}: {e}")
                await update.message.reply_text(f"Не удалось найти пользователя @{username}.")
                return

    # Если целевой пользователь не найден
    if not target_user:
        await update.message.reply_text("Пожалуйста, укажите пользователя через упоминание или отправьте команду в ответ на его сообщение.")
        return

    # Получаем время мута из аргументов команды
    mute_duration = None
    if len(context.args) >= 1:
        try:
            # Если первый аргумент — это время (число)
            mute_duration = int(context.args[-1]) * 60  # Преобразуем минуты в секунды
        except ValueError:
            await update.message.reply_text("Неверный формат времени. Укажите время в минутах.")
            return

    if mute_duration is None:
        await update.message.reply_text("Пожалуйста, укажите время мута в минутах.")
        return

    # Мутим пользователя
    try:
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=target_user.id,
            permissions={"can_send_messages": False},
            until_date=time.time() + mute_duration
        )
        logger.info(f"Пользователь {target_user.username} замучен в чате {chat_id} на {mute_duration // 60} минут пользователем {user.username}.")
        await update.message.reply_text(f"Пользователь @{target_user.username} замучен на {mute_duration // 60} минут.")
    except Exception as e:
        logger.error(f"Ошибка при муте пользователя {target_user.id} в чате {chat_id}: {e}")
        await update.message.reply_text("Не удалось замутить пользователя. Проверьте права бота.")

    # Удаляем команду из чата
    try:
        await update.message.delete()
    except Exception as e:
        logger.error(f"Ошибка при удалении команды: {e}")

# Основная функция
def main():
    # Создаём объект Application
    application = Application.builder().token(BOT_TOKEN).build()

    # Регистрируем обработчики
    application.add_handler(CommandHandler("timer", reset_pin_timer))
    application.add_handler(CommandHandler("ban", ban_user))
    application.add_handler(CommandHandler("mute", mute_user))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Запускаем бота
    application.run_polling()
    logger.info("Бот запущен. Ожидание сообщений...")

if __name__ == '__main__':
    main()
