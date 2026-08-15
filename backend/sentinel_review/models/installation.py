from django.db import models


class Installation(models.Model):
    """A GitHub App installation on a user/organization account."""

    github_installation_id = models.BigIntegerField(unique=True)
    account_login = models.CharField(max_length=255)
    account_type = models.CharField(
        max_length=20,
        choices=[("User", "User"), ("Organization", "Organization")],
        default="User",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "installation"
        verbose_name = "Installation"
        verbose_name_plural = "Installations"
        indexes = [
            models.Index(fields=["github_installation_id"]),
        ]

    def __str__(self):
        return f"Installation {self.github_installation_id} ({self.account_login})"
