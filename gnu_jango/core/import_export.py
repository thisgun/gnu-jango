"""Small safety layer around django-import-export resources.

The package's formula setting is format-level and is not enough for every exporter path. These
helpers keep numeric export values numeric and prefix spreadsheet-formula-leading text at the
resource field boundary. ``UpdateOnlyResource`` also makes existing-row imports save only the
columns the file actually supplied instead of rewriting the whole model row.
"""

from import_export import resources

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def safe_export_value(value):
    if isinstance(value, str) and value[:1] in FORMULA_PREFIXES:
        return "'" + value
    return value


class SafeExportResource(resources.ModelResource):
    def export_field(self, field, instance, **kwargs):
        return safe_export_value(super().export_field(field, instance, **kwargs))


class UpdateOnlyResource(SafeExportResource):
    """Save existing records with ``update_fields`` limited to the supplied CSV columns."""

    protected_update_fields = ()

    def save_instance(self, instance, is_create, row, **kwargs):
        self.before_save_instance(instance, row, **kwargs)
        if not (self._is_dry_run(kwargs) and not self._is_using_transactions(kwargs)):
            if is_create:
                instance.save(force_insert=True)
            else:
                pk_name = self._meta.model._meta.pk.attname
                update_fields = []
                for field in self.get_import_fields():
                    attribute = getattr(field, "attribute", None)
                    column_name = getattr(field, "column_name", None) or attribute
                    if (
                        not attribute
                        or getattr(field, "readonly", False)
                        or column_name not in row
                        or attribute == pk_name
                        or attribute in self.protected_update_fields
                    ):
                        continue
                    update_fields.append(attribute)
                if update_fields:
                    instance.save(update_fields=update_fields)
        self.after_save_instance(instance, row, **kwargs)
