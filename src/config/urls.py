from django.urls import include, path

urlpatterns = [
    path("", include("apps.core.urls")),
    path("", include("apps.photos.urls")),
]

handler404 = "apps.core.views.page_not_found"
handler500 = "apps.core.views.server_error"
