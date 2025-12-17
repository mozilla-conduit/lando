from django import forms
from django.contrib.auth.models import User
from django.forms.widgets import RadioSelect
from django.utils import timezone

from lando.api.legacy.validation import parse_revision_ids
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


class LinkUpliftAssessmentForm(forms.Form):
    """Form to select an existing uplift assessment owned by the user."""

    assessment = forms.ModelChoiceField(
        label="Existing uplift assessment",
        # `queryset` is defined in `__init__` as it depends on the user.
        queryset=None,
        required=True,
        help_text="Select a previous assessment to link to this revision.",
    )

    def __init__(self, *args, user: User | None = None, **kwargs):
        super().__init__(*args, **kwargs)

        queryset = UpliftAssessment.objects.none()
        if user is not None and user.is_authenticated:
            queryset = (
                UpliftAssessment.objects.filter(user=user)
                .order_by("-updated_at")
                .prefetch_related("revisions")
            )

        field = self.fields["assessment"]
        field.queryset = queryset
        field.label_from_instance = self.assessment_label
        field.empty_label = "Select an assessment"

        # Set this helper so templates can quickly check if there
        # are any pre-existing assessments to display.
        self.has_assessments = queryset.exists()

    @staticmethod
    def assessment_label(assessment: UpliftAssessment) -> str:
        """Provide a useful label for the uplift assessments.

        Example: "Tue, 4 November: D1234, D1235 -- reason for urgency"
        """
        timestamp = assessment.updated_at or assessment.created_at
        timestamp_local = timezone.localtime(timestamp)

        date_label = f"{timestamp_local.strftime('%a, %B')} {timestamp_local.day}, {timestamp_local.year}"

        linked_revisions = list(
            assessment.revisions.values_list("revision_id", flat=True)
        )
        if linked_revisions:
            revisions_note = ", ".join(f"D{rev_id}" for rev_id in linked_revisions)
        else:
            revisions_note = "No linked revisions"

        summary = assessment.user_impact.strip().replace("\n", " ")
        if len(summary) > 80:
            summary = f"{summary[:77]}..."

        return f"#{assessment.id}: {date_label}: {revisions_note} -- {summary}"


class UpliftAssessmentLinkForm(UpliftAssessmentForm):
    """Form for creating/updating an assessment and linking to multiple revisions."""

    assessment = forms.ModelChoiceField(
        queryset=UpliftAssessment.objects.none(),
        widget=forms.widgets.HiddenInput(),
        required=False,
        help_text="Existing assessment to update (optional)",
    )

    revision_ids = forms.CharField(
        widget=forms.widgets.HiddenInput(),
        help_text="Comma-separated list of Phabricator revision IDs",
    )

    def __init__(self, *args, user: User | None = None, **kwargs):
        super().__init__(*args, **kwargs)

        # Filter queryset to only show assessments owned by the current user.
        if user is not None and user.is_authenticated:
            self.fields["assessment"].queryset = UpliftAssessment.objects.filter(
                user=user
            )

    def clean_revision_ids(self) -> list[int]:
        """Parse and validate the comma-separated revision IDs."""
        revision_ids_str = self.cleaned_data["revision_ids"]

        try:
            return parse_revision_ids(revision_ids_str)
        except ValueError as e:
            raise forms.ValidationError(str(e)) from e


class UpliftRequestForm(UpliftAssessmentForm):
    """Form used to request uplift of a stack."""

    source_revisions = forms.ModelMultipleChoiceField(
        queryset=Revision.objects.all(),
        to_field_name="revision_id",
        widget=forms.CheckboxSelectMultiple(),
    )
    repositories = forms.ModelMultipleChoiceField(
        queryset=Repo.objects.filter(approval_required=True).order_by("name"),
        widget=forms.CheckboxSelectMultiple(),
        to_field_name="name",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Set the rendered value of the repository to the
        # name, instead of the default `__str__` representation.
        self.fields["repositories"].label_from_instance = lambda repo: repo.name

    def clean_source_revisions(self) -> list[Revision]:
        """Return source revisions in the same order they were submitted."""
        revisions_qs = self.cleaned_data["source_revisions"]
        requested_order = self.data.getlist(self.add_prefix("source_revisions"))

        revisions_by_id = {
            str(revision.revision_id): revision for revision in revisions_qs
        }
        ordered_revisions = [
            revisions_by_id[rev_id]
            for rev_id in requested_order
            if rev_id in revisions_by_id
        ]

        return ordered_revisions


class UserSettingsForm(forms.Form):
    """Form used to provide the Phabricator API Token."""

    phabricator_api_key = forms.RegexField(
        required=False,
        regex="^api-[a-z0-9]{28}$",
        label="Phabricator API Key",
    )
    phabricator_api_key.widget.attrs.update({"class": "input"})
    reset_key = forms.BooleanField(required=False, label="Delete")
