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

from django.contrib import admin
from django.urls import include, path, re_path

from lando.api.legacy.api import landing_jobs
from lando.api.views import (
    LandingJobPullRequestAPIView,
    LegacyDiffWarningView,
    git2hgCommitMapView,
    hg2gitCommitMapView,
)
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
from lando.ui import jobs, pull_requests
from lando.ui.legacy import pages, revisions, user_settings

urlpatterns = [
    path("", include("lando.dockerflow.urls", "dockerflow")),
    path("admin/", admin.site.urls),
    path("oidc/", include("mozilla_django_oidc.urls")),
]

urlpatterns += [
    path("", pages.IndexView.as_view()),
    path(
        "D<int:revision_id>/", revisions.RevisionView.as_view(), name="revisions-page"
    ),
    path(
        "pulls/<str:repo_name>/<int:number>/",
        pull_requests.PullRequestView.as_view(),
        name="pull-request",
    ),
    path("manage_api_key/", user_settings.manage_api_key, name="user-settings"),
    path("uplift/", revisions.UpliftRequestView.as_view(), name="uplift-page"),
    path(
        "uplift/<int:revision_id>/assessment/",
        revisions.UpliftAssessmentCreateOrEditView.as_view(),
        name="uplift-assessment-page",
    ),
    path(
        "uplift/jobs/<int:job_id>/",
        jobs.UpliftJobView.as_view(),
        name="uplift-jobs-page",
    ),
]

urlpatterns += [
    path("api/diff_warnings/", LegacyDiffWarningView.as_view(), name="diff-warnings"),
    path(
        "api/diff_warnings/<int:diff_warning_id>/",
        LegacyDiffWarningView.as_view(),
        name="diff-warnings",
    ),
    re_path(
        r"api/git2hg/(?P<git_repo_name>.*)/(?P<commit_hash>[0-9a-f]{7,40})",
        git2hgCommitMapView.as_view(),
        name="git2hg",
    ),
    re_path(
        r"api/hg2git/(?P<git_repo_name>.*)/(?P<commit_hash>[0-9a-f]{40})",
        hg2gitCommitMapView.as_view(),
        name="hg2git",
    ),
]

urlpatterns += [
    path(
        "api/pulls/<str:repo_name>/<int:pull_number>/landing_jobs",
        LandingJobPullRequestAPIView.as_view(),
        name="api-landing-job-pull-request",
    ),
]

# "API" endpoints ported from legacy API app.
urlpatterns += [
    path(
        "landing_jobs/<int:job_id>/",
        landing_jobs.LandingJobApiView.as_view(),
        name="landing-jobs",
    ),
    path(
        "D<int:revision_id>/landings/<int:job_id>/",
        jobs.LandingJobView.as_view(),
        name="revision-jobs-page",
    ),
    # Allow to find a landing job by ID only. The page will redirect to the canonical
    # URL including the revision.
    path(
        "landings/<int:job_id>/",
        jobs.LandingJobView.as_view(),
        {"revision_id": None},
        name="jobs-page",
    ),
]

urlpatterns += [
    path("api/", headless_api.urls, name="headless-api"),
    path(
        "api/jobs/<int:job_id>/",
        jobs.AutomationJobView.as_view(),
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
urlpatterns += [path("try/", try_api.urls, name="try")]
