# Базовый образ Python
FROM python:3.10

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    libsqlite3-dev \
    python3-dev \
    build-essential

# Создание директории для приложения
WORKDIR /app

# Копирование файлов проекта
COPY . /app

# Установка зависимостей Python
RUN python -m venv /opt/venv && \
    . /opt/venv/bin/activate && \
    pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Команда для запуска бота
CMD ["/opt/venv/bin/python", "tg_bot_zvezda.py"]
