import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models
class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    class Role(models.TextChoices):
        STUDENT='student','Student'; RESEARCHER='researcher','Researcher'; PROFESSOR='professor','Professor'; ADMIN='admin','Admin'
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)
    full_name = models.CharField(max_length=160, blank=True)
