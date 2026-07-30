from typing import Dict, Any, Optional

class ComplianceEngine:
    @staticmethod
    def calculate_unit_price(price: float, amount: float, unit: str) -> Dict[str, Any]:
        """
        Fiyat Etiketi Yönetmeliği uyarınca birim fiyat hesaplar.
        Örn: 500 gr fındık 150 TL -> 1 kg fındık 300 TL / kg
        """
        if not amount or amount <= 0:
            return {"has_error": True, "message": "Geçersiz miktar veya hacim."}
        
        # Gramaj veya mililitre girildiyse kg/L bazına çevir
        unit_lower = unit.lower().strip()
        factor = 1.0
        base_unit = unit

        if unit_lower in ["g", "gr", "gram"]:
            factor = 1000.0
            base_unit = "kg"
        elif unit_lower in ["ml", "mililitre"]:
            factor = 1000.0
            base_unit = "L"

        unit_price = (price / amount) * factor
        
        return {
            "has_error": False,
            "unit_price": round(unit_price, 2),
            "base_unit": base_unit,
            "formatted_text": f"Birim Fiyatı: {unit_price:.2f} TL / {base_unit}"
        }