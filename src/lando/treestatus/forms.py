import enum
from dataclasses import dataclass
from typing import Optional


class Status(enum.Enum):
    """Allowable statuses of a tree."""

    OPEN = "open"
    CLOSED = "closed"
    APPROVAL_REQUIRED = "approval required"

    @classmethod
    def to_choices(cls) -> list[tuple[str, str]]:
        """Return a list of choices for display."""
        return [(choice.value, choice.value.capitalize()) for choice in list(cls)]


class ReasonCategory(enum.Enum):
    """Allowable reasons for a Tree closure."""

    NO_CATEGORY = ""
    JOB_BACKLOG = "backlog"
    CHECKIN_COMPILE_FAILURE = "checkin_compilation"
    CHECKIN_TEST_FAILURE = "checkin_test"
    PLANNED_CLOSURE = "planned"
    MERGES = "merges"
    WAITING_FOR_COVERAGE = "waiting_for_coverage"
    INFRASTRUCTURE_RELATED = "infra"
    OTHER = "other"

    @classmethod
    def to_choices(cls) -> list[tuple[str, str]]:
        """Return a list of choices for display."""
        return [(choice.value, choice.to_display()) for choice in list(cls)]

    def to_display(self) -> str:
        """Return a human-readable version of the category."""
        return {
            ReasonCategory.NO_CATEGORY: "No Category",
            ReasonCategory.JOB_BACKLOG: "Job Backlog",
            ReasonCategory.CHECKIN_COMPILE_FAILURE: "Check-in compilation failure",
            ReasonCategory.CHECKIN_TEST_FAILURE: "Check-in test failure",
            ReasonCategory.PLANNED_CLOSURE: "Planned closure",
            ReasonCategory.MERGES: "Merges",
            ReasonCategory.WAITING_FOR_COVERAGE: "Waiting for coverage",
            ReasonCategory.INFRASTRUCTURE_RELATED: "Infrastructure related",
            ReasonCategory.OTHER: "Other",
        }[self]

    @classmethod
    def is_valid_for_backend(cls, value) -> bool:  # noqa: ANN001
        """Return `True` if `value` is a valid `ReasonCategory` to be submitted.

        All `ReasonCategory` members are valid except for `NO_CATEGORY` as that is
        implied by an empty `tags` key in the backend.
        """
        try:
            category = cls(value)
        except ValueError:
            return False

        if category == ReasonCategory.NO_CATEGORY:
            return False

        return True


def build_update_json_body(
    reason: Optional[str], reason_category: Optional[str]
) -> dict:
    """Return a `dict` for use as a JSON body in a log/change update."""
    json_body = {}

    json_body["reason"] = reason

    if reason_category and ReasonCategory.is_valid_for_backend(reason_category):
        json_body["tags"] = [reason_category]

    return json_body


