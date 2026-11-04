// Défi 3 : onglets du panneau de décision (l'onglet actif est gardé dans l'URL)
document.querySelectorAll("[data-tabs]").forEach(function (bar) {
  var root = bar.parentElement;
  bar.querySelectorAll("[data-tab]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var key = btn.dataset.tab;
      bar.querySelectorAll("[data-tab]").forEach(function (b) { b.setAttribute("aria-selected", b === btn); });
      root.querySelectorAll("[data-panel]").forEach(function (p) { p.hidden = p.dataset.panel !== key; });
      var url = new URL(window.location); url.searchParams.set("tab", key);
      history.replaceState(null, "", url.pathname + url.search + "#decision");
      root.querySelectorAll('input[name="tab"]').forEach(function (i) { i.value = key; });
    });
  });
});
