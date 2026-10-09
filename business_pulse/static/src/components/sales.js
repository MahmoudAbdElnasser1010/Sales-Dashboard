/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { computeDelta, formatDate, formatExact, formatRange, formatShare, formatValue } from "../utils/format";

class SalesSection extends Component {
    money(value, currencyId = this.props.currencyId) {
        return formatValue(value, "monetary", currencyId, { compact: true });
    }
    exact(value, currencyId = this.props.currencyId) {
        return formatExact(value, "monetary", currencyId);
    }
    count(value) {
        return formatValue(value, "count");
    }
    pct(value) {
        return value === null || value === undefined ? "—" : formatShare(value);
    }
    open(action) {
        if (action) {
            this.props.onOpen(action);
        }
    }
}

export class Funnel extends SalesSection {
    static template = "business_pulse.Funnel";
    static props = { data: Object, currencyId: { type: Number, optional: true }, onOpen: Function };

    get delta() {
        const { rate, compare_rate: cmp } = this.props.data;
        return computeDelta(rate, cmp, "rate", "up");
    }
    get days() {
        const d = this.props.data.avg_days_to_confirm;
        return d === null || d === undefined ? "—" : formatValue(Math.round(d * 10) / 10, "count");
    }
    width(stage) {
        return `${Math.max(stage.share * 100, stage.count ? 1.5 : 0).toFixed(2)}%`;
    }
}

export class QuotationAging extends SalesSection {
    static template = "business_pulse.QuotationAging";
    static props = { data: Object, currencyId: { type: Number, optional: true }, onOpen: Function, onOpenRecord: Function };

    get maxBucket() {
        return Math.max(1, ...this.props.data.buckets.map((b) => b.value));
    }
    width(bucket) {
        return `${((bucket.value / this.maxBucket) * 100).toFixed(2)}%`;
    }
    validity(row) {
        return row.validity_date ? formatDate(row.validity_date) : "—";
    }
    ageLabel(row) {
        return row.age === null ? "—" : _t("%(days)s d", { days: row.age });
    }
}

const STATUS = {
    achieved: { label: _t("Achieved"), icon: "fa-check-circle", tone: "good" },
    on_track: { label: _t("On track"), icon: "fa-arrow-circle-up", tone: "good" },
    behind: { label: _t("Behind"), icon: "fa-exclamation-triangle", tone: "warning" },
    missed: { label: _t("Missed"), icon: "fa-times-circle", tone: "bad" },
    upcoming: { label: _t("Not started"), icon: "fa-clock-o", tone: "neutral" },
};

export function targetStatus(key) {
    return STATUS[key] || STATUS.upcoming;
}

export class TargetProgress extends Component {
    static template = "business_pulse.TargetProgress";
    static props = { target: Object, compact: { type: Boolean, optional: true } };

    get status() {
        return targetStatus(this.props.target.status);
    }
    get fill() {
        return `${Math.min(this.props.target.completion * 100, 100).toFixed(2)}%`;
    }
    get pace() {
        return `${Math.min(this.props.target.elapsed * 100, 100).toFixed(2)}%`;
    }
    fmt(value) {
        const t = this.props.target;
        return formatValue(value, t.kind, t.currency_id, { compact: true });
    }
    exact(value) {
        const t = this.props.target;
        return formatExact(value, t.kind, t.currency_id);
    }
    get completion() {
        return formatShare(this.props.target.completion);
    }
    get summary() {
        const t = this.props.target;
        return _t("%(actual)s of %(amount)s (%(completion)s). Expected by now: %(expected)s. Status: %(status)s.", {
            actual: this.exact(t.actual),
            amount: this.exact(t.amount),
            completion: this.completion,
            expected: this.exact(t.expected),
            status: this.status.label,
        });
    }
}

export class TargetsPanel extends Component {
    static template = "business_pulse.TargetsPanel";
    static components = { TargetProgress };
    static props = { data: Object, onOpen: Function };

    range(t) {
        return formatRange(t.date_from, t.date_to);
    }
}

const SORTERS = {
    name: (i) => (i.name || "").toLowerCase(),
    value: (i) => i.value,
    orders: (i) => i.orders,
    aov: (i) => i.aov ?? -Infinity,
    conversion: (i) => i.conversion ?? -Infinity,
    pipeline: (i) => i.pipeline,
    target: (i) => (i.target ? i.target.completion : -Infinity),
    change: (i) => (i.compare ? (i.value - i.compare) / Math.abs(i.compare) : -Infinity),
};

export class SalespeopleTable extends SalesSection {
    static template = "business_pulse.SalespeopleTable";
    static components = { TargetProgress };
    static props = { data: Object, currencyId: { type: Number, optional: true }, onOpen: Function };

    setup() {
        this.sort = useState({ key: "value", desc: true });
    }
    get columns() {
        return [
            { key: "name", label: _t("Salesperson"), align: "start" },
            { key: "value", label: _t("Sales") },
            { key: "change", label: _t("Change"), hideSm: true },
            { key: "orders", label: _t("Orders"), hideSm: true },
            { key: "aov", label: _t("Avg. order"), hideMd: true },
            { key: "conversion", label: _t("Conversion"), hideMd: true },
            { key: "pipeline", label: _t("Open pipeline"), hideMd: true },
            { key: "target", label: _t("Target"), align: "start" },
        ];
    }
    get rows() {
        const getter = SORTERS[this.sort.key];
        const rows = [...this.props.data.items];
        rows.sort((a, b) => {
            const x = getter(a);
            const y = getter(b);
            const order = x < y ? -1 : x > y ? 1 : 0;
            return this.sort.desc ? -order : order;
        });
        return rows;
    }
    setSort(key) {
        if (this.sort.key === key) {
            this.sort.desc = !this.sort.desc;
        } else {
            this.sort.key = key;
            this.sort.desc = key !== "name";
        }
    }
    ariaSort(key) {
        if (this.sort.key !== key) {
            return "none";
        }
        return this.sort.desc ? "descending" : "ascending";
    }
    delta(item) {
        return computeDelta(item.value, item.compare, "monetary", "up");
    }
}
