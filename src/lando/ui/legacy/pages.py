# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging
import os

from flask import (
    Blueprint,
    current_app,
    jsonify,
    make_response,
    redirect,
    render_template,
    session,
)

from lando.ui.legacy.app import oidc
from lando.ui.legacy.forms import UserSettingsForm
from lando.ui.legacy.helpers import set_last_local_referrer, is_user_authenticated
from lando.ui.legacy.usersettings import manage_phab_api_token_cookie

logger = logging.getLogger(__name__)

pages = Blueprint("page", __name__)
pages.before_request(set_last_local_referrer)


@pages.route("/")
def home():
    return render_template("home.html")


@pages.route("/signin")
@oidc.oidc_auth("AUTH0")
def signin():
    redirect_url = session.get("last_local_referrer") or "/"
    return redirect(redirect_url)


@pages.route("/signout")
def signout():
    return render_template("signout.html")


@pages.route("/logout")
@oidc.oidc_logout
def logout():
    protocol = "https" if current_app.config["USE_HTTPS"] else "http"

    return_url = "{protocol}://{host}/signout".format(
        protocol=protocol, host=current_app.config["SERVER_NAME"]
    )

    logout_url = (
        "https://{auth0_host}/v2/logout?returnTo={return_url}&"
        "client_id={client_id}".format(
            auth0_host=os.environ["OIDC_DOMAIN"],
            return_url=return_url,
            client_id=os.environ["OIDC_CLIENT_ID"],
        )
    )

    response = make_response(redirect(logout_url, code=302))
    response.delete_cookie("phabricator-api-token")
    return response


@pages.route("/settings", methods=["POST"])
@oidc.oidc_auth("AUTH0")
def settings():
    if not is_user_authenticated():
        # Accessing it unauthenticated from UI is protected by CSP
        return jsonify(
            dict(success=False, errors=dict(form_errors=["User is not authenticated"]))
        )

    form = UserSettingsForm()
    if not form.validate_on_submit():
        return jsonify(dict(success=False, errors=form.errors))

    payload = dict(success=True)
    response = manage_phab_api_token_cookie(form, payload)
    return response
