import os


def list_downloads(download_dir):
    """
    Возвращает список файлов в указанной папке.
    """
    try:
        files = os.listdir(download_dir)
        return files
    except Exception as e:
        raise RuntimeError(f"Ошибка при получении содержимого папки: {e}")


def clean_downloads(download_dir):
    """
    Очищает указанную папку.
    """
    try:
        for filename in os.listdir(download_dir):
            file_path = os.path.join(download_dir, filename)
            if os.path.isfile(file_path):
                os.remove(file_path)
    except Exception as e:
        raise RuntimeError(f"Ошибка при очистке папки: {e}")
