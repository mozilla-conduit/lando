from django.contrib import admin

from lando.main.models import LandingJob, Repo, Revision, Worker

admin.site.register(LandingJob, admin.ModelAdmin)
admin.site.register(Revision, admin.ModelAdmin)
admin.site.register(Repo, admin.ModelAdmin)
admin.site.register(Worker, admin.ModelAdmin)
