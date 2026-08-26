from django.db import models

from .repo import Repo


class PullRequest(models.Model):
    """A pull request that has been or should be reviewed."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"
        MERGED = "merged", "Merged"

    repo = models.ForeignKey(Repo, on_delete=models.CASCADE, related_name="pull_requests")
    github_pr_number = models.IntegerField()
    title = models.CharField(max_length=500, blank=True, default="")
    author_login = models.CharField(max_length=255, blank=True, default="")
    head_sha = models.CharField(max_length=40, blank=True, default="")
    base_sha = models.CharField(max_length=40, blank=True, default="")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "pull_request"
        verbose_name = "Pull Request"
        verbose_name_plural = "Pull Requests"
        constraints = [
            models.UniqueConstraint(
                fields=["repo", "github_pr_number"],
                name="uq_pull_request_repo_number",
            )
        ]
        indexes = [
            models.Index(fields=["repo"]),
            models.Index(fields=["repo", "status"]),
        ]

    def __str__(self) -> str:
        return f"#{self.github_pr_number} on {self.repo.full_name}"
