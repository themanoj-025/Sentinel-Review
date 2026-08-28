from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from sentinel_review.models.comment import Comment
from sentinel_review.models.feedback import Feedback
from sentinel_review.models.installation import Installation
from sentinel_review.models.pull_request import PullRequest
from sentinel_review.models.repo import Repo
from sentinel_review.models.review import Review
from sentinel_review.services.stats_service import StatsService

from .serializers import (
    CommentSerializer,
    FeedbackSerializer,
    InstallationSerializer,
    PullRequestSerializer,
    RepoConfigSerializer,
    RepoSerializer,
    ReviewSerializer,
)


class InstallationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Installation.objects.all()
    serializer_class = InstallationSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["account_login"]
    ordering_fields = ["account_login", "created_at"]
    ordering = ["-created_at"]


class RepoViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Repo.objects.select_related("installation").all()
    serializer_class = RepoSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["full_name"]
    ordering_fields = ["full_name", "created_at"]
    ordering = ["full_name"]

    @action(detail=True, methods=["patch"])
    def config(self, request, pk=None) -> Response:
        repo = self.get_object()
        serializer = RepoConfigSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        cfg = dict(repo.config or {})
        if "enabled_categories" in serializer.validated_data:
            cfg["enabled_categories"] = serializer.validated_data["enabled_categories"]
        if "max_comments" in serializer.validated_data:
            cfg["max_comments"] = serializer.validated_data["max_comments"]
        if "private_repo_opt_in" in serializer.validated_data:
            cfg["private_repo_opt_in"] = serializer.validated_data["private_repo_opt_in"]

        repo.config = cfg
        repo.save(update_fields=["config"])
        return Response(RepoSerializer(repo).data)


class PullRequestViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PullRequest.objects.select_related("repo__installation").all()
    serializer_class = PullRequestSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["title", "author_login"]
    ordering_fields = ["created_at", "github_pr_number", "status"]
    ordering = ["-created_at"]

    def get_queryset(self) -> Any:
        qs = super().get_queryset()
        repo_id = self.request.query_params.get("repo_id")
        if repo_id:
            qs = qs.filter(repo_id=repo_id)
        return qs


class ReviewViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = (
        Review.objects.select_related("pull_request__repo__installation")
        .prefetch_related("comments__feedback")
        .all()
    )
    serializer_class = ReviewSerializer
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["created_at", "status", "findings_count", "latency_ms"]
    ordering = ["-created_at"]

    def get_queryset(self) -> Any:
        qs = super().get_queryset()
        pr_id = self.request.query_params.get("pull_request_id")
        if pr_id:
            qs = qs.filter(pull_request_id=pr_id)
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs


class CommentViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Comment.objects.all()
    serializer_class = CommentSerializer
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["created_at", "severity", "category"]
    ordering = ["-created_at"]

    def get_queryset(self) -> Any:
        qs = super().get_queryset()
        review_id = self.request.query_params.get("review_id")
        if review_id:
            qs = qs.filter(review_id=review_id)
        category = self.request.query_params.get("category")
        if category:
            qs = qs.filter(category=category)
        severity = self.request.query_params.get("severity")
        if severity:
            qs = qs.filter(severity=severity)
        return qs


class FeedbackViewSet(viewsets.ModelViewSet):
    queryset = Feedback.objects.all()
    serializer_class = FeedbackSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.OrderingFilter]
    ordering = ["-created_at"]

    def perform_create(self, serializer) -> None:
        reactor_login = self.request.data.get("reactor_login", "")
        if not reactor_login and self.request.user.is_authenticated:
            reactor_login = self.request.user.username
        serializer.save(reactor_login=reactor_login)


class StatsViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticatedOrReadOnly]

    def list(self, request) -> Response:
        repo_full_name = request.query_params.get("repo", None)
        data = StatsService.get_usefulness_rate(repo_full_name)
        return Response(data)
