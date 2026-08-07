(function () {
  var ROWS_PER_PAGE = 50;

  function paginate(table) {
    var tbody = table.querySelector("tbody");
    if (!tbody) return;
    var rows = Array.prototype.slice.call(tbody.querySelectorAll("tr"));
    if (rows.length <= ROWS_PER_PAGE) return;

    var pageCount = Math.ceil(rows.length / ROWS_PER_PAGE);
    var wrapper = table.parentElement;
    var nav = wrapper.querySelector(".releases-pagination");
    if (nav) nav.remove();

    nav = document.createElement("div");
    nav.className = "releases-pagination";
    wrapper.appendChild(nav);

    function showPage(page) {
      var start = (page - 1) * ROWS_PER_PAGE;
      var end = start + ROWS_PER_PAGE;
      rows.forEach(function (row, i) {
        row.style.display = i >= start && i < end ? "" : "none";
      });
      renderControls(page);
      table.scrollIntoView({ block: "nearest" });
    }

    function button(label, page, opts) {
      opts = opts || {};
      var btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = label;
      if (opts.ariaLabel) btn.setAttribute("aria-label", opts.ariaLabel);
      if (opts.disabled) {
        btn.disabled = true;
      } else {
        btn.addEventListener("click", function () {
          showPage(page);
        });
      }
      if (opts.active) btn.classList.add("is-active");
      return btn;
    }

    function renderControls(current) {
      while (nav.firstChild) nav.removeChild(nav.firstChild);
      nav.appendChild(
        button("‹ Prev", current - 1, {
          disabled: current === 1,
          ariaLabel: "Previous page",
        })
      );
      for (var p = 1; p <= pageCount; p++) {
        nav.appendChild(button(String(p), p, { active: p === current }));
      }
      nav.appendChild(
        button("Next ›", current + 1, {
          disabled: current === pageCount,
          ariaLabel: "Next page",
        })
      );
    }

    showPage(1);
  }

  function init() {
    var wrapper = document.getElementById("releases-table");
    if (!wrapper) return;
    var table = wrapper.querySelector("table");
    if (!table) return;
    paginate(table);
  }

  if (window.document$) {
    document$.subscribe(init);
  } else {
    document.addEventListener("DOMContentLoaded", init);
  }
})();
