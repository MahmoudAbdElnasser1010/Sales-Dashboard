/** @odoo-module **/

import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { formatDate, formatExact, formatRelative, formatShare, formatValue } from "../utils/format";

export class Receivables extends Component {
    static template = "business_pulse.Receivables";
    static props = {
        data: Object,
        currencyId: { type: Number, optional: true },
        onOpen: Function,
    };

    fmt(value) {
        return formatValue(value, "monetary", this.props.currencyId, { compact: true });
    }
    exact(value) {
        return formatExact(value, "monetary", this.props.currencyId);
    }
    get asOf() {
        return formatDate(this.props.data.as_of);
    }
    get overdueShare() {
        return formatShare(this.props.data.overdue_share);
    }
    get positiveTotal() {
        return this.props.data.buckets.reduce((sum, b) => sum + Math.max(b.value, 0), 0) || 1;
    }
    segmentWidth(bucket) {
        return `${((Math.max(bucket.value, 0) / this.positiveTotal) * 100).toFixed(2)}%`;
    }
}

const SEVERITY = {
    critical: { icon: "fa-exclamation-circle", label: _t("Critical") },
    warning: { icon: "fa-exclamation-triangle", label: _t("Warning") },
    info: { icon: "fa-info-circle", label: _t("Info") },
};

export class Attention extends Component {
    static template = "business_pulse.Attention";
    static props = {
        data: Object,
        currencyId: { type: Number, optional: true },
        onOpen: Function,
    };

    severity(item) {
        return SEVERITY[item.severity] || SEVERITY.info;
    }
    amount(item) {
        return item.value === null || item.value === undefined
            ? ""
            : formatValue(item.value, "monetary", this.props.currencyId, { compact: true });
    }
}

export class ActivityFeed extends Component {
    static template = "business_pulse.ActivityFeed";
    static props = {
        data: Object,
        onOpenRecord: Function,
    };

    amount(event) {
        return formatValue(event.amount, "monetary", event.currency_id, { compact: true });
    }
    when(event) {
        return formatRelative(event.when);
    }
    label(event) {
        return `${event.label}: ${event.title}, ${event.partner}`;
    }
    get typeLabels() {
        return { order: _t("Order"), quotation: _t("Quotation"), invoice: _t("Invoice"), payment: _t("Payment") };
    }
}
