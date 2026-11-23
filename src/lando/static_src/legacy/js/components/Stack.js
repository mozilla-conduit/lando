"use strict";

// Label shown on the landing button when unacknowledged warnings block landing.
const ACKNOWLEDGE_WARNINGS_LABEL = "Acknowledge warnings to continue";

// Put the landing button into the state that requires the user to acknowledge
// warnings before landing can proceed.
function need_warnings_acknowledgements(button) {
    button.prop("disabled", true);
    button.removeClass("is-loading is-danger").addClass("is-warning");
    button.html(ACKNOWLEDGE_WARNINGS_LABEL);
}

// Submit the uplift modal's form as JSON when it names a `data-submit-url`, as it
// does on a pull request page, and show any errors the API returns in the modal.
function setup_pull_request_uplift_form() {
    var uplift_form = $(".uplift-request-modal form[data-submit-url]");
    if (!uplift_form.length) {
        return;
    }

    var submit_button = uplift_form.find(".uplift-request-submit");
    var submit_url = uplift_form.data("submit-url");
    var csrf_token = uplift_form.data("csrf-token");

    // The browser only fires `submit` once the form's own validation passes.
    uplift_form.on("submit", function (event) {
        event.preventDefault();
        hide_uplift_errors(uplift_form);
        submit_button.addClass("is-loading").prop("disabled", true);

        fetch(submit_url, {
            method: "POST",
            body: JSON.stringify(serialize_uplift_form(uplift_form)),
            headers: {
                Accept: "application/json",
                "Content-Type": "application/json",
                "X-CSRFToken": csrf_token,
            },
        })
            .then(async (response) => {
                if (response.status == 201) {
                    window.location.reload();
                    return;
                }

                var messages = ["An unknown error occurred."];
                if (response.status == 400) {
                    messages = uplift_error_messages(await response.json());
                }
                show_uplift_errors(uplift_form, messages);
                submit_button.removeClass("is-loading").prop("disabled", false);
            })
            .catch(() => {
                show_uplift_errors(uplift_form, ["An unknown error occurred."]);
                submit_button.removeClass("is-loading").prop("disabled", false);
            });
    });
}

// Collect the uplift form's fields into the JSON body the uplift API expects.
// `repositories` is a list, since several trains can be checked at once.
function serialize_uplift_form(uplift_form) {
    var data = { repositories: [] };
    for (var [name, value] of new FormData(uplift_form[0])) {
        if (name === "repositories") {
            data.repositories.push(value);
        } else {
            data[name] = value;
        }
    }
    return data;
}

// Turn an uplift API error response into messages, formatting field errors as
// `field: error` like the stack page's flash messages.
function uplift_error_messages(result) {
    if (result.error) {
        return [result.error];
    }

    var messages = [];
    for (var [field, field_errors] of Object.entries(result.errors || {})) {
        messages.push(`${field}: ${field_errors.join(", ")}`);
    }
    return messages.length ? messages : ["An unknown error occurred."];
}

function show_uplift_errors(uplift_form, messages) {
    var errors = uplift_form.find(".uplift-request-errors");
    var list = $("<ul>");
    for (var message of messages) {
        // Use `text` so error content is never interpreted as HTML.
        list.append($("<li>").text(message));
    }
    errors.empty().append(list).removeClass("is-hidden");

    // Errors sit at the top of the modal, which is scrolled to the submit button.
    uplift_form.find(".modal-card-body").scrollTop(0);
}

function hide_uplift_errors(uplift_form) {
    uplift_form.find(".uplift-request-errors").addClass("is-hidden").empty();
}

