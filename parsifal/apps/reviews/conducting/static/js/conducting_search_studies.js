$(function () {
    $(".js-save-source-string").click(function () {
        var btn = $(this);
        var form = $(this).closest("form");
        var url = $(this).attr("data-remote");
        $.ajax({
            url: url,
            data: $(form).serialize(),
            type: 'post',
            cache: false,
            beforeSend: function () {
                $(btn).ajaxDisable();
            },
            success: function () {
                var source_id = $("[name='source-id']", form).val();
                var search_string = $("[name='search_string']", form).val();
                $("[data-source-id='" + source_id + "'] textarea[name='query']").val(search_string);
            },
            complete: function () {
                $(btn).ajaxEnable();
            }
        });
    });

    $(".js-import-base-string").click(function () {
        var btn = $(this);
        var form = $(this).closest("form");
        var url = $(this).attr("data-remote");
        $.ajax({
            url: url,
            data: $(form).serialize(),
            type: 'post',
            cache: false,
            beforeSend: function () {
                $(btn).ajaxDisable();
            },
            success: function (data) {
                $("textarea[name='search_string']", form).val(data);
                var source_id = $("[name='source-id']", form).val();
                $("[data-source-id='" + source_id + "'] textarea[name='query']").val(data);
            },
            complete: function () {
                $(btn).ajaxEnable();
            }
        });
    });

    $(".js-remove-source-string").click(function () {
        $(this).ajaxDisable();
        var form = $(this).closest("form");
        var url = $(this).attr("data-remote");
        $(form).attr("action", url);
        $(form).submit();
    });

});
