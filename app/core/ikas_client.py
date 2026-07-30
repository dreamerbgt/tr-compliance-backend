import json
import logging
import urllib.request
import urllib.error
from typing import List, Dict, Any, Optional

logger = logging.getLogger("UyumHub.IkasClient")

class IkasGraphQLClient:
    GRAPHQL_URL = "https://api.myikas.com/api/v1/admin/graphql"

    def __init__(self, access_token: str):
        self.access_token = access_token
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) UyumHub/1.0",
            "Accept": "application/json"
        }

    def _execute_query(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        try:
            payload_bytes = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.GRAPHQL_URL,
                data=payload_bytes,
                headers=self.headers,
                method="POST"
            )
            
            with urllib.request.urlopen(req, timeout=15) as response:
                res_body = json.loads(response.read().decode("utf-8"))
                if isinstance(res_body, dict) and "errors" in res_body:
                    logger.error(f"GraphQL Hata Döndürdü: {res_body['errors']}")
                    return {"success": False, "errors": res_body["errors"]}
                return {"success": True, "data": res_body.get("data") if isinstance(res_body, dict) else {}}
        except urllib.error.HTTPError as e:
            logger.error(f"İkas API HTTP Hatası: {e.code} - {e.reason}")
            return {"success": False, "error": f"HTTP {e.code}: {e.reason}"}
        except Exception as e:
            logger.error(f"İkas API Bağlantı Hatası: {str(e)}")
            return {"success": False, "error": str(e)}

    def list_products(self, limit: int = 20) -> List[Dict[str, Any]]:
        query = """
        query listProducts($limit: Int) {
          listProduct(limit: $limit) {
            data {
              id
              name
              variants {
                id
                sku
                price
                weight
                unit
              }
            }
          }
        }
        """
        try:
            result = self._execute_query(query, {"limit": limit})
            data = result.get("data") if isinstance(result, dict) else {}
            if isinstance(data, dict) and "listProduct" in data and isinstance(data["listProduct"], dict):
                return data["listProduct"].get("data", []) or []
        except Exception as e:
            logger.error(f"list_products işlenirken hata: {str(e)}")
        return []