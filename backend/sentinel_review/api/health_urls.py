from django.urls import path

from .health import liveness, readiness

urlpatterns = [
    path("health/", liveness, name="health-liveness"),
    path("health/ready/", readiness, name="health-readiness"),
]
