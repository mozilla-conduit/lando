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
  });
};
