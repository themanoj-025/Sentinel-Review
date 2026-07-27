"""
Root URL configuration for sentinel_review.
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("webhooks/", include("sentinel_review.webhooks.urls")),
    path("api/", include("sentinel_review.api.urls")),
    path("", include("sentinel_review.dashboard.urls")),
]
