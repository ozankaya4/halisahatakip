#!/usr/bin/env python
"""Django komut satırı yardımcısı."""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "halisaha.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        # Yol işletim sistemine göre değişiyor. Mesaj bir dönem her yerde
        # Windows yolunu yazıyordu ve sunucuda ".venv\Scripts\activate"
        # diyerek insanı olmayan bir dosyaya yolluyordu.
        if os.name == "nt":
            etkinlestir = r".venv\Scripts\activate"
            calistir = r".venv\Scripts\python.exe manage.py " + " ".join(sys.argv[1:])
        else:
            etkinlestir = "source .venv/bin/activate"
            calistir = "./.venv/bin/python manage.py " + " ".join(sys.argv[1:])
        raise ImportError(
            "Django bulunamadı. Sanal ortamı etkinleştirin:\n"
            f"    {etkinlestir}\n"
            "ya da etkinleştirmeden doğrudan çalıştırın:\n"
            f"    {calistir}"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
