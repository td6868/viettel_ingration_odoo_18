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
        Xử lý webhook ViettelPost để cập nhật trạng thái đơn hàng
        """
        try:
            raw_data = request.httprequest.data
            if not raw_data:
                _logger.warning("VTP Webhook: Không nhận được dữ liệu")
                return Response("Không nhận được dữ liệu", status=400)

            # Parse JSON
            try:
                raw_payload = json.loads(raw_data)
            except Exception as e:
                _logger.error(f"VTP Webhook: JSON không hợp lệ: {e}")
                return Response("JSON không hợp lệ", status=400)

            _logger.debug(f"VTP Webhook raw data: {raw_data}")

            # Xử lý danh sách hoặc 
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
                # Compare with configured webhook token if set
                if token:
                    _logger.info(f"VTP Webhook nhận được token: {token}")

                # Process the data
                if data_dict and isinstance(data_dict, dict) and data_dict.get('ORDER_NUMBER'):
                    order_number = data_dict.get('ORDER_NUMBER')
                    _logger.info("VTP Webhook đang xử lý đơn hàng: %s (Status: %s)", 
                                 order_number, data_dict.get('STATUS_NAME'))
                    
                    # Find the account via order_number to validate token
                    if token:
                        # Find the bill to get the account
                        bill = request.env['vtp.order.bill'].sudo().search([
                            ('order_number', '=', order_number)
                        ], limit=1)
                        
                        if bill and bill.account_id:
                            # Validate token against account's webhook_token
                            if bill.account_id.webhook_token:
                                if token != bill.account_id.webhook_token:
                                    _logger.warning(
                                        f"VTP Webhook: Token không hợp lệ cho tài khoản {bill.account_id.name}, "
                                        f"đơn hàng {order_number}"
                                    )
                                    return Response("Unauthorized - Token không hợp lệ", status=401)
                                else:
                                    _logger.info(f"VTP Webhook: Token hợp lệ cho tài khoản {bill.account_id.name}")
                    
                    # Call model method
                    # Note: create_update_bill_from_webhook already handles audit logging and history
                    result = request.env['vtp.order.bill'].sudo().create_update_bill_from_webhook(data_dict)
                    
                    if result:
                        count += 1
                    else:
                        _logger.warning(f"VTP Webhook: Item for order {order_number} không hợp lệ.")
                else:
                    _logger.warning(f"VTP Webhook: Item structure not recognized or missing ORDER_NUMBER: {item}")

            return Response(f"Processed {count} items", status=200)

        except Exception as e:
            _logger.exception(f"VTP Webhook: Lỗi không mong muốn: {e}")
            return Response(str(e), status=500)
