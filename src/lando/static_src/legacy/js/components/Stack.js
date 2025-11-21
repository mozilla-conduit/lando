'use strict';

$.fn.stack = function() {
  return this.each(function() {
    let $stack = $(this);
    let $radio = $stack.find('.StackPage-revision-land-radio');

    $radio.on('click', (e) => {
      window.location.href = '/' + e.target.id;
      $radio.attr({'disabled': true});
    });

    // Show the uplift request form modal when the "Request Uplift" button is clicked.
    $('.uplift-request-open').on("click", function () {
        $('.uplift-request-modal').addClass("is-active");
    });
    $('.uplift-request-close').on("click", function () {
        $('.uplift-request-modal').removeClass("is-active");
    });

    // Show the assessment edit form modal when the "Request Uplift" button is clicked.
    $('.edit-assessment-open').on("click", function () {
        $('.uplift-assessment-edit-modal').addClass("is-active");
    });
    $('.edit-assessment-close').on("click", function () {
        $('.uplift-assessment-edit-modal').removeClass("is-active");
    });

    // Show the modal to link an existing uplift assessment.
    $('.link-assessment-open').on("click", function () {
        $('.uplift-assessment-link-modal').addClass("is-active");
    });
    $('.link-assessment-close').on("click", function () {
        $('.uplift-assessment-link-modal').removeClass("is-active");
    });

    // Simple check for time being. If the button exists, assume this is a pull request page.
    // This should be cleaned up as part of bug 1995754.
    var is_pull_request_page = Boolean($('button.post-landing-job').length);
    if (is_pull_request_page) {

        $('#acknowledge-warnings').on("click", function () {
            if (this.checked) {
                pull_request_button.prop("disabled", false);
                pull_request_button.html("Request landing despite warnings");
            } else {
                pull_request_button.prop("disabled", true);
                pull_request_button.html("Acknowledge warnings to continue");
            }
        });

        var pull_request_button = $('button.post-landing-job');
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

        fetch(`/api/pulls/${repo_name}/${pull_number}/landing_jobs`, {
            method: 'GET',
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'X-CSRFToken': csrf_token
            },
        }).then(async response => {
            if (response.status == 200) {
                var result = await response.json();
                if (result.status == "landed") {
                    pull_request_button.prop("disabled", true);
                    pull_request_button.removeClass("is-loading").addClass("is-danger");
                    pull_request_button.html("Pull request landed");
                } else if (["created", "submitted", "in progress"].includes(result.status)) {
                    pull_request_button.prop("disabled", true);
                    pull_request_button.removeClass("is-loading");
                    pull_request_button.html("Landing job submitted");
                } else {
                    fetch(`/api/pulls/${repo_name}/${pull_number}/checks`, {
                        method: 'GET',
                    }).then(async response => {
                        if (response.status == 200) {
                            var result = await response.json();
                            var blockers = result.blockers;
                            var warnings = result.warnings;

                            var has_blockers = blockers.length !== 0;
                            var has_warnings = warnings.length !== 0;

                            if (!has_blockers) {
                                $("#blockers").html("None found.");
                            } else {
                                $("#blockers").html("");
                                for (var blocker of blockers) {
                                    $("#blockers").append(`<li>${blocker}</li>`);
                                }
                            }

                            if (!has_warnings) {
                                $("#warnings").html("None found.");
                            } else {
                                $("#warnings").html("");
                                for (var warning of warnings) {
                                    $("#warnings").append(`<li>${warning}</li>`);
                                }
                            }

                            if (!has_blockers && !has_warnings) {
                                pull_request_button.prop("disabled", false);
                                pull_request_button.removeClass("is-loading").addClass("is-success");;
                                pull_request_button.html("Request landing");
                            } else if (has_blockers) {
                                pull_request_button.prop("disabled", true);
                                pull_request_button.removeClass("is-loading").addClass("is-danger");
                                pull_request_button.html("Landing is blocked");
                            } else if (has_warnings) {
                                $('.acknowledge-warnings-section').show();
                                pull_request_button.prop("disabled", true);
                                pull_request_button.removeClass("is-loading").addClass("is-warning");
                                pull_request_button.html("Acknowledge warnings to continue");
                            }
                        } else {
                            // TODO: handle this case. See bug 1996000.
                        }
                    });
                }
            } else {
                // TODO: handle this case. See bug 1996000.
            }
        });

        pull_request_button.on('click', function(e) {
            pull_request_button.addClass("is-loading");
            fetch(`/api/pulls/${repo_name}/${pull_number}/landing_jobs`, {
                method: 'POST',
                body: JSON.stringify({"head_sha": head_sha}),
                headers: {
                    'Accept': 'application/json',
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrf_token
                },
            }).then(response => {
                if (response.status == 201) {
                    window.location.reload();
                } else if (response.status == 400) {
                    pull_request_button.prop("disabled", true);
                    pull_request_button.removeClass("is-danger").removeClass("is-loading").addClass("is-warning");
                    pull_request_button.html("Could not create landing job");
                } else {
                    pull_request_button.prop("disabled", true);
                    pull_request_button.removeClass("is-danger").removeClass("is-loading").addClass("is-warning");
                    pull_request_button.html("An unknown error occurred");
                }
            });
        });
    };
  });
};
