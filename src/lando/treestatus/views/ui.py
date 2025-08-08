import logging

from django.contrib import messages
from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.views.decorators.http import require_POST

from lando.treestatus.forms import (
    TreeStatusLogUpdateForm,
    TreeStatusNewTreeForm,
    TreeStatusRecentChangesForm,
    TreeStatusUpdateTreesForm,
)
from lando.treestatus.models import (
    CombinedTree,
    ReasonCategory,
    StatusChange,
    TreeCategory,
    TreeStatus,
)
from lando.treestatus.views.api import (
    ProblemException,
    apply_log_and_stack_update,
    apply_status_change_update,
    apply_tree_updates,
    create_new_tree,
    get_combined_trees,
    get_tree_logs_by_name,
    revert_status_change,
)

logger = logging.getLogger(__name__)


def build_recent_changes_stack(
    recent_changes_data: list[dict],
) -> list[tuple[TreeStatusRecentChangesForm, dict]]:
    """Build the recent changes stack object."""
    recent_changes_stack = []
    for change in recent_changes_data:
        form = TreeStatusRecentChangesForm(
            initial={
                "id": change["id"],
                "reason": change["reason"],
                "reason_category": (
                    change["trees"][0]["last_state"]["current_tags"][0]
                    if change["trees"][0]["last_state"]["current_tags"]
                    else ReasonCategory.NO_CATEGORY.value
                ),
            },
        )

        recent_changes_stack.append((form, change))

    return recent_changes_stack


def view_treestatus_dashboard(request: WSGIRequest) -> HttpResponse:
    """Display the status of all the current trees.

    This view is the main landing page for Treestatus. The view is a list of all trees
    and their current statuses. The view of all trees is a form where each tree can be
    selected, and clicking "Update trees" opens a modal which presents the tree updating
    form.
    """
    combined_trees = get_combined_trees()
    sorted_combined_trees = sorted(combined_trees, key=TreeCategory.sort_trees)
    sorted_tree_names = [tree.tree for tree in sorted_combined_trees]
    combined_trees_mapping = {tree.tree: tree for tree in sorted_combined_trees}

    user_can_update_trees = request.user.is_authenticated and request.user.has_perm(
        "treestatus.change_tree"
    )

    if request.method == "POST":
        return handle_treestatus_update_post(
            request, combined_trees_mapping, user_can_update_trees
        )

    # Populate initial choices for the form.
    update_trees_form = TreeStatusUpdateTreesForm.with_tree_names(
        list(combined_trees_mapping.keys()), initial={"trees": sorted_tree_names}
    )

    recent_changes_data = StatusChange.get_stack()
    recent_changes_stack = build_recent_changes_stack(recent_changes_data)

    return TemplateResponse(
        request=request,
        template="treestatus/trees.html",
        context={
            "recent_changes_stack": recent_changes_stack,
            "trees": combined_trees_mapping,
            "treestatus_update_trees_form": update_trees_form,
            "is_treestatus_user": user_can_update_trees,
        },
    )


def handle_treestatus_update_post(
    request: WSGIRequest,
    combined_trees_mapping: dict[str, CombinedTree],
    user_can_update_trees: bool,
) -> HttpResponse:
    """Handler for the tree status updating form.

    This function handles form submission for the status updating form. Validate
    the form submission update trees, redirecting to the main Treestatus page on
    success. Display an error message and return to the form if the status updating
    rules were broken.
    """
    update_trees_form = TreeStatusUpdateTreesForm.with_tree_names(
        list(combined_trees_mapping.keys()), data=request.POST
    )

    if not user_can_update_trees:
        messages.add_message(
            request,
            messages.ERROR,
            "You do not have permission to update tree statuses.",
        )
        return redirect("treestatus-dashboard")

    if not update_trees_form.is_valid():
        # Display form errors as flash messages.
        for field_name, field_errors in update_trees_form.errors.items():
            for error in field_errors:
                message = f"{field_name}: {error}"
                messages.add_message(request, messages.ERROR, message)

        return redirect("treestatus-dashboard")

    logger.info("Requesting tree status update.")

    tags = []
    reason_category = update_trees_form.cleaned_data.get("reason_category")
    if reason_category:
        tags.append(reason_category.value)

    try:
        apply_tree_updates(
            user_id=request.user.email,
            trees=update_trees_form.cleaned_data["trees"],
            status=update_trees_form.cleaned_data.get("status"),
            reason=update_trees_form.cleaned_data.get("reason"),
            tags=tags,
            remember=update_trees_form.cleaned_data.get("remember", False),
            message_of_the_day=update_trees_form.cleaned_data.get(
                "message_of_the_day", ""
            ),
        )
    except ProblemException as exc:
        messages.add_message(
            request, messages.ERROR, f"Error updating trees: {exc.problem.detail}"
        )
    else:
        message = "Tree statuses updated successfully."
        logger.info(message)
        messages.add_message(request, messages.SUCCESS, message)

    return redirect("treestatus-dashboard")


