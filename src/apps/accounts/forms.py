from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm

from .roles import split_name


def normalise_email(value: str | None) -> str:
    return (value or "").strip().lower()


class SignInForm(AuthenticationForm):
    """Sign in with an email address (accounts use the email as their username)."""

    username = forms.EmailField(
        label="Email address",
        max_length=254,
        error_messages={"required": "Enter your email address.", "invalid": "Enter a valid email address."},
        widget=forms.EmailInput(attrs={"autocomplete": "username", "autofocus": True}),
    )
    password = forms.CharField(
        label="Password",
        strip=False,
        error_messages={"required": "Enter your password."},
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    error_messages = {
        **AuthenticationForm.error_messages,
        # The same message whether the email or the password is wrong, so accounts can't be discovered.
        "invalid_login": "The email address or password is incorrect.",
        "inactive": "This account is disabled. Ask an administrator to enable it.",
    }

    def clean_username(self):
        return normalise_email(self.cleaned_data.get("username"))


class FullNameField(forms.CharField):
    def __init__(self, **kwargs):
        super().__init__(label="Full name", max_length=150, min_length=2, **kwargs,
                         error_messages={"required": "Enter the full name.",
                                         "min_length": "Enter the full name."})

    def clean(self, value):
        return " ".join((super().clean(value) or "").split())


class UserForm(forms.Form):
    """Add or edit an editor's account (administrators only)."""

    name = FullNameField()
    email = forms.EmailField(label="Email address", max_length=254,
                             error_messages={"required": "Enter the email address.",
                                             "invalid": "Enter a valid email address."})
    password1 = forms.CharField(label="Password", strip=False, required=False, widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm password", strip=False, required=False, widget=forms.PasswordInput)
    is_active = forms.BooleanField(label="Account active", required=False, initial=True)

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        if instance is not None and "initial" not in kwargs:
            kwargs["initial"] = {"name": instance.get_full_name(), "email": instance.email,
                                 "is_active": instance.is_active}
        super().__init__(*args, **kwargs)
        self.creating = instance is None
        self.fields["password1"].required = self.creating
        self.fields["password1"].error_messages["required"] = "Set a password for the new account."

    def clean_email(self):
        email = normalise_email(self.cleaned_data["email"])
        others = get_user_model().objects.filter(username__iexact=email)
        if self.instance is not None:
            others = others.exclude(pk=self.instance.pk)
        if others.exists():
            raise forms.ValidationError("An account with this email address already exists.")
        return email

    def clean(self):
        cleaned = super().clean()
        password1, password2 = cleaned.get("password1"), cleaned.get("password2")
        if password1:
            if password1 != password2:
                self.add_error("password2", "The two passwords don't match.")
            else:
                first, last = split_name(cleaned.get("name") or "")
                probe = get_user_model()(username=cleaned.get("email") or "", email=cleaned.get("email") or "",
                                         first_name=first, last_name=last)
                try:
                    password_validation.validate_password(password1, probe)
                except forms.ValidationError as exc:
                    self.add_error("password1", exc)
        return cleaned

    def save(self):
        User = get_user_model()
        user = self.instance or User()
        user.username = user.email = self.cleaned_data["email"]
        user.first_name, user.last_name = split_name(self.cleaned_data["name"])
        user.is_active = self.cleaned_data["is_active"] if not self.creating else True
        user.is_staff = user.is_superuser = False
        if self.cleaned_data.get("password1"):
            user.set_password(self.cleaned_data["password1"])  # also signs the account out elsewhere
        user.save()
        return user


class ProfileForm(forms.Form):
    """What users may change about themselves: their name. The email is set by an administrator."""

    name = FullNameField()


class ChangePasswordForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["old_password"].label = "Current password"
        self.fields["new_password1"].label = "New password"
        self.fields["new_password2"].label = "Confirm new password"
        self.fields["old_password"].widget.attrs.pop("autofocus", None)

    error_messages = {
        **PasswordChangeForm.error_messages,
        "password_incorrect": "Your current password is incorrect.",
        "password_mismatch": "The two new passwords don't match.",
    }
