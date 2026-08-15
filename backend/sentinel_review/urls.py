"""
Root URL configuration for sentinel_review.
"""

from django.contrib import admin
from django.urls import include, path

from .api.metrics import metrics_view

urlpatterns = [
    path("admin/", admin.site.urls),
    path("webhooks/", include("sentinel_review.webhooks.urls")),
    path("api/", include("sentinel_review.api.urls")),
    path("", include("sentinel_review.dashboard.urls")),
    path("", include("sentinel_review.api.health_urls")),
    path("metrics/", metrics_view, name="prometheus-metrics"),
]

# drf-spectacular OpenAPI schema (if installed)
try:
    from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
        path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    ]
except ImportError:
    pass
