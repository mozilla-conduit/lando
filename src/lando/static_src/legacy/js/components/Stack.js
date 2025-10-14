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


    var landing_button = $('button.post-landing-job');
    var pull_number = landing_button.data("pull-number");
    var head_sha = landing_button.data("head-sha");
    var repo_name = landing_button.data("repo-name");
    var csrf_token = landing_button.data("csrf-token");

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
              landing_button.prop("disabled", true);
              landing_button.removeClass("is-loading").addClass("is-danger");
              landing_button.html("Pull request landed");
          } else if (["created", "submitted", "in progress"].includes(result.status)) {
              landing_button.prop("disabled", true);
              landing_button.removeClass("is-loading");
              // TODO: allow cancelling job in this case.
              landing_button.html("Landing job submitted");
          } else {
              landing_button.prop("disabled", false);
              landing_button.removeClass("is-loading").addClass("is-success");;
              landing_button.html("Request landing");
          }
      } else {
          // TODO: handle this case.
      }
    });


    landing_button.on('click', function(e) {
      landing_button.addClass("is-loading");
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
          landing_button.prop("disabled", true);
          landing_button.removeClass("is-danger").removeClass("is-loading").addClass("is-warning");
          landing_button.html("Could not create landing job");
        } else {
          landing_button.prop("disabled", true);
          landing_button.removeClass("is-danger").removeClass("is-loading").addClass("is-warning");
          landing_button.html("An unknown error occurred");
        }
      });
    });




  });
};
