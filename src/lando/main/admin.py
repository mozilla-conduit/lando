from django.contrib import admin

from lando.main.models.landing_job import LandingJob
from lando.main.models.revision import Revision
from lando.main.models.base import Repo, Worker

admin.site.register(LandingJob, admin.ModelAdmin)
admin.site.register(Revision, admin.ModelAdmin)
admin.site.register(Repo, admin.ModelAdmin)
admin.site.register(Worker, admin.ModelAdmin)
