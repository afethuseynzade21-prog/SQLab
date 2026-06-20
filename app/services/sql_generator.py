"""
SQL Generator — promptlarin qurulmasi ve few-shot numuneleri.
Bu modul yalniz METN qurur, hec bir API cagirisi etmir.
"""

FEW_SHOT = """
FEW-SHOT NUMUNELER:

Sual: aylik sifaris sayi
SQL: SELECT EXTRACT(MONTH FROM order_purchase_timestamp) AS ay, COUNT(*) AS sifaris_sayi FROM olist_orders_dataset GROUP BY ay ORDER BY ay

Sual: en cox satilan kateqoriyalar
SQL: SELECT p.product_category_name, COUNT(*) AS satis FROM olist_order_items_dataset oi JOIN olist_products_dataset p ON oi.product_id = p.product_id GROUP BY p.product_category_name ORDER BY satis DESC LIMIT 10

Sual: catdirilmis sifarislerin faizi
SQL: SELECT ROUND(COUNT(*) FILTER (WHERE order_status = 'delivered') * 100.0 / COUNT(*), 2) AS faiz FROM olist_orders_dataset

Sual: en cox musterili sehirler
SQL: SELECT customer_city, COUNT(*) AS musteri_sayi FROM olist_customers_dataset GROUP BY customer_city ORDER BY musteri_sayi DESC LIMIT 10

Sual: odenis novlerinin paylanmasi
SQL: SELECT payment_type, COUNT(*) AS say, ROUND(SUM(payment_value), 2) AS umumi FROM olist_order_payments_dataset GROUP BY payment_type ORDER BY say DESC

Sual: umumi gelir
SQL: SELECT ROUND(SUM(price + freight_value), 2) AS umumi_gelir FROM olist_order_items_dataset

Sual: bazarin 80 faiz satisini nece satici formalasdirir
SQL: WITH satis AS (SELECT seller_id, SUM(price + freight_value) AS umumi FROM olist_order_items_dataset GROUP BY seller_id), kumul AS (SELECT seller_id, umumi, SUM(umumi) OVER (ORDER BY umumi DESC) AS kumul_satis, SUM(umumi) OVER () AS total_satis FROM satis) SELECT COUNT(*) AS satici_sayi FROM kumul WHERE kumul_satis <= total_satis * 0.8
"""


def build_chat_prompt(filtered_schema: str, semantic_block: str, message: str) -> str:
    """Esas SQL generasiya prompt-unu qurur: sxem + semantic + few-shot + CoT."""
    return (
        "Sen SQL agentisen. Asagidaki sxem ve semantik layere esaslanaraq sualini cavabla.\n\n"
        + filtered_schema + "\n\n"
        + semantic_block + "\n\n"
        + FEW_SHOT + "\n\n"
        "DUSUNCE PROSESI - SQL yazmadan evvel:\n"
        "1. Sual ne sorusur?\n"
        "2. Hansi cedveller lazimdir?\n"
        "3. Hansi hesablamalar lazimdir?\n"
        "4. Netice nece olmalidir?\n\n"
        "VACIB QAYDALAR:\n"
        "- Yalniz sxemdeki REAL sutun adlarini istifade et\n"
        "- SQL-i ```sql ``` blokunun icine yaz\n"
        "- Cavabi durugli Azerbaycan edebiyyat dilinde, resmi uslubda ver\n"
        "- SQL alias adlarinda noqte isletme\n\n"
        "Istifadeci suali: " + message + "\n\n"
        "Yuxaridaki dusunce prosesini izle, sonra SQL sorgusu yaz."
    )


def build_excel_prompt(schema_info: str, table_name: str, message: str) -> str:
    """Excel/CSV data source ucun SQL generasiya prompt-unu qurur."""
    return (
        f"Sen Excel/CSV fayl analiz agentisen. YALNIZ asagidaki Excel faylindaki melumatlarla isle.\n\n"
        f"EXCEL FAYL:\n{schema_info}\n\n"
        f"SUPER VACIB: Yalniz '{table_name}' cedvelini istifade et. FROM {table_name} yaz.\n"
        f"information_schema, olist ve ya baska cedvellere muraciet ETME.\n"
        f"SQL-i ```sql ``` blokunun icine yaz. Cavabi durugli Azerbaycan edebiyyat dilinde, resmi uslubda ver.\n\n"
        f"Istifadeci suali: {message}\n\n"
        f"Yalniz '{table_name}' cedvelindeki sutunlari istifade ederek SQL yaz."
    )
