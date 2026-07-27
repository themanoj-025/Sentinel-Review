"""
Tests for the GitHub API client.

Uses respx to mock HTTP requests to api.github.com.
Covers:
- JWT generation
- Installation token exchange
- Diff fetching
- File content retrieval
- Repo context gathering (CONTRIBUTING.md, linter configs)
- Review/posting comments
- Reaction fetching
- Error handling
"""
from __future__ import annotations

import pytest
import respx
from sentinel_review.workers.github_client import GitHubClient, GitHubRepoContext

GITHUB_API = "https://api.github.com"


@pytest.fixture(autouse=True)
def _mock_jwt(monkeypatch):
    """Mock JWT generation to avoid needing a real RSA key."""
    monkeypatch.setattr("django.conf.settings.GITHUB_APP_ID", "123456")
    monkeypatch.setattr(
        "sentinel_review.workers.github_client.GitHubClient._generate_jwt",
        lambda self: "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.fake-jwt",
    )
    monkeypatch.setattr(
        "sentinel_review.workers.github_client.GitHubClient._get_private_key",
        lambda self: b"fake-key",
    )


class TestGitHubClientJWT:
    """Tests for JWT generation (mocked)."""

    def test_client_initializes(self):
        """Client should initialize without error."""
        client = GitHubClient()
        assert client is not None


