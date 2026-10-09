/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

const MAX_CARDS = 12;

/**
 * Personalization dialog: choose and order KPI cards, and set a personal
 * default period/comparison. Only presentation is affected.
 */
export class KpiPicker extends Component {
    static template = "business_pulse.KpiPicker";
    static components = { Dialog };
    static props = {
        catalog: Array,
        selected: Array,
        presets: Array,
        comparisons: Array,
        datePreset: { type: [String, Boolean], optional: true },
        comparison: { type: [String, Boolean], optional: true },
        onSave: Function,
        onReset: Function,
        close: Function,
    };

    setup() {
        const available = this.props.catalog.filter((k) => k.available);
        const selected = this.props.selected.filter((key) => available.some((k) => k.key === key));
        this.state = useState({
            order: [...selected, ...available.map((k) => k.key).filter((key) => !selected.includes(key))],
            checked: Object.fromEntries(available.map((k) => [k.key, selected.includes(k.key)])),
            datePreset: this.props.datePreset || "",
            comparison: this.props.comparison || "",
            saving: false,
        });
        this.byKey = Object.fromEntries(available.map((k) => [k.key, k]));
        this.maxCards = MAX_CARDS;
    }

    get selectedCount() {
        return this.state.order.filter((key) => this.state.checked[key]).length;
    }

    get presetOptions() {
        return this.props.presets.filter((p) => p.key !== "custom");
    }

    get comparisonOptions() {
        return this.props.comparisons.filter((c) => c.key !== "custom");
    }

    toggle(key) {
        if (!this.state.checked[key] && this.selectedCount >= MAX_CARDS) {
            return;
        }
        this.state.checked[key] = !this.state.checked[key];
    }

    move(index, offset) {
        const target = index + offset;
        if (target < 0 || target >= this.state.order.length) {
            return;
        }
        const order = [...this.state.order];
        [order[index], order[target]] = [order[target], order[index]];
        this.state.order = order;
    }

    async save() {
        this.state.saving = true;
        try {
            await this.props.onSave({
                kpi_keys: this.state.order.filter((key) => this.state.checked[key]),
                date_preset: this.state.datePreset || false,
                comparison: this.state.comparison || false,
            });
            this.props.close();
        } finally {
            this.state.saving = false;
        }
    }

    async reset() {
        await this.props.onReset();
        this.props.close();
    }
}
