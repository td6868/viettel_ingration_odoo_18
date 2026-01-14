from odoo import http, fields
import logging
from odoo.http import request
import json
from odoo.http import Response

_logger = logging.getLogger(__name__)


class VTPWebhookController(http.Controller):

    @http.route('/vtp/webhook/order_status', type='http', auth='public', methods=['POST'], csrf=False)
    def vtp_order_status(self):
        """
        Handle ViettelPost webhook for order status updates.
        Supports both single object and list of objects (n8n format).
        """
        try:
            raw_data = request.httprequest.data
            if not raw_data:
                _logger.warning("VTP Webhook: No data received")
                return Response("No data", status=400)

            # Parse JSON
            try:
                raw_payload = json.loads(raw_data)
            except Exception as e:
                _logger.error(f"VTP Webhook: Failed to parse JSON: {e}")
                return Response("Invalid JSON", status=400)

            _logger.debug(f"VTP Webhook raw data: {raw_data}")

            # Handle list vs dictionary
            items = raw_payload if isinstance(raw_payload, list) else [raw_payload]

            count = 0
            for item in items:
                # Tìm dữ liệu DATA trong item
                data_dict = False
                token = False
                
                if isinstance(item, dict):
                    # Check for nested structure from n8n-like proxies
                    if 'body' in item and isinstance(item['body'], dict):
                        data_dict = item['body'].get('DATA')
                        token = item['body'].get('TOKEN')
                    # Standard VTP direct structure
                    elif 'DATA' in item:
                        data_dict = item.get('DATA')
                        token = item.get('TOKEN')
                    # Fallback if the whole object is the data
                    else:
                        data_dict = item

                # Check for TOKEN (Optional security)
                # You can compare this token with a value in ir.config_parameter if needed
                # For now, we just log it
                if token:
                    _logger.info(f"VTP Webhook received with token: {token}")

                # Process the data
                if data_dict and isinstance(data_dict, dict) and data_dict.get('ORDER_NUMBER'):
                    _logger.info("VTP Webhook processing Order: %s (Status: %s)", 
                                 data_dict.get('ORDER_NUMBER'), data_dict.get('STATUS_NAME'))
                    
                    # Call model method
                    # Note: create_update_bill_from_webhook already calls create_bill_history_from_webhook internally
                    request.env['vtp.order.bill'].sudo().create_update_bill_from_webhook(data_dict)
                    
                    count += 1
                else:
                    _logger.warning(f"VTP Webhook: Item structure not recognized or missing ORDER_NUMBER: {item}")

            return Response(f"Processed {count} items", status=200)

        except Exception as e:
            _logger.exception(f"VTP Webhook: Unexpected error: {e}")
            return Response(str(e), status=500)
