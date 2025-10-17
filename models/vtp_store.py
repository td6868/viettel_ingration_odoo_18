from odoo import api, fields, models


class VTPAccount(models.Model):
    _name = 'vtp.account'
    _description = 'ViettelPost Account'
    _rec_name = 'name'
    
    name = fields.Char(string='Tên tài khoản', required=True)
    userId = fields.Integer(string='User ID', readonly=True)
    phone = fields.Char(string='Số điện thoại', readonly=True)    
    username = fields.Char(string='Username', required=True)
    password = fields.Char(string='Password', required=True)
    client_id = fields.Char(string='Client ID')
    client_secret = fields.Char(string='Client Secret')
    token = fields.Text(string='Token', readonly=True)
    token_expiry = fields.Char(string='Hết hạn', readonly=True)
    active = fields.Boolean(string='Hoạt động', default=False)
    store_ids = fields.One2many('vtp.store', 'account_id', string='Danh sách Store')
    
    def action_get_token(self):
        """Lấy token mới từ API ViettelPost"""
        VTPService = self.env['vtp.service']
        for account in self:
            # Lưu thông tin tài khoản tạm thời vào config parameter
            self.env['ir.config_parameter'].sudo().set_param('viettel_ingration_odoo_18.username', account.username)
            self.env['ir.config_parameter'].sudo().set_param('viettel_ingration_odoo_18.password', account.password)
            if account.client_id:
                self.env['ir.config_parameter'].sudo().set_param('viettel_ingration_odoo_18.client_id', account.client_id)
            if account.client_secret:
                self.env['ir.config_parameter'].sudo().set_param('viettel_ingration_odoo_18.client_secret', account.client_secret)
                
            # Lấy token
            result = VTPService.get_token()
            if not result:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Thất bại',
                        'message': 'Không thể lấy token. Vui lòng kiểm tra tài khoản hoặc mật khẩu.',
                        'type': 'danger',
                        'sticky': False,
                    }
                }
            if result and result.get('token'):
                account.write({
                    'userId': result.get('userId', 0),
                    'token': result['token'],                    
                    'token_expiry': result.get('expiry'),
                    'phone': result.get('phone', ''),
                })
                account.active = True
                
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Thành công',
                'message': 'Đã lấy token mới thành công',
                'sticky': False,
                'type': 'success',
            }
        }
    
    def action_sync_stores(self):
        """Đồng bộ danh sách store từ API ViettelPost"""
        VTPService = self.env['vtp.service']
        Store = self.env['vtp.store']

        for account in self:
            # set tạm credential
            self.env['ir.config_parameter'].sudo().set_param('viettel_ingration_odoo_18.username', account.username)
            self.env['ir.config_parameter'].sudo().set_param('viettel_ingration_odoo_18.password', account.password)
            if account.token:
                self.env['ir.config_parameter'].sudo().set_param('viettel_ingration_odoo_18.token', account.token)
                self.env['ir.config_parameter'].sudo().set_param(
                    'viettel_ingration_odoo_18.token_expiry',
                    account.token_expiry if account.token_expiry else ''
                )

            # gọi API lấy store raw data
            stores = VTPService.fetch_stores()
            if not stores:
                continue

            # Lấy tất cả store hiện có của account
            existing_stores = Store.search([('account_id', '=', account.id)])
            existing_store_ids = existing_stores.mapped('groupaddressId')
            processed_store_ids = set()

            for store_data in stores:
                store_id = store_data.get('groupaddressId')
                if not store_id:
                    continue
                processed_store_ids.add(store_id)

                # Map Many2one từ mã API sang record Odoo
                province = self.env['vtp.province'].search([('provinceId', '=', store_data.get('provinceId'))], limit=1)
                district = self.env['vtp.district'].search([('districtId', '=', store_data.get('districtId'))], limit=1)
                ward = self.env['vtp.ward'].search([('wardId', '=', store_data.get('wardId'))], limit=1)

                store_vals = {
                    'groupaddressId': store_id,
                    'cusId': store_data.get('cusId', 0),
                    'name': store_data.get('name', ''),
                    'phone': store_data.get('phone', ''),
                    'address': store_data.get('address', ''),
                    'provinceId': province.id or False,
                    'districtId': district.id or False,
                    'wardId': ward.id or False,
                    'account_id': account.id,
                }

                # Kiểm tra store đã tồn tại chưa
                existing_store = existing_stores.filtered(lambda s: s.groupaddressId == store_id)
                if existing_store:
                    # So sánh để tránh write thừa
                    diff_vals = {
                        k: v for k, v in store_vals.items()
                        if existing_store[k] != v
                    }
                    if diff_vals:
                        existing_store.write(diff_vals)
                else:
                    Store.create(store_vals)

            # Archive stores không còn trong API
            stores_to_archive = set(existing_store_ids) - processed_store_ids
            if stores_to_archive:
                existing_stores.filtered(
                    lambda s: s.groupaddressId in stores_to_archive
                ).write({'active': False})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Thành công',
                'message': 'Đã đồng bộ danh sách store thành công',
                'sticky': False,
                'type': 'success',
            }
        }



