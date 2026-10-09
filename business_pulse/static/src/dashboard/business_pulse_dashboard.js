/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { _t } from "@web/core/l10n/translation";
import { download } from "@web/core/network/download";
import { MultiRecordSelector } from "@web/core/record_selectors/multi_record_selector";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { useSetupAction } from "@web/search/action_hook";

import { WidgetFrame } from "../components/widget_frame";
import { KpiCard } from "../components/kpi_card";
import { TrendChart } from "../components/trend_chart";
import { Breakdown, TopPerformers } from "../components/rankings";
import { ActivityFeed, Attention, Receivables } from "../components/insights";
import { KpiPicker } from "../components/kpi_picker";
import { formatRange } from "../utils/format";

const WIDGETS = ["kpis", "trend", "breakdown", "top", "receivables", "attention", "activity"];
const DIMENSION_FILTERS = [
    { key: "team_ids", model: "crm.team", label: _t("Sales Team") },
    { key: "user_ids", model: "res.users", label: _t("Salesperson"), domain: [["share", "=", false]] },
    { key: "partner_ids", model: "res.partner", label: _t("Customer") },
    { key: "product_ids", model: "product.product", label: _t("Product") },
    { key: "categ_ids", model: "product.category", label: _t("Product Category") },
];

function emptyDimensions() {
    return Object.fromEntries([...DIMENSION_FILTERS.map((d) => [d.key, []]), ["company_ids", []]]);
}

export class BusinessPulseDashboard extends Component {
    static template = "business_pulse.Dashboard";
    static components = {
        Dropdown,
        DropdownItem,
        MultiRecordSelector,
        WidgetFrame,
        KpiCard,
        TrendChart,
        Breakdown,
        TopPerformers,
        Receivables,
        Attention,
        ActivityFeed,
    };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.dimensionFilters = DIMENSION_FILTERS;
        this.tokens = {};
        this.state = useState({
            boot: null,
            bootError: null,
            filters: {
                preset: "this_month",
                date_from: "",
                date_to: "",
                comparison: "previous_period",
                compare_from: "",
                compare_to: "",
                ...emptyDimensions(),
            },
            draft: { date_from: "", date_to: "", compare_from: "", compare_to: "" },
            options: {
                trend: { metric: "sales", granularity: "auto" },
                breakdown: { dimension: "categ_id" },
                top: { kind: "products" },
            },
            kpiKeys: [],
            showFilters: false,
            widgets: Object.fromEntries(WIDGETS.map((w) => [w, { status: "loading", data: null, loading: true }])),
        });

        useSetupAction({
            getLocalState: () => ({
                businessPulse: {
                    filters: JSON.parse(JSON.stringify(this.state.filters)),
                    options: JSON.parse(JSON.stringify(this.state.options)),
                    showFilters: this.state.showFilters,
                },
            }),
        });

