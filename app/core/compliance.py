import logging

logger = logging.getLogger("UyumHub.Compliance")

class ComplianceEngine:
    @staticmethod
    def calculate_unit_price(price: float, weight_or_volume: float = None, unit: str = "kg", *args, **kwargs):
        """
        TR Fiyat Etiketi Yönetmeliği'ne uygun birim fiyat hesaplama motoru.
        Hem konum parametrelerini hem de esnek anahtar kelimeleri (weight, quantity, volume) destekler.
        """
        # Miktar/Hacim parametresini esnek şekilde yakala
        qty = weight_or_volume
        if qty is None:
            if args:
                qty = args[0]
            else:
                qty = kwargs.get("weight") or kwargs.get("quantity") or kwargs.get("volume") or kwargs.get("amount") or 1.0

        try:
            price = float(price)
            qty = float(qty)
        except (ValueError, TypeError):
            return {"has_error": True, "message": "Geçersiz fiyat veya miktar."}

        if qty <= 0:
            return {"has_error": True, "message": "Geçersiz miktar/hacim."}

        base_unit_price = price / qty
        return {
            "has_error": False,
            "unit_price_formatted": f"{base_unit_price:.2f} TL / {unit}",
            "raw_unit_price": round(base_unit_price, 2),
            "display_text": f"Birim Fiyatı: {base_unit_price:.2f} TL/{unit}"
        }

    @staticmethod
    def generate_distance_sales_contract(merchant_info: dict, customer_info: dict, cart_items: list, *args, **kwargs):
        return "<html><body><h1>Mesafeli Satış Sözleşmesi</h1></body></html>"