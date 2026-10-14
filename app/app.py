import logging
import mimetypes
import os
import subprocess
import tempfile

from flask import Flask, Response, redirect, render_template, request, session

import config
import db

# Boilerplate to set up the web server and logger.
# Server logs are written to /root/admin.log.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

app = Flask(__name__)
app.teardown_appcontext(db.close_connection)
# A Flask-specific setting which allows it to handle authentication itself.
# We don't need to edit this.
app.secret_key = config.SECRET_KEY

# Re-read templates from disk when they change.
# This allows the server to update immidiately as we make changes, without needing to be restarted.
app.config["TEMPLATES_AUTO_RELOAD"] = True

# The file path where we write product images to disk.
# Images are eventually stored in the database, but we often need to write them to the disk first to resize them.
PRODUCT_IMAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "images")


def get_current_admin():
    """Return the username of the logged-in admin, or None if the user is not logged in.
    This uses Flask's built-in "session" library, so we know it's secure."""
    username = session.get("admin")
    if not username:
        return None

    # Make sure the account actually exists in the database.
    admin = db.query_one("SELECT username FROM admin_users WHERE username = %s", (username,))
    return admin["username"] if admin else None


def require_admin():
    """Return the current admin, or None if nobody is logged in."""
    return get_current_admin()


@app.route("/", methods=["GET"])
def index():
    """The landing page, which lists an overview of the products and recent orders."""
    if not require_admin():
        return redirect("/login")

    counts = {
        "products": db.query_one("SELECT COUNT(*) AS count FROM products")["count"],
        "users": db.query_one("SELECT COUNT(*) AS count FROM users")["count"],
        "orders": db.query_one("SELECT COUNT(*) AS count FROM orders")["count"],
    }
    recent_orders = db.query(
        "SELECT id, username, total, status, created_at "
        "FROM orders ORDER BY id DESC LIMIT 10"
    )
    return render_template("index.html", counts=counts, recent_orders=recent_orders)


@app.route("/product-image/<filename>", methods=["GET"])
def product_image(filename):
    """Serve a product photo out of the database.

    The same photos the shop shows. They are kept in the database rather than
    on either machine's disk, so that a photo uploaded here is immediately
    visible over there -- see save_photo_to_database.
    """
    if not require_admin():
        return redirect("/login")

    row = db.query_one("SELECT data FROM product_images WHERE filename = %s", (filename,))
    if row is None:
        return render_template("error.html", error="That image does not exist"), 404

    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return Response(row["data"], mimetype=content_type)


@app.route("/products", methods=["GET"])
def products_list():
    """Every product in the shop, with a link to edit them."""
    if not require_admin():
        return redirect("/login")

    products = db.query("SELECT * FROM products ORDER BY id")
    return render_template("products.html", products=products)


@app.route("/products/new", methods=["GET"])
def product_new_get():
    """The "add a product" form."""
    if not require_admin():
        return redirect("/login")
    return render_template("product_new.html")


def save_product_photo(photo):
    """Saves a new product photo to the disk, if an admin creates one."""
    # Create the directory to save the photo, if it doesn't already exist
    os.makedirs(PRODUCT_IMAGE_DIR, exist_ok=True)
    filename = photo.filename

    log.info("product photo %s uploaded by %s", filename, require_admin())

    # Save the original photo as uploaded: this may be too large, so we will resize it
    # and delete the original afterwards.
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        photo.save(tmp.name)
        tmp_path = tmp.name

    # Resize the photo to 512x512 pixels, the size every product photo in the
    # shop uses, so the grid stays even.
    # This uses the imagemagick convert tool to do the resizing.
    resized_photo_path = os.path.join(PRODUCT_IMAGE_DIR, filename)
    subprocess.getoutput(f"convert {tmp_path} -resize 512x512 {resized_photo_path}")

    # Delete the original photo
    os.remove(tmp_path)

    # Save the photo to the database, where it can be displayed by the storefront.
    save_photo_to_database(filename, resized_photo_path)
    return filename


def save_photo_to_database(filename, path):
    """Copy a photo into the database so the storefront can display it."""
    try:
        with open(path, "rb") as handle:
            data = handle.read()
        db.execute(
            "INSERT INTO product_images (filename, data) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE data = VALUES(data)",
            (filename, data),
        )
        log.info("published photo %s to the shop (%s bytes)", filename, len(data))
    except Exception as e:
        log.warning("could not publish photo %s to the shop: %s", filename, e)


@app.route("/products/new", methods=["POST"])
def product_new_post():
    """Add a new product to the shop."""
    if not require_admin():
        return redirect("/login")

    name = request.form.get("name")
    description = request.form.get("description", "")
    price = request.form.get("price", type=int)

    if not name or price is None:
        return render_template("error.html", error="A name and price are both required")

    photo = request.files.get("photo")
    if photo and photo.filename:
        image = save_product_photo(photo) 
    else:
        image = ""

    product_id = db.execute(
        "INSERT INTO products (image, name, description, price) VALUES (%s, %s, %s, %s)",
        (image, name, description, price),
    )

    log.info("product %s (%s) created by %s", product_id, name, require_admin())
    return redirect(f"/products/{product_id}")


