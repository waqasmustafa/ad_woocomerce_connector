import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

class WooDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            stats: {
                order_count: 0,
                product_count: 0,
                customer_count: 0,
                total_revenue: 0.0,
                pct_completed: 0,
                pct_processing: 0,
                pct_on_hold: 0,
                pct_cancelled: 0,
                completed_count: 0,
                processing_count: 0,
                on_hold_count: 0,
                cancelled_count: 0,
                total_orders: 0,
                path_d: "",
                area_d: "",
            },
            stores: [],
            recentOrders: [],
            selectedStoreId: "",
        });

        onWillStart(async () => {
            await this.loadData();
        });
    }

    async loadData() {
        const storeId = this.state.selectedStoreId ? parseInt(this.state.selectedStoreId) : null;
        const result = await this.orm.call("wc.dashboard", "get_dashboard_data", [], {
            store_id: storeId,
        });
        this.state.stats = result.stats;
        this.state.stores = result.stores;
        this.state.recentOrders = result.recent_orders;
    }

    async onStoreChange(ev) {
        this.state.selectedStoreId = ev.target.value;
        await this.loadData();
    }

    async actionSyncWizard() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Run WooCommerce Sync",
            res_model: "wc.sync.wizard",
            view_mode: "form",
            target: "new",
            views: [[false, "form"]],
        });
    }

    async actionRefresh() {
        await this.loadData();
    }

    formatCurrency(amount) {
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD',
        }).format(amount);
    }

    openOrders() {
        const domain = this.state.selectedStoreId ? [["backend_id", "=", parseInt(this.state.selectedStoreId)]] : [];
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "WooCommerce Orders",
            res_model: "wc.order",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: domain,
            target: "current",
        });
    }

    openProducts() {
        const domain = this.state.selectedStoreId ? [["backend_id", "=", parseInt(this.state.selectedStoreId)]] : [];
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "WooCommerce Products",
            res_model: "wc.product.link",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: domain,
            target: "current",
        });
    }

    openCustomers() {
        const domain = this.state.selectedStoreId ? [["backend_id", "=", parseInt(this.state.selectedStoreId)]] : [];
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "WooCommerce Customers",
            res_model: "wc.customer.link",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: domain,
            target: "current",
        });
    }

    openOrder(orderId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "wc.order",
            res_id: orderId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openStore(storeId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "wc.store",
            res_id: storeId,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

WooDashboard.template = "ad_woocomerce_connector.WooDashboard";
registry.category("actions").add("wc_dashboard_client_action", WooDashboard);
