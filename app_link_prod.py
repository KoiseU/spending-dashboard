
import os, json, secrets
from pathlib import Path
from flask import Flask, jsonify, request, render_template, redirect
from dotenv import load_dotenv

from plaid.configuration import Configuration, Environment
from plaid import ApiClient
from plaid.api import plaid_api
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest

REPO = Path(__file__).resolve().parent
load_dotenv(REPO / ".env")

CLIENT_ID = os.getenv("PLAID_CLIENT_ID")
SECRET    = os.getenv("PLAID_SECRET")
ENV_NAME  = (os.getenv("PLAID_ENV") or "production").lower()

if ENV_NAME not in ("production","sandbox"):
    raise RuntimeError("PLAID_ENV must be 'production' or 'sandbox'")

env_map = {"production": Environment.Production, "sandbox": Environment.Sandbox}
configuration = Configuration(host=env_map[ENV_NAME],
                              api_key={"clientId": CLIENT_ID, "secret": SECRET})
client = plaid_api.PlaidApi(ApiClient(configuration))

CONFIG_DIR   = REPO / "config"
CONFIG_DIR.mkdir(exist_ok=True)
ITEMS_JSON   = CONFIG_DIR / "plaid_items.json"
CURSORS_JSON = CONFIG_DIR / "plaid_cursors.json"

app = Flask(__name__, template_folder=str(REPO / "templates"))

def load_items():
    if ITEMS_JSON.exists():
        return json.loads(ITEMS_JSON.read_text(encoding="utf-8"))
    return {"items": []}

def save_items(obj):
    ITEMS_JSON.write_text(json.dumps(obj, indent=2), encoding="utf-8")

def load_cursors():
    if CURSORS_JSON.exists():
        return json.loads(CURSORS_JSON.read_text(encoding="utf-8"))
    return {"transactions": {}}

def save_cursors(obj):
    CURSORS_JSON.write_text(json.dumps(obj, indent=2), encoding="utf-8")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/create_link_token", methods=["POST"])
def create_link_token():
    # one-off user id for Link session
    user_id = secrets.token_hex(8)
    # resolve enum variants for Products
    try:
        prod_tx = Products("transactions")
    except Exception:
        prod_tx = Products.TRANSACTIONS

    req = LinkTokenCreateRequest(
        user=LinkTokenCreateRequestUser(client_user_id=user_id),
        client_name="Blue Lantern Dashboard",
        products=[prod_tx],
        country_codes=[CountryCode("US")],
        language="en",
    )
    resp = client.link_token_create(req)
    return jsonify({"link_token": resp["link_token"]})

@app.route("/exchange_public_token", methods=["POST"])
def exchange_public_token():
    data = request.get_json(force=True)
    public_token = data.get("public_token")
    exch = client.item_public_token_exchange(
        ItemPublicTokenExchangeRequest(public_token=public_token)
    )

    item_id = exch["item_id"]
    access_token = exch["access_token"]

    # persist to items + init cursor
    items = load_items()
    items["items"].append({"item_id": item_id, "access_token": access_token})
    save_items(items)

    cursors = load_cursors()
    cursors["transactions"][item_id] = ""     # first sync
    save_cursors(cursors)

    return jsonify({"ok": True, "item_id": item_id})

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
