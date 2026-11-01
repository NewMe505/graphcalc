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
})();
