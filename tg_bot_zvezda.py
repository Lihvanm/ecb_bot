from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    JobQueue,
    CallbackContext
)
import logging
import time
import os
from bs4 import BeautifulSoup
import requests
from datetime import datetime
import re

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")
HTML_URL = os.getenv("HTML_URL")
TARGET_GROUP_ID = -1002382138419
ALLOWED_CHAT_IDS = [-1002201488475, -1002437528572, -1002385047417, -1002382138419]
PINNED_DURATION = 2700  # 45 минут
MESSAGE_STORAGE_TIME = 180  # 3 минуты для хранения сообщений
ALLOWED_USER = "@Muzikant1429"
TEMPORARY_ADD_DURATION = 3600  # 1 час для временного добавления чатов

# Антимат - теперь проверяет части слов
BANNED_WORDS = ["бляд", "хуй", "пизд", "наху", "гандон", "пидр", "пидорас", "пидар", "шалав", "шлюх", "мразь", "мразо", "ебат", "ебал", "дебил", "имебецил", "говнюк"]
MESSENGER_KEYWORDS = ["t.me", "telegram", "whatsapp", "viber", "discord", "vk.com", "instagram", "facebook", "twitter", "youtube", "http", "www", ".com", ".ru", ".net", "tiktok"]

# Глобальные переменные
last_pinned_times = {}
last_user_username = {}
last_thanks_times = {}
pinned_messages = {}  # {chat_id: {"message_id": int, "user_id": int, "text": str, "timestamp": float, "photo_id": int}}
message_storage = {}  # {message_id: {"chat_id": int, "user_id": int, "text": str, "timestamp": float}}
STAR_MESSAGES = {}
banned_users = set()
sent_photos = {}  # {chat_id: message_id} для хранения ID отправленных фото
temporary_allowed_chats = {}  # {chat_id: expiry_timestamp}

def clean_text(text: str) -> str:
    return " ".join(text.split()).lower() if text else ""

def load_star_messages():
    try:
        response = requests.get(HTML_URL)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        return {
            clean_text(row.find_all("td")[0].text.strip()): {
                "message": row.find_all("td")[1].text.strip(),
                "photo": row.find_all("td")[2].text.strip() if row.find_all("td")[2].text.strip().startswith("http") else None
            }
            for row in soup.find_all("tr")[1:] if len(row.find_all("td")) >= 3
        }
    except Exception as e:
        logger.error(f"Ошибка загрузки Google таблицы: {e}")
        return {}

STAR_MESSAGES = load_star_messages()

