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
})();
