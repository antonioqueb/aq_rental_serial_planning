/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onWillStart } from "@odoo/owl";

// Getting Ready palette — warm editorial funnel (champagne -> caramel)
const STATE_COLORS = {
    quotation: "#E0D5C2", soft_hold: "#D8B98C", reserved: "#CBB596",
    prepared: "#C7A578", picked_up: "#BE9466", delivered: "#B07F50",
    in_use: "#9E6A3E", returned: "#C79A6B", released: "#CFCABF",
};

export class RentalKpiDashboard extends Component {
    static template = "aq_rental_serial_planning.KpiDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ loading: true, days: 30, data: null });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.data = await this.orm.call(
            "rental.serial.reservation", "planning_dashboard", [], { days: this.state.days });
        this.state.loading = false;
    }
    setDays(d) { this.state.days = d; this.load(); }
    refresh() { this.load(); }
    openBoard() {
        this.action.doAction({ type: "ir.actions.client", tag: "aq_rental_planning_board" });
    }

    // ------------------------------------------------------------------
    money(v) {
        const n = Number(v || 0);
        return (this.state.data.currency || "") + n.toLocaleString("es-MX", { maximumFractionDigits: 0 });
    }
    stateColor(key) { return STATE_COLORS[key] || "#cbd5e1"; }
    pct(value, max) { return max > 0 ? Math.round((value / max) * 100) : 0; }
    utilColor(pct) {
        // warm scale: taupe -> gold -> caramel -> warm brick
        return pct >= 85 ? "#A8442E" : pct >= 60 ? "#A86F45" : pct >= 30 ? "#C79A6B" : "#B8A995";
    }

    get donutStyle() {
        const u = this.state.data.headline.utilization;
        return `background: conic-gradient(#C79A6B 0 ${u}%, #E8DFD0 ${u}% 100%);`;
    }

    get cards() {
        const h = this.state.data.headline;
        return [
            { key: "serials", icon: "fa-barcode", label: "Items gestionados", value: h.total_serials, cls: "" },
            { key: "active", icon: "fa-calendar-check-o", label: "Reservas activas", value: h.active_reservations, cls: "is-busy" },
            { key: "deliv", icon: "fa-truck", label: "Salidas (7 días)", value: h.deliveries_7d, cls: "is-info" },
            { key: "ret", icon: "fa-undo", label: "Retornos (7 días)", value: h.returns_7d, cls: "is-info" },
            { key: "overdue", icon: "fa-clock-o", label: "Atrasadas", value: h.overdue, cls: h.overdue ? "is-danger" : "is-ok" },
            { key: "conflicts", icon: "fa-exclamation-triangle", label: "Conflictos", value: h.conflicts, cls: h.conflicts ? "is-danger" : "is-ok" },
            { key: "soft", icon: "fa-hourglass-half", label: "Apartados temporales", value: h.soft_holds, cls: "is-warn", sub: h.soft_expiring ? h.soft_expiring + " por expirar" : "" },
            { key: "maint", icon: "fa-wrench", label: "En mantenimiento", value: h.maint_now, cls: "is-muted", sub: h.damaged_lost ? h.damaged_lost + " dañados/perdidos" : "" },
        ];
    }

    get stateMax() { return Math.max(1, ...this.state.data.reservations_by_state.map((s) => s.count)); }
    get demandMax() { return Math.max(1, ...this.state.data.demand.map((d) => d.count)); }
    get productsMax() { return Math.max(1, ...this.state.data.top_products.map((p) => p.count)); }
    get customersMax() { return Math.max(1, ...this.state.data.top_customers.map((c) => c.count)); }
}

registry.category("actions").add("aq_rental_kpi_dashboard", RentalKpiDashboard);
