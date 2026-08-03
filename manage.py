#!/usr/bin/env python
"""Django komut satırı yardımcısı."""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "halisaha.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Django bulunamadı. Sanal ortamı etkinleştirdiğinizden emin olun: "
            ".venv\\Scripts\\activate"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
