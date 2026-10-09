/** @odoo-module **/

import { Component, useRef, useState, onMounted } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class SaveViewDialog extends Component {
    static template = "business_pulse.SaveViewDialog";
    static components = { Dialog };
    static props = {
        views: Array,
        onSave: Function,
        close: Function,
    };

    setup() {
        this.state = useState({ name: "", saving: false, error: "" });
        this.inputRef = useRef("input");
        onMounted(() => this.inputRef.el?.focus());
    }

    get willReplace() {
        const name = this.state.name.trim();
        return name && this.props.views.some((v) => v.name === name);
    }

    async save() {
        const name = this.state.name.trim();
        if (!name) {
            return;
        }
        this.state.saving = true;
        this.state.error = "";
        try {
            await this.props.onSave(name);
            this.props.close();
        } catch (error) {
            this.state.error = error?.data?.message || error?.message || "";
        } finally {
            this.state.saving = false;
        }
    }

    onKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.save();
        }
    }
}
