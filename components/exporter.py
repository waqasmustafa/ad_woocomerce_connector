import logging

_logger = logging.getLogger(__name__)

class WooExportError(Exception):
    pass

class WooRecordExporter:

    def get_endpoint(self, binding) -> str:
        raise NotImplementedError

    def get_create_endpoint(self) -> str:
        raise NotImplementedError

    def get_payload(self, binding) -> dict:
        raise NotImplementedError

    def after_export(self, binding, response_data: dict):
        pass

    def run(self, backend, binding):
        client = backend.get_api_client()
        payload = self.get_payload(binding)

        if not payload:
            _logger.info("Nothing to export for binding %s", binding)
            return

        try:
            if binding.external_id:
                endpoint = self.get_endpoint(binding)
                result = client.put(endpoint, payload)
                _logger.info("Updated WooCommerce record at %s", endpoint)
            else:
                endpoint = self.get_create_endpoint()
                result = client.post(endpoint, payload)
                new_ext_id = str(result.get("data", {}).get("id", ""))
                if new_ext_id:
                    binding.with_context(syncing_from_wc=True).write({"external_id": new_ext_id})
                _logger.info("Created WooCommerce record %s at %s", new_ext_id, endpoint)

            self.after_export(binding, result.get("data", {}))
            return result

        except Exception as exc:
            _logger.exception("WooCommerce export failed for binding %s: %s", binding, exc)
            raise WooExportError(str(exc)) from exc

class WooOrderStatusExporter(WooRecordExporter):

    def get_endpoint(self, binding) -> str:
        return "orders/%s" % binding.external_id

    def get_create_endpoint(self) -> str:
        return "orders"

    def get_payload(self, binding) -> dict:
        status = binding.wc_fulfillment_status
        if not status:
            if binding.order_id.state == "cancel":
                status = "cancelled"
            elif binding.order_id.all_deliveries_done:
                status = "completed"
            elif binding.wc_status_id:
                status = binding.wc_status_id.code
            else:
                if binding.order_id.state in ("sale", "done"):
                    status = "processing"
                else:
                    status = "pending"
        payload = {"status": status}
        if binding.backend_id.push_tracking_info:
            tracking = getattr(binding, "carrier_tracking_ref", False)
            if not tracking and binding.order_id.picking_ids:
                pickings = binding.order_id.picking_ids.filtered(
                    lambda p: p.picking_type_code == "outgoing" and p.state == "done"
                )
                if pickings:
                    refs = [p.carrier_tracking_ref for p in pickings if p.carrier_tracking_ref]
                    if refs:
                        tracking = ", ".join(refs)
            if tracking:
                payload["meta_data"] = [
                    {"key": "_tracking_number", "value": tracking},
                ]
        return payload

    def after_export(self, binding, response_data: dict):
        if response_data and response_data.get("status"):
            code = response_data["status"]
            stage = binding.env["wc.order.stage"].search([("code", "=", code)], limit=1)
            if stage:
                binding.with_context(syncing_from_wc=True).write({
                    "wc_status_id": stage.id,
                    "wc_fulfillment_status": False,
                })

class WooStockExporter(WooRecordExporter):

    def get_endpoint(self, binding) -> str:
        return "products/%s" % binding.external_id

    def get_create_endpoint(self) -> str:
        return "products"

    def get_payload(self, binding) -> dict:
        return {
            "stock_quantity": int(binding.wc_stock_qty),
            "manage_stock": True,
        }

class WooProductExporter(WooRecordExporter):

    def get_endpoint(self, binding) -> str:
        return "products/%s" % binding.external_id

    def get_create_endpoint(self) -> str:
        return "products"

    def get_payload(self, binding) -> dict:
        product = binding.product_id
        payload = {
            "name": binding.wc_product_name or product.name,
            "type": "simple",
            "status": binding.wc_status or "publish",
            "regular_price": str(
                binding.wc_regular_price if binding.wc_regular_price
                else product.list_price
            ),
            "manage_stock": bool(binding.wc_manage_stock),
            "description": product.description_sale or "",
        }

        sku = binding.wc_sku or product.default_code
        if sku:
            payload["sku"] = sku

        if binding.wc_manage_stock:
            payload["stock_quantity"] = int(binding.wc_stock_qty or 0)

        weight = binding.wc_weight or (str(product.weight) if product.weight else "")
        if weight and str(weight) not in ("0", "0.0", ""):
            payload["weight"] = str(weight)

        if binding.wc_sale_price:
            payload["sale_price"] = str(binding.wc_sale_price)

        if binding.wc_category_ids:
            payload["categories"] = [
                {"id": int(cat.external_id)}
                for cat in binding.wc_category_ids
                if cat.external_id
            ]

        if binding.wc_tag_ids:
            payload["tags"] = [
                {"id": int(tag.external_id)}
                for tag in binding.wc_tag_ids
                if tag.external_id
            ]

        return payload

    def after_export(self, binding, response_data: dict):
        if response_data:
            vals = {}
            if response_data.get("sku"):
                vals["wc_sku"] = response_data["sku"]
            if response_data.get("status"):
                vals["wc_status"] = response_data["status"]
            if vals:
                binding.with_context(syncing_from_wc=True).write(vals)

