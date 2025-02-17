from telegram import Update
from telegram.ext import Application, MessageHandler, filters, CommandHandler, ContextTypes
import logging
import time

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токен вашего бота
BOT_TOKEN = '8095859951:AAFGrYc5flFZk2EU8NNnsqpVWRJTGn009D4'

# ID целевой группы
TARGET_GROUP_ID = -1002437528572  # Замените на реальный ID вашей целевой группы

# Время в секундах (100 минут = 6000 секунд)
PINNED_DURATION = 6000

# Глобальная переменная для хранения времени последнего закрепления
last_pinned_time = 0

# Разрешенный пользователь для сброса таймера
ALLOWED_USER = "@Muzikant1429"

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

# Обработчик команды /reset_pin_timer
async def reset_pin_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global last_pinned_time
    user = update.message.from_user
    chat_id = update.message.chat.id

    # Проверяем права пользователя
    if not await is_admin_or_allowed_user(update, context):
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    # Сбрасываем таймер
    last_pinned_time = 0
    logger.info(f"Таймер закрепа сброшен пользователем {user.username} в чате {chat_id}.")
    await update.message.reply_text("Таймер закрепа успешно сброшен.")

    # Удаляем команду из чата
    try:
        await update.message.delete()
    except Exception as e:
        logger.error(f"Ошибка при удалении команды: {e}")

# Обработчик новых сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global last_pinned_time

    try:
        message = update.message
        if not message:
            logger.warning("Сообщение не содержит текста.")
            return

        chat_id = message.chat.id
        text = message.text
        logger.info(f"Получено новое сообщение в чате {chat_id}: {text}")

        # Проверяем, что сообщение пришло из группы или супергруппы
        if message.chat.type not in ['group', 'supergroup']:
            logger.info("Сообщение не из группы. Игнорируем.")
            return

        # Проверяем, начинается ли сообщение с "звезда" (в любом регистре), "зч" (в любом регистре) или содержит 🌟
        if not text or (
            not text.lower().startswith("звезда") and
            not text.lower().startswith("зч") and
            "🌟" not in text
        ):
            logger.info("Сообщение не соответствует условиям. Игнорируем.")
            return

        # Если прошло менее 100 минут с момента последнего закрепления
        current_time = time.time()
        if current_time - last_pinned_time < PINNED_DURATION:
            logger.info(f"Прошло {current_time - last_pinned_time} секунд. Удаляем сообщение.")
            await message.delete()
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
            last_pinned_time = current_time  # Обновляем время последнего закрепления
        except Exception as e:
            logger.error(f"Ошибка при закреплении сообщения в группе {chat_id}: {e}")

        # Если сообщение пришло из другой группы (не целевой), пересылаем его в целевую группу
        if chat_id != TARGET_GROUP_ID:
            # Проверяем права администратора в целевой группе
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
            except Exception as e:
                logger.error(f"Ошибка при пересылке сообщения в целевую группу {TARGET_GROUP_ID}: {e}")
                return

            # Закрепляем пересланное сообщение в целевой группе
            try:
                await forwarded_message.pin()
                logger.info(f"Пересланное сообщение закреплено в целевой группе {TARGET_GROUP_ID}.")
            except Exception as e:
                logger.error(f"Ошибка при закреплении пересланного сообщения: {e}")

    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения: {e}")


# Основная функция
def main():
    # Создаём объект Application
    application = Application.builder().token(BOT_TOKEN).build()

    # Регистрируем обработчики
    application.add_handler(CommandHandler("timer", reset_pin_timer))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Запускаем бота
    application.run_polling()
    logger.info("Бот запущен. Ожидание сообщений...")


if __name__ == '__main__':
    main()
