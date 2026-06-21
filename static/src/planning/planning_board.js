/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { Component, useState, onWillStart } from "@odoo/owl";
import { DateTime } from "luxon";

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

export class RentalPlanningBoard extends Component {
    static template = "aq_rental_serial_planning.PlanningBoard";
    static props = ["*"];

    setup() {
        this.action = useService("action");
        this.notification = useService("notification");

        const params = (this.props.action && this.props.action.params) || {};
        // Work in UTC for all positioning math so the percentage offsets match
        // the UTC-naive datetimes Odoo returns. (Odoo stores/returns UTC.)
        const today = DateTime.utc().startOf("day");

        this.state = useState({
            loading: true,
            zoom: "week",                       // day | week | month
            dateStart: today.toISODate(),
            dateEnd: today.plus({ days: 14 }).toISODate(),
            products: [],
            expanded: {},                       // productId -> bool
            filters: {
                warehouse_id: params.warehouse_id || null,
                product_ids: params.product_id ? [params.product_id] : null,
                package_id: params.package_id || null,
                partner_id: params.sale_order_id ? null : null,
                states: null,
            },
            meta: { warehouses: [], products: [], packages: [], states: [] },
            selected: null,                     // selected block detail
            showDowntime: false,
            downtimeForm: { lot_id: null, reason: "maintenance", start: "", end: "" },
        });

        onWillStart(async () => {
            this.state.meta = await rpc("/rental_serial_planning/filters", {});
            await this.loadBoard();
        });
    }

    // ------------------------------------------------------------------
    // Data
    // ------------------------------------------------------------------
    async loadBoard() {
        this.state.loading = true;
        const f = this.state.filters;
        const data = await rpc("/rental_serial_planning/serial_timeline", {
            date_start: this.toServer(this.rangeStart),
            date_end: this.toServer(this.rangeEnd),
            product_ids: f.product_ids,
            warehouse_id: f.warehouse_id,
            package_id: f.package_id,
            partner_id: f.partner_id,
            states: f.states,
        });
        this.state.products = data.products;
        // Expand products with few serials by default for first load.
        for (const p of data.products) {
            if (!(p.product_id in this.state.expanded)) {
                this.state.expanded[p.product_id] = data.products.length <= 3;
            }
        }
        this.state.loading = false;
    }

    // ------------------------------------------------------------------
    // Time axis helpers
    // ------------------------------------------------------------------
    toServer(dt) {
        // Odoo expects a UTC-naive 'YYYY-MM-DD HH:mm:ss' string.
        return dt.toUTC().toFormat("yyyy-MM-dd HH:mm:ss");
    }

    get rangeStart() {
        return DateTime.fromISO(this.state.dateStart, { zone: "utc" }).startOf("day");
    }
    get rangeEnd() {
        return DateTime.fromISO(this.state.dateEnd, { zone: "utc" }).endOf("day");
    }
    get spanMs() {
        return Math.max(this.rangeEnd.toMillis() - this.rangeStart.toMillis(), 1);
    }

    get columns() {
        const cols = [];
        const unit = this.state.zoom === "month" ? "month"
            : this.state.zoom === "week" ? "day" : "day";
        let cursor = this.rangeStart;
        let guard = 0;
        while (cursor < this.rangeEnd && guard < 400) {
            const next = cursor.plus(this.state.zoom === "month" ? { months: 1 } : { days: 1 });
            cols.push({
                key: cursor.toISODate(),
                label: this.state.zoom === "month"
                    ? cursor.toFormat("LLL yyyy")
                    : cursor.toFormat("ccc dd"),
                left: ((cursor.toMillis() - this.rangeStart.toMillis()) / this.spanMs) * 100,
                isWeekend: cursor.weekday >= 6,
            });
            cursor = next;
            guard++;
        }
        return cols;
    }

    blockStyle(block) {
        const s = DateTime.fromISO(block.start, { zone: "utc" }).toMillis();
        const e = DateTime.fromISO(block.end, { zone: "utc" }).toMillis();
        const start = Math.max(s, this.rangeStart.toMillis());
        const end = Math.min(e, this.rangeEnd.toMillis());
        const left = ((start - this.rangeStart.toMillis()) / this.spanMs) * 100;
        const width = Math.max(((end - start) / this.spanMs) * 100, 0.6);
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
            this.state.dateEnd = start.plus({ days: 2 }).toISODate();
        } else if (zoom === "week") {
            this.state.dateEnd = start.plus({ days: 14 }).toISODate();
        } else {
            this.state.dateEnd = start.plus({ months: 3 }).toISODate();
        }
        this.loadBoard();
    }

    shift(direction) {
        const days = this.state.zoom === "month" ? 30 : (this.state.zoom === "week" ? 7 : 1);
        this.state.dateStart = this.rangeStart.plus({ days: direction * days }).toISODate();
        this.state.dateEnd = this.rangeEnd.plus({ days: direction * days }).toISODate();
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
            res_model: block.type === "downtime" ? "rental.serial.downtime" : "rental.serial.reservation",
            res_id: block.id,
            views: [[false, "form"]],
        });
    }

    async releaseReservation(block) {
        try {
            await rpc("/rental_serial_planning/release", { reservation_ids: [block.id] });
            this.notification.add("Serial released.", { type: "success" });
            this.state.selected = null;
            await this.loadBoard();
        } catch (e) {
            this.notification.add("Release failed: " + (e.message || e), { type: "danger" });
        }
    }

    startDowntime(lotId) {
        this.state.showDowntime = true;
        this.state.downtimeForm = {
            lot_id: lotId,
            reason: "maintenance",
            start: DateTime.now().toFormat("yyyy-MM-dd'T'HH:mm"),
            end: "",
        };
    }

    async submitDowntime() {
        const f = this.state.downtimeForm;
        if (!f.lot_id || !f.start) {
            this.notification.add("Serial and start are required.", { type: "warning" });
            return;
        }
        try {
            await rpc("/rental_serial_planning/create_downtime", {
                lot_id: f.lot_id,
                reason: f.reason,
                start: this.toServer(DateTime.fromISO(f.start)),
                end: f.end ? this.toServer(DateTime.fromISO(f.end)) : null,
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
