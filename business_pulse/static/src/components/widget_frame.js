/** @odoo-module **/

import { Component } from "@odoo/owl";

/**
 * Shared shell for every dashboard section: header, and the loading,
 * empty, error and permission states. Sections render their content in the
 * default slot only when data is available.
 */
export class WidgetFrame extends Component {
    static template = "business_pulse.WidgetFrame";
    static props = {
        title: String,
        subtitle: { type: String, optional: true },
        widget: Object, // { status, data, loading }
        emptyTitle: { type: String, optional: true },
        emptyText: { type: String, optional: true },
        isEmpty: { type: Boolean, optional: true },
        onRetry: { type: Function, optional: true },
        onExport: { type: Function, optional: true },
        skeleton: { type: String, optional: true }, // "chart" | "list" | "bars"
        ignoredFilters: { type: Array, optional: true },
        className: { type: String, optional: true },
        slots: { type: Object, optional: true },
        headingId: { type: String, optional: true },
    };
    static defaultProps = {
        skeleton: "list",
        className: "",
    };

    get status() {
        const { status, data } = this.props.widget;
        if (!data && status === "loading") {
            return "skeleton";
        }
        if (["forbidden", "error", "invalid"].includes(status)) {
            return status;
        }
        if (this.props.isEmpty) {
            return "empty";
        }
        return "ok";
    }

    get message() {
        return this.props.widget.data?.message || "";
    }
}
