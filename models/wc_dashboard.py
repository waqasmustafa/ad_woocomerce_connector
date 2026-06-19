from datetime import datetime, timedelta
from odoo import api, fields, models, _

class WooDashboard(models.TransientModel):
    _name = "wc.dashboard"
    _description = "WooCommerce Dashboard"

    name = fields.Char(string="Dashboard Title", default="WooCommerce Sync Dashboard")
    backend_id = fields.Many2one(
        comodel_name="wc.store",
        string="Filter by Store",
    )

    @api.model
    def get_dashboard_data(self, store_id=None):
        domain = []
        if store_id:
            domain.append(("backend_id", "=", int(store_id)))

        stores = self.env["wc.store"].search([])
        stores_data = []
        for s in stores:
            stores_data.append({
                "id": s.id,
                "name": s.name,
                "active": s.active,
                "use_sandbox": s.use_sandbox,
                "url": s.sandbox_url if s.use_sandbox else s.store_url,
            })

        order_count = self.env["wc.order"].search_count(domain)
        product_count = self.env["wc.product.link"].search_count(domain)
        customer_count = self.env["wc.customer.link"].search_count(domain)

        orders = self.env["wc.order"].search(domain, order="sync_date desc, id desc")
        total_revenue = sum(orders.mapped("wc_order_total"))

        today = datetime.now().date()
        spark_revs = []
        spark_labels = []
        for i in range(6, -1, -1):
            d = today - timedelta(days=i)
            day_orders = orders.filtered(lambda o: o.sync_date and o.sync_date.date() == d)
            day_total = sum(day_orders.mapped("wc_order_total"))
            spark_labels.append(d.strftime("%b %d"))
            spark_revs.append(day_total)

        max_rev = max(spark_revs) if spark_revs and max(spark_revs) > 0 else 1
        points = []
        for idx, val in enumerate(spark_revs):
            x = int(idx * 28 + 10)
            y = int(45 - (val / max_rev * 35))
            points.append((x, y))
        path_d = "M " + " L ".join(f"{x},{y}" for x, y in points) if points else ""
        area_d = f"{path_d} L {points[-1][0]},48 L {points[0][0]},48 Z" if points else ""

        total_orders = len(orders) or 1
        completed = len(orders.filtered(lambda o: o.wc_status_id.code == "completed"))
        processing = len(orders.filtered(lambda o: o.wc_status_id.code == "processing"))
        on_hold = len(orders.filtered(lambda o: o.wc_status_id.code == "on-hold"))
        cancelled = len(orders.filtered(lambda o: o.wc_status_id.code == "cancelled"))

        stats = {
            "order_count": order_count,
            "product_count": product_count,
            "customer_count": customer_count,
            "total_revenue": total_revenue,
            "spark_labels": spark_labels,
            "spark_revs": spark_revs,
            "path_d": path_d,
            "area_d": area_d,
            "pct_completed": int((completed / total_orders) * 100),
            "pct_processing": int((processing / total_orders) * 100),
            "pct_on_hold": int((on_hold / total_orders) * 100),
            "pct_cancelled": int((cancelled / total_orders) * 100),
            "completed_count": completed,
            "processing_count": processing,
            "on_hold_count": on_hold,
            "cancelled_count": cancelled,
            "total_orders": len(orders),
        }

        recent_orders = []
        for o in orders[:8]:
            recent_orders.append({
                "id": o.id,
                "name": o.name,
                "external_id": o.external_id,
                "date": o.sync_date.strftime("%Y-%m-%d %H:%M") if o.sync_date else "N/A",
                "status": o.wc_status_id.name or "Pending",
                "status_code": o.wc_status_id.code or "pending",
                "total": o.wc_order_total,
            })

        return {
            "stats": stats,
            "stores": stores_data,
            "recent_orders": recent_orders,
        }
