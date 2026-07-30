import logging
import requests
from typing import List, Dict, Any, Optional

logger = logging.getLogger("UyumHub.IkasClient")

class IkasGraphQLClient:
    GRAPHQL_URL = "https://api.myikas.com/api/v1/admin/graphql"

    def __init__(self, access_token: str):
        self.access_token = access_token
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "User-Agent": "UyumHub/1.0"
        }

    def _execute_query(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        İkas GraphQL API'sine sorgu gönderir.
        """
        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        try:
            response = requests.post(self.GRAPHQL_URL, json=payload, headers=self.headers, timeout=15)
            response.raise_for_status()
            res_data = response.json()

            if "errors" in res_data:
                logger.error(f"GraphQL Hata Döndürdü: {res_data['errors']}")
                return {"success": False, "errors": res_data["errors"]}

            return {"success": True, "data": res_data.get("data", {})}
        except Exception as e:
            logger.error(f"İkas API Bağlantı Hatası: {str(e)}")
            return {"success": False, "error": str(e)}

    def list_products(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Mağazadaki ürün listesini, fiyatlarını ve ağırlık/hacim detaylarını getirir.
        """
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
        result = self._execute_query(query, {"limit": limit})
        if result.get("success") and "listProduct" in result.get("data", {}):
            return result["data"]["listProduct"].get("data", [])
        return []