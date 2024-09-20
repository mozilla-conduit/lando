from django import forms


class TransplantRequestForm(forms.Form):
    landing_path = forms.JSONField(widget=forms.widgets.HiddenInput)
    confirmation_token = forms.CharField(widget=forms.widgets.HiddenInput, required=False)
    flags = forms.JSONField(widget=forms.widgets.HiddenInput, required=False)


class UpliftRequestForm(forms.Form):
    """Form used to request uplift of a stack."""

    revision_id = forms.RegexField(regex="D[0-9]+$")
    repository = forms.CharField()


class UserSettingsForm(forms.Form):
    """Form used to provide the Phabricator API Token."""

    phabricator_api_key = forms.RegexField(required=False, regex="^api-[a-z0-9]{28}$")
    reset_key = forms.BooleanField(required=False)