def view_new_tree(request: WSGIRequest) -> HttpResponse:
    """View for the new tree form."""
    user_can_update_trees = request.user.is_authenticated and request.user.has_perm(
        "treestatus.change_tree"
    )

    if request.method == "POST":
        return handle_new_tree_form(request, user_can_update_trees)

    treestatus_new_tree_form = TreeStatusNewTreeForm()

    recent_changes_data = StatusChange.get_stack()
    recent_changes_stack = build_recent_changes_stack(recent_changes_data)

    return TemplateResponse(
        request=request,
        template="treestatus/new_tree.html",
        context={
            "treestatus_new_tree_form": treestatus_new_tree_form,
            "recent_changes_stack": recent_changes_stack,
        },
    )


def handle_new_tree_form(
    request: WSGIRequest, user_can_update_trees: bool
) -> HttpResponse:
    """Handler for the new tree form."""
    if not user_can_update_trees:
        messages.add_message(
            request, messages.ERROR, "Authentication is required to create new trees."
        )
        return redirect("treestatus-dashboard")

    form = TreeStatusNewTreeForm(data=request.POST)
    if not form.is_valid():
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.add_message(request, messages.ERROR, error)
        return redirect("treestatus-new-tree")

    # Retrieve data from the form.
    tree = form.cleaned_data["tree"]
    category = form.cleaned_data["category"]

    logger.info(f"Requesting new tree {tree}.")

    try:
        create_new_tree(
            user_id=request.user.email,
            tree=tree,
            category=category,
            status=TreeStatus.OPEN,
        )
    except ProblemException as exc:
        logger.info(f"Could not create new tree {tree}.")

        if not exc.problem.detail:
            raise exc

        messages.add_message(
            request,
            messages.ERROR,
            f"Could not create new tree: {exc.problem.detail}. Please try again later.",
        )
        return redirect("treestatus-new-tree")

    message = f"New tree {tree} created successfully."
    logger.info(message)
    messages.add_message(request, messages.SUCCESS, message)

    return redirect("treestatus-dashboard")


def view_tree_logs(request: WSGIRequest, tree: str) -> HttpResponse:
    """Display the log of statuses for an individual tree."""
    try:
        logs = get_tree_logs_by_name(tree_name=tree, limit_logs=True)
    except ProblemException as exc:
        logger.info(exc.problem.detail)
        messages.add_message(request, messages.ERROR, exc.problem.detail)
        return redirect("treestatus-dashboard")

    current_log = logs[0]

    logs_forms = [
        (
            TreeStatusLogUpdateForm(
                initial={
                    "reason": log["reason"],
                    "reason_category": (
                        log["tags"][0]
                        if log["tags"]
                        else ReasonCategory.NO_CATEGORY.value
                    ),
                }
            ),
            log,
        )
        for log in logs
    ]

    recent_changes_data = StatusChange.get_stack()
    recent_changes_stack = build_recent_changes_stack(recent_changes_data)

    return TemplateResponse(
        request=request,
        template="treestatus/log.html",
        context={
            "current_log": current_log,
            "logs": logs_forms,
            "recent_changes_stack": recent_changes_stack,
            "tree": tree,
        },
    )


