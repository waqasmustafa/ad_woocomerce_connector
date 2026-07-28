import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

class WooWebhookController(http.Controller):

    def _get_backend(self, token: str):
        return request.env["wc.store"].sudo().search(
            [("webhook_token", "=", token), ("active", "=", True)], limit=1
        )

    def _parse_payload(self):
        try:
            return json.loads(request.httprequest.data or "{}")
        except (ValueError, TypeError):
            return {}

    @http.route(
        "/woocommerce/webhook/order_created/<string:token>",
        type="http",
        auth="public",
        methods=["GET", "POST"],
        csrf=False,
    )
    def on_order_created(self, token, **kwargs):
        backend = self._get_backend(token)
        if not backend:
            return request.make_response("Unauthorized", status=401)
        payload = self._parse_payload()
        print(payload, "payload 34\n")
        if payload:
            try:
                request.env["wc.order"].sudo().syncing_from_wc(
                    backend, [payload], force=False
                )
            except Exception as exc:
                _logger.exception("Webhook order_created error: %s", exc)
        return request.make_response("OK", status=200)

    @http.route(
        "/woocommerce/webhook/order_updated/<string:token>",
        type="http",
        auth="public",
        methods=["GET", "POST"],
        csrf=False,
    )
    def on_order_updated(self, token, **kwargs):
        backend = self._get_backend(token)
        if not backend:
            return request.make_response("Unauthorized", status=401)
        payload = self._parse_payload()
        print(payload, "payload 55\n")
        if payload:
            try:
                request.env["wc.order"].sudo().syncing_from_wc(
                    backend, [payload], force=True
                )
            except Exception as exc:
                _logger.exception("Webhook order_updated error: %s", exc)
        return request.make_response("OK", status=200)

    @http.route(
        "/woocommerce/webhook/product_created/<string:token>",
        type="http",
        auth="public",
        methods=["GET", "POST"],
        csrf=False,
    )
    def on_product_created(self, token, **kwargs):
        backend = self._get_backend(token)
        if not backend:
            return request.make_response("Unauthorized", status=401)
        payload = self._parse_payload()
        print(payload, "payload 78\n")
        if payload:
            try:
                ptype = payload.get("type", "simple")
                if ptype == "variable":
                    request.env["wc.template.link"].sudo().syncing_from_wc(
                        backend, [payload], force=False
                    )
                else:
                    request.env["wc.product.link"].sudo().syncing_from_wc(
                        backend, [payload], force=False
                    )
            except Exception as exc:
                _logger.exception("Webhook product_created error: %s", exc)
        return request.make_response("OK", status=200)

    @http.route(
        "/woocommerce/webhook/product_updated/<string:token>",
        type="http",
        auth="public",
        methods=["GET", "POST"],
        csrf=False,
    )
    def on_product_updated(self, token, **kwargs):
        backend = self._get_backend(token)
        if not backend:
            return request.make_response("Unauthorized", status=401)
        payload = self._parse_payload()
        print(payload, "payload 105\n")
        if payload:
            try:
                ptype = payload.get("type", "simple")
                if ptype == "variable":
                    request.env["wc.template.link"].sudo().syncing_from_wc(
                        backend, [payload], force=True
                    )
                else:
                    request.env["wc.product.link"].sudo().syncing_from_wc(
                        backend, [payload], force=True
                    )
            except Exception as exc:
                _logger.exception("Webhook product_updated error: %s", exc)
        return request.make_response("OK", status=200)

    @http.route(
        "/woocommerce/webhook/customer_created/<string:token>",
        type="http",
        auth="public",
        methods=["GET", "POST"],
        csrf=False,
    )
    def on_customer_created(self, token, **kwargs):
        backend = self._get_backend(token)
        if not backend:
            return request.make_response("Unauthorized", status=401)
        payload = self._parse_payload()
        print(payload, "payload 134\n")
        if payload:
            try:
                request.env["wc.customer.link"].sudo().syncing_from_wc(
                    backend, [payload], force=False
                )
            except Exception as exc:
                _logger.exception("Webhook customer_created error: %s", exc)
        return request.make_response("OK", status=200)

    @http.route(
        "/woocommerce/webhook/customer_updated/<string:token>",
        type="http",
        auth="public",
        methods=["GET", "POST"],
        csrf=False,
    )
    def on_customer_updated(self, token, **kwargs):
        backend = self._get_backend(token)
        if not backend:
            return request.make_response("Unauthorized", status=401)
        payload = self._parse_payload()
        print(payload, "payload 156\n")
        if payload:
            try:
                request.env["wc.customer.link"].sudo().syncing_from_wc(
                    backend, [payload], force=True
                )
            except Exception as exc:
                _logger.exception("Webhook customer_updated error: %s", exc)
        return request.make_response("OK", status=200)
