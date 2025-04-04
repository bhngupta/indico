// This file is part of Indico.
// Copyright (C) 2002 - 2025 CERN
//
// Indico is free software; you can redistribute it and/or
// modify it under the terms of the MIT License; see the
// LICENSE file for more details.

(function($) {
  'use strict';

  /*
   * This provides an untility for checkboxes (usually switch widgets) which immediately
   * save the state using an AJAX request. The checkbox is disabled during the AJAX request
   * to avoid the user from clicking multiple times and spamming unnecessary AJAX requests.
   *
   * The following data attributes may be set on the checkbox to configure the behavior:
   * - href: required unless specified in the function call, URL for the AJAX request
   * - method: optional, method for the AJAX request if it's not POST
   * - confirm_enable: optional, show confirmation prompt when checking the checkbox if set
   * - confirm_disable: optional, show confirmation prompt when unchecking the checkbox if set
   */
  $.fn.ajaxCheckbox = function ajaxCheckbox(options) {
    options = $.extend(
      {
        sendData: true, // if `enabled: '1/0'` should be sent in the request
        // all these options may also be functions which are invoked with `this` set to the checkbox
        method: null, // taken from data-method by default, can be any valid HTTP method
        href: null, // taken from data-href by default
      },
      options
    );

    function getOption(opt, ctx) {
      var value = options[opt];
      if (_.isFunction(value)) {
        return value.call(ctx);
      } else {
        return value;
      }
    }

    return this.on('click', function(e) {
      e.preventDefault();
      var self = this;
      var $this = $(this);
      var checked = this.checked;
      var message = checked ? $this.data('confirmEnable') : $this.data('confirmDisable');
      var deferred = message ? confirmPrompt(message) : $.Deferred().resolve();
      deferred.then(function() {
        // update check state and prevent changes until the request finished
        $this.prop('checked', checked).prop('disabled', true);
        var data = options.sendData
          ? {
              enabled: checked ? '1' : '0',
            }
          : null;
        $.ajax({
          url: getOption('href', self) || $this.data('href'),
          method: getOption('method', self) || $this.data('method') || 'POST',
          dataType: 'json',
          data: data,
          complete: function() {
            $this.prop('disabled', false);
          },
          error: function(data) {
            handleAjaxError(data);
            $this.prop('checked', !checked);
          },
          success: function(data) {
            $this
              .prop('checked', data.enabled)
              .trigger('ajaxCheckbox:changed', [data.enabled, data]);
            handleFlashes(data, true, $this);
          },
        });
      });
    });
  };
})(jQuery);
