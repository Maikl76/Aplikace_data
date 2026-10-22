from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "apps.core"
    verbose_name = "Jádro"

    def ready(self):
        from django.db.backends.signals import connection_created

        from . import sqlite

        # Režim deníku SQLite podle místa databáze (WAL jen na místním disku).
        connection_created.connect(sqlite.on_connection_created,
                                   dispatch_uid="ftvs_sqlite_journal_mode")
