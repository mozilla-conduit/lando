from django.core.management.base import BaseCommand

from lando.utils.celery import app


class Command(BaseCommand):
    help = "Start celery worker"

    def handle(self, *args, **options):
        worker = app.Worker()
        worker.start()
