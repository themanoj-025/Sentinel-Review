"""
Dashboard views — server-rendered pages with HTMX for dynamic updates.
"""

import json
import logging
from datetime import timedelta

from django.db import models
from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncDate
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.cache import cache_control

from sentinel_review.models.comment import Comment
from sentinel_review.models.installation import Installation
from sentinel_review.models.pull_request import PullRequest
from sentinel_review.models.repo import Repo
from sentinel_review.models.review import Review
from sentinel_review.services.stats_service import StatsService

logger = logging.getLogger(__name__)


@cache_control(private=True, max_age=30)
def dashboard_home(request: HttpRequest) -> HttpResponse:
    """Dashboard home page with overview stats."""
    total_installations = Installation.objects.count()
    total_repos = Repo.objects.count()
    total_reviews = Review.objects.count()
    total_comments = Comment.objects.count()
    total_prs = PullRequest.objects.count()

    # Usefulness rate
    usefulness = StatsService.get_usefulness_rate()

    # Recent reviews
    recent_reviews = Review.objects.select_related("pull_request__repo").order_by("-created_at")[
        :10
    ]

    # Reviews by status
    status_counts = Review.objects.values("status").annotate(count=Count("id")).order_by("status")

    # Reviews over time (last 7 days)
    seven_days_ago = timezone.now() - timedelta(days=7)
    reviews_by_day = (
        Review.objects.filter(created_at__gte=seven_days_ago)
        .annotate(date=TruncDate("created_at"))
        .values("date")
        .annotate(count=Count("id"))
        .order_by("date")
    )

    context = {
        "total_installations": total_installations,
        "total_repos": total_repos,
        "total_reviews": total_reviews,
        "total_comments": total_comments,
        "total_prs": total_prs,
        "usefulness": usefulness,
        "recent_reviews": recent_reviews,
        "status_counts": status_counts,
        "reviews_by_day": list(reviews_by_day),
    }
    return render(request, "dashboard/home.html", context)


@cache_control(private=True, max_age=30)
def repo_list(request: HttpRequest) -> HttpResponse:
    """List all configured repositories with pagination."""
    page_size = 20
    page = int(request.GET.get("page", 1))
    offset = (page - 1) * page_size

    repos = (
        Repo.objects.select_related("installation")
        .annotate(
            review_count=Count("pull_requests__reviews", distinct=True),
            comment_count=Count("pull_requests__reviews__comments", distinct=True),
        )
        .order_by("full_name")
    )

    # HTMX partial for search
    search = request.GET.get("search", "")
    if search:
        repos = repos.filter(full_name__icontains=search)

    total = repos.count()
    repos_page = repos[offset : offset + page_size]
    has_next = (offset + page_size) < total

    if request.headers.get("HX-Request"):
        return render(
            request,
            "dashboard/partials/repo_table.html",
            {
                "repos": repos_page,
                "page": page,
                "has_next": has_next,
                "search": search,
            },
        )

    return render(
        request,
        "dashboard/repo_list.html",
        {
            "repos": repos_page,
            "page": page,
            "has_next": has_next,
            "total": total,
            "search": search,
        },
    )


@cache_control(private=True, max_age=15)
def repo_detail(request: HttpRequest, repo_id: int) -> HttpResponse:
    """Show repository details, settings, and review history."""
    repo = get_object_or_404(
        Repo.objects.select_related("installation"),
        id=repo_id,
    )

    # Update config via HTMX POST
    if request.method == "POST" and request.headers.get("HX-Request"):
        enabled_categories = request.POST.getlist("enabled_categories", [])
        max_comments = request.POST.get("max_comments", 25)
        private_opt_in = request.POST.get("private_repo_opt_in") == "on"

        config = dict(repo.config or {})
        config["enabled_categories"] = enabled_categories or [
            "bug",
            "style",
            "security",
            "suggestion",
        ]
        config["max_comments"] = int(max_comments)
        config["private_repo_opt_in"] = private_opt_in
        repo.config = config
        repo.save()

        return render(request, "dashboard/partials/repo_config.html", {"repo": repo})

    pull_requests = (
        PullRequest.objects.filter(repo=repo)
        .annotate(
            review_count=Count("reviews"),
            last_reviewed_at=models.Max("reviews__created_at"),
        )
        .order_by("-created_at")[:20]
    )

    recent_reviews = (
        Review.objects.filter(pull_request__repo=repo)
        .select_related("pull_request")
        .order_by("-created_at")[:10]
    )

    # Stats for this repo
    stats = StatsService.get_usefulness_rate(repo.full_name)

    context = {
        "repo": repo,
        "pull_requests": pull_requests,
        "recent_reviews": recent_reviews,
        "stats": stats,
        "all_categories": Comment.Category.choices,
    }
    return render(request, "dashboard/repo_detail.html", context)


@cache_control(private=True, max_age=30)
def review_detail(request: HttpRequest, review_id: int) -> HttpResponse:
    """Show details of a single review run."""
    review = get_object_or_404(
        Review.objects.select_related("pull_request__repo__installation"),
        id=review_id,
    )

    comments = (
        Comment.objects.filter(review=review)
        .annotate(
            upvotes=Count("feedback", filter=Q(feedback__reaction="thumbs_up")),
            downvotes=Count("feedback", filter=Q(feedback__reaction="thumbs_down")),
        )
        .order_by("-severity", "file_path", "line_number")
    )

    context = {
        "review": review,
        "comments": comments,
    }
    return render(request, "dashboard/review_detail.html", context)


@cache_control(no_cache=True, no_store=True, must_revalidate=True)
def stats_overview(request: HttpRequest) -> HttpResponse:
    """Full stats and metrics page with Chart.js visualizations."""
    usefulness = StatsService.get_usefulness_rate()

    # Per-repo stats
    repo_stats = Repo.objects.annotate(
        review_count=Count("pull_requests__reviews", distinct=True),
        comment_count=Count("pull_requests__reviews__comments", distinct=True),
    ).order_by("-comment_count")[:20]

    # Comment volume by category
    category_volume = (
        Comment.objects.values("category").annotate(count=Count("id")).order_by("-count")
    )

    # Average latency
    avg_latency = Review.objects.filter(status=Review.Status.COMPLETED).aggregate(
        avg=Avg("latency_ms"),
        total_tokens=Avg("token_cost"),
    )

    # Reviews over time (last 7 days) for trend chart
    seven_days_ago = timezone.now() - timedelta(days=7)
    reviews_by_day = (
        Review.objects.filter(created_at__gte=seven_days_ago)
        .annotate(date=TruncDate("created_at"))
        .values("date")
        .annotate(count=Count("id"))
        .order_by("date")
    )

    # Serialize to JSON for Chart.js (Django templates don't auto-serialize)
    reviews_by_day_list = [
        {
            "date": r["date"].isoformat() if hasattr(r["date"], "isoformat") else str(r["date"]),
            "count": r["count"],
        }
        for r in reviews_by_day
    ]

    context = {
        "usefulness": usefulness,
        "usefulness_json": json.dumps(usefulness.get("categories", [])),
        "repo_stats": repo_stats,
        "category_volume": category_volume,
        "category_volume_json": json.dumps(list(category_volume)),
        "reviews_by_day": list(reviews_by_day),
        "reviews_by_day_json": json.dumps(reviews_by_day_list),
        "avg_latency_ms": avg_latency.get("avg"),
        "avg_tokens": avg_latency.get("total_tokens"),
    }
    return render(request, "dashboard/stats.html", context)
