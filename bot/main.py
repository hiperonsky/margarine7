import os
import telebot
from yt_dlp import YoutubeDL
import subprocess
import re
import time

from bot import config  # ← было просто config
from bot import downloads_manager  # ← было просто downloads_manager
from bot.video_sender import send_video_to_user  # ← указали путь через bot

from yt_dlp.utils import DownloadError


bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN)

if not os.path.exists(config.DOWNLOAD_DIR):
    os.makedirs(config.DOWNLOAD_DIR)

# test comment 08/10/2025
def sanitize_filename(filename):
    """
    Удаляет из имени файла символы, которые могут вызывать конфликты.
    """
    return re.sub(r'[:"*?<>|/\\]', '', filename).strip()


def sanitize_filepath(filepath):
    """
    Применяет sanitize_filename ко всей части пути.
    """
    directory, filename = os.path.split(filepath)
    sanitized_filename = sanitize_filename(filename)
    return os.path.join(directory, sanitized_filename)


def notify_admin(user_id, username, message_text):

    bot.send_message(
        config.ADMIN_ID,
        f"🔔 Новый пользователь:\n"
        f"ID: {user_id}\n"
        f"Имя: {username}\n"
        f"Сообщение: {message_text}"
    )


def is_subscribed(user_id):
    """
    Проверяет, подписан ли пользователь на канал.
    """
    try:
        chat_member = bot.get_chat_member(config.CHANNEL_USERNAME, user_id)
        return chat_member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        print(f"Ошибка при проверке подписки: {e}")
        return False


def process_video(video_path):
    try:
        # Убедимся, что путь безопасен
        video_path = sanitize_filepath(video_path)
        fixed_video_path = sanitize_filepath(
            os.path.splitext(video_path)[0] + "_fixed.mp4"
        )

        # Перекодируем в совместимый формат: H.264 + AAC
        ffmpeg_command = [
            "ffmpeg", "-i", video_path,
            "-c:v", "libx264",             # Видео кодек
            "-preset", "fast",             # Скорость кодирования
            "-crf", "23",                  # Качество (меньше = лучше)
            "-c:a", "aac",                 # Аудио кодек
            "-b:a", "128k",                # Битрейт аудио
            "-movflags", "faststart",      # Для Telegram и веб
            fixed_video_path
        ]
        subprocess.run(ffmpeg_command, check=True)

        # Получение размеров видео
        ffmpeg_command = [
            "ffmpeg", "-i", fixed_video_path
        ]
        result = subprocess.run(
            ffmpeg_command,
            stderr=subprocess.PIPE,
            text=True
        )
        ffmpeg_output = result.stderr

        resolution_match = re.search(r'Video:.* (\d+)x(\d+)', ffmpeg_output)
        if resolution_match:
            width = int(resolution_match.group(1))
            height = int(resolution_match.group(2))
        else:
            raise ValueError("Не удалось извлечь размеры видео.")

        # Удаление оригинала
        if os.path.exists(video_path):
            os.remove(video_path)
            print(f"Оригинальное видео {video_path} удалено.")
        else:
            print(f"Оригинальное видео {video_path} не найдено для удаления.")

        return fixed_video_path, width, height

    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Ошибка при обработке видео через FFmpeg: {e}")


