"""Database connection manager using mysql-connector-python."""

from __future__ import annotations

import os
import logging
from contextlib import contextmanager
from typing import Generator, Any
import mysql.connector
from mysql.connector import Error as MySQLError
from mysql.connector.cursor import MySQLCursor
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def get_db_config() -> dict[str, Any]:
    """Retrieve MySQL connection configuration parameters from environment."""
    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", "3306")),
        "user": os.getenv("DB_USER", "root"),
        "password": os.getenv("DB_PASSWORD", ""),
        "database": os.getenv("DB_NAME", "organ_allocation"),
        "charset": "utf8mb4",
        "autocommit": False,
    }


def get_connection(include_db: bool = True) -> mysql.connector.MySQLConnection:
    """Establish and return a new MySQL connection.

    Args:
        include_db: Whether to connect to the specific target database.
            Set to False when running initial database creation scripts.

    Returns:
        Active MySQL connection instance.

    Raises:
        MySQLError: If database connection cannot be established.
    """
    config = get_db_config()
    if not include_db:
        config.pop("database", None)

    try:
        conn = mysql.connector.connect(**config)
        return conn
    except MySQLError as err:
        logger.error("Failed to connect to MySQL database: %s", err)
        raise


@contextmanager
def get_cursor(
    dictionary: bool = True,
    include_db: bool = True,
    commit: bool = True,
) -> Generator[MySQLCursor, None, None]:
    """Context manager providing a database cursor with automatic commit/rollback.

    Args:
        dictionary: Whether to return rows as dictionaries instead of tuples.
        include_db: Whether to connect to the target database.
        commit: Whether to commit transaction upon successful execution.

    Yields:
        Active MySQLCursor instance.
    """
    conn = None
    cursor = None
    try:
        conn = get_connection(include_db=include_db)
        cursor = conn.cursor(dictionary=dictionary)
        yield cursor
        if commit:
            conn.commit()
    except Exception as err:
        if conn and conn.is_connected():
            conn.rollback()
        logger.error("Database operation failed: %s", err)
        raise
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()
