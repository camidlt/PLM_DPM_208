// Baie de cellules en direct : interroge le serveur toutes les 2 s et anime chaque module
// avec une balistique pondérée (masse, amortissement, léger dépassement), jamais un saut instantané.
(function () {
  var roots = document.querySelectorAll("[data-live]");
  if (!roots.length) return;
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var LABEL = { OK: "Nominal", WARNING: "Surveillance", CRITICAL: "Critique" };

  function fmtTs(v) {
    if (!v) return "";
    var s = String(v).replace("Z", "").split("T");
    if (s.length < 2) return v;
    var d = s[0].split("-");
    return "Dernière mesure " + d[2] + "/" + d[1] + "/" + d[0] + " " + s[1].slice(0, 8);
  }

  function Cell(el) {
    this.el = el;
    this.max = parseFloat(el.dataset.max) || 2;
    this.cur = parseFloat(el.dataset.r) || 0;
    this.target = this.cur;
    this.vel = 0;
    this.val = el.querySelector("[data-val]");
    this.fill = el.querySelector(".fill");
    this.trace = el.querySelector("svg.trace polyline");
    this.health = el.querySelector("[data-health-label]");
    this.temp = el.querySelector("[data-temp]");
    el.style.setProperty("--maxp", "50%");
    this.paint();
  }
  Cell.prototype.pct = function (r) { return Math.max(0, Math.min(100, r / (this.max * 2) * 100)); };
  Cell.prototype.paint = function () {
    var p = this.pct(this.cur);
    this.fill.style.height = p.toFixed(1) + "%";
    this.el.style.setProperty("--w", p.toFixed(1) + "%");
    this.val.textContent = Math.max(0, this.cur).toFixed(2);
  };
  // ressort amorti : k raideur, c amortissement (sous-critique, donc léger dépassement)
  Cell.prototype.step = function (dt) {
    var k = 70, c = 11;
    var a = k * (this.target - this.cur) - c * this.vel;
    this.vel += a * dt;
    this.cur += this.vel * dt;
    if (Math.abs(this.target - this.cur) < 0.002 && Math.abs(this.vel) < 0.01) {
      this.cur = this.target; this.vel = 0; this.paint(); return false;
    }
    this.paint();
    return true;
  };
  Cell.prototype.update = function (m) {
    if (m.rmax) this.max = m.rmax;
    if (m.r !== null && m.r !== undefined) this.target = m.r;
    var h = m.health || "OK";
    this.el.dataset.health = h;
    if (this.health) this.health.textContent = LABEL[h] || h;
    if (this.temp && m.t !== null && m.t !== undefined) this.temp.textContent = Number(m.t).toFixed(1) + " °C";
    if (this.trace && m.points && m.points.length > 1) {
      var self = this, n = m.points.length;
      this.trace.setAttribute("points", m.points.map(function (pt, i) {
        var y = 30 - self.pct(pt.r) * 0.3;
        return (i / (n - 1) * 100).toFixed(1) + "," + y.toFixed(1);
      }).join(" "));
    }
    if (reduce) { this.cur = this.target; this.paint(); }
  };

  roots.forEach(function (root) {
    var cells = {};
    root.querySelectorAll(".cell[data-index]").forEach(function (el) { cells[el.dataset.index] = new Cell(el); });
    var dev = root.querySelector("[data-device]");
    var summary = root.querySelector("[data-summary]");
    var running = false, last = 0;

    function loop(t) {
      var dt = Math.min(0.05, (t - last) / 1000 || 0.016);
      last = t;
      var moving = false;
      Object.keys(cells).forEach(function (k) { if (cells[k].step(dt)) moving = true; });
      if (moving) requestAnimationFrame(loop); else running = false;
    }
    function kick() { if (!running && !reduce) { running = true; last = performance.now(); requestAnimationFrame(loop); } }

    function apply(data) {
      if (!data || !data.modules) return;
      var over = 0;
      data.modules.forEach(function (m) {
        if (cells[m.index]) cells[m.index].update(m);
        if (m.r !== null && m.rmax && m.r > m.rmax) over++;
      });
      if (summary) {
        summary.textContent = over ? over + (over > 1 ? " modules hors seuil" : " module hors seuil") : "Modules dans les tolérances";
        summary.className = "badge " + (over ? "st-Waste" : "st-RECEIVED");
      }
      if (dev) {
        dev.dataset.online = data.online ? "true" : "false";
        dev.querySelector("[data-dev-state]").textContent = data.online ? "BMS ESP32 en ligne" : "BMS hors ligne";
        var d = data.device;
        dev.querySelector("[data-dev-detail]").textContent = d
          ? d.source + " · " + d.packets + " paquets · vu il y a " + Math.round(d.ageSeconds) + " s"
          : "En attente de l'ESP32 sur /api/telemetry";
        dev.querySelector("[data-dev-last]").textContent = fmtTs(data.lastTelemetryAt);
      }
      kick();
    }

    function poll() {
      if (document.hidden) return;
      fetch(root.dataset.live, { headers: { Accept: "application/json" }, credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(apply)
        .catch(function () {});
    }
    poll();
    setInterval(poll, 2000);
  });
})();
