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

from lando.ui.legacy import revisions, pages
from lando.dockerflow import views as DockerflowViews

urlpatterns = [
    path("admin/", admin.site.urls),
    path("oidc/", include("mozilla_django_oidc.urls")),
]

# "UI" pages ported from legacy UI app.
urlpatterns += [
    path("", pages.Index.as_view()),
    path("D<int:revision_id>/", revisions.Revision.as_view(), name="revisions-page"),
]

urlpatterns += [
    path("__version__", DockerflowViews.VersionView.as_view(), name="version"),
    path("__heartbeat__", DockerflowViews.HeartbeatView.as_view(), name="heartbeat"),
    path("__lbheartbeat__", DockerflowViews.LoadBalancerHeartbeatView.as_view(), name="lbheartbeat"),
]
