from odoo import models, fields, api
from .vtp_store import VTPStore
import logging

_logger = logging.getLogger(__name__)

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
    
    # Temporary field for Excel import
    district_name_temp = fields.Char(string='Tên Quận/Huyện (Import)', help='Dùng để import từ Excel, hệ thống sẽ tự động tìm District ID')
    
    @api.model_create_multi
    def create(self, vals_list):
        """Auto-map district_name_temp to districtId during import"""
        for vals in vals_list:
            if vals.get('district_name_temp') and not vals.get('districtId'):
                district_name = vals['district_name_temp'].strip()
                district = self.env['vtp.district'].search([
                    ('district_name', '=', district_name)
                ], limit=1)
                
                if district:
                    vals['districtId'] = district.id
                else:
                    # Log warning but don't fail
                    _logger.warning(f"District not found: {district_name} for ward {vals.get('ward_name')}")
            
            # Remove temp field before creating
            vals.pop('district_name_temp', None)
        
        return super().create(vals_list)
    
    def name_get(self):
        result = []
        for rec in self:
            result.append((rec.id, rec.ward_name))
        return result