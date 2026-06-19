from odoo import fields, models

class WooTaxRate(models.Model):

    _name = "wc.tax.link"
    _description = "WooCommerce Tax Rate"
    _inherit = "wc.binding"
    _inherits = {"account.tax": "tax_id"}
    _rec_name = "name"

    tax_id = fields.Many2one(
        comodel_name="account.tax",
        string="Odoo Tax",
        required=True,
        ondelete="cascade",
    )
    wc_rate = fields.Float(
        string="WooCommerce Rate (%)",
        help="The tax percentage as defined in WooCommerce.",
    )
    wc_tax_class = fields.Char(
        string="Tax Class",
        help="WooCommerce tax class slug, e.g. 'standard', 'reduced-rate'.",
    )
    wc_compound = fields.Boolean(
        string="Compound Tax",
        help="Whether this tax is applied on top of other taxes.",
    )
    wc_shipping = fields.Boolean(
        string="Applies to Shipping",
        help="Whether this tax applies to shipping charges.",
    )

class AccountTaxWoo(models.Model):

    _inherit = "account.tax"

    wc_bind_ids = fields.One2many(
        comodel_name="wc.tax.link",
        inverse_name="tax_id",
        string="WooCommerce Bindings",
        copy=False,
    )
