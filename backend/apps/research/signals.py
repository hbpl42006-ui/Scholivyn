from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import DocumentVersion


@receiver(post_delete, sender=DocumentVersion)
def remove_private_file(sender, instance, **kwargs):
    path = Path(settings.PRIVATE_DOCUMENT_ROOT) / instance.storage_key
    transaction.on_commit(lambda: path.unlink(missing_ok=True))
