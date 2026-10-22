"""
Režim deníku SQLite podle toho, kde databáze leží.

WAL (čtení souběžně se zápisem) potřebuje sdílenou paměť mezi procesy,
které databázi otevírají, a proto funguje jen na místním disku. Na
PythonAnywhere běží webová aplikace a konzole na různých strojích nad
síťovým diskem – tam by WAL mohl ztratit zapsaná data. Tam se databáze
drží v klasickém režimu (delete) a databáze, kterou předchozí verze
přepnula do WAL, se převede zpět.

Přechod z WAL jde jen tehdy, když databázi nemá otevřenou nikdo jiný;
jinak SQLite hned odpoví „database is locked“. Pokus se proto dělá při
každém novém připojení a neúspěch se tiše přejde – převede to první
proces, který bude s databází sám.
"""

import logging
import sqlite3

from django.conf import settings

logger = logging.getLogger(__name__)


def wanted_mode() -> str:
    return "wal" if getattr(settings, "SQLITE_WAL", False) else "delete"


def set_journal_mode(raw) -> str:
    """
    Nastaví režim deníku na spojení ``raw`` (sqlite3.Connection v režimu
    autocommit), pokud to jde. Vrací režim, ve kterém databáze je.
    """
    mode = raw.execute("PRAGMA journal_mode").fetchone()[0].lower()
    if mode == "memory":                      # databáze v paměti (testy)
        return mode
    wanted = wanted_mode()
    if mode != wanted:
        try:
            mode = raw.execute(f"PRAGMA journal_mode={wanted}").fetchone()[0].lower()
        except sqlite3.OperationalError:
            logger.info("Režim databáze zůstal %s – je otevřená i jinde, převede se později.",
                        mode)
    if mode == "wal":
        raw.execute("PRAGMA synchronous=NORMAL")
    return mode


def on_connection_created(sender, connection, **kwargs):
    if connection.vendor == "sqlite":
        set_journal_mode(connection.connection)