$.fn.stack = function () {
    return this.each(function () {
        let $stack = $(this);
        let $radio = $stack.find(".StackPage-revision-land-radio");

        $radio.on("click", (e) => {
            window.location.href = "/" + e.target.id;
            $radio.attr({ disabled: true });
        });

        // Show the uplift request form modal when the "Request Uplift" button is clicked.
        // On an uplift revision it is a link in the "More" menu, so keep it from
        // following its `#` target.
        $(".uplift-request-open").on("click", function (e) {
            e.preventDefault();
            $(".uplift-request-modal").addClass("is-active");
        });

        // Close the "More" menu, and stop listening for the click that closes it.
        function closeMoreActions() {
            $(".StackPage-moreActions.is-active")
                .removeClass("is-active")
                .find(".StackPage-moreActions-trigger")
                .attr("aria-expanded", "false");
            $(document).off("click.StackPage-moreActions");
        }

        // Toggle the "More" menu holding the actions this revision rarely needs.
        // Only an open menu listens for clicks elsewhere on the page.
        $(".StackPage-moreActions-trigger").on("click", function (e) {
            e.stopPropagation();
            let $menu = $(this).closest(".StackPage-moreActions");
            if ($menu.hasClass("is-active")) {
                closeMoreActions();
                return;
            }
            $menu.addClass("is-active");
            $(this).attr("aria-expanded", "true");
            $(document).on("click.StackPage-moreActions", closeMoreActions);
        });
        $(".uplift-request-close").on("click", function () {
            $(".uplift-request-modal").removeClass("is-active");
        });

        // Open the assessment modal named by the clicked button. The page renders
        // one modal per assessment it can edit, so the id selects between them.
        $(".assessment-modal-open").on("click", function () {
            let modalId = $(this).data("assessment-modal");
            $(`.uplift-assessment-modal[data-assessment-modal="${modalId}"]`).addClass(
                "is-active",
            );
        });
        $(".assessment-modal-close").on("click", function () {
            $(this).closest(".uplift-assessment-modal").removeClass("is-active");
        });

        // Toggle `required` on the "steps to reproduce" textarea based on
        // whether "Needs manual QE testing?" is set to "Yes".
        function updateQeStepsRequired(form) {
            let selectedRadio = form.find(
                'input[name="needs_manual_qe_testing"]:checked',
            );
            let stepsTextarea = form.find(
                'textarea[name="qe_testing_reproduction_steps"]',
            );
            stepsTextarea.prop("required", selectedRadio.val() === "yes");
        }

        $('input[name="needs_manual_qe_testing"]').on("change", function () {
            updateQeStepsRequired($(this).closest("form"));
        });

        // Set the initial `required` state for any pre-populated forms.
        $('input[name="needs_manual_qe_testing"]')
            .closest("form")
            .each(function () {
                updateQeStepsRequired($(this));
            });

        // Require at least one repository checkbox to be selected in the uplift
        // request form. Since `required` on `CheckboxSelectMultiple` would require
        // all checkboxes to be checked, we use `setCustomValidity` instead.
        let repositoryCheckboxes = $('input[name="repositories"]');

        function updateRepositoryValidity() {
            let isAnyChecked = repositoryCheckboxes.is(":checked");
            let validityMessage = isAnyChecked
                ? ""
                : "Please select at least one repository.";
            repositoryCheckboxes.each(function () {
                this.setCustomValidity(validityMessage);
            });
        }

        repositoryCheckboxes.on("change", updateRepositoryValidity);
        updateRepositoryValidity();

        // Simple check for time being. If the button exists, assume this is a pull request page.
        // This should be cleaned up as part of bug 1995754.
        var is_pull_request_page = Boolean($("button.post-landing-job").length);
        if (is_pull_request_page) {
            var saved_landing_state = null;
            var pull_request_button = $("button.post-landing-job");

            // The uplift modal is only rendered for logged-in users, so set it up
            // before the anonymous check below returns early.
            setup_pull_request_uplift_form();
            $("#save-edit-pr").prop("disabled", true);
            $("#acknowledge-warnings").on("click", function () {
                if (this.checked) {
                    pull_request_button.prop("disabled", false);
                    pull_request_button.html("Request landing despite warnings");
                } else {
                    need_warnings_acknowledgements(pull_request_button);
                }
            });

            if (pull_request_button.data("anonymous") == 1) {
                pull_request_button.prop("disabled", true);
                pull_request_button.removeClass("is-loading").addClass("is-danger");
                pull_request_button.html("Log in to request landing");
                return;
            }

            var pull_number = pull_request_button.data("pull-number");
            var head_sha = pull_request_button.data("head-sha");
            var repo_name = pull_request_button.data("repo-name");
            var csrf_token = pull_request_button.data("csrf-token");
            var old_warnings = [];

            fetch(`/api/pulls/${repo_name}/${pull_number}/landing_jobs`, {
                method: "GET",
                headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrf_token,
                },
            }).then(async (response) => {
                if (response.status == 200) {
                    var result = await response.json();
                    if (result.status == "landed") {
                        var message = "Pull request landed";
                        pull_request_button.prop("disabled", true);
                        pull_request_button
                            .removeClass("is-loading")
                            .addClass("is-info");
                        pull_request_button.html(message);
                        $("#blockers").html(`${message}.`);
                        $("#warnings").html(`${message}.`);
                    } else if (
                        ["created", "submitted", "in_progress", "deferred"].includes(
                            result.status,
                        )
                    ) {
                        var message = "Landing job submitted";
                        pull_request_button.prop("disabled", true);
                        pull_request_button.removeClass("is-loading has-text-white");
                        pull_request_button.html(message);
                        $("#blockers").html(`${message}.`);
                        $("#warnings").html(`${message}.`);
                    } else {
                        fetch(`/api/pulls/${repo_name}/${pull_number}/checks`, {
                            method: "GET",
                        }).then(async (response) => {
                            $("#save-edit-pr").prop("disabled", false);
                            if (response.status == 200) {
                                var result = await response.json();
                                var blockers = result.blockers;
                                var warnings = result.warnings;
                                old_warnings = warnings;
                                var has_blockers = blockers.length !== 0;
                                var has_warnings = warnings.length !== 0;
                                var success_placeholder = `<li><span class="fa-li has-text-success"><i class="fa fa-check"></i></span>None found.</li>`;

                                if (!has_blockers) {
                                    $("#blockers").html(success_placeholder);
                                } else {
                                    $("#blockers").html("");
                                    for (var blocker of blockers) {
                                        $("#blockers").append(
                                            `<li><span class="fa-li has-text-danger"><i class="fa fa-ban"></i></span>${blocker}</li>`,
                                        );
                                    }
                                }

                                if (!has_warnings) {
                                    $("#warnings").html(success_placeholder);
                                } else {
                                    $("#warnings").html("");
                                    for (var warning of warnings) {
                                        $("#warnings").append(
                                            `<li><span class="fa-li has-text-warning"><i class="fa fa-warning"></i></span>${warning}</li>`,
                                        );
                                    }
                                }

                                if (!has_blockers && !has_warnings) {
                                    pull_request_button.prop("disabled", false);
                                    pull_request_button
                                        .removeClass("is-loading")
                                        .addClass("is-success");
                                    pull_request_button.html("Request landing");
                                } else if (has_blockers) {
                                    pull_request_button.prop("disabled", true);
                                    pull_request_button
                                        .removeClass("is-loading")
                                        .addClass("is-danger");
                                    pull_request_button.html("Landing is blocked");
                                } else if (has_warnings) {
                                    $(".acknowledge-warnings-section").show();
                                    need_warnings_acknowledgements(pull_request_button);
                                }
                                saved_landing_state = {
                                    html: pull_request_button.html(),
                                    disabled: pull_request_button.prop("disabled"),
                                    classes: pull_request_button.attr("class"),
                                    ack_section_visible: $(
                                        ".acknowledge-warnings-section",
                                    ).is(":visible"),
                                    ack_checked: $("#acknowledge-warnings").prop(
                                        "checked",
                                    ),
                                };
                            } else {
                                // TODO: handle this case. See bug 1996000.
                            }
                        });
                    }
                } else {
                    // TODO: handle this case. See bug 1996000.
                }
            });

            pull_request_button.on("click", function (e) {
                pull_request_button.addClass("is-loading");
                fetch(`/api/pulls/${repo_name}/${pull_number}/landing_jobs`, {
                    method: "POST",
                    body: JSON.stringify({
                        head_sha: head_sha,
                        old_warnings: old_warnings,
                    }),
                    headers: {
                        Accept: "application/json",
                        "Content-Type": "application/json",
                        "X-CSRFToken": csrf_token,
                    },
                }).then(async (response) => {
                    if (response.status == 201) {
                        window.location.reload();
                    } else if (response.status == 400) {
                        var result = await response.json();
                        pull_request_button
                            .removeClass("is-danger")
                            .removeClass("is-loading")
                            .addClass("is-warning");
                        pull_request_button.prop("disabled", true);

                        if ("new_warnings" in result) {
                            $("#warnings-mismatch").append(
                                `<li>${result["errors"]["warnings"]}</li>`,
                            );
                            $("#warnings").empty();
                            $("#acknowledge-warnings").prop("checked", false);
                            need_warnings_acknowledgements(pull_request_button);
                            var new_warnings = result["new_warnings"];
                            for (var warning of new_warnings) {
                                $("#warnings").append(
                                    `<li><span class="fa-li has-text-warning"><i class="fa fa-warning"></i></span>${warning}</li>`,
                                );
                            }
                        } else {
                            pull_request_button.html("Could not create landing job");
                        }
                    } else {
                        pull_request_button.prop("disabled", true);
                        pull_request_button
                            .removeClass("is-danger")
                            .removeClass("is-loading")
                            .addClass("is-warning");
                        pull_request_button.html("An unknown error occurred");
                    }
                });
            });

            $("#save-edit-pr").on("click", function (e) {
                var save_edit_pr_button = $(this);
                var pull_request_button = $("#post-landing-job");

                pull_request_button.prop("disabled", true);
                pull_request_button.addClass("is-danger");
                pull_request_button.html("Landing is blocked");
                $(".acknowledge-warnings-section").hide();

                if (save_edit_pr_button.attr("data-mode") === "edit") {
                    var body = $("#commit-body").val();
                    var title = $("#commit-title").val();
                    save_edit_pr_button.prop("disabled", true);
                    save_edit_pr_button.addClass("is-loading");
                    $("#cancel-edit-pr").prop("disabled", true);
                    $("#commit-title").prop("disabled", true);
                    $("#commit-body").prop("disabled", true);
                    fetch(`/api/pulls/${repo_name}/${pull_number}`, {
                        method: "PUT",
                        body: JSON.stringify({ body: body, title: title }),
                        headers: {
                            Accept: "application/json",
                            "Content-Type": "application/json",
                            "X-CSRFToken": csrf_token,
                        },
                    }).then(async (response) => {
                        if (response.status === 204) {
                            $("#commit-title-error").text("");
                            $("#commit-body-error").text("");
                            $("#commit-title").removeClass("is-danger");
                            $("#commit-body").removeClass("is-danger");
                            window.location.reload();
                        } else {
                            if (response.status >= 400 && response.status < 500) {
                                var result = await response.json();
                                save_edit_pr_button.removeClass("is-loading");
                                $("#cancel-edit-pr").prop("disabled", false);
                                if (result.title) {
                                    $("#commit-title-error").text(result.title);
                                    $("#commit-title-error").addClass("help is-danger");
                                    $("#commit-title").prop("disabled", false);
                                    $("#commit-body").prop("disabled", false);
                                    $("#commit-title").addClass("is-danger");
                                }
                                if (result.body) {
                                    $("#commit-body-error").text(result.body);
                                    $("#commit-body-error").addClass("help is-danger");
                                    $("#commit-title").prop("disabled", false);
                                    $("#commit-body").prop("disabled", false);
                                    $("#commit-body").addClass("is-danger");
                                }
                            } else {
                                save_edit_pr_button
                                    .prop("disabled", true)
                                    .removeClass("is-danger is-loading")
                                    .addClass("is-warning")
                                    .text("An unknown error occurred");
                            }
                        }
                    });
                    return;
                }

                const pTitle = $("#commit-title");
                const pBody = $("#commit-body");
                const textareaTitle = $("<textarea>")
                    .attr("id", "commit-title")
                    .addClass("textarea")
                    .val(pTitle.text())
                    .attr("data-original", pTitle.text());
                const textareaBody = $("<textarea>")
                    .attr("id", "commit-body")
                    .addClass("textarea")
                    .val(pBody.text())
                    .attr("data-original", pBody.text());

                pTitle.replaceWith(textareaTitle);
                pBody.replaceWith(textareaBody);

                save_edit_pr_button
                    .attr("data-mode", "edit")
                    .text("Save Commit Message");
                $("#cancel-edit-pr").removeClass("is-hidden");
                $("#commit-title").focus();
                $("#post-landing-job").prop("disabled", true);

                textareaTitle.on("input", function () {
                    $("#commit-title").removeClass("is-danger");
                    $("#commit-title-error").text("");
                    save_edit_pr_button.prop("disabled", false);
                });

                textareaBody.on("input", function () {
                    $("#commit-body").removeClass("is-danger");
                    $("#commit-body-error").text("");
                    save_edit_pr_button.prop("disabled", false);
                });
            });

            $("#cancel-edit-pr").on("click", function (e) {
                var pull_request_button = $("#post-landing-job");
                if (saved_landing_state) {
                    pull_request_button.html(saved_landing_state.html);
                    pull_request_button.prop("disabled", saved_landing_state.disabled);
                    pull_request_button.attr("class", saved_landing_state.classes);
                    $(".acknowledge-warnings-section").toggle(
                        saved_landing_state.ack_section_visible,
                    );
                    $("#acknowledge-warnings").prop(
                        "checked",
                        saved_landing_state.ack_checked,
                    );
                }
                const pTitle = document.createElement("p");
                const pBody = document.createElement("p");
                const textareaTitle = $("#commit-title");
                const textareaBody = $("#commit-body");
                pTitle.textContent = textareaTitle.data("original");
                pBody.textContent = textareaBody.data("original");
                pTitle.id = "commit-title";
                pBody.id = "commit-body";
                textareaTitle.replaceWith(pTitle);
                textareaBody.replaceWith(pBody);

                const save_edit_pr_button = $("#save-edit-pr");
                save_edit_pr_button.prop("disabled", false);
                save_edit_pr_button
                    .attr("data-mode", "saved")
                    .text("Edit Commit Message");

                $("#commit-title-error").text("");
                $("#commit-body-error").text("");
                $("#cancel-edit-pr").addClass("is-hidden");
            });
        }
    });
};
