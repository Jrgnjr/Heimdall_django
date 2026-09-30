#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Point d'entrée des commandes Django."""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as souci:
        raise ImportError(
            "Django est introuvable. L'environnement virtuel est-il activé ?"
        ) from souci
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
