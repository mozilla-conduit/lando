"""
URL configuration for lando project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/dev/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path

from lando.api import views as api_views
from lando.api.uplift_api import api as uplift_api
from lando.headless_api.api import (
    api as headless_api,
)
from lando.treestatus.views.api import treestatus_api
from lando.treestatus.views.ui import (
    TreestatusDashboardView,
    TreestatusLogUpdateView,
    TreestatusNewTreeView,
    TreestatusTreeLogsView,
    TreestatusUpdateChangeView,
)
from lando.try_api.api import (
    api as try_api,
)
from lando.try_api.api import (
    legacy_api as legacy_try_api,
)
from lando.ui import views as ui_views
from lando.utils.ninja_auth import api as auth_api

urlpatterns = [
    path("", include("lando.dockerflow.urls", "dockerflow")),
    path("admin/", admin.site.urls),
    path("oidc/", include("mozilla_django_oidc.urls")),
]

if settings.ENVIRONMENT.is_lower:
    urlpatterns += [
        path("auth/", auth_api.urls),
    ]


urlpatterns += [
    path("", ui_views.index.IndexView.as_view()),
    path(
        "D<int:revision_id>/",
        ui_views.revisions.RevisionView.as_view(),
        name="revisions-page",
    ),
    path(
        "pulls/<str:repo_name>/<int:number>/",
        ui_views.pull_requests.PullRequestView.as_view(),
        name="pull-request",
    ),
    path("manage_api_key/", api_views.manage_api_key, name="user-settings"),
    path("uplift/", ui_views.revisions.UpliftRequestView.as_view(), name="uplift-page"),
    path(
        "uplift/request/",
        ui_views.revisions.UpliftAssessmentBatchLinkView.as_view(),
        name="uplift-request-page",
    ),
    path(
        "uplift/<int:revision_id>/assessment/",
        ui_views.revisions.UpliftAssessmentCreateOrEditView.as_view(),
        name="uplift-assessment-page",
    ),
    path(
        "uplift/<int:revision_id>/assessment/link/",
        ui_views.revisions.UpliftAssessmentLinkView.as_view(),
        name="uplift-assessment-link-page",
    ),
    path(
        "uplift/jobs/<int:job_id>/",
        ui_views.jobs.UpliftJobView.as_view(),
        name="uplift-jobs-page",
    ),
    path(
        "D<int:revision_id>/landings/<int:job_id>/",
        ui_views.jobs.LandingJobView.as_view(),
        name="revision-jobs-page",
    ),
    # Allow to find a landing job by ID only. The page will redirect to the canonical
    # URL including the revision.
    path(
        "landings/<int:job_id>/",
        ui_views.jobs.LandingJobView.as_view(),
        {"revision_id": None},
        name="jobs-page",
    ),
]

urlpatterns += [
    path(
        "api/diff_warnings/",
        api_views.LegacyDiffWarningView.as_view(),
        name="diff-warnings",
    ),
    path(
        "api/diff_warnings/<int:diff_warning_id>/",
        api_views.LegacyDiffWarningView.as_view(),
        name="diff-warnings",
    ),
    re_path(
        r"api/git2hg/(?P<git_repo_name>.*)/(?P<commit_hash>[0-9a-f]{7,40})",
        api_views.git2hgCommitMapView.as_view(),
        name="git2hg",
    ),
    re_path(
        r"api/hg2git/(?P<git_repo_name>.*)/(?P<commit_hash>[0-9a-f]{40})",
        api_views.hg2gitCommitMapView.as_view(),
        name="hg2git",
    ),
]

urlpatterns += [
    path(
        "api/pulls/<str:repo_name>/<int:pull_number>/landing_jobs",
        api_views.LandingJobPullRequestAPIView.as_view(),
        name="api-landing-job-pull-request",
    ),
    path(
        "api/pulls/<str:repo_name>/<int:pull_number>/checks",
        api_views.PullRequestChecksAPIView.as_view(),
        name="api-pull-request-checks",
    ),
    path(
        "api/pulls/<str:repo_name>/<int:pull_number>",
        api_views.PullRequestContentAPIView.as_view(),
        name="api-pull-request-update-content",
    ),
    path(
        "api/pulls/webhook",
        api_views.PullRequestUpdateWebhook.as_view(),
        name="api-pull-request-description",
    ),
]

# "API" endpoints ported from legacy API app.
urlpatterns += [
    path(
        "landing_jobs/<int:job_id>/",
        api_views.LandingJobApiView.as_view(),
        name="landing-jobs",
    ),
]

urlpatterns += [
    path("api/", headless_api.urls, name="headless-api"),
    path("api/uplift/", uplift_api.urls, name="uplift-api"),
    path(
        "api/jobs/<int:job_id>/",
        ui_views.jobs.AutomationJobView.as_view(),
        name="api-jobs-page",
    ),
]

# Treestatus URLs.
urlpatterns += [
    path("", treestatus_api.urls, name="treestatus-api"),
    path("treestatus/", TreestatusDashboardView.as_view(), name="treestatus-dashboard"),
    path(
        "treestatus/new_tree/",
        TreestatusNewTreeView.as_view(),
        name="treestatus-new-tree",
    ),
    path(
        "treestatus/<str:tree>/logs",
        TreestatusTreeLogsView.as_view(),
        name="treestatus-tree-logs",
    ),
    path(
        "treestatus/stack/<int:id>",
        TreestatusUpdateChangeView.as_view(),
        name="treestatus-update-change",
    ),
    path(
        "treestatus/log/<int:id>",
        TreestatusLogUpdateView.as_view(),
        name="treestatus-update-log",
    ),
]

# Try endpoints.
urlpatterns += [
    # New path, as per bug 1990111.
    path("api/try/", try_api.urls, name="try"),
    # Deprecated backward-compatible path.
    path("try/", legacy_try_api.urls, name="legacy_try"),
]
