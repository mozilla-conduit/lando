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
    LegacyDiffWarningView,
    git2hgCommitMapView,
    hg2gitCommitMapView,
)
from lando.headless_api.api import (
    api as headless_api,
)
from lando.ui.legacy import pages, revisions, user_settings

urlpatterns = [
    path("", include("lando.dockerflow.urls", "dockerflow")),
    path("admin/", admin.site.urls),
    path("oidc/", include("mozilla_django_oidc.urls")),
]

urlpatterns += [
    path("", pages.Index.as_view()),
    path("D<int:revision_id>/", revisions.Revision.as_view(), name="revisions-page"),
    path("manage_api_key/", user_settings.manage_api_key, name="user-settings"),
    path("uplift/", revisions.Uplift.as_view(), name="uplift-page"),
]

urlpatterns += [
    path("api/diff_warnings/", LegacyDiffWarningView.as_view(), name="diff-warnings"),
    path(
        "api/diff_warnings/<int:diff_warning_id>/",
        LegacyDiffWarningView.as_view(),
        name="diff-warnings",
    ),
    re_path(
        r"api/git2hg/(?P<git_repo_name>.*)/(?P<commit_hash>[0-9a-f]{40})",
        git2hgCommitMapView.as_view(),
        name="git2hg",
    ),
    re_path(
        r"api/hg2git/(?P<git_repo_name>.*)/(?P<commit_hash>[0-9a-f]{40})",
        hg2gitCommitMapView.as_view(),
        name="hg2git",
    ),
]

# "API" endpoints ported from legacy API app.
urlpatterns += [
    path("landing_jobs/<int:landing_job_id>/", landing_jobs.put, name="landing-jobs"),
]

urlpatterns += [
    path("api/", headless_api.urls, name="headless-api"),
]
