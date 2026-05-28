from flask import Flask, Response

app = Flask(__name__)

HTML = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>LK Failover</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { margin: 0; min-height: 100vh; font-family: Arial, sans-serif; background: #f4f6f8; color: #1f2933; display: flex; align-items: center; justify-content: center; padding: 24px; text-align: center; }
    .box { width: 100%; max-width: 560px; background: #fff; padding: 42px 34px; border: 1px solid #e5e7eb; border-radius: 22px; box-shadow: 0 18px 45px rgba(15, 23, 42, 0.08); }
    h1 { margin: 0 0 14px; font-size: 32px; line-height: 1.15; }
    p { margin: 0 auto 10px; max-width: 460px; color: #5f6b7a; font-size: 17px; line-height: 1.6; }
  </style>
</head>
<body>
  <main class="box">
    <h1>LK Failover activo</h1>
    <p>Este servicio Cloud Run esta funcionando correctamente.</p>
  </main>
</body>
</html>"""


@app.get("/")
def home():
    return Response(HTML, mimetype="text/html")


@app.get("/healthz")
def healthz():
    return "ok", 200


@app.get("/<path:any_path>")
def catch_all(any_path):
    return Response(HTML, mimetype="text/html")
