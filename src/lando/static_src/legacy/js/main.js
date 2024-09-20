'use strict';

$(document).ready(function() {
  let $flashMessages = $('.FlashMessages');
  let $landingPreview = $('.StackPage-landingPreview');
  let $navBar = $('.Navbar');
  let $secRequestSubmitted = $('.StackPage-secRequestSubmitted');
  let $stack = $('.StackPage-stack');
  let $timeline = $('.StackPage-timeline');

  // Initialize components
  $flashMessages.flashMessages();
  $landingPreview.landingPreview();
  $navBar.landoNavbar();
  $secRequestSubmitted.secRequestSubmitted();
  $stack.stack();
  $timeline.timeline();
});
