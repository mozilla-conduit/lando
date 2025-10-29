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


class UpliftRequestForm(UpliftAssessmentForm):
    """Form used to request uplift of a stack."""

    source_revision_ids = forms.ModelMultipleChoiceField(
        queryset=Revision.objects.all(),
        to_field_name="revision_id",
        widget=forms.widgets.MultipleHiddenInput(),
    )
    repositories = forms.ModelMultipleChoiceField(
        queryset=Repo.objects.filter(approval_required=True),
        widget=forms.CheckboxSelectMultiple(),
        to_field_name="name",
    )

    def clean_source_revision_ids(self) -> list[Revision]:
        """Return source revisions in the same order they were submitted."""
        revisions_qs = self.cleaned_data["source_revision_ids"]
        requested_order = self.data.getlist(self.add_prefix("source_revision_ids"))

        revisions_by_id = {
            str(revision.revision_id): revision for revision in revisions_qs
        }
        ordered_revisions = [
            revisions_by_id[rev_id]
            for rev_id in requested_order
            if rev_id in revisions_by_id
        ]

        return ordered_revisions

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Set the rendered value of the repository to the
        # name, instead of the default `__str__` representation.
        self.fields["repositories"].label_from_instance = lambda repo: repo.name


class UserSettingsForm(forms.Form):
    """Form used to provide the Phabricator API Token."""

    phabricator_api_key = forms.RegexField(
        required=False,
        regex="^api-[a-z0-9]{28}$",
        label="Phabricator API Key",
    )
    phabricator_api_key.widget.attrs.update({"class": "input"})
    reset_key = forms.BooleanField(required=False, label="Delete")
