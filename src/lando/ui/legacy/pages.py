# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging

from lando.ui.views import LandoView
from django.template.response import TemplateResponse

logger = logging.getLogger(__name__)


class Index(LandoView):
    def get(self, request):
        return TemplateResponse(request=request, template="home.html")


# @pages.route("/settings", methods=["POST"])
# @oidc.oidc_auth("AUTH0")
# def settings():
#     if not is_user_authenticated():
#         # Accessing it unauthenticated from UI is protected by CSP
#         return jsonify(
#             dict(success=False, errors=dict(form_errors=["User is not authenticated"]))
#         )
#
#     form = UserSettingsForm()
#     if not form.validate_on_submit():
#         return jsonify(dict(success=False, errors=form.errors))
#
#     payload = dict(success=True)
#     response = manage_phab_api_token_cookie(form, payload)
#     return response
