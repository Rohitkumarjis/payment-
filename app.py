# app.py - Main Server & Dynamic QR Checkout
import uuid
import urllib.parse
from flask import Flask, request, jsonify, render_template_string
from config import MERCHANT_UPI_ID, MERCHANT_NAME, GATEWAY_SECRET_KEY
from database import init_db, create_order, get_order
from gmail_listener import scan_gmail_for_order

app = Flask(__name__)
init_db()

DOCS_HTML = '''<!DOCTYPE html>
<html>
<head>
<title>Auto UPI Gateway Documentation</title>
<style>
body { font-family: sans-serif; background: #0f172a; color: #fff; padding: 25px; line-height: 1.6; }
.box { max-width: 800px; margin: auto; background: #1e293b; padding: 30px; border-radius: 10px; }
pre { background: #000; color: #4ade80; padding: 15px; border-radius: 6px; overflow-x: auto; }
code { color: #38bdf8; font-weight: bold; }
</style>
</head>
<body>
<div class="box">
    <h1>Auto UPI Payment Gateway API</h1>
    <p>Apni website se niche diye endpoint par call karein. Dynamic QR code URL mil jayega:</p>
    <h3>POST /api/create_order</h3>
    <p>Header: <code>X-API-KEY: sec_live_998877665544332211</code></p>
    <pre>{
  "amount": 100.0,
  "customer_name": "Customer Name",
  "webhook_url": "https://yourwebsite.com/webhook"
}</pre>
    <p>Response me <code>payment_url</code> milega, customer ko us URL par redirect karein.</p>
</div>
</body>
</html>'''

PAYMENT_PAGE_HTML = '''<!DOCTYPE html>
<html>
<head>
    <title>Pay ₹{{ "%.2f"|format(order.amount) }}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://cdn.jsdelivr.net/npm/qrcodejs@1.0.0/qrcode.min.js"></script>
    <style>
        body { font-family: -apple-system, sans-serif; background: #f1f5f9; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; }
        .card { background: white; padding: 25px; border-radius: 14px; box-shadow: 0 10px 25px rgba(0,0,0,0.1); width: 340px; text-align: center; }
        .amt { font-size: 30px; font-weight: bold; color: #16a34a; margin: 8px 0; }
        #qrcode { display: flex; justify-content: center; margin: 15px 0; }
        .btn { display: block; background: #2563eb; color: white; padding: 12px; border-radius: 8px; text-decoration: none; font-weight: bold; }
        .status { margin-top: 15px; font-size: 13px; color: #0284c7; font-weight: 500; }
        .success { display: none; background: #dcfce7; color: #15803d; padding: 20px; border-radius: 10px; }
        .utr-box { margin-top: 15px; border-top: 1px solid #e2e8f0; padding-top: 12px; }
        input { width: 65%; padding: 7px; border: 1px solid #cbd5e1; border-radius: 5px; }
        button { padding: 7px 12px; background: #334155; color: white; border: none; border-radius: 5px; cursor: pointer; }
    </style>
</head>
<body>
    <div class="card" id="payBox">
        <div style="font-size: 13px; color: #64748b;">Order: {{ order.order_id }}</div>
        <div class="amt">₹ {{ "%.2f"|format(order.amount) }}</div>
        <div style="font-size: 12px; color: #64748b;">GPay / PhonePe / Paytm se scan karein</div>
        <div id="qrcode"></div>
        <a href="{{ upi_url }}" class="btn">Pay With UPI App</a>
        <div class="status" id="statusTxt">Payment check ho raha hai... Pay karte hi auto-detect ho jayega</div>
        <div class="utr-box">
            <input type="text" id="utrInp" placeholder="12-digit UTR No.">
            <button onclick="checkNow()">Verify</button>
        </div>
    </div>

    <div class="card success" id="successBox">
        <h2>Payment Verified!</h2>
        <p>Order ID: <b>{{ order.order_id }}</b></p>
        <p>UTR: <span id="utrVal"></span></p>
        <p style="color: #64748b; font-size: 13px;">Auto-redirect ho raha hai...</p>
    </div>

    <script>
        new QRCode(document.getElementById("qrcode"), {
            text: "{{ upi_url }}",
            width: 180,
            height: 180
        });

        const orderId = "{{ order.order_id }}";
        let timer = setInterval(pollStatus, 4000);

        function pollStatus() {
            fetch('/api/check_status/' + orderId)
            .then(r => r.json())
            .then(d => {
                if (d.status === "SUCCESS") showSuccess(d.utr);
            });
        }

        function checkNow() {
            const u = document.getElementById("utrInp").value.trim();
            document.getElementById("statusTxt").innerText = "Gmail me match kiya ja raha hai...";
            fetch('/api/check_status/' + orderId, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ utr: u })
            })
            .then(r => r.json())
            .then(d => {
                if (d.status === "SUCCESS") showSuccess(d.utr);
                else document.getElementById("statusTxt").innerText = d.message;
            });
        }

        function showSuccess(utr) {
            clearInterval(timer);
            document.getElementById("payBox").style.display = "none";
            document.getElementById("successBox").style.display = "block";
            document.getElementById("utrVal").innerText = utr;
        }
    </script>
</body>
</html>'''

