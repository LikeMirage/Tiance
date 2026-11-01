"""Execute frozen SQL scripts without sqlite3.executescript's implicit commit."""

import sqlite3


def execute_script(connection: sqlite3.Connection, script: str) -> None:
    statement = ""
    for char in script:
        statement += char
        if char == ";" and sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    # Permit trailing whitespace/comments, but never silently drop unfinished SQL.
    if statement.strip():
        connection.execute(statement)
