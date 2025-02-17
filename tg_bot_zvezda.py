from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import logging

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

# Функция для проверки прав администратора
async def check_admin_rights(context, chat_id):
    try:
        chat_member = await context.bot.get_chat_member(chat_id=chat_id, user_id=context.bot.id)
        return chat_member.status in ["administrator", "creator"]
    except Exception as e:
        logger.error(f"Ошибка при проверке прав администратора в чате {chat_id}: {e}")
        return False

# Обработчик новых сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message = update.message
        chat_id = message.chat.id
        text = message.text

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

        # Если сообщение пришло из целевой группы
        if chat_id == TARGET_GROUP_ID:
            # Открепляем предыдущее закрепленное сообщение
            try:
                await context.bot.unpin_chat_message(chat_id=TARGET_GROUP_ID)
                logger.info(f"Откреплено последнее закрепленное сообщение в целевой группе {TARGET_GROUP_ID}.")
            except Exception as e:
                logger.error(f"Ошибка при откреплении сообщения в целевой группе {TARGET_GROUP_ID}: {e}")

            # Закрепляем текущее сообщение
            try:
                await message.pin()
                logger.info(f"Исходное сообщение закреплено в целевой группе {TARGET_GROUP_ID}.")
            except Exception as e:
                logger.error(f"Ошибка при закреплении исходного сообщения: {e}")
            return

        # Если сообщение пришло из другой группы
        if chat_id != TARGET_GROUP_ID:
            # Проверяем права администратора в текущей группе
            if not await check_admin_rights(context, chat_id):
                logger.warning(f"Бот не имеет прав администратора в группе {chat_id}.")
                return

            # Открепляем предыдущее закрепленное сообщение в текущей группе
            try:
                await context.bot.unpin_chat_message(chat_id=chat_id)
                logger.info(f"Откреплено последнее закрепленное сообщение в группе {chat_id}.")
            except Exception as e:
                logger.error(f"Ошибка при откреплении сообщения в группе {chat_id}: {e}")

            # Закрепляем текущее сообщение в текущей группе
            try:
                await message.pin()
                logger.info(f"Сообщение закреплено в группе {chat_id}.")
            except Exception as e:
                logger.error(f"Ошибка при закреплении сообщения в группе {chat_id}: {e}")

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

    # Регистрируем обработчик для новых сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Запускаем бота
    application.run_polling()
    logger.info("Бот запущен. Ожидание сообщений...")

if __name__ == '__main__':
    main()
