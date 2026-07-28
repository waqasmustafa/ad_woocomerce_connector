from odoo import fields, models

class WooOrderStatus(models.Model):

    _name = "wc.order.stage"
    _description = "WooCommerce Order Status"
    _order = "sequence, name"

    name = fields.Char(string="Status Label", required=True, translate=True)
    code = fields.Char(
        string="Status Code",
        required=True,
        help="The slug used by WooCommerce, e.g. 'processing', 'completed'.",
    )
    sequence = fields.Integer(default=10)
    is_terminal = fields.Boolean(
        string="Terminal State",
        help="When enabled, orders in this status will not be re-exported.",
    )
    color = fields.Integer(string="Color Index")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("wc_status_code_unique", "unique(code)", "Status code must be unique."),
    ]
