"use strict";

$(document).ready(function () {
    let $flashMessages = $(".FlashMessages");
    let $landingPreview = $(".StackPage-landingPreview");
    let $navBar = $(".Navbar");
    let $secRequestSubmitted = $(".StackPage-secRequestSubmitted");
    let $stack = $(".StackPage-stack");
    let $timeline = $(".StackPage-timeline");
    let $treestatus = $(".Treestatus");
    let $uplifts = $(".Uplifts");
    let $gh_stack = $(".StackPage-gh-stack");

    // Initialize components
    $flashMessages.flashMessages();
    $landingPreview.landingPreview();
    $navBar.landoNavbar();
    $secRequestSubmitted.secRequestSubmitted();
    $stack.stack();
    $gh_stack.gh_stack();
    $timeline.timeline();
    $treestatus.treestatus();
    $uplifts.uplifts();
});
