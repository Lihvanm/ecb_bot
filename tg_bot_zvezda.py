from telegram import Update
from telegram.ext import Application, MessageHandler, filters, CommandHandler, ContextTypes
import logging
import time
import re

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токен вашего бота
BOT_TOKEN = '8095859951:AAFGrYc5flFZk2EU8NNnsqpVWRJTGn009D4'

# ID целевой группы (если нужно пересылать сообщения)
TARGET_GROUP_ID = -1002437528572 # Замените на правильный ID группы

# Время в секундах (45 минут = 2700 секунд)
PINNED_DURATION = 2700  # Изменено на 45 минут

# Глобальные переменные
last_pinned_times = {}  # {chat_id: timestamp}
last_user_username = {}  # {chat_id: username}
last_zch_times = {}  # {chat_id: timestamp}
last_thanks_times = {}  # {chat_id: timestamp}

# Разрешенный пользователь для сброса таймера
ALLOWED_USER = "@Muzikant1429"

# Список запрещенных слов (антимат)
BANNED_WORDS = ["бля", "хуй", "пизд", "наху", "гандон", "пидр", "пидорас", "шалав", "шлюх", "мразь"]

# Ключевые слова для мессенджеров и ссылок
MESSENGER_KEYWORDS = [
    "t.me", "telegram", "whatsapp", "viber", "discord", "vk.com", "instagram",
    "facebook", "twitter", "youtube", "http", "www", ".com", ".ru"
]

# Лимиты для антиспама
SPAM_LIMIT = 4  # Максимальное количество сообщений
SPAM_INTERVAL = 30  # Интервал в секундах
MUTE_DURATION = 900  # Время мута в секундах (15 минут)

