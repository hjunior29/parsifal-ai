from django.contrib.auth.models import User
from django.core.files.storage import FileSystemStorage, storages
from django.db import models, transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _

FILES_STORAGE = "files"


def files_storage():
    """Where uploaded files are kept: a private folder in the data directory or an S3-compatible bucket."""
    return storages[FILES_STORAGE]


def files_are_local():
    return isinstance(files_storage(), FileSystemStorage)


class StoredFile(models.Model):
    """
    One uploaded file and where it is kept. Records point at it (a study's full text is ``Article.pdf``); the object
    in the storage is deleted with the row, once the transaction commits.
    """

    key = models.CharField(max_length=255, unique=True)  # its name in the storage
    filename = models.CharField(max_length=255)  # the name it was uploaded with, given back on download
    content_type = models.CharField(max_length=100)
    size = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    uploaded_by = models.ForeignKey(User, null=True, blank=True, related_name="+", on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("stored file")
        verbose_name_plural = _("stored files")

    def __str__(self):
        return self.filename

    def open(self):
        return files_storage().open(self.key, "rb")


@receiver(post_delete, sender=StoredFile)
def delete_stored_object(sender, instance, **kwargs):
    key = instance.key
    transaction.on_commit(lambda: files_storage().delete(key))
