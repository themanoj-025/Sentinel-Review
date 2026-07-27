from django.db import models

from .review import Review


class Comment(models.Model):
    """A single finding/comment within a review."""

    class Category(models.TextChoices):
        BUG = "bug", "Bug"
        STYLE = "style", "Style"
        SECURITY = "security", "Security"
        SUGGESTION = "suggestion", "Suggestion"

    class Severity(models.TextChoices):
        BLOCKING = "blocking", "Blocking"
        WARNING = "warning", "Warning"
        NIT = "nit", "Nit"

    review = models.ForeignKey(
        Review, on_delete=models.CASCADE, related_name="comments"
    )
    github_comment_id = models.BigIntegerField(null=True, blank=True)
    file_path = models.CharField(max_length=500)
    line_number = models.IntegerField(null=True, blank=True)
    category = models.CharField(max_length=20, choices=Category.choices)
    severity = models.CharField(max_length=10, choices=Severity.choices)
    content = models.TextField()
    suggested_fix = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "comment"
        verbose_name = "Comment"
        verbose_name_plural = "Comments"
        indexes = [
            models.Index(fields=["review"]),
            models.Index(fields=["category"]),
            models.Index(fields=["severity"]),
            models.Index(fields=["file_path", "line_number"]),
        ]

    def __str__(self):
        return f"Comment #{self.id} ({self.severity}/{self.category}) on {self.file_path}:{self.line_number}"
