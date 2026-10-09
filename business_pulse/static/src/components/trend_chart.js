/** @odoo-module **/

import { Component, onMounted, onWillStart, onWillUnmount, onPatched, useRef, useState } from "@odoo/owl";
import { loadBundle } from "@web/core/assets";
import { getCurrency } from "@web/core/currency";
import { formatFloat, humanNumber } from "@web/core/utils/numbers";
import { _t } from "@web/core/l10n/translation";
import { computeDelta, formatBucket, formatExact, formatValue } from "../utils/format";

function cssVar(el, name, fallback) {
    const value = getComputedStyle(el).getPropertyValue(name).trim();
    return value || fallback;
}

export class TrendChart extends Component {
    static template = "business_pulse.TrendChart";
    static props = {
        data: Object,
        currencyId: { type: Number, optional: true },
        currentLabel: String,
        compareLabel: { type: String, optional: true },
        onPointClick: Function,
    };

    setup() {
        this.canvasRef = useRef("canvas");
        this.rootRef = useRef("root");
        this.view = useState({ mode: "chart" });
        this.chart = null;
        this.renderedKey = null;
        onWillStart(() => loadBundle("web.chartjs_lib"));
        onMounted(() => this.renderChart());
        onPatched(() => this.renderChart());
        onWillUnmount(() => this.destroy());
    }

    get kind() {
        return this.props.data.metric === "orders" ? "count" : "monetary";
    }

    get hasComparison() {
        return this.props.data.compare && this.props.data.compare.length > 0;
    }

    get rows() {
        const d = this.props.data;
        return d.labels.map((label, i) => ({
            label: formatBucket(label, d.granularity, { withYear: true }),
            value: formatExact(d.current[i], this.kind, this.props.currencyId),
            compareLabel: d.compare_labels[i] ? formatBucket(d.compare_labels[i], d.granularity, { withYear: true }) : "",
            compare: d.compare[i] !== undefined ? formatExact(d.compare[i], this.kind, this.props.currencyId) : "",
        }));
    }

    get totalDelta() {
        const d = this.props.data;
        if (d.compare_total === null || d.compare_total === undefined) {
            return null;
        }
        return computeDelta(d.total, d.compare_total, this.kind, "up");
    }

    get totalLabel() {
        return formatValue(this.props.data.total, this.kind, this.props.currencyId, { compact: true });
    }

    get summary() {
        const d = this.props.data;
        if (!d.current.length) {
            return "";
        }
        const max = Math.max(...d.current);
        const idx = d.current.indexOf(max);
        return _t("Total %(total)s. Highest %(granularity)s: %(label)s with %(value)s.", {
            total: formatExact(d.total, this.kind, this.props.currencyId),
            granularity: d.granularity,
            label: formatBucket(d.labels[idx], d.granularity, { withYear: true }),
            value: formatExact(max, this.kind, this.props.currencyId),
        });
    }

    setMode(mode) {
        this.view.mode = mode;
    }

    destroy() {
        if (this.chart) {
            this.chart.destroy();
            this.chart = null;
        }
    }

