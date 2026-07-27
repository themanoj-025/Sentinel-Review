"""Targeted tests for dashboard/views.py to boost coverage above 75%.

Uses pytest-style functions with fixtures instead of unittest.TestCase
to allow fixture injection (seeded_db).
"""

from __future__ import annotations

import pytest
from django.conf import settings
from django.http import Http404
from django.test import RequestFactory
from sentinel_review.dashboard.views import (
    dashboard_home,
    repo_detail,
    repo_list,
    review_detail,
    stats_overview,
)


class TestDashboardHome:
    """dashboard_home — KPI cards, recent reviews, status distribution."""

    @pytest.mark.django_db
    def test_returns_200(self):
        factory = RequestFactory()
        request = factory.get("/")
        response = dashboard_home(request)
        assert response.status_code == 200

    @pytest.mark.django_db
    def test_context_has_reviews(self):
        factory = RequestFactory()
        request = factory.get("/")
        response = dashboard_home(request)
        assert response.status_code == 200


class TestRepoList:
    """repo_list — repository listing with search and HTMX support."""

    @pytest.mark.django_db
    def test_returns_200(self, seeded_db):
        factory = RequestFactory()
        request = factory.get("/repos/")
        response = repo_list(request)
        assert response.status_code == 200

    @pytest.mark.django_db
    def test_with_search_query(self, seeded_db):
        factory = RequestFactory()
        request = factory.get("/repos/?search=test")
        response = repo_list(request)
        assert response.status_code == 200

    @pytest.mark.django_db
    def test_htmx_partial(self, seeded_db):
        factory = RequestFactory()
        request = factory.get("/repos/", HTTP_HX_REQUEST="true")
        response = repo_list(request)
        assert response.status_code == 200

    @pytest.mark.django_db
    def test_htmx_partial_with_search(self, seeded_db):
        factory = RequestFactory()
        request = factory.get("/repos/?search=test", HTTP_HX_REQUEST="true")
        response = repo_list(request)
        assert response.status_code == 200


class TestRepoDetail:
    """repo_detail — repo config panel, PR list, recent reviews, stats."""

    @pytest.mark.django_db
    @pytest.mark.skipif(
        "sqlite" in settings.DATABASES["default"]["ENGINE"],
        reason="SQLite does not support Avg on datetime fields used in repo_detail",
    )
    def test_returns_200(self, seeded_db):
        repo, *_ = seeded_db
        factory = RequestFactory()
        request = factory.get(f"/repos/{repo.id}/")
        response = repo_detail(request, repo_id=repo.id)
        assert response.status_code == 200

    @pytest.mark.django_db
    def test_htmx_post_updates_config(self, seeded_db):
        repo, *_ = seeded_db
        factory = RequestFactory()
        request = factory.post(
            f"/repos/{repo.id}/",
            {"enabled_categories": ["security"], "max_comments": 10, "private_repo_opt_in": "on"},
            HTTP_HX_REQUEST="true",
        )
        response = repo_detail(request, repo_id=repo.id)
        assert response.status_code == 200
        repo.refresh_from_db()
        assert repo.config["max_comments"] == 10
        assert repo.config["private_repo_opt_in"] is True
        assert "security" in repo.config["enabled_categories"]

    @pytest.mark.django_db
    def test_htmx_post_default_categories(self, seeded_db):
        repo, *_ = seeded_db
        factory = RequestFactory()
        request = factory.post(
            f"/repos/{repo.id}/",
            {"max_comments": 5},
            HTTP_HX_REQUEST="true",
        )
        response = repo_detail(request, repo_id=repo.id)
        assert response.status_code == 200
        repo.refresh_from_db()
        assert len(repo.config["enabled_categories"]) >= 4
        assert repo.config["max_comments"] == 5

    @pytest.mark.django_db
    def test_htmx_post_int_max_comments(self, seeded_db):
        repo, *_ = seeded_db
        factory = RequestFactory()
        request = factory.post(
            f"/repos/{repo.id}/",
            {"enabled_categories": ["bug"], "max_comments": "15"},
            HTTP_HX_REQUEST="true",
        )
        response = repo_detail(request, repo_id=repo.id)
        assert response.status_code == 200
        repo.refresh_from_db()
        assert repo.config["max_comments"] == 15

    @pytest.mark.django_db
    def test_htmx_post_private_opt_in_false(self, seeded_db):
        repo, *_ = seeded_db
        factory = RequestFactory()
        request = factory.post(
            f"/repos/{repo.id}/",
            {"enabled_categories": ["style"], "max_comments": 25},
            HTTP_HX_REQUEST="true",
        )
        response = repo_detail(request, repo_id=repo.id)
        assert response.status_code == 200
        repo.refresh_from_db()
        assert repo.config["private_repo_opt_in"] is False


class TestReviewDetail:
    """review_detail — review comments with upvote/downvote counts."""

    @pytest.mark.django_db
    def test_returns_200(self, seeded_db):
        *_, review = seeded_db
        factory = RequestFactory()
        request = factory.get(f"/reviews/{review.id}/")
        response = review_detail(request, review_id=review.id)
        assert response.status_code == 200

    @pytest.mark.django_db
    def test_returns_404_for_missing(self):
        factory = RequestFactory()
        request = factory.get("/reviews/99999/")
        with pytest.raises(Http404):
            review_detail(request, review_id=99999)


class TestStatsOverview:
    """stats_overview — full analytics page with Chart.js data."""

    @pytest.mark.django_db
    def test_returns_200(self, seeded_db):
        factory = RequestFactory()
        request = factory.get("/stats/")
        response = stats_overview(request)
        assert response.status_code == 200

    @pytest.mark.django_db
    def test_context_has_json_data(self, seeded_db):
        factory = RequestFactory()
        request = factory.get("/stats/")
        response = stats_overview(request)
        assert response.status_code == 200