# TODO see bug 1893312.
# class TreeStatusUpdateTreesForm(forms.Form):
#     """Form used to update the state of a selection of trees."""
#
#     trees = forms.MultipleChoiceField(
#         "Trees",
#         required=True,
#     )
#
#     status = forms.ChoiceField(
#         "Status",
#         choices=Status.to_choices(),
#         required=True,
#     )
#
#     reason = forms.CharField("Reason")
#
#     reason_category = forms.ChoiceField(
#         "Reason Category",
#         choices=ReasonCategory.to_choices(),
#         default=ReasonCategory.NO_CATEGORY.value,
#     )
#
#     remember = forms.BooleanField(
#         "Remember this change",
#         default=True,
#     )
#
#     message_of_the_day = forms.CharField("Message of the day")
#
#     def validate_trees(self, field):
#         """Validate that at least 1 tree was selected."""
#         if not field.entries:
#             raise ValidationError(
#                 "A selection of trees is required to update statuses."
#             )
#
#     def validate_reason(self, field):
#         """Validate that the reason field is required for non-open statuses."""
#         reason_is_empty = not field.data
#
#         if Status(self.status.data) == Status.CLOSED and reason_is_empty:
#             raise ValidationError("Reason description is required to close trees.")
#
#     def validate_reason_category(self, field):
#         """Validate that the reason category field is required for non-open statuses."""
#         try:
#             category_is_empty = (
#                 not field.data
#                 or ReasonCategory(field.data) == ReasonCategory.NO_CATEGORY
#             )
#         except ValueError:
#             raise ValidationError("Reason category is an invalid value.")
#
#         if Status(self.status.data) == Status.CLOSED and category_is_empty:
#             raise ValidationError("Reason category is required to close trees.")
#
#     def to_submitted_json(self) -> dict:
#         """Convert a validated form to JSON for submission to LandoAPI."""
#         # Avoid setting tags for invalid values.
#         tags = (
#             [self.reason_category.data]
#             if ReasonCategory.is_valid_for_backend(self.reason_category.data)
#             else []
#         )
#
#         return {
#             "trees": self.trees.data,
#             "status": self.status.data,
#             "reason": self.reason.data,
#             "message_of_the_day": self.message_of_the_day.data,
#             "tags": tags,
#             "remember": self.remember.data,
#         }
#
#
class TreeCategory(enum.Enum):
    """Categories of the various trees.

    Note: the definition order is in order of importance for display in the UI.
    Note: this class also exists in Lando-UI, and should be updated in both places.
    """

    DEVELOPMENT = "development"
    RELEASE_STABILIZATION = "release_stabilization"
    TRY = "try"
    COMM_REPOS = "comm_repos"
    OTHER = "other"

    @classmethod
    def sort_trees(cls, item: dict) -> int:
        """Key function for sorting tree `dict`s according to category order."""
        return [choice.value for choice in list(cls)].index(item["category"])

    @classmethod
    def to_choices(cls) -> list[tuple[str, str]]:
        """Return a list of choices for display."""
        return [(choice.value, choice.to_display()) for choice in list(cls)]

    def to_display(self) -> str:
        """Return a human readable version of the category."""
        return " ".join(word.capitalize() for word in self.value.split("_"))


# TODO see bug 1893312.
# class TreeStatusNewTreeForm(forms.Form):
#     """Add a new tree to Treestatus."""
#
#     tree = forms.CharField(
#         "Tree",
#         required=True,
#     )
#
#     category = forms.ChoiceField(
#         "Tree category",
#         choices=TreeCategory.to_choices(),
#         default=TreeCategory.OTHER.value,
#     )


@dataclass
class RecentChangesAction:
    method: str
    request_args: dict
    message: str


# TODO see bug 1893312.
# class TreeStatusRecentChangesForm(forms.Form):
#     """Modify a recent status change."""
#
#     id = forms.CharField(widget=forms.HiddenInput(), required=True)
#
#     reason = forms.CharField(label="Reason", required=False)
#
#     reason_category = forms.ChoiceField(
#         label="Reason Category",
#         choices=ReasonCategory.to_choices(),
#         required=False,
#     )
#
#     restore = SubmitField("Restore")
#
#     update = SubmitField("Update")
#
#     discard = SubmitField("Discard")
#
#     def to_action(self) -> RecentChangesAction:
#         """Return a `RecentChangesAction` describing interaction with Lando-API."""
#         if self.update.data:
#             # Update is a PATCH with any changed attributes passed in the body.
#             return RecentChangesAction(
#                 method="PATCH",
#                 request_args={
#                     "json": build_update_json_body(
#                         self.reason.data, self.reason_category.data
#                     )
#                 },
#                 message="Status change updated.",
#             )
#
#         revert = 1 if self.restore.data else 0
#         message = f"Status change {'restored' if self.restore.data else 'discarded'}."
#
#         return RecentChangesAction(
#             method="DELETE",
#             request_args={"params": {"revert": revert}},
#             message=message,
#         )
#
#
# class TreeStatusLogUpdateForm(forms.Form):
#     """Modify a log entry."""
#
#     id = HiddenField("Id")
#
#     reason = StringField("Reason")
#
#     reason_category = SelectField(
#         "Reason Category",
#         choices=ReasonCategory.to_choices(),
#     )
