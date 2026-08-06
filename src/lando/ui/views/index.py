from django.core.handlers.wsgi import WSGIRequest
from django.template.response import TemplateResponse

from lando.main.models import JobStatus, LandingJob
from lando.ui.views.base import LandoView


class IndexView(LandoView):
    MAX_JOBS_HISTORY = 10

    def get(self, request: WSGIRequest) -> TemplateResponse:
        context = {"MAX_JOBS_HISTORY": self.MAX_JOBS_HISTORY}
        if request.user.is_authenticated:
            context["pending_jobs"] = LandingJob.objects.filter(
                requester_email=request.user.email, status__in=JobStatus.pending()
            )
            context["final_jobs"] = LandingJob.objects.filter(
                requester_email=request.user.email,
                status__in=JobStatus.final(),
            ).order_by("-updated_at")[: self.MAX_JOBS_HISTORY]

        return TemplateResponse(request=request, template="home.html", context=context)
