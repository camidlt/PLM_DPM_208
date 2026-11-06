// QR codes affichés dans les passeports (librairie qrcodejs chargée en local)
document.querySelectorAll("[data-qr]").forEach(function (el) {
  if (typeof QRCode === "undefined") { el.classList.add("no-lib"); return; }
  new QRCode(el, { text: el.dataset.qr, width: 96, height: 96, correctLevel: QRCode.CorrectLevel.M });
});

// Scanner QR par la caméra (html5-qrcode). Fonctionne sur webcam PC et mobile
(function () {
  var btn = document.getElementById("start-scan");
  if (!btn) return;
  btn.addEventListener("click", function () {
    if (typeof Html5Qrcode === "undefined") {
      alert("Scanner indisponible. Saisissez l'identifiant ci-dessous.");
      return;
    }
    btn.disabled = true;
    var scanner = new Html5Qrcode("reader");

    var onScanSuccess = function (text) {
      scanner.stop().finally(function () {
        window.location = "/scan?code=" + encodeURIComponent(text);
      });
    };

    var onScanError = function (err) {
      btn.disabled = false;
      alert("Impossible d'ouvrir la webcam : " + err);
    };

    Html5Qrcode.getCameras().then(function (cameras) {
      var camConfig = (cameras && cameras.length > 0) ? cameras[0].id : { facingMode: "user" };
      scanner.start(camConfig, { fps: 10, qrbox: 240 }, onScanSuccess).catch(onScanError);
    }).catch(function () {
      scanner.start({ facingMode: "user" }, { fps: 10, qrbox: 240 }, onScanSuccess).catch(onScanError);
    });
  });
})();

// Notifications in-app du propriétaire : rafraîchit le compteur toutes les 10 s
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

// Défi 1 : rafraîchit l'affichage et le statut du test en temps réel sans clignotement
(function () {
  var el = document.querySelector("[data-live-telemetry]");
  if (!el) return;
  var bid = el.dataset.liveTelemetry;
  var last = el.dataset.last;
  var prevTestState = null;
  var isReloading = false;

  setInterval(function () {
    if (isReloading) return;
    fetch("/api/battery/" + encodeURIComponent(bid) + "/telemetry?limit=1")
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d) return;

        // Mise à jour fluide du badge et du décompte en direct SANS recharger la page
        if (d.test_status) {
          var badge = document.getElementById("bms-test-status-badge");
          var text = document.getElementById("bms-status-text");
          if (badge && text) {
            text.textContent = d.test_status.label;
            badge.className = "bms-status-badge " + d.test_status.css_class;
          }

          var st = d.test_status.state;

          // Si le test vient de se terminer (transition de RUNNING vers COMPLETED ou ALERT)
          if (prevTestState === "RUNNING" && (st === "COMPLETED" || st === "ALERT")) {
            prevTestState = st;
            isReloading = true;
            // Délai fluide pour que l'opérateur voie le passage au statut terminé
            setTimeout(function () { window.location.reload(); }, 600);
            return;
          }

          prevTestState = st;

          // PENDANT QUE LE TEST TOURNE : AUCUN RELOAD DE PAGE (supprime tout clignotement)
          if (st === "RUNNING") {
            return;
          }
        }

        // Hors test actif : recharge une seule fois si une nouvelle mesure est archivée
        if (d.readings && d.readings.length > 0) {
          var newest = d.readings[d.readings.length - 1].at;
          if (last && newest !== last) {
            last = newest;
            isReloading = true;
            window.location.reload();
          }
        }
      }).catch(function () {});
  }, 1000);
})();
