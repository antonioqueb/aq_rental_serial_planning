/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onWillStart } from "@odoo/owl";

const STATE_COLORS = {
    soft_hold: "#f0ad4e",
    reserved: "#5bc0de",
    prepared: "#6f42c1",
    picked_up: "#0d6efd",
    delivered: "#20c997",
    in_use: "#198754",
    returned: "#fd7e14",
    released: "#adb5bd",
    quotation: "#ced4da",
    draft: "#dee2e6",
    maintenance: "#6c757d",
};

const STATE_LABELS = {
    soft_hold: "Soft Hold",
    reserved: "Reserved",
    prepared: "Prepared",
    picked_up: "Picked Up",
    delivered: "Delivered",
    in_use: "In Use",
    returned: "Returned (pending review)",
    released: "Released",
    quotation: "Quotation",
    draft: "Draft",
    maintenance: "Maintenance / Downtime",
};

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// --- native-Date helpers (all UTC, to match Odoo's naive UTC datetimes) ---
function pad(n) {
    return String(n).padStart(2, "0");
}
function parseUTC(s) {
    if (!s) {
        return null;
    }
    const hasTZ = /[zZ]$|[+-]\d\d:?\d\d$/.test(s);
    return new Date(hasTZ ? s : s.replace(" ", "T") + "Z");
}
function toServer(d) {
    // -> "YYYY-MM-DD HH:MM:SS" in UTC, the format Odoo expects.
    return d.toISOString().slice(0, 19).replace("T", " ");
}
function isoDate(d) {
    return d.toISOString().slice(0, 10);
}
function dayStartUTC(dateStr) {
    return new Date(dateStr + "T00:00:00Z");
}
function dayEndUTC(dateStr) {
    return new Date(dateStr + "T23:59:59Z");
}
function addDaysUTC(d, n) {
    const x = new Date(d);
    x.setUTCDate(x.getUTCDate() + n);
    return x;
}
function addMonthsUTC(d, n) {
    const x = new Date(d);
    x.setUTCMonth(x.getUTCMonth() + n);
    return x;
}

export class RentalPlanningBoard extends Component {
    static template = "aq_rental_serial_planning.PlanningBoard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        const params = (this.props.action && this.props.action.params) || {};
        const today = isoDate(new Date());

        this.state = useState({
            loading: true,
            zoom: "week",
            dateStart: today,
            dateEnd: isoDate(addDaysUTC(new Date(), 14)),
            products: [],
            expanded: {},
            filters: {
                warehouse_id: params.warehouse_id || null,
                product_ids: params.product_id ? [params.product_id] : null,
                package_id: params.package_id || null,
                partner_id: null,
                states: null,
            },
            meta: { warehouses: [], products: [], packages: [], states: [] },
            selected: null,
            showDowntime: false,
            downtimeForm: { lot_id: null, reason: "maintenance", start: "", end: "" },
        });

