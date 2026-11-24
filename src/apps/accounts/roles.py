"""Two roles.

- Administrator: a superuser (the account from ADMIN_EMAIL). Manages photos and users.
- Editor: an account an administrator adds. Uploads, edits, deletes and restores photos; cannot
  delete photos permanently (that removes evidence from storage) or manage users.
"""

from django.contrib.auth.models import Group, Permission

EDITORS = "Editors"
EDITOR_PERMISSIONS = ("add_photo", "change_photo", "delete_photo", "view_photo")


def editors_group() -> Group:
    """The Editors group with exactly the editor permissions (created on first use)."""
    group, _ = Group.objects.get_or_create(name=EDITORS)
    wanted = set(Permission.objects.filter(content_type__app_label="photos", content_type__model="photo",
                                           codename__in=EDITOR_PERMISSIONS))
    if set(group.permissions.all()) != wanted:
        group.permissions.set(wanted)
    return group


def role_label(user) -> str:
    return "Administrator" if user.is_superuser else "Editor"


def split_name(full_name: str) -> tuple[str, str]:
    first, _, last = " ".join(full_name.split()).partition(" ")
    return first[:150], last[:150]
