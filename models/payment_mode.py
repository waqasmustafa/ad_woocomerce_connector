from odoo import api, fields, models, _
from odoo.exceptions import UserError

class WooPaymentMethod(models.Model):

    _name = "wc.payment.mode"
    _description = "WooCommerce Payment Method"
    _order = "name"

    name = fields.Char(string="Gateway Name", required=True)
    external_id = fields.Char(
        string="Gateway Code",
        required=True,
        help="The gateway slug used by WooCommerce, e.g. 'stripe', 'paypal'.",
    )
    backend_id = fields.Many2one(
        comodel_name="wc.store",
        string="WooCommerce Store",
        required=True,
        ondelete="cascade",
    )
    description = fields.Char(string="Description")
    is_enabled = fields.Boolean(string="Enabled on Store", default=True)
    journal_id = fields.Many2one(
        comodel_name="account.journal",
        string="Accounting Journal",
        domain=[("type", "in", ["bank", "cash"])],
        help="Map this payment method to an Odoo journal for automatic reconciliation.",
    )

    _sql_constraints = [
        (
            "wc_payment_mode_unique",
            "unique(backend_id, external_id)",
            "This payment gateway already exists for this store.",
        )
    ]

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("syncing_from_wc") and not self.env.su:
            raise UserError(_("Payment methods must be configured and synced from WooCommerce itself."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.context.get("syncing_from_wc") and not self.env.su:
            if any(k != "journal_id" for k in vals.keys()):
                raise UserError(_("WooCommerce Payment Method fields (except journal mapping) are read-only and configured from WooCommerce."))
        return super().write(vals)

    def unlink(self):
        if not self.env.context.get("syncing_from_wc") and not self.env.su:
            raise UserError(_("WooCommerce Payment Methods cannot be deleted manually."))
        return super().unlink()
