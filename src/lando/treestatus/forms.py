from typing import Self

from django import forms

from lando.treestatus.models import (
    ReasonCategory,
    TreeCategory,
    TreeStatus,
)


class TreeStatusUpdateTreesForm(forms.Form):
    """Form used to update the state of a selection of trees."""

    trees = forms.MultipleChoiceField(label="Trees", required=True)

    status = forms.ChoiceField(label="Status", choices=TreeStatus, required=True)

    reason = forms.CharField(label="Reason", required=False)

    reason_category = forms.ChoiceField(
        label="Reason Category",
        choices=ReasonCategory,
        required=False,
        initial=ReasonCategory.NO_CATEGORY.value,
    )

    remember = forms.BooleanField(
        label="Remember this change", required=False, initial=True
    )

    message_of_the_day = forms.CharField(label="Message of the day", required=False)

    @classmethod
    def with_tree_names(cls, tree_names: list[str], **kwargs) -> Self:
        """Construct a `TreeStatusUpdateTreesForm` and populate tree choices.

        Builds the form from `data` or `initial` arguments and populates choices
        for the `trees` argument from a list of tree names.
        """
        form = cls(**kwargs)
        form.fields["trees"].choices = [
            (tree_name, tree_name) for tree_name in tree_names
        ]

        return form

    def clean_status(self) -> TreeStatus:
        """Verify the `status` field and convert to a `TreeStatus`."""
        status_input = self.cleaned_data["status"]

        try:
            return TreeStatus(status_input)
        except ValueError:
            raise forms.ValidationError(f"{status_input} is not a valid tree status.")

    def clean_reason_category(self) -> ReasonCategory:
        """Verify the `reason_category` field and convert to a `ReasonCategory`."""
        reason_category_input = self.cleaned_data["reason_category"]

        try:
            return ReasonCategory(reason_category_input)
        except ValueError:
            raise forms.ValidationError(
                f"{reason_category_input} is not a valid reason category."
            )

    def clean(self):
        """Verify required fields are present when closing trees."""
        cleaned_data = super().clean()

        status = cleaned_data.get("status")
        reason = cleaned_data.get("reason")
        reason_category = cleaned_data.get("reason_category")

        if status == TreeStatus.CLOSED:
            if not reason:
                self.add_error(
                    "reason", "Reason description is required to close trees."
                )

            if not reason_category or reason_category == ReasonCategory.NO_CATEGORY:
                self.add_error(
                    "reason_category", "Reason category is required to close trees."
                )


class TreeStatusNewTreeForm(forms.Form):
    """Add a new tree to Treestatus."""

    tree = forms.CharField(label="Tree", required=True)

    category = forms.ChoiceField(
        label="Tree category",
        choices=TreeCategory,
        required=False,
        initial=TreeCategory.OTHER.value,
    )


class TreeStatusRecentChangesForm(forms.Form):
    """Modify a recent status change."""

    reason = forms.CharField(label="Reason", required=False)

    reason_category = forms.ChoiceField(
        label="Reason Category", choices=ReasonCategory, required=False
    )


class TreeStatusLogUpdateForm(forms.Form):
    """Modify a log entry."""

    reason = forms.CharField(label="Reason", required=False)

    reason_category = forms.ChoiceField(
        label="Reason Category", choices=ReasonCategory, required=False
    )
