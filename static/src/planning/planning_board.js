/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onWillStart, onMounted, onWillUnmount } from "@odoo/owl";

// --- Humanized states (never show technical values to the user) ---
const RENTAL_STATE_LABELS = {
    draft: "Borrador",
    quotation: "Cotización",
    soft_hold: "Apartado temporal",
    reserved: "Reservado",
    prepared: "Preparado",
    picked_up: "Retirado",
    delivered: "Entregado",
    in_use: "En uso",
    returned: "Devuelto por revisar",
    released: "Liberado",
    cancelled: "Cancelado",
    maintenance: "Mantenimiento / Bloqueo",
    conflict: "Conflicto",
};

const STATE_OPERATIONAL_HINT = {
    reserved: "Reservado (serie bloqueada)",
    prepared: "Preparado en almacén",
    picked_up: "Retirado del almacén",
    delivered: "Entregado / instalado",
    in_use: "En uso durante el evento",
    returned: "Devuelto, pendiente de revisión",
    released: "Liberado y disponible",
    soft_hold: "Apartado temporal",
};

const REASON_LABELS = {
    maintenance: "Mantenimiento",
    cleaning: "Limpieza",
    repair: "Reparación",
    damaged: "Dañado",
    lost: "Perdido",
    internal_use: "Uso interno",
    other: "Otro",
};

// Hex mirror of the SCSS palette (used for legend swatches only).
const STATE_COLORS = {
    draft: "#cbd5e1", quotation: "#94a3b8", soft_hold: "#f59e0b",
    reserved: "#38bdf8", prepared: "#7c3aed", picked_up: "#2563eb",
    delivered: "#10b981", in_use: "#15803d", returned: "#f97316",
    released: "#d1d5db", maintenance: "#4b5563", conflict: "#dc2626",
};

const LEGEND_GROUPS = [
    { title: "Comercial", states: ["draft", "quotation", "soft_hold"] },
    { title: "Operación", states: ["reserved", "prepared", "picked_up", "delivered", "in_use"] },
    { title: "Cierre", states: ["returned", "released"] },
    { title: "Incidencias", states: ["maintenance", "conflict"] },
];

// Severity for picking a representative state on a serial row.
const STATE_PRIORITY = {
    in_use: 7, delivered: 6, picked_up: 5, prepared: 4,
    reserved: 3, returned: 2, soft_hold: 1,
};
const OPERATION_STATES = ["reserved", "prepared", "picked_up", "delivered", "in_use", "returned"];

