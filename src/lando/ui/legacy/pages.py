import datetime
import logging

from django.core.handlers.wsgi import WSGIRequest
from django.template.response import TemplateResponse

from lando.main.models.jobs import JobStatus
from lando.main.models.landing_job import LandingJob
from lando.ui.views import LandoView

logger = logging.getLogger(__name__)


class IndexView(LandoView):
    FINAL_JOBS_MAX_DAYS = 7

    def get(self, request: WSGIRequest) -> TemplateResponse:
        context = {}
        if request.user.is_authenticated:
            context["pending_jobs"] = LandingJob.objects.filter(
                requester_email=request.user.email, status__in=JobStatus.pending()
            )
            context["final_jobs"] = LandingJob.objects.filter(
                requester_email=request.user.email,
                status__in=JobStatus.final(),
                updated_at__gt=datetime.datetime.now()
                - datetime.timedelta(days=self.FINAL_JOBS_MAX_DAYS),
            )

        return TemplateResponse(request=request, template="home.html", context=context)
