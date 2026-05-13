from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.template.response import TemplateResponse


class BaseLandoViewMixin:
    """Provide helper methods for returning HTTP responses."""

    def _raise_handled_exception(self, exception: Exception, original: Exception):
        """Handle the special case of raising exceptions that are handled by middleware."""
        if original:
            raise exception from original
        raise exception

    def response(self, *args, **kwargs) -> TemplateResponse | JsonResponse:
        """Return a response object based on the base response class."""
        return self.response_class(*args, **kwargs)

    def raise_http404(self, message: str = "", original: Exception | None = None):
        """Raise django.http.Http404."""
        # Note: this will use the 404 template available to Lando.
        exception = Http404(message)
        self._raise_handled_exception(exception, original)

    def raise_permission_denied(self, message: str, original: Exception | None = None):
        """Raise django.core.exceptions.PermissionDenied which is handled by middleware."""
        # Note: this will use the 403 template available to Lando.
        exception = PermissionDenied(message)
        self._raise_handled_exception(exception, original)
