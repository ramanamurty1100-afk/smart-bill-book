import os
import tempfile
import unittest

DB_FILE = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ["DATABASE_PATH"] = DB_FILE
os.environ["SECRET_KEY"] = "test-secret-key"
import app as billapp

class BillBookFlowTests(unittest.TestCase):
    def setUp(self):
        self.client = billapp.app.test_client()
        with billapp.db() as c:
            for table in ("payments","purchase_items","purchases","expenses","bill_items","bills","customers","products","settings","users"):
                c.execute("DELETE FROM " + table)
        r = self.client.post("/api/register", json={"username":"tester","password":"testpass123"})
        self.assertEqual(r.status_code, 200)

    def test_shop_flow_gst_purchase_payment_and_reports(self):
        self.assertEqual(self.client.post("/api/customers",json={"name":"Asha","phone":"9999999999"}).status_code,200)
        self.assertEqual(self.client.post("/api/products",json={"name":"Tea","price":100,"stock":10}).status_code,200)
        product=self.client.get("/api/products").get_json()[0]
        purchase=self.client.post("/api/purchases",json={"supplier":"Supplier","items":[{"product_id":product["id"],"qty":5,"cost_price":60}]})
        self.assertEqual(purchase.status_code,200)
        bill=self.client.post("/api/bills",json={"customer_name":"Asha","items":[{"product_id":product["id"],"qty":2}],"gst_rate":5,"gst_type":"intra","paid":50})
        self.assertEqual(bill.status_code,200,bill.get_json())
        bid=bill.get_json()["id"]
        detail=self.client.get(f"/api/bills/{bid}").get_json()
        self.assertAlmostEqual(detail["bill"]["cgst"],5,places=2)
        self.assertAlmostEqual(detail["bill"]["sgst"],5,places=2)
        self.assertEqual(len(detail["payments"]),1)
        payment=self.client.post(f"/api/bills/{bid}/payments",json={"amount":70,"method":"UPI"})
        self.assertEqual(payment.status_code,200,payment.get_json())
        self.assertAlmostEqual(payment.get_json()["remaining"],90,places=2)
        self.assertEqual(self.client.post("/api/expenses",json={"title":"Rent","amount":1000}).status_code,200)
        product_after=self.client.get("/api/products").get_json()[0]
        self.assertEqual(product_after["stock"],13)
        report=self.client.get("/api/reports")
        self.assertEqual(report.status_code,200)
        backup=self.client.get("/api/backup")
        self.assertEqual(backup.status_code,200)
        self.assertEqual(backup.get_json()["format"],"smart-bill-book-backup-v1")
        self.assertEqual(len(backup.get_json()["data"]["bills"]),1)

    def test_rejects_invalid_product_and_payment(self):
        self.assertEqual(self.client.post("/api/products",json={"name":"Bad","price":-1,"stock":2}).status_code,400)
        self.assertEqual(self.client.post("/api/expenses",json={"title":"","amount":10}).status_code,400)

if __name__ == "__main__":
    unittest.main()
