"""Reopen transient mobile menus under the shared navigation semantics."""
from datetime import UTC, datetime


def upgrade(connection):
    # Old WeChat stacks did not contain conversation frames. Reusing their
    # numbers/back paths would route input differently after this upgrade.
    # Keep selections, jobs, receipts, attachments and permission callbacks.
    connection.execute("DELETE FROM mobile_records WHERE namespace IN ('menus', 'navigation')")
    connection.execute('INSERT INTO schema_migrations VALUES (56, ?, ?)',
                       ('mobile_menu_paths', datetime.now(UTC).isoformat()))