const WD = ["Dom", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"];
const MO = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
const MO_FULL = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"];
const VIEW_MODES = [
    { key: "timeline", label: "Timeline", icon: "fa-tasks" },
    { key: "month", label: "Mes", icon: "fa-calendar" },
    { key: "agenda", label: "Agenda", icon: "fa-list-ul" },
    { key: "heatmap", label: "Carga", icon: "fa-th" },
    { key: "customer", label: "Cliente", icon: "fa-users" },
];

// ---------- date helpers (UTC-naive in, browser-local out) ----------
function pad(n) { return String(n).padStart(2, "0"); }
function parseUTC(s) {
    if (!s) return null;
    const hasTZ = /[zZ]$|[+-]\d\d:?\d\d$/.test(s);
    return new Date(hasTZ ? s : s.replace(" ", "T") + "Z");
}
function toServer(d) { return d.toISOString().slice(0, 19).replace("T", " "); }
function isoDate(d) { return d.toISOString().slice(0, 10); }
function dayStartUTC(s) { return new Date(s + "T00:00:00Z"); }
function dayEndUTC(s) { return new Date(s + "T23:59:59Z"); }
function addDaysUTC(d, n) { const x = new Date(d); x.setUTCDate(x.getUTCDate() + n); return x; }
function addMonthsUTC(d, n) { const x = new Date(d); x.setUTCMonth(x.getUTCMonth() + n); return x; }

function formatRentalDateTime(dt) {
    if (!dt) return "";
    return `${WD[dt.getDay()]} ${dt.getDate()} ${MO[dt.getMonth()]}, ${pad(dt.getHours())}:${pad(dt.getMinutes())}`;
}
function formatRentalDate(dt) {
    if (!dt) return "";
    return `${WD[dt.getDay()]} ${dt.getDate()} ${MO[dt.getMonth()]}`;
}
function formatRentalDateRange(a, b) {
    return `${formatRentalDateTime(a)} → ${formatRentalDateTime(b)}`;
}
const AVATAR_COLORS = ["#0E7C86", "#7c3aed", "#2563eb", "#db2777", "#ea580c",
                       "#0891b2", "#65a30d", "#9333ea", "#dc2626", "#0d9488"];
function avatarInitials(name) {
    const parts = (name || "?").trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return "?";
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[1][0]).toUpperCase();
}
function avatarColor(name) {
    let h = 0;
    for (let i = 0; i < (name || "").length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
    return AVATAR_COLORS[h % AVATAR_COLORS.length];
}

function getRentalDurationLabel(a, b) {
    let ms = b - a;
    if (ms < 0) ms = 0;
    const days = Math.floor(ms / 86400000);
    const hours = Math.round((ms % 86400000) / 3600000);
    const parts = [];
    if (days) parts.push(days + (days === 1 ? " día" : " días"));
    if (hours) parts.push(hours + " h");
    return parts.length ? parts.join(" ") : "0 h";
}

export class RentalPlanningBoard extends Component {
    static template = "aq_rental_serial_planning.PlanningBoard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.labels = RENTAL_STATE_LABELS;

        const params = (this.props.action && this.props.action.params) || {};
        const today = isoDate(new Date());
        let density = "comfortable";
        try { density = window.localStorage.getItem("aq_rental_density") || "comfortable"; } catch (e) { /* ignore */ }

        this.state = useState({
            loading: true,
            viewMode: "timeline",
            monthProductId: null,
            zoom: "week",
            dateStart: today,
            dateEnd: isoDate(addDaysUTC(new Date(), 14)),
            products: [],
            expanded: {},
            density,
            legendCollapsed: false,
            search: "",
            filters: {
                warehouse_id: params.warehouse_id || null,
                product_ids: params.product_id ? [params.product_id] : null,
                package_id: params.package_id || null,
                partner_id: null,
                states: null,
            },
            meta: { warehouses: [], products: [], packages: [], states: [] },
            selected: null,
            tooltip: null,
            showDowntime: false,
            downtimeForm: { lot_id: null, reason: "maintenance", start: "", end: "" },
        });

        this._onKeydown = (ev) => {
            if (ev.key === "Escape") {
                if (this.state.tooltip) this.state.tooltip = null;
                else if (this.state.showDowntime) this.state.showDowntime = false;
                else if (this.state.selected) this.state.selected = null;
            }
        };

        onWillStart(async () => {
            this.state.meta = await this.orm.call(
                "rental.serial.reservation", "board_filters", []);
            await this.loadBoard();
        });
        onMounted(() => document.addEventListener("keydown", this._onKeydown));
        onWillUnmount(() => document.removeEventListener("keydown", this._onKeydown));
    }

    // ------------------------------------------------------------------
    // Data + decoration (compute everything once per load = memoization)
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
        this._decorate(data.products);
        this.state.products = data.products;
        for (const p of data.products) {
            if (!(p.product_id in this.state.expanded)) {
                this.state.expanded[p.product_id] = data.products.length <= 4;
            }
        }
        this.state.loading = false;
    }

    _decorate(products) {
        const rs = this.rangeStart.getTime();
        const span = this.spanMs;
        for (const product of products) {
            for (const serial of product.serials) {
                // sort blocks by start for conflict pairing
                serial.blocks.sort((a, b) => parseUTC(a.start) - parseUTC(b.start));
                for (let i = 0; i < serial.blocks.length; i++) {
                    const block = serial.blocks[i];
                    const s = parseUTC(block.start), e = parseUTC(block.end);
                    const sMs = Math.max(s.getTime(), rs);
                    const eMs = Math.min(e.getTime(), this.rangeEnd.getTime());
                    const leftPct = ((sMs - rs) / span) * 100;
                    const widthPct = Math.max(((eMs - sMs) / span) * 100, 0.5);
                    block._leftPct = leftPct;
                    block._widthPct = widthPct;
                    block._style = `left:${leftPct}%;width:${widthPct}%;`;
                    block._sizeClass = widthPct < 6 ? "is-compact"
                        : widthPct < 16 ? "is-medium" : "is-wide";
                    block._isDowntime = block.type === "downtime";
                    block._stateKey = block._isDowntime ? "maintenance" : block.state;
                    block._stateClass = `aq_state_${block._stateKey}`;
                    block._stateLabel = RENTAL_STATE_LABELS[block._stateKey] || block._stateKey;
                    block._opLabel = STATE_OPERATIONAL_HINT[block.state] || block._stateLabel;
                    block._reasonLabel = block.reason ? (REASON_LABELS[block.reason] || block.reason) : "";
                    // human dates
                    block._startLabel = formatRentalDateTime(s);
                    block._endLabel = formatRentalDateTime(e);
                    block._rangeLabel = formatRentalDateRange(s, e);
                    block._durationLabel = getRentalDurationLabel(s, e);
                    // billable inner segment (relative to the block)
                    const bs = parseUTC(block.billable_start), be = parseUTC(block.billable_end);
                    if (bs && be && e > s) {
                        const total = e.getTime() - s.getTime();
                        const segL = Math.max(((bs.getTime() - s.getTime()) / total) * 100, 0);
                        const segR = Math.min(((be.getTime() - s.getTime()) / total) * 100, 100);
                        block._billableStyle = `left:${segL}%;width:${Math.max(segR - segL, 1)}%;`;
                        block._billableLabel = bs.toDateString() === be.toDateString()
                            ? `${formatRentalDate(bs)}, ${pad(bs.getHours())}:${pad(bs.getMinutes())}–${pad(be.getHours())}:${pad(be.getMinutes())}`
                            : formatRentalDateRange(bs, be);
                    } else {
                        block._billableStyle = null;
                        block._billableLabel = "";
                    }
                    // precomputed booleans (avoid `and` in OWL templates)
                    block._overdueOnly = !!block.overdue && !block.conflict;
                    block._hasSaleOrder = !block._isDowntime && !!block.sale_order_id;
                    block._blocking = block._isDowntime
                        || OPERATION_STATES.includes(block.state)
                        || block.state === "soft_hold";
                    // conflict partner (overlap with a sibling on the same serial)
                    block._conflictWith = "";
                    if (block.conflict) {
                        for (let j = 0; j < serial.blocks.length; j++) {
                            if (j === i) continue;
                            const o = serial.blocks[j];
                            if (parseUTC(o.start) < e && parseUTC(o.end) > s) {
                                block._conflictWith = o.name;
                                break;
                            }
                        }
                    }
                }
                this._classifySerial(serial);
            }
            this._summarizeProduct(product);
        }
    }

    _classifySerial(serial) {
        const blocking = serial.blocks.filter(
            (b) => b._isDowntime || OPERATION_STATES.includes(b.state) || b.state === "soft_hold");
        serial._isBlocked = blocking.length > 0;
        serial._hasConflict = serial.blocks.some((b) => b.conflict);
        serial._hasMaint = serial.blocks.some((b) => b._isDowntime);
        serial._hasOverdue = serial.blocks.some((b) => b.overdue);
        let rep = "available";
        if (serial._hasConflict) rep = "conflict";
        else if (serial._hasMaint) rep = "maintenance";
        else {
            let best = -1;
            for (const b of blocking) {
                const p = STATE_PRIORITY[b.state] || 0;
                if (p > best) { best = p; rep = b.state; }
            }
        }
        serial._badgeState = rep;
        serial._badgeLabel = RENTAL_STATE_LABELS[rep] || "Disponible";
        serial._badgeClass = `aq_serial_badge aq_state_${rep}`;
    }

    _summarizeProduct(product) {
        const total = product.serials.length;
        const blocked = product.serials.filter((s) => s._isBlocked).length;
        const available = total - blocked;
        let badge = "is-ok";
        if (available === 0) badge = "is-full";
        else if (blocked > 0) badge = "is-warning";
        product._summary = { total, blocked, available, badge };
    }

    // ------------------------------------------------------------------
    // Derived view data
    // ------------------------------------------------------------------
    get searching() { return this.state.search.trim().length > 0; }

    get filteredProducts() {
        const q = this.state.search.trim().toLowerCase();
        if (!q) return this.state.products;
        const out = [];
        for (const p of this.state.products) {
            const pMatch = (p.product_name || "").toLowerCase().includes(q)
                || (p.sku || "").toLowerCase().includes(q);
            if (pMatch) { out.push(p); continue; }
            const serials = p.serials.filter((s) =>
                (s.lot_name || "").toLowerCase().includes(q)
                || s.blocks.some((b) => (b.partner || "").toLowerCase().includes(q)
                    || (b.name || "").toLowerCase().includes(q)));
            if (serials.length) out.push(Object.assign({}, p, { serials }));
        }
        return out;
    }

    isExpanded(product) {
        return this.searching || !!this.state.expanded[product.product_id];
    }

    get kpis() {
        let visible = 0, available = 0, occupied = 0, soft = 0, conflict = 0, maint = 0;
        for (const p of this.filteredProducts) {
            for (const s of p.serials) {
                visible++;
                if (s._hasConflict) conflict++;
                else if (s._hasMaint) maint++;
                else if (s._badgeState === "soft_hold") soft++;
                else if (s._isBlocked) occupied++;
                else available++;
            }
        }
        return [
            { key: "visible", label: "Items visibles", value: visible, cls: "", icon: "fa-barcode" },
            { key: "available", label: "Disponibles", value: available, cls: "is-ok", icon: "fa-check-circle" },
            { key: "occupied", label: "Ocupados", value: occupied, cls: "is-busy", icon: "fa-cube" },
            { key: "soft", label: "Apartados", value: soft, cls: "is-warn", icon: "fa-hourglass-half" },
            { key: "conflict", label: "Conflictos", value: conflict, cls: conflict ? "is-danger" : "", icon: "fa-exclamation-triangle" },
            { key: "maint", label: "Mantenimiento", value: maint, cls: maint ? "is-muted" : "", icon: "fa-wrench" },
        ];
    }

    get activeFilterChips() {
        const chips = [];
        const f = this.state.filters;
        const wh = this.state.meta.warehouses.find((w) => w.id === f.warehouse_id);
        chips.push({ key: "wh", label: "Almacén", value: wh ? wh.name : "Todos", active: !!wh });
        const pkg = this.state.meta.packages.find((p) => p.id === f.package_id);
        chips.push({ key: "pkg", label: "Paquete", value: pkg ? pkg.name : "Todos", active: !!pkg });
        const st = f.states && f.states.length
            ? (this.state.meta.states.find((s) => s.key === f.states[0]) || {}).label
            : null;
        chips.push({ key: "st", label: "Estado", value: st || "Todos", active: !!st });
        return chips;
    }

    get hasActiveFilters() {
        const f = this.state.filters;
        return !!(f.warehouse_id || f.package_id || (f.states && f.states.length) || f.partner_id);
    }

    get legendGroups() {
        return LEGEND_GROUPS.map((g) => ({
            title: g.title,
            items: g.states.map((s) => ({
                key: s, label: RENTAL_STATE_LABELS[s], color: STATE_COLORS[s],
                cls: `aq_state_${s}`,
            })),
        }));
    }

    // ------------------------------------------------------------------
    // Time axis
    // ------------------------------------------------------------------
    get rangeStart() { return dayStartUTC(this.state.dateStart); }
    get rangeEnd() { return dayEndUTC(this.state.dateEnd); }
    get spanMs() { return Math.max(this.rangeEnd.getTime() - this.rangeStart.getTime(), 1); }

    get columns() {
        const cols = [];
        const todayISO = isoDate(new Date());
        let cursor = this.rangeStart;
        const endMs = this.rangeEnd.getTime();
        let guard = 0;
        while (cursor.getTime() < endMs && guard < 400) {
            const dow = cursor.getUTCDay();
            const key = isoDate(cursor);
            cols.push({
                key,
                label: this.state.zoom === "month"
                    ? `${MO[cursor.getUTCMonth()]} ${cursor.getUTCFullYear()}`
                    : `${WD[dow]} ${pad(cursor.getUTCDate())}`,
                left: ((cursor.getTime() - this.rangeStart.getTime()) / this.spanMs) * 100,
                isWeekend: dow === 0 || dow === 6,
                isToday: key === todayISO,
            });
            cursor = this.state.zoom === "month" ? addMonthsUTC(cursor, 1) : addDaysUTC(cursor, 1);
            guard++;
        }
        return cols;
    }

    get todayLineLeft() {
        const now = Date.now();
        if (now < this.rangeStart.getTime() || now > this.rangeEnd.getTime()) return null;
        return ((now - this.rangeStart.getTime()) / this.spanMs) * 100;
    }

    get densityClass() {
        return this.state.density === "compact"
            ? "is-density-compact" : "is-density-comfortable";
    }

    blockClass(block) {
        let c = `aq_reservation_block ${block._stateClass} ${block._sizeClass}`;
        if (block._isDowntime) c += " aq_is_downtime";
        if (block.conflict) c += " has-conflict";
        if (block.overdue) c += " is-overdue";
        return c;
    }

    // ==================================================================
    // Alternate view modes (all derived from the already-loaded data)
    // ==================================================================
    get viewModes() { return VIEW_MODES; }
    get showStateLegend() { return ["timeline", "customer"].includes(this.state.viewMode); }
    get showZoom() { return this.state.viewMode !== "month"; }
    get isTimelineLike() { return ["timeline", "customer", "heatmap", "agenda"].includes(this.state.viewMode); }

    setViewMode(mode) {
        this.state.viewMode = mode;
        if (mode === "month") {
            const d = dayStartUTC(this.state.dateStart);
            const first = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1));
            const last = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0));
            this.state.dateStart = isoDate(first);
            this.state.dateEnd = isoDate(last);
            if (!this.state.monthProductId && this.state.products.length) {
                this.state.monthProductId = this.state.products[0].product_id;
            }
            this.loadBoard();
        }
    }
    nav(dir) {
        if (this.state.viewMode === "month") this.monthShift(dir);
        else this.shift(dir);
    }
    monthShift(dir) {
        const d = dayStartUTC(this.state.dateStart);
        const first = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + dir, 1));
        const last = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + dir + 1, 0));
        this.state.dateStart = isoDate(first);
        this.state.dateEnd = isoDate(last);
        this.loadBoard();
    }
    onMonthProductChange(ev) { this.state.monthProductId = parseInt(ev.target.value); }

    // --- shared day axis ---
    get rangeDays() {
        const out = [];
        let cur = this.rangeStart;
        const end = this.rangeEnd.getTime();
        const todayISO = isoDate(new Date());
        let guard = 0;
        while (cur.getTime() < end && guard < 92) {
            const dow = cur.getUTCDay();
            const key = isoDate(cur);
            out.push({
                key, ms: cur.getTime(),
                label: `${WD[dow]} ${pad(cur.getUTCDate())}`,
                full: `${WD[dow]} ${cur.getUTCDate()} ${MO[cur.getUTCMonth()]}`,
                isWeekend: dow === 0 || dow === 6,
                isToday: key === todayISO,
            });
            cur = addDaysUTC(cur, 1);
            guard++;
        }
        return out;
    }

    _dayBusy(product, ds, de) {
        let busy = 0;
        for (const s of product.serials) {
            for (const b of s.blocks) {
                if (b._blocking
                    && parseUTC(b.start).getTime() < de
                    && parseUTC(b.end).getTime() > ds) { busy++; break; }
            }
        }
        return busy;
    }
    _level(busy, total) {
        if (!total) return "none";
        const r = busy / total;
        if (r >= 1) return "full";
        if (r >= 0.66) return "high";
        if (r >= 0.33) return "mid";
        if (r > 0) return "low";
        return "free";
    }

    // --- month (availability calendar for one product) ---
    get monthProducts() { return this.state.products; }
    get monthProduct() {
        return this.state.products.find((p) => p.product_id === this.state.monthProductId)
            || this.state.products[0] || null;
    }
    get monthLabel() {
        const d = dayStartUTC(this.state.dateStart);
        return `${MO_FULL[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
    }
    get monthWeeks() {
        const product = this.monthProduct;
        const d = dayStartUTC(this.state.dateStart);
        const year = d.getUTCFullYear(), month = d.getUTCMonth();
        const startDow = (new Date(Date.UTC(year, month, 1)).getUTCDay() + 6) % 7; // Monday=0
        const daysInMonth = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
        const todayISO = isoDate(new Date());
        const cells = [];
        for (let i = 0; i < startDow; i++) cells.push(null);
        for (let day = 1; day <= daysInMonth; day++) {
            const ds = Date.UTC(year, month, day);
            const total = product ? product.serials.length : 0;
            const busy = product ? this._dayBusy(product, ds, ds + 86400000) : 0;
            const dow = new Date(ds).getUTCDay();
            const level = this._level(busy, total);
            const isToday = isoDate(new Date(ds)) === todayISO;
            const isWeekend = dow === 0 || dow === 6;
            cells.push({
                key: `${year}-${month}-${day}`, day,
                total, busy, free: total - busy, level, isToday, isWeekend,
                pct: total ? Math.round((busy / total) * 100) : 0,
                cls: `aq_month_cell lvl-${level}`
                    + (isToday ? " is-today" : "")
                    + (isWeekend ? " is-weekend" : ""),
            });
        }
        while (cells.length % 7) cells.push(null);
        const weeks = [];
        for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
        return weeks;
    }
    monthDayDrill() {
        const p = this.monthProduct;
        if (p) this.state.filters.product_ids = [p.product_id];
        this.state.viewMode = "timeline";
        this.loadBoard();
    }

    // --- heatmap (products x days, occupation level) ---
    get heatmapRows() {
        const days = this.rangeDays;
        return this.filteredProducts.map((p) => ({
            product: p,
            total: p.serials.length,
            cells: days.map((day) => {
                const total = p.serials.length;
                const busy = this._dayBusy(p, day.ms, day.ms + 86400000);
                return { key: day.key, busy, total, free: total - busy, level: this._level(busy, total) };
            }),
        }));
    }
    heatDrill(product) {
        this.state.filters.product_ids = [product.product_id];
        this.state.viewMode = "timeline";
        this.loadBoard();
    }

    // --- agenda (operational day list) ---
    _agendaItem(g) {
        return {
            label: `${g.count}× ${g.product}`,
            partner: g.partner, order: g.order,
            stateLabel: RENTAL_STATE_LABELS[g.state] || g.state,
            rep: g.rep,
        };
    }
    get agendaDays() {
        const inRange = new Set(this.rangeDays.map((d) => d.key));
        const buckets = {};
        const ensure = (k) => buckets[k] || (buckets[k] = { salidas: {}, retornos: {} });
        const push = (side, gkey, b) => {
            side[gkey] || (side[gkey] = {
                count: 0, product: b.product_name, partner: b.partner,
                order: b.sale_order, state: b.state, rep: b.id,
            });
            side[gkey].count++;
        };
        for (const p of this.filteredProducts) {
            for (const s of p.serials) {
                for (const b of s.blocks) {
                    if (b._isDowntime) continue;
                    const gkey = (b.sale_order || b.partner || "—") + "|" + (b.product_name || "");
                    const startKey = isoDate(parseUTC(b.start));
                    const endKey = isoDate(parseUTC(b.end));
                    if (inRange.has(startKey)) push(ensure(startKey).salidas, gkey, b);
                    if (inRange.has(endKey)) push(ensure(endKey).retornos, gkey, b);
                }
            }
        }
        const res = [];
        for (const d of this.rangeDays) {
            const e = buckets[d.key];
            if (!e) continue;
            const sal = Object.values(e.salidas), ret = Object.values(e.retornos);
            if (!sal.length && !ret.length) continue;
            res.push({
                key: d.key, label: d.full, isToday: d.isToday,
                salidas: sal.map((g) => this._agendaItem(g)),
                retornos: ret.map((g) => this._agendaItem(g)),
            });
        }
        return res;
    }
    agendaOpen(rep) {
        this.action.doAction({
            type: "ir.actions.act_window", res_model: "rental.serial.reservation",
            res_id: rep, views: [[false, "form"]],
        });
    }

    // --- group by customer / order (swimlanes) ---
    get customerGroups() {
        const groups = new Map();
        for (const p of this.filteredProducts) {
            for (const s of p.serials) {
                for (const b of s.blocks) {
                    const isMaint = b._isDowntime;
                    const key = isMaint ? "__maint" : (b.partner || "—");
                    const title = isMaint ? "Mantenimiento / Bloqueos" : (b.partner || "Sin cliente");
                    if (!groups.has(key)) groups.set(key, { key, title, isMaint, serials: new Map() });
                    const g = groups.get(key);
                    if (!g.serials.has(s.lot_id)) {
                        g.serials.set(s.lot_id, {
                            lot_id: s.lot_id, lot_name: s.lot_name,
                            product_name: p.product_name, blocks: [],
                        });
                    }
                    g.serials.get(s.lot_id).blocks.push(b);
                }
            }
        }
        return [...groups.values()]
            .map((g) => ({
                key: g.key, title: g.title, isMaint: g.isMaint,
                initials: g.isMaint ? "" : avatarInitials(g.title),
                avatarColor: g.isMaint ? "#64748b" : avatarColor(g.title),
                serials: [...g.serials.values()],
            }))
            .sort((a, b) => (a.isMaint ? 1 : 0) - (b.isMaint ? 1 : 0) || a.title.localeCompare(b.title));
    }

    // ------------------------------------------------------------------
    // Interactions
    // ------------------------------------------------------------------
    toggleProduct(productId) {
        this.state.expanded[productId] = !this.state.expanded[productId];
    }
    onBlockClick(block) { this.state.selected = block; this.state.tooltip = null; this.state.showDowntime = false; }
    closePanel() { this.state.selected = null; }
    async refresh() { await this.loadBoard(); }

    setDensity(d) {
        this.state.density = d;
        try { window.localStorage.setItem("aq_rental_density", d); } catch (e) { /* ignore */ }
    }
    toggleLegend() { this.state.legendCollapsed = !this.state.legendCollapsed; }
    onSearch(ev) { this.state.search = ev.target.value; }
    clearSearch() { this.state.search = ""; }

    setZoom(zoom) {
        this.state.zoom = zoom;
        const start = this.rangeStart;
        this.state.dateEnd = isoDate(
            zoom === "day" ? addDaysUTC(start, 2)
                : zoom === "week" ? addDaysUTC(start, 14) : addMonthsUTC(start, 3));
        this.loadBoard();
    }
    shift(direction) {
        const days = this.state.zoom === "month" ? 30 : (this.state.zoom === "week" ? 7 : 1);
        this.state.dateStart = isoDate(addDaysUTC(this.rangeStart, direction * days));
        this.state.dateEnd = isoDate(addDaysUTC(this.rangeEnd, direction * days));
        this.loadBoard();
    }
    goToday() {
        this.state.dateStart = isoDate(new Date());
        if (this.state.viewMode === "month") this.setViewMode("month");
        else this.setZoom(this.state.zoom);
    }
    onFilterChange(field, ev) {
        const val = ev.target.value;
        this.state.filters[field] = val ? (field === "states" ? [val] : parseInt(val)) : null;
        this.loadBoard();
    }
    clearFilters() {
        this.state.filters.warehouse_id = null;
        this.state.filters.package_id = null;
        this.state.filters.states = null;
        this.state.filters.partner_id = null;
        this.loadBoard();
    }
    onDateChange(field, ev) { this.state[field] = ev.target.value; this.loadBoard(); }

    // ------------------------------------------------------------------
    // Tooltip (on demand; positioned once on enter, not on mousemove)
    // ------------------------------------------------------------------
    onBlockEnter(ev, block) {
        const x = Math.min(ev.clientX + 16, window.innerWidth - 340);
        const y = Math.min(ev.clientY + 14, window.innerHeight - 240);
        this.state.tooltip = { block, x: Math.max(x, 8), y: Math.max(y, 8) };
    }
    onBlockLeave() { this.state.tooltip = null; }

    // ------------------------------------------------------------------
    // Quick actions
    // ------------------------------------------------------------------
    openSaleOrder(block) {
        if (!block.sale_order_id) {
            this.notification.add("No hay pedido de venta vinculado.", { type: "warning" });
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window", res_model: "sale.order",
            res_id: block.sale_order_id, views: [[false, "form"]],
        });
    }
    openReservation(block) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: block.type === "downtime" ? "rental.serial.downtime" : "rental.serial.reservation",
            res_id: block.id, views: [[false, "form"]],
        });
    }
    async releaseReservation(block) {
        try {
            await this.orm.call("rental.serial.reservation", "release_reservations", [[block.id]]);
            this.notification.add("Serie liberada.", { type: "success" });
            this.state.selected = null;
            await this.loadBoard();
        } catch (e) {
            this.notification.add("No se pudo liberar: " + (e.message || e), { type: "danger" });
        }
    }
    viewConflict(block) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Conflictos de la serie",
            res_model: "rental.serial.reservation",
            views: [[false, "list"], [false, "form"]],
            domain: [["lot_id.name", "=", block.lot_name], ["conflict_status", "=", "conflict"]],
        });
    }
    viewHistory(serial) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Historial · " + serial.lot_name,
            res_model: "rental.serial.reservation",
            views: [[false, "list"], [false, "form"]],
            domain: [["lot_id", "=", serial.lot_id]],
        });
    }
    reserveSerial(serial, product) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Nueva reserva · " + serial.lot_name,
            res_model: "rental.serial.reservation",
            views: [[false, "form"]],
            target: "current",
            context: {
                default_product_id: product.product_id,
                default_lot_id: serial.lot_id,
                default_reservation_block_start: toServer(this.rangeStart),
                default_reservation_block_end: toServer(this.rangeEnd),
            },
        });
    }
    viewAvailability(product) {
        this.state.search = "";
        this.state.filters.product_ids = [product.product_id];
        this.loadBoard();
    }
    async copySerial(serial) {
        try {
            await navigator.clipboard.writeText(serial.lot_name);
            this.notification.add(`Copiado: ${serial.lot_name}`, { type: "success" });
        } catch (e) {
            this.notification.add("No se pudo copiar.", { type: "warning" });
        }
    }

    // ------------------------------------------------------------------
    // Downtime quick form
    // ------------------------------------------------------------------
    startDowntime(lotId) {
        const now = new Date();
        const local = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
            + `T${pad(now.getHours())}:${pad(now.getMinutes())}`;
        this.state.showDowntime = true;
        this.state.selected = null;
        this.state.downtimeForm = { lot_id: lotId, reason: "maintenance", start: local, end: "" };
    }
    async submitDowntime() {
        const f = this.state.downtimeForm;
        if (!f.lot_id || !f.start) {
            this.notification.add("La serie y la fecha de inicio son obligatorias.", { type: "warning" });
            return;
        }
        try {
            await this.orm.call("rental.serial.reservation", "create_downtime_quick", [], {
                lot_id: f.lot_id, reason: f.reason,
                start: toServer(new Date(f.start)),
                end: f.end ? toServer(new Date(f.end)) : null,
            });
            this.notification.add("Bloqueo creado.", { type: "success" });
            this.state.showDowntime = false;
            await this.loadBoard();
        } catch (e) {
            this.notification.add("No se pudo crear el bloqueo: " + (e.message || e), { type: "danger" });
        }
    }
}

registry.category("actions").add("aq_rental_planning_board", RentalPlanningBoard);
