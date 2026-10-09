/** @odoo-module **/

import { formatCurrency } from "@web/core/currency";
import { _t } from "@web/core/l10n/translation";
import { formatFloat, humanNumber } from "@web/core/utils/numbers";

const { DateTime } = luxon;

const COMPACT_THRESHOLD = 100000;

/**
 * Format a metric value. Compact formatting (1.2M) is only used for large
 * values; callers expose the exact value through `formatExact` (title/sr-only).
 */
export function formatValue(value, kind, currencyId, { compact = false } = {}) {
    if (value === null || value === undefined || value === false) {
        return "—";
    }
    if (kind === "rate") {
        return `${formatFloat(value * 100, { digits: [69, 1] })}%`;
    }
    if (kind === "count") {
        if (compact && Math.abs(value) >= COMPACT_THRESHOLD) {
            return humanNumber(value, { decimals: 1 });
        }
        return formatFloat(value, { digits: [69, 0] });
    }
    // monetary
    if (compact && Math.abs(value) >= COMPACT_THRESHOLD) {
        return formatCurrency(value, currencyId, { humanReadable: true, digits: [69, 1] });
    }
    if (compact && Math.abs(value) >= 1000) {
        return formatCurrency(value, currencyId, { digits: [69, 0] });
    }
    return formatCurrency(value, currencyId);
}

export function formatExact(value, kind, currencyId) {
    if (value === null || value === undefined || value === false) {
        return _t("Not available");
    }
    if (kind === "rate") {
        return `${formatFloat(value * 100, { digits: [69, 2] })}%`;
    }
    if (kind === "count") {
        return formatFloat(value, { digits: [69, 0] });
    }
    return formatCurrency(value, currencyId);
}

export function formatShare(share) {
    return `${formatFloat((share || 0) * 100, { digits: [69, 1] })}%`;
}

/**
 * Compute the change between a value and its comparison.
 * - counts/amounts: relative change in %
 * - rates: difference in percentage points (pp) + relative change
 */
export function computeDelta(value, compare, kind, better = "up") {
    if (value === null || value === undefined || compare === null || compare === undefined) {
        return null;
    }
    const diff = value - compare;
    let label;
    let relative = null;
    if (compare !== 0) {
        relative = diff / Math.abs(compare);
    }
    if (kind === "rate") {
        const pp = diff * 100;
        label = `${pp > 0 ? "+" : ""}${formatFloat(pp, { digits: [69, 1] })} pp`;
    } else if (relative === null) {
        label = diff === 0 ? "0%" : _t("New");
    } else {
        const pct = relative * 100;
        label = `${pct > 0 ? "+" : ""}${formatFloat(pct, { digits: [69, 1] })}%`;
    }
    const magnitude = kind === "rate" ? Math.abs(diff * 100) : relative === null ? Math.abs(diff) : Math.abs(relative * 100);
    let direction = "flat";
    if (magnitude >= (kind === "rate" ? 0.05 : 0.05) && diff !== 0) {
        direction = diff > 0 ? "up" : "down";
    }
    let tone = "neutral";
    if (direction !== "flat") {
        tone = (direction === "up") === (better === "up") ? "good" : "bad";
    }
    const directionText = {
        up: _t("Increase"),
        down: _t("Decrease"),
        flat: _t("No change"),
    }[direction];
    return { diff, relative, label, direction, tone, directionText };
}

export function parseDate(iso) {
    return iso ? DateTime.fromISO(iso) : null;
}

export function formatDate(iso, { year = true } = {}) {
    const dt = parseDate(iso);
    if (!dt) {
        return "";
    }
    return dt.toLocaleString(year ? { day: "numeric", month: "short", year: "numeric" } : { day: "numeric", month: "short" });
}

export function formatRange(from, to) {
    if (!from || !to) {
        return "";
    }
    if (from === to) {
        return formatDate(from);
    }
    const a = parseDate(from);
    const b = parseDate(to);
    const sameYear = a.year === b.year;
    return `${formatDate(from, { year: !sameYear })} – ${formatDate(to)}`;
}

export function formatBucket(iso, granularity, { withYear = false } = {}) {
    const dt = parseDate(iso);
    if (!dt) {
        return "";
    }
    switch (granularity) {
        case "quarter":
            return `Q${dt.quarter} ${dt.year}`;
        case "month":
            return dt.toLocaleString(withYear ? { month: "short", year: "numeric" } : { month: "short" });
        case "week":
            return dt.toLocaleString(withYear ? { day: "numeric", month: "short", year: "numeric" } : { day: "numeric", month: "short" });
        default:
            return dt.toLocaleString(withYear ? { day: "numeric", month: "short", year: "numeric" } : { day: "numeric", month: "short" });
    }
}

export function bucketEnd(iso, granularity) {
    const dt = parseDate(iso);
    const units = { day: { days: 1 }, week: { weeks: 1 }, month: { months: 1 }, quarter: { months: 3 } };
    return dt.plus(units[granularity] || { days: 1 }).minus({ days: 1 }).toISODate();
}

export function formatRelative(when) {
    if (!when) {
        return "";
    }
    const dt = when.length > 10 ? DateTime.fromSQL(when, { zone: "utc" }).toLocal() : DateTime.fromISO(when);
    if (!dt.isValid) {
        return "";
    }
    if (when.length <= 10) {
        const days = Math.round(DateTime.now().startOf("day").diff(dt.startOf("day"), "days").days);
        if (days === 0) {
            return _t("Today");
        }
        if (days === 1) {
            return _t("Yesterday");
        }
        return dt.toLocaleString({ day: "numeric", month: "short" });
    }
    return dt.toRelative() || "";
}
