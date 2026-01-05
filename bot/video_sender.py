import os
import subprocess
import json
import asyncio


def get_segment_time(path, max_size_mb=50, reserve=0.95):
    """
    Вычисляет длительность сегмента (в секундах), чтобы каждый файл
    был не больше max_size_mb.
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration,size",
        "-of", "json", path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    info = json.loads(result.stdout)["format"]
    duration = float(info["duration"])       # в секундах
    size_bytes = float(info["size"])         # в байтах

    max_bytes = max_size_mb * 1024**2 * reserve
    raw_time = (max_bytes / size_bytes) * duration
    seg = int(raw_time)

    return max(10, min(seg, 600))


async def send_video_to_user(
    bot, chat_id, user_id, username, url, video_path, width, height, admin_id
):
    try:
        # Получение размера файла (в отдельном потоке)
        file_size = await asyncio.to_thread(os.path.getsize, video_path)
        file_size_mb = file_size / (1024 * 1024)

        # Если файл больше 50 МБ, разделяем его на части
        if file_size_mb > 50:
            await bot.send_message(
                chat_id,
                "Файл больше 50 МБ, попробую разделить его на несколько частей "
                "и отправить вам одну за другой."
            )

            parts_dir = os.path.dirname(video_path)
            original_filename = os.path.basename(video_path)
            base_filename, ext = os.path.splitext(original_filename)
            part_filenames = []

            # Вычисляем оптимальную длительность сегмента
            seg_time = get_segment_time(video_path, max_size_mb=50)
            output_template = os.path.join(parts_dir, f"{base_filename}_part%02d{ext}")
            ffmpeg_command = [
                "ffmpeg",
                "-i", video_path,
                "-c", "copy",
                "-map", "0",
                "-f", "segment",
                "-segment_time", str(seg_time),
                "-reset_timestamps", "1",
                output_template
            ]

            # ffmpeg остаётся синхронным → в поток
            await asyncio.to_thread(subprocess.run, ffmpeg_command, check=True)

            # Удаляем оригинальный файл после деления
            if os.path.exists(video_path):
                await asyncio.to_thread(os.remove, video_path)
                print(f"Исходное видео {video_path} удалено после деления.")

            # Формируем список частей (тоже в поток)
            def _collect_parts():
                res = []
                for filename in os.listdir(parts_dir):
                    if filename.startswith(base_filename) and filename.endswith(ext):
                        res.append(os.path.join(parts_dir, filename))
                return res

            part_filenames = await asyncio.to_thread(_collect_parts)

            # Уведомление администратора о делении
            parts_info_lines = []
            for part in sorted(part_filenames):
                size_mb = (await asyncio.to_thread(os.path.getsize, part)) / (1024 * 1024)
                parts_info_lines.append(
                    f"{os.path.basename(part)} ({size_mb:.2f} MB)"
                )

            await bot.send_message(
                admin_id,
                "⚠️ Видео разделено на части:\n"
                f"ID: {user_id}\n"
                f"Имя: @{username}\n"
                f"Ссылка: {url}\n"
                f"Имя исходного файла: {original_filename} ({file_size_mb:.2f} MB)\n"
                f"Части:\n" + "\n".join(parts_info_lines)
            )

            # Отправка частей пользователю
            for part_path in sorted(part_filenames):
                part_size_mb = (
                    await asyncio.to_thread(os.path.getsize, part_path)
                ) / (1024 * 1024)

                if part_size_mb > 50:
                    await bot.send_message(
                        chat_id,
                        f"⚠️ Одна из частей ({os.path.basename(part_path)}) "
                        f"превышает 50 МБ. Я не могу отправить её через Telegram."
                    )
                    continue

                # Чтение файла в потоках, чтобы не блокировать event loop
                def _read_file(path):
                    with open(path, "rb") as f:
                        return f.read()

                data = await asyncio.to_thread(_read_file, part_path)
                await bot.send_video(chat_id, data, width=width, height=height)

                await asyncio.to_thread(os.remove, part_path)
                print(f"Часть {part_path} отправлена и удалена.")

            return

        # Если файл меньше 50 МБ, отправляем как обычно
        def _read_main(path):
            with open(path, "rb") as f:
                return f.read()

        data = await asyncio.to_thread(_read_main, video_path)
        await bot.send_video(chat_id, data, width=width, height=height)

        # Уведомление администратора о завершении
        await bot.send_message(
            admin_id,
            "✅ Видео успешно скачано и отправлено пользователю:\n"
            f"ID: {user_id}\n"
            f"Имя: @{username}\n"
            f"Ссылка: {url}\n"
            f"Имя файла: {os.path.basename(video_path)}\n"
            f"Размер файла: {file_size_mb:.2f} MB"
        )

    except subprocess.CalledProcessError as e:
        await bot.send_message(admin_id, f"Ошибка при делении файла: {e}")
        raise
    except Exception as e:
        await bot.send_message(admin_id, f"Ошибка при отправке видео: {e}")
        raise
    finally:
        if os.path.exists(video_path):
            await asyncio.to_thread(os.remove, video_path)
            print(f"Видео {video_path} удалено.")
        else:
            print(f"Видео {video_path} не найдено для удаления.")