@require_POST
def handle_update_change(request: WSGIRequest, id: int) -> HttpResponse:
    """Handler for stack updates.

    This function handles form submissions for updates to entries in the recent changes
    stack. This includes pressing the "restore" or "discard" buttons, as well as updates
    to the reason and reason category after pressing "edit" and "update".
    """
    user_can_update_trees = request.user.is_authenticated and request.user.has_perm(
        "treestatus.change_tree"
    )

    if not user_can_update_trees:
        messages.add_message(
            request,
            messages.ERROR,
            "Authentication is required to update stack entries.",
        )
        return redirect("treestatus-dashboard")

    recent_changes_form = TreeStatusRecentChangesForm(data=request.POST)

    if not recent_changes_form.is_valid():
        # Display form errors as flash messages.
        for field_name, field_errors in recent_changes_form.errors.items():
            for error in field_errors:
                message = f"{field_name}: {error}"
                messages.add_message(request, messages.ERROR, message)
        return redirect("treestatus-dashboard")

    action = request.POST.get("action")
    if not action or action not in {"discard", "restore", "update"}:
        message = f"Action was not an expected value: {action}"
        logger.error(message)
        messages.add_message(request, messages.ERROR, message)
        return redirect("treestatus-dashboard")

    logger.info(f"Requesting {action} stack update for stack id {id}.")

    if action == "update":
        reason = recent_changes_form.cleaned_data["reason"]
        reason_category = recent_changes_form.cleaned_data["reason_category"]
        tags = [reason_category] if reason_category else []

        try:
            apply_status_change_update(id, tags=tags, reason=reason)
        except ProblemException as exc:
            messages.add_message(request, messages.ERROR, exc.problem.detail)
            logger.exception(exc.problem.detail)
        else:
            messages.add_message(request, messages.SUCCESS, "Stack entry updated.")

        return redirect("treestatus-dashboard")

    revert = action == "restore"

    try:
        revert_status_change(id, request.user.email, revert=revert)
    except ProblemException as exc:
        message = (
            f"Could not modify stack entry {id}: {exc.problem.detail} "
            "Please try again later."
        )
        logger.info(message)

        messages.add_message(
            request,
            messages.ERROR,
            message,
        )
    else:
        message = f"Stack entry {id} updated."
        logger.info(message)
        messages.add_message(request, messages.SUCCESS, message)

    return redirect("treestatus-dashboard")


@require_POST
def handle_update_log(request: WSGIRequest, id: int) -> HttpResponse:
    """Handler for log updates.

    This function handles form submissions for updates to individual log entries
    in the per-tree log view.
    """
    user_can_update_trees = request.user.is_authenticated and request.user.has_perm(
        "treestatus.change_tree"
    )

    if not user_can_update_trees:
        messages.add_message(
            request, messages.ERROR, "Authentication is required to update log entries."
        )
        return redirect("treestatus-dashboard")

    log_update_form = TreeStatusLogUpdateForm(data=request.POST)

    if not log_update_form.is_valid():
        # Display form errors as flash messages.
        for field_name, field_errors in log_update_form.errors.items():
            for error in field_errors:
                message = f"{field_name}: {error}"
                messages.add_message(request, messages.ERROR, message)

        return redirect("treestatus-dashboard")

    reason = log_update_form.cleaned_data["reason"]
    reason_category = log_update_form.cleaned_data["reason_category"]

    tags = [reason_category] if reason_category else []

    logger.info(f"Requesting log update for log id {id}.")

    try:
        apply_log_and_stack_update(log_id=id, reason=reason, tags=tags)
    except ProblemException as exc:
        logger.info(f"Log entry {id} failed to update.")

        if not exc.problem.detail:
            raise exc

        messages.add_message(
            request,
            messages.ERROR,
            f"Could not modify log entry: {exc.problem.detail}. Please try again later.",
        )
    else:
        logger.info(f"Log entry {id} updated.")
        messages.add_message(request, messages.SUCCESS, "Log entry updated.")

    return redirect("treestatus-dashboard")