@app.route("/", methods=["GET"])
def home():
    return render_template_string(DOCS_HTML)

@app.route("/api/create_order", methods=["POST"])
def api_create_order():
    auth_key = request.headers.get("X-API-KEY")
    if auth_key != GATEWAY_SECRET_KEY:
        return jsonify({"success": False, "error": "Invalid API Key"}), 401

    data = request.get_json(force=True, silent=True) or {}
    amount = data.get("amount")
    customer_name = data.get("customer_name", "Customer")
    customer_email = data.get("customer_email", "")
    webhook_url = data.get("webhook_url", "")

    if not amount or float(amount) <= 0:
        return jsonify({"success": False, "error": "Valid amount zaroori hai"}), 400

    order_id = "ORD_" + uuid.uuid4().hex[:10].upper()
    create_order(order_id, float(amount), customer_name, customer_email, webhook_url)

    payment_url = request.host_url.rstrip("/") + f"/pay/{order_id}"

    return jsonify({
        "success": True,
        "order_id": order_id,
        "amount": float(amount),
        "payment_url": payment_url,
        "status": "PENDING"
    })

@app.route("/pay/<order_id>", methods=["GET"])
def checkout_page(order_id):
    order = get_order(order_id)
    if not order:
        return "Order not found", 404

    upi_payload = f"upi://pay?pa={MERCHANT_UPI_ID}&pn={urllib.parse.quote(MERCHANT_NAME)}&am={order['amount']:.2f}&cu=INR&tn={order_id}"
    return render_template_string(PAYMENT_PAGE_HTML, order=order, upi_url=upi_payload)

@app.route("/api/check_status/<order_id>", methods=["GET", "POST"])
def check_status(order_id):
    order = get_order(order_id)
    if not order:
        return jsonify({"success": False, "error": "Order not found"}), 404

    if order["status"] == "SUCCESS":
        return jsonify({
            "success": True,
            "status": "SUCCESS",
            "utr": order["utr"],
            "amount": order["amount"],
            "message": "Payment already verified"
        })

    submitted_utr = None
    if request.method == "POST":
        post_data = request.get_json(silent=True) or {}
        submitted_utr = post_data.get("utr") or request.form.get("utr")

    result = scan_gmail_for_order(order_id, order["amount"], submitted_utr=submitted_utr)

    if result["success"]:
        return jsonify({
            "success": True,
            "status": "SUCCESS",
            "utr": result.get("utr"),
            "amount": order["amount"],
            "message": result["message"]
        })
    else:
        return jsonify({
            "success": False,
            "status": "PENDING",
            "message": result["message"]
        })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
