from django.http import HttpResponse


class ProblemException(Exception):
    def __init__(self, *, status=500, title=None, detail=None, type=None, instance=None, headers=None, ext=None):
        # TODO: this should be reimplemented as either middleware or HttpResponse return values.
        super().__init__(self)


def problem(status, title, detail, type=None, instance=None, headers=None, ext=None):
    return HttpResponse(content=detail, headers=headers, status_code=status)


request = {
    "headers": {},
}

session = {}


class g:
    auth0_user = None
    access_token = None
    access_token_payload = None
    _request_start_timestamp = None


class FlaskApi:
    @classmethod
    def get_response(self, _problem):
        return _problem


class ConnexionResponse(HttpResponse):
    pass