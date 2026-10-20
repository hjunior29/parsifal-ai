function isScrolledIntoView(elem) {
    const docViewTop = $(window).scrollTop();
    const docViewBottom = docViewTop + $(window).height();

    const elemTop = $(elem).offset().top;
    const elemBottom = elemTop + $(elem).height();

    return ((elemBottom <= docViewBottom) && (elemTop >= docViewTop));
}

$(function () {

  $(".source-tab-content").on("click", ".btn-add-manual", function () {
    var container = $("#modal-add-article .modal-body");
    var review_id = $("#review-id").val();
    var div = $(this).closest(".source-buttons");
    var source_id = $("input[name=source-id]", div).val();
    $.ajax({
      url: '/reviews/conducting/new_article/',
      data: {'review-id': review_id, 'source-id': source_id},
      type: 'get',
      cache: false,
      beforeSend: function () {
        $(container).loading();
      },
      success: function (data) {
        $(container).html(data);
      },
      complete: function () {
        $(container).stopLoading();
      }
    });
    $("#modal-add-article").modal('show');
  });

  $("#source-tab a").click(function () {
    var source_id = $(this).attr("source-id");
    $("ul#source-tab li").removeClass("active");
    $(this).closest("li").addClass("active");

    $.ajax({
      url: '/reviews/conducting/source_articles/',
      data: { 'review-id': $("#review-id").val(), 'source-id': source_id },
      type: 'get',
      cache: false,
      beforeSend: function () {
        $(".source-tab-content").spinner();
      },
      success: function (data) {
        $(".source-tab-content").html(data);
        $(".source-tab-content table").tablesorter({ headers: { 0: { sorter: false }}});
      },
      complete: function () {
        $(".source-tab-content").spinner();
      }
    });

    return false;
  });

  /* Loads the active row's article, or ``articleId`` (an article that may not be in this tab). */
  $.fn.loadActiveArticle = function (articleId) {
    var article_id = articleId || $(".source-articles tbody tr.active").attr("oid");
    var review_id = $("#review-id").val();
    var container = $(this);

    var rows = $(".source-articles tbody tr:visible").not(".no-data");
    var position = rows.index(rows.filter("[oid=" + article_id + "]")) + 1;
    $("#modal-article span.current-article").text(position || "–");
    $("#modal-article span.total-articles").text(rows.length);

    $.ajax({
      url: '/reviews/conducting/article_details/',
      data: {'review-id': review_id, 'article-id': article_id},
      type: 'get',
      cache: false,
      beforeSend: function () {
        $(container).spinner();
      },
      success: function (data) {
        $(container).html(data);
      },
      complete: function () {
        $(container).spinner();
      }
    });
  };

  /* Opens an article in the details window. Its row, when this tab has it, becomes the active one, so that
     Previous/Next go on from there. */
  function openArticle(articleId) {
    $(".source-articles tbody tr").removeClass("active");
    $(".source-articles tbody tr[oid=" + articleId + "]").addClass("active");
    $("#modal-article .modal-body").css("height", $(window).height() * 0.7);
    $("#modal-article .modal-body").loadActiveArticle(articleId);
    $("#modal-article").modal('show');
  }

  $(".source-tab-content").on("click", "tbody tr", function () {
    if (!$(this).hasClass("no-data")) {
      openArticle($(this).attr("oid"));
    }
  });


  /* Reviewers tab inside the article modal: the tab pane is rendered hidden after the form and moved into the
     tab content, so that posting the decision form does not interfere with the article form. */
  $("#modal-article").on("click", "a[href='#tab-reviewers']", function () {
    var source = $("#modal-article #tab-reviewers-source");
    if ($("#modal-article #tab-reviewers").length === 0 && source.length) {
      $("#modal-article .tab-content").append('<div role="tabpanel" class="tab-pane" id="tab-reviewers"></div>');
      $("#modal-article #tab-reviewers").html(source.html());
      source.remove();
    }
  });

  $("#modal-article").on("click", ".btn-record-decision", function () {
    var btn = $(this);
    $.ajax({
      url: '/reviews/conducting/record_decision/',
      type: 'post',
      cache: false,
      data: $("#modal-article #decision-form :input").serialize(),
      beforeSend: function () { btn.prop("disabled", true); },
      success: function (data) {
        $("#modal-article #tab-reviewers").html(data);
      },
      error: function (xhr) {
        $.parsifal.alert("Could not record the decision", requestError(xhr));
      },
      complete: function () { btn.prop("disabled", false); }
    });
  });

  /* Full text tab: the PDF is fetched only when the tab is opened, not with every article of Previous/Next. */
  function loadPdfFrame() {
    var frame = $("#modal-article .article-pdf-frame");
    if (frame.length && !frame.attr("src") && $("#modal-article #tab-full-text").hasClass("active")) {
      frame.attr("src", frame.data("src"));
    }
  }

  $("#modal-article").on("shown.bs.tab", "a[href='#tab-full-text']", loadPdfFrame);

  function postPdf(url, data, title) {
    data.append("csrfmiddlewaretoken", $("#article-details [name=csrfmiddlewaretoken]").val());
    data.append("review-id", $("#modal-article #review-id").val());
    data.append("article-id", $("#modal-article #article-id").val());
    var buttons = $("#modal-article #article-pdf button");
    $.ajax({
      url: url,
      type: 'post',
      data: data,
      cache: false,
      contentType: false,
      processData: false,
      beforeSend: function () { buttons.prop("disabled", true); },
      success: function (html) {
        $("#modal-article #article-pdf").replaceWith(html);
        var tab = $("#modal-article a[href='#tab-full-text']");
        tab.find(".glyphicon").remove();
        if ($("#modal-article .article-pdf-frame").length) {
          tab.append(' <span class="glyphicon glyphicon-file" title="Has a PDF"></span>');
        }
        loadPdfFrame();
      },
      error: function (xhr) {
        $.parsifal.alert(title, requestError(xhr));
      },
      complete: function () { buttons.prop("disabled", false); }
    });
  }

  $("#modal-article").on("click", ".js-choose-pdf", function () {
    $("#modal-article .js-pdf-file").val("").click();
  });

  $("#modal-article").on("change", ".js-pdf-file", function () {
    if (this.files.length) {
      var data = new FormData();
      data.append("pdf", this.files[0]);
      postPdf('/reviews/conducting/article_pdf/upload/', data, "Could not upload the PDF");
    }
  });

  $("#modal-article").on("click", ".js-remove-pdf", function () {
    if (confirm("Remove the PDF of this study? The file is deleted.")) {
      postPdf('/reviews/conducting/article_pdf/remove/', new FormData(), "Could not remove the PDF");
    }
  });

  var agreementConsolidated = false;

  /* Short, readable text for a failed AJAX call: plain-text responses (our 400s) are shown as they are, HTML
     error pages are reduced to the status line. */
  function requestError(xhr) {
    var text = xhr.responseText || "";
    if (text && text.indexOf("<") !== 0) {
      return text;
    }
    return "Request failed" + (xhr.status ? " (" + xhr.status + " " + xhr.statusText + ")" : "") + ".";
  }

  function loadAgreement(stage) {
    $.ajax({
      url: '/reviews/conducting/agreement/',
      data: {'review-id': $("#review-id").val(), 'stage': stage || ''},
      type: 'get',
      cache: false,
      beforeSend: function () {
        $("#modal-agreement .modal-body").css("max-height", $(window).height() * 0.7);
        $("#modal-agreement").modal('show');
        $("#modal-agreement .modal-body").loading();
      },
      success: function (data) {
        $("#modal-agreement .modal-body").html(data);
        restoreRule();
      },
      complete: function () {
        $("#modal-agreement .modal-body").stopLoading();
      }
    });
  }

  /* The consolidation rule last used in this review is selected again when the window opens (in this browser). */
  function ruleKey() {
    return "parsifal.consolidateRule." + $("#review-id").val();
  }

  function restoreRule() {
    var select = $("#modal-agreement #consolidate-form select[name=rule]");
    try {
      var rule = window.localStorage.getItem(ruleKey());
      if (rule && select.find("option[value='" + rule + "']").length) {
        select.val(rule);
      }
    } catch (e) { /* storage blocked: keep the default */ }
  }

  function rememberRule(rule) {
    try { window.localStorage.setItem(ruleKey(), rule); } catch (e) { /* storage blocked */ }
  }

  $("#btn-agreement").click(function () { loadAgreement(); });

  $("#modal-agreement").on("change", "#agreement-stage", function () {
    loadAgreement($(this).val());
  });

  $("#modal-agreement").on("click", "#btn-consolidate", function () {
    var btn = $(this);
    var stage = $("#modal-agreement #agreement-stage").val();
    var rule = $("#modal-agreement #consolidate-form select[name=rule]").val();
    var csrf_token = $("#modal-agreement input[name=csrfmiddlewaretoken]").val();
    $.ajax({
      url: '/reviews/conducting/consolidate/',
      type: 'post',
      cache: false,
      data: {'review-id': $("#review-id").val(), 'stage': stage, 'rule': rule, 'csrfmiddlewaretoken': csrf_token},
      beforeSend: function () { btn.prop("disabled", true); },
      success: function (data) {
        agreementConsolidated = true;
        rememberRule(rule);
        $("#modal-agreement .modal-body").html(data);
      },
      error: function (xhr) {
        $.parsifal.alert("Could not consolidate", requestError(xhr));
        btn.prop("disabled", false);
      }
    });
  });

  $("#modal-agreement").on("hidden.bs.modal", function () {
    if (agreementConsolidated) {
      agreementConsolidated = false;
      $("#source-tab li.active a").click();
    }
  });

  /* A disagreement opens the article's details, to read it before deciding (the decisions are on its Reviewers
     tab); "Back to agreement" returns to the agreement window at the same stage. */
  var agreementStage = null;

  $("#modal-agreement").on("click", ".js-open-article", function (event) {
    event.preventDefault();
    var articleId = $(this).attr("data-article-id");
    agreementStage = $("#modal-agreement #agreement-stage").val() || "";
    $("#modal-agreement").one("hidden.bs.modal", function () {
      $("#btn-back-to-agreement").show();
      openArticle(articleId);
    }).modal("hide");
  });

  $("#btn-back-to-agreement").click(function () {
    var stage = agreementStage;
    $("#modal-article").one("hidden.bs.modal", function () { loadAgreement(stage); }).modal("hide");
  });

  $("#modal-article").on("hidden.bs.modal", function () {
    $("#btn-back-to-agreement").hide();
    agreementStage = null;
  });

  $("body").keydown(function (event) {
    var keyCode = event.which?event.which:event.keyCode;

    if (keyCode == ESCAPE_KEY) {
      if ($("body").hasClass("modal-open")) {
        $(".modal").modal('hide');
      }
      else {
        $(".source-articles tbody tr").removeClass("active");
      }
    }
    else if (!$("body").hasClass("modal-open") && !$(event.target).is("input[type=search], input[type=text], textarea")) {
      if (keyCode == UP_ARROW_KEY) {
        event.preventDefault();
        move(BACKWARD);
      }
      else if (keyCode == DOWN_ARROW_KEY) {
        event.preventDefault();
        move(FORWARD);
      }
      else if (keyCode == ENTER_KEY) {
       $(".source-articles tbody tr.active").click();
      }
    }
  });

  function move(step) {
    if ($(".source-articles tbody tr:visible").not(".no-data").length === 0) {
      return;  // every row is filtered out
    }
    var active = $(".source-articles tbody tr.active").index();
    var old_active = active;
    var size = $(".source-articles tbody tr").length;
    var next;
    do {
      active = (active + step) % size;
      next = $(".source-articles tbody tr:eq("+active+")");
    } while($(next).is(":hidden"));
    $(".source-articles tbody tr").removeClass("active");
    $(next).addClass("active");

    var row = $(".source-articles tbody tr.active");

    if (!isScrolledIntoView(row)) {
      if (active > old_active)
        $('html, body').animate({scrollTop: $(row).offset().top}, 2000);
      else
        $('html, body').animate({scrollTop: $(row).offset().top - $(window).height()}, 2000);
    }
  }

  $("#btn-previous").click(function () {
    move(BACKWARD);
    $("#modal-article .modal-body").loadActiveArticle();
  });

  $("#btn-next").click(function () {
    move(FORWARD);
    $("#modal-article .modal-body").loadActiveArticle();
  });

  function save_article(move_next) {
    var article_id = $("#modal-article #article-id").val();
    $.ajax({
      url: '/reviews/conducting/save_article_details/',
      cache: false,
      data: $("#article-details").serialize(),
      type: 'post',
      beforeSend: function () {
        $(".btn-save-article").prop("disabled", true);
      },
      success: function (data) {
        $(".source-articles table tbody tr[oid=" + article_id + "]").replaceWith(data);
        $(".source-articles table tbody tr[oid=" + article_id + "]").addClass("active");
        if (move_next) {
          move(FORWARD);
          $("#modal-article .modal-body").loadActiveArticle();
        }
        else {
          $("#modal-article .alert .modal-alert").text("Article successfully saved!");
          $("#modal-article .alert").removeClass("alert-error").addClass("alert-success");
          $("#modal-article .alert").removeClass("hide");
        }
      },
      error: function () {
          $("#modal-article .alert .modal-alert").text("Something went wrong! That's all we know :(");
          $("#modal-article .alert").removeClass("alert-success").addClass("alert-error");
          $("#modal-article .alert").removeClass("hide");
      },
      complete: function () {
        $(".btn-save-article").prop("disabled", false);
      }
    });
  }

  $(".btn-save-article").click(function () {
    save_article(false);
  });

  $("#modal-article").on("click", "ul.tab a", function () {
    var tab_id = $(this).attr("href");
    $("#modal-article div.tabs form > div").hide();
    $("#modal-article ul.tab li").removeClass("active");
    $(this).closest("li").addClass("active");
    $(tab_id).show();
    return false;
  });

  $("#modal-article").on("change", "#status", function () {
    if ($("#save-and-move-next").is(":checked")) {
      save_article(true);
    }
  });

  /* Rows shown: those with the status chosen in "Show" that match the search (title, DOI or BibTeX key). A row
     that gets hidden is unselected, so that an action never applies to rows out of sight. */
  var DOI_PREFIX = /^(?:(?:https?:\/\/)?(?:dx\.)?doi\.org\/|doi:\s*)/i;

  function applyFilters() {
    var content = $(".source-tab-content");
    var status = content.find("input[name=filter]:checked").val() || "ALL";
    var query = $.trim(content.find(".js-article-search").val() || "").toLowerCase();
    var doi = query.replace(DOI_PREFIX, "");
    var rows = content.find(".source-articles table tbody tr").not(".no-data");
    var shown = 0;
    rows.each(function () {
      var row = $(this);
      var cells = row.children("td");
      var matches = (status === "ALL" || row.attr("article-status") === status) && (
        !query ||
        cells.eq(1).text().toLowerCase().indexOf(query) !== -1 ||
        cells.eq(2).text().toLowerCase().indexOf(query) !== -1 ||
        (row.attr("article-doi") || "").toLowerCase().indexOf(doi) !== -1
      );
      row.toggle(matches);
      if (matches) {
        shown++;
      } else {
        row.removeClass("active").find("input[type=checkbox]").prop("checked", false);
      }
    });
    content.find(".js-no-match").toggle(rows.length > 0 && shown === 0);
    var checked = content.find(".source-articles tbody tr:visible td input[type=checkbox]:checked").length;
    $("#ck-all-articles").prop("checked", shown > 0 && checked === shown);
    updateSelectedArticlesCount();
  }

  $(".source-tab-content").on("click", "input[name=filter]", function () {
    $(".source-tab-content input[type=checkbox]").prop("checked", false);
    $(".source-articles tbody tr").removeClass("active");
    applyFilters();
  });

  var searchTimer = null;
  $(".source-tab-content").on("input", ".js-article-search", function () {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(applyFilters, 150);
  });

  $(".source-tab-content").on("click", "table tbody tr td input[type=checkbox]", function (event) {
    event.stopPropagation();
  });

  $(".source-tab-content").on("click", "#ck-all-articles", function () {
    $(".source-tab-content table tbody tr td input[type=checkbox]").prop("checked", false);
    if ($(this).is(":checked")) {
      $(".source-tab-content table tbody tr:visible td input[type=checkbox]").prop("checked", true);
    }
    updateSelectedArticlesCount();
  });

  function multiple_articles_actions(article_ids, action) {
    var review_id = $("#review-id").val();
    var csrf_token = $(".source-tab-content table").attr("csrf-token");

    $.ajax({
      url: '/reviews/conducting/multiple_articles_action/' + action + '/',
      data: {
        'review-id': review_id,
        'article_ids': article_ids,
        'csrfmiddlewaretoken': csrf_token
      },
      type: 'post',
      cache: false,
      beforeSend: function () {
        $(".go-button").prop("disabled", true);
        $(".go-button").text("Processing...");
      },
      success: function (data) {
        switch (action) {
          case "remove":
            $(".source-articles table tbody input[type=checkbox]:checked").each(function () {
              $(this).closest("tr").remove();
            });
            break;
          case "unclassify":
            $(".source-articles table tbody input[type=checkbox]:checked").each(function () {
              var row = $(this).closest("tr");
              $(row).attr("article-status", "U");
              $("span", row).replaceWith("<span class='label label-default'>Unclassified</span>");
            });
            break;
          case "accept":
            $(".source-articles table tbody input[type=checkbox]:checked").each(function () {
              var row = $(this).closest("tr");
              $(row).attr("article-status", "A");
              $("span", row).replaceWith("<span class='label label-success'>Accepted</span>");
            });
            break;
          case "reject":
            $(".source-articles table tbody input[type=checkbox]:checked").each(function () {
              var row = $(this).closest("tr");
              $(row).attr("article-status", "R");
              $("span", row).replaceWith("<span class='label label-danger'>Rejected</span>");
            });
            break;
          case "duplicated":
            $(".source-articles table tbody input[type=checkbox]:checked").each(function () {
              var row = $(this).closest("tr");
              $(row).attr("article-status", "D");
              $("span", row).replaceWith("<span class='label label-warning'>Duplicated</span>");
            });
            break;
        }
      },
      error: function () {

      },
      complete: function () {
        $(".go-button").prop("disabled", false);
        $(".go-button").text("Go");
        updateSelectedArticlesCount();
      }
    });
  }

  $(".source-tab-content").on("click", ".go-button", function () {
    var article_ids = '';
    var action = $(".source-tab-content .select-action").val();
    if (action) {
      $(".source-articles table tbody input[type=checkbox]:checked").each(function () {
        article_ids += $(this).val() + "|";
      });
      if (article_ids) {
        article_ids = article_ids.substring(0, article_ids.length - 1);
        switch (action) {
          case "remove":
            multiple_articles_actions(article_ids, action);
            break;
          case "unclassify":
            multiple_articles_actions(article_ids, action);
            break;
          case "accept":
            multiple_articles_actions(article_ids, action);
            break;
          case "reject":
            multiple_articles_actions(article_ids, action);
            break;
          case "duplicated":
            multiple_articles_actions(article_ids, action);
            break;
        }
      }
    }
  });

  $(".source-tab-content").on("click", "table tbody tr td input[type=checkbox]", function () {
    var total = $(".source-articles table tbody tr td input[type='checkbox']:visible").length;
    var checked = $(".source-articles table tbody tr td input[type='checkbox']:checked").length;
    if (checked === total) {
      $("#ck-all-articles").prop("checked", true);
    }
    else {
      $("#ck-all-articles").prop("checked", false);
    }
    updateSelectedArticlesCount();
  });

  $(".source-tab-content").on("click", "table tbody tr td:first-child", function (e) {
    e.stopPropagation();
    $("input[type='checkbox']", this).click();
    return false;
  });

  var updateSelectedArticlesCount = function () {
    var total = $(".source-articles table tbody tr td input[type='checkbox']:visible").length;
    var checked = $(".source-articles table tbody tr td input[type='checkbox']:checked").length;
    $(".articles-selected").text(checked);
    $(".articles-total").text(total);
  };

  $(".source-tab-content").on("click", ".btn-find-duplicates", function () {
    $.ajax({
      url: '/reviews/conducting/find_duplicates/',
      data: {'review-id': $("#review-id").val()},
      type: 'get',
      cache: false,
      beforeSend: function () {
        $("#modal-duplicates .modal-body").css("max-height", $(window).height() * 0.7);
        $("#modal-duplicates").modal('show');
        $("#modal-duplicates .modal-body").loading();
      },
      success: function (data) {
        $("#modal-duplicates .modal-body").html(data);
      },
      complete: function () {
        $("#modal-duplicates .modal-body").stopLoading();
      }
    });
  });

  $("#modal-duplicates").on("click", ".btn-resolve", function () {
    var row = $(this).closest("tr");
    var btn = $(this);
    var review_id = $("#review-id").val();
    var article_id = $(row).attr("article-id");
    var duplicate = $(row).attr("duplicate");
    var csrf_token = $("#modal-duplicates input[name=csrfmiddlewaretoken]").val();
    $.ajax({
      url: '/reviews/conducting/resolve_duplicated/',
      data: {
        'review-id': review_id,
        'article-id': article_id,
        'csrfmiddlewaretoken': csrf_token
      },
      type: 'post',
      cache: false,
      beforeSend: function () {
        $(btn).prop("disabled", true);
        $(btn).text("Resolving...");
      },
      success: function (data) {
        $("span", row).replaceWith("<span class='label label-warning'>Duplicated</span>");
        $(btn).text("Resolved");
        $(row).attr("resolved", "true");
        var duplicates = $("#modal-duplicates .modal-body tr[duplicate=" + duplicate + "]");
        var duplicates_resolved = $("#modal-duplicates .modal-body tr[duplicate=" + duplicate + "][resolved=true]");

        if (duplicates.length - duplicates_resolved.length === 1) {
          var btn_resolved = $("#modal-duplicates .modal-body tr[duplicate=" + duplicate + "][resolved=false] button");
          $(btn_resolved).text("Resolved");
          $(btn_resolved).prop("disabled", true);
        }

        var article_row = $(".source-tab-content .source-articles tr[oid=" + article_id + "]");
        $(article_row).attr("article-status", "D");
        $("span", article_row).replaceWith("<span class=\"label label-warning\">Duplicated</span>");
      },
      error: function () {
        $(btn).prop("disabled", false);
        $(btn).text("Resolve");
      }
    });
  });

  $("#btn-resolve-all").click(function () {
    var review_id = $("#review-id").val();
    var csrf_token = $("#modal-duplicates input[name=csrfmiddlewaretoken]").val();
    var btn = $(this);
    $.ajax({
      url: '/reviews/conducting/resolve_all/',
      data: {
        'review-id': review_id,
        'csrfmiddlewaretoken': csrf_token
      },
      type: 'post',
      cache: false,
      beforeSend: function () {
        $(btn).prop("disabled", true);
        $(btn).text("Resolving...");
      },
      success: function (data) {
        if (data !== "") {
          var btn_modal = $("#modal-duplicates table tbody tr td button");
          $(btn_modal).prop("disabled", true);
          $(btn_modal).text("Resolved");
          var ids = data.split(",");
          for (var i = ids.length - 1; i >= 0; i--) {
            var article_row = $(".source-tab-content .source-articles tr[oid=" + ids[i] + "]");
            $(article_row).attr("article-status", "D");
            $("span", article_row).replaceWith("<span class=\"label label-warning\">Duplicated</span>");
          }
        }
      },
      complete: function () {
        $(btn).prop("disabled", false);
        $(btn).text("Resolve All");
      }
    });
  });

  // On page load

  if ($("ul#source-tab li").length > 0) {
    if($("ul#source-tab li.active").length === 0) {
      $("ul#source-tab li:eq(0)").addClass("active");
    }
    $("#source-tab li.active a").click();
  }

});
