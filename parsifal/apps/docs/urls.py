from django.urls import path

from parsifal.apps.docs import views

app_name = "docs"

urlpatterns = [
    path("", views.page, name="index"),
    path("<slug:slug>/", views.page, name="page"),
]
