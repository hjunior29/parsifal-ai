/* Google Charts is loaded once for the whole page: its loader refuses a second load, which left the charts drawn
   after it empty. When it is ready, "charts-ready" draws the charts below the first three. */
$(function () {
    google.charts.load('current', {'packages': ['corechart']});
    google.charts.setOnLoadCallback(drawChartCallback);

    function drawChartCallback() {
      drawChart();
      drawYearLines();
      $(document).trigger("charts-ready");
    }

    function drawPieChart(rows) {
      var data = new google.visualization.DataTable();
      data.addColumn('string', 'Source');
      data.addColumn('number', 'Number of Articles');
      data.addRows(rows);
      var options = {'height': 400};
      var chart = new google.visualization.PieChart(document.getElementById('articles-selection-pie'));
      chart.draw(data, options);
    }

    function drawColumnChart(rows) {
      var data = google.visualization.arrayToDataTable(rows);
      var options = {
        vAxis: {title: 'Number of Articles',  titleTextStyle: {color: '#3A3D40'}},
        'height': 400
      };
      var chart = new google.visualization.ColumnChart(document.getElementById('articles-selection-column'));
      chart.draw(data, options);
    }

    function drawLineChart(rows) {
      var data = google.visualization.arrayToDataTable(rows);
      var options = {
        vAxis: {title: 'Number of Articles',  titleTextStyle: {color: '#3A3D40'}},
        'height': 400
      };
      var chart = new google.visualization.LineChart(document.getElementById('articles-selection-line'));
      chart.draw(data, options);
    }

    function drawChart() {
      $.ajax({
        url: '/reviews/conducting/articles_selection_chart/',
        data: {'review-id': $("#review-id").val()},
        type: 'get',
        cache: false,
        beforeSend: function () {
          $("#articles-selection-pie").spinner(false);
          $("#articles-selection-column").spinner(false);
        },
        success: function (data) {
          var source_data = data.split(",");
          var rows_pie = [];
          var rows_chart = [['Source', 'Selected', 'Accepted']];
          for (var i = source_data.length - 1; i >= 0; i--) {
            row = source_data[i].split(":");
            rows_pie.push([row[0], parseInt(row[1])]);
            rows_chart.push([row[0], parseInt(row[1]), parseInt(row[2])]);
          }
          drawPieChart(rows_pie);
          drawColumnChart(rows_chart);
        },
        complete: function () {
          $("#articles-selection-pie").spinner();
          $("#articles-selection-column").spinner();
        }
      });
    }

    function drawYearLines() {
      $.ajax({
        url: '/reviews/conducting/articles_per_year/',
        data: {'review-id': $("#review-id").val()},
        type: 'get',
        cache: false,
        beforeSend: function () {
          $("#articles-selection-line").spinner(false);
        },
        success: function (data) {
          var source_data = data.split(",");
          var rows = [['Year', 'Number of Articles']];
          for (var i = source_data.length - 1; i >= 0; i--) {
            row = source_data[i].split(":");
            rows.push([row[0], parseInt(row[1])]);
          }
          drawLineChart(rows);
        },
        complete: function () {
          $("#articles-selection-line").spinner();
        }
      });
    }
});

/* The charts below the first three: the study selection in numbers, the statuses per source, the criteria most used
   and the studies per year. Their data come with the page (json_script). */
$(function () {
  var COLORS = {accepted: "#5cb85c", rejected: "#d9534f", unclassified: "#999999", duplicated: "#f0ad4e"};

  function data(id) {
    var node = document.getElementById(id);
    return node ? JSON.parse(node.textContent) : null;
  }

  function stacked(elementId, rows, statuses) {
    var element = document.getElementById(elementId);
    if (!element || rows.length < 2) { return; }
    var chart = new google.visualization.ColumnChart(element);
    chart.draw(google.visualization.arrayToDataTable(rows), {
      height: 400,
      isStacked: true,
      colors: statuses.map(function (status) { return COLORS[status]; }),
      vAxis: {title: "Number of Articles", titleTextStyle: {color: "#3A3D40"}},
      legend: {position: "top"}
    });
  }

  function ranking(elementId, criteria, color) {
    var element = document.getElementById(elementId);
    if (!element || !criteria.length) { return; }
    var rows = [["Criterion", "Studies"]];
    criteria.forEach(function (criterion) {
      var description = criterion.description.length > 70 ? criterion.description.slice(0, 67) + "…" : criterion.description;
      rows.push([criterion.key + " — " + description, criterion.studies]);
    });
    var chart = new google.visualization.BarChart(element);
    chart.draw(google.visualization.arrayToDataTable(rows), {
      height: Math.max(160, 40 * criteria.length + 60),
      colors: [color],
      legend: {position: "none"},
      chartArea: {left: "45%", width: "50%"},
      hAxis: {title: "Number of Articles", minValue: 0, format: "0"}
    });
  }

  function draw() {
    var summary = data("analysis-summary");
    var criteria = data("analysis-criteria");
    var years = data("analysis-years-data");
    if (!summary) { return; }

    var statuses = ["accepted", "rejected", "unclassified", "duplicated"];
    var pie = document.getElementById("analysis-statuses");
    if (pie && summary.total) {
      var rows = [["Status", "Studies"]];
      statuses.forEach(function (status) { rows.push([status.charAt(0).toUpperCase() + status.slice(1), summary[status]]); });
      new google.visualization.PieChart(pie).draw(google.visualization.arrayToDataTable(rows), {
        height: 320,
        colors: statuses.map(function (status) { return COLORS[status]; })
      });
    }

    var sources = [["Source", "Accepted", "Rejected", "Unclassified", "Duplicated"]];
    summary.by_source.forEach(function (row) {
      sources.push([row.source, row.accepted, row.rejected, row.unclassified, row.duplicated]);
    });
    stacked("analysis-sources", sources, statuses);

    ranking("analysis-exclusion", criteria.exclusion, COLORS.rejected);
    ranking("analysis-inclusion", criteria.inclusion, COLORS.accepted);

    var perYear = [["Year", "Accepted", "Rejected", "Unclassified"]];
    years.forEach(function (row) {
      perYear.push([row.year === null ? "Unknown" : String(row.year), row.accepted, row.rejected, row.unclassified]);
    });
    stacked("analysis-years", perYear, ["accepted", "rejected", "unclassified"]);
  }

  $(document).on("charts-ready", draw);
});
