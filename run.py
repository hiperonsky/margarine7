from bot.main import main


import sys
import os

# отключаем буферизацию stdout/stderr, чтобы print сразу шёл в journalctl
os.environ["PYTHONUNBUFFERED"] = "1"
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)


if __name__ == "__main__":
    main()
