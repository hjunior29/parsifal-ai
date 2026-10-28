/* The Full text tab of a study's window (the study of Study Selection, and the one of Quality Assessment and Data
   Extraction): the PDF is framed only when the tab is shown, and it is uploaded or removed in place.

   $.parsifal.fullText({window: the modal, tab: the tab pane's id ("#tab-full-text"), ids: a function giving the
   review's id, the study's id and the csrf token}) binds it and returns {loadFrame}. */
(function ($) {

  'use strict';

  $.parsifal.fullText = function (options) {
    var $window = options.window;

    function loadFrame() {
      var frame = $window.find(".article-pdf-frame");
      if (frame.length && !frame.attr("src") && $window.find(options.tab).hasClass("active")) {
        frame.attr("src", frame.data("src"));
      }
    }

    function post(url, data, title) {
      var ids = options.ids();
      data.append("csrfmiddlewaretoken", ids.csrf);
      data.append("review-id", ids.review);
      data.append("article-id", ids.article);
      var buttons = $window.find("#article-pdf button");
      $.ajax({
        url: url,
        type: 'post',
        data: data,
        cache: false,
        contentType: false,
        processData: false,
        beforeSend: function () { buttons.prop("disabled", true); },
        success: function (html) {
          $window.find("#article-pdf").replaceWith(html);
          var tab = $window.find("a[href='" + options.tab + "']");
          tab.find(".glyphicon").remove();
          if ($window.find(".article-pdf-frame").length) {
            tab.append(' <span class="glyphicon glyphicon-file" title="Has a PDF"></span>');
          }
          loadFrame();
        },
        error: function (xhr) {
          $.parsifal.alert(title, $.parsifal.requestError(xhr));
        },
        complete: function () { buttons.prop("disabled", false); }
      });
    }

    $window.on("shown.bs.tab", "a[href='" + options.tab + "']", loadFrame);

    $window.on("click", ".js-choose-pdf", function () {
      $window.find(".js-pdf-file").val("").click();
    });

    $window.on("change", ".js-pdf-file", function () {
      if (this.files.length) {
        var data = new FormData();
        data.append("pdf", this.files[0]);
        post('/reviews/conducting/article_pdf/upload/', data, "Could not upload the PDF");
      }
    });

    $window.on("click", ".js-remove-pdf", function () {
      if (confirm("Remove the PDF of this study? The file is deleted.")) {
        post('/reviews/conducting/article_pdf/remove/', new FormData(), "Could not remove the PDF");
      }
    });

    return {loadFrame: loadFrame};
  };

})(jQuery);
