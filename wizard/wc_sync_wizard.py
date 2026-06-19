import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

SYNC_ACTIONS = [
    ("pull_metadata", "Refresh Metadata (Shipping & Payment Methods)"),
    ("pull_categories", "Pull Product Categories"),
    ("pull_tags", "Pull Product Tags"),
    ("pull_attributes", "Pull Product Attributes"),
    ("pull_taxes", "Pull Tax Rates"),
    ("pull_customers", "Pull Customers"),
    ("pull_products", "Pull Simple Products"),
    ("pull_variable_products", "Pull Variable Products"),
    ("pull_orders", "Pull Orders"),
    ("push_stock", "Push Stock Quantities to WooCommerce"),
    ("push_order_statuses", "Push Order Fulfillment Statuses"),
]

class WooSyncWizard(models.TransientModel):

    _name = "wc.sync.wizard"
    _description = "WooCommerce Sync Wizard"

    backend_id = fields.Many2one(
        comodel_name="wc.store",
        string="WooCommerce Store",
        required=True,
        domain=[("active", "=", True)],
        default=lambda self: self._default_backend(),
    )
    sync_action = fields.Selection(
        selection=SYNC_ACTIONS,
        string="What to Sync",
        required=True,
        default="pull_orders",
    )
    force_resync = fields.Boolean(
        string="Force Re-sync",
        help="Re-process records even if they appear up to date.",
    )
    result_summary = fields.Text(
        string="Result", readonly=True,
    )
    state = fields.Selection(
        [("draft", "Configure"), ("done", "Complete")],
        default="draft",
    )

    @api.model
    def _default_backend(self):
        return self.env["wc.store"].search(
            [("active", "=", True)], limit=1
        )

    def action_run_sync(self):
        self.ensure_one()
        backend = self.backend_id.with_context(return_raw_results=True)
        action = self.sync_action
        force = self.force_resync

        action_map = {
            "pull_metadata": backend.action_pull_metadata,
            "pull_categories": lambda: backend._do_pull_categories(force),
            "pull_tags": lambda: backend._do_pull_tags(force),
            "pull_attributes": lambda: backend._do_pull_attributes(force),
            "pull_taxes": lambda: backend._do_pull_taxes(force),
            "pull_customers": lambda: backend._do_pull_customers(force),
            "pull_products": lambda: backend._do_pull_products(force),
            "pull_variable_products": lambda: backend._do_pull_variable_products(force),
            "pull_orders": lambda: backend._do_pull_orders(force),
            "push_stock": backend.action_push_stock,
            "push_order_statuses": backend.action_push_order_statuses,
        }

        fn = action_map.get(action)
        if not fn:
            raise UserError(_("Unknown sync action: %s") % action)

        try:
            res = fn()
            if isinstance(res, dict) and any(k in res for k in ("created", "updated", "skipped", "failed")):
                created = res.get("created", 0)
                updated = res.get("updated", 0)
                skipped = res.get("skipped", 0)
                failed = res.get("failed", 0)
                errors = res.get("errors", [])
                
                label = dict(SYNC_ACTIONS).get(action, action)
                summary_lines = [
                    _("Sync Action: %s") % label,
                    _("Status: Completed"),
                    _("- Created: %d") % created,
                    _("- Updated: %d") % updated,
                    _("- Skipped: %d") % skipped,
                    _("- Failed: %d") % failed,
                ]
                if errors:
                    summary_lines.append(_("\nErrors / Warnings:"))
                    for err in errors[:50]:
                        summary_lines.append("  • %s" % err)
                    if len(errors) > 50:
                        summary_lines.append("  • ... and %d more errors" % (len(errors) - 50))
                summary = "\n".join(summary_lines)
            else:
                label = dict(SYNC_ACTIONS).get(action, action)
                summary = _("✓ '%s' completed successfully for store: %s") % (label, backend.name)
        except Exception as exc:
            _logger.exception("Manual sync failed: %s", exc)
            summary = _("✗ Sync failed: %s") % str(exc)

        self.write({"result_summary": summary, "state": "done"})
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_close(self):
        return {"type": "ir.actions.act_window_close"}
