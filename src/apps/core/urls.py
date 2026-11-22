from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("healthz", views.healthz, name="healthz"),
    path("readyz", views.readyz, name="readyz"),
    path("about", views.about, name="about"),
]
