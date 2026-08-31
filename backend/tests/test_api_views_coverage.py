"""Additional API view tests using direct URL paths for coverage."""

from __future__ import annotations

from django.contrib.auth.models import User
from django.test import Client

pytestmark = pytest.mark.slow
class TestViewsReturnOk:
    def test_installation_list(self, seeded_db) -> None:
        assert Client().get("/api/v1/installations/").status_code == 200

    def test_repo_list(self, seeded_db) -> None:
        assert Client().get("/api/v1/repos/").status_code == 200

    def test_pull_request_list(self, seeded_db) -> None:
        assert Client().get("/api/v1/pull-requests/").status_code == 200

    def test_review_list(self, seeded_db) -> None:
        assert Client().get("/api/v1/reviews/").status_code == 200

    def test_comment_list(self, seeded_db) -> None:
        assert Client().get("/api/v1/comments/").status_code == 200


class TestReviewFilters:
    def test_filter_by_status(self, seeded_db) -> None:
        assert Client().get("/api/v1/reviews/?status=completed").status_code == 200

    def test_filter_by_status_no_match(self, seeded_db) -> None:
        assert Client().get("/api/v1/reviews/?status=nonexistent").status_code == 200


class TestCommentFilters:
    def test_filter_by_category(self, seeded_db) -> None:
        assert Client().get("/api/v1/comments/?category=security").status_code == 200

    def test_filter_by_severity(self, seeded_db) -> None:
        assert Client().get("/api/v1/comments/?severity=blocking").status_code == 200


class TestFeedbackAuth:
    def test_unauthenticated_post_rejected(self, seeded_db) -> None:
        assert Client().post(
            "/api/v1/feedback/",
            {"comment": 1, "reaction": "thumbs_up"},
            content_type="application/json",
        ).status_code in (401, 403)

    def test_authenticated_post_accepted(self, seeded_db, db_comments) -> None:
        User.objects.create_user(username="apitester", password="pass1234")
        client = Client()
        client.login(username="apitester", password="pass1234")
        comment_id = db_comments[0].id
        resp = client.post(
            "/api/v1/feedback/",
            {"comment": comment_id, "reaction": "thumbs_up"},
            content_type="application/json",
        )
        assert resp.status_code in (201, 200)


class TestStats:
    def test_unauthenticated_read_allowed(self, seeded_db) -> None:
        assert Client().get("/api/v1/stats/").status_code == 200

    def test_filter_by_repo(self, seeded_db) -> None:
        assert Client().get("/api/v1/stats/?repo=testowner/testrepo").status_code == 200
