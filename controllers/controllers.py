from odoo import http
from odoo.http import request
import json
import urllib.request
import urllib.error


class AddressConvertController(http.Controller):

    def get_new_address(self, old_address):
        """Hàm gọi API Casso"""
        url = "https://production.cas.so/address-kit/convert"
        try:
            data = {
                "oldAddress": old_address
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(data).encode('utf-8'),
                method='POST',
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                if response.getcode() != 200:
                    return False

                data = json.loads(response.read())
                return data.get("newAddress", {}).get("fullAddress") or False

        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
            return False
        
    

    @http.route('/api/convert/address', type='json', auth='public', methods=['POST'], csrf=False)
    def api_convert_address(self, **post):
        """
        API nhận vào old_address (POST JSON) và trả về new_address.
        Ví dụ:
        POST /api/convert/address
        {
            "old_address": "123 duong cu, Quan 1, TPHCM"
        }
        """
        old_address = post.get("old_address")
        if not old_address:
            return {"success": False, "message": "Thiếu tham số old_address"}

        new_address = self.get_new_address(old_address)
        if not new_address:
            return {"success": False, "message": "Không convert được địa chỉ"}

        return {"success": True, "new_address": new_address}
