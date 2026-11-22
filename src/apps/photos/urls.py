from django.urls import path

from . import views

app_name = "photos"

urlpatterns = [
    path("", views.gallery, name="gallery"),
    path("upload", views.upload, name="upload"),
    path("photos/<uuid:photo_id>", views.detail, name="detail"),
    path("photos/<uuid:photo_id>/delete", views.delete, name="delete"),
    path("photos/<uuid:photo_id>/restore", views.restore, name="restore"),
    path("deleted", views.deleted, name="deleted"),
    path("media/<path:subkey>", views.media, name="media"),
]
