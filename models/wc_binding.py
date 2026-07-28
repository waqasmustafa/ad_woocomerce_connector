import logging
from datetime import datetime

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

class WooBinding(models.AbstractModel):

    _name = "wc.binding"
    _description = "WooCommerce Binding (Abstract)"

    backend_id = fields.Many2one(
        comodel_name="wc.store",
        string="WooCommerce Store",
        required=True,
        ondelete="restrict",
        index=True,
    )
    external_id = fields.Char(
        string="WooCommerce ID",
        index=True,
        copy=False,
        help="The record's ID on the WooCommerce store.",
    )
    sync_date = fields.Datetime(
        string="Last Synced On",
        readonly=True,
        copy=False,
    )
    sync_message = fields.Text(
        string="Sync Notes",
        readonly=True,
        copy=False,
    )

    def mark_synced(self, message=None):
        self.write({
            "sync_date": datetime.now(),
            "sync_message": message or "",
        })

    @api.model
    def get_binding_by_ext_id(self, backend_id, external_id):
        return self.search([
            ("backend_id", "=", backend_id),
            ("external_id", "=", str(external_id)),
        ], limit=1)

    def _run_with_notification(self, operation, title="Operation Complete"):
        success, failed = 0, 0
        error_msgs = []
        for binding in self:
            try:
                operation(binding)
                success += 1
            except Exception as exc:
                name = binding.display_name or str(binding.id)
                error_msgs.append(f"{name}: {exc}")
                failed += 1
                _logger.exception("Operation failed on binding %s: %s", binding, exc)

        if self.env.context.get("return_raw_results"):
            return {
                "success": success,
                "failed": failed,
                "errors": error_msgs,
            }

        msg = f"Successfully processed {success} records."
        if failed:
            msg += f"\nFailed {failed} records:\n" + "\n".join(error_msgs)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title if not failed else f'{title} with Errors',
                'message': msg,
                'type': 'success' if not failed else 'danger',
                'sticky': bool(failed),
                'next': {
                    'type': 'ir.actions.client',
                    'tag': 'reload',
                }
            }
        }