@bot.message_handler(commands=['youtube_blocked_test'])
def youtube_blocked_test(message):
    if message.from_user.id != config.ADMIN_ID:
        bot.reply_to(message, "Эта команда доступна только администратору.")
        return

    try:
        # Подготовка
        download_dir = os.path.join(os.path.dirname(__file__), 'downloads')
        os.makedirs(download_dir, exist_ok=True)
        output_template = os.path.join(download_dir, '%(title)s.%(ext)s')

        ytdlp_command = [
            "yt-dlp",
            "--proxy", "socks5://127.0.0.1:9050",
            "--cookies", "web_auth_storage.txt",
            "-f", "(bv*+ba/b)[height<=720]",
            "-o", output_template,
            "https://www.youtube.com/watch?v=QnaS8T4MdrI"
        ]

        # Первичное сообщение
        status_message = bot.send_message(message.chat.id, "🔄 Загрузка видео...")

        # Запуск yt-dlp
        process = subprocess.Popen(
            ytdlp_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        last_edit_time = 0
        for line in process.stdout:
            if not line.strip():
                continue

            print(f"[yt-dlp] {line.strip()}")  # лог в stdout → journalctl

            # Попытка найти прогресс
            progress_match = re.search(r'(\d{1,3}\.\d+)%', line)
            if progress_match:
                percent = float(progress_match.group(1))
                blocks = int(percent / 10)
                bar = "▓" * blocks + "░" * (10 - blocks)
                now = time.time()
                if now - last_edit_time > 1:  # не обновлять чаще 1 раза в секунду
                    bot.edit_message_text(
                        f"📥 Прогресс: `{bar} {percent:.1f}%`",
                        chat_id=message.chat.id,
                        message_id=status_message.message_id,
                        parse_mode="Markdown"
                    )
                    last_edit_time = now

        process.wait()

        if process.returncode != 0:
            bot.edit_message_text("❌ Загрузка завершилась с ошибкой.", chat_id=message.chat.id, message_id=status_message.message_id)
            return

        # Поиск и обработка видео
        downloaded_files = [f for f in os.listdir(download_dir) if f.endswith(('.mp4', '.mkv'))]
        if not downloaded_files:
            bot.edit_message_text("⚠️ Не удалось найти загруженное видео.", chat_id=message.chat.id, message_id=status_message.message_id)
            return

        video_path = os.path.join(download_dir, downloaded_files[0])
        fixed_video_path, width, height = process_video(video_path)

        # Отправка видео
        send_video_to_user(
            bot=bot,
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            username=message.from_user.username,
            url="https://www.youtube.com/watch?v=QnaS8T4MdrI",
            video_path=fixed_video_path,
            width=width,
            height=height,
            admin_id=config.ADMIN_ID
        )

        # Удаление
        if os.path.exists(fixed_video_path):
            os.remove(fixed_video_path)

    except Exception as e:
        bot.send_message(message.chat.id, f"🚫 Ошибка: {e}")


@bot.message_handler(commands=['instagram_test'])
def instagram_test(message):
    if message.from_user.id != config.ADMIN_ID:
        bot.reply_to(message, "Эта команда доступна только администратору.")
        return

    try:
        # Подготовка путей и команды
        download_dir = os.path.join(os.path.dirname(__file__), 'downloads')
        os.makedirs(download_dir, exist_ok=True)
        output_template = os.path.join(download_dir, '%(title)s.%(ext)s')

        ytdlp_command = [
            "yt-dlp",
            "--proxy", "socks5://127.0.0.1:9050",
            "--cookies", "web_auth_storage.txt",
            "-f", "mp4",
            "-o", output_template,
            "https://www.instagram.com/reel/DFk0NvTuX4S/?igsh=MWZ1MTFhOWExMGV5bQ=="
        ]

        # Первичное сообщение
        status_message = bot.send_message(message.chat.id, "🔄 Загрузка Instagram-видео...")

        # Запуск yt-dlp с выводом прогресса
        process = subprocess.Popen(
            ytdlp_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        last_edit_time = 0
        for line in process.stdout:
            if not line.strip():
                continue

            # Отображение прогресса
            progress_match = re.search(r'(\d{1,3}\.\d+)%', line)
            if progress_match:
                percent = float(progress_match.group(1))
                blocks = int(percent / 10)
                bar = "▓" * blocks + "░" * (10 - blocks)
                now = time.time()
                if now - last_edit_time > 1:
                    bot.edit_message_text(
                        f"📥 Прогресс: `{bar} {percent:.1f}%`",
                        chat_id=message.chat.id,
                        message_id=status_message.message_id,
                        parse_mode="Markdown"
                    )
                    last_edit_time = now

        process.wait()

        if process.returncode != 0:
            bot.edit_message_text("❌ Ошибка при загрузке видео.", chat_id=message.chat.id, message_id=status_message.message_id)
            return

        # Поиск загруженного файла
        downloaded_files = [f for f in os.listdir(download_dir) if f.endswith(('.mp4', '.mkv'))]
        if not downloaded_files:
            bot.edit_message_text("⚠️ Не удалось найти загруженное видео.", chat_id=message.chat.id, message_id=status_message.message_id)
            return

        video_path = os.path.join(download_dir, downloaded_files[0])

        # Обработка видео
        fixed_video_path, width, height = process_video(video_path)

        # Отправка пользователю
        send_video_to_user(
            bot=bot,
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            username=message.from_user.username,
            url="https://www.instagram.com/reel/DFk0NvTuX4S/?igsh=MWZ1MTFhOWExMGV5bQ==",
            video_path=fixed_video_path,
            width=width,
            height=height,
            admin_id=config.ADMIN_ID
        )

        # Удаление обработанного файла
        if os.path.exists(fixed_video_path):
            os.remove(fixed_video_path)

    except Exception as e:
        bot.send_message(message.chat.id, f"🚫 Ошибка: {e}")


@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    notify_admin(
        message.from_user.id,
        message.from_user.username,
        message.text
    )

    # Приветственное сообщение
    bot.reply_to(
        message,
        "Привет! Отправь мне ссылку на видео, и я скачаю его для тебя"
    )

    # Отправка видеоинструкции
    try:
        with open("margarine_intro.mp4", "rb") as video:
            bot.send_video(
                message.chat.id,
                video,
                caption=(
                    "Посмотрите видеоинструкцию, чтобы узнать, "
                    "как пользоваться ботом."
                )
            )
    except Exception as e:
        bot.send_message(
            config.ADMIN_ID,
            f"⚠️ Ошибка при отправке видеоинструкции:\n\n"
            f"Пользователь: @{message.from_user.username} "
            f"(ID: {message.from_user.id})\n"
            f"Ошибка: {e}"
        )


@bot.message_handler(commands=['show_downloads'])
def show_downloads(message):
    if message.from_user.id == config.ADMIN_ID:
        try:
            files = downloads_manager.list_downloads(config.DOWNLOAD_DIR)
            if files:
                bot.send_message(
                    message.chat.id,
                    "Содержимое папки downloads:\n" + "\n".join(files)
                )
            else:
                bot.send_message(message.chat.id, "Папка downloads пуста.")
        except Exception as e:
            bot.send_message(
                message.chat.id,
                f"Ошибка при получении содержимого папки: {e}"
            )
    else:
        bot.reply_to(message, "Эта команда доступна только администратору.")


@bot.message_handler(commands=['clean_downloads'])
def clean_downloads(message):
    if message.from_user.id == config.ADMIN_ID:
        try:
            downloads_manager.clean_downloads(config.DOWNLOAD_DIR)
            bot.send_message(message.chat.id, "Папка downloads очищена.")
        except Exception as e:
            bot.send_message(message.chat.id, f"Ошибка при очистке папки: {e}")
    else:
        bot.reply_to(message, "Эта команда доступна только администратору.")


def get_format_str(url):
    if 'instagram.com' in url or 'vimeo.com' in url:
        return 'b'
    elif 'youtube.com/shorts/' in url:
        # Shorts — только fallback без ограничений
        return 'bv*+ba/b/best'
    else:
        return (
            "bestvideo[height=480]+bestaudio/best[height=480]/"
            "bestvideo[height=720]+bestaudio/best[height=720]/"
            "bestvideo[height=360]+bestaudio/best[height=360]/"
            "bv*+ba/b/best"
        )


#def download_with_options(url, use_tor=False):
def download_with_options(url):
    ydl_opts = {
        'format': get_format_str(url),
        'outtmpl': f'{config.DOWNLOAD_DIR}/%(title)s.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'merge_output_format': 'mp4',
        'force_keyframes_at_cuts': True,
        'overwrites': True,
        'noplaylist': True,
        'no_sabr': True,
        'restrictfilenames': True,
        'geo_bypass': True,
        'retries': 5,
        'fragment_retries': 5,
        'continuedl': True,
    }

#    if use_tor:
#        ydl_opts['proxy'] = 'socks5://127.0.0.1:9050'
#        ydl_opts['cookiefile'] = '/root/Margarine6_bot/web_auth_storage.txt'

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        video_path = sanitize_filepath(ydl.prepare_filename(info))
        return process_video(video_path)


#def download_video_file(url):
#    try:
#        return download_with_options(url)
#    except Exception as e:
#        print(f"[BOT] Ошибка при первой попытке скачивания: {e}")
#        try:
#            return download_with_options(url, use_tor=True)
#        except Exception as e2:
#            raise RuntimeError(f"[BOT] Ошибка даже через Tor: {e2}")
        
def download_video_file(url):
    try:
        return download_with_options(url)
    except Exception as e:
        raise RuntimeError(f"[BOT] Ошибка при скачивании видео: {e}")
    
def log(msg: str):
    print(msg, flush=True)



def download_with_progress(url, bot, chat_id, status_message, download_dir):
    log(f"[BOT] download_with_progress called for url={url}")
    os.makedirs(download_dir, exist_ok=True)
    output_template = os.path.join(download_dir, '%(title)s.%(ext)s')
    format_str = get_format_str(url)

    ytdlp_command = [
        "yt-dlp",
        "-f", format_str,
        "-o", output_template,
        "--merge-output-format", "mp4",
        "--force-keyframes-at-cuts",
        "--no-playlist",
#        "--no-sabr",
        "--restrict-filenames",
        "--geo-bypass",
        "--retries", "5",
        "--fragment-retries", "5",
        "--continue",
#        "--no-warnings",
#        "--quiet",
        url,
    ]

    log(f"[BOT] running command: {' '.join(ytdlp_command)}")

    process = subprocess.Popen(
        ytdlp_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

output_lines = []
last_edit_time = 0

for line in process.stdout:
    if not line.strip():
        continue

    text = line.rstrip("\n")
    output_lines.append(text)
    log(f"[yt-dlp] {text}")

    now = time.time()
    if now - last_edit_time > 1:  # не чаще раза в секунду
        try:
            bot.edit_message_text(
                f"```{text[-4000:]}```",   # последний лог yt-dlp, обрезаем если длинный
                chat_id=chat_id,
                message_id=status_message.message_id,
                parse_mode="Markdown"
            )
            last_edit_time = now
        except Exception:
            pass

    process.wait()
    log(f"[BOT] yt-dlp returncode={process.returncode}")

    if process.returncode != 0:
        debug_output = "".join(output_lines)
        log(f"[yt-dlp ERROR] output:\n{debug_output}")
        raise RuntimeError("Загрузка завершилась с ошибкой (yt-dlp)")

    downloaded_files = [f for f in os.listdir(download_dir) if f.endswith(('.mp4', '.mkv'))]
    if not downloaded_files:
        raise RuntimeError("Не удалось найти загруженное видео после скачивания")

    return os.path.join(download_dir, downloaded_files[0])


@bot.message_handler(content_types=['text'])
def handle_download_request(message):
    log(f"[BOT] handle_download_request from {message.from_user.id}: {message.text}")
    if not is_subscribed(message.from_user.id):
        bot.reply_to(
            message,
            "Бот бесплатный, но работает только для подписчиков "
            "моего телеграм канала: "
            "[Передатчик Вована](https://t.me/+AM5qac1gwTUwMGNi)",
            parse_mode='Markdown'
        )
        return

    notify_admin(
        message.from_user.id,
        message.from_user.username,
        message.text
    )

    url = message.text

    # Первичное сообщение — его будем обновлять
    status_message = bot.reply_to(message, "🔄 Начинаю загрузку видео...")

    try:
        # 1. Скачивание с прогрессом (через yt-dlp CLI)
        video_path = download_with_progress(
            url=url,
            bot=bot,
            chat_id=message.chat.id,
            status_message=status_message,
            download_dir=config.DOWNLOAD_DIR,
        )

        # 2. Обработка видео (как было)
        fixed_video_path, width, height = process_video(video_path)

        # 3. Отправка видео
        send_video_to_user(
            bot,
            message.chat.id,
            message.from_user.id,
            message.from_user.username,
            url,
            fixed_video_path,
            width,
            height,
            config.ADMIN_ID
        )

        # 4. Обновляем статус
        bot.edit_message_text(
            "✅ Видео готово и отправлено.",
            chat_id=message.chat.id,
            message_id=status_message.message_id,
        )

        # 5. Удаляем файл
        if os.path.exists(fixed_video_path):
            os.remove(fixed_video_path)

    except Exception as e:
        # Если что-то пошло не так — редактируем статусное сообщение
        try:
            bot.edit_message_text(
                f"🚫 Ошибка при скачивании: {e}",
                chat_id=message.chat.id,
                message_id=status_message.message_id,
            )
        except Exception:
            bot.reply_to(message, f"🚫 Ошибка при скачивании: {e}")



def main():
    # здесь запускается твой бот
    bot.polling()  # или executor.start_polling(...) — зависит от реализации

if __name__ == "__main__":
    main()
