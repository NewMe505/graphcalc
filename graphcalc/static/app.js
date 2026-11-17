(function () {
  "use strict";

  var buttons = document.querySelectorAll(".tab-button");
  var panels = document.querySelectorAll(".tab-panel");

  function showTab(tabId) {
    panels.forEach(function (panel) {
      panel.classList.toggle("active", panel.id === tabId);
    });
    buttons.forEach(function (button) {
      button.classList.toggle("active", button.dataset.tab === tabId);
    });
  }

  buttons.forEach(function (button) {
    button.addEventListener("click", function () {
      showTab(button.dataset.tab);
    });
  });

  showTab("tab-calculator");

  // ---- Calculator tab: wired to /api/calc/evaluate, /api/calc/history and
  // /api/calc/vars (plan step P8). The page only draws what the API
  // returns -- no client-side math, ever.
  var CALC_EVALUATE_PATH = "/api/calc/evaluate";
  var CALC_HISTORY_PATH = "/api/calc/history";
  var CALC_VARS_PATH = "/api/calc/vars";

  var calcInput = document.getElementById("calc-input");
  var calcMode = document.getElementById("calc-mode");
  var calcSubmit = document.getElementById("calc-submit");
  var calcHistory = document.getElementById("calc-history");
  var calcVars = document.getElementById("calc-vars");
  var calcError = document.getElementById("calc-error");

  function calcShowError(message) {
    calcError.textContent = message || "";
  }

  function calcFormatResult(entry) {
    if (entry.domain_error) {
      return entry.domain_error;
    }
    if (entry.complex) {
      return entry.exact + " = " + entry.complex.real + " + " + entry.complex.imag + "i";
    }
    if (entry.decimal && entry.decimal !== entry.exact) {
      return entry.exact + " = " + entry.decimal;
    }
    return entry.exact;
  }

  function calcRenderHistory(history) {
    calcHistory.innerHTML = "";
    history.forEach(function (entry) {
      var item = document.createElement("li");
      item.textContent = entry.expr + " => " + calcFormatResult(entry);
      calcHistory.appendChild(item);
    });
  }

  function calcRenderVars(data) {
    calcVars.innerHTML = "";
    var variables = data.variables || {};
    var functions = data.functions || {};
    Object.keys(variables).forEach(function (name) {
      var dt = document.createElement("dt");
      dt.textContent = name;
      var dd = document.createElement("dd");
      dd.textContent = variables[name];
      calcVars.appendChild(dt);
      calcVars.appendChild(dd);
    });
    Object.keys(functions).forEach(function (name) {
      var spec = functions[name];
      var dt = document.createElement("dt");
      dt.textContent = name + "(" + spec.params.join(", ") + ")";
      var dd = document.createElement("dd");
      dd.textContent = spec.body;
      calcVars.appendChild(dt);
      calcVars.appendChild(dd);
    });
  }

  function calcRefreshHistory() {
    fetch(CALC_HISTORY_PATH)
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        calcRenderHistory(data.history || []);
      });
  }

  function calcRefreshVars() {
    fetch(CALC_VARS_PATH)
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        calcRenderVars(data);
      });
  }

  function calcSubmitExpression() {
    calcShowError("");
    fetch(CALC_EVALUATE_PATH, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expr: calcInput.value, mode: calcMode.value }),
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok) {
          calcShowError(result.data.error || "error");
          return;
        }
        if (result.data.domain_error) {
          calcShowError(result.data.domain_error);
        }
        calcRefreshHistory();
        calcRefreshVars();
      })
      .catch(function (err) {
        calcShowError(String(err));
      });
  }

  if (calcSubmit) {
    calcSubmit.addEventListener("click", calcSubmitExpression);
    calcInput.addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        event.preventDefault();
        calcSubmitExpression();
      }
    });
    calcRefreshHistory();
    calcRefreshVars();
  }

  // ---- Graphs tab: wired to /api/graph/plot, /api/graph/window,
  // /api/graph/analyze and /api/graph/table (plan step P14/S2). Same as the
  // Calculator tab above, the page only draws what the API returns -- no
  // client-side math, ever.
  var GRAPH_PLOT_PATH = "/api/graph/plot";
  var GRAPH_WINDOW_PATH = "/api/graph/window";
  var GRAPH_ANALYZE_PATH = "/api/graph/analyze";
  var GRAPH_TABLE_PATH = "/api/graph/table";

  var GRAPH_SLOTS = ["f1", "f2", "f3", "f4"];
  var GRAPH_ZOOM_FACTOR = 2;
  var GRAPH_PAN_FRACTION = 0.25;
  var GRAPH_TABLE_ROWS = 21;

  var graphInputs = GRAPH_SLOTS.map(function (slot) {
    return document.getElementById("graph-" + slot);
  });
  var graphXmin = document.getElementById("graph-xmin");
  var graphXmax = document.getElementById("graph-xmax");
  var graphYmin = document.getElementById("graph-ymin");
  var graphYmax = document.getElementById("graph-ymax");
  var graphWindowInputs = [graphXmin, graphXmax, graphYmin, graphYmax];
  var graphZoomIn = document.getElementById("graph-zoom-in");
  var graphZoomOut = document.getElementById("graph-zoom-out");
  var graphPanLeft = document.getElementById("graph-pan-left");
  var graphPanRight = document.getElementById("graph-pan-right");
  var graphPanUp = document.getElementById("graph-pan-up");
  var graphPanDown = document.getElementById("graph-pan-down");
  var graphTraceX = document.getElementById("graph-trace-x");
  var graphAnalyzeButton = document.getElementById("graph-analyze");
  var graphCanvas = document.getElementById("graph-canvas");
  var graphTable = document.getElementById("graph-table");

  if (graphCanvas) {
    var graphCtx = graphCanvas.getContext("2d");

    // A plain, unlabeled status line for an analyze result or a 400 JSON
    // error from any of the four graph endpoints. Created here, not in
    // index.html, because this step only touches app.js; it inherits the
    // page's global overflow-wrap/word-break rule (style.css, plan step
    // P33), so a long result or error message wraps instead of widening
    // the page, the same as calc-error already does.
    var graphStatus = document.createElement("p");
    if (graphAnalyzeButton && graphAnalyzeButton.parentNode) {
      graphAnalyzeButton.parentNode.appendChild(graphStatus);
    }

    function graphShowStatus(message) {
      graphStatus.textContent = message || "";
    }

    function graphReadFunctions() {
      var functions = {};
      GRAPH_SLOTS.forEach(function (slot, index) {
        var value = graphInputs[index].value;
        if (value) {
          functions[slot] = value;
        }
      });
      return functions;
    }

    function graphFirstFunction() {
      for (var i = 0; i < graphInputs.length; i++) {
        if (graphInputs[i].value) {
          return graphInputs[i].value;
        }
      }
      return null;
    }

    function graphReadWindow() {
      return {
        xmin: parseFloat(graphXmin.value),
        xmax: parseFloat(graphXmax.value),
        ymin: parseFloat(graphYmin.value),
        ymax: parseFloat(graphYmax.value),
      };
    }

    function graphApplyWindow(win) {
      graphXmin.value = win.xmin;
      graphXmax.value = win.xmax;
      graphYmin.value = win.ymin;
      graphYmax.value = win.ymax;
    }

    function graphToPixel(win, x, y) {
      var px = ((x - win.xmin) / (win.xmax - win.xmin)) * graphCanvas.width;
      var py =
        graphCanvas.height -
        ((y - win.ymin) / (win.ymax - win.ymin)) * graphCanvas.height;
      return [px, py];
    }

    function graphDrawAxes(win) {
      graphCtx.strokeStyle = "#999999";
      graphCtx.lineWidth = 1;
      if (win.ymin <= 0 && win.ymax >= 0) {
        var xAxis = graphToPixel(win, 0, 0);
        graphCtx.beginPath();
        graphCtx.moveTo(0, xAxis[1]);
        graphCtx.lineTo(graphCanvas.width, xAxis[1]);
        graphCtx.stroke();
      }
      if (win.xmin <= 0 && win.xmax >= 0) {
        var yAxis = graphToPixel(win, 0, 0);
        graphCtx.beginPath();
        graphCtx.moveTo(yAxis[0], 0);
        graphCtx.lineTo(yAxis[0], graphCanvas.height);
        graphCtx.stroke();
      }
    }

    // P34-BEGIN
    // Bug #40: a vertical asymptote (e.g. "1/x" at x=0) falls *between* two
    // sampled x-values -- plot() (P10) only ever returns null for a sample
    // exactly on the pole, so both neighbouring samples come back as huge
    // but finite floats, one on each side. Without this check,
    // graphDrawSeries below joins them with a near-vertical lineTo, drawing
    // a line across the gap that visually welds the two branches together.
    // A jump between two consecutive samples is treated as an asymptote --
    // never part of the curve -- only when both samples are finite numbers,
    // they swing from positive to negative (or back), and the swing is
    // more than twice the window's own height (ymax - ymin). A steep but
    // continuous curve such as "10*x" never swings by more than a small
    // fraction of the window between two adjacent canvas-width samples, so
    // it is never broken by this check (see NOTES.md for the one case this
    // heuristic does not cover: an even steeper continuous line).
    function graphIsAsymptoteJump(y0, y1, ymin, ymax) {
      if (
        typeof y0 !== "number" ||
        typeof y1 !== "number" ||
        !isFinite(y0) ||
        !isFinite(y1)
      ) {
        return false;
      }
      if (!(y0 * y1 < 0)) {
        return false;
      }
      return Math.abs(y1 - y0) > 2 * (ymax - ymin);
    }
    // P34-END

    // Draws each returned series on graph-canvas, mapping the window to
    // pixels and breaking the path wherever "y" is null -- a gap in the
    // domain (plan step P10's own series shape) must stay a gap, never a
    // straight line drawn across it -- and also wherever two consecutive
    // finite samples jump across a vertical asymptote (bug #40, P34).
    function graphDrawSeries(win, xs, series) {
      Object.keys(series).forEach(function (name) {
        var entry = series[name];
        var ys = entry.y || [];
        graphCtx.strokeStyle = entry.color || "#000000";
        graphCtx.lineWidth = 2;
        graphCtx.beginPath();
        var drawing = false;
        var prevY = null;
        xs.forEach(function (x, index) {
          var y = ys[index];
          if (y === null || y === undefined) {
            drawing = false;
            prevY = null;
            return;
          }
          var point = graphToPixel(win, x, y);
          if (drawing && !graphIsAsymptoteJump(prevY, y, win.ymin, win.ymax)) {
            graphCtx.lineTo(point[0], point[1]);
          } else {
            graphCtx.moveTo(point[0], point[1]);
            drawing = true;
          }
          prevY = y;
        });
        graphCtx.stroke();
      });
    }

    function graphRenderPlot(win, data) {
      graphCtx.clearRect(0, 0, graphCanvas.width, graphCanvas.height);
      graphDrawAxes(win);
      graphDrawSeries(win, data.x || [], data.series || {});
    }

    function graphRenderTable(data) {
      graphTable.innerHTML = "";
      var columnNames = Object.keys(data.columns || {});
      var headerRow = document.createElement("tr");
      var xHeader = document.createElement("th");
      xHeader.textContent = "x";
      headerRow.appendChild(xHeader);
      columnNames.forEach(function (name) {
        var th = document.createElement("th");
        th.textContent = name;
        headerRow.appendChild(th);
      });
      graphTable.appendChild(headerRow);

      (data.x || []).forEach(function (xValue, index) {
        var row = document.createElement("tr");
        var xCell = document.createElement("td");
        xCell.textContent = xValue;
        row.appendChild(xCell);
        columnNames.forEach(function (name) {
          var cell = document.createElement("td");
          var value = data.columns[name][index];
          cell.textContent = value === null || value === undefined ? "" : value;
          row.appendChild(cell);
        });
        graphTable.appendChild(row);
      });
    }

    // The table action (P13): POSTs to /api/graph/table for the same
    // functions and window the canvas just plotted, evenly spaced across
    // the current window, and renders the rows into graph-table.
    function graphRefreshTable(functions, win) {
      if (Object.keys(functions).length === 0) {
        graphTable.innerHTML = "";
        return;
      }
      var step = (win.xmax - win.xmin) / (GRAPH_TABLE_ROWS - 1);
      if (!isFinite(step) || step === 0) {
        return;
      }
      fetch(GRAPH_TABLE_PATH, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          functions: functions,
          start: win.xmin,
          step: step,
          rows: GRAPH_TABLE_ROWS,
        }),
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data };
          });
        })
        .then(function (result) {
          if (!result.ok) {
            graphShowStatus(result.data.error || "error");
            return;
          }
          graphRenderTable(result.data);
        })
        .catch(function (err) {
          graphShowStatus(String(err));
        });
    }

    // Reads graph-f1..f4 and the window inputs, then POSTs to plot.
    function graphPlot() {
      var functions = graphReadFunctions();
      var win = graphReadWindow();
      if (Object.keys(functions).length === 0) {
        graphCtx.clearRect(0, 0, graphCanvas.width, graphCanvas.height);
        graphDrawAxes(win);
        graphTable.innerHTML = "";
        return;
      }
      fetch(GRAPH_PLOT_PATH, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          functions: functions,
          window: win,
          samples: Math.max(2, graphCanvas.width),
        }),
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data };
          });
        })
        .then(function (result) {
          if (!result.ok) {
            graphShowStatus(result.data.error || "error");
            return;
          }
          graphShowStatus("");
          graphRenderPlot(win, result.data);
          graphRefreshTable(functions, win);
        })
        .catch(function (err) {
          graphShowStatus(String(err));
        });
    }

    // Zoom and pan buttons POST to window, update the window inputs from
    // the response, then replot.
    function graphWindowAction(extra) {
      var body = { window: graphReadWindow() };
      Object.keys(extra).forEach(function (key) {
        body[key] = extra[key];
      });
      fetch(GRAPH_WINDOW_PATH, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data };
          });
        })
        .then(function (result) {
          if (!result.ok) {
            graphShowStatus(result.data.error || "error");
            return;
          }
          graphApplyWindow(result.data);
          graphPlot();
        })
        .catch(function (err) {
          graphShowStatus(String(err));
        });
    }

    function graphPan(dxFactor, dyFactor) {
      var win = graphReadWindow();
      graphWindowAction({
        action: "pan",
        dx: (win.xmax - win.xmin) * GRAPH_PAN_FRACTION * dxFactor,
        dy: (win.ymax - win.ymin) * GRAPH_PAN_FRACTION * dyFactor,
      });
    }

    // The graph-analyze button POSTs to analyze using the trace-x value and
    // the first non-empty function, and shows the result as text.
    function graphAnalyze() {
      var expr = graphFirstFunction();
      if (!expr) {
        graphShowStatus("no function to analyze");
        return;
      }
      fetch(GRAPH_ANALYZE_PATH, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          operation: "value",
          f: expr,
          x: parseFloat(graphTraceX.value),
        }),
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data };
          });
        })
        .then(function (result) {
          if (!result.ok) {
            graphShowStatus(result.data.error || "error");
            return;
          }
          var data = result.data;
          if (data.domain_error) {
            graphShowStatus(data.domain_error);
          } else {
            graphShowStatus("x = " + data.x + ", y = " + data.y);
          }
        })
        .catch(function (err) {
          graphShowStatus(String(err));
        });
    }

    graphInputs.concat(graphWindowInputs).forEach(function (input) {
      input.addEventListener("change", graphPlot);
      input.addEventListener("keydown", function (event) {
        if (event.key === "Enter") {
          event.preventDefault();
          graphPlot();
        }
      });
    });

    graphZoomIn.addEventListener("click", function () {
      graphWindowAction({ action: "zoom_in", factor: GRAPH_ZOOM_FACTOR });
    });
    graphZoomOut.addEventListener("click", function () {
      graphWindowAction({ action: "zoom_out", factor: GRAPH_ZOOM_FACTOR });
    });
    graphPanLeft.addEventListener("click", function () {
      graphPan(-1, 0);
    });
    graphPanRight.addEventListener("click", function () {
      graphPan(1, 0);
    });
    graphPanUp.addEventListener("click", function () {
      graphPan(0, 1);
    });
    graphPanDown.addEventListener("click", function () {
      graphPan(0, -1);
    });
    graphAnalyzeButton.addEventListener("click", graphAnalyze);

    // Seed the window inputs from the server's own "standard" window
    // (rather than hard-coding -10..10 here) and draw the initial (empty)
    // plot -- consistent with "the page only draws what the API returns."
    graphWindowAction({ action: "standard" });
  }

  // ---- Lists & Statistics tab: wired to /api/lists and /api/stats/onevar
  // (plan step P18/S2). Wiring /api/stats/regression and stats-canvas is a
  // later step. Same as the Calculator and Graphs tabs above, the page
  // only draws what the API returns -- no client-side math, ever.
  var LISTS_PATH = "/api/lists";
  var STATS_ONEVAR_PATH = "/api/stats/onevar";

  var listsTabButton = document.querySelector('.tab-button[data-tab="tab-lists"]');
  var listGrid = document.getElementById("list-grid");
  var statsList = document.getElementById("stats-list");
  var statsOutput = document.getElementById("stats-output");
  var regressionX = document.getElementById("regression-x");
  var regressionY = document.getElementById("regression-y");

  if (listGrid && statsList && statsOutput) {
    function listsShowStatsError(message) {
      statsOutput.textContent = message || "";
    }

    // Same {"exact","decimal"} formatting rule calcFormatResult above
    // already applies to a /api/calc/evaluate entry: "decimal" is shown
    // alongside "exact" only when they actually differ, so an integer
    // result such as mean=3 (exact "3", decimal "3") shows plainly as "3",
    // never "3 = 3" or a raw "3.0". A plain (non-{exact,decimal}) value
    // such as "n" is just stringified.
    function statsFormatValue(value) {
      if (value && typeof value === "object" && "exact" in value) {
        if (value.decimal && value.decimal !== value.exact) {
          return value.exact + " = " + value.decimal;
        }
        return value.exact;
      }
      return String(value);
    }

    function listsRenderGrid(lists) {
      listGrid.innerHTML = "";
      lists.forEach(function (entry) {
        var block = document.createElement("div");
        var heading = document.createElement("h3");
        heading.textContent = entry.name;
        block.appendChild(heading);
        var valueList = document.createElement("ul");
        (entry.values || []).forEach(function (value) {
          var item = document.createElement("li");
          item.textContent = value;
          valueList.appendChild(item);
        });
        block.appendChild(valueList);
        listGrid.appendChild(block);
      });
    }

    function listsFillSelect(select, lists) {
      if (!select) {
        return;
      }
      select.innerHTML = "";
      lists.forEach(function (entry) {
        var option = document.createElement("option");
        option.value = entry.name;
        option.textContent = entry.name;
        select.appendChild(option);
      });
    }

    // GET /api/lists only returns names (plan step P15/S1) -- each list's
    // own values come from a separate GET /api/lists/<name>, fetched in
    // parallel so list-grid, stats-list, regression-x and regression-y all
    // render/fill once, not one list at a time.
    function loadLists() {
      return fetch(LISTS_PATH)
        .then(function (res) {
          return res.json();
        })
        .then(function (data) {
          var names = data.lists || [];
          return Promise.all(
            names.map(function (name) {
              return fetch(LISTS_PATH + "/" + encodeURIComponent(name)).then(function (res) {
                return res.json();
              });
            })
          );
        })
        .then(function (lists) {
          listsRenderGrid(lists);
          listsFillSelect(statsList, lists);
          listsFillSelect(regressionX, lists);
          listsFillSelect(regressionY, lists);
        });
    }

    function statsRenderOutput(data) {
      statsOutput.innerHTML = "";
      var dl = document.createElement("dl");
      Object.keys(data).forEach(function (key) {
        var dt = document.createElement("dt");
        dt.textContent = key;
        var dd = document.createElement("dd");
        dd.textContent = statsFormatValue(data[key]);
        dl.appendChild(dt);
        dl.appendChild(dd);
      });
      statsOutput.appendChild(dl);
    }

    // The stats-list dropdown's change handler: POSTs the chosen list to
    // /api/stats/onevar and renders the returned statistics verbatim, or
    // the JSON error message from a 400 (e.g. an empty list), into
    // stats-output.
    function statsRefreshOnevar() {
      var name = statsList.value;
      if (!name) {
        statsOutput.innerHTML = "";
        return;
      }
      fetch(STATS_ONEVAR_PATH, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ list: name }),
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data };
          });
        })
        .then(function (result) {
          if (!result.ok) {
            listsShowStatsError(result.data.error || "error");
            return;
          }
          statsRenderOutput(result.data);
        })
        .catch(function (err) {
          listsShowStatsError(String(err));
        });
    }

    statsList.addEventListener("change", statsRefreshOnevar);

    document.addEventListener("DOMContentLoaded", loadLists);
    if (listsTabButton) {
      listsTabButton.addEventListener("click", loadLists);
    }
  }
})();
