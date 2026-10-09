from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r"installations", views.InstallationViewSet)
router.register(r"repos", views.RepoViewSet)
router.register(r"pull-requests", views.PullRequestViewSet)
router.register(r"reviews", views.ReviewViewSet)
router.register(r"comments", views.CommentViewSet)
router.register(r"feedback", views.FeedbackViewSet)
router.register(r"stats", views.StatsViewSet, basename="stats")

urlpatterns = [
    path("", include(router.urls)),
]
