/** @odoo-module **/

import { Component } from "@odoo/owl";
import { computeDelta, formatExact, formatShare, formatValue } from "../utils/format";

class RankingMixin extends Component {
    fmt(value) {
        return formatValue(value, "monetary", this.props.currencyId, { compact: true });
    }
    exact(value) {
        return formatExact(value, "monetary", this.props.currencyId);
    }
    share(value) {
        return formatShare(value);
    }
    delta(item) {
        if (item.compare === null || item.compare === undefined) {
            return null;
        }
        return computeDelta(item.value, item.compare, "monetary", "up");
    }
    open(item) {
        if (item.action) {
            this.props.onOpen(item.action);
        }
    }
}

export class Breakdown extends RankingMixin {
    static template = "business_pulse.Breakdown";
    static props = {
        data: Object,
        currencyId: { type: Number, optional: true },
        onOpen: Function,
    };

    get maxValue() {
        const values = this.props.data.items.map((i) => Math.max(i.value, i.compare || 0));
        return Math.max(...values, 1);
    }

    barWidth(value) {
        return `${Math.max(0, (value / this.maxValue) * 100).toFixed(2)}%`;
    }
}

export class TopPerformers extends RankingMixin {
    static template = "business_pulse.TopPerformers";
    static props = {
        data: Object,
        currencyId: { type: Number, optional: true },
        onOpen: Function,
    };

    qty(item) {
        return formatValue(item.quantity, "count", null, { compact: true });
    }
}
