import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

class WooProductCategory(models.Model):

    _name = "wc.category.link"
    _description = "WooCommerce Product Category"
    _inherit = "wc.binding"
    _inherits = {"product.category": "category_id"}
    _rec_name = "name"

    category_id = fields.Many2one(
        comodel_name="product.category",
        string="Odoo Category",
        required=True,
        ondelete="cascade",
    )
    wc_slug = fields.Char(string="Slug")
    wc_description = fields.Text(string="WooCommerce Description")
    wc_count = fields.Integer(
        string="Product Count",
        help="Number of products in this category on WooCommerce.",
    )
    wc_parent_id = fields.Many2one(
        comodel_name="wc.category.link",
        string="Parent WooCommerce Category",
        ondelete="set null",
    )

    _sql_constraints = [
        (
            "wc_category_link_unique",
            "unique(backend_id, external_id)",
            "A WooCommerce category with this ID already exists for this store.",
        )
    ]

    @api.model
    def syncing_from_wc(self, backend, records: list, force: bool = False):
        results = {"created": 0, "updated": 0, "skipped": 0, "failed": 0, "errors": []}
        by_ext = {str(r["id"]): r for r in records if r.get("id")}

        def sort_key(r):
            parent = r.get("parent", 0)
            return 0 if not parent or str(parent) not in by_ext else 1

        sorted_records = sorted(records, key=sort_key)

        for record in sorted_records:
            ext_id = str(record.get("id", ""))
            if not ext_id:
                continue
            try:
                binding, status = self._sync_one(backend, record, force)
                results[status] += 1
            except Exception as exc:
                _logger.exception("Failed syncing WooCommerce category %s: %s", ext_id, exc)
                results["failed"] += 1
                results["errors"].append("Category %s: %s" % (ext_id, exc))
        return results

    def _sync_one(self, backend, record: dict, force: bool = False):
        ext_id = str(record["id"])
        existing = self.search([
            ("backend_id", "=", backend.id),
            ("external_id", "=", ext_id),
        ], limit=1)

        parent_woo = None
        parent_ext = str(record.get("parent") or "")
        if parent_ext and parent_ext != "0":
            parent_woo = self.search([
                ("backend_id", "=", backend.id),
                ("external_id", "=", parent_ext),
            ], limit=1)

        vals = {
            "name": record.get("name") or "Unnamed Category",
            "wc_slug": record.get("slug", ""),
            "wc_description": record.get("description", ""),
            "wc_count": record.get("count", 0),
            "backend_id": backend.id,
            "external_id": ext_id,
            "sync_date": fields.Datetime.now(),
        }
        if parent_woo:
            vals["parent_id"] = parent_woo.category_id.id
            vals["wc_parent_id"] = parent_woo.id

        if existing:
            if not force:
                return existing, "skipped"
            existing.with_context(syncing_from_wc=True).write(vals)
            return existing, "updated"
        else:
            cat_vals = {"name": vals["name"]}
            if parent_woo:
                cat_vals["parent_id"] = parent_woo.category_id.id
            category = self.env["product.category"].create(cat_vals)
            vals["category_id"] = category.id
            binding = self.with_context(syncing_from_wc=True).create(vals)
            return binding, "created"

    def push_to_store(self):
        from ..components.exporter import WooCategoryExporter
        exporter = WooCategoryExporter()

        def _op(binding):
            exporter.run(binding.backend_id, binding)
            binding.mark_synced("Category pushed to WooCommerce.")

        return self._run_with_notification(_op, title="Push Complete")

    def pull_from_store(self):
        def _op(binding):
            client = binding.backend_id.get_api_client()
            result = client.get("products/categories/%s" % binding.external_id)
            data = result.get("data", {})
            if data:
                self.syncing_from_wc(binding.backend_id, [data], force=True)
                binding.mark_synced("Category pulled from WooCommerce.")

        return self.filtered("external_id")._run_with_notification(_op, title="Pull Complete")

class ProductCategoryWoo(models.Model):

    _inherit = "product.category"

    wc_bind_ids = fields.One2many(
        comodel_name="wc.category.link",
        inverse_name="category_id",
        string="WooCommerce Bindings",
        copy=False,
    )
