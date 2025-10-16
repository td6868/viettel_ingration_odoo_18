from odoo import models, fields, api

class VtpService(models.Model):
    _name = 'vtp.service.bill'
    _description = 'ViettelPost Service'
    _rec_name = 'service_name'
    
    service_code = fields.Char(string = 'Mã dịch vụ', required=True)
    service_name = fields.Char(string='Tên dịch vụ', required=True)
    pricing_ids = fields.One2many('vtp.pricing', 'service_code', string='Danh sách giá')
    service_wizard = fields.One2many('vtp.shipping.wizard.mixin', 'service_type', string='Dịch vụ')