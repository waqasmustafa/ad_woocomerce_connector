{
    "name": "WooCommerce Connector",
    "version": "18.0.1.0",
    "category": "Connector",
    "summary": "Synchronize Odoo with WooCommerce — Products, Orders, Customers, Taxes & Stock",
    "description": """
WooCommerce Connector for Odoo
=====================================================================
* Multi-backend support (multiple WooCommerce stores)
* Import: Products (simple + variable), Categories, Tags, Attributes,
          Customers, Sale Orders, Taxes, Shipping Methods, Payment Gateways
* Export: Products, Stock Inventory, Order Fulfillment Status, Customers, Categories
* Auto-create missing products when importing orders
* Webhook support for real-time bidirectional sync
* Scheduled cron jobs for automated sync
* Sandbox / Live mode per backend
""",
    "author": "ADream Innovations",
    "website": "https://adreaminnovations.odoo.com",
    "license": "LGPL-3",
    "depends": [
        "mail",
        "contacts",
        "sale_management",
        "delivery",
        "stock",
        "account",
    ],
    "external_dependencies": {
        "python": ["woocommerce", "requests"],
    },
    "data": [
        "security/ir.model.access.csv",
        "data/order_stage_data.xml",
        "data/ir_cron_data.xml",
        "wizard/wc_sync_wizard_view.xml",
        "views/order_stage_views.xml",
        "views/payment_views.xml",
        "views/shipping_views.xml",
        "views/tax_views.xml",
        "views/category_views.xml",
        "views/tag_views.xml",
        "views/attribute_views.xml",
        "views/product_link_views.xml",
        "views/customer_views.xml",
        "views/order_views.xml",
        "views/wc_store_views.xml",
        "views/dashboard_views.xml",
        "views/menu.xml",
    ],
    "images": ["static/description/banner.png"],
    "assets": {
        "web.assets_backend": [
            "ad_woocomerce_connector/static/src/css/wc_dashboard.css",
            "ad_woocomerce_connector/static/src/js/wc_dashboard.js",
            "ad_woocomerce_connector/static/src/xml/wc_dashboard.xml",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