async def is_admin_or_musician(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.username == ALLOWED_USER[1:]:
        return True
    
    try:
        chat_member = await context.bot.get_chat_member(update.effective_chat.id, user.id)
        return chat_member.status in ["administrator", "creator"]
    except Exception as e:
        logger.error(f"Ошибка проверки прав: {e}")
        return False

async def cleanup_storage(context: CallbackContext):
    current_time = time.time()
    # Очистка временных сообщений
    expired_messages = [
        msg_id for msg_id, data in message_storage.items() 
        if current_time - data["timestamp"] > MESSAGE_STORAGE_TIME
    ]
    for msg_id in expired_messages:
        del message_storage[msg_id]
    
    # Очистка временно разрешенных чатов
    expired_chats = [
        chat_id for chat_id, expiry in temporary_allowed_chats.items()
        if current_time > expiry
    ]
    for chat_id in expired_chats:
        del temporary_allowed_chats[chat_id]
        logger.info(f"Чат {chat_id} удален из временно разрешенных")

async def unpin_message(context: CallbackContext):
    job = context.job
    chat_id = job.chat_id
    
    if chat_id in pinned_messages:
        try:
            await context.bot.unpin_chat_message(chat_id, pinned_messages[chat_id]["message_id"])
            logger.info(f"Сообщение откреплено в чате {chat_id}")
        except Exception as e:
            logger.error(f"Ошибка открепления: {e}")
        finally:
            if "photo_id" in pinned_messages[chat_id] and pinned_messages[chat_id]["photo_id"] == sent_photos.get(chat_id):
                try:
                    await context.bot.delete_message(chat_id, pinned_messages[chat_id]["photo_id"])
                    del sent_photos[chat_id]
                except Exception as e:
                    logger.error(f"Ошибка удаления фото: {e}")
            
            del pinned_messages[chat_id]
            if chat_id in last_pinned_times:
                del last_pinned_times[chat_id]

async def check_pinned_message_exists(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> bool:
    try:
        chat = await context.bot.get_chat(chat_id)
        if chat.pinned_message and chat.pinned_message.message_id == pinned_messages.get(chat_id, {}).get("message_id"):
            return True
    except Exception as e:
        logger.error(f"Ошибка при проверке закрепленного сообщения: {e}")
    return False

async def process_new_pinned_message(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, user, text: str, is_edit: bool = False):
    current_time = time.time()
    message = update.message or update.edited_message
    
    # Проверяем Google таблицу
    text_cleaned = clean_text(text)
    target_message = None
    for word in text_cleaned.split():
        if word in STAR_MESSAGES:
            target_message = STAR_MESSAGES[word]
            break
    
    try:
        if is_edit and chat_id in sent_photos and pinned_messages.get(chat_id, {}).get("user_id") == user.id:
            try:
                await context.bot.delete_message(chat_id, sent_photos[chat_id])
                del sent_photos[chat_id]
            except Exception as e:
                logger.error(f"Ошибка удаления старого фото: {e}")
        
        photo_message = None
        if target_message and target_message["photo"]:
            photo_message = await context.bot.send_photo(
                chat_id=chat_id,
                photo=target_message["photo"]
            )
            sent_photos[chat_id] = photo_message.message_id
        
        await message.pin()
        
        pinned_messages[chat_id] = {
            "message_id": message.message_id,
            "user_id": user.id,
            "text": text,
            "timestamp": current_time,
            "photo_id": photo_message.message_id if photo_message else None
        }
        
        last_pinned_times[chat_id] = current_time
        last_user_username[chat_id] = user.username or f"id{user.id}"
        
        context.job_queue.run_once(unpin_message, PINNED_DURATION, chat_id=chat_id)
        
        if chat_id == TARGET_GROUP_ID:
            logger.info(f"ЗЧ в целевой группе от @{user.username}")
            return
        
        await process_target_group_forward(update, context, chat_id, user, text, target_message, current_time, is_edit)
                
    except Exception as e:
        logger.error(f"Ошибка обработки сообщения: {e}")

async def process_target_group_forward(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                     source_chat_id: int, user, text: str, 
                                     target_message: dict, current_time: float,
                                     is_edit: bool = False):
    try:
        target_has_active_pin = (TARGET_GROUP_ID in pinned_messages and 
                                current_time - pinned_messages[TARGET_GROUP_ID]["timestamp"] < PINNED_DURATION)
        
        if target_has_active_pin and pinned_messages[TARGET_GROUP_ID].get("source_chat_id") == source_chat_id:
            await context.bot.unpin_chat_message(TARGET_GROUP_ID, pinned_messages[TARGET_GROUP_ID]["message_id"])
            if "photo_id" in pinned_messages[TARGET_GROUP_ID]:
                try:
                    await context.bot.delete_message(TARGET_GROUP_ID, pinned_messages[TARGET_GROUP_ID]["photo_id"])
                except Exception as e:
                    logger.error(f"Ошибка удаления фото в целевой группе: {e}")
            del pinned_messages[TARGET_GROUP_ID]
            target_has_active_pin = False
        
        if not target_has_active_pin:
            forwarded_text = target_message["message"] if target_message else f"🌟 {text.replace('🌟', '').strip()}"
            
            forwarded = await context.bot.send_message(
                chat_id=TARGET_GROUP_ID,
                text=forwarded_text
            )
            
            await forwarded.pin()
            
            pinned_messages[TARGET_GROUP_ID] = {
                "message_id": forwarded.message_id,
                "user_id": user.id,
                "text": forwarded_text,
                "timestamp": current_time,
                "source_chat_id": source_chat_id
            }
            
            context.job_queue.run_once(unpin_message, PINNED_DURATION, chat_id=TARGET_GROUP_ID)
            
            if target_message and target_message["photo"]:
                try:
                    photo_message = await context.bot.send_photo(
                        chat_id=TARGET_GROUP_ID,
                        photo=target_message["photo"]
                    )
                    pinned_messages[TARGET_GROUP_ID]["photo_id"] = photo_message.message_id
                except Exception as e:
                    logger.error(f"Ошибка отправки фото в целевую группу: {e}")
            
            logger.info(f"Сообщение переслано и закреплено в целевой группе")
            
    except Exception as e:
        logger.error(f"Ошибка при обработке целевой группы: {e}")

async def process_duplicate_message(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, user):
    current_time = time.time()
    try:
        await update.message.delete()
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения: {e}")
    
    if current_time - last_thanks_times.get(chat_id, 0) > 180:
        last_user = last_user_username.get(chat_id, "администратора")
        thanks = await context.bot.send_message(
            chat_id=chat_id,
            text=f"@{user.username or user.id}, спасибо за бдительность! Звезда часа уже закреплена пользователем {last_user}. Надеюсь, в следующий раз именно Вы станете нашей 🌟!!!"
        )
        context.job_queue.run_once(
            lambda ctx: ctx.bot.delete_message(chat_id=chat_id, message_id=thanks.message_id),
            180
        )
        last_thanks_times[chat_id] = current_time

async def handle_message_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.edited_message:
        return
    
    edited_msg = update.edited_message
    chat_id = edited_msg.chat.id
    user = edited_msg.from_user
    
    if (chat_id in pinned_messages and 
        pinned_messages[chat_id]["message_id"] == edited_msg.message_id and
        (pinned_messages[chat_id]["user_id"] == user.id or await is_admin_or_musician(update, context))):
        
        text = edited_msg.text or edited_msg.caption
        
        if not await check_message_allowed(update, context, chat_id, user, text):
            return
        
        await process_new_pinned_message(update, context, chat_id, user, text, is_edit=True)

async def handle_message_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.left_chat_member or update.message.new_chat_members:
        return
        
    chat_id = update.message.chat.id
    message_id = update.message.message_id
    
    if chat_id in pinned_messages and pinned_messages[chat_id]["message_id"] == message_id:
        logger.info(f"Удалена закрепленная ЗЧ в чате {chat_id}")
        
        if chat_id in last_pinned_times:
            del last_pinned_times[chat_id]
        
        del pinned_messages[chat_id]
        
        if chat_id in sent_photos:
            try:
                await context.bot.delete_message(chat_id, sent_photos[chat_id])
            except Exception as e:
                logger.error(f"Ошибка при удалении фото: {e}")
            del sent_photos[chat_id]

async def check_message_allowed(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, user, text: str) -> bool:
    """Проверяет, разрешено ли обрабатывать сообщение"""
    # Проверка бана пользователя
    if user.id in banned_users:
        logger.info(f"Заблокированное сообщение от забаненного пользователя {user.id}")
        return False
    
    # Проверка разрешенных чатов
    current_time = time.time()
    if chat_id not in ALLOWED_CHAT_IDS and chat_id not in temporary_allowed_chats:
        # Добавляем чат временно в разрешенные
        temporary_allowed_chats[chat_id] = current_time + TEMPORARY_ADD_DURATION
        logger.info(f"Чат {chat_id} временно добавлен в разрешенные на {TEMPORARY_ADD_DURATION} сек")
    
    # Проверка на мат (ищем части слов)
    if text and any(re.search(re.escape(word), text.lower()) for word in BANNED_WORDS):
        try:
            await update.message.delete()
            warn = await context.bot.send_message(chat_id, "Использование мата запрещено!")
            context.job_queue.run_once(
                lambda ctx: ctx.bot.delete_message(chat_id=chat_id, message_id=warn.message_id),
                10
            )
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщения с матом: {e}")
        return False
        
    # Проверка на рекламу
    if text and any(re.search(re.escape(keyword), text.lower()) for keyword in MESSENGER_KEYWORDS):
        try:
            await update.message.delete()
            warn = await context.bot.send_message(chat_id, "Реклама запрещена!")
            context.job_queue.run_once(
                lambda ctx: ctx.bot.delete_message(chat_id=chat_id, message_id=warn.message_id),
                10
            )
        except Exception as e:
            logger.error(f"Ошибка при удалении рекламы: {e}")
        return False
    
    return True

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message = update.message or update.edited_message
        if not message:
            return
            
        user = message.from_user
        chat_id = message.chat.id
        text = message.text or message.caption
        current_time = time.time()
        
        if not await check_message_allowed(update, context, chat_id, user, text):
            return

        if text and any(marker in text.lower() for marker in ["звезда", "зч", "🌟"]):
            try:
                chat = await context.bot.get_chat(chat_id)
                current_pinned = chat.pinned_message
                
                if chat_id in pinned_messages:
                    if not current_pinned or current_pinned.message_id != pinned_messages[chat_id]["message_id"]:
                        del pinned_messages[chat_id]
                        if chat_id in last_pinned_times:
                            del last_pinned_times[chat_id]
                        if chat_id in sent_photos:
                            try:
                                await context.bot.delete_message(chat_id, sent_photos[chat_id])
                                del sent_photos[chat_id]
                            except Exception as e:
                                logger.error(f"Ошибка удаления фото: {e}")
            except Exception as e:
                logger.error(f"Ошибка при проверке закрепленного сообщения: {e}")

            can_pin = True
            if chat_id in pinned_messages:
                last_pin_time = pinned_messages[chat_id]["timestamp"]
                if current_time - last_pin_time < PINNED_DURATION:
                    can_pin = False
            
            if can_pin:
                await process_new_pinned_message(update, context, chat_id, user, text)
            else:
                if await is_admin_or_musician(update, context):
                    await process_new_pinned_message(update, context, chat_id, user, text, is_edit=True)
                    correction = await context.bot.send_message(
                        chat_id=chat_id,
                        text="Корректировка звезды часа от Админа."
                    )
                    context.job_queue.run_once(
                        lambda ctx: ctx.bot.delete_message(chat_id=chat_id, message_id=correction.message_id),
                        10
                    )
                else:
                    await process_duplicate_message(update, context, chat_id, user)
                
    except Exception as e:
        logger.error(f"Ошибка обработки сообщения: {e}")

async def delete_message_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /del для удаления сообщений админами"""
    if not await is_admin_or_musician(update, context):
        resp = await update.message.reply_text("❌ Только админы могут удалять сообщения!")
        context.job_queue.run_once(
            lambda ctx: ctx.bot.delete_message(chat_id=update.message.chat.id, message_id=resp.message_id),
            10
        )
        await update.message.delete()
        return
    
    if not update.message.reply_to_message:
        resp = await update.message.reply_text("❌ Ответьте на сообщение, которое нужно удалить!")
        context.job_queue.run_once(
            lambda ctx: ctx.bot.delete_message(chat_id=update.message.chat.id, message_id=resp.message_id),
            10
        )
        await update.message.delete()
        return
    
    try:
        await update.message.reply_to_message.delete()
        await update.message.delete()
        logger.info(f"Сообщение удалено админом {update.effective_user.username}")
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения: {e}")
        resp = await update.message.reply_text("❌ Не удалось удалить сообщение!")
        context.job_queue.run_once(
            lambda ctx: ctx.bot.delete_message(chat_id=update.message.chat.id, message_id=resp.message_id),
            10
        )

async def reset_pin_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_musician(update, context):
        resp = await update.message.reply_text("У вас нет прав для этой команды.")
        context.job_queue.run_once(
            lambda ctx: ctx.bot.delete_message(chat_id=update.message.chat.id, message_id=resp.message_id),
            10
        )
        await update.message.delete()
        return
        
    chat_id = update.message.chat.id
    if chat_id in pinned_messages:
        await context.bot.unpin_chat_message(chat_id, pinned_messages[chat_id]["message_id"])
        del pinned_messages[chat_id]
    if chat_id in last_pinned_times:
        del last_pinned_times[chat_id]
        
    resp = await update.message.reply_text("Таймер сброшен, можно публиковать новую ЗЧ.")
    context.job_queue.run_once(
        lambda ctx: ctx.bot.delete_message(chat_id=chat_id, message_id=resp.message_id),
        10
    )
    await update.message.delete()

async def update_google_table(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin_or_musician(update, context):
        resp = await update.message.reply_text("У вас нет прав для этой команды.")
        context.job_queue.run_once(
            lambda ctx: ctx.bot.delete_message(chat_id=update.message.chat.id, message_id=resp.message_id),
            10
        )
        await update.message.delete()
        return
    
    global STAR_MESSAGES
    STAR_MESSAGES = load_star_messages()
    
    resp = await update.message.reply_text(f"Google таблица обновлена. Загружено {len(STAR_MESSAGES)} записей.")
    context.job_queue.run_once(
        lambda ctx: ctx.bot.delete_message(chat_id=update.message.chat.id, message_id=resp.message_id),
        10
    )
    await update.message.delete()

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    job_queue = app.job_queue
    job_queue.run_repeating(cleanup_storage, interval=60, first=10)
    
    # Обработчики команд
    app.add_handler(CommandHandler("timer", reset_pin_timer))
    app.add_handler(CommandHandler("google", update_google_table))
    app.add_handler(CommandHandler("del", delete_message_command))
    
    # Обработчики сообщений
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.ALL & filters.UpdateType.EDITED_MESSAGE, handle_message_edit))
    app.add_handler(MessageHandler(filters.ALL & filters.UpdateType.MESSAGE, handle_message_delete))
    
    app.run_polling()
    logger.info("Бот запущен")

if __name__ == '__main__':
    main()
