// Scanner QR par la caméra (html5-qrcode). Le navigateur n'autorise la caméra que sur
// https:// ou http://localhost ; sinon, utiliser l'appareil photo natif ou la saisie.
(function () {
  var btn = document.getElementById("start-scan");
  if (!btn) return;
  btn.addEventListener("click", function () {
    if (typeof Html5Qrcode === "undefined") {
      alert("Scanner indisponible (pas d'accès internet ?). Saisissez l'identifiant.");
      return;
    }
    if (!window.isSecureContext) {
      alert("Le navigateur bloque la caméra hors https ou localhost. Scannez le QR code avec " +
            "l'appareil photo du téléphone, ou saisissez l'identifiant.");
      return;
    }
    btn.disabled = true;
    var scanner = new Html5Qrcode("reader");
    scanner.start({ facingMode: "environment" }, { fps: 10, qrbox: 220 }, function (text) {
      scanner.stop().finally(function () {
        window.location = "/scan?code=" + encodeURIComponent(text);
      });
    }).catch(function (err) {
      btn.disabled = false;
      alert("Impossible d'ouvrir la caméra : " + err);
    });
  });
})();

// Compteurs : demandes en attente (propriétaire) et notifications non lues (tous les rôles),
// rafraîchis toutes les 10 s
(function () {
  var counter = document.querySelector(".bell .count");
  var unread = document.querySelector("[data-unread]");
  if (!counter && !unread) return;
  setInterval(function () {
    if (document.hidden) return;
    fetch("/api/notifications/count", { headers: { Accept: "application/json" } })
      .then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
        if (!d) return;
        if (counter) {
          var before = parseInt(counter.dataset.n, 10);
          counter.dataset.n = d.pending;
          counter.textContent = d.pending;
          if (d.pending > before && document.title.indexOf("(") !== 0) {
            document.title = "(" + d.pending + ") " + document.title;
          }
        }
        if (unread && d.unread !== undefined) {
          unread.dataset.n = d.unread;
          unread.textContent = d.unread;
        }
      }).catch(function () {});
  }, 10000);
})();

// Signalement garagiste : champs date et créneau visibles seulement si la collecte est automatique
// (délégation : le panneau peut être rechargé en direct par live.js)
(function () {
  function sync() {
    var sw = document.getElementById("auto_logistics");
    var fields = document.getElementById("auto-fields");
    if (sw && fields) fields.hidden = !sw.checked;
  }
  document.addEventListener("change", function (e) { if (e.target && e.target.id === "auto_logistics") sync(); });
  document.addEventListener("report:refreshed", sync);
  sync();
})();
