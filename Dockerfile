# Базовый образ Python
FROM python:3.10

# Установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода
COPY . .

# Запуск бота
CMD ["python", "tg_bot_zvezda.py"]
