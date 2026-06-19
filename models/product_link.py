import base64
import logging

import requests

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def _fetch_image_b64(url):
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200 and resp.content:
            import io
            from PIL import Image
            try:
                Image.open(io.BytesIO(resp.content)).verify()
            except Exception:
                _logger.warning("Image from %s failed PIL verify, skipping", url)
                return None
            return base64.b64encode(resp.content).decode("utf-8")
    except Exception as e:
        _logger.warning("Could not download product image from %s: %s", url, e)
    return None

PRODUCT_STATUS = [
    ("draft", "Draft"),
    ("pending", "Pending Review"),
    ("private", "Private"),
    ("publish", "Published"),
]

STOCK_STATUS = [
    ("instock", "In Stock"),
    ("outofstock", "Out of Stock"),
    ("onbackorder", "On Backorder"),
]

class WooProduct(models.Model):

    _name = "wc.product.link"
    _description = "WooCommerce Product"
    _inherit = "wc.binding"
    _inherits = {"product.product": "product_id"}
    _rec_name = "name"

    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Odoo Product Variant",
        required=True,
        ondelete="cascade",
    )
    wc_product_name = fields.Char(string="Name on Store")
    wc_status = fields.Selection(PRODUCT_STATUS, string="Store Status", default="publish")
    wc_stock_status = fields.Selection(STOCK_STATUS, string="Stock Status", default="instock")
    wc_manage_stock = fields.Boolean(string="Store Manages Stock")
    wc_stock_qty = fields.Float(
        string="Synced Qty",
        help="Last stock quantity pushed to WooCommerce.",
    )
    wc_regular_price = fields.Char(string="Regular Price")
    wc_sale_price = fields.Char(string="Sale Price")
    wc_sku = fields.Char(string="SKU on Store")
    wc_weight = fields.Char(string="Weight")
    wc_category_ids = fields.Many2many(
        comodel_name="wc.category.link",
        string="WooCommerce Categories",
    )
    wc_tag_ids = fields.Many2many(
        comodel_name="wc.tag",
        string="WooCommerce Tags",
    )
    wc_image_urls = fields.Text(
        string="Image URLs",
        help="Comma-separated image URLs from WooCommerce.",
    )
    is_variation = fields.Boolean(
        string="Is Variation",
        help="Set when this product is a variation of a variable product.",
    )
    wc_template_id = fields.Many2one(
        comodel_name="wc.template.link",
        string="Parent Template",
        ondelete="set null",
    )

    _sql_constraints = [
        (
            "wc_product_link_unique",
            "unique(backend_id, external_id)",
            "A WooCommerce product with this ID already exists for this store.",
        )
    ]

    def push_to_store(self):
        from ..components.exporter import WooProductExporter
        exporter = WooProductExporter()

        def _op(binding):
            if binding.wc_manage_stock:
                qty = binding._get_computed_stock()
                binding.with_context(syncing_from_wc=True).write({"wc_stock_qty": qty})
            exporter.run(binding.backend_id, binding)
            binding.mark_synced("Product pushed to WooCommerce.")

        return self._run_with_notification(_op, title="Push Complete")

    def push_stock_to_store(self):
        from ..components.exporter import WooStockExporter
        exporter = WooStockExporter()

        def _op(binding):
            qty = binding._get_computed_stock()
            binding.with_context(syncing_from_wc=True).write({"wc_stock_qty": qty})
            exporter.run(binding.backend_id, binding)
            binding.mark_synced("Stock pushed to WooCommerce.")

        return self.filtered("external_id")._run_with_notification(_op, title="Push Stock Complete")

    def _get_computed_stock(self):
        backend = self.backend_id
        warehouses = backend.stock_warehouse_ids
        if not warehouses:
            return self.product_id.qty_available
        total = 0.0
        for wh in warehouses:
            total += self.product_id.with_context(warehouse=wh.id).qty_available
        return total

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
                _logger.exception("Failed syncing WooCommerce product %s: %s", ext_id, exc)
                results["failed"] += 1
                results["errors"].append("Product %s: %s" % (ext_id, exc))
        return results

    def _sync_one(self, backend, record: dict, force: bool = False):
        from datetime import datetime
        ext_id = str(record["id"])

        existing = self.search([
            ("backend_id", "=", backend.id),
            ("external_id", "=", ext_id),
        ], limit=1)

        sku = (record.get("sku") or "").strip()

        if not sku and not backend.allow_products_without_sku and not force:
            _logger.debug(
                "Skipping WooCommerce product %s — no SKU and 'allow_products_without_sku' is off.",
                ext_id,
            )
            return None, "skipped"

        name = (record.get("name") or "").strip() or "WooCommerce Product %s" % ext_id
        product_type = backend.default_product_type or "consu"

        regular_price_raw = record.get("regular_price") or record.get("price") or ""
        try:
            list_price = float(regular_price_raw) if regular_price_raw else 0.0
        except (ValueError, TypeError):
            list_price = 0.0

        weight_raw = record.get("weight") or ""
        try:
            weight = float(weight_raw) if weight_raw else 0.0
        except (ValueError, TypeError):
            weight = 0.0

        stock_qty_raw = record.get("stock_quantity")
        try:
            stock_qty = float(stock_qty_raw) if stock_qty_raw is not None else 0.0
        except (ValueError, TypeError):
            stock_qty = 0.0

        cat_ids = self._resolve_categories(backend, record.get("categories", []))
        tag_ids = self._resolve_tags(backend, record.get("tags", []))

        images = ",".join(
            img.get("src", "") for img in record.get("images", []) if img.get("src")
        )

        vals = {
            "wc_product_name": name,
            "wc_status": record.get("status", "publish"),
            "wc_stock_status": record.get("stock_status", "instock"),
            "wc_manage_stock": bool(record.get("manage_stock", False)),
            "wc_stock_qty": stock_qty,
            "wc_regular_price": regular_price_raw,
            "wc_sale_price": record.get("sale_price", ""),
            "wc_sku": sku,
            "wc_weight": weight_raw,
            "wc_image_urls": images,
            "wc_category_ids": [(6, 0, cat_ids)],
            "wc_tag_ids": [(6, 0, tag_ids)],
            "backend_id": backend.id,
            "external_id": ext_id,
            "sync_date": datetime.now(),
        }

        if existing:
            if not force and self._is_up_to_date(existing, record):
                return existing, "skipped"
            existing.product_id.with_context(syncing_from_wc=True).write({
                "name": name,
                "default_code": sku or existing.product_id.default_code,
                "list_price": list_price,
                "weight": weight,
            })
            existing.with_context(syncing_from_wc=True).write(vals)
            if images and not existing.product_id.product_tmpl_id.image_1920:
                first_url = images.split(",")[0].strip()
                img_b64 = _fetch_image_b64(first_url)
                if img_b64:
                    existing.product_id.product_tmpl_id.with_context(
                        syncing_from_wc=True
                    ).write({"image_1920": img_b64})
            return existing, "updated"

        odoo_product = None
        if sku and backend.match_product_by_sku:
            odoo_product = self.env["product.product"].search(
                [("default_code", "=", sku)], limit=1
            )
            if odoo_product:
                _logger.info(
                    "Matched WooCommerce product %s to existing Odoo product %s by SKU '%s'",
                    ext_id, odoo_product.id, sku,
                )

        is_var = record.get("parent_id") or record.get("is_variation") or False
        if not odoo_product and not is_var:
            odoo_product = self.env["product.product"].search(
                [("name", "=", name)], limit=1
            )
            if odoo_product:
                _logger.info(
                    "Matched WooCommerce product %s to existing Odoo product %s by Name '%s'",
                    ext_id, odoo_product.id, name,
                )

        if not odoo_product:
            categ_id = (
                backend.default_category_id.id
                if backend.default_category_id
                else self.env.ref("product.product_category_goods").id
            )
            odoo_product = self.env["product.product"].with_context(
                syncing_from_wc=True
            ).create({
                "name": name,
                "default_code": sku,
                "type": product_type if product_type in ("consu", "service") else "consu",
                "categ_id": categ_id,
                "list_price": list_price,
                "weight": weight,
                "sale_ok": True,
                "purchase_ok": True,
            })

        if images:
            first_url = images.split(",")[0].strip()
            img_b64 = _fetch_image_b64(first_url)
            if img_b64:
                odoo_product.product_tmpl_id.with_context(syncing_from_wc=True).write(
                    {"image_1920": img_b64}
                )

        vals["product_id"] = odoo_product.id
        binding = self.with_context(syncing_from_wc=True).create(vals)
        _logger.info(
            "Created wc.product.link %s for WooCommerce product %s (%s)",
            binding.id, ext_id, name,
        )
        return binding, "created"

    def _resolve_categories(self, backend, cat_list: list) -> list:
        ids = []
        for cat in cat_list:
            wc_cat = self.env["wc.category.link"].search([
                ("backend_id", "=", backend.id),
                ("external_id", "=", str(cat.get("id", ""))),
            ], limit=1)
            if wc_cat:
                ids.append(wc_cat.id)
        return ids

    def _resolve_tags(self, backend, tag_list: list) -> list:
        ids = []
        for tag in tag_list:
            wc_tag = self.env["wc.tag"].search([
                ("backend_id", "=", backend.id),
                ("external_id", "=", str(tag.get("id", ""))),
            ], limit=1)
            if wc_tag:
                ids.append(wc_tag.id)
        return ids

    def _is_up_to_date(self, binding, remote_record: dict) -> bool:
        if not binding.sync_date:
            return False
        modified_str = (
            remote_record.get("date_modified_gmt")
            or remote_record.get("date_modified")
        )
        if not modified_str:
            return False
        from datetime import datetime
        try:
            remote_dt = datetime.strptime(modified_str, "%Y-%m-%dT%H:%M:%S")
            return binding.sync_date >= remote_dt
        except ValueError:
            return False

    def pull_from_store(self):
        def _op(binding):
            client = binding.backend_id.get_api_client()
            if binding.is_variation and binding.wc_template_id and binding.wc_template_id.external_id:
                result = client.get(
                    "products/%s/variations/%s" % (
                        binding.wc_template_id.external_id,
                        binding.external_id,
                    )
                )
            else:
                result = client.get("products/%s" % binding.external_id)
            data = result.get("data", {})
            if data:
                self.syncing_from_wc(binding.backend_id, [data], force=True)
                binding.mark_synced("Product pulled from WooCommerce.")

        return self.filtered("external_id")._run_with_notification(_op, title="Pull Complete")

    @api.model
    def get_or_create_for_order_line(self, backend, item: dict):
        var_id = item.get("variation_id", 0)
        prod_id = item.get("product_id", 0)
        ext_id = str(var_id) if var_id else str(prod_id) if prod_id else ""

        if ext_id and ext_id != "0":
            binding = self.search([
                ("backend_id", "=", backend.id),
                ("external_id", "=", ext_id),
            ], limit=1)
            if binding and binding.product_id:
                return binding.product_id

            client = backend.get_api_client()
            try:
                if var_id and prod_id:
                    parent_result = client.get("products/%s" % prod_id)
                    parent_data = parent_result.get("data", {})
                    if parent_data:
                        self.env["wc.template.link"].syncing_from_wc(
                            backend, [parent_data], force=True
                        )
                    binding = self.search([
                        ("backend_id", "=", backend.id),
                        ("external_id", "=", ext_id),
                    ], limit=1)
                    if binding and binding.product_id:
                        return binding.product_id

                    var_result = client.get("products/%s/variations/%s" % (prod_id, var_id))
                    var_data = var_result.get("data", {})
                    if var_data:
                        if not var_data.get("name") and parent_data.get("name"):
                            attr_parts = [
                                a.get("option", "")
                                for a in var_data.get("attributes", [])
                                if a.get("option")
                            ]
                            var_data["name"] = parent_data["name"]
                            if attr_parts:
                                var_data["name"] += " - " + ", ".join(attr_parts)
                        binding = self._sync_one(backend, var_data, force=True)
                        if binding and binding.product_id:
                            binding.with_context(syncing_from_wc=True).write({"is_variation": True})
                            return binding.product_id

                elif prod_id:
                    result = client.get("products/%s" % prod_id)
                    data = result.get("data", {})
                    if data:
                        binding = self._sync_one(backend, data, force=True)
                        if binding and binding.product_id:
                            return binding.product_id

            except Exception as exc:
                _logger.warning(
                    "Could not fetch WooCommerce product (prod_id=%s, var_id=%s): %s",
                    prod_id, var_id, exc,
                )

        sku = (item.get("sku") or "").strip()
        if sku:
            product = self.env["product.product"].search(
                [("default_code", "=", sku)], limit=1
            )
            if product:
                return product

        item_name = (item.get("name") or "").strip() or "WooCommerce Product"
        _logger.warning(
            "Creating fallback Odoo product for WooCommerce item '%s' (ext_id=%s, sku=%s)",
            item_name, ext_id, sku,
        )
        categ_id = (
            backend.default_category_id.id
            if backend.default_category_id
            else self.env.ref("product.product_category_goods").id
        )
        _fallback_type = backend.default_product_type or "consu"
        new_product = self.env["product.product"].with_context(
            syncing_from_wc=True
        ).create({
            "name": item_name,
            "default_code": sku or False,
            "type": _fallback_type if _fallback_type in ("consu", "service") else "consu",
            "categ_id": categ_id,
            "list_price": self._safe_float(
                item.get("price") or item.get("subtotal_tax") or 0
            ),
            "sale_ok": True,
            "purchase_ok": True,
        })

        if ext_id and ext_id != "0":
            try:
                self.with_context(syncing_from_wc=True).create({
                    "product_id": new_product.id,
                    "backend_id": backend.id,
                    "external_id": ext_id,
                    "wc_product_name": item_name,
                    "wc_sku": sku,
                })
            except Exception:
                pass

        return new_product

    @staticmethod
    def _safe_float(val, default=0.0):
        try:
            return float(val) if val not in (None, "", False) else default
        except (ValueError, TypeError):
            return default

