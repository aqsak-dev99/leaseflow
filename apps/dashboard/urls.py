from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.home, name="home"),
    path("chat/", views.chat, name="chat"),
    path("chat/send/", views.chat_send, name="chat_send"),
    path("chat/new/", views.chat_new, name="chat_new"),
]
