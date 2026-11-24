from django.conf import settings


def lab(request):
    initials = "".join(word[0] for word in settings.STUDENT_NAME.split()[:2]).upper()
    user = getattr(request, "user", None)
    account_name = ""
    if user is not None and user.is_authenticated:
        account_name = user.get_full_name() or user.email or user.get_username()
    return {
        "account_name": account_name,
        "account_initials": "".join(word[0] for word in account_name.split()[:2]).upper(),
        "student_name": settings.STUDENT_NAME,
        "student_initials": initials,
        "lab_name": settings.LAB_NAME,
        "app_env": settings.APP_ENV,
        "app_version": settings.APP_VERSION,
        "app_version_short": settings.APP_VERSION[:7],
    }
