"""Create or update the first administrator account interactively."""
from getpass import getpass
from werkzeug.security import generate_password_hash
from mysql.connector import IntegrityError
from db.connection import get_cursor


def main():
    username = input("Admin username: ").strip()
    if not username:
        raise SystemExit("Username cannot be empty.")
    password = getpass("Admin password (minimum 10 characters): ")
    confirm = getpass("Confirm password: ")
    if len(password) < 10:
        raise SystemExit("Use a password with at least 10 characters.")
    if password != confirm:
        raise SystemExit("Passwords do not match.")
    password_hash = generate_password_hash(password)
    with get_cursor(commit=True) as cursor:
        cursor.execute(
            "INSERT INTO users (username, password_hash, role, is_active) VALUES (%s, %s, 'admin', TRUE) "
            "ON DUPLICATE KEY UPDATE password_hash=VALUES(password_hash), role='admin', is_active=TRUE",
            (username, password_hash),
        )
    print(f"Administrator '{username}' is ready. Keep the password private.")


if __name__ == "__main__":
    main()
