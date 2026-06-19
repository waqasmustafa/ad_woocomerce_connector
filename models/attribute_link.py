import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

class WooProductAttribute(models.Model):

    _name = "wc.attribute.link"
    _description = "WooCommerce Product Attribute"
    _inherit = "wc.binding"
    _inherits = {"product.attribute": "attribute_id"}
    _rec_name = "name"

    attribute_id = fields.Many2one(
        comodel_name="product.attribute",
        string="Odoo Attribute",
        required=True,
        ondelete="cascade",
    )
    wc_slug = fields.Char(string="Attribute Slug")
    wc_type = fields.Char(
        string="Attribute Type",
        help="WooCommerce type, e.g. 'select', 'text', 'color'.",
    )
    wc_order_by = fields.Char(string="Order By")
    wc_has_archives = fields.Boolean(string="Has Archives")

    _sql_constraints = [
        (
            "wc_attribute_link_unique",
            "unique(backend_id, external_id)",
            "A WooCommerce attribute with this ID already exists for this store.",
        )
    ]

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
                _logger.exception("Failed syncing WooCommerce attribute %s: %s", ext_id, exc)
                results["failed"] += 1
                results["errors"].append("Attribute %s: %s" % (ext_id, exc))
        return results

    def _sync_one(self, backend, record: dict, force: bool = False):
        ext_id = str(record["id"])
        existing = self.search([
            ("backend_id", "=", backend.id),
            ("external_id", "=", ext_id),
        ], limit=1)

        attr_name = record.get("name") or "Unnamed Attribute"
        vals = {
            "name": attr_name,
            "wc_slug": record.get("slug", ""),
            "wc_type": record.get("type", "select"),
            "wc_order_by": record.get("order_by", ""),
            "wc_has_archives": record.get("has_archives", False),
            "backend_id": backend.id,
            "external_id": ext_id,
            "sync_date": fields.Datetime.now(),
        }

        if existing:
            if not force:
                return existing, "skipped"
            existing.with_context(syncing_from_wc=True).write(vals)
            return existing, "updated"
        else:
            odoo_attr = self.env["product.attribute"].search(
                [("name", "=", attr_name)], limit=1
            )
            if not odoo_attr:
                odoo_attr = self.env["product.attribute"].create({"name": attr_name})
            vals["attribute_id"] = odoo_attr.id
            binding = self.with_context(syncing_from_wc=True).create(vals)
            return binding, "created"

    def push_to_store(self):
        from ..components.exporter import WooAttributeExporter
        exporter = WooAttributeExporter()

        def _op(binding):
            exporter.run(binding.backend_id, binding)
            binding.mark_synced("Attribute pushed to WooCommerce.")

        return self._run_with_notification(_op, title="Push Complete")

    def pull_from_store(self):
        def _op(binding):
            client = binding.backend_id.get_api_client()
            result = client.get("products/attributes/%s" % binding.external_id)
            data = result.get("data", {})
            if data:
                self.syncing_from_wc(binding.backend_id, [data], force=True)
                binding.mark_synced("Attribute pulled from WooCommerce.")

        return self.filtered("external_id")._run_with_notification(_op, title="Pull Complete")

class WooProductAttributeValue(models.Model):

    _name = "wc.attribute.term"
    _description = "WooCommerce Attribute Value"
    _inherit = "wc.binding"
    _inherits = {"product.attribute.value": "value_id"}
    _rec_name = "name"

    value_id = fields.Many2one(
        comodel_name="product.attribute.value",
        string="Odoo Attribute Value",
        required=True,
        ondelete="cascade",
    )
    wc_attribute_id = fields.Many2one(
        comodel_name="wc.attribute.link",
        string="WooCommerce Attribute",
        ondelete="cascade",
        index=True,
    )
    wc_slug = fields.Char(string="Slug")
    wc_description = fields.Text(string="Description")
    wc_menu_order = fields.Integer(string="Menu Order")

    _sql_constraints = [
        (
            "wc_attribute_term_unique",
            "unique(backend_id, external_id)",
            "A WooCommerce attribute term with this ID already exists for this store.",
        )
    ]

    @api.model
    def sync_terms_from_wc(self, backend, wc_attribute, records: list, force: bool = False):
        results = {"created": 0, "updated": 0, "skipped": 0, "failed": 0, "errors": []}
        for record in records:
            ext_id = str(record.get("id", ""))
            if not ext_id:
                continue
            try:
                binding, status = self._sync_one(backend, wc_attribute, record, force)
                results[status] += 1
            except Exception as exc:
                _logger.exception("Failed syncing attribute term %s: %s", ext_id, exc)
                results["failed"] += 1
                results["errors"].append("Attribute Term %s: %s" % (ext_id, exc))
        return results

    def _sync_one(self, backend, wc_attribute, record: dict, force: bool = False):
        ext_id = str(record["id"])
        existing = self.search([
            ("backend_id", "=", backend.id),
            ("external_id", "=", ext_id),
        ], limit=1)

        term_name = record.get("name") or "Unnamed Value"
        vals = {
            "name": term_name,
            "wc_attribute_id": wc_attribute.id,
            "wc_slug": record.get("slug", ""),
            "wc_description": record.get("description", ""),
            "wc_menu_order": record.get("menu_order", 0),
            "backend_id": backend.id,
            "external_id": ext_id,
            "sync_date": fields.Datetime.now(),
        }

        if existing:
            if not force:
                return existing, "skipped"
            existing.with_context(syncing_from_wc=True).write(vals)
            return existing, "updated"
        else:
            odoo_attr = wc_attribute.attribute_id
            odoo_val = self.env["product.attribute.value"].search([
                ("attribute_id", "=", odoo_attr.id),
                ("name", "=", term_name),
            ], limit=1)
            if not odoo_val:
                odoo_val = self.env["product.attribute.value"].create({
                    "attribute_id": odoo_attr.id,
                    "name": term_name,
                })
            vals["value_id"] = odoo_val.id
            binding = self.with_context(syncing_from_wc=True).create(vals)
            return binding, "created"
