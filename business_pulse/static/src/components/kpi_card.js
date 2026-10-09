/** @odoo-module **/

import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { computeDelta, formatExact, formatValue } from "../utils/format";

export class Sparkline extends Component {
    static template = "business_pulse.Sparkline";
    static props = { values: Array, tone: { type: String, optional: true } };

    get paths() {
        const values = this.props.values;
        if (!values || values.length < 2) {
            return null;
        }
        const width = 100;
        const height = 32;
        const pad = 2;
        const min = Math.min(...values, 0);
        const max = Math.max(...values);
        const span = max - min || 1;
        const points = values.map((v, i) => [
            (i / (values.length - 1)) * width,
            height - pad - ((v - min) / span) * (height - pad * 2),
        ]);
        const line = points.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
        const area = `${line} L${width},${height} L0,${height} Z`;
        const [lx, ly] = points[points.length - 1];
        return { line, area, lx, ly };
    }
}

export class KpiCard extends Component {
    static template = "business_pulse.KpiCard";
    static components = { Sparkline };
    static props = {
        card: Object,
        meta: Object,
        currencyId: { type: Number, optional: true },
        compareLabel: { type: String, optional: true },
        hasComparison: Boolean,
        loading: { type: Boolean, optional: true },
        onOpen: Function,
    };

    get kind() {
        return this.props.meta.kind;
    }

    get value() {
        return formatValue(this.props.card.value, this.kind, this.props.currencyId, { compact: true });
    }

    get exactValue() {
        return formatExact(this.props.card.value, this.kind, this.props.currencyId);
    }

    get compareValue() {
        return formatValue(this.props.card.compare, this.kind, this.props.currencyId, { compact: true });
    }

    get delta() {
        if (!this.props.hasComparison || this.props.meta.snapshot) {
            return null;
        }
        return computeDelta(this.props.card.value, this.props.card.compare, this.kind, this.props.meta.better);
    }

    get deltaTitle() {
        const delta = this.delta;
        if (!delta) {
            return "";
        }
        const parts = [`${delta.directionText}: ${delta.label}`];
        if (this.kind === "rate" && delta.relative !== null) {
            parts.push(_t("relative change %(value)s%", { value: (delta.relative * 100).toFixed(1) }));
        } else if (this.kind !== "rate") {
            parts.push(_t("absolute change %(value)s", {
                value: formatExact(delta.diff, this.kind, this.props.currencyId),
            }));
        }
        return parts.join(" · ");
    }

    get canOpen() {
        return this.props.card.status === "ok" && !!this.props.card.action;
    }

    open() {
        if (this.canOpen) {
            this.props.onOpen(this.props.card.action);
        }
    }
}
