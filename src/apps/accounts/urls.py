from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("sign-in", views.sign_in, name="sign-in"),
    path("sign-out", views.sign_out, name="sign-out"),
    path("account", views.account, name="account"),
    path("manage/users", views.users, name="users"),
    path("manage/users/new", views.user_add, name="user-add"),
    path("manage/users/<int:pk>", views.user_detail, name="user-detail"),
    path("manage/users/<int:pk>/edit", views.user_edit, name="user-edit"),
    path("manage/users/<int:pk>/delete", views.user_delete, name="user-delete"),
]