class ProductProductWoo(models.Model):
    _inherit = "product.product"

    wc_bind_ids = fields.One2many(
        comodel_name="wc.product.link",
        inverse_name="product_id",
        string="WooCommerce Bindings",
        copy=False,
    )

    def action_push_stock_to_store(self):
        self.mapped("wc_bind_ids").push_stock_to_store()

    def action_push_product_to_store(self):
        backends = self.env["wc.store"].search([("active", "=", True)])
        if not backends:
            raise UserError("No active WooCommerce stores found.")

        for product in self:
            for backend in backends:
                binding = self.env["wc.product.link"].search([
                    ("product_id", "=", product.id),
                    ("backend_id", "=", backend.id),
                ], limit=1)

                if not binding:
                    binding = self.env["wc.product.link"].with_context(
                        syncing_from_wc=True
                    ).create({
                        "product_id": product.id,
                        "backend_id": backend.id,
                        "wc_product_name": product.name,
                        "wc_sku": product.default_code or "",
                        "wc_regular_price": str(product.list_price),
                        "wc_manage_stock": True,
                    })

                binding.push_to_store()

class WooProductTemplate(models.Model):

    _name = "wc.template.link"
    _description = "WooCommerce Variable Product"
    _inherit = "wc.binding"
    _inherits = {"product.template": "template_id"}
    _rec_name = "name"

    template_id = fields.Many2one(
        comodel_name="product.template",
        string="Odoo Product Template",
        required=True,
        ondelete="cascade",
    )
    wc_product_name = fields.Char(string="Name on Store")
    wc_status = fields.Selection(PRODUCT_STATUS, string="Store Status", default="publish")
    wc_sku = fields.Char(string="Template SKU")
    wc_regular_price = fields.Char(string="Regular Price")
    wc_variation_ids = fields.One2many(
        comodel_name="wc.product.link",
        inverse_name="wc_template_id",
        string="Variations",
        copy=False,
    )
    wc_category_ids = fields.Many2many(
        comodel_name="wc.category.link",
        string="WooCommerce Categories",
    )
    wc_tag_ids = fields.Many2many(
        comodel_name="wc.tag",
        string="WooCommerce Tags",
    )
    wc_image_urls = fields.Text(string="Image URLs")

    _sql_constraints = [
        (
            "wc_template_link_unique",
            "unique(backend_id, external_id)",
            "A WooCommerce variable product with this ID already exists for this store.",
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
                binding, status = self._sync_one(backend, record, force, results)
                results[status] += 1
            except Exception as exc:
                _logger.exception("Failed syncing variable product %s: %s", ext_id, exc)
                results["failed"] += 1
                results["errors"].append("Variable Product %s: %s" % (ext_id, exc))
        return results

    def _sync_one(self, backend, record: dict, force: bool = False, results=None):
        from datetime import datetime
        ext_id = str(record["id"])
        existing = self.search([
            ("backend_id", "=", backend.id),
            ("external_id", "=", ext_id),
        ], limit=1)

        name = (record.get("name") or "").strip() or "WooCommerce Variable Product %s" % ext_id
        images = ",".join(
            img.get("src", "") for img in record.get("images", []) if img.get("src")
        )
        cat_ids = self.env["wc.product.link"]._resolve_categories(
            backend, record.get("categories", [])
        )
        tag_ids = self.env["wc.product.link"]._resolve_tags(
            backend, record.get("tags", [])
        )

        regular_price_raw = record.get("regular_price") or record.get("price") or ""
        try:
            list_price = float(regular_price_raw) if regular_price_raw else 0.0
        except (ValueError, TypeError):
            list_price = 0.0

        vals = {
            "wc_product_name": name,
            "wc_status": record.get("status", "publish"),
            "wc_sku": record.get("sku", ""),
            "wc_regular_price": regular_price_raw,
            "wc_image_urls": images,
            "wc_category_ids": [(6, 0, cat_ids)],
            "wc_tag_ids": [(6, 0, tag_ids)],
            "backend_id": backend.id,
            "external_id": ext_id,
            "sync_date": datetime.now(),
        }

        if existing:
            if not force:
                self._sync_variations(backend, existing, record, force, results)
                return existing, "skipped"
            existing.template_id.with_context(syncing_from_wc=True).write({
                "name": name,
                "list_price": list_price,
            })
            existing.with_context(syncing_from_wc=True).write(vals)
            if images and not existing.template_id.image_1920:
                first_url = images.split(",")[0].strip()
                img_b64 = _fetch_image_b64(first_url)
                if img_b64:
                    existing.template_id.with_context(
                        syncing_from_wc=True
                    ).write({"image_1920": img_b64})
            self._sync_variations(backend, existing, record, force, results)
            return existing, "updated"

        odoo_tmpl = None
        tmpl_sku = (record.get("sku") or "").strip()
        if tmpl_sku and backend.match_product_by_sku:
            odoo_tmpl = self.env["product.template"].search(
                [("default_code", "=", tmpl_sku)], limit=1
            )
            if odoo_tmpl:
                _logger.info(
                    "Matched WooCommerce variable template %s to existing Odoo template %s by SKU '%s'",
                    ext_id, odoo_tmpl.id, tmpl_sku,
                )
        if not odoo_tmpl:
            odoo_tmpl = self.env["product.template"].search(
                [("name", "=", name)], limit=1
            )
            if odoo_tmpl:
                _logger.info(
                    "Matched WooCommerce variable template %s to existing Odoo template %s by Name '%s'",
                    ext_id, odoo_tmpl.id, name,
                )

        if odoo_tmpl:
            odoo_tmpl.with_context(syncing_from_wc=True).write({
                "name": name,
                "list_price": list_price,
                "default_code": tmpl_sku or odoo_tmpl.default_code,
            })
        else:
            categ_id = (
                backend.default_category_id.id
                if backend.default_category_id
                else self.env.ref("product.product_category_goods").id
            )
            _ptype = backend.default_product_type or "consu"
            odoo_tmpl = self.env["product.template"].with_context(
                syncing_from_wc=True
            ).create({
                "name": name,
                "type": _ptype if _ptype in ("consu", "service") else "consu",
                "categ_id": categ_id,
                "list_price": list_price,
                "sale_ok": True,
                "default_code": tmpl_sku or False,
            })

        if images and not odoo_tmpl.image_1920:
            first_url = images.split(",")[0].strip()
            img_b64 = _fetch_image_b64(first_url)
            if img_b64:
                odoo_tmpl.with_context(syncing_from_wc=True).write(
                    {"image_1920": img_b64}
                )

        vals["template_id"] = odoo_tmpl.id
        vals["name"] = name
        tmpl_binding = self.with_context(syncing_from_wc=True).create(vals)
        _logger.info(
            "Created wc.template.link %s for variable product %s (%s)",
            tmpl_binding.id, ext_id, name,
        )
        self._sync_variations(backend, tmpl_binding, record, force, results)
        return tmpl_binding, "created"

    def _sync_variations(self, backend, tmpl_binding, record: dict, force: bool, results=None):
        variation_ids = record.get("variations", [])
        if not variation_ids:
            return

        client = backend.get_api_client()
        var_endpoint = "products/%s/variations" % record["id"]
        try:
            var_records = []
            for page in client.get_all_pages(var_endpoint, {"per_page": 100}):
                var_records.extend(page)
        except Exception as exc:
            _logger.warning("Could not fetch variations for product %s: %s", record["id"], exc)
            if results is not None:
                results["failed"] += 1
                results["errors"].append("Variations fetch %s: %s" % (record["id"], exc))
            return

        wc_product_model = self.env["wc.product.link"]
        parent_name = record.get("name") or ""

        for var in var_records:
            var_ext_id = str(var.get("id", ""))
            if not var_ext_id:
                continue

            if not var.get("name"):
                attr_parts = [
                    a.get("option", "")
                    for a in var.get("attributes", [])
                    if a.get("option")
                ]
                var["name"] = parent_name
                if attr_parts:
                    var["name"] += " - " + ", ".join(attr_parts)

            if not var.get("categories"):
                var["categories"] = record.get("categories", [])
            if not var.get("tags"):
                var["tags"] = record.get("tags", [])

            try:
                var_binding, status = wc_product_model._sync_one(backend, var, force)
                if results is not None:
                    results[status] += 1
                if var_binding:
                    var_binding.with_context(syncing_from_wc=True).write({
                        "is_variation": True,
                        "wc_template_id": tmpl_binding.id,
                    })
            except Exception as exc:
                _logger.exception("Failed syncing variation %s: %s", var_ext_id, exc)
                if results is not None:
                    results["failed"] += 1
                    results["errors"].append("Variation %s: %s" % (var_ext_id, exc))

    def pull_from_store(self):
        def _op(binding):
            client = binding.backend_id.get_api_client()
            result = client.get("products/%s" % binding.external_id)
            data = result.get("data", {})
            if data:
                self.syncing_from_wc(binding.backend_id, [data], force=True)
                binding.mark_synced("Template pulled from WooCommerce.")

        return self.filtered("external_id")._run_with_notification(_op, title="Pull Complete")

    def push_to_store(self):
        from ..components.exporter import WooVariableProductExporter
        exporter = WooVariableProductExporter()

        def _op(binding):
            exporter.run(binding.backend_id, binding)
            binding.mark_synced("Variable product pushed to WooCommerce.")

        return self._run_with_notification(_op, title="Push Complete")

class ProductTemplateWoo(models.Model):
    _inherit = "product.template"

    wc_bind_ids = fields.One2many(
        comodel_name="wc.template.link",
        inverse_name="template_id",
        string="WooCommerce Bindings",
        copy=False,
    )

    def action_push_product_to_store(self):
        backends = self.env["wc.store"].search([("active", "=", True)])
        if not backends:
            raise UserError("No active WooCommerce stores found.")

        for template in self:
            if template.wc_bind_ids:
                template.wc_bind_ids.push_to_store()
            else:
                for product in template.product_variant_ids:
                    product.action_push_product_to_store()