        onWillStart(async () => {
            try {
                const boot = await this.orm.call("business.pulse.dashboard", "get_bootstrap", []);
                this.state.boot = boot;
                this.initFilters(boot);
                this.loadAll();
            } catch {
                this.state.bootError = _t("Business Pulse could not be loaded. Please refresh the page.");
            }
        });
    }

    // ------------------------------------------------------------------
    // Initialization
    // ------------------------------------------------------------------
    initFilters(boot) {
        const restored = this.props.state?.businessPulse;
        const prefs = boot.preferences || {};
        this.state.kpiKeys = prefs.kpi_keys?.length ? prefs.kpi_keys : boot.default_kpis;
        if (restored) {
            Object.assign(this.state.filters, restored.filters);
            Object.assign(this.state.options, restored.options);
            this.state.showFilters = restored.showFilters;
        } else {
            this.state.filters.preset = prefs.date_preset || boot.settings.default_preset;
            this.state.filters.comparison = prefs.comparison || boot.settings.default_comparison;
        }
        if (!boot.permissions.finance && this.state.options.trend.metric === "revenue") {
            this.state.options.trend.metric = "sales";
        }
        this.syncDraft();
    }

    syncDraft() {
        const f = this.state.filters;
        const preset = this.presetEntry(f.preset);
        this.state.draft.date_from = f.preset === "custom" ? f.date_from : preset?.date_from || "";
        this.state.draft.date_to = f.preset === "custom" ? f.date_to : preset?.date_to || "";
        this.state.draft.compare_from = f.compare_from;
        this.state.draft.compare_to = f.compare_to;
    }

    // ------------------------------------------------------------------
    // Getters
    // ------------------------------------------------------------------
    get boot() {
        return this.state.boot;
    }

    get permissions() {
        return this.boot?.permissions || {};
    }

    get catalog() {
        return Object.fromEntries((this.boot?.kpi_catalog || []).map((k) => [k.key, k]));
    }

    presetEntry(key) {
        return this.boot?.presets.find((p) => p.key === key);
    }

    get presetLabel() {
        return this.presetEntry(this.state.filters.preset)?.label || "";
    }

    get comparisonLabel() {
        return this.boot?.comparisons.find((c) => c.key === this.state.filters.comparison)?.label || "";
    }

    get period() {
        for (const name of ["kpis", "trend", "breakdown"]) {
            const period = this.state.widgets[name].data?.period;
            if (period) {
                return period;
            }
        }
        const preset = this.presetEntry(this.state.filters.preset);
        return preset ? { date_from: preset.date_from, date_to: preset.date_to } : null;
    }

    get periodCaption() {
        const p = this.period;
        return p ? formatRange(p.date_from, p.date_to) : "";
    }

    get compareCaption() {
        const p = this.period;
        return p && p.cmp_from ? formatRange(p.cmp_from, p.cmp_to) : "";
    }

    get hasComparison() {
        return this.state.filters.comparison !== "none";
    }

    get currencyId() {
        for (const name of WIDGETS) {
            const data = this.state.widgets[name].data;
            if (data?.currency_id) {
                return data.currency_id;
            }
        }
        return this.boot?.currency_id;
    }

    get activeChips() {
        const chips = [];
        const f = this.state.filters;
        if (f.company_ids.length) {
            const names = this.boot.companies.filter((c) => f.company_ids.includes(c.id)).map((c) => c.name);
            chips.push({ key: "company_ids", label: _t("Company"), value: names.join(", ") });
        }
        for (const dim of DIMENSION_FILTERS) {
            if (f[dim.key].length) {
                chips.push({
                    key: dim.key,
                    label: dim.label,
                    value: _t("%(count)s selected", { count: f[dim.key].length }),
                });
            }
        }
        return chips;
    }

    get kpiCards() {
        const data = this.state.widgets.kpis.data;
        const byKey = Object.fromEntries((data?.cards || []).map((c) => [c.key, c]));
        return this.state.kpiKeys
            .filter((key) => this.catalog[key])
            .map((key) => ({ key, meta: this.catalog[key], card: byKey[key] || { key, status: "loading" } }));
    }

    get trendMetrics() {
        const metrics = [
            { key: "sales", label: _t("Sales") },
            { key: "orders", label: _t("Orders") },
        ];
        if (this.permissions.finance) {
            metrics.push({ key: "revenue", label: _t("Invoiced") });
        }
        return metrics;
    }

    get granularities() {
        return [
            { key: "auto", label: _t("Auto") },
            { key: "day", label: _t("Day") },
            { key: "week", label: _t("Week") },
            { key: "month", label: _t("Month") },
            { key: "quarter", label: _t("Quarter") },
        ];
    }

    get topKinds() {
        return [
            { key: "products", label: _t("Products") },
            { key: "customers", label: _t("Customers") },
            { key: "salespeople", label: _t("Salespeople") },
        ];
    }

    get exportItems() {
        const items = [
            { key: "kpis", label: _t("KPI summary") },
            { key: "trend", label: _t("Trend data") },
            { key: "breakdown", label: _t("Sales breakdown") },
            { key: "top", label: _t("Top performers") },
        ];
        if (this.permissions.finance) {
            items.push({ key: "receivables", label: _t("Receivables aging") });
        }
        return items;
    }

    get companyDomain() {
        return [["id", "in", (this.boot?.companies || []).map((c) => c.id)]];
    }

    get trendCurrentLabel() {
        return this.periodCaption || _t("Selected period");
    }

    get trendCompareLabel() {
        return this.compareCaption || _t("Comparison period");
    }

    get trendSubtitle() {
        const metric = this.trendMetrics.find((m) => m.key === this.state.options.trend.metric);
        return metric?.key === "revenue"
            ? _t("Invoiced revenue (net of credit notes)")
            : metric?.key === "orders"
            ? _t("Confirmed orders")
            : _t("Confirmed sales, untaxed");
    }

    get breakdownSubtitle() {
        return _t("Confirmed sales by %(dimension)s", { dimension: this.dimensionLabel.toLowerCase() });
    }

    formatPresetRange(preset) {
        return formatRange(preset.date_from, preset.date_to);
    }

    get dimensionLabel() {
        return this.boot?.dimensions.find((d) => d.key === this.state.options.breakdown.dimension)?.label || "";
    }

    // ------------------------------------------------------------------
    // Data loading
    // ------------------------------------------------------------------
    serverFilters(widget) {
        const f = this.state.filters;
        const payload = {
            preset: f.preset,
            comparison: f.comparison,
            company_ids: f.company_ids,
        };
        for (const dim of DIMENSION_FILTERS) {
            payload[dim.key] = f[dim.key];
        }
        if (f.preset === "custom") {
            payload.date_from = f.date_from;
            payload.date_to = f.date_to;
        }
        if (f.comparison === "custom") {
            payload.compare_from = f.compare_from;
            payload.compare_to = f.compare_to;
        }
        if (widget === "trend") {
            payload.granularity = this.state.options.trend.granularity;
        }
        return payload;
    }

    widgetOptions(widget) {
        if (widget === "kpis") {
            return { keys: this.state.kpiKeys };
        }
        return this.state.options[widget] || {};
    }

    isWidgetVisible(widget) {
        if (widget === "receivables") {
            return !!this.permissions.finance;
        }
        return true;
    }

    async loadWidget(widget) {
        if (!this.isWidgetVisible(widget)) {
            return;
        }
        const token = (this.tokens[widget] = (this.tokens[widget] || 0) + 1);
        const slot = this.state.widgets[widget];
        slot.loading = true;
        if (!slot.data) {
            slot.status = "loading";
        }
        try {
            const data = await this.orm.silent.call("business.pulse.dashboard", "get_widget", [
                widget,
                this.serverFilters(widget),
                this.widgetOptions(widget),
            ]);
            if (token !== this.tokens[widget]) {
                return;
            }
            slot.status = data.status;
            slot.data = data;
        } catch {
            if (token !== this.tokens[widget]) {
                return;
            }
            slot.status = "error";
            slot.data = { message: _t("The server could not be reached. Check your connection and try again.") };
        } finally {
            if (token === this.tokens[widget]) {
                slot.loading = false;
            }
        }
    }

    loadAll() {
        for (const widget of WIDGETS) {
            this.loadWidget(widget);
        }
    }

    // ------------------------------------------------------------------
    // Filter handlers
    // ------------------------------------------------------------------
    selectPreset(key) {
        if (key === "custom") {
            this.state.filters.preset = "custom";
            this.state.filters.date_from = this.state.draft.date_from || this.period?.date_from || "";
            this.state.filters.date_to = this.state.draft.date_to || this.period?.date_to || "";
            this.syncDraft();
            this.loadAll();
            return;
        }
        this.state.filters.preset = key;
        this.syncDraft();
        this.loadAll();
    }

    applyCustomRange() {
        const { date_from, date_to } = this.state.draft;
        if (!date_from || !date_to) {
            this.notification.add(_t("Select both a start and an end date."), { type: "warning" });
            return;
        }
        if (date_from > date_to) {
            this.notification.add(_t("The start date must be before the end date."), { type: "warning" });
            return;
        }
        Object.assign(this.state.filters, { preset: "custom", date_from, date_to });
        this.loadAll();
    }

    selectComparison(key) {
        this.state.filters.comparison = key;
        if (key === "custom") {
            const p = this.period;
            this.state.draft.compare_from = this.state.filters.compare_from || p?.cmp_from || p?.date_from || "";
            this.state.draft.compare_to = this.state.filters.compare_to || p?.cmp_to || p?.date_to || "";
            this.state.filters.compare_from = this.state.draft.compare_from;
            this.state.filters.compare_to = this.state.draft.compare_to;
        }
        this.loadAll();
    }

    applyCustomComparison() {
        const { compare_from, compare_to } = this.state.draft;
        if (!compare_from || !compare_to || compare_from > compare_to) {
            this.notification.add(_t("Select a valid comparison period."), { type: "warning" });
            return;
        }
        Object.assign(this.state.filters, { comparison: "custom", compare_from, compare_to });
        this.loadAll();
    }

    updateDimension(key, ids) {
        this.state.filters[key] = ids;
        this.loadAll();
    }

    clearDimension(key) {
        this.state.filters[key] = [];
        this.loadAll();
    }

    clearAll() {
        Object.assign(this.state.filters, emptyDimensions());
        this.loadAll();
    }

    toggleFilters() {
        this.state.showFilters = !this.state.showFilters;
    }

    // ------------------------------------------------------------------
    // Widget options
    // ------------------------------------------------------------------
    setTrendMetric(metric) {
        this.state.options.trend.metric = metric;
        this.loadWidget("trend");
    }

    setGranularity(ev) {
        this.state.options.trend.granularity = ev.target.value;
        this.loadWidget("trend");
    }

    setDimension(ev) {
        this.state.options.breakdown.dimension = ev.target.value;
        this.loadWidget("breakdown");
    }

    setTopKind(kind) {
        this.state.options.top.kind = kind;
        this.loadWidget("top");
    }

    onTabKeydown(ev, kinds, current, setter) {
        const index = kinds.findIndex((k) => k.key === current);
        let next = null;
        if (ev.key === "ArrowRight") {
            next = kinds[(index + 1) % kinds.length];
        } else if (ev.key === "ArrowLeft") {
            next = kinds[(index - 1 + kinds.length) % kinds.length];
        }
        if (next) {
            ev.preventDefault();
            setter(next.key);
            const tabs = ev.currentTarget.closest('[role="tablist"]').querySelectorAll('[role="tab"]');
            tabs[kinds.indexOf(next)]?.focus();
        }
    }

    // ------------------------------------------------------------------
    // Navigation & actions
    // ------------------------------------------------------------------
    openAction(action) {
        if (action) {
            this.actionService.doAction(action);
        }
    }

    openRecord(event) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: event.res_model,
            res_id: event.res_id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async openTrendPoint(bucket) {
        try {
            const action = await this.orm.call("business.pulse.dashboard", "get_drill_action", [
                "trend",
                this.serverFilters("trend"),
                { metric: this.state.options.trend.metric, bucket },
            ]);
            this.openAction(action);
        } catch {
            this.notification.add(_t("These records could not be opened."), { type: "danger" });
        }
    }

    refresh() {
        this.loadAll();
    }

    async exportCsv(widget) {
        try {
            await download({
                url: "/business_pulse/export/csv",
                data: {
                    widget,
                    filters: JSON.stringify({
                        ...this.serverFilters(widget),
                        context: { allowed_company_ids: user.context.allowed_company_ids },
                    }),
                    options: JSON.stringify(this.widgetOptions(widget)),
                },
            });
        } catch {
            this.notification.add(_t("The export failed. Please try again."), { type: "danger" });
        }
    }

    openCustomize() {
        const prefs = this.boot.preferences || {};
        this.dialog.add(KpiPicker, {
            catalog: this.boot.kpi_catalog,
            selected: this.state.kpiKeys,
            presets: this.boot.presets,
            comparisons: this.boot.comparisons,
            datePreset: prefs.date_preset || false,
            comparison: prefs.comparison || false,
            onSave: async (values) => {
                const saved = await this.orm.call("business.pulse.preference", "save_preferences", [values]);
                this.boot.preferences = saved;
                this.state.kpiKeys = saved.kpi_keys.length ? saved.kpi_keys : this.boot.default_kpis;
                this.notification.add(_t("Your dashboard has been saved."), { type: "success" });
                this.loadWidget("kpis");
            },
            onReset: async () => {
                const saved = await this.orm.call("business.pulse.preference", "reset_preferences", []);
                this.boot.preferences = saved;
                this.state.kpiKeys = this.boot.default_kpis;
                this.notification.add(_t("Default layout restored."), { type: "info" });
                this.loadWidget("kpis");
            },
        });
    }

    openSettings() {
        this.actionService.doAction("business_pulse.action_business_pulse_settings");
    }
}

registry.category("actions").add("business_pulse.dashboard", BusinessPulseDashboard);
