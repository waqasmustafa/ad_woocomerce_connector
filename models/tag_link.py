import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

class WooProductTag(models.Model):

    _name = "wc.tag"
    _description = "WooCommerce Product Tag"
    _inherit = "wc.binding"
    _rec_name = "name"

    name = fields.Char(string="Tag Name", required=True)
    slug = fields.Char(string="Slug")
    description = fields.Text(string="Description")
    product_count = fields.Integer(
        string="Product Count",
        help="Number of products with this tag in WooCommerce.",
    )

    _sql_constraints = [
        (
            "wc_tag_unique",
            "unique(backend_id, external_id)",
            "This WooCommerce tag already exists for this store.",
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
                _logger.exception("Failed syncing WooCommerce tag %s: %s", ext_id, exc)
                results["failed"] += 1
                results["errors"].append("Tag %s: %s" % (ext_id, exc))
        return results

    def _sync_one(self, backend, record: dict, force: bool = False):
        ext_id = str(record["id"])
        existing = self.search([
            ("backend_id", "=", backend.id),
            ("external_id", "=", ext_id),
        ], limit=1)

        vals = {
            "name": record.get("name") or "Unnamed Tag",
            "slug": record.get("slug", ""),
            "description": record.get("description", ""),
            "product_count": record.get("count", 0),
            "backend_id": backend.id,
            "external_id": ext_id,
            "sync_date": fields.Datetime.now(),
        }
        if existing:
            if not force:
                return existing, "skipped"
            existing.with_context(syncing_from_wc=True).write(vals)
            return existing, "updated"
        binding = self.with_context(syncing_from_wc=True).create(vals)
        return binding, "created"

    def push_to_store(self):
        from ..components.exporter import WooTagExporter
        exporter = WooTagExporter()

        def _op(binding):
            exporter.run(binding.backend_id, binding)
            binding.mark_synced("Tag pushed to WooCommerce.")

        return self._run_with_notification(_op, title="Push Complete")

    def pull_from_store(self):
        def _op(binding):
            client = binding.backend_id.get_api_client()
            result = client.get("products/tags/%s" % binding.external_id)
            data = result.get("data", {})
            if data:
                self.syncing_from_wc(binding.backend_id, [data], force=True)
                binding.mark_synced("Tag pulled from WooCommerce.")

        return self.filtered("external_id")._run_with_notification(_op, title="Pull Complete")
