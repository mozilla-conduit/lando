from django import forms
from django.forms.widgets import RadioSelect

from lando.api.legacy.uplift import get_uplift_repositories
from lando.main.models import Repo
from lando.main.models.uplift import (
    LowMediumHighChoices,
    UpliftAssessment,
    YesNoChoices,
    YesNoUnknownChoices,
)


class TransplantRequestForm(forms.Form):
    landing_path = forms.JSONField(widget=forms.widgets.HiddenInput)
    confirmation_token = forms.CharField(
        widget=forms.widgets.HiddenInput, required=False
    )
    flags = forms.JSONField(widget=forms.widgets.HiddenInput, required=False)


class UpliftAssessmentForm(forms.ModelForm):
    """Form to process the uplift request assessment."""

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
        """Ensure QE reproduction steps are given if manual QE testing is required."""
        cleaned_data = super().clean()

        needs_manual_qe_testing = cleaned_data.get("needs_manual_qe_testing")

        if needs_manual_qe_testing == YesNoChoices.YES and not cleaned_data.get(
            "qe_testing_reproduction_steps"
        ):
            self.add_error(
                "qe_testing_reproduction_steps",
                "QE testing reproduction steps must be provided if manual testing is required.",
            )

    class Meta:
        model = UpliftAssessment
        exclude = ["id", "user"]
        widgets = {
            "user_impact": forms.Textarea,
            "qe_testing_reproduction_steps": forms.Textarea,
            "risk_level_explanation": forms.Textarea,
            "string_changes": forms.Textarea,
            "covered_by_testing": RadioSelect,
            "fix_verified_in_nightly": RadioSelect,
            "needs_manual_qe_testing": RadioSelect,
            "risk_associated_with_patch": RadioSelect,
            "is_android_affected": RadioSelect,
        }
        labels = {
            "user_impact": "User impact if declined/Reason for urgency",
            "covered_by_testing": "Code covered by automated testing?",
            "fix_verified_in_nightly": "Fix verified in Nightly?",
            "needs_manual_qe_testing": "Needs manual QE testing?",
            "qe_testing_reproduction_steps": "Steps to reproduce for manual QE testing",
            "risk_associated_with_patch": "Risk associated with taking this patch",
            "risk_level_explanation": "Explanation of risk level",
            "string_changes": "String changes made/needed?",
            "is_android_affected": "Is Android affected?",
        }


class UpliftAssessmentEditForm(UpliftAssessmentForm):
    """Form used to edit an uplift assessment form for a patch."""

    revision_id = forms.RegexField(
        regex="^D[0-9]+$",
        widget=forms.widgets.HiddenInput,
    )


class UpliftRequestForm(UpliftAssessmentForm):
    """Form used to request uplift of a stack."""

    source_revision_id = forms.RegexField(
        regex="^D[0-9]+$",
        widget=forms.widgets.HiddenInput,
        required=False,
    )
    repository = forms.ChoiceField(
        widget=forms.Select(),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        uplift_repos = get_uplift_repositories()
        self.fields["repository"].choices = [(repo, repo) for repo in uplift_repos]

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