class TestGitHubClientRequests:
    """Tests for GitHub API requests using respx mocks."""

    @respx.mock
    def test_get_diff_success(self):
        """fetch_diff should return the diff text."""
        diff_text = "diff --git a/file.py b/file.py\nindex abc..def\n--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-foo\n+bar"
        # Mock token exchange
        respx.post(f"{GITHUB_API}/app/installations/1001/access_tokens").respond(
            201, json={"token": "inst_token_abc", "expires_at": "2099-01-01T00:00:00Z"}
        )
        # Mock diff request
        respx.get(f"{GITHUB_API}/repos/testowner/testrepo/pulls/42").respond(
            200,
            text=diff_text,
            headers={"Content-Type": "text/plain"},
        )

        client = GitHubClient()
        result = client.get_diff(1001, "testowner/testrepo", 42)
        assert result == diff_text

    @respx.mock
    def test_get_diff_404(self):
        """A 404 should raise an exception."""
        respx.post(f"{GITHUB_API}/app/installations/1001/access_tokens").respond(
            201, json={"token": "inst_token_abc", "expires_at": "2099-01-01T00:00:00Z"}
        )
        respx.get(f"{GITHUB_API}/repos/testowner/testrepo/pulls/42").respond(404)

        client = GitHubClient()
        with pytest.raises(Exception):
            client.get_diff(1001, "testowner/testrepo", 42)

    @respx.mock
    def test_get_file_content_success(self):
        """get_file_content should decode base64 content."""
        import base64

        content = base64.b64encode(b"print('hello')").decode()
        respx.post(f"{GITHUB_API}/app/installations/1001/access_tokens").respond(
            201, json={"token": "tok", "expires_at": "2099-01-01T00:00:00Z"}
        )
        respx.get(
            f"{GITHUB_API}/repos/testowner/testrepo/contents/app.py?ref=main"
        ).respond(200, json={"encoding": "base64", "content": content})

        client = GitHubClient()
        result = client.get_file_content(1001, "testowner/testrepo", "app.py", "main")
        assert result == "print('hello')"

    @respx.mock
    def test_get_file_content_not_found(self):
        """A 404 should return None, not crash."""
        respx.post(f"{GITHUB_API}/app/installations/1001/access_tokens").respond(
            201, json={"token": "tok", "expires_at": "2099-01-01T00:00:00Z"}
        )
        respx.get(
            f"{GITHUB_API}/repos/testowner/testrepo/contents/missing.py?ref=main"
        ).respond(404)

        client = GitHubClient()
        result = client.get_file_content(1001, "testowner/testrepo", "missing.py", "main")
        assert result is None

    @respx.mock
    def test_get_repo_context(self):
        """get_repo_context should gather repo metadata and file contents."""
        respx.post(f"{GITHUB_API}/app/installations/1001/access_tokens").respond(
            201, json={"token": "tok", "expires_at": "2099-01-01T00:00:00Z"}
        )
        # Mock repo info
        respx.get(f"{GITHUB_API}/repos/testowner/testrepo").respond(
            200, json={"default_branch": "main", "full_name": "testowner/testrepo"}
        )
        # Mock CONTRIBUTING.md (not found)
        respx.get(
            f"{GITHUB_API}/repos/testowner/testrepo/contents/CONTRIBUTING.md?ref=main",
            headers={"Accept": "application/vnd.github.v3+json"},
        ).respond(404)
        # Mock .eslintrc (not found)
        respx.get(
            f"{GITHUB_API}/repos/testowner/testrepo/contents/.eslintrc?ref=main",
            headers={"Accept": "application/vnd.github.v3+json"},
        ).respond(404)

        client = GitHubClient()
        ctx = client.get_repo_context(1001, "testowner/testrepo")
        assert isinstance(ctx, GitHubRepoContext)
        assert ctx.default_branch == "main"
        assert ctx.has_contributing is False
        assert ctx.has_linter_config is False

    @respx.mock
    def test_post_review_success(self):
        """post_review should create a review with inline comments."""
        comments = [
            {"path": "app.py", "line": 2, "body": "**BLOCKING** (security)\n\nIssue here."}
        ]
        respx.post(f"{GITHUB_API}/app/installations/1001/access_tokens").respond(
            201, json={"token": "tok", "expires_at": "2099-01-01T00:00:00Z"}
        )
        mock_review = {
            "id": 5001,
            "body": "Review summary",
            "comments": [{"id": 3001}],
        }
        respx.post(
            f"{GITHUB_API}/repos/testowner/testrepo/pulls/42/reviews"
        ).respond(200, json=mock_review)

        client = GitHubClient()
        result = client.post_review(
            installation_id=1001,
            repo_full_name="testowner/testrepo",
            pr_number=42,
            comments=comments,
            review_body="Review summary",
        )
        assert result["id"] == 5001
        assert len(result["comments"]) == 1

    @respx.mock
    def test_post_review_with_empty_comments(self):
        """post_review should accept an empty list of comments."""
        respx.post(f"{GITHUB_API}/app/installations/1001/access_tokens").respond(
            201, json={"token": "tok", "expires_at": "2099-01-01T00:00:00Z"}
        )
        respx.post(
            f"{GITHUB_API}/repos/testowner/testrepo/pulls/42/reviews"
        ).respond(200, json={"id": 5002, "body": "No issues", "comments": []})

        client = GitHubClient()
        result = client.post_review(
            installation_id=1001,
            repo_full_name="testowner/testrepo",
            pr_number=42,
            comments=[],
            review_body="No issues found.",
        )
        assert result["id"] == 5002

    @respx.mock
    def test_get_comment_reactions(self):
        """get_comment_reactions should return reaction data."""
        reactions = [
            {"id": 1, "content": "+1", "user": {"login": "user1"}},
            {"id": 2, "content": "-1", "user": {"login": "user2"}},
        ]
        respx.post(f"{GITHUB_API}/app/installations/1001/access_tokens").respond(
            201, json={"token": "tok", "expires_at": "2099-01-01T00:00:00Z"}
        )
        respx.get(
            f"{GITHUB_API}/repos/testowner/testrepo/pulls/comments/3001/reactions"
        ).respond(200, json=reactions)

        client = GitHubClient()
        result = client.get_comment_reactions(1001, "testowner/testrepo", 3001)
        assert len(result) == 2
        assert result[0]["content"] == "+1"
        assert result[1]["content"] == "-1"

    @respx.mock
    def test_get_comment_reactions_error_returns_empty(self):
        """An error fetching reactions should return an empty list."""
        respx.post(f"{GITHUB_API}/app/installations/1001/access_tokens").respond(
            201, json={"token": "tok", "expires_at": "2099-01-01T00:00:00Z"}
        )
        respx.get(
            f"{GITHUB_API}/repos/testowner/testrepo/pulls/comments/9999/reactions"
        ).respond(404)

        client = GitHubClient()
        result = client.get_comment_reactions(1001, "testowner/testrepo", 9999)
        assert result == []

    @respx.mock
    def test_repo_context_with_contributing(self):
        """get_repo_context should detect CONTRIBUTING.md."""
        respx.post(f"{GITHUB_API}/app/installations/1001/access_tokens").respond(
            201, json={"token": "tok", "expires_at": "2099-01-01T00:00:00Z"}
        )
        respx.get(f"{GITHUB_API}/repos/testowner/testrepo").respond(
            200, json={"default_branch": "main"}
        )
        # CONTRIBUTING.md found
        import base64

        contrib_content = base64.b64encode(b"# Contributing\nPlease write tests.").decode()
        respx.get(
            f"{GITHUB_API}/repos/testowner/testrepo/contents/CONTRIBUTING.md?ref=main"
        ).respond(
            200, json={"encoding": "base64", "content": contrib_content}
        )

        client = GitHubClient()
        ctx = client.get_repo_context(1001, "testowner/testrepo")
        assert ctx.has_contributing is True
        assert ctx.contributing_content is not None
        assert "Contributing" in ctx.contributing_content
