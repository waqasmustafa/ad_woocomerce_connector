from odoo import api, fields, models, _
from odoo.exceptions import UserError

class WooShippingMethod(models.Model):

    _name = "wc.shipping.carrier"
    _description = "WooCommerce Shipping Method"
    _inherit = "wc.binding"
    _inherits = {"delivery.carrier": "carrier_id"}
    _rec_name = "name"

    carrier_id = fields.Many2one(
        comodel_name="delivery.carrier",
        string="Odoo Delivery Carrier",
        required=True,
        ondelete="cascade",
    )
    wc_method_id = fields.Char(
        string="WooCommerce Method ID",
        help="The method_id slug from WooCommerce, e.g. 'flat_rate', 'free_shipping'.",
    )
    wc_instance_id = fields.Char(
        string="Instance ID",
        help="The shipping zone instance ID from WooCommerce.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("syncing_from_wc") and not self.env.su:
            raise UserError(_("Shipping methods must be configured and synced from WooCommerce itself."))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.context.get("syncing_from_wc") and not self.env.su:
            raise UserError(_("WooCommerce Shipping Method fields are read-only and configured from WooCommerce."))
        return super().write(vals)

    def unlink(self):
        if not self.env.context.get("syncing_from_wc") and not self.env.su:
            raise UserError(_("WooCommerce Shipping Methods cannot be deleted manually."))
        return super().unlink()

class DeliveryCarrierWoo(models.Model):

    _inherit = "delivery.carrier"

    wc_bind_ids = fields.One2many(
        comodel_name="wc.shipping.carrier",
        inverse_name="carrier_id",
        string="WooCommerce Bindings",
        copy=False,
    )
