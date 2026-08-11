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
$.fn.gh_stack = function () {    
        return this.each(function () {
        let $gh_stack = $(this);
                    // Simple check for time being. If the button exists, assume this is a pull request page.
        // This should be cleaned up as part of bug 1995754.
        var request_land_button = $("button.post-landing-job");
        var head_sha = request_land_button.data("head-sha");
        var repo_name = request_land_button.data("repo-name");
        var csrf_token = request_land_button.data("csrf-token");
        if (document.getElementById("pull-request-page")) {
            var saved_landing_state = null;
            $("#save-edit-pr").prop("disabled", true);
            $("#acknowledge-warnings").on("click", function () {
                if (this.checked) {
                    request_land_button.prop("disabled", false);
                    request_land_button.html("Request landing despite warnings");
                } else {
                    need_warnings_acknowledgements(request_land_button);
                }
            });

            if (request_land_button.data("anonymous") == 1) {
                request_land_button.prop("disabled", true);
                request_land_button.removeClass("is-loading").addClass("is-danger");
                request_land_button.html("Log in to request landing");
                return;
            }

            var pull_number = request_land_button.data("pull-number");
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
                        request_land_button.prop("disabled", true);
                        request_land_button
                            .removeClass("is-loading")
                            .addClass("is-info");
                        request_land_button.html(message);
                        $("#blockers").html(`${message}.`);
                        $("#warnings").html(`${message}.`);
                    } else if (
                        ["created", "submitted", "in_progress", "deferred"].includes(
                            result.status,
                        )
                    ) {
                        var message = "Landing job submitted";
                        request_land_button.prop("disabled", true);
                        request_land_button.removeClass("is-loading has-text-white");
                        request_land_button.html(message);
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
                                    request_land_button.prop("disabled", false);
                                    request_land_button
                                        .removeClass("is-loading")
                                        .addClass("is-success");
                                    request_land_button.html("Request landing");
                                } else if (has_blockers) {
                                    request_land_button.prop("disabled", true);
                                    request_land_button
                                        .removeClass("is-loading")
                                        .addClass("is-danger");
                                    request_land_button.html("Landing is blocked");
                                } else if (has_warnings) {
                                    $(".acknowledge-warnings-section").show();
                                    need_warnings_acknowledgements(request_land_button);
                                }
                                saved_landing_state = {
                                    html: request_land_button.html(),
                                    disabled: request_land_button.prop("disabled"),
                                    classes: request_land_button.attr("class"),
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

            request_land_button.on("click", function (e) {
                request_land_button.addClass("is-loading");
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
                        request_land_button
                            .removeClass("is-danger")
                            .removeClass("is-loading")
                            .addClass("is-warning");
                        request_land_button.prop("disabled", true);

                        if ("new_warnings" in result) {
                            $("#warnings-mismatch").append(
                                `<li>${result["errors"]["warnings"]}</li>`,
                            );
                            $("#warnings").empty();
                            $("#acknowledge-warnings").prop("checked", false);
                            need_warnings_acknowledgements(request_land_button);
                            var new_warnings = result["new_warnings"];
                            for (var warning of new_warnings) {
                                $("#warnings").append(
                                    `<li><span class="fa-li has-text-warning"><i class="fa fa-warning"></i></span>${warning}</li>`,
                                );
                            }
                        } else {
                            request_land_button.html("Could not create landing job");
                        }
                    } else {
                        request_land_button.prop("disabled", true);
                        request_land_button
                            .removeClass("is-danger")
                            .removeClass("is-loading")
                            .addClass("is-warning");
                        request_land_button.html("An unknown error occurred");
                    }
                });
            });

            $("#save-edit-pr").on("click", function (e) {
                var save_edit_pr_button = $(this);
                var request_land_button = $("#post-landing-job");

                request_land_button.prop("disabled", true);
                request_land_button.addClass("is-danger");
                request_land_button.html("Landing is blocked");
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
                if (saved_landing_state) {
                    request_land_button.html(saved_landing_state.html);
                    request_land_button.prop("disabled", saved_landing_state.disabled);
                    request_land_button.attr("class", saved_landing_state.classes);
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

        if (document.getElementById("stack-page")) {
            var stack_number = request_land_button.data("stack-number");
            var repo_url = request_land_button.data("repo-url");
            fetch(`/api/stacks/${repo_name}/${stack_number}/checks`, {
                method: "GET",
            }).then(async (response) => {
                if (response.status == 200) {
                    var result = await response.json();
                    var blockers = result["blockers"];
                    var warnings = result["warnings"];
                    var has_blockers = blockers.length !== 0;
                    var has_warnings = warnings.length !== 0;

                    var success_placeholder = `<li><span class="fa-li has-text-success"><i class="fa fa-check"></i></span>None found.</li>`;

                    if (!has_blockers) {
                        $("#blockers").html(success_placeholder);
                    } else {
                        $("#blockers").html("");

                        $("#blockers").append(
                            `<ul>
                            ${Object.entries(blockers)
                                .map(
                                    ([blocker, numbers]) =>
                                        `<li>${blocker}: ${numbers
                                            .map(
                                                (number) =>
                                                    `<a href="${repo_url}/pull/${number}">${number}</a>`,
                                            )
                                            .join(", ")}</li>`,
                                )
                                .join("")}
                        </ul>`,
                        );
                    }

                    if (!has_warnings) {
                        $("#warnings").html(success_placeholder);
                    } else {
                        $("#warnings").html("");
                        $("#warnings").append(
                            `<ul>
                                ${Object.entries(warnings)
                                    .map(
                                        ([warning, numbers]) =>
                                            `<li>${warning}: ${numbers.map((number) => `<a href="${repo_url}/pull/${number}">${number}</a>`).join(", ")}</li>`,
                                    )
                                    .join("")}
                            </ul>`,
                        );
                    }

                    if (!has_blockers && !has_warnings) {
                    request_land_button.prop("disabled", false);
                    request_land_button
                        .removeClass("is-loading")
                        .addClass("is-success");
                    request_land_button.html("Request landing");
                    } else if (has_blockers) {
                        request_land_button.prop("disabled", true);
                        request_land_button
                            .removeClass("is-loading")
                            .addClass("is-danger");
                        request_land_button.html("Landing is blocked");
                    } else if (has_warnings) {
                        $(".acknowledge-warnings-section").show();
                        need_warnings_acknowledgements(request_land_button);
                    }
                }
                

            });

            request_land_button.on("click", function (e) {
                e.preventDefault();
                request_land_button.addClass("is-loading");
                fetch(`/api/stacks/${repo_name}/${stack_number}/landing_jobs`, {
                    method: "POST",
                    body: JSON.stringify({
                        old_warnings: [],
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
                        request_land_button
                            .removeClass("is-danger")
                            .removeClass("is-loading")
                            .addClass("is-warning");
                        request_land_button.prop("disabled", true);
                    }
                });
            });
        }
    });
};
