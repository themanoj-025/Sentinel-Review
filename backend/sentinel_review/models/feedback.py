from django.db import models

from .comment import Comment


class Feedback(models.Model):
    """User reaction (👍/👎) on a review comment."""

    class Reaction(models.TextChoices):
        THUMBS_UP = "thumbs_up", "👍 Thumbs Up"
        THUMBS_DOWN = "thumbs_down", "👎 Thumbs Down"

    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name="feedback")
    reaction = models.CharField(max_length=20, choices=Reaction.choices)
    reactor_login = models.CharField(max_length=255, blank=True, default="")
    github_reaction_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "feedback"
        verbose_name = "Feedback"
        verbose_name_plural = "Feedback"
        indexes = [
            models.Index(fields=["comment"]),
            models.Index(fields=["reaction"]),
            models.Index(fields=["comment", "reaction"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["comment", "reactor_login", "reaction"],
                name="uq_feedback_comment_reactor_reaction",
            )
        ]

    def __str__(self):
        return f"{self.reaction} on Comment #{self.comment_id} by {self.reactor_login}"
