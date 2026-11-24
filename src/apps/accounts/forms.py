from django import forms
from django.contrib.auth.forms import AuthenticationForm


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
