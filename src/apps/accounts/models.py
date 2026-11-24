from django.db import models
from django.utils import timezone


class FailedSignIn(models.Model):
    """One failed sign-in, kept briefly to slow down password guessing (see throttle.py)."""

    email = models.CharField(max_length=254, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    attempted_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "failed_sign_ins"

    def __str__(self):
        return f"{self.email} from {self.ip_address} at {self.attempted_at:%Y-%m-%d %H:%M}"