class VTPStore(models.Model):
    _name = 'vtp.store'
    _description = 'ViettelPost Store'
    _rec_name = 'name'

    name = fields.Char(string='Tên Store', required=True)
    groupaddressId = fields.Char(string='Group Address ID')
    cusId = fields.Char(string='Customer ID')
    phone = fields.Char(string='Số điện thoại')
    address = fields.Char(string='Địa chỉ')
    provinceId = fields.Many2one('vtp.province', string='Tỉnh/Thành phố', ondelete='cascade')
    districtId = fields.Many2one('vtp.district', string='Quận/Huyện', ondelete='cascade')
    wardId = fields.Many2one('vtp.ward', string='Phường/Xã', ondelete='cascade')
    pricing_id = fields.One2many('vtp.pricing', 'store_id', string='Giá cước')
    order_bill_id = fields.One2many('vtp.order.bill', 'store_id', string='Vận đơn ViettelPost')
    store_id = fields.Char(string='Store ID', required=True, copy=False, default='New', readonly=True)
    account_id = fields.Many2one('vtp.account', string='Tài khoản VTP', required=True, ondelete='cascade')
    
    province_code = fields.Char(string='Tên Tỉnh/Thành phố', related='provinceId.province_code', store=True)
    district_value = fields.Integer(string='Mã Quận/Huyện', related='districtId.district_value', store=True)
    ward_name = fields.Char(string='Tên Phường/Xã', related='wardId.ward_name', store=True)

    is_default = fields.Boolean(string='Mặc định', default=False)
    active = fields.Boolean(string='Hoạt động', default=True)

    @api.model
    def create(self, vals):
        if vals.get('store_id', 'New') == 'New':
            vals['store_id'] = self.env['ir.sequence'].next_by_code('vtp.store') or 'New'
        if vals.get('is_default'):
            self.search([('is_default', '=', True)]).write({'is_default': False})
        return super(VTPStore, self).create(vals)

    def write(self, vals):
        if vals.get('is_default'):
            self.search([('id', '!=', self.id), ('is_default', '=', True)]).write({'is_default': False})
        return super(VTPStore, self).write(vals)

    def action_set_default(self):
        """Đặt store này làm mặc định"""
        self.ensure_one()
        self.search([('is_default', '=', True)]).write({'is_default': False})
        self.write({'is_default': True})
        # Cập nhật cấu hình
        self.env['ir.config_parameter'].sudo().set_param('viettel_ingration_odoo_18.default_store_id', self.id)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Thành công',
                'message': f'Đã đặt {self.name} làm store mặc định',
                'sticky': False,
                'type': 'success',
            }
        }