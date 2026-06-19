import logging
from datetime import datetime

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class WooOrder(models.Model):

    _name = "wc.order"
    _description = "WooCommerce Order"
    _inherit = "wc.binding"
    _inherits = {"sale.order": "order_id"}
    _rec_name = "name"

    order_id = fields.Many2one(
        comodel_name="sale.order",
        string="Odoo Sale Order",
        required=True,
        ondelete="cascade",
    )
    wc_order_number = fields.Integer(string="WooCommerce Order Number")
    wc_order_key = fields.Char(string="Order Key")
    wc_status_id = fields.Many2one(
        comodel_name="wc.order.stage",
        string="WooCommerce Status",
        ondelete="restrict",
    )
    wc_payment_mode_id = fields.Many2one(
        comodel_name="wc.payment.mode",
        string="Payment Method",
        ondelete="set null",
    )
    wc_discount_total = fields.Monetary(string="Discount Total", currency_field="currency_id")
    wc_shipping_total = fields.Monetary(string="Shipping Total", currency_field="currency_id")
    wc_total_tax = fields.Monetary(string="Tax Total", currency_field="currency_id")
    wc_order_total = fields.Monetary(string="WooCommerce Grand Total", currency_field="currency_id")
    wc_coupon_codes = fields.Char(string="Coupon Codes Applied")
    wc_customer_link_note = fields.Text(string="Customer Note")
    wc_line_ids = fields.One2many(
        comodel_name="wc.order.line",
        inverse_name="wc_order_id",
        string="WooCommerce Lines",
        copy=False,
    )
    wc_fulfillment_status = fields.Char(
        string="Fulfillment Status to Push",
        help="Status code to send back to WooCommerce on delivery.",
    )

    _sql_constraints = [
        (
            "wc_order_unique",
            "unique(backend_id, external_id)",
            "A WooCommerce order with this ID already exists for this store.",
        )
    ]

    def push_status_to_store(self):
        from ..components.exporter import WooOrderStatusExporter
        exporter = WooOrderStatusExporter()

        def _op(binding):
            if not binding.external_id:
                return
            exporter.run(binding.backend_id, binding)
            binding.mark_synced("Status pushed to WooCommerce.")

        return self._run_with_notification(_op, title="Push Status Complete")

    def pull_from_store(self):
        def _op(binding):
            client = binding.backend_id.get_api_client()
            result = client.get("orders/%s" % binding.external_id)
            data = result.get("data", {})
            if data:
                self.syncing_from_wc(binding.backend_id, [data], force=True)
                binding.mark_synced("Order pulled from WooCommerce.")

        return self.filtered("external_id")._run_with_notification(_op, title="Pull Complete")

    @api.model
    def syncing_from_wc(self, backend, records: list, force: bool = False):
        results = {"created": 0, "updated": 0, "skipped": 0, "failed": 0, "errors": []}
        for record in records:
            ext_id = str(record.get("id", ""))
            if not ext_id:
                continue
            try:
                binding, status = self._sync_one(backend, record, force)
                results[status] += 1
            except Exception as exc:
                _logger.exception("Failed syncing WooCommerce order %s: %s", ext_id, exc)
                results["failed"] += 1
                results["errors"].append("Order %s: %s" % (ext_id, exc))
        return results

    def _sync_one(self, backend, record: dict, force: bool = False):
        ext_id = str(record["id"])
        existing = self.search([
            ("backend_id", "=", backend.id),
            ("external_id", "=", ext_id),
        ], limit=1)

        if existing and not force:
            return existing, "skipped"

        partner = self._resolve_partner(backend, record)
        if not partner:
            _logger.warning("Could not resolve partner for WooCommerce order %s — skipping.", ext_id)
            return None, "skipped"

        currency = self._resolve_currency(record.get("currency", ""))
        status = self._resolve_status(record.get("status", ""))
        payment_method = self._resolve_payment_method(backend, record)

        order_name = "%s%s" % (
            backend.order_name_prefix or "WC-",
            record.get("number") or record["id"],
        )

        invoice_addr, delivery_addr = self._resolve_order_addresses(partner, record)

        order_vals = {
            "name": order_name,
            "partner_id": partner.id,
            "partner_invoice_id": invoice_addr.id,
            "partner_shipping_id": delivery_addr.id,
            "currency_id": currency.id if currency else self.env.company.currency_id.id,
            "warehouse_id": backend.warehouse_id.id if backend.warehouse_id else False,
            "team_id": backend.sales_team_id.id if backend.sales_team_id else False,
            "note": record.get("customer_note", ""),
            "company_id": backend.company_id.id,
        }

        binding_vals = {
            "wc_order_number": record.get("number", 0),
            "wc_order_key": record.get("order_key", ""),
            "wc_status_id": status.id if status else False,
            "wc_payment_mode_id": payment_method.id if payment_method else False,
            "wc_discount_total": self._safe_float(record.get("discount_total")),
            "wc_shipping_total": self._safe_float(record.get("shipping_total")),
            "wc_total_tax": self._safe_float(record.get("total_tax")),
            "wc_order_total": self._safe_float(record.get("total")),
            "wc_coupon_codes": ", ".join(
                c.get("code", "") for c in record.get("coupon_lines", [])
            ),
            "wc_customer_link_note": record.get("customer_note", ""),
            "backend_id": backend.id,
            "external_id": ext_id,
            "sync_date": datetime.now(),
        }

        if existing:
            if existing.order_id.state in ("draft", "sent"):
                existing.order_id.with_context(syncing_from_wc=True).write(order_vals)
            existing.with_context(syncing_from_wc=True).write(binding_vals)
            if force:
                self._sync_order_lines(backend, existing, record)
            return existing, "updated"

        odoo_order = self.env["sale.order"].with_context(
            syncing_from_wc=True
        ).create(order_vals)
        binding_vals["order_id"] = odoo_order.id
        binding = self.with_context(syncing_from_wc=True).create(binding_vals)
        self._sync_order_lines(backend, binding, record)
        _logger.info("Created wc.order %s for WooCommerce order %s", binding.id, ext_id)
        return binding, "created"

    def _sync_order_lines(self, backend, binding, record: dict):
        order = binding.order_id

        if order.state in ("draft", "sent"):
            binding.wc_line_ids.unlink()
            order.order_line.filtered(
                lambda l: l.wc_line_id
            ).unlink()

        lines_vals = []

        for item in record.get("line_items", []):
            product = self.env["wc.product.link"].get_or_create_for_order_line(backend, item)

            qty = self._safe_float(item.get("quantity"), default=1.0)
            total = self._safe_float(item.get("total"))
            price = (total / qty) if qty else self._safe_float(item.get("price"))

            tax_ids = self._resolve_line_taxes(backend, item, record)

            sol_vals = {
                "order_id": order.id,
                "product_id": product.id,
                "name": (item.get("name") or product.name or ""),
                "product_uom_qty": qty,
                "price_unit": price,
                "product_uom_id": product.uom_id.id,
                "tax_ids": [(6, 0, tax_ids)],
                "wc_line_id": str(item.get("id", "")),
            }
            sol = self.env["sale.order.line"].with_context(
                syncing_from_wc=True
            ).create(sol_vals)
            lines_vals.append({
                "wc_order_id": binding.id,
                "line_id": sol.id,
                "external_id": str(item.get("id", "")),
                "backend_id": backend.id,
                "wc_line_total": self._safe_float(item.get("total")),
                "wc_line_tax": self._safe_float(item.get("total_tax")),
            })

        for ship in record.get("shipping_lines", []):
            carrier_product = self._resolve_shipping_product(backend, ship)
            if not carrier_product:
                carrier_product = self._get_or_create_shipping_product(
                    ship.get("method_title") or "Shipping"
                )

            if not carrier_product:
                continue

            ship_vals = {
                "order_id": order.id,
                "product_id": carrier_product.id,
                "name": ship.get("method_title") or "Shipping",
                "product_uom_qty": 1,
                "price_unit": self._safe_float(ship.get("total")),
                "product_uom_id": carrier_product.uom_id.id,
                "is_delivery": True,
                "wc_line_id": str(ship.get("id", "")),
            }
            sol = self.env["sale.order.line"].with_context(
                syncing_from_wc=True
            ).create(ship_vals)
            lines_vals.append({
                "wc_order_id": binding.id,
                "line_id": sol.id,
                "external_id": str(ship.get("id", "")),
                "backend_id": backend.id,
                "wc_line_total": self._safe_float(ship.get("total")),
                "wc_line_tax": self._safe_float(ship.get("total_tax")),
            })

        for fee in record.get("fee_lines", []):
            fee_product = backend.default_fee_product_id
            if not fee_product:
                fee_product = self._get_or_create_fee_product(fee.get("name") or "Fee")
            if not fee_product:
                continue

            fee_line_vals = {
                "order_id": order.id,
                "product_id": fee_product.id,
                "name": fee.get("name") or "Fee",
                "product_uom_qty": 1,
                "price_unit": self._safe_float(fee.get("total")),
                "product_uom_id": fee_product.uom_id.id,
                "wc_line_id": str(fee.get("id", "")),
            }
            sol = self.env["sale.order.line"].with_context(
                syncing_from_wc=True
            ).create(fee_line_vals)
            lines_vals.append({
                "wc_order_id": binding.id,
                "line_id": sol.id,
                "external_id": str(fee.get("id", "")),
                "backend_id": backend.id,
                "wc_line_total": self._safe_float(fee.get("total")),
                "wc_line_tax": self._safe_float(fee.get("total_tax")),
            })

        for lv in lines_vals:
            self.env["wc.order.line"].with_context(syncing_from_wc=True).create(lv)

    def _resolve_partner(self, backend, record: dict):
        cust_id = record.get("customer_id", 0)
        if cust_id:
            binding = self.env["wc.customer.link"].search([
                ("backend_id", "=", backend.id),
                ("external_id", "=", str(cust_id)),
            ], limit=1)
            if binding and binding.partner_id:
                return binding.partner_id

            try:
                client = backend.get_api_client()
                result = client.get("customers/%s" % cust_id)
                data = result.get("data", {})
                if data:
                    self.env["wc.customer.link"].syncing_from_wc(backend, [data], force=False)
                    binding = self.env["wc.customer.link"].search([
                        ("backend_id", "=", backend.id),
                        ("external_id", "=", str(cust_id)),
                    ], limit=1)
                    if binding and binding.partner_id:
                        return binding.partner_id
            except Exception as exc:
                _logger.warning("Could not fetch customer %s: %s", cust_id, exc)

        billing = record.get("billing", {}) or {}
        email = (billing.get("email") or "").strip()
        first = billing.get("first_name", "")
        last = billing.get("last_name", "")
        name = " ".join(filter(None, [first, last])) or email or "WooCommerce Guest"

        if email:
            partner = self.env["res.partner"].search(
                [("email", "=", email), ("customer_rank", ">", 0)], limit=1
            )
            if partner:
                return partner

        country = self.env["res.country"].search(
            [("code", "=", (billing.get("country") or "").upper())], limit=1
        )
        state = (
            self.env["res.country.state"].search([
                ("code", "=", (billing.get("state") or "").upper()),
                ("country_id", "=", country.id),
            ], limit=1) if country else self.env["res.country.state"]
        )
        partner = self.env["res.partner"].create({
            "name": name,
            "email": email,
            "phone": billing.get("phone", ""),
            "street": billing.get("address_1", ""),
            "street2": billing.get("address_2", ""),
            "city": billing.get("city", ""),
            "zip": billing.get("postcode", ""),
            "country_id": country.id if country else False,
            "state_id": state.id if state else False,
            "is_company": bool(billing.get("company")),
            "company_name": billing.get("company", ""),
            "customer_rank": 1,
        })
        return partner

    def _resolve_order_addresses(self, partner, record: dict):
        billing = record.get("billing", {}) or {}
        shipping = record.get("shipping", {}) or {}

        invoice_addr = partner
        delivery_addr = partner

        if partner.child_ids:
            invoice_child = partner.child_ids.filtered(lambda c: c.type == "invoice")[:1]
            delivery_child = partner.child_ids.filtered(lambda c: c.type == "delivery")[:1]
            if invoice_child:
                invoice_addr = invoice_child
            if delivery_child:
                delivery_addr = delivery_child

        return invoice_addr, delivery_addr

    def _resolve_currency(self, code: str):
        if not code:
            return None
        currency = self.env["res.currency"].search(
            [("name", "=", code.upper())], limit=1
        )
        if currency and not currency.active:
            currency.sudo().write({"active": True})
        return currency

    def _resolve_status(self, code: str):
        if not code:
            return None
        status = self.env["wc.order.stage"].search([("code", "=", code)], limit=1)
        if not status:
            status = self.env["wc.order.stage"].create({
                "name": code.replace("-", " ").title(),
                "code": code,
            })
        return status

    def _resolve_payment_method(self, backend, record: dict):
        method_id = record.get("payment_method", "")
        if not method_id:
            return None
        pm = self.env["wc.payment.mode"].search([
            ("backend_id", "=", backend.id),
            ("external_id", "=", method_id),
        ], limit=1)
        if not pm:
            pm = self.env["wc.payment.mode"].with_context(syncing_from_wc=True).create({
                "name": record.get("payment_method_title") or method_id,
                "external_id": method_id,
                "backend_id": backend.id,
                "is_enabled": True,
            })
        return pm

    def _resolve_shipping_product(self, backend, ship: dict):
        method_id = ship.get("method_id", "")
        if method_id:
            wc_carrier = self.env["wc.shipping.carrier"].search([
                ("backend_id", "=", backend.id),
                ("wc_method_id", "=", method_id),
            ], limit=1)
            if wc_carrier and wc_carrier.carrier_id.product_id:
                return wc_carrier.carrier_id.product_id
        return backend.default_shipping_product_id

    def _get_or_create_shipping_product(self, name: str):
        product = self.env["product.product"].search([
            ("name", "=", name),
            ("type", "=", "service"),
        ], limit=1)
        if not product:
            product = self.env["product.product"].with_context(
                syncing_from_wc=True
            ).create({
                "name": name,
                "type": "service",
                "sale_ok": True,
                "purchase_ok": False,
            })
        return product

    def _get_or_create_fee_product(self, name: str):
        product = self.env["product.product"].search([
            ("name", "=", name),
            ("type", "=", "service"),
        ], limit=1)
        if not product:
            product = self.env["product.product"].with_context(
                syncing_from_wc=True
            ).create({
                "name": name,
                "type": "service",
                "sale_ok": True,
                "purchase_ok": False,
            })
        return product

    def _resolve_line_taxes(self, backend, item: dict, order_record: dict) -> list:
        tax_ids = []
        tax_lines = order_record.get("tax_lines", [])
        for tax in item.get("taxes", []):
            if not self._safe_float(tax.get("total")):
                continue
            rate_id = tax.get("id")
            wc_tax = self.env["wc.tax.link"].search([
                ("backend_id", "=", backend.id),
                ("external_id", "=", str(rate_id)),
            ], limit=1)
            if wc_tax and wc_tax.tax_id:
                tax_ids.append(wc_tax.tax_id.id)
                continue
            tax_line = next(
                (tl for tl in tax_lines if tl.get("rate_id") == rate_id), None
            )
            if tax_line:
                rate = self._safe_float(tax_line.get("rate_percent"))
                odoo_tax = self.env["account.tax"].search([
                    ("amount", "=", rate),
                    ("type_tax_use", "in", ["sale", "none"]),
                    ("company_id", "=", backend.company_id.id),
                ], limit=1)
                if odoo_tax:
                    tax_ids.append(odoo_tax.id)
        return tax_ids

    @staticmethod
    def _safe_float(val, default=0.0):
        try:
            return float(val) if val not in (None, "", False) else default
        except (ValueError, TypeError):
            return default

class WooOrderLine(models.Model):

    _name = "wc.order.line"
    _description = "WooCommerce Order Line"
    _inherit = "wc.binding"
    _inherits = {"sale.order.line": "line_id"}
    _rec_name = "external_id"

    line_id = fields.Many2one(
        comodel_name="sale.order.line",
        string="Odoo Order Line",
        required=True,
        ondelete="cascade",
    )
    wc_order_id = fields.Many2one(
        comodel_name="wc.order",
        string="WooCommerce Order",
        required=True,
        ondelete="cascade",
        index=True,
    )
    wc_line_total = fields.Monetary(
        string="Line Total",
        currency_field="currency_id",
    )
    wc_line_tax = fields.Monetary(
        string="Line Tax",
        currency_field="currency_id",
    )

    _sql_constraints = [
        (
            "wc_order_line_unique",
            "unique(backend_id, external_id)",
            "A WooCommerce order line with this ID already exists for this store.",
        )
    ]

class SaleOrderWoo(models.Model):
    _inherit = "sale.order"

    wc_bind_ids = fields.One2many(
        comodel_name="wc.order",
        inverse_name="order_id",
        string="WooCommerce Bindings",
        copy=False,
    )
    wc_order_stage = fields.Char(
        string="WooCommerce Status",
        compute="_compute_wc_order_stage",
        store=False,
    )
    all_deliveries_done = fields.Boolean(
        string="All Deliveries Completed",
        compute="_compute_all_deliveries_done",
        store=True,
    )

    @api.depends("wc_bind_ids", "wc_bind_ids.wc_status_id")
    def _compute_wc_order_stage(self):
        for order in self:
            binding = order.wc_bind_ids[:1]
            order.wc_order_stage = (
                binding.wc_status_id.name if binding and binding.wc_status_id else ""
            )

    @api.depends("picking_ids", "picking_ids.state")
    def _compute_all_deliveries_done(self):
        for order in self:
            pickings = order.picking_ids.filtered(
                lambda p: p.picking_type_code == "outgoing"
            )
            order.all_deliveries_done = bool(pickings) and all(
                p.state in ("done", "cancel") for p in pickings
            )

    def action_push_wc_status(self):
        for order in self:
            for binding in order.wc_bind_ids:
                binding.push_status_to_store()

class SaleOrderLineWoo(models.Model):
    _inherit = "sale.order.line"

    wc_line_id = fields.Char(
        string="WooCommerce Line ID",
        copy=False,
        index=True,
    )
    wc_bind_ids = fields.One2many(
        comodel_name="wc.order.line",
        inverse_name="line_id",
        string="WooCommerce Line Bindings",
        copy=False,
    )
