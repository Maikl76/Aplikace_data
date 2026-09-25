# Obsah WSGI souboru na PythonAnywhere.
#
# Na záložce Web klikněte na odkaz „WSGI configuration file“, smažte
# celý jeho obsah a vložte tohle. JMENO nahraďte svým uživatelským
# jménem na PythonAnywhere.
#
# Tajemství (klíč, heslo správce) sem NEPATŘÍ – aplikace si je načte
# ze souboru .env ve složce s projektem.

import os
import sys

path = "/home/JMENO/Aplikace_data"
if path not in sys.path:
    sys.path.insert(0, path)

os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.prod"

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
