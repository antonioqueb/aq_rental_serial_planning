/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onWillStart } from "@odoo/owl";

const STATUS = {
    saturated: { label: "Saturado", cls: "st-saturated" },
    shortage_risk: { label: "Riesgo de shortage", cls: "st-shortage" },
    dead_stock: { label: "Producto muerto", cls: "st-dead" },
    low_rotation: { label: "Baja rotación", cls: "st-low" },
    healthy: { label: "Saludable", cls: "st-ok" },
};

function fmtNum(v) { return Number(v || 0).toLocaleString("es-MX", { maximumFractionDigits: 0 }); }

export class RentalCommercialReports extends Component {
    static template = "aq_rental_serial_planning.CommercialReports";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ loading: true, error: false, days: 90, data: null });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.error = false;
        try {
            this.state.data = await this.orm.call(
                "rental.serial.reservation", "commercial_reports", [], { days: this.state.days });
        } catch (e) {
            this.state.error = true;
        }
        this.state.loading = false;
    }
    setDays(d) { this.state.days = d; this.load(); }
    refresh() { this.load(); }
    openBoard() { this.action.doAction({ type: "ir.actions.client", tag: "aq_rental_planning_board" }); }

    fmt(v) { return fmtNum(v); }
    money(v) { return (this.state.data.currency || "") + fmtNum(v); }
    statusLabel(s) { return (STATUS[s] || { label: s }).label; }
    statusClass(s) { return (STATUS[s] || { cls: "" }).cls; }
    pct(v, max) { return max > 0 ? Math.round((v / max) * 100) : 0; }

    get ready() { return !this.state.loading && !!this.state.data; }
    get catMax() { return Math.max(1, ...this.state.data.category_utilization.map((c) => c.revenue)); }
    get projMax() { return Math.max(1, ...this.state.data.projected.map((p) => p.confirmed + p.quotes)); }
}

registry.category("actions").add("aq_rental_commercial_reports", RentalCommercialReports);
