const params = new URLSearchParams(location.search);
const BID = params.get("id") || "DLR-1985";

async function api(path, { method = "GET", body, role } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (role) headers["X-Role"] = role;
  const r = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}

function fmtTs(ts) {
  if (!ts) return "—";
  return new Date(ts).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "medium" });
}

function ago(ts) {
  if (!ts) return "aucune mesure";
  const s = Math.round((Date.now() - new Date(ts)) / 1000);
  return s < 60 ? `il y a ${s}s` : `il y a ${Math.round(s / 60)} min`;
}

function statusBadge(s) { return `<span class="badge s-${s}">${s || "?"}</span>`; }

const EVENT_LABELS = {
  MANUFACTURED: "🏗️ Fabrication",
  DIAGNOSIS_REPORTED: "🔧 Diagnostic remonté par le garagiste",
  STATUS_CHANGED: "📝 Statut modifié par le propriétaire",
  RECEIVED: "📦 Réception au centre de tri",
  RECYCLING_STARTED: "♻️ Recyclage lancé",
};

function timeline(events) {
  if (!events.length) return `<p class="muted">Aucun événement.</p>`;
  return `<ul class="timeline">${events.map(e => `
    <li><b>${EVENT_LABELS[e.type] || e.type}</b><br>${e.details || ""}
    <div class="ts">${fmtTs(e.ts)} · ${e.by || e.role}</div></li>`).join("")}</ul>`;
}

function identity(p) {
  const b = p.battery, dp = p.dynamicPerformance || {};
  return `<div class="kv">
    <span>Battery ID</span><span><b>${b.batteryId}</b></span>
    <span>Passeport</span><span>${b.batteryPassportId || "—"}</span>
    <span>Modèle</span><span>${p.model?.name || "—"}</span>
    <span>Catégorie</span><span>${p.type?.name || "—"}</span>
    <span>N° de série</span><span>${b.serialNumber || "—"}</span>
    <span>Détenteur</span><span>${b.currentHolder || "—"}</span>
    <span>SOCE / SOC</span><span>${dp.soce ?? "—"} % / ${dp.soc ?? "—"} %</span>
    <span>Statut</span><span>${statusBadge(b.status)}</span>
  </div>`;
}

function materials(names, pcts) {
  return (names || []).map((n, i) => `${n} (${pcts?.[i] ?? "?"} %)`).join(", ") || "—";
}

function techSheet(p) {
  const sp = p.staticPerformance || {}, sd = p.staticDurability || {}, cf = p.carbonFootprint || {};
  const c = p.composition || {}, cert = p.certification || {}, circ = p.circularity || {};
  const o = p.operator || {}, b = p.battery, dd = p.dynamicDurability || {};
  return `<div class="kv">
    <span>Fabricant</span><span>${p.company?.name || "—"}</span>
    <span>Opérateur éco.</span><span>${o.name || "—"} · ${o.country || ""} · ${o.email || ""}</span>
    <span>Fabrication</span><span>${b.manufacturingDate || "—"} · ${b.manufacturingPlace || ""}</span>
    <span>Poids</span><span>${b.weightKg ?? "—"} kg</span>
    <span>Tension min/nom/max</span><span>${sp.minimalVoltage ?? "—"} / ${sp.nominalVoltage ?? "—"} / ${sp.maximalVoltage ?? "—"} V</span>
    <span>R interne max/module</span><span>${sp.maxInternalResistance ?? "—"} mΩ</span>
    <span>Durée de vie attendue</span><span>${sd.expectedBatteryLifetimeCycles ?? "—"} cycles (essai à ${sd.cRateRelevantCycleLifeTest ?? "?"} C)</span>
    <span>Garantie</span><span>${dd.warranty || "—"} · ${dd.accidents || ""}</span>
    <span>Chimie</span><span><b>${c.batteryChemistry || "—"}</b></span>
    <span>Cathode</span><span>${materials(c.cathode?.cathodeMaterialsList, c.cathode?.percentageList)}</span>
    <span>Anode</span><span>${materials(c.anode?.anodeMaterialsList, c.anode?.percentageList)}</span>
    <span>Électrolyte</span><span>${materials(c.electrolyte?.electrolyteMaterialsList, c.electrolyte?.percentageList)}</span>
    <span>Empreinte carbone</span><span>${cf.carbonFootprintDeclared ?? "—"} ${cf.unit || ""} · classe <b>${cf.performanceClass || "—"}</b></span>
    <span>Agent extincteur</span><span>${circ.extinguishAgent || "—"}</span>
    <span>Déclaration UE</span><span>${cert.EUDeclarationOfConformityId || "—"}</span>
    <span>Symbole collecte</span><span>${cert.separateCollectionSymbol || "—"}</span>
  </div>`;
}

function moduleCards(p) {
  const rmax = p.staticPerformance?.maxInternalResistance || 25;
  return p.modules.map(m => {
    const r = m.lastResistance;
    const pct = r == null ? 0 : Math.min(100, (r / (rmax * 2)) * 100);
    const color = m.health === "CRITICAL" ? "var(--crit)" : m.health === "WARNING" ? "var(--warn)" : "var(--ok)";
    return `<div class="module ${m.health || "OK"}">
      <div class="name">Module ${m.position}</div>
      <div class="val">${r == null ? "—" : r.toFixed(1)} <span class="unit">mΩ</span></div>
      <div class="bar"><div style="width:${pct}%;background:${color}"></div><span class="lim" style="left:50%"></span></div>
      <div class="muted" style="margin-top:6px">${m.lastTemperature == null ? "" : m.lastTemperature.toFixed(1) + " °C · "}max ${rmax} mΩ</div>
      <div class="health">${m.health || "OK"}</div>
    </div>`;
  }).join("");
}

function toast(msg) {
  let t = document.querySelector(".toast");
  if (!t) { t = document.createElement("div"); t.className = "toast"; document.body.appendChild(t); }
  t.textContent = msg; t.style.display = "block";
  clearTimeout(t._h); t._h = setTimeout(() => (t.style.display = "none"), 3500);
}
