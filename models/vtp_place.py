from odoo import models, fields, api
from .vtp_store import VTPStore

class VTPProvince(models.Model):
    _name = 'vtp.province'
    _description = 'ViettelPost Province'
    _rec_name = 'province_name'

    provinceId = fields.Integer(string='ID Tỉnh/Thành phố')
    province_name = fields.Char(string='Tên Tỉnh/Thành phố', required=True)
    province_code = fields.Char(string='Mã Tỉnh/Thành phố', required=True)
    districtIds = fields.One2many('vtp.district', 'provinceId', string='Quận/Huyện')
    
    def name_get(self):
        result = []
        for rec in self:
            result.append((rec.id, rec.province_name))
        return result
    
class VTPDistrict(models.Model):
    _name = 'vtp.district'
    _description = 'ViettelPost District'
    _rec_name = 'district_name'

    districtId = fields.Integer(string='ID Quận/Huyện')
    district_name = fields.Char(string='Tên Quận/Huyện', required=True)
    district_value = fields.Integer(string='Mã Quận/Huyện', required=True)
    provinceId = fields.Many2one('vtp.province', string='Tỉnh/Thành phố')
    wardIds = fields.One2many('vtp.ward', 'districtId', string='Phường/Xã')
    
    def name_get(self):
        result = []
        for rec in self:
            result.append((rec.id, rec.district_name))
        return result
    
class VTPWard(models.Model):
    _name = 'vtp.ward'
    _description = 'ViettelPost Ward'
    _rec_name = 'ward_name'

    wardId = fields.Integer(string='ID Phường/Xã')
    ward_name = fields.Char(string='Tên Phường/Xã', required=True)
    districtId = fields.Many2one('vtp.district', string='Quận/Huyện')
    
    def name_get(self):
        result = []
        for rec in self:
            result.append((rec.id, rec.ward_name))
        return result