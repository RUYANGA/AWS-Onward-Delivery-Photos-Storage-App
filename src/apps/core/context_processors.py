from django.conf import settings


def lab(request):
    initials = "".join(word[0] for word in settings.STUDENT_NAME.split()[:2]).upper()
    return {
        "student_name": settings.STUDENT_NAME,
        "student_initials": initials,
        "lab_name": settings.LAB_NAME,
        "app_env": settings.APP_ENV,
        "app_version": settings.APP_VERSION,
        "app_version_short": settings.APP_VERSION[:7],
    }