    renderChart() {
        if (this.view.mode !== "chart" || !this.canvasRef.el) {
            this.destroy();
            this.renderedKey = null;
            return;
        }
        const d = this.props.data;
        // Re-render only when this chart's own inputs change, not on every
        // dashboard update (other sections loading would restart animations).
        const key = [d, this.props.currencyId, this.props.currentLabel, this.props.compareLabel];
        if (this.chart && this.renderedKey && key.every((v, i) => v === this.renderedKey[i])) {
            return;
        }
        this.renderedKey = key;
        const root = this.rootRef.el;
        const primary = cssVar(root, "--bp-series-1", "#2a78d6");
        const primaryFill = cssVar(root, "--bp-series-1-fill", "rgba(42,120,214,0.10)");
        const muted = cssVar(root, "--bp-series-compare", "#9a9a94");
        const grid = cssVar(root, "--bp-grid", "rgba(0,0,0,0.06)");
        const text = cssVar(root, "--bp-text-muted", "#6b6b66");
        const kind = this.kind;
        const currencyId = this.props.currencyId;
        const labels = d.labels.map((l) => formatBucket(l, d.granularity));
        // One consistent tick format per axis: compact (50k) for large scales.
        const maxValue = Math.max(0, ...d.current, ...(d.compare || []));
        const currency = kind === "monetary" ? getCurrency(currencyId) : null;
        const axisLabel = (value) => {
            const number = maxValue >= 10000 ? humanNumber(value, { decimals: 1 }) : formatFloat(value, { digits: [69, 0] });
            if (!currency) {
                return number;
            }
            return currency.position === "after" ? `${number} ${currency.symbol}` : `${currency.symbol} ${number}`;
        };
        const datasets = [
            {
                label: this.props.currentLabel,
                data: d.current,
                borderColor: primary,
                backgroundColor: primaryFill,
                fill: "origin",
                borderWidth: 2,
                cubicInterpolationMode: "monotone",
                pointRadius: d.current.length > 40 ? 0 : 3,
                pointHoverRadius: 5,
                pointBackgroundColor: primary,
                pointBorderColor: cssVar(root, "--bp-surface", "#fff"),
                pointBorderWidth: 2,
                order: 1,
            },
        ];
        if (this.hasComparison) {
            datasets.push({
                label: this.props.compareLabel,
                data: d.compare,
                borderColor: muted,
                backgroundColor: "transparent",
                borderDash: [5, 4],
                borderWidth: 2,
                cubicInterpolationMode: "monotone",
                pointRadius: 0,
                pointHoverRadius: 4,
                pointBackgroundColor: muted,
                fill: false,
                order: 2,
            });
        }
        const config = {
            type: "line",
            data: { labels, datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: { duration: 250 },
                interaction: { mode: "index", intersect: false },
                layout: { padding: { top: 8, right: 8 } },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: cssVar(root, "--bp-tooltip-bg", "#1f1f1d"),
                        titleColor: "#fff",
                        bodyColor: "#fff",
                        padding: 10,
                        cornerRadius: 6,
                        boxPadding: 4,
                        usePointStyle: true,
                        callbacks: {
                            title: (items) => {
                                const i = items[0].dataIndex;
                                return formatBucket(d.labels[i], d.granularity, { withYear: true });
                            },
                            label: (item) => {
                                const i = item.dataIndex;
                                const value = formatExact(item.raw, kind, currencyId);
                                if (item.datasetIndex === 1) {
                                    const when = d.compare_labels[i]
                                        ? formatBucket(d.compare_labels[i], d.granularity, { withYear: true })
                                        : "";
                                    return ` ${value}  (${when})`;
                                }
                                return ` ${value}`;
                            },
                            footer: (items) => {
                                const i = items[0].dataIndex;
                                if (!this.hasComparison || d.compare[i] === undefined) {
                                    return _t("Click to open records");
                                }
                                const delta = computeDelta(d.current[i], d.compare[i], kind, "up");
                                return delta ? `${delta.label} · ${_t("Click to open records")}` : "";
                            },
                        },
                    },
                },
                scales: {
                    x: {
                        grid: { display: false },
                        border: { color: grid },
                        ticks: { color: text, maxRotation: 0, autoSkip: true, autoSkipPadding: 16 },
                    },
                    y: {
                        beginAtZero: true,
                        grid: { color: grid },
                        border: { display: false },
                        ticks: {
                            color: text,
                            maxTicksLimit: 5,
                            callback: (value) => axisLabel(value),
                        },
                    },
                },
                onClick: (_event, elements) => {
                    if (elements.length) {
                        this.props.onPointClick(d.labels[elements[0].index]);
                    }
                },
                onHover: (event, elements) => {
                    event.native.target.style.cursor = elements.length ? "pointer" : "default";
                },
            },
        };
        if (this.chart) {
            this.chart.data = config.data;
            this.chart.options = config.options;
            this.chart.update();
        } else {
            this.chart = new window.Chart(this.canvasRef.el, config);
        }
    }
}
