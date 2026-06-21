/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onWillStart } from "@odoo/owl";

// Shared semantic state palette (MUST match the planning board / calendar).
const STATE_COLORS = {
    draft: "#cbd5e1", quotation: "#94a3b8", soft_hold: "#f59e0b", reserved: "#38bdf8",
    prepared: "#7c3aed", picked_up: "#2563eb", delivered: "#10b981", in_use: "#15803d",
    returned: "#f97316", released: "#d1d5db", maintenance: "#4b5563", conflict: "#dc2626",
};

// ---- reusable formatting / classification helpers ----
function formatNumber(v) { return Number(v || 0).toLocaleString("es-MX", { maximumFractionDigits: 0 }); }
function getUtilizationStatus(p) {
    if (p < 20) return { label: "Utilización baja", cls: "is-low" };
    if (p < 60) return { label: "Utilización saludable", cls: "is-healthy" };
    if (p < 85) return { label: "Alta utilización", cls: "is-high" };
    return { label: "Riesgo de saturación", cls: "is-saturated" };
}
function getOccupancyLevel(p) {
    if (p >= 100) return "is-full";
    if (p >= 80) return "is-high";
    if (p >= 50) return "is-warning";
    return "is-normal";
}
function isoDay(d) { return d.toISOString().slice(0, 10); }
function serverNow() { return new Date().toISOString().slice(0, 19).replace("T", " "); }

