/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { DomainSelectorDialog } from "@web/core/domain_selector_dialog/domain_selector_dialog";

class DomainButtonField extends Component {
    static template = "flink_analytics.DomainButtonField";
    static components = {};
    static supportedTypes = ["char"];
    static props = {
        id: { type: String, optional: true },
        name: { type: String, optional: true },
        record: { type: Object, optional: true },
        readonly: { type: Boolean, optional: true },
        "*": true,
    };

    setup() {
        this.dialog = useService("dialog");
    }

    get resModel() {
        return this.props.record?.data?.model_name || "";
    }

    get domain() {
        return this.props.record?.data?.[this.props.name] || "[]";
    }

    get label() {
        if (!this.resModel) return "Select a model first";
        try {
            const parsed = JSON.parse(this.domain.replace(/'/g, '"'));
            if (!Array.isArray(parsed) || parsed.length === 0) return "Match all records";
            const count = parsed.filter((c) => Array.isArray(c) && c.length === 3).length;
            return count === 1 ? "1 condition" : `${count} conditions`;
        } catch {
            return "Custom filter";
        }
    }

    get hasFilter() {
        try {
            const parsed = JSON.parse(this.domain.replace(/'/g, '"'));
            return Array.isArray(parsed) && parsed.length > 0;
        } catch {
            return false;
        }
    }

    openDialog() {
        if (!this.resModel) return;
        this.dialog.add(DomainSelectorDialog, {
            resModel: this.resModel,
            domain: this.domain,
            onConfirm: (domain) => {
                this.props.record.update({ [this.props.name]: domain });
            },
        });
    }

    clearDomain() {
        this.props.record.update({ [this.props.name]: "[]" });
    }
}

registry.category("fields").add("domain_button", {
    component: DomainButtonField,
    supportedTypes: ["char"],
});
