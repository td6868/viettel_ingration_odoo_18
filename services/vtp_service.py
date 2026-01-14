# -*- coding: utf-8 -*-
"""
VTP Service - Pure & Stateless API Service

This service is completely stateless and does NOT:
- Read from global config (ir.config_parameter) for credentials
- Write to global config for tokens
- Have any side effects besides API calls and audit logging

All methods require an `account` parameter to ensure multi-account isolation.
"""

import json
import logging
import requests
import time
from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# API Endpoints
API_ENDPOINTS = {
    'test': 'https://partnerdev.viettelpost.vn/v2',
    'production': 'https://partner.viettelpost.vn/v2'
}

# Retry Configuration
DEFAULT_RETRY_CONFIG = {
    'max_retries': 3,
    'backoff_factor': 2,  # Exponential backoff: 1s, 2s, 4s
    'retry_on_status': [408, 500, 502, 503, 504],  # Timeout + Server errors
    'timeout': 30,  # Request timeout in seconds
}


class VTPService(models.AbstractModel):
    """
    ViettelPost API Service - Stateless & Pure
    
    All API methods require an `account` parameter (vtp.account recordset).
    This ensures complete isolation between accounts and enables:
    - Multi-account support
    - Concurrent operations without race conditions
    - Full auditability (track which account made which call)
    - Easy testing (mock account can be injected)
    """
    
    _name = 'vtp.service'
    _description = 'ViettelPost API Service (Pure & Stateless)'

    # ============ Configuration ============

    @api.model
    def _get_api_url(self):
        """Lấy URL API dựa trên cấu hình môi trường"""
        env = self.env['ir.config_parameter'].sudo().get_param(
            'viettel_ingration_odoo_18.environment', 'production'
        )
        base_url = API_ENDPOINTS.get(env, API_ENDPOINTS['production'])
        return base_url.rstrip('/')

    @api.model
    def _get_retry_config(self):
        """Lấy cấu hình retry - có thể được ghi đè trong config"""
        return DEFAULT_RETRY_CONFIG.copy()

    # ============ Token Management (Pure Functions) ============

    @api.model
    def get_token(self, account):
        """
        Lấy token mới từ API ViettelPost.
        
        Đây là một HÀM TÍP HỌC - nó không thay đổi bất kỳ trạng thái nào.
        Người gọi (vtp.account) chịu trách nhiệm lưu trữ token.
        
        Args:
            account: vtp.account recordset (required)
        
        Returns:
            dict: {'token': str, 'expiry': int, 'userId': int, 'phone': str}
            or False if failed
        """
        if not account:
            raise UserError(_('Cần có tài khoản để nhận mã thông báo'))
        
        account.ensure_one()
        
        if not account.username or not account.password:
            raise UserError(_('Tài khoản và mật khẩu là bắt buộc'))
        
        url = f"{self._get_api_url()}/user/Login"
        headers = {'Content-Type': 'application/json'}
        data = {
            'USERNAME': account.username,
            'PASSWORD': account.password,
        }
        
        start_time = time.time()
        
        try:
            response = requests.post(
                url, 
                headers=headers, 
                json=data, 
                timeout=DEFAULT_RETRY_CONFIG['timeout']
            )
            duration_ms = int((time.time() - start_time) * 1000)
            response.raise_for_status()
            result = response.json()
            
            if result.get('status') == 200 and result.get('data', {}).get('token'):
                short_token = result['data']['token']
                expiry = result['data'].get('expired')
                user_id = result['data'].get('userId')
                phone = result['data'].get('phone')
                
                # Tạo nhật ký login
                self._create_audit_log(
                    account=account,
                    endpoint='user/Login',
                    method='POST',
                    request_data={'USERNAME': account.username, 'PASSWORD': '***'},
                    response_data={'status': 200, 'message': 'Login successful'},
                    success=True,
                    duration_ms=duration_ms,
                    token=short_token
                )
                
                # Bước 2: Lấy token dài hạn
                long_token_data = self.get_owner_token(account, short_token)
                
                if long_token_data and long_token_data.get('token'):
                    token = long_token_data['token']
                    # Handle expiry from owner token
                    if long_token_data.get('expiry') is not None:
                        if long_token_data.get('expiry') == 0:
                            # Expiry = 0 means long-term, set to 1 year
                            expiry = int((datetime.now() + timedelta(days=365)).timestamp())
                        else:
                            expiry = long_token_data.get('expiry')
                else:
                    # Fall back to short token
                    token = short_token
                    _logger.warning(f"Không thể lấy token dài hạn cho tài khoản {account.id}, sử dụng token ngắn hạn")
                
                return {
                    'token': token,
                    'expiry': expiry,
                    'userId': user_id,
                    'phone': phone,
                }
            else:
                error_msg = result.get('message', 'Unknown error')
                _logger.error(f"Lỗi VTP Login Error for account {account.id}: {error_msg}")
                
                self._create_audit_log(
                    account=account,
                    endpoint='user/Login',
                    method='POST',
                    request_data={'USERNAME': account.username},
                    success=False,
                    error_message=error_msg,
                    duration_ms=duration_ms
                )
                return False
                
        except requests.exceptions.Timeout:
            error_msg = 'Login request timeout'
            _logger.error(f"VTP Login Timeout for account {account.id}")
            self._create_audit_log(
                account=account,
                endpoint='user/Login',
                method='POST',
                success=False,
                error_message=error_msg
            )
            return False
            
        except requests.exceptions.RequestException as e:
            error_msg = f'Đăng nhập thất bại: {str(e)}'
            _logger.error(f"Lỗi đăng nhập VTP cho tài khoản {account.id}: {e}")
            self._create_audit_log(
                account=account,
                endpoint='user/Login',
                method='POST',
                success=False,
                error_message=error_msg
            )
            return False
            
        except Exception as e:
            error_msg = f'Đăng nhập thất bại: {str(e)}'
            _logger.exception(f"Lỗi đăng nhập VTP cho tài khoản {account.id}")
            self._create_audit_log(
                account=account,
                endpoint='user/Login',
                method='POST',
                success=False,
                error_message=error_msg
            )
            return False

    @api.model
    def get_owner_token(self, account, short_token):
        """
        Lấy token dài hạn từ /user/ownerconnect.
        
        Args:
            account: vtp.account recordset
            short_token: str - Short-term token from login
        
        Returns:
            dict: {'token': str, 'expiry': int} or False
        """
        if not account or not short_token:
            return False
        
        url = f"{self._get_api_url()}/user/ownerconnect"
        headers = {
            'Content-Type': 'application/json',
            'Token': short_token
        }
        data = {
            'USERNAME': account.username,
            'PASSWORD': account.password,
        }
        
        start_time = time.time()
        
        try:
            _logger.info(f"VTP: Getting long-term token for account {account.id}")
            response = requests.post(
                url, 
                headers=headers, 
                json=data, 
                timeout=DEFAULT_RETRY_CONFIG['timeout']
            )
            duration_ms = int((time.time() - start_time) * 1000)
            response.raise_for_status()
            result = response.json()
            
            if result.get('status') == 200 and result.get('data', {}).get('token'):
                self._create_audit_log(
                    account=account,
                    endpoint='user/ownerconnect',
                    method='POST',
                    success=True,
                    duration_ms=duration_ms,
                    token=result['data']['token']
                )
                
                return {
                    'token': result['data']['token'],
                    'expiry': result['data'].get('expired')
                }
            else:
                error_msg = result.get('message', 'Unknown error')
                _logger.error(f"Lỗi token dài hạn cho tài khoản {account.id}: {error_msg}")
                self._create_audit_log(
                    account=account,
                    endpoint='user/ownerconnect',
                    method='POST',
                    success=False,
                    error_message=error_msg,
                    duration_ms=duration_ms
                )
                return False
                
        except Exception as e:
            _logger.error(f"Lỗi token dài hạn cho tài khoản {account.id}: {e}")
            self._create_audit_log(
                account=account,
                endpoint='user/ownerconnect',
                method='POST',
                success=False,
                error_message=str(e)
            )
            return False

    # ============ Core API Call with Retry ============

    @api.model
    def _make_api_call(self, account, endpoint, method='POST', data=None, order_bill=None):
        """
        Gọi API với logic retry và nhật ký.
        
        Đây là phương thức core được sử dụng trong tất cả các phương thức gọi API.
        
        Args:
            account: vtp.account recordset (REQUIRED)
            endpoint: str - API endpoint (e.g., 'order/createOrder')
            method: str - HTTP method ('GET' or 'POST')
            data: dict - Request payload
            order_bill: vtp.order.bill recordset (optional, for audit)
        
        Returns:
            dict/list: API response data
            or {'error': str} if failed
        """
        if not account:
            raise UserError(_('Cần có tài khoản để thực hiện các cuộc gọi API'))
        
        account.ensure_one()
        retry_config = self._get_retry_config()
        last_error = None
        
        for attempt in range(retry_config['max_retries']):
            try:
                # Get valid token from account
                token = account.get_valid_token()
                if not token:
                    error = _('Không thể lấy Token cho tài khoản %s') % account.name
                    self._create_audit_log(
                        account=account,
                        endpoint=endpoint,
                        method=method,
                        request_data=data,
                        success=False,
                        error_message=error,
                        order_bill=order_bill
                    )
                    return {'error': error}
                
                # Prepare request
                url = f"{self._get_api_url()}/{endpoint}"
                headers = {
                    'Content-Type': 'application/json',
                    'Token': token
                }
                
                # Make request
                start_time = time.time()
                
                if method == 'GET':
                    response = requests.get(
                        url, 
                        headers=headers, 
                        params=data, 
                        timeout=retry_config['timeout']
                    )
                elif method == 'POST':
                    response = requests.post(
                        url, 
                        headers=headers, 
                        json=data, 
                        timeout=retry_config['timeout']
                    )
                else:
                    raise UserError(_('Hệ thống không hỗ trợ phương thức HTTP: %s') % method)
                
                duration_ms = int((time.time() - start_time) * 1000)
                
                # Kiểm tra các mã trạng thái có thể retry
                if response.status_code in retry_config['retry_on_status']:
                    if attempt < retry_config['max_retries'] - 1:
                        wait_time = retry_config['backoff_factor'] ** attempt
                        _logger.warning(
                            f"VTP API {endpoint} returned {response.status_code}, "
                            f"retrying in {wait_time}s (attempt {attempt + 1}/{retry_config['max_retries']})"
                        )
                        time.sleep(wait_time)
                        continue
                
                response.raise_for_status()
                result = response.json()
                
                # Log success
                account.log_api_call(endpoint, success=True)
                self._create_audit_log(
                    account=account,
                    endpoint=endpoint,
                    method=method,
                    request_data=data,
                    response_data=result,
                    success=True,
                    http_status=response.status_code,
                    duration_ms=duration_ms,
                    token=token,
                    order_bill=order_bill
                )
                
                # Trả về dữ liệu dựa trên cấu trúc phản hồi
                if isinstance(result, dict):
                    if result.get('status') == 200:
                        return result.get('data', result)
                    else:
                        error = f"API Error: {result.get('message', 'Unknown error')}"
                        return {'error': error}
                elif isinstance(result, list):
                    return result
                else:
                    return result
                
            except requests.exceptions.HTTPError as e:
                status_code = e.response.status_code if e.response is not None else 0
                last_error = f"HTTP Error {status_code}: {str(e)}"
                
                # Retry on specific status codes
                if status_code in retry_config['retry_on_status'] and attempt < retry_config['max_retries'] - 1:
                    wait_time = retry_config['backoff_factor'] ** attempt
                    _logger.warning(
                        f"VTP API {endpoint} failed with {status_code}, "
                        f"retrying in {wait_time}s (attempt {attempt + 1}/{retry_config['max_retries']})"
                    )
                    time.sleep(wait_time)
                    continue
                
                _logger.error(f"VTP API {endpoint} failed: {last_error}")
                
            except requests.exceptions.Timeout:
                last_error = f"Request timeout after {retry_config['timeout']}s"
                
                if attempt < retry_config['max_retries'] - 1:
                    wait_time = retry_config['backoff_factor'] ** attempt
                    _logger.warning(
                        f"VTP API {endpoint} timeout, "
                        f"retrying in {wait_time}s (attempt {attempt + 1}/{retry_config['max_retries']})"
                    )
                    time.sleep(wait_time)
                    continue
                
                _logger.error(f"VTP API {endpoint} failed: {last_error}")
                
            except requests.exceptions.ConnectionError:
                last_error = "Lỗi kết nối - không thể truy cập mạng"
                
                if attempt < retry_config['max_retries'] - 1:
                    wait_time = retry_config['backoff_factor'] ** attempt
                    _logger.warning(
                        f"VTP API {endpoint} connection error, "
                        f"retrying in {wait_time}s (attempt {attempt + 1}/{retry_config['max_retries']})"
                    )
                    time.sleep(wait_time)
                    continue
                
                _logger.error(f"VTP API {endpoint} failed: {last_error}")
                
            except Exception as e:
                last_error = f"Lỗi không mong muốn: {str(e)}"
                _logger.exception(f"VTP API {endpoint} unexpected error")
        
        # All retries exhausted
        account.log_api_call(endpoint, success=False, error=last_error)
        self._create_audit_log(
            account=account,
            endpoint=endpoint,
            method=method,
            request_data=data,
            success=False,
            error_message=last_error,
            order_bill=order_bill
        )
        
        return {'error': last_error or 'Max retries exhausted'}

    # ============ Audit Logging ============

    @api.model
    def _create_audit_log(self, account, endpoint, method='POST', request_data=None,
                          response_data=None, success=True, error_message=None,
                          http_status=None, duration_ms=None, token=None, order_bill=None):
        """
        Create audit log entry safely.
        
        This method never raises exceptions to avoid breaking API calls.
        """
        try:
            AuditLog = self.env['vtp.api.audit']
            AuditLog.create_log(
                account=account,
                endpoint=endpoint,
                method=method,
                request_data=request_data,
                response_data=response_data,
                success=success,
                error_message=error_message,
                http_status=http_status,
                duration_ms=duration_ms,
                token=token,
                order_bill=order_bill
            )
        except Exception as e:
            _logger.error(f"Failed to create audit log: {e}")

    @api.model
    def log_webhook_event(self, account, data, success, message, bill=None):
        """
        Ghi nhật ký sự kiện Webhook đơn lẻ.
        Sử dụng phương thức này để ghi lại các kết quả từ checklist webhook.
        """
        self._create_audit_log(
            account=account,
            endpoint='webhook/order_status',
            method='POST',
            request_data=data,
            success=success,
            error_message=message if not success else None,
            response_data={'status': 'logged', 'message': message} if success else None,
            order_bill=bill
        )

    # ============ Business Methods (All require account) ============

    @api.model
    def fetch_stores(self, account):
        """
        Fetch stores from ViettelPost API.
        
        Args:
            account: vtp.account recordset
        
        Returns:
            list: Store data from API
            or {'error': str} if failed
        """
        result = self._make_api_call(account, 'user/listInventory', method='GET')
        if not result:
            return []
        return result

    @api.model
    def calculate_fee(self, account, data, order_bill=None):
        """
        Calculate shipping fee.
        
        Args:
            account: vtp.account recordset
            data: dict - Fee calculation parameters
            order_bill: vtp.order.bill recordset (optional)
        
        Returns:
            dict: Fee calculation result
        """
        return self._make_api_call(account, 'order/getPrice', method='POST', data=data, order_bill=order_bill)

    @api.model
    def create_bill(self, account, data, order_bill=None):
        """
        Create shipping bill.
        
        Args:
            account: vtp.account recordset
            data: dict - Bill creation data
            order_bill: vtp.order.bill recordset (optional)
        
        Returns:
            dict: Created bill data including ORDER_NUMBER
        """
        result = self._make_api_call(account, 'order/createOrder', method='POST', data=data, order_bill=order_bill)
        
        # Track which token was used for this bill
        if order_bill and (
            (not isinstance(result, dict)) or 
            (isinstance(result, dict) and not result.get('error'))
        ):
            try:
                # Ensure we have a record and the method exists
                if order_bill.exists() and hasattr(order_bill, '_track_token_usage'):
                    order_bill._track_token_usage(account.token)
            except Exception as e:
                _logger.warning(f"Failed to track token usage for account {account.id}: {e}")
        
        return result

    @api.model
    def update_bill(self, account, data, order_bill=None):
        """
        Update shipping bill.
        
        Args:
            account: vtp.account recordset
            data: dict - Bill update data
            order_bill: vtp.order.bill recordset (optional)
        
        Returns:
            dict: Update result
        """
        return self._make_api_call(account, 'order/edit', method='POST', data=data, order_bill=order_bill)

    @api.model
    def update_bill_status(self, account, data, order_bill=None):
        """
        Update bill status.
        
        Args:
            account: vtp.account recordset
            data: dict - Status update data
            order_bill: vtp.order.bill recordset (optional)
        
        Returns:
            dict: Update result
        """
        return self._make_api_call(account, 'order/UpdateOrder', method='POST', data=data, order_bill=order_bill)

    @api.model
    def link_print_bill(self, account, data, order_bill=None):
        """
        Get print link for bill.
        
        This endpoint has special response handling.
        
        Args:
            account: vtp.account recordset
            data: dict - Print request data
            order_bill: vtp.order.bill recordset (optional)
        
        Returns:
            str: Print code/link
            or False if failed
        """
        if not account:
            raise UserError(_('Cần có tài khoản'))
        
        account.ensure_one()
        
        token = account.get_valid_token()
        if not token:
            return False
        
        url = f"{self._get_api_url()}/order/printing-code"
        headers = {
            'accept': '*/*',
            'Content-Type': 'application/json',
            'Token': token,
            'Cookie': 'SERVERID=2'
        }
        
        start_time = time.time()
        
        try:
            response = requests.post(url, headers=headers, json=data, timeout=30)
            duration_ms = int((time.time() - start_time) * 1000)
            response.raise_for_status()
            result = response.json()
            
            _logger.info(f"VTP Print Response: {result}")
            
            # Handle list response
            if isinstance(result, list) and len(result) > 0:
                res = result[0]
                if res.get('status') == 200 and not res.get('error'):
                    self._create_audit_log(
                        account=account,
                        endpoint='order/printing-code',
                        method='POST',
                        request_data=data,
                        success=True,
                        duration_ms=duration_ms,
                        token=token,
                        order_bill=order_bill
                    )
                    return res.get('message')
            
            # Handle dict response
            if isinstance(result, dict) and result.get('status') == 200:
                self._create_audit_log(
                    account=account,
                    endpoint='order/printing-code',
                    method='POST',
                    request_data=data,
                    success=True,
                    duration_ms=duration_ms,
                    token=token,
                    order_bill=order_bill
                )
                return result.get('message')
            
            _logger.error(f"Lỗi in VTP Bill Error: {result}")
            self._create_audit_log(
                account=account,
                endpoint='order/printing-code',
                method='POST',
                request_data=data,
                success=False,
                error_message=str(result),
                duration_ms=duration_ms,
                token=token,
                order_bill=order_bill
            )
            return False
            
        except Exception as e:
            _logger.error(f"VTP Print Bill Exception: {e}")
            self._create_audit_log(
                account=account,
                endpoint='order/printing-code',
                method='POST',
                request_data=data,
                success=False,
                error_message=str(e),
                order_bill=order_bill
            )
            return False

    @api.model
    def get_bill_status(self, order_number):
        """
        Get bill status from local history (no API call).
        
        This method does not require account as it reads from local DB.
        
        Args:
            order_number: str - VTP order number
        
        Returns:
            dict: Status information or False
        """
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