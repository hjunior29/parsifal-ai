from django.urls import path

from parsifal.apps.reviews.reporting import views

app_name = "reporting"

urlpatterns = [
    path("download_docx/", views.download_docx, name="download_docx"),
    path("manuscripts/<int:version_id>/file/", views.manuscript_file, name="manuscript_file"),
]
