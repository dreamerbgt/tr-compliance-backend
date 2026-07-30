import logging
from typing import Dict, Any, List

logger = logging.getLogger("UyumHub.Compliance")

class ComplianceEngine:
    @staticmethod
    def calculate_unit_price(price: float, weight_or_volume: float = None, unit: str = "kg", *args, **kwargs):
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
    def generate_distance_sales_contract(merchant_info: Dict[str, Any], customer_info: Dict[str, Any], cart_items: List[Dict[str, Any]], *args, **kwargs) -> str:
        """
        6502 Sayılı Tüketicinin Korunması Hakkında Kanun ve Mesafeli Sözleşmeler Yönetmeliği'ne 
        uygun dinamik Mesafeli Satış Sözleşmesi ve Ön Bilgilendirme Formu üretir.
        """
        # Satıcı Bilgileri
        m_name = merchant_info.get("company_name", "UyumHub Test Mağazası A.Ş.")
        m_address = merchant_info.get("address", "Kayseri Teknopark İletişim Cad. No: 1/A Melikgazi/Kayseri")
        m_phone = merchant_info.get("phone", "0850 000 00 00")
        m_email = merchant_info.get("email", "destek@uyumhub.com")
        m_mersis = merchant_info.get("mersis_no", "0123456789000015")

        # Alıcı Bilgileri
        c_name = customer_info.get("name", "Müşteri Adı Soyadı")
        c_address = customer_info.get("address", "Teslimat Adresi Belirtilmedi")
        c_phone = customer_info.get("phone", "0500 000 00 00")
        c_email = customer_info.get("email", "musteri@ornek.com")

        # Sepet ve Ürün Kalemleri Hesaplama
        subtotal = 0.0
        items_html = ""
        for item in cart_items:
            name = item.get("name", "Ürün Adı")
            qty = item.get("quantity", 1)
            price = item.get("price", 0.0)
            total = qty * price
            subtotal += total
            items_html += f"""
            <tr>
                <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">{name}</td>
                <td style="padding: 10px; border-bottom: 1px solid #e2e8f0; text-align: center;">{qty}</td>
                <td style="padding: 10px; border-bottom: 1px solid #e2e8f0; text-align: right;">{price:.2f} TL</td>
                <td style="padding: 10px; border-bottom: 1px solid #e2e8f0; text-align: right;">{total:.2f} TL</td>
            </tr>
            """

        shipping_fee = 49.90 if subtotal > 0 and subtotal < 1000 else 0.0
        grand_total = subtotal + shipping_fee

        contract_html = f"""
        <!DOCTYPE html>
        <html lang="tr">
        <head>
            <meta charset="UTF-8">
            <title>Mesafeli Satış Sözleşmesi ve Ön Bilgilendirme Formu</title>
            <style>
                body {{ font-family: 'Arial', sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: 0 auto; padding: 20px; }}
                h1 {{ font-size: 18px; text-align: center; color: #1e293b; margin-bottom: 5px; }}
                h2 {{ font-size: 14px; color: #475569; border-bottom: 2px solid #cbd5e1; padding-bottom: 5px; margin-top: 25px; }}
                p, li {{ font-size: 12px; text-align: justify; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 12px; }}
                th {{ background-color: #f1f5f9; padding: 10px; text-align: left; border-bottom: 2px solid #cbd5e1; }}
                .box {{ background: #f8fafc; border: 1px solid #e2e8f0; padding: 15px; border-radius: 6px; margin-bottom: 15px; font-size: 12px; }}
                .legal-footer {{ font-size: 10px; color: #64748b; margin-top: 30px; text-align: center; border-top: 1px solid #e2e8f0; padding-top: 10px; }}
            </style>
        </head>
        <body>

            <h1>MESAFELİ SATIŞ SÖZLEŞMESİ</h1>
            <p style="text-align: center; font-size: 11px; color: #64748b;">İşbu sözleşme 6502 sayılı Tüketicinin Korunması Hakkında Kanun ve Mesafeli Sözleşmeler Yönetmeliği'ne uygundur.</p>

            <h2>MADDE 1: TARAFLAR</h2>
            <div class="box">
                <strong>SATICI BİLGİLERİ</strong><br>
                Unvanı: {m_name}<br>
                Adresi: {m_address}<br>
                Telefon: {m_phone} | E-posta: {m_email}<br>
                MERSİS No: {m_mersis}
            </div>
            <div class="box">
                <strong>ALICI BİLGİLERİ</strong><br>
                Adı Soyadı / Unvanı: {c_name}<br>
                Teslimat Adresi: {c_address}<br>
                Telefon: {c_phone} | E-posta: {c_email}
            </div>

            <h2>MADDE 2: SÖZLEŞME KONUSU ÜRÜNLER VE BEDELİ</h2>
            <table>
                <thead>
                    <tr>
                        <th>Ürün / Hizmet Açıklaması</th>
                        <th style="text-align: center;">Adet</th>
                        <th style="text-align: right;">Birim Fiyat</th>
                        <th style="text-align: right;">Toplam</th>
                    </tr>
                </thead>
                <tbody>
                    {items_html}
                </tbody>
            </table>
            
            <div style="text-align: right; margin-top: 10px; font-size: 13px;">
                <p>Ara Toplam: <strong>{subtotal:.2f} TL</strong></p>
                <p>Kargo Ücreti: <strong>{shipping_fee:.2f} TL</strong></p>
                <p style="font-size: 15px; color: #0f172a;"><strong>Genel Toplam: {grand_total:.2f} TL</strong></p>
            </div>

            <h2>MADDE 3: GENEL HÜKÜMLER</h2>
            <ol>
                <li>Alıcı, internet sitesinde sözleşme konusu ürünün temel nitelikleri, satış fiyatı ve ödeme şekli ile teslimata ilişkin ön bilgileri okuyup bilgi sahibi olduğunu ve elektronik ortamda gerekli teyidi verdiğini beyan eder.</li>
                <li>Sözleşme konusu ürün, yasal 30 günlük süreyi aşmamak kaydı ile alıcının yerleşim yerinin uzaklığına bağlı olarak internet sitesinde ön bilgiler içinde açıklanan süre zarfında alıcı veya gösterdiği adresteki kişi/kuruluşa teslim edilir.</li>
                <li>Ürünün teslim edキュリティe masrafı olan kargo ücreti aksi belirtilmedikçe Alıcı'ya aittir.</li>
            </ol>

            <h2>MADDE 4: CAYMA HAKKI</h2>
            <p>Alıcı, sözleşme konusu ürünün kendisine veya gösterdiği adresteki kişi/kuruluşa tesliminden itibaren <strong>14 (on dört) gün</strong> içinde hiçbir hukuki ve cezai sorumluluk üstlenmeksizin ve hiçbir gerekçe göstermeksizin malı reddederek sözleşmeden cayma hakkına sahiptir.</p>
            <p>Cayma hakkının kullanılmasında 14 günlük süre içinde satıcıya yazılı olarak bildirimde bulunulması yeterlidir. İade edilecek ürünlerin kutusu, ambalajı, varsa standart aksesuarları ile birlikte eksiksiz ve hasarsız olarak teslim edilmesi gerekmektedir.</p>

            <h2>MADDE 5: YETKİLİ MAHKEME</h2>
            <p>İşbu sözleşmeden doğan uyuşmazlıklarda, Ticaret Bakanlığı'nca ilan edilen değere kadar Tüketici Hakem Heyetleri ile Alıcı'nın veya Satıcı'nın yerleşim yerindeki Tüketici Mahkemeleri yetkilidir.</p>

            <div class="legal-footer">
                UyumHub Mevzuat ve Uyum Motoru tarafından güvenle üretilmiştir. | Tarih: 2026-07-30
            </div>

        </body>
        </html>
        """
        return contract_html