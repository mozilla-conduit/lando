'use strict';

$.fn.landoNavbar = function() {
  return this.each(function() {
    let $navbar = $(this);

    // Initialize the responsive menu.
    let $menu = $navbar.find('#Navbar-menu').first();
    let $mobileMenuBtn = $navbar.find('.navbar-burger').first();
    $mobileMenuBtn.on('click', () => {
      $menu.toggleClass('is-active');
      $mobileMenuBtn.toggleClass('is-active');
    });

    // Initialize the settings modal.
    let $modal = $navbar.find('.Navbar-modal').first();
    if (!$modal.length) {
      return;
    }
    let $modalToggleBtn = $navbar.find('.Navbar-userSettingsBtn').first();
    let $modalSubmitBtn = $navbar.find('.Navbar-modalSubmit').first();
    let $modalCancelBtn = $navbar.find('.Navbar-modalCancel');
    let $settingsForm = $modal.find('.userSettingsForm').first();
    let $settingsFormErrors = $modal.find('.userSettingsForm-Errors');
    let $errorPageShowModal = $('.ErrorPage-showAPIKey');

    // Phabricator API key settings
    let $phabricatorAPIKeyInput = $modal.find('#id_phabricator_api_key').first();
    let $phabricatorAPIKeyReset = $modal.find('#id_reset_key').first();
    let isSetPhabricatorAPIKey = $settingsForm.data('phabricator_api_key');

    modalSubmitBtnOn();
    setAPIKeyPlaceholder();

    $modalToggleBtn.on('click', () => {
      $modal.toggleClass('is-active');
    });

    if ($errorPageShowModal) {
      $errorPageShowModal.on('click', e => {
        e.preventDefault();
        $modal.addClass('is-active');
      });
    }

    $settingsForm.on('submit', function(e) {
      e.preventDefault();
      e.stopImmediatePropagation();
      // We don't have any other setting than the API key
      if (!$phabricatorAPIKeyInput.val() && !$phabricatorAPIKeyReset.prop('checked')) {
        displaySettingsError('phabricator_api_key_errors', 'Invalid API Key Value');
        return;
      }
      modalSubmitBtnOff();
      $.ajax({
        url: '/manage_api_key/',
        type: 'post',
        data: $(this).serialize(),
        dataType: 'json',
        success: data => {
          modalSubmitBtnOn();
            console.log(data);
          if (!data.success) {
            return handlePhabricatorAPIKeyErrors(data.errors);
          }
          restartPhabricatorAPIKey();
          $modal.removeClass('is-active');
          console.log('Your settings have been saved.');
          window.location.reload(true);
        },
        error: () => {
          modalSubmitBtnOn();
          resetSettingsFormErrors();
          displaySettingsError('form_errors', 'Connection error');
        }
      });
    });

    $modalCancelBtn.each(function() {
      $(this).on('click', () => {
        restartPhabricatorAPIKey();
        resetSettingsFormErrors();
        $modal.removeClass('is-active');
      });
    });

    $phabricatorAPIKeyReset.on('click', () => {
      setAPIKeyPlaceholder();
    });

    function resetSettingsFormErrors() {
      $settingsFormErrors.empty();
    }

    function displaySettingsError(errorSet, message) {
      $modal
        .find('#' + errorSet)
        .first()
        .append('<li class="help is-danger">' + message + '</li>');
    }

    function setAPIKeyPlaceholder() {
      if ($phabricatorAPIKeyReset.prop('checked')) {
        $phabricatorAPIKeyInput.val('');
        $phabricatorAPIKeyInput.prop('disabled', true);
        return;
      }
      $phabricatorAPIKeyInput.prop('disabled', false);
      if (!isSetPhabricatorAPIKey) {
        $phabricatorAPIKeyInput.prop('placeholder', 'Enter new key.');
      } else {
        $phabricatorAPIKeyInput.prop('placeholder', '************************');
      }
    }

    function restartPhabricatorAPIKey() {
      $phabricatorAPIKeyInput.val('');
      $phabricatorAPIKeyReset.prop('checked', false);
      $phabricatorAPIKeyInput.prop('disabled', false);
      setAPIKeyPlaceholder();
    }

    function handlePhabricatorAPIKeyErrors(errors) {
      resetSettingsFormErrors();
      Object.keys(errors).forEach(error => {
        if (error in ['phabricator_api_key', 'reset_key']) {
          errors[error].each(message => {
            displaySettingsError('phabricator_api_key_errors', message);
          });
          return;
        }
        errors[error].forEach(message => {
          displaySettingsError(error + '_errors', message);
        });
      });
    }

    function settingsFormSubmit() {
      $settingsForm.submit();
    }

    function modalSubmitBtnOn() {
      $modalSubmitBtn.removeClass('is-loading');
      $modalSubmitBtn.on('click', settingsFormSubmit);
    }

    function modalSubmitBtnOff() {
      $modalSubmitBtn.addClass('is-loading');
      $modalSubmitBtn.off('click');
    }
  });
};