@app.route("/products/<int:product_id>", methods=["GET"])
def product_edit_get(product_id):
    """The edit form for a single product."""
    if not require_admin():
        return redirect("/login")

    product = db.query_one("SELECT * FROM products WHERE id = %s", (product_id,))
    if product is None:
        return render_template("error.html", error="That product does not exist"), 404

    return render_template("product_edit.html", product=product)


@app.route("/products/<int:product_id>", methods=["POST"])
def product_edit_post(product_id):
    """Save changes to a product."""
    if not require_admin():
        return redirect("/login")

    image = request.form.get("image", "")
    name = request.form.get("name")
    description = request.form.get("description", "")
    price = request.form.get("price", type=int)

    if not name or price is None:
        return render_template("error.html", error="A name and price are both required")

    db.execute(
        "UPDATE products SET image = %s, name = %s, description = %s, price = %s WHERE id = %s",
        (image, name, description, price, product_id),
    )

    log.info("product %s updated by %s, price now %s", product_id, require_admin(), price)
    return redirect(f"/products/{product_id}")


@app.route("/users", methods=["GET"])
def users_list():
    """Show every customer, including their balance and how many orders they've placed."""
    if not require_admin():
        return redirect("/login")

    rows = db.query(
        "SELECT u.username, u.email, u.balance, "
        "(SELECT COUNT(*) FROM orders o WHERE o.username = u.username) AS order_count "
        "FROM users u ORDER BY u.username"
    )
    return render_template("users.html", users=rows)


@app.route("/users/<username>", methods=["GET"])
def user_detail(username):
    """A single customer's profile and order history."""
    if not require_admin():
        return redirect("/login")

    user = db.query_one("SELECT * FROM users WHERE username = %s", (username,))
    if user is None:
        return render_template("error.html", error="That customer does not exist"), 404

    orders = db.query(
        "SELECT * FROM orders WHERE username = %s ORDER BY id DESC", (username,)
    )
    # Replace "\n" characters with HTML <br> tags so they actually display as newlines.
    address_html = (user["address"] or "").replace("\n", "<br>")

    log.info("customer record %s opened by %s, ship-to %s",
             username, require_admin(), user["address"])

    return render_template(
        "user_detail.html", user=user, orders=orders, address_html=address_html
    )


@app.route("/users/<username>/reset_password", methods=["POST"])
def reset_user_password(username):
    """Resets a customer's password on their behalf. The support team uses this
    when a user forgets their password.
    """
    if not require_admin():
        return redirect("/login")

    new_password = request.form.get("new_password", "")
    if not new_password:
        return render_template("error.html", error="A new password is required")

    user = db.query_one("SELECT username FROM users WHERE username = %s", (username,))
    if user is None:
        return render_template("error.html", error="That customer does not exist"), 404

    db.execute(
        "UPDATE users SET password = %s WHERE username = %s",
        (new_password, username),
    )

    log.info("password reset for %s by %s", username, require_admin())
    return redirect(f"/users/{username}")


@app.route("/search", methods=["GET", "POST"])
def search():
    """Look up a customer by name, email, or shipping address.

    /users already lists every customer, but this makes it much easier to quickly
    find the details for a specific account.
    """
    if not require_admin():
        return redirect("/login")

    query = request.values.get("q", "").strip()
    results = []
    if query:
        log.info("customer search for %s by %s", query, require_admin())
        results = db.query(
            "SELECT username, email, address, balance FROM users WHERE "
            f"username LIKE '%{query}%' OR email LIKE '%{query}%' OR address LIKE '%{query}%'"
        )
    return render_template("search.html", query=query, results=results)


@app.route("/login", methods=["GET"])
def login_get():
    """The admin login page."""
    return render_template("login.html")


@app.route("/login", methods=["POST"])
def login_post():
    """Log an admin in."""
    username = request.form.get("username", "")
    password = request.form.get("password", "")

    if not username or not password:
        return render_template("error.html", error="Username and password are both required")

    log.info("admin login attempt for %s", username)

    admin = db.query_one(
        "SELECT * FROM admin_users WHERE username = "
        f"'{username}' AND password = '{password}'"
    )
    if admin is None:
        return render_template("error.html", error="Invalid username or password")

    log.info("admin session opened for %s", admin["username"])

    session["admin"] = admin["username"]
    return redirect("/")


@app.route("/logout", methods=["GET"])
def logout():
    """Log the current admin out."""
    log.info("admin session closed for %s", get_current_admin())

    session.clear()
    return redirect("/login")


@app.context_processor
def inject_branding():
    """Makes the store's name and colors available to every template."""

    def readable_text(hex_color):
        """Returns either black or white, whichever is easier to read for the given color hex_color."""
        try:
            value = int(hex_color.lstrip("#"), 16)
        except ValueError:
            return "#ffffff"
        r, g, b = (value >> 16) & 255, (value >> 8) & 255, value & 255
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return "#222222" if luminance > 0.55 else "#ffffff"

    return {
        "store_name": config.STORE_NAME,
        "primary_color": config.PRIMARY_COLOR,
        "accent_color": config.ACCENT_COLOR,
        "primary_text": readable_text(config.PRIMARY_COLOR),
        "accent_text": readable_text(config.ACCENT_COLOR),
        "current_admin": get_current_admin(),
    }

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)

