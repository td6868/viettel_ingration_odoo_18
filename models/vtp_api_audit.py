# -*- coding: utf-8 -*-
"""
VTP API Audit Log Model
Track all API calls for debugging, auditing, and compliance.
"""

from odoo import models, fields, api
from datetime import datetime, timedelta
import logging

_logger = logging.getLogger(__name__)


class VTPAPIAudit(models.Model):
    _name = 'vtp.api.audit'
    _description = 'VTP API Audit Log'
    _order = 'timestamp desc'
    _rec_name = 'endpoint'

    # Relationships
    account_id = fields.Many2one(
        'vtp.account', 
        string='Account', 
        required=True, 
        ondelete='cascade', 
        index=True
    )
    order_bill_id = fields.Many2one(
        'vtp.order.bill', 
        string='Order Bill', 
        ondelete='set null', 
        index=True
    )

    # Request Info
    endpoint = fields.Char(string='API Endpoint', required=True, index=True)
    method = fields.Selection([
        ('GET', 'GET'),
        ('POST', 'POST'),
        ('PUT', 'PUT'),
    ], string='HTTP Method', default='POST')
    
    request_data = fields.Text(string='Request Data')
    response_data = fields.Text(string='Response Data')
    
    # Response Info
    success = fields.Boolean(string='Success', default=True, index=True)
    error_message = fields.Text(string='Error Message')
    http_status = fields.Integer(string='HTTP Status Code')
    
    # Timing
    timestamp = fields.Datetime(
        string='Timestamp', 
        required=True, 
        default=fields.Datetime.now, 
        index=True
    )
    duration_ms = fields.Integer(string='Duration (ms)')
    
    # Token Tracking (only last 10 chars for security)
    token_used = fields.Char(string='Token Used (last 10 chars)', size=10)
    
    # User tracking
    user_id = fields.Many2one('res.users', string='User', default=lambda self: self.env.user)
    
    @api.autovacuum
    def _gc_audit_logs(self):
        """Auto-delete logs older than 90 days to manage disk space"""
        cutoff = datetime.now() - timedelta(days=90)
        old_logs = self.search([('timestamp', '<', cutoff)])
        count = len(old_logs)
        if count:
            old_logs.unlink()
            _logger.info(f"VTP Audit: Cleaned up {count} old audit logs")
        return True
    
    @api.model
    def create_log(self, account, endpoint, method='POST', request_data=None, 
                   response_data=None, success=True, error_message=None,
                   http_status=None, duration_ms=None, token=None, order_bill=None):
        """
        Helper method to create audit log entry safely.
        
        Args:
            account: vtp.account recordset
            endpoint: str - API endpoint called
            method: str - HTTP method
            request_data: dict - Request payload (will be JSON encoded)
            response_data: dict - Response data (will be JSON encoded)
            success: bool - Whether call was successful
            error_message: str - Error message if failed
            http_status: int - HTTP status code
            duration_ms: int - Duration in milliseconds
            token: str - Full token (only last 10 chars will be stored)
            order_bill: vtp.order.bill recordset (optional)
        
        Returns:
            vtp.api.audit recordset or False if creation fails
        """
        import json
        
        try:
            vals = {
                'account_id': account.id,
                'endpoint': endpoint,
                'method': method,
                'success': success,
                'timestamp': fields.Datetime.now(),
            }
            
            if order_bill:
                vals['order_bill_id'] = order_bill.id
                
            if request_data:
                # Mask sensitive data
                safe_request = self._mask_sensitive_data(request_data)
                vals['request_data'] = json.dumps(safe_request, ensure_ascii=False, indent=2)
                
            if response_data:
                vals['response_data'] = json.dumps(response_data, ensure_ascii=False, indent=2)
                
            if error_message:
                vals['error_message'] = error_message[:2000]  # Limit length
                
            if http_status:
                vals['http_status'] = http_status
                
            if duration_ms:
                vals['duration_ms'] = duration_ms
                
            if token:
                vals['token_used'] = token[-10:]  # Only store last 10 chars
                
            return self.create(vals)
            
        except Exception as e:
            _logger.error(f"Failed to create VTP audit log: {str(e)}")
            return False
    
    def _mask_sensitive_data(self, data):
        """Mask sensitive fields in request data for security"""
        if not isinstance(data, dict):
            return data
            
        safe_data = data.copy()
        sensitive_fields = ['PASSWORD', 'password', 'token', 'Token', 'client_secret']
        
        for field in sensitive_fields:
            if field in safe_data:
                value = safe_data[field]
                if value and isinstance(value, str):
                    safe_data[field] = value[:3] + '*' * (len(value) - 6) + value[-3:] if len(value) > 6 else '***'
                    
        return safe_data
