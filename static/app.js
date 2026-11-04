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

// Propriétaire : compteur de demandes en attente, rafraîchi toutes les 10 s
(function () {
  var counter = document.querySelector(".bell .count");
  if (!counter) return;
  setInterval(function () {
    fetch("/api/notifications/count").then(function (r) { return r.json(); }).then(function (d) {
      var before = parseInt(counter.dataset.n, 10);
      counter.dataset.n = d.pending;
      counter.textContent = d.pending;
      if (d.pending > before && document.title.indexOf("(") !== 0) {
        document.title = "(" + d.pending + ") " + document.title;
      }
    }).catch(function () {});
  }, 10000);
})();