class WooVariableProductExporter(WooRecordExporter):

    def get_endpoint(self, binding) -> str:
        return "products/%s" % binding.external_id

    def get_create_endpoint(self) -> str:
        return "products"

    def get_payload(self, binding) -> dict:
        template = binding.template_id
        payload = {
            "name": binding.wc_product_name or template.name,
            "type": "variable",
            "status": binding.wc_status or "publish",
            "description": template.description_sale or "",
        }

        if binding.wc_sku or template.default_code:
            payload["sku"] = binding.wc_sku or template.default_code or ""

        if binding.wc_category_ids:
            payload["categories"] = [
                {"id": int(cat.external_id)}
                for cat in binding.wc_category_ids
                if cat.external_id
            ]
        if binding.wc_tag_ids:
            payload["tags"] = [
                {"id": int(tag.external_id)}
                for tag in binding.wc_tag_ids
                if tag.external_id
            ]
        return payload

class WooCustomerExporter(WooRecordExporter):

    def get_endpoint(self, binding) -> str:
        return "customers/%s" % binding.external_id

    def get_create_endpoint(self) -> str:
        return "customers"

    def get_payload(self, binding) -> dict:
        partner = binding.partner_id
        names = (partner.name or "").split(" ", 1)
        first_name = names[0]
        last_name = names[1] if len(names) > 1 else ""

        payload = {
            "first_name": first_name,
            "last_name": last_name,
            "email": partner.email or "",
        }

        billing = {
            "first_name": first_name,
            "last_name": last_name,
            "address_1": partner.street or "",
            "address_2": partner.street2 or "",
            "city": partner.city or "",
            "state": partner.state_id.code if partner.state_id else "",
            "postcode": partner.zip or "",
            "country": partner.country_id.code if partner.country_id else "",
            "email": partner.email or "",
            "phone": partner.phone or partner.mobile or "",
        }
        payload["billing"] = billing

        ship_partner = partner.child_ids.filtered(lambda c: c.type == "delivery")[:1]
        if ship_partner:
            ship_names = (ship_partner.name or "").split(" ", 1)
            payload["shipping"] = {
                "first_name": ship_names[0],
                "last_name": ship_names[1] if len(ship_names) > 1 else "",
                "address_1": ship_partner.street or "",
                "address_2": ship_partner.street2 or "",
                "city": ship_partner.city or "",
                "state": ship_partner.state_id.code if ship_partner.state_id else "",
                "postcode": ship_partner.zip or "",
                "country": ship_partner.country_id.code if ship_partner.country_id else "",
            }
        else:
            payload["shipping"] = billing.copy()
            payload["shipping"].pop("email", None)
            payload["shipping"].pop("phone", None)

        return payload

class WooCategoryExporter(WooRecordExporter):

    def get_endpoint(self, binding) -> str:
        return "products/categories/%s" % binding.external_id

    def get_create_endpoint(self) -> str:
        return "products/categories"

    def get_payload(self, binding) -> dict:
        payload = {
            "name": binding.name,
            "description": binding.wc_description or "",
            "slug": binding.wc_slug or "",
        }
        if binding.wc_parent_id and binding.wc_parent_id.external_id:
            payload["parent"] = int(binding.wc_parent_id.external_id)
        elif binding.category_id.parent_id:
            parent_binding = binding.env["wc.category.link"].search([
                ("category_id", "=", binding.category_id.parent_id.id),
                ("backend_id", "=", binding.backend_id.id),
                ("external_id", "!=", False),
            ], limit=1)
            if parent_binding:
                payload["parent"] = int(parent_binding.external_id)
        return payload

class WooTagExporter(WooRecordExporter):

    def get_endpoint(self, binding) -> str:
        return "products/tags/%s" % binding.external_id

    def get_create_endpoint(self) -> str:
        return "products/tags"

    def get_payload(self, binding) -> dict:
        return {
            "name": binding.name,
            "description": binding.description or "",
            "slug": binding.slug or "",
        }

class WooAttributeExporter(WooRecordExporter):

    def get_endpoint(self, binding) -> str:
        return "products/attributes/%s" % binding.external_id

    def get_create_endpoint(self) -> str:
        return "products/attributes"

    def get_payload(self, binding) -> dict:
        return {
            "name": binding.name,
            "type": binding.wc_type or "select",
            "order_by": binding.wc_order_by or "menu_order",
            "has_archives": bool(binding.wc_has_archives),
        }
