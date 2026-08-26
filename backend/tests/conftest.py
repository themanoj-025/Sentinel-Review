"""
Shared pytest fixtures for Sentinel Review tests.

NOTE: All Django model imports happen inside fixture functions
(to avoid AppRegistryNotReady during test collection).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test.utils import override_settings
from sentinel_review.workers.schemas import Finding, ReviewOutput

# Sample Data

SAMPLE_DIFF = """diff --git a/app.py b/app.py
index abc123..def456 100644
--- a/app.py
+++ b/app.py
@@ -1,5 +1,7 @@
 def get_user(email):
-    query = "SELECT * FROM users WHERE email = %s" % email
+    query = f"SELECT * FROM users WHERE email = '{email}'"
     cursor.execute(query)
     return cursor.fetchone()

+def delete_user(user_id):
+    db.execute("DELETE FROM users WHERE id = " + str(user_id))
"""

SAMPLE_DIFF_SAFE = """diff --git a/utils.py b/utils.py
index 111aaa..222bbb 100644
--- a/utils.py
+++ b/utils.py
@@ -1,4 +1,4 @@
-def format_name(first, last):
-    return first + ' ' + last
+def format_name(first_name, last_name):
+    return first_name + ' ' + last_name
"""

SAMPLE_LLM_RESPONSE = json.dumps(
    {
        "findings": [
            {
                "file_path": "app.py",
                "line_number": 2,
                "category": "security",
                "severity": "blocking",
                "comment": "SQL injection vulnerability — user input is interpolated directly into query string.",
                "suggested_fix": "Use parameterized queries: `cursor.execute('SELECT * FROM users WHERE email = %s', (email,))`",
            },
            {
                "file_path": "app.py",
                "line_number": 8,
                "category": "security",
                "severity": "blocking",
                "comment": "SQL injection via string concatenation — never trust str(user_id).",
                "suggested_fix": "Use parameterized queries with placeholders.",
            },
        ]
    }
)

SAMPLE_DIFF_WITH_CONTRIBUTING = """diff --git a/app.py b/app.py
index 111aaa..222bbb 100644
--- a/app.py
+++ b/app.py
@@ -1,5 +1,6 @@
 import os
+PASSWORD = os.getenv("SECRET")
"""


# Fixtures


@pytest.fixture
def sample_diff() -> str:
    return SAMPLE_DIFF


@pytest.fixture
def sample_diff_safe() -> str:
    return SAMPLE_DIFF_SAFE


@pytest.fixture
def sample_llm_response() -> str:
    return SAMPLE_LLM_RESPONSE


@pytest.fixture
def sample_finding() -> Finding:
    return Finding(
        file_path="app.py",
        line_number=2,
        category="security",
        severity="blocking",
        comment="SQL injection vulnerability.",
        suggested_fix="Use parameterized queries.",
    )


@pytest.fixture
def sample_review_output(sample_finding: Finding) -> ReviewOutput:
    return ReviewOutput(findings=[sample_finding])


@pytest.fixture
def webhook_payload() -> dict[str, Any]:
    return {
        "action": "opened",
        "pull_request": {
            "number": 42,
            "title": "Fix login bug",
            "user": {"login": "testuser"},
            "head": {"sha": "abc123"},
            "base": {"sha": "def456"},
        },
        "repository": {
            "id": 789,
            "full_name": "testowner/testrepo",
            "private": False,
            "owner": {"login": "testowner"},
        },
        "installation": {"id": 1001},
    }


# Database Fixtures


def _get_installation_model() -> None:
    from sentinel_review.models.installation import Installation

    return Installation


def _get_repo_model() -> None:
    from sentinel_review.models.repo import Repo

    return Repo


def _get_pull_request_model() -> None:
    from sentinel_review.models.pull_request import PullRequest

    return PullRequest


def _get_review_model() -> None:
    from sentinel_review.models.review import Review

    return Review


def _get_comment_model() -> None:
    from sentinel_review.models.comment import Comment

    return Comment


def _get_feedback_model() -> None:
    from sentinel_review.models.feedback import Feedback

    return Feedback


@pytest.fixture
@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
)
def db_installation(db: Any) -> Any:
    """Create a minimal Installation record."""
    installation_model = _get_installation_model()
    return installation_model.objects.create(
        github_installation_id=1001,
        account_login="testowner",
    )


@pytest.fixture
def db_repo(db_installation: Any, db: Any) -> Any:
    """Create a Repo linked to the installation."""
    repo_model = _get_repo_model()
    return repo_model.objects.create(
        installation=db_installation,
        github_repo_id=789,
        full_name="testowner/testrepo",
        config={
            "enabled_categories": ["bug", "style", "security", "suggestion"],
            "max_comments": 25,
            "private_repo_opt_in": False,
        },
    )


@pytest.fixture
def db_pull_request(db_repo: Any, db: Any) -> Any:
    """Create a PullRequest."""
    pr_model = _get_pull_request_model()
    return pr_model.objects.create(
        repo=db_repo,
        github_pr_number=42,
        title="Fix login bug",
        author_login="testuser",
        head_sha="abc123",
        base_sha="def456",
        status=pr_model.Status.OPEN,
    )


@pytest.fixture
def db_review(db_pull_request: Any, db: Any) -> Any:
    """Create a Review."""
    review_model = _get_review_model()
    return review_model.objects.create(
        pull_request=db_pull_request,
        triggered_by=review_model.Trigger.OPENED,
        status=review_model.Status.COMPLETED,
        latency_ms=1500,
        token_cost=500,
        findings_count=2,
    )


@pytest.fixture
def db_comments(db_review: Any, db: Any) -> list[Any]:
    """Create sample comments for a review."""
    comment_model = _get_comment_model()
    c1 = comment_model.objects.create(
        review=db_review,
        github_comment_id=2001,
        file_path="app.py",
        line_number=2,
        category=comment_model.Category.SECURITY,
        severity=comment_model.Severity.BLOCKING,
        content="SQL injection vulnerability.",
        suggested_fix="Use parameterized queries.",
    )
    c2 = comment_model.objects.create(
        review=db_review,
        github_comment_id=2002,
        file_path="app.py",
        line_number=8,
        category=comment_model.Category.SECURITY,
        severity=comment_model.Severity.BLOCKING,
        content="SQL injection via string concat.",
    )
    return [c1, c2]


@pytest.fixture
def db_feedback(db_comments: list[Any], db: Any) -> list[Any]:
    """Create sample feedback entries."""
    feedback_model = _get_feedback_model()
    f1 = feedback_model.objects.create(
        comment=db_comments[0],
        reaction=feedback_model.Reaction.THUMBS_UP,
        reactor_login="reviewer1",
    )
    f2 = feedback_model.objects.create(
        comment=db_comments[0],
        reaction=feedback_model.Reaction.THUMBS_DOWN,
        reactor_login="reviewer2",
    )
    f3 = feedback_model.objects.create(
        comment=db_comments[1],
        reaction=feedback_model.Reaction.THUMBS_UP,
        reactor_login="reviewer1",
    )
    return [f1, f2, f3]


@pytest.fixture
def seeded_db(db_repo: Any, db_pull_request: Any, db_review: Any, db_comments: list[Any]) -> tuple[Any, Any, Any]:
    """Convenience fixture: returns (repo, pr, review) for view tests.
    Also creates comments and feedback via db_comments.
    """
    return (db_repo, db_pull_request, db_review)
