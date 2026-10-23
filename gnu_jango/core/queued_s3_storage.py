from storages.backends.s3 import S3Storage

from .queued_storage import QueueImagesMixin


class QueuedS3Storage(QueueImagesMixin, S3Storage):
    pass
