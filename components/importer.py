import logging
from datetime import datetime

_logger = logging.getLogger(__name__)

class WooImportMapper:

    def get_odoo_vals(self, record: dict, backend) -> dict:
        raise NotImplementedError

    def get_external_id(self, record: dict) -> str:
        return str(record.get("id", ""))

    @staticmethod
    def parse_wc_datetime(dt_str: str):
        if not dt_str:
            return None
        try:
            return datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            try:
                return datetime.fromisoformat(dt_str)
            except ValueError:
                return None

class WooBatchSync:

    def run_batch(self, backend, model_env, mapper: WooImportMapper,
                  endpoint: str, params: dict = None, force: bool = False,
                  binding_field: str = "external_id"):
        client = backend.get_api_client()
        params = params or {}
        params["per_page"] = backend.records_per_page or 100

        total_created = 0
        total_updated = 0
        total_skipped = 0

        for page_records in client.get_all_pages(endpoint, params, per_page=params["per_page"]):
            for record in page_records:
                ext_id = str(mapper.get_external_id(record))
                if not ext_id:
                    _logger.warning("Skipping record with no external ID in %s", endpoint)
                    total_skipped += 1
                    continue

                try:
                    result = self._sync_record(
                        backend, model_env, mapper, record, ext_id, force
                    )
                    if result == "created":
                        total_created += 1
                    elif result == "updated":
                        total_updated += 1
                    else:
                        total_skipped += 1
                except Exception as exc:
                    _logger.exception(
                        "Failed to sync WooCommerce record %s from %s: %s",
                        ext_id, endpoint, exc
                    )
                    total_skipped += 1

        _logger.info(
            "WooCommerce batch sync [%s]: created=%d, updated=%d, skipped=%d",
            endpoint, total_created, total_updated, total_skipped,
        )
        return {"created": total_created, "updated": total_updated, "skipped": total_skipped}

    def _sync_record(self, backend, model_env, mapper: WooImportMapper,
                     record: dict, ext_id: str, force: bool) -> str:
        existing = model_env.search([
            ("backend_id", "=", backend.id),
            ("external_id", "=", ext_id),
        ], limit=1)

        vals = mapper.get_odoo_vals(record, backend)
        vals["external_id"] = ext_id
        vals["backend_id"] = backend.id
        vals["sync_date"] = datetime.now()

        if existing:
            if not force and self._is_up_to_date(existing, record):
                return "skipped"
            existing.with_context(syncing_from_wc=True).write(vals)
            return "updated"
        else:
            model_env.with_context(syncing_from_wc=True).create(vals)
            return "created"

    def _is_up_to_date(self, binding, remote_record: dict) -> bool:
        if not binding.sync_date:
            return False
        remote_modified_str = remote_record.get("date_modified_gmt") or remote_record.get("date_modified")
        if not remote_modified_str:
            return False
        try:
            remote_modified = datetime.strptime(remote_modified_str, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return False
        return binding.sync_date >= remote_modified

batch_sync = WooBatchSync()