# Функция для проверки, является ли пользователь админом или музыкантом
async def is_admin_or_musician(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.message.from_user
    chat_id = update.message.chat.id

    # Проверяем, является ли пользователь админом
    try:
        chat_member = await context.bot.get_chat_member(chat_id, user.id)
        if chat_member.status in ["administrator", "creator"]:
            return True
    except Exception as e:
        logger.error(f"Ошибка при проверке прав пользователя {user.id}: {e}")

    # Проверяем, является ли пользователь музыкантом
    if user.username == ALLOWED_USER[1:]:  # Убираем "@" из ALLOWED_USER
        return True

    return False

# Функция для проверки прав администратора
async def check_admin_rights(context, chat_id):
    try:
        chat_member = await context.bot.get_chat_member(chat_id=chat_id, user_id=context.bot.id)
        return chat_member.status in ["administrator", "creator"]
    except Exception as e:
        logger.error(f"Ошибка при проверке прав администратора в чате {chat_id}: {e}")
        return False

# Функция для удаления системных сообщений через указанное время
async def delete_system_message(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    try:
        await context.bot.delete_message(chat_id=job.chat_id, message_id=job.data)
    except Exception as e:
        logger.error(f"Ошибка при удалении системного сообщения: {e}")

# Функция для открепления последнего закрепленного сообщения
async def unpin_last_message(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.chat_id
    try:
        await context.bot.unpin_chat_message(chat_id=chat_id)
        logger.info(f"Откреплено последнее закрепленное сообщение в группе {chat_id}.")
    except Exception as e:
        logger.error(f"Ошибка при откреплении сообщения в группе {chat_id}: {e}")

# Обработчик команды /reset_pin_timer
async def reset_pin_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat.id
    user = update.message.from_user

    # Проверяем права пользователя
    if not await is_admin_or_musician(update, context):
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    # Сбрасываем таймер
    last_pinned_times[chat_id] = 0
    logger.info(f"Таймер закрепа сброшен пользователем {user.username} в чате {chat_id}.")

    # Открепляем последнее закрепленное сообщение
    try:
        await context.bot.unpin_chat_message(chat_id=chat_id)
        logger.info(f"Откреплено последнее закрепленное сообщение в группе {chat_id}.")
    except Exception as e:
        logger.error(f"Ошибка при откреплении сообщения в группе {chat_id}: {e}")

    success_message = await update.message.reply_text("Таймер закрепа успешно сброшен.")

    # Удаляем команду и уведомление через 10 СЕК
    try:
        await update.message.delete()
        context.job_queue.run_once(delete_system_message, 10, data=success_message.message_id, chat_id=chat_id)
    except Exception as e:
        logger.error(f"Ошибка при удалении команды: {e}")

# Обработчик команды /del
async def delete_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat.id
    user = update.message.from_user

    # Проверяем права пользователя
    if not await is_admin_or_musician(update, context):
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    # Проверяем, есть ли сообщение, в ответ на которое отправлена команда
    if not update.message.reply_to_message:
        await update.message.reply_text("Пожалуйста, отправьте команду в ответ на сообщение, которое нужно удалить.")
        return

    # Удаляем сообщение
    try:
        await update.message.reply_to_message.delete()
        logger.info(f"Сообщение удалено пользователем {user.username} в чате {chat_id}.")
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения: {e}")
        await update.message.reply_text("Не удалось удалить сообщение. Проверьте права бота.")

    # Удаляем команду
    try:
        await update.message.delete()
    except Exception as e:
        logger.error(f"Ошибка при удалении команды: {e}")

# Глобальные переменные
user_message_history = {}  # {user_id: [(chat_id, message_id), ...]}
user_message_counts = {}  # {user_id: [timestamp1, timestamp2, ...]}
user_mute_times = {}  # {user_id: mute_end_time}

# Функция для удаления всех сообщений пользователя
async def delete_all_user_messages(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    if user_id in user_message_history:
        for chat_id, message_id in user_message_history[user_id]:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
                logger.info(f"Удалено сообщение {message_id} пользователя {user_id} в чате {chat_id}.")
            except Exception as e:
                logger.error(f"Ошибка при удалении сообщения {message_id} пользователя {user_id}: {e}")
        user_message_history[user_id].clear()  # Очищаем историю после удаления

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

        # Проверка, находится ли пользователь под мутом
        if user.id in user_mute_times:
            if current_time < user_mute_times[user.id]:  # Если время мута ещё не истекло
                logger.info(f"Пользователь {user.username} находится под мутом. Удаляем сообщение.")
                await message.delete()
                return
            else:
                # Если время мута истекло, удаляем пользователя из списка
                del user_mute_times[user.id]

        # Сохраняем сообщение в историю
        if user.id not in user_message_history:
            user_message_history[user.id] = []
        user_message_history[user.id].append((chat_id, message.message_id))

        # Проверка на спам (игнорируем для админов и музыканта)
        if not await is_admin_or_musician(update, context):
            if user.id not in user_message_counts:
                user_message_counts[user.id] = []
            user_message_counts[user.id] = [t for t in user_message_counts[user.id] if current_time - t < SPAM_INTERVAL]
            user_message_counts[user.id].append(current_time)

            if len(user_message_counts[user.id]) > SPAM_LIMIT:
                # Удаляем все сообщения пользователя
                await delete_all_user_messages(context, user.id)

                # Проверяем права администратора для мута
                mute_status = False
                try:
                    await context.bot.restrict_chat_member(
                        chat_id=chat_id,
                        user_id=user.id,
                        permissions={"can_send_messages": False},
                        until_date=current_time + MUTE_DURATION
                    )
                    mute_status = True
                    logger.info(f"Пользователь {user.username or 'анонимный'} замучен на 15 минут в чате {chat_id}.")
                except Exception as e:
                    logger.error(f"Ошибка при муте пользователя {user.id} в чате {chat_id}: {e}")

                # Если мут не удался, добавляем пользователя в список для удаления сообщений
                if not mute_status:
                    user_mute_times[user.id] = current_time + MUTE_DURATION
                    logger.info(f"Пользователь {user.username or 'анонимный'} добавлен в список для удаления сообщений на 15 минут.")

                # Отправляем предупреждение
                warning_text = (
                    f"{user.username or 'Уважаемый спамер'}, в связи с тем что вы захламляете группу, "
                    f"все ваши сообщения были удалены. Пожалуйста, соблюдайте правила общения."
                )
                warning_message = await context.bot.send_message(chat_id=chat_id, text=warning_text)
                logger.info(f"Отправлено предупреждение спамеру {user.username or 'анонимному'} в чате {chat_id}.")

                # Удаляем предупреждение через 10 секунд
                context.job_queue.run_once(delete_system_message, 10, data=warning_message.message_id, chat_id=chat_id)

                # Очищаем счетчик сообщений спамера
                user_message_counts[user.id].clear()
                return

        # Антимат (игнорируем для админов и музыканта)
        if not await is_admin_or_musician(update, context):
            if any(word in text.lower() for word in BANNED_WORDS):
                await message.delete()
                warning_message = await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"{user.username if user.username else 'Уважаемый'}, использование нецензурных выражений недопустимо! Пожалуйста, соблюдайте правила общения."
                )
                logger.info(f"Обнаружен мат от пользователя {user.username if user.username else 'анонимного'} в чате {chat_id}.")
                context.job_queue.run_once(delete_system_message, 10, data=warning_message.message_id, chat_id=chat_id)
                return

        # Антифлуд для ссылок и мессенджеров (игнорируем для админов и музыканта)
        if not await is_admin_or_musician(update, context):
            if any(re.search(rf"\b{re.escape(keyword)}\b", text.lower()) for keyword in MESSENGER_KEYWORDS):
                await message.delete()
                warning_message = await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"{user.username if user.username else 'Уважаемый'}, отправка ссылок и упоминание мессенджеров недопустимы! Пожалуйста, соблюдайте правила общения."
                )
                logger.info(f"Обнаружена ссылка или мессенджер от пользователя {user.username if user.username else 'анонимного'} в чате {chat_id}.")
                context.job_queue.run_once(delete_system_message, 10, data=warning_message.message_id, chat_id=chat_id)
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

        # Если пользователь — админ или музыкант, игнорируем ограничение в 45 минут
        if await is_admin_or_musician(update, context):
            # Проверяем, есть ли уже закрепленное сообщение
            if chat_id in last_pinned_times and last_pinned_times[chat_id] > 0:
                # Отправляем сообщение о корректировке
                correction_message = await context.bot.send_message(
                    chat_id=chat_id,
                    text="Корректировка звезды часа от Админа."
                )
                logger.info(f"Админ или музыкант {user.username} отправил корректировку звезды часа.")

                # Удаляем сообщение о корректировке через 10 секунд
                context.job_queue.run_once(delete_system_message, 10, data=correction_message.message_id, chat_id=chat_id)

            # Закрепляем сообщение
            try:
                await message.pin()
                logger.info(f"Сообщение закреплено в группе {chat_id}.")
                last_pinned_times[chat_id] = current_time  # Обновляем время последнего закрепления
                last_user_username[chat_id] = user.username if user.username else None  # Сохраняем username

                # Планируем открепление сообщения через 45 минут
                context.job_queue.run_once(unpin_last_message, PINNED_DURATION, chat_id=chat_id)
            except Exception as e:
                logger.error(f"Ошибка при закреплении сообщения в группе {chat_id}: {e}")
            return

        # Если прошло менее 45 минут с момента последнего закрепления
        last_pinned_time = last_pinned_times.get(chat_id, 0)
        if current_time - last_pinned_time < PINNED_DURATION:
            logger.info(f"Прошло {current_time - last_pinned_time} секунд. Удаляем сообщение.")
            await message.delete()

            # Проверяем, прошло ли менее 3 минут с момента последнего закрепа
            if current_time - last_pinned_time < 180:
                # Проверяем, когда было последнее сообщение с "ЗЧ"
                last_zch_time = last_zch_times.get(chat_id, 0)
                if current_time - last_zch_time < 180:
                    logger.info("Повторное сообщение с 'ЗЧ' игнорируется.")
                    return
                
                # Проверяем, когда была отправлена последняя благодарность
                last_thanks_time = last_thanks_times.get(chat_id, 0)
                if current_time - last_thanks_time < 180:
                    logger.info("Благодарность ещё не может быть отправлена.")
                    return

                # Отправляем сообщение с благодарностью
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
                context.job_queue.run_once(delete_system_message, 180, data=thanks_message.message_id, chat_id=chat_id)
                
                # Обновляем время последнего сообщения с "ЗЧ" и времени благодарности
                last_zch_times[chat_id] = current_time
                last_thanks_times[chat_id] = current_time
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

            # Планируем открепление сообщения через 45 минут
            context.job_queue.run_once(unpin_last_message, PINNED_DURATION, chat_id=chat_id)

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
                    
                    # Закрепляем пересланное сообщение
                    await forwarded_message.pin()
                    logger.info(f"Пересланное сообщение закреплено в целевой группе {TARGET_GROUP_ID}.")
                except Exception as e:
                    logger.error(f"Ошибка при пересылке сообщения в целевую группу {TARGET_GROUP_ID}: {e}")
        except Exception as e:
            logger.error(f"Ошибка при закреплении сообщения в группе {chat_id}: {e}")

    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения: {e}")

# Основная функция
def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # Регистрируем обработчики
    application.add_handler(CommandHandler("timer", reset_pin_timer))
    application.add_handler(CommandHandler("del", delete_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Запускаем бота
    application.run_polling()
    logger.info("Бот запущен. Ожидание сообщений...")

if __name__ == '__main__':
    main()
