import hashlib
import logging
from datetime import datetime

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

class WooCustomer(models.Model):

    _name = "wc.customer.link"
    _description = "WooCommerce Customer"
    _inherit = "wc.binding"
    _inherits = {"res.partner": "partner_id"}
    _rec_name = "name"

    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Odoo Contact",
        required=True,
        ondelete="cascade",
    )
    wc_username = fields.Char(string="Store Username")
    wc_role = fields.Char(string="WordPress Role")
    wc_orders_count = fields.Integer(string="Orders on Store")
    wc_total_spent = fields.Char(string="Total Spent on Store")

    _sql_constraints = [
        (
            "wc_customer_link_unique",
            "unique(backend_id, external_id)",
            "A WooCommerce customer with this ID already exists for this store.",
        )
    ]

    @api.model
    def syncing_from_wc(self, backend, records: list, force: bool = False):
        results = {"created": 0, "updated": 0, "skipped": 0, "failed": 0, "errors": []}
        for record in records:
            ext_id = str(record.get("id", ""))
            if not ext_id or ext_id == "0":
                continue
            try:
                binding, status = self._sync_one(backend, record, force)
                results[status] += 1
            except Exception as exc:
                _logger.exception(
                    "Failed syncing WooCommerce customer %s: %s", ext_id, exc
                )
                results["failed"] += 1
                results["errors"].append("Customer %s: %s" % (ext_id, exc))
        return results

    def _sync_one(self, backend, record: dict, force: bool = False):
        ext_id = str(record["id"])
        existing = self.search([
            ("backend_id", "=", backend.id),
            ("external_id", "=", ext_id),
        ], limit=1)

        email = (record.get("email") or "").strip()
        if not email and not backend.allow_customers_without_email:
            return None, "skipped"

        first = record.get("first_name", "")
        last = record.get("last_name", "")
        username = record.get("username", "")
        name = " ".join(filter(None, [first, last])) or username or email or "WooCommerce Customer"

        billing = record.get("billing", {}) or {}
        phone = billing.get("phone", "")

        vals = {
            "name": name,
            "email": email,
            "phone": phone,
            "wc_username": username,
            "wc_role": record.get("role", "customer"),
            "wc_orders_count": record.get("orders_count", 0),
            "wc_total_spent": str(record.get("total_spent", "")),
            "backend_id": backend.id,
            "external_id": ext_id,
            "sync_date": datetime.now(),
        }

        if existing:
            if not force and self._is_up_to_date(existing, record):
                return existing, "skipped"
            existing.with_context(syncing_from_wc=True).write(vals)
            self._sync_addresses(existing.partner_id, record)
            return existing, "updated"

        partner = None
        if email:
            partner = self.env["res.partner"].search(
                [("email", "=", email), ("is_company", "=", False)], limit=1
            )
            if partner and partner.wc_bind_ids.filtered(
                lambda b: b.backend_id.id == backend.id
            ):
                partner = None

        if not partner:
            partner = self.env["res.partner"].with_context(
                syncing_from_wc=True
            ).create({
                "name": name,
                "email": email,
                "phone": phone,
                "is_company": False,
                "customer_rank": 1,
            })

        vals["partner_id"] = partner.id
        binding = self.with_context(syncing_from_wc=True).create(vals)
        self._sync_addresses(partner, record)
        return binding, "created"

    def _sync_addresses(self, parent_partner, record: dict):
        for wc_key, odoo_type in [("billing", "invoice"), ("shipping", "delivery")]:
            addr = record.get(wc_key, {})
            if not addr or not any(v for v in addr.values() if v):
                continue
            self._upsert_address(parent_partner, addr, odoo_type)

    def _upsert_address(self, parent, addr: dict, atype: str):
        first = addr.get("first_name", "")
        last = addr.get("last_name", "")
        addr_name = " ".join(filter(None, [first, last])) or parent.name

        country = self.env["res.country"].search(
            [("code", "=", (addr.get("country") or "").upper())], limit=1
        )
        state = (
            self.env["res.country.state"].search([
                ("code", "=", (addr.get("state") or "").upper()),
                ("country_id", "=", country.id),
            ], limit=1)
            if country
            else self.env["res.country.state"]
        )

        hash_src = "|".join([
            addr_name,
            addr.get("address_1", ""),
            addr.get("city", ""),
            addr.get("postcode", ""),
            addr.get("country", ""),
            atype,
        ])
        hash_key = hashlib.md5(hash_src.encode()).hexdigest()

        existing = parent.child_ids.filtered(
            lambda c: c.type == atype and c.comment == hash_key
        )
        if existing:
            return

        old = parent.child_ids.filtered(lambda c: c.type == atype)
        if old:
            old.write({
                "name": addr_name,
                "street": addr.get("address_1", ""),
                "street2": addr.get("address_2", ""),
                "city": addr.get("city", ""),
                "zip": addr.get("postcode", ""),
                "country_id": country.id if country else False,
                "state_id": state.id if state else False,
                "comment": hash_key,
            })
            return

        self.env["res.partner"].create({
            "name": addr_name,
            "type": atype,
            "parent_id": parent.id,
            "email": addr.get("email", ""),
            "phone": addr.get("phone", ""),
            "street": addr.get("address_1", ""),
            "street2": addr.get("address_2", ""),
            "city": addr.get("city", ""),
            "zip": addr.get("postcode", ""),
            "country_id": country.id if country else False,
            "state_id": state.id if state else False,
            "comment": hash_key,
        })

    def push_to_store(self):
        from ..components.exporter import WooCustomerExporter
        exporter = WooCustomerExporter()

        def _op(binding):
            exporter.run(binding.backend_id, binding)
            binding.mark_synced("Customer pushed to WooCommerce.")

        return self._run_with_notification(_op, title="Push Complete")

    def pull_from_store(self):
        def _op(binding):
            client = binding.backend_id.get_api_client()
            result = client.get("customers/%s" % binding.external_id)
            data = result.get("data", {})
            if data:
                self.syncing_from_wc(binding.backend_id, [data], force=True)
                binding.mark_synced("Customer pulled from WooCommerce.")

        return self.filtered("external_id")._run_with_notification(_op, title="Pull Complete")

    def _is_up_to_date(self, binding, remote: dict) -> bool:
        if not binding.sync_date:
            return False
        modified = remote.get("date_modified_gmt") or remote.get("date_modified")
        if not modified:
            return False
        try:
            return binding.sync_date >= datetime.strptime(modified, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return False

class ResPartnerWoo(models.Model):
    _inherit = "res.partner"

    wc_bind_ids = fields.One2many(
        comodel_name="wc.customer.link",
        inverse_name="partner_id",
        string="WooCommerce Bindings",
        copy=False,
    )
