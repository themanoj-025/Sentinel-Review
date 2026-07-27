from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard_home, name="dashboard-home"),
    path("repos/", views.repo_list, name="repo-list"),
    path("repos/<int:repo_id>/", views.repo_detail, name="repo-detail"),
    path("reviews/<int:review_id>/", views.review_detail, name="review-detail"),
    path("stats/", views.stats_overview, name="stats-overview"),
]
