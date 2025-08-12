from django import forms
from django.db import models
from django.forms.widgets import RadioSelect

from lando.api.legacy.uplift import get_uplift_repositories
from lando.main.models import Repo


class TransplantRequestForm(forms.Form):
    landing_path = forms.JSONField(widget=forms.widgets.HiddenInput)
    confirmation_token = forms.CharField(
        widget=forms.widgets.HiddenInput, required=False
    )
    flags = forms.JSONField(widget=forms.widgets.HiddenInput, required=False)


# Yes/No constants for re-use in `TextChoices`.
YES = "yes", "Yes"
NO = "no", "No"


class YesNoChoices(models.TextChoices):
    """A yes/no choice selection."""

    YES = YES
    NO = NO


class YesNoUnknownChoices(models.TextChoices):
    """A yes/no/unknown choice selection."""

    YES = YES
    NO = NO
    UNKNOWN = "unknown", "Unknown"


class LowMediumHighChoices(models.TextChoices):
    """A low/medium/high choice selection."""

    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"


class UpliftQuestionnaireForm(forms.Form):
    """Form to process the uplift request questionnaire."""

    user_impact = forms.CharField(
        widget=forms.Textarea, label="User impact if declined/Reason for urgency"
    )

    covered_by_testing = forms.ChoiceField(
        label="Code covered by automated testing?",
        choices=YesNoUnknownChoices.choices,
        widget=RadioSelect,
    )

    fix_verified_in_nightly = forms.ChoiceField(
        label="Fix verified in Nightly?",
        choices=YesNoChoices.choices,
        widget=RadioSelect,
    )

    needs_manual_qe_testing = forms.ChoiceField(
        label="Needs manual QE testing?",
        choices=YesNoChoices.choices,
        widget=RadioSelect,
    )

    qe_testing_reproduction_steps = forms.CharField(
        required=False,
        label="Steps to reproduce for manual QE testing",
        widget=forms.Textarea,
    )

    risk_associated_with_patch = forms.ChoiceField(
        label="Risk associated with taking this patch",
        choices=LowMediumHighChoices.choices,
        widget=RadioSelect,
    )

    risk_level_explanation = forms.CharField(
        widget=forms.Textarea, label="Explanation of risk level"
    )

    string_changes = forms.CharField(
        widget=forms.Textarea, label="String changes made/needed?"
    )

    is_android_affected = forms.ChoiceField(
        label="Is Android affected?",
        choices=YesNoUnknownChoices.choices,
        widget=RadioSelect,
    )

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
