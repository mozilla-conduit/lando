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
from django.urls import include, path

from lando.api.legacy.api import landing_jobs
from lando.main.api import (
    api as automation_api,
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
]

# "API" endpoints ported from legacy API app.
urlpatterns += [
    path("landing_jobs/<int:landing_job_id>/", landing_jobs.put, name="landing-jobs"),
]

urlpatterns += [
    path("api/", automation_api.urls, name="automation-api"),
]
