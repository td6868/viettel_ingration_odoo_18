import json
import logging
import requests
from datetime import datetime, timedelta

from urllib3 import response
from odoo import api, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# API Endpoints
API_ENDPOINTS = {
    'test': 'https://partnerdev.viettelpost.vn/v2',
    'production': 'https://partner.viettelpost.vn/v2/'
}

class VTPService(models.AbstractModel):
    _name = 'vtp.service'
    _description = 'ViettelPost API Service'

    @api.model
    def _get_api_url(self):
        """Lấy URL API dựa trên môi trường cấu hình"""
        env = self.env['ir.config_parameter'].sudo().get_param('viettelpost.environment', 'test')
        return API_ENDPOINTS.get(env, API_ENDPOINTS['test'])

    @api.model
    def _get_token(self):
        """Lấy token hiện tại hoặc tạo mới nếu hết hạn"""
        token = self.env['ir.config_parameter'].sudo().get_param('viettelpost.token')
        expiry_str = self.env['ir.config_parameter'].sudo().get_param('viettelpost.token_expiry')
        
        if token and expiry_str:
            if int(expiry_str) > int(datetime.now().timestamp()):
                return token
        
        # Token hết hạn hoặc không tồn tại, lấy token mới
        return self.get_token().get('token')

    @api.model
    def get_token(self):
        """Lấy token từ API ViettelPost"""
        username = self.env['ir.config_parameter'].sudo().get_param('viettelpost.username')
        password = self.env['ir.config_parameter'].sudo().get_param('viettelpost.password')
        
        if not username or not password:
            raise UserError(_('Vui lòng cấu hình tài khoản ViettelPost!'))
        
        url = f"{self._get_api_url()}/user/Login"
        headers = {
            'Content-Type': 'application/json'
        }
        data = {
            'USERNAME': username,
            'PASSWORD': password
        }
        
        try:
            response = requests.post(url, headers=headers, data=json.dumps(data))
            response.raise_for_status()
            result = response.json()
            
            if result.get('status') == 200 and result.get('data', {}).get('token'):
                token = result['data']['token']
                # Lưu token với thời hạn 24 giờ
                expiry = result['data']['expired']
                self.env['ir.config_parameter'].sudo().set_param('viettelpost.token', token)
                self.env['ir.config_parameter'].sudo().set_param('viettelpost.token_expiry', expiry)
                return {'token': token, 'expiry': expiry}
            else:
                _logger.error("ViettelPost API Error: %s", result.get('message', 'Unknown error'))
                return False
        except Exception as e:
            _logger.error("ViettelPost API Exception: %s", str(e))
            return False
    
    @api.model 
    def _get_link_print_bill(self, endpoint, method='POST', data=None):
        """Lấy link in phiếu ViettelPost"""
        token = self._get_token()
        if not token:
            raise UserError(_('Không thể lấy token. Vui lòng kiểm tra thông tin đăng nhập!'))

        url = f"{self._get_api_url()}/{endpoint}"
        headers = {
            'accept': '*/*',
            'Content-Type': 'application/json',
            'Token': token,
            'Cookie': 'SERVERID=2'
        }

        try:
            # Gửi đúng kiểu POST + json body
            response = requests.post(url, headers=headers, json=data)
            response.raise_for_status()

            result = response.json()
            _logger.info(">>> VTP Response: %s", result)

            # Trường hợp API trả về list chứa dict
            if isinstance(result, list) and len(result) > 0:
                res = result[0]
                if res.get('status') == 200 and not res.get('error'):
                    return res.get('message')

            # Trường hợp API trả về dict thông thường
            if isinstance(result, dict) and result.get('status') == 200:
                return result.get('message')

            _logger.error("ViettelPost API Error: %s", result)
            return False

        except Exception as e:
            _logger.error("ViettelPost API Exception: %s", str(e))
            return False



    @api.model
    def _make_api_call(self, endpoint, method='GET', data=None):
        """Thực hiện gọi API với token"""
        token = self._get_token()
        if not token:
            raise UserError(_('Không thể lấy token. Vui lòng kiểm tra thông tin đăng nhập!'))
        
        url = f"{self._get_api_url()}/{endpoint}"
        headers = {
            'Content-Type': 'application/json',
            'Token': token
        }
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers, params=data)
            elif method == 'POST':
                response = requests.post(url, headers=headers, data=json.dumps(data))
            else:
                raise UserError(_('Phương thức không được hỗ trợ!'))
            
            response.raise_for_status()
            result = response.json()
            
            if result.get('status') == 200:
                return result.get('data')
            else:
                error = f"ViettelPost API Error: {result.get('message', 'Unknown error')}"
                _logger.error(result)
                return {'error': error}
        except Exception as e:
            error = f"ViettelPost API Exception: {str(e)}"
            _logger.error(error)
            return {'error': error}    

    @api.model
    def fetch_stores(self):
        """Lấy danh sách store từ API (raw data)"""
        stores = self._make_api_call('user/listInventory', method='GET')
        if not stores:
            return []
        return stores

    @api.model
    def calculate_fee(self, data):
        """Tính phí vận chuyển"""
        return self._make_api_call('order/getPrice', method='POST', data=data)

    @api.model
    def create_bill(self, data):
        """Tạo vận đơn"""
        return self._make_api_call('order/createOrder', method='POST', data=data)

    @api.model
    def update_bill(self, data):
        """Cập nhật thông tin đơn hàng"""
        return self._make_api_call('order/edit', method='POST', data=data)

    @api.model
    def get_bill_status(self, order_number):
        """Lấy trạng thái vận đơn từ lịch sử"""
        BillHistory = self.env['vtp.order.bill.history']
        latest_history = BillHistory.search([
            ('order_number', '=', order_number)
        ], order='create_date desc', limit=1)
        
        if latest_history:
            return {
                'status': latest_history.status,
                'ORDER_STATUSDATE': latest_history.status_date,
                'ORDER_STATUS': latest_history.status_code,
                'STATUS_NAME': latest_history.status_name,
            }
        return False

    @api.model
    def update_bill_status(self, data):
        """Cập nhật trạng thái vận đơn"""

        return self._make_api_call('order/UpdateOrder', method='POST', data=data)

    @api.model
    def link_print_bill(self, data):
        """Lấy link in phiếu Viettelpost"""
        # API trả về 'message' chứa code, vì vậy dùng hàm chuyên biệt để trích xuất 'message'
        return self._get_link_print_bill('order/printing-code', method='POST', data=data)

        
        