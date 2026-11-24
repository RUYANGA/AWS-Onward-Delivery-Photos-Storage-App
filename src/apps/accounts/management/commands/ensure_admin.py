"""Create or update the administrator account from the environment.

    ADMIN_EMAIL     sign-in email (Parameter Store in AWS)
    ADMIN_NAME      full name shown in the app and the change history (Parameter Store)
    ADMIN_PASSWORD  password (Secrets Manager in AWS; never in the code or the repositories)

Every task runs this at start, after the migrations, so the secret is the source of truth: change
the password in Secrets Manager and the next task start applies it. With --if-configured it does
nothing when the variables are not set (local runs without an admin).
"""

import logging
import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import transaction

from apps.accounts.forms import normalise_email
from apps.accounts.roles import editors_group

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Create or update the administrator from ADMIN_EMAIL, ADMIN_NAME and ADMIN_PASSWORD."

    def add_arguments(self, parser):
        parser.add_argument("--if-configured", action="store_true",
                            help="Do nothing (instead of failing) when ADMIN_EMAIL or ADMIN_PASSWORD is not set.")

    def handle(self, *args, **options):
        editors_group()  # create the Editors group, or bring its permissions up to date
        email = normalise_email(os.environ.get("ADMIN_EMAIL"))
        name = " ".join((os.environ.get("ADMIN_NAME") or "").split())
        password = os.environ.get("ADMIN_PASSWORD") or ""  # only from the environment: never a CLI argument

        if not email or not password:
            if options["if_configured"]:
                self.stdout.write("Administrator not configured (ADMIN_EMAIL / ADMIN_PASSWORD unset); skipped.")
                return
            raise CommandError("Set ADMIN_EMAIL and ADMIN_PASSWORD (and optionally ADMIN_NAME).")
        try:
            validate_email(email)
        except ValidationError as exc:
            raise CommandError(f"ADMIN_EMAIL is not a valid email address: {email!r}") from exc

        first_name, _, last_name = name.partition(" ")
        User = get_user_model()
        with transaction.atomic():
            user, created = User.objects.select_for_update().get_or_create(
                username=email, defaults={"email": email})
            try:
                validate_password(password, user=User(username=email, email=email,
                                                      first_name=first_name, last_name=last_name))
            except ValidationError as exc:
                raise CommandError("ADMIN_PASSWORD is too weak: " + " ".join(exc.messages)) from exc

            user.email = email
            user.first_name, user.last_name = first_name[:150], last_name[:150]
            user.is_active = user.is_staff = user.is_superuser = True
            password_changed = created or not user.check_password(password)
            if password_changed:
                user.set_password(password)
            user.save()

        if created:
            message = f"Administrator {email} created."
        elif password_changed:
            message = f"Administrator {email} updated; password changed to the configured one."
        else:
            message = f"Administrator {email} is up to date."
        log.info(message, extra={"user_id": user.pk, "account_created": created,
                                "password_changed": password_changed})
        self.stdout.write(self.style.SUCCESS(message))