export class RentalKpiDashboard extends Component {
    static template = "aq_rental_serial_planning.KpiDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ loading: true, error: false, days: 30, data: null, clientBy: "count" });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.error = false;
        try {
            this.state.data = await this.orm.call(
                "rental.serial.reservation", "planning_dashboard", [], { days: this.state.days });
        } catch (e) {
            this.state.error = true;
        }
        this.state.loading = false;
    }
    setDays(d) { this.state.days = d; this.load(); }
    refresh() { this.load(); }

    // ---- formatting exposed to template ----
    fmt(v) { return formatNumber(v); }
    money(v) { return (this.state.data.currency || "") + formatNumber(v); }
    stateColor(key) { return STATE_COLORS[key] || "#cbd5e1"; }
    pct(value, max) { return max > 0 ? Math.round((value / max) * 100) : 0; }
    occLevel(p) { return getOccupancyLevel(p); }

    get ready() { return !this.state.loading && !!this.state.data; }
    get periodLabel() { return `Mostrando indicadores de los próximos ${this.state.days} días`; }

    get donutStyle() {
        const u = this.state.data.headline.utilization;
        return `background: conic-gradient(#C9A36A 0 ${u}%, #DCE5DC ${u}% 100%);`;
    }
    get utilStatus() { return getUtilizationStatus(this.state.data.headline.utilization); }

    // breakdown subtitle for "Reservas activas"
    get activeSubtitle() {
        const map = {};
        for (const s of this.state.data.reservations_by_state) map[s.key] = s.count;
        const parts = [];
        if (map.reserved) parts.push(`${map.reserved} reservadas`);
        if (map.prepared) parts.push(`${map.prepared} preparadas`);
        if (map.picked_up) parts.push(`${map.picked_up} retiradas`);
        if (map.delivered) parts.push(`${map.delivered} entregadas`);
        if (map.in_use) parts.push(`${map.in_use} en uso`);
        return parts.join(" · ") || "Sin reservas activas";
    }

    // ---- alert summary ----
    get alerts() {
        const h = this.state.data.headline;
        const out = [];
        if (h.conflicts) out.push({ key: "conflicts", icon: "fa-exclamation-triangle", level: "is-critical", text: `${h.conflicts} conflicto(s) por resolver` });
        if (h.overdue) out.push({ key: "overdue", icon: "fa-clock-o", level: "is-warning", text: `${h.overdue} reserva(s) atrasada(s)` });
        if (h.soft_expiring) out.push({ key: "soft", icon: "fa-hourglass-half", level: "is-warning", text: `${h.soft_expiring} apartado(s) temporal(es) por expirar` });
        if (h.maint_now) out.push({ key: "maint", icon: "fa-wrench", level: "is-info", text: `${h.maint_now} item(s) en mantenimiento` });
        if (h.returns_pending) out.push({ key: "returns", icon: "fa-undo", level: "is-info", text: `${h.returns_pending} retorno(s) pendiente(s) de revisión` });
        return out;
    }
    get hasAlerts() { return this.alerts.length > 0; }

    // ---- KPI cards ----
    get cards() {
        const h = this.state.data.headline;
        return [
            { key: "active", icon: "fa-calendar-check-o", label: "Reservas activas", value: h.active_reservations,
              sub: this.activeSubtitle, sev: "is-info", click: "board",
              tip: "Reservas que bloquean disponibilidad en el periodo seleccionado." },
            { key: "deliv", icon: "fa-truck", label: "Salidas (7 días)", value: h.deliveries_7d,
              sub: "Programadas próximos 7 días", sev: "is-info", click: "deliveries",
              tip: "Equipos con salida programada en los próximos 7 días." },
            { key: "ret", icon: "fa-undo", label: "Retornos (7 días)", value: h.returns_7d,
              sub: "Programados próximos 7 días", sev: "is-info", click: "returns7",
              tip: "Equipos con retorno programado en los próximos 7 días." },
            { key: "items", icon: "fa-barcode", label: "Items gestionados", value: h.total_serials,
              sub: "Seriales rentables planificados", sev: "", click: "board",
              tip: "Total de seriales de productos rentables considerados en la planeación." },
            { key: "conflicts", icon: "fa-exclamation-triangle", label: "Conflictos", value: h.conflicts,
              sub: h.conflicts ? "Requieren revisión inmediata" : "Sin empalmes detectados",
              sev: h.conflicts ? "is-critical" : "is-success", click: "conflicts",
              tip: "Reservas con empalme de la misma serie en periodos que se traslapan." },
            { key: "overdue", icon: "fa-clock-o", label: "Atrasadas", value: h.overdue,
              sub: h.overdue ? "Equipos no devueltos a tiempo" : "Sin atrasos",
              sev: h.overdue ? "is-warning" : "is-success", click: "overdue",
              tip: "Reservas cuyo retorno ya venció y aún no se registra devolución." },
            { key: "soft", icon: "fa-hourglass-half", label: "Apartados por expirar", value: h.soft_expiring,
              sub: h.soft_expiring ? "Confirmar antes de que liberen" : "Sin apartados por expirar",
              sev: h.soft_expiring ? "is-warning" : "", click: "soft",
              tip: "Apartados temporales (soft hold) próximos a expirar automáticamente." },
            { key: "maint", icon: "fa-wrench", label: "En mantenimiento", value: h.maint_now,
              sub: h.damaged_lost ? `${h.damaged_lost} dañados/perdidos` : "Bloqueados por mantenimiento",
              sev: h.maint_now ? "is-warning" : "", click: "maint",
              tip: "Items bloqueados por mantenimiento, limpieza, daño o pérdida." },
            { key: "returns_pending", icon: "fa-inbox", label: "Retornos pendientes", value: h.returns_pending,
              sub: h.returns_pending ? "Por revisar y liberar" : "Sin retornos pendientes",
              sev: h.returns_pending ? "is-warning" : "", click: "returns",
              tip: "Equipos devueltos físicamente que aún no se revisan/liberan." },
        ];
    }

    onCardClick(card) {
        const map = {
            conflicts: () => this.openConflicts(), overdue: () => this.openOverdue(),
            soft: () => this.openSoftHolds(), maint: () => this.openMaintenance(),
            returns: () => this.openReturnsPending(), board: () => this.openBoard(),
            deliveries: () => this.openBoard(), returns7: () => this.openBoard(),
        };
        (map[card.click] || (() => this.openBoard()))();
    }
    onAlertClick(alert) {
        this.onCardClick({ click: alert.key === "soft" ? "soft" : alert.key });
    }

    // ---- clients toggle ----
    setClientBy(c) { this.state.clientBy = c; }
    get clients() {
        const arr = [...this.state.data.top_customers];
        const k = this.state.clientBy;
        arr.sort((a, b) => (b[k] || 0) - (a[k] || 0));
        return arr;
    }
    clientSub(c) {
        if (c.value > 0) return `${this.fmt(c.count)} reservas · ${this.money(c.value)} estimado`;
        return `${this.fmt(c.count)} reservas · ${this.fmt(c.items)} items bloqueados`;
    }

    // ---- maxes ----
    get demandMax() { return Math.max(1, ...this.state.data.demand.map((d) => d.count)); }
    get productsMax() { return Math.max(1, ...this.state.data.top_products.map((p) => p.count)); }
    get clientsMax() { return Math.max(1, ...this.clients.map((c) => c[this.state.clientBy] || 0)); }

    demandTip(d) {
        return `Semana del ${d.label}\n${d.count} items bloqueados\n${d.customers} cliente(s)`;
    }

    // ---- navigation with context ----
    get periodRange() {
        const s = new Date(); const e = new Date(); e.setDate(e.getDate() + this.state.days);
        return { start: isoDay(s), end: isoDay(e) };
    }
    openBoard(extra = {}) {
        const r = this.periodRange;
        this.action.doAction({
            type: "ir.actions.client", tag: "aq_rental_planning_board",
            params: Object.assign({ date_start: r.start, date_end: r.end }, extra),
        });
    }
    openProduct(p) { this.openBoard({ product_id: p.product_id }); }
    openWeek(d) {
        const s = new Date(); s.setDate(s.getDate() + d.week_index * 7);
        const e = new Date(s); e.setDate(e.getDate() + 7);
        this.openBoard({ date_start: isoDay(s), date_end: isoDay(e) });
    }
    _openReservations(name, domain) {
        this.action.doAction({
            type: "ir.actions.act_window", name, res_model: "rental.serial.reservation",
            domain, views: [[false, "list"], [false, "form"]],
        });
    }
    openConflicts() { this._openReservations("Conflictos", [["conflict_status", "=", "conflict"]]); }
    openOverdue() {
        this._openReservations("Reservas atrasadas", [
            ["state", "in", ["picked_up", "delivered", "in_use"]],
            ["reservation_block_end", "<", serverNow()],
            ["actual_return_datetime", "=", false]]);
    }
    openSoftHolds() { this._openReservations("Apartados temporales", [["state", "=", "soft_hold"]]); }
    openReturnsPending() { this._openReservations("Retornos pendientes", [["state", "=", "returned"]]); }
    openCustomer(c) { this._openReservations("Reservas · " + c.name, [["partner_id", "=", c.partner_id]]); }
    openMaintenance() {
        this.action.doAction({
            type: "ir.actions.act_window", name: "Mantenimiento / Bloqueos",
            res_model: "rental.serial.downtime",
            domain: [["state", "in", ["scheduled", "in_progress"]]],
            views: [[false, "list"], [false, "form"]],
        });
    }
}

registry.category("actions").add("aq_rental_kpi_dashboard", RentalKpiDashboard);
