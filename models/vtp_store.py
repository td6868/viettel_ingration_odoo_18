# -*- coding: utf-8 -*-
"""
VTP Account and Store Models - Refactored with:
- Encrypted credentials
- Token management with PostgreSQL advisory locks
- Audit logging
- Multi-account support
"""

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta
import logging
import time
import hashlib

_logger = logging.getLogger(__name__)


class VTPAccount(models.Model):
    _name = 'vtp.account'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'ViettelPost Account'
    _rec_name = 'name'

    # Basic Info
    name = fields.Char(string='Tên tài khoản', required=True)
    userId = fields.Integer(string='User ID', readonly=True)
    phone = fields.Char(string='Số điện thoại', readonly=True)
    
    # Credentials
    username = fields.Char(string='Username', required=True)
    # Password stored encrypted
    password_encrypted = fields.Text(string='Password (Đã mã hóa)', groups='base.group_system')
    password = fields.Char(
        string='Password', 
        compute='_compute_password', 
        inverse='_inverse_password',
        store=False
    )
    client_id = fields.Char(string='Client ID')
    client_secret = fields.Char(string='Client Secret')
    
    # Token Management
    token = fields.Text(string='Token', readonly=True, groups='base.group_system')
    token_expiry = fields.Char(string='Hết hạn token (timestamp)', readonly=True)
    token_expiry_display = fields.Datetime(
        string='Hết hạn token', 
        compute='_compute_token_expiry_display',
        store=False
    )
    token_last_refresh = fields.Datetime(string='Lần refresh cuối', readonly=True)
    token_refresh_count = fields.Integer(string='Số lần refresh', default=0, readonly=True)
    
    # Audit / Status
    active = fields.Boolean(string='Hoạt động', default=False)
    last_api_call = fields.Datetime(string='API call cuối', readonly=True)
    api_call_count = fields.Integer(string='Số lượng API calls', default=0, readonly=True)
    last_error = fields.Text(string='Lỗi gần nhất', readonly=True)
    
    # Relationships
    store_ids = fields.One2many('vtp.store', 'account_id', string='Danh sách Store')
    api_audit_ids = fields.One2many('vtp.api.audit', 'account_id', string='API Audit Logs')
    
    # ============ Password Encryption ============
    
    @api.depends('password_encrypted')
    def _compute_password(self):
        """Decrypt password for use in API calls"""
        for record in self:
            if record.password_encrypted:
                try:
                    record.password = self._decrypt_value(record.password_encrypted)
                except Exception as e:
                    _logger.error(f"Không thể giải mã mật khẩu cho tài khoản {record.id}: {e}")
                    record.password = ''
            else:
                record.password = ''
    
    def _inverse_password(self):
        """Mã hóa mật khẩu khi thiết lập"""
        for record in self:
            if record.password:
                record.password_encrypted = self._encrypt_value(record.password)
            else:
                record.password_encrypted = False
    
    def _get_encryption_key(self):
        """
        Lấy hoặc tạo khóa mã hóa.
        Trong môi trường sản phẩm, khóa này nên được lưu trữ trong biến môi trường hoặc hệ thống quản lý khóa.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        key = ICP.get_param('vtp.encryption_key')
        
        if not key:
            # Generate a simple key based on database UUID for basic security
            # WARNING: In production, use proper key management!
            db_uuid = ICP.get_param('database.uuid', '')
            key = hashlib.sha256(f'vtp_encryption_{db_uuid}'.encode()).hexdigest()[:32]
            ICP.set_param('vtp.encryption_key', key)
            _logger.warning("Đã tạo khóa mã hóa VTP mới. Hãy cân nhắc sử dụng hệ thống quản lý khóa bên ngoài cho môi trường sản xuất.")
        
        return key
    
    def _encrypt_value(self, value):
        """Simple XOR-based encryption. For production, use cryptography library."""
        if not value:
            return False
        
        key = self._get_encryption_key()
        encrypted = []
        for i, char in enumerate(value):
            key_char = key[i % len(key)]
            encrypted.append(chr(ord(char) ^ ord(key_char)))
        
        import base64
        return base64.b64encode(''.join(encrypted).encode('utf-8', errors='replace')).decode()
    
    def _decrypt_value(self, encrypted_value):
        """Decrypt XOR-encrypted value"""
        if not encrypted_value:
            return False
        
        try:
            import base64
            decoded = base64.b64decode(encrypted_value).decode('utf-8', errors='replace')
            
            key = self._get_encryption_key()
            decrypted = []
            for i, char in enumerate(decoded):
                key_char = key[i % len(key)]
                decrypted.append(chr(ord(char) ^ ord(key_char)))
            
            return ''.join(decrypted)
        except Exception as e:
            _logger.error(f"Giải mã thất bại: {e}")
            return False
    
    @api.depends('token_expiry')
    def _compute_token_expiry_display(self):
        """Convert timestamp string to datetime for display"""
        for record in self:
            if record.token_expiry:
                try:
                    # Convert string timestamp to integer, handle both seconds and milliseconds
                    timestamp = int(record.token_expiry)
                    # If timestamp is in milliseconds (> year 2100 in seconds), convert to seconds
                    if timestamp > 4102444800:  # Jan 1, 2100 in seconds
                        timestamp = timestamp // 1000
                    record.token_expiry_display = datetime.fromtimestamp(timestamp)
                except (ValueError, TypeError, OSError) as e:
                    _logger.warning(f"Invalid token_expiry value for account {record.id}: {record.token_expiry}")
                    record.token_expiry_display = False
            else:
                record.token_expiry_display = False
    
    # ============ Token Management with Locking ============
    
    def _get_lock_id(self):
        """Generate consistent lock ID for advisory lock"""
        self.ensure_one()
        # Sử dụng hàm băm để đảm bảo ID nằm trong phạm vi số nguyên của PostgreSQL.
        return hash(f'vtp_token_refresh_{self.id}') % 2147483647
    
    def _acquire_token_lock(self, timeout=5):
        """
        Thử lấy khóa thông báo cho việc refresh token.
        Trả về True nếu khóa được lấy, False nếu timeout.
        """
        self.ensure_one()
        lock_id = self._get_lock_id()
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            self.env.cr.execute(
                "SELECT pg_try_advisory_lock(%s)",
                (lock_id,)
            )
            if self.env.cr.fetchone()[0]:
                return True
            time.sleep(0.2)
        
        return False
    
    def _release_token_lock(self):
        """Giải phóng khóa thông báo cho việc refresh token."""
        self.ensure_one()
        lock_id = self._get_lock_id()
        try:
            self.env.cr.execute(
                "SELECT pg_advisory_unlock(%s)",
                (lock_id,)
            )
        except Exception as e:
            _logger.warning(f"Không thể mở khóa tài khoản {self.id}: {e}")
    
    def refresh_token(self, force=False):
        """
        Refresh token với khóa thông báo để ngăn chặn các cuộc cạnh tranh.
        
        Args:
            force: Nếu True, refresh ngay cả khi token vẫn còn hiệu lực
        
        Returns:
            str: Token hợp lệ hoặc False nếu refresh thất bại
        """
        self.ensure_one()
        
        # Try to acquire lock
        if not self._acquire_token_lock(timeout=10):
            _logger.warning(f"Không thể lấy khóa thông báo cho tài khoản {self.id}, sử dụng token hiện tại")
            self.invalidate_recordset(['token', 'token_expiry'])
            return self.token if self.token else False
        
        try:
            # Kiểm tra lại thời gian hết hạn sau khi lấy khóa (có thể có quá trình khác đã refresh)
            self.invalidate_recordset(['token', 'token_expiry'])
            
            if not force and self.token and self.token_expiry:
                try:
                    current_ts = int(datetime.now().timestamp())
                    expiry_ts = int(self.token_expiry)
                    # Handle milliseconds timestamp
                    if expiry_ts > 4102444800:  # Jan 1, 2100 in seconds
                        expiry_ts = expiry_ts // 1000
                    # Still valid for more than 5 minutes
                    if expiry_ts > current_ts + 300:
                        return self.token
                except (ValueError, TypeError):
                    _logger.warning(f"Invalid token_expiry format for account {self.id}: {self.token_expiry}")
            
            # Thực hiện refresh token
            VTPService = self.env['vtp.service']
            result = VTPService.get_token(self)
            
            if result and result.get('token'):
                self.write({
                    'token': result['token'],
                    'token_expiry': str(result.get('expiry', '')),  # Store as string
                    'token_last_refresh': fields.Datetime.now(),
                    'token_refresh_count': self.token_refresh_count + 1,
                    'userId': result.get('userId', 0),
                    'phone': result.get('phone', ''),
                    'last_error': False,
                    'active': True,
                })
                # Commit immediately so other workers can see the new token
                self.env.cr.commit()
                _logger.info(f"Token refresh thành công cho tài khoản {self.id}")
                return result['token']
            else:
                error_msg = 'Không thể refresh token - API trả về không có token'
                self.write({'last_error': error_msg})
                _logger.error(f"Token refresh thất bại cho tài khoản {self.id}: {error_msg}")
                return False
                
        except Exception as e:
            error_msg = f"Token refresh exception: {str(e)}"
            self.write({'last_error': error_msg})
            _logger.exception(f"Token refresh failed for account {self.id}")
            return False
            
        finally:
            self._release_token_lock()
    
    def get_valid_token(self):
        """
        Lấy token hợp lệ, refresh nếu cần thiết.
        Đây là điểm đầu vào chính cho việc lấy token.
        
        Returns:
            str: Token hợp lệ hoặc False nếu không thể lấy token
        """
        self.ensure_one()
        
        # Kiểm tra nếu token tồn tại và vẫn còn hiệu lực
        if self.token and self.token_expiry:
            try:
                current_ts = int(datetime.now().timestamp())
                expiry_ts = int(self.token_expiry)
                # Handle milliseconds timestamp
                if expiry_ts > 4102444800:  # Jan 1, 2100 in seconds
                    expiry_ts = expiry_ts // 1000
                
                # Token hợp lệ cho hơn 10 phút - sử dụng nó
                if expiry_ts > current_ts + 600:
                    return self.token
                
                # Token sắp hết hạn - refresh
                return self.refresh_token(force=True)
            except (ValueError, TypeError):
                _logger.warning(f"Invalid token_expiry for account {self.id}: {self.token_expiry}")
                # Try to refresh if token_expiry is invalid
                return self.refresh_token(force=True)
        
        # Không có token - lấy token mới
        return self.refresh_token(force=True)
    
    def log_api_call(self, endpoint, success=True, error=None):
        """Cập nhật thông tin API"""
        self.ensure_one()
        vals = {
            'last_api_call': fields.Datetime.now(),
            'api_call_count': self.api_call_count + 1,
        }
        if not success and error:
            vals['last_error'] = str(error)[:1000]
        elif success:
            vals['last_error'] = False
            
        self.write(vals)
    
    # ============ Action Buttons ============
    
    def action_get_token(self):
        """Button action to refresh token"""
        self.ensure_one()
        
        token = self.refresh_token(force=True)
        
        if token:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Thành công'),
                    'message': _('Đã lấy token mới thành công'),
                    'sticky': False,
                    'type': 'success',
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Thất bại'),
                    'message': self.last_error or _('Không thể lấy token. Vui lòng kiểm tra tài khoản hoặc mật khẩu.'),
                    'type': 'danger',
                    'sticky': True,
                }
            }
    
    def action_sync_stores(self):
        """Đồng bộ hóa dữ liệu từ API ViettelPost"""
        self.ensure_one()
        
        VTPService = self.env['vtp.service']
        Store = self.env['vtp.store']
        
        # Fetch stores using this account
        stores = VTPService.fetch_stores(self)
        
        if not stores or (isinstance(stores, dict) and stores.get('error')):
            error_msg = stores.get('error') if isinstance(stores, dict) else 'Không lấy được danh sách store'
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Thất bại'),
                    'message': error_msg,
                    'type': 'danger',
                    'sticky': True,
                }
            }
        
        # Process stores
        existing_stores = Store.search([('account_id', '=', self.id)])
        existing_store_ids = existing_stores.mapped('groupaddressId')
        processed_store_ids = set()
        
        for store_data in stores:
            store_id = store_data.get('groupaddressId')
            if not store_id:
                continue
            processed_store_ids.add(store_id)
            
            # Map location IDs
            province = self.env['vtp.province'].search(
                [('provinceId', '=', store_data.get('provinceId'))], limit=1
            )
            district = self.env['vtp.district'].search(
                [('districtId', '=', store_data.get('districtId'))], limit=1
            )
            ward = self.env['vtp.ward'].search(
                [('wardId', '=', store_data.get('wardId'))], limit=1
            )
            
            store_vals = {
                'groupaddressId': store_id,
                'cusId': store_data.get('cusId', 0),
                'name': store_data.get('name', ''),
                'phone': store_data.get('phone', ''),
                'address': store_data.get('address', ''),
                'provinceId': province.id or False,
                'districtId': district.id or False,
                'wardId': ward.id or False,
                'account_id': self.id,
            }
            
            # Update or create
            existing_store = existing_stores.filtered(lambda s: s.groupaddressId == store_id)
            if existing_store:
                diff_vals = {k: v for k, v in store_vals.items() if existing_store[k] != v}
                if diff_vals:
                    existing_store.write(diff_vals)
            else:
                Store.create(store_vals)
        
        # Archive removed stores
        stores_to_archive = set(existing_store_ids) - processed_store_ids
        if stores_to_archive:
            existing_stores.filtered(
                lambda s: s.groupaddressId in stores_to_archive
            ).write({'active': False})
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Thành công'),
                'message': _('Đã đồng bộ %d store thành công') % len(processed_store_ids),
                'sticky': False,
                'type': 'success',
            }
        }
    
    def action_view_audit_logs(self):
        """View audit logs for this account"""
        self.ensure_one()
        return {
            'name': _('API Audit Logs'),
            'type': 'ir.actions.act_window',
            'res_model': 'vtp.api.audit',
            'view_mode': 'list,form',
            'domain': [('account_id', '=', self.id)],
            'context': {'default_account_id': self.id},
        }


class VTPStore(models.Model):
    _name = 'vtp.store'
    _description = 'ViettelPost Store'
    _rec_name = 'name'

    name = fields.Char(string='Tên Store', required=True)
    groupaddressId = fields.Char(string='Group Address ID', index=True)
    cusId = fields.Char(string='Customer ID')
    phone = fields.Char(string='Số điện thoại')
    address = fields.Char(string='Địa chỉ')
    provinceId = fields.Many2one('vtp.province', string='Tỉnh/Thành phố', ondelete='set null')
    districtId = fields.Many2one('vtp.district', string='Quận/Huyện', ondelete='set null')
    wardId = fields.Many2one('vtp.ward', string='Phường/Xã', ondelete='set null')
    pricing_id = fields.One2many('vtp.pricing', 'store_id', string='Giá cước')
    order_bill_id = fields.One2many('vtp.order.bill', 'store_id', string='Vận đơn ViettelPost')
    store_id = fields.Char(string='Store ID', required=True, copy=False, default='New', readonly=True)
    account_id = fields.Many2one(
        'vtp.account', 
        string='Tài khoản VTP', 
        required=True, 
        ondelete='cascade',
        index=True
    )
    
    # Related fields
    province_code = fields.Char(string='Mã Tỉnh/TP', related='provinceId.province_code', store=True)
    district_value = fields.Integer(string='Mã Quận/Huyện', related='districtId.district_value', store=True)
    ward_name = fields.Char(string='Tên Phường/Xã', related='wardId.ward_name', store=True)
    account_name = fields.Char(string='Tên tài khoản', related='account_id.name', store=True)

    is_default = fields.Boolean(string='Mặc định', default=False)
    active = fields.Boolean(string='Hoạt động', default=True)
    
    _sql_constraints = [
        ('groupaddress_account_unique', 
         'UNIQUE(groupaddressId, account_id)', 
         'Store này đã tồn tại trong tài khoản!'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('store_id', 'New') == 'New':
                vals['store_id'] = self.env['ir.sequence'].next_by_code('vtp.store') or 'New'
            if vals.get('is_default') and vals.get('account_id'):
                # Only unset default within same account
                self.search([
                    ('account_id', '=', vals['account_id']),
                    ('is_default', '=', True)
                ]).write({'is_default': False})
        return super(VTPStore, self).create(vals_list)

    def write(self, vals):
        if vals.get('is_default'):
            # Only unset default within same account
            for record in self:
                self.search([
                    ('id', '!=', record.id),
                    ('account_id', '=', record.account_id.id),
                    ('is_default', '=', True)
                ]).write({'is_default': False})
        return super(VTPStore, self).write(vals)

    def action_set_default(self):
        """Set this store as default for its account"""
        self.ensure_one()
        # Chỉ ảnh hưởng đến các cửa hàng trong cùng một tài khoản
        self.search([
            ('account_id', '=', self.account_id.id),
            ('is_default', '=', True)
        ]).write({'is_default': False})
        self.write({'is_default': True})
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Thành công'),
                'message': _('Đã đặt %s làm store mặc định cho tài khoản %s') % (self.name, self.account_id.name),
                'sticky': False,
                'type': 'success',
            }
        }
    
    def get_account_token(self):
        """Helper method to get valid token from associated account"""
        self.ensure_one()
        if not self.account_id:
            raise UserError(_('Store chưa được gán tài khoản VTP!'))
        return self.account_id.get_valid_token()