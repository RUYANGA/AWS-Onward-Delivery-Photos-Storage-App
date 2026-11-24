from django.conf import settings
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


class Activity(models.Model):
    """What someone did in the app: the audit trail administrators read on a user's page."""

    class Action(models.TextChoices):
        SIGNED_IN = "signed_in", "Signed in"
        SIGN_IN_FAILED = "sign_in_failed", "Failed sign-in"
        SIGNED_OUT = "signed_out", "Signed out"
        UPLOADED = "uploaded", "Uploaded a photo"
        EDITED = "edited", "Edited a photo"
        DELETED = "deleted", "Deleted a photo"
        RESTORED = "restored", "Restored a photo"
        PURGED = "purged", "Deleted a photo permanently"
        NAME_CHANGED = "name_changed", "Changed their name"
        PASSWORD_CHANGED = "password_changed", "Changed their password"
        USER_ADDED = "user_added", "Added a user"
        USER_UPDATED = "user_updated", "Updated a user"
        USER_DELETED = "user_deleted", "Deleted a user"

    GROUPS = {
        "photos": (Action.UPLOADED, Action.EDITED, Action.DELETED, Action.RESTORED, Action.PURGED),
        "sign-ins": (Action.SIGNED_IN, Action.SIGN_IN_FAILED, Action.SIGNED_OUT),
        "account": (Action.NAME_CHANGED, Action.PASSWORD_CHANGED, Action.USER_ADDED, Action.USER_UPDATED,
                    Action.USER_DELETED),
    }

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="activities")  # who did it
    actor_name = models.CharField(max_length=150, blank=True, default="")  # their name at the time
    action = models.CharField(max_length=32, choices=Action.choices, db_index=True)
    photo = models.ForeignKey("photos.Photo", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    account = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="account_events")  # the user an administrator changed
    subject = models.CharField(max_length=255, blank=True, default="")  # e.g. "ONW-2026-3F9A1C · Title"
    detail = models.CharField(max_length=500, blank=True, default="")  # e.g. the reason for an edit
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = "activity"
        ordering = ["-at", "-id"]
        indexes = [models.Index(fields=["user", "-at"], name="activity_user_at")]

    def __str__(self):
        return f"{self.actor_name or 'someone'} {self.get_action_display().lower()} at {self.at:%Y-%m-%d %H:%M}"

    @property
    def icon(self) -> str:
        return {
            "signed_in": "log-in", "sign_in_failed": "alert", "signed_out": "log-out", "uploaded": "upload",
            "edited": "edit", "deleted": "trash", "restored": "restore", "purged": "trash",
            "name_changed": "user", "password_changed": "key", "user_added": "user-plus",
            "user_updated": "users", "user_deleted": "users",
        }.get(self.action, "info")

    @property
    def tone(self) -> str:
        return {"sign_in_failed": "danger", "purged": "danger", "deleted": "warn", "user_deleted": "danger",
                "restored": "ok", "uploaded": "ok"}.get(self.action, "")
