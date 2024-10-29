from django.urls import path

from lando.dockerflow import views as DockerflowViews

app_name = "dockerflow"

urlpatterns = [
    path("__version__", DockerflowViews.VersionView.as_view(), name="version"),
    path("__heartbeat__", DockerflowViews.HeartbeatView.as_view(), name="heartbeat"),
    path(
        "__lbheartbeat__",
        DockerflowViews.LoadBalancerHeartbeatView.as_view(),
        name="lbheartbeat",
    ),
]
