"""Refuse a Preview connection routed to the wrong role or schema."""
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db.backends.postgresql.base import DatabaseWrapper as PostgreSQLDatabaseWrapper


class DatabaseWrapper(PostgreSQLDatabaseWrapper):
    def get_new_connection(self, conn_params):
        connection = super().get_new_connection(conn_params)
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_user, current_schema()")
            role, schema = cursor.fetchone()
        # Django configures autocommit after get_new_connection returns.
        connection.rollback()
        if (role, schema) != (settings.PREVIEW_DB_ROLE, settings.PREVIEW_DB_SCHEMA):
            connection.close()
            raise ImproperlyConfigured("Preview DB role/schema isolation check failed.")
        return connection
