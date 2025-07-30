from django import forms

from lando.api.legacy.uplift import get_uplift_repositories
from lando.main.models import Repo


class TransplantRequestForm(forms.Form):
    landing_path = forms.JSONField(widget=forms.widgets.HiddenInput)
    confirmation_token = forms.CharField(
        widget=forms.widgets.HiddenInput, required=False
    )
    flags = forms.JSONField(widget=forms.widgets.HiddenInput, required=False)


class UpliftQuestionnaireForm(forms.Form):
    """Form to process the uplift request questionnaire."""

    user_impact = forms.TextField(
        widget=forms.Textarea, label="User impact if declined?"
    )

    covered_by_testing = forms.BooleanField(label="Code covered by automated testing?")

    fix_verified_in_nightly = forms.BooleanField(label="Fix verified in Nightly?")

    needs_manual_qe_testing = forms.BooleanField(label="Needs manual QE testing?")

    qe_testing_reproduction_steps = forms.TextField(
        required=False, label="Steps to reproduce for manual QE testing"
    )

    risk_associated_with_patch = forms.TextField(
        widget=forms.Textarea, label="Risk associated with taking this patch"
    )

    risk_level_explanation = forms.TextField(
        widget=forms.Textarea, label="Explanation of risk level"
    )

    string_changes = forms.TextField(
        widget=forms.Textarea, label="String changes made/needed?"
    )

    is_android_affected = forms.BooleanField(label="Is Android affected?")

    def clean(self):
        cleaned_data = super().clean()

        """Ensure QE reproduction steps are given if manual QE testing is required."""
        if (
            cleaned_data["needs_manual_qe_testing"]
            and not cleaned_data["qe_testing_reproduction_steps"]
        ):
            raise forms.ValidationError(
                "QE testing reproduction steps must be provided if manual testing is required."
            )


class UpliftRequestForm(UpliftQuestionnaireForm):
    """Form used to request uplift of a stack."""

    revision_id = forms.RegexField(
        regex="^D[0-9]+$",
        widget=forms.widgets.HiddenInput,
        required=False,
    )
    repository = forms.ChoiceField(
        widget=forms.Select(),
        choices=((repo, repo) for repo in get_uplift_repositories()),
    )

    def clean_repository(self) -> str:
        repo_short_name = self.cleaned_data["repository"]
        try:
            repository = Repo.objects.get(short_name=repo_short_name)
        except Repo.DoesNotExist:
            raise forms.ValidationError(
                f"Repository {repo_short_name} is not a repository known to Lando. "
                "Please select an uplift repository to create the uplift request."
            )

        if not repository.approval_required:
            raise forms.ValidationError(
                f"Repository {repo_short_name} is not an uplift repository. "
                "Please select an uplift repository to create the uplift request."
            )
        return repository


class UserSettingsForm(forms.Form):
    """Form used to provide the Phabricator API Token."""

    phabricator_api_key = forms.RegexField(
        required=False,
        regex="^api-[a-z0-9]{28}$",
        label="Phabricator API Key",
    )
    phabricator_api_key.widget.attrs.update({"class": "input"})
    reset_key = forms.BooleanField(required=False, label="Delete")
