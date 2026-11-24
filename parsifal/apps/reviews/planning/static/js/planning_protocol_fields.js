/* The forms of the Protocol saved field by field through save_protocol_fields: the practical context and the
   procedures of a rapid review. A refusal (a date, a deadline before the start) is shown next to the button. */
$(function () {
  $(".js-save-protocol-fields").click(function () {
    var btn = $(this);
    var form = btn.closest("form");
    var error = $(".js-protocol-fields-error", form);
    error.text("");
    $.ajax({
      url: '/reviews/planning/save_protocol_fields/',
      data: form.serialize(),
      type: 'post',
      cache: false,
      beforeSend: function () {
        $(btn).ajaxDisable();
      },
      success: function () {
        $(btn).ajaxEnable();
      },
      error: function (jqXHR) {
        $(btn).ajaxEnableError();
        error.text(jqXHR.responseText || "Could not save.");
      }
    });
  });
});
