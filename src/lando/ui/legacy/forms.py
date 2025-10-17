from django import forms
from django.forms.widgets import RadioSelect

from lando.main.models import Repo, Revision
from lando.main.models.uplift import (
    UpliftAssessment,
    YesNoChoices,
)


class TransplantRequestForm(forms.Form):
    landing_path = forms.JSONField(widget=forms.widgets.HiddenInput)
    confirmation_token = forms.CharField(
        widget=forms.widgets.HiddenInput, required=False
    )
    flags = forms.JSONField(widget=forms.widgets.HiddenInput, required=False)


class UpliftAssessmentForm(forms.ModelForm):
    """Form to process the uplift request assessment."""

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


class UpliftAssessmentEditForm(UpliftAssessmentForm):
    """Form used to edit an uplift assessment form for a patch."""

    revision_id = forms.RegexField(
        regex="^D[0-9]+$",
        widget=forms.widgets.HiddenInput,
    )


class UpliftRequestForm(UpliftAssessmentForm):
    """Form used to request uplift of a stack."""

    source_revision_ids = forms.ModelMultipleChoiceField(
        queryset=Revision.objects.all(),
        to_field_name="revision_id",
        widget=forms.widgets.MultipleHiddenInput(),
    )
    repositories = forms.MultipleChoiceField(
        widget=forms.CheckboxSelectMultiple(),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        uplift_repos = Repo.objects.filter(approval_required=True).all()
        self.fields["repositories"].choices = [
            (repo.name, repo.name) for repo in uplift_repos
        ]

    def clean_repositories(self) -> list[Repo]:
        repositories = self.cleaned_data.get("repositories")

        cleaned_repositories = []
        for repo in repositories:
            try:
                repository = Repo.objects.get(name=repo)
            except Repo.DoesNotExist:
                raise forms.ValidationError(
                    f"Repository {repo} is not a repository known to Lando. "
                    "Please select an uplift repository to create the uplift request."
                )

            if not repository.approval_required:
                raise forms.ValidationError(
                    f"Repository {repo} is not an uplift repository. "
                    "Please select an uplift repository to create the uplift request."
                )

            cleaned_repositories.append(repository)

        return cleaned_repositories


class UserSettingsForm(forms.Form):
    """Form used to provide the Phabricator API Token."""

    phabricator_api_key = forms.RegexField(
        required=False,
        regex="^api-[a-z0-9]{28}$",
        label="Phabricator API Key",
    )
    phabricator_api_key.widget.attrs.update({"class": "input"})
    reset_key = forms.BooleanField(required=False, label="Delete")
