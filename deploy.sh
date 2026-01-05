#!/bin/bash

# Остановить выполнение скрипта при ошибке
set -e

echo "Начало деплоя Telegram-бота..."

# Перейти в папку с ботом
cd /opt/margarine7

# Обновить код из репозитория
echo "Обновление кода из репозитория..."
git pull origin main

# Перезапустить сервис
echo "Перезапуск сервиса Telegram-бота..."
sudo systemctl restart margarine7

echo "Деплой Telegram-бота завершён!"