        onWillStart(async () => {
            this.state.meta = await this.orm.call(
                "rental.serial.reservation", "board_filters", []);
            await this.loadBoard();
        });
    }

    // ------------------------------------------------------------------
    // Data
    // ------------------------------------------------------------------
    async loadBoard() {
        this.state.loading = true;
        const f = this.state.filters;
        const data = await this.orm.call(
            "rental.serial.reservation", "serial_timeline", [], {
                date_start: toServer(this.rangeStart),
                date_end: toServer(this.rangeEnd),
                product_ids: f.product_ids,
                warehouse_id: f.warehouse_id,
                package_id: f.package_id,
                partner_id: f.partner_id,
                states: f.states,
            });
        this.state.products = data.products;
        for (const p of data.products) {
            if (!(p.product_id in this.state.expanded)) {
                this.state.expanded[p.product_id] = data.products.length <= 3;
            }
        }
        this.state.loading = false;
    }

    // ------------------------------------------------------------------
    // Time axis
    // ------------------------------------------------------------------
    get rangeStart() {
        return dayStartUTC(this.state.dateStart);
    }
    get rangeEnd() {
        return dayEndUTC(this.state.dateEnd);
    }
    get spanMs() {
        return Math.max(this.rangeEnd.getTime() - this.rangeStart.getTime(), 1);
    }

    get columns() {
        const cols = [];
        let cursor = this.rangeStart;
        const endMs = this.rangeEnd.getTime();
        let guard = 0;
        while (cursor.getTime() < endMs && guard < 400) {
            const dow = cursor.getUTCDay();
            cols.push({
                key: isoDate(cursor),
                label: this.state.zoom === "month"
                    ? `${MONTHS[cursor.getUTCMonth()]} ${cursor.getUTCFullYear()}`
                    : `${WEEKDAYS[dow]} ${pad(cursor.getUTCDate())}`,
                left: ((cursor.getTime() - this.rangeStart.getTime()) / this.spanMs) * 100,
                isWeekend: dow === 0 || dow === 6,
            });
            cursor = this.state.zoom === "month"
                ? addMonthsUTC(cursor, 1) : addDaysUTC(cursor, 1);
            guard++;
        }
        return cols;
    }

    blockStyle(block) {
        const s = parseUTC(block.start).getTime();
        const e = parseUTC(block.end).getTime();
        const startMs = Math.max(s, this.rangeStart.getTime());
        const endMs = Math.min(e, this.rangeEnd.getTime());
        const left = ((startMs - this.rangeStart.getTime()) / this.spanMs) * 100;
        const width = Math.max(((endMs - startMs) / this.spanMs) * 100, 0.6);
        const color = block.conflict ? "#dc3545" : (STATE_COLORS[block.state] || "#0d6efd");
        return `left:${left}%;width:${width}%;background:${color};`;
    }

    blockTitle(block) {
        const label = STATE_LABELS[block.state] || block.state;
        const partner = block.partner ? ` — ${block.partner}` : "";
        const conflict = block.conflict ? " ⚠ CONFLICT" : "";
        return `${block.name} [${label}]${partner}${conflict}`;
    }

    // ------------------------------------------------------------------
    // Interactions
    // ------------------------------------------------------------------
    toggleProduct(productId) {
        this.state.expanded[productId] = !this.state.expanded[productId];
    }

    onBlockClick(block) {
        this.state.selected = block;
        this.state.showDowntime = false;
    }

    closePanel() {
        this.state.selected = null;
    }

    async refresh() {
        await this.loadBoard();
    }

    setZoom(zoom) {
        this.state.zoom = zoom;
        const start = this.rangeStart;
        if (zoom === "day") {
            this.state.dateEnd = isoDate(addDaysUTC(start, 2));
        } else if (zoom === "week") {
            this.state.dateEnd = isoDate(addDaysUTC(start, 14));
        } else {
            this.state.dateEnd = isoDate(addMonthsUTC(start, 3));
        }
        this.loadBoard();
    }

    shift(direction) {
        const days = this.state.zoom === "month" ? 30 : (this.state.zoom === "week" ? 7 : 1);
        this.state.dateStart = isoDate(addDaysUTC(this.rangeStart, direction * days));
        this.state.dateEnd = isoDate(addDaysUTC(this.rangeEnd, direction * days));
        this.loadBoard();
    }

    onFilterChange(field, ev) {
        const val = ev.target.value;
        this.state.filters[field] = val ? (field === "states" ? [val] : parseInt(val)) : null;
        this.loadBoard();
    }

    onDateChange(field, ev) {
        this.state[field] = ev.target.value;
        this.loadBoard();
    }

    // ------------------------------------------------------------------
    // Quick actions
    // ------------------------------------------------------------------
    openSaleOrder(block) {
        if (!block.sale_order_id) {
            this.notification.add("No sale order linked.", { type: "warning" });
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "sale.order",
            res_id: block.sale_order_id,
            views: [[false, "form"]],
        });
    }

    openReservation(block) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: block.type === "downtime"
                ? "rental.serial.downtime" : "rental.serial.reservation",
            res_id: block.id,
            views: [[false, "form"]],
        });
    }

    async releaseReservation(block) {
        try {
            await this.orm.call("rental.serial.reservation", "release_reservations",
                [[block.id]]);
            this.notification.add("Serial released.", { type: "success" });
            this.state.selected = null;
            await this.loadBoard();
        } catch (e) {
            this.notification.add("Release failed: " + (e.message || e), { type: "danger" });
        }
    }

    startDowntime(lotId) {
        const now = new Date();
        const local = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
            + `T${pad(now.getHours())}:${pad(now.getMinutes())}`;
        this.state.showDowntime = true;
        this.state.downtimeForm = { lot_id: lotId, reason: "maintenance", start: local, end: "" };
    }

    async submitDowntime() {
        const f = this.state.downtimeForm;
        if (!f.lot_id || !f.start) {
            this.notification.add("Serial and start are required.", { type: "warning" });
            return;
        }
        try {
            await this.orm.call("rental.serial.reservation", "create_downtime_quick", [], {
                lot_id: f.lot_id,
                reason: f.reason,
                start: toServer(new Date(f.start)),
                end: f.end ? toServer(new Date(f.end)) : null,
            });
            this.notification.add("Downtime created.", { type: "success" });
            this.state.showDowntime = false;
            await this.loadBoard();
        } catch (e) {
            this.notification.add("Could not create downtime: " + (e.message || e), { type: "danger" });
        }
    }

    get legend() {
        return Object.keys(STATE_LABELS).map((k) => ({
            key: k, label: STATE_LABELS[k], color: STATE_COLORS[k],
        }));
    }
}

registry.category("actions").add("aq_rental_planning_board", RentalPlanningBoard);
