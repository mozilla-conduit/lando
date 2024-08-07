'use strict';

$(document).ready(function() {
  let $timeline = $('.StackPage-timeline');
  let $landingPreview = $('.StackPage-landingPreview');
  let $stack = $('.StackPage-stack');
  let $secRequestSubmitted = $('.StackPage-secRequestSubmitted');
  let $flashMessages = $('.FlashMessages');

  // Initialize components
  $('.Navbar').landoNavbar();
  $timeline.timeline();
  $landingPreview.landingPreview();
  $stack.stack();
  $secRequestSubmitted.secRequestSubmitted();
  $flashMessages.flashMessages();
});
