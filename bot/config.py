import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Telegram Admin ID — убедись, что он приводится к int
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Папки
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "downloads")
CONVERTED_DIR = os.getenv("CONVERTED_DIR", "converted")

# Канал
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@example_channel")