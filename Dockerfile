# Используем официальный образ Python
FROM python:3.10-slim

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Создаем рабочую директорию
WORKDIR /app

# Копируем зависимости
COPY requirements.txt .

# Обновляем pip и устанавливаем зависимости
RUN pip install --upgrade pip && \
    pip install --no-cache-dir \
    --use-deprecated=legacy-resolver \  # Для обхода конфликтов зависимостей
    -r requirements.txt

# Копируем исходный код
COPY . .

# Запускаем бота
CMD ["python3.10", "tg_bot_zvezda.py"]
