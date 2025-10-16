from odoo import http, fields
import logging
from odoo.http import request
import json
from odoo.http import Response

_logger = logging.getLogger(__name__)


class VTPWebhookController(http.Controller):

    @http.route('/vtp/webhook/order_status', type='json', auth='public', methods=['POST'], csrf=False)
    def vtp_order_status(self, **post):
        
        try:
            payload = json.loads(request.httprequest.data)['body']
        except:
            payload = json.loads(request.httprequest.data)

        print("Dữ liệu nhận được: ", payload)

        try:
            # Đảm bảo payload là dictionary
            if not isinstance(payload, dict):
                payload = json.loads(payload) if isinstance(payload, str) else payload
            
            request.env['vtp.order.bill'].sudo().create_update_bill_from_webhook(payload)
            return Response("Webhook received successfully", status=200, content_type='text/plain')
        except Exception as e:
            _logger.error(f"Error processing webhook: {e}")
            return Response(f"Error processing webhook: {e}", status=500, content_type='text/plain')
