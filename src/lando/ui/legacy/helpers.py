from typing import (
    Optional,
)

from flask import request, session


def is_user_authenticated() -> bool:
    """Returns whether the user is logged in or not."""
    return "id_token" in session and "access_token" in session


def set_last_local_referrer():
    """
    Sets the url of the last route that the user visited on this server.

    This is mainly used to implement our login flow:
        - Most pages are initially public (i.e. you do not have to sign in).
          This means they cannot be protected with the 'oidc_auth' decorator.
        - Routes protected with the 'oidc_auth' decorator require login
          before any code in that route is executed.
        - Going to a protected route will immediately redirect to Auth0.
        - Upon successful login, flask-pyoidc will redirect back to the
          original route that was decorated.

    Considering this we need a dedicated 'signin' route which will be protected
    and when the user is redirected back to the route, it will then redirect
    them to the last_local_referrer stored in their session.
    This referrer can of course be used for many other things.

    This does not activate for the IGNORED_ROUTES defined inside this method.
    """
    IGNORED_ROUTES = ["/signin", "/signout", "/logout"]
    full_path = request.script_root + request.path
    if full_path not in IGNORED_ROUTES:
        session["last_local_referrer"] = request.url


def str2bool(value: str) -> bool:
    """Translate a string to a boolean value."""
    return str(value).lower() in ("yes", "true", "y", "1")


def get_phabricator_api_token() -> Optional[str]:
    """Gets the Phabricator API Token from the cookie."""
    if is_user_authenticated() and "phabricator-api-token" in request.cookies:
        return request.cookies["phabricator-api-token"]

    return None
