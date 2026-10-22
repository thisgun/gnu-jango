"""Stored PostgreSQL vectors with an inert SQLite column for portable migrations."""
from django.db import models


class StoredVectorField(models.Field):
    def db_type(self, connection):
        return "tsvector" if connection.vendor == "postgresql" else "text"


class TokenVector(models.Func):
    output_field = StoredVectorField()

    def as_postgresql(self, compiler, connection):
        from django.contrib.postgres.search import SearchVector
        return SearchVector(*self.source_expressions, config="simple").as_sql(compiler, connection)

    def as_sqlite(self, compiler, connection):
        return "''", []


def vector_reference(name):
    from django.contrib.postgres.search import SearchVectorField
    return models.ExpressionWrapper(models.F(name), output_field=SearchVectorField())
