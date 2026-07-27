from django.db import models

from .installation import Installation


class Repo(models.Model):
    """A GitHub repository configured for review."""

    installation = models.ForeignKey(Installation, on_delete=models.CASCADE, related_name="repos")
    github_repo_id = models.BigIntegerField()
    full_name = models.CharField(max_length=255)
    is_private = models.BooleanField(default=False)
    config = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Repo-specific configuration. "
            "Keys: enabled_categories (list), private_repo_opt_in (bool), "
            "max_comments (int), custom_instructions (str)"
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "repo"
        verbose_name = "Repository"
        verbose_name_plural = "Repositories"
        constraints = [
            models.UniqueConstraint(
                fields=["installation", "github_repo_id"],
                name="uq_repo_installation_github_id",
            )
        ]
        indexes = [
            models.Index(fields=["installation"]),
            models.Index(fields=["full_name"]),
        ]

    def __str__(self):
        return self.full_name

    @property
    def enabled_categories(self):
        return self.config.get("enabled_categories", ["bug", "style", "security", "suggestion"])

    @enabled_categories.setter
    def enabled_categories(self, value):
        cfg = dict(self.config or {})
        cfg["enabled_categories"] = value
        self.config = cfg

    @property
    def private_review_allowed(self):
        return self.config.get("private_repo_opt_in", False)

    @property
    def max_comments(self):
        return self.config.get("max_comments", 25)
