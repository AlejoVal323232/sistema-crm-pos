from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from werkzeug.security import generate_password_hash, check_password_hash
import mysql.connector

# ====== CONEXIÓN A MYSQL: escribe aquí tu clave de Workbench ======
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '12345',
    'database': 'sistema_crm_pos'
}
# ===================================================================

app = Flask(__name__)
app.secret_key = 'cambia-esta-clave'

# Configuración de las pantallas CRUD: (campo, etiqueta, tipo, opciones)
ENTIDADES = {
    'clientes': {
        'tabla': 'cliente', 'pk': 'id_cliente', 'titulo': 'Clientes',
        'campos': [('nombre', 'Nombre', 'text'), ('email', 'Email', 'email'),
                   ('telefono', 'Teléfono', 'text'), ('direccion', 'Dirección', 'text'),
                   ('ciudad', 'Ciudad', 'text'), ('pais', 'País', 'text')],
        'mostrar': ['id_cliente', 'nombre', 'email', 'telefono', 'ciudad', 'pais']
    },
    'productos': {
        'tabla': 'producto', 'pk': 'id_producto', 'titulo': 'Productos', 'admin': True,
        'campos': [('nombre_producto', 'Nombre', 'text'), ('descripcion', 'Descripción', 'text'),
                   ('precio', 'Precio', 'decimal'), ('stock', 'Stock', 'number')],
        'mostrar': ['id_producto', 'nombre_producto', 'descripcion', 'precio', 'stock']
    },
    'usuarios': {
        'tabla': 'usuarios', 'pk': 'id_usuario', 'titulo': 'Usuarios', 'admin': True,
        'campos': [('nombre_usuario', 'Usuario', 'text'), ('email', 'Email', 'email'),
                   ('contrasena', 'Contraseña', 'password'),
                   ('rol', 'Rol', 'select', ['Administrador', 'Vendedor']),
                   ('estado', 'Estado', 'select', ['Activo', 'Inactivo'])],
        'mostrar': ['id_usuario', 'nombre_usuario', 'email', 'rol', 'estado']
    }
}


def conectar():
    return mysql.connector.connect(**DB_CONFIG)


def consultar(sql, params=(), uno=False):
    con = conectar()
    cur = con.cursor(dictionary=True)
    cur.execute(sql, params)
    resultado = cur.fetchone() if uno else cur.fetchall()
    cur.close()
    con.close()
    return resultado


def ejecutar(sql, params=()):
    con = conectar()
    cur = con.cursor()
    cur.execute(sql, params)
    con.commit()
    cur.close()
    con.close()


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'id_usuario' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper


def obtener(entidad):
    e = ENTIDADES.get(entidad)
    if not e:
        abort(404)
    if e.get('admin') and session['rol'] != 'Administrador':
        abort(403)
    return e


def mensaje_error(err):
    if err.errno == 1062:
        return 'Ya existe un registro con ese email o nombre de usuario.'
    if err.errno == 1451:
        return 'No se puede eliminar: el registro tiene ventas asociadas.'
    return str(err)


# ---------- Acceso ----------
@app.route('/setup', methods=['GET', 'POST'])
def setup():
    if consultar("SELECT COUNT(*) AS n FROM usuarios", uno=True)['n']:
        return redirect(url_for('login'))
    if request.method == 'POST':
        try:
            ejecutar("INSERT INTO usuarios (nombre_usuario, email, contrasena, rol) VALUES (%s, %s, %s, 'Administrador')",
                     (request.form['nombre_usuario'], request.form['email'],
                      generate_password_hash(request.form['contrasena'])))
            flash('Administrador creado. Ya puedes iniciar sesión.', 'success')
            return redirect(url_for('login'))
        except mysql.connector.Error as err:
            flash(mensaje_error(err), 'danger')
    return render_template('login.html', setup=True)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if not consultar("SELECT COUNT(*) AS n FROM usuarios", uno=True)['n']:
        return redirect(url_for('setup'))
    if request.method == 'POST':
        u = consultar("SELECT * FROM usuarios WHERE nombre_usuario = %s AND estado = 'Activo'",
                      (request.form['nombre_usuario'],), uno=True)
        if u and check_password_hash(u['contrasena'], request.form['contrasena']):
            session['id_usuario'] = u['id_usuario']
            session['nombre'] = u['nombre_usuario']
            session['rol'] = u['rol']
            return redirect(url_for('index'))
        flash('Usuario o contraseña incorrectos.', 'danger')
    return render_template('login.html', setup=False)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ---------- Inicio ----------
@app.route('/')
@login_required
def index():
    datos = consultar("""SELECT
        (SELECT COUNT(*) FROM cliente) AS clientes,
        (SELECT COUNT(*) FROM producto) AS productos,
        (SELECT COUNT(*) FROM venta) AS ventas,
        (SELECT COALESCE(SUM(total), 0) FROM venta) AS total_vendido""", uno=True)
    bajo_stock = consultar("SELECT nombre_producto, stock FROM producto WHERE stock <= 5 ORDER BY stock")
    return render_template('index.html', d=datos, bajo_stock=bajo_stock)


# ---------- CRUD genérico (clientes, productos, usuarios) ----------
@app.route('/<entidad>')
@login_required
def listar(entidad):
    e = obtener(entidad)
    filas = consultar(f"SELECT {', '.join(e['mostrar'])} FROM {e['tabla']} ORDER BY {e['pk']}")
    return render_template('tabla.html', e=e, entidad=entidad, filas=filas)


@app.route('/<entidad>/nuevo', methods=['GET', 'POST'])
@app.route('/<entidad>/<int:id>/editar', methods=['GET', 'POST'])
@login_required
def formulario(entidad, id=None):
    e = obtener(entidad)
    registro = {}
    if id:
        registro = consultar(f"SELECT * FROM {e['tabla']} WHERE {e['pk']} = %s", (id,), uno=True)
        if not registro:
            abort(404)

    if request.method == 'POST':
        datos = {}
        for c in e['campos']:
            valor = request.form.get(c[0], '').strip()
            if c[2] == 'password':
                if not valor and id:
                    continue
                valor = generate_password_hash(valor)
            datos[c[0]] = valor or None
        try:
            if id:
                sets = ', '.join(f"{k} = %s" for k in datos)
                ejecutar(f"UPDATE {e['tabla']} SET {sets} WHERE {e['pk']} = %s", (*datos.values(), id))
            else:
                marcas = ', '.join(['%s'] * len(datos))
                ejecutar(f"INSERT INTO {e['tabla']} ({', '.join(datos)}) VALUES ({marcas})", tuple(datos.values()))
            flash('Registro guardado.', 'success')
            return redirect(url_for('listar', entidad=entidad))
        except mysql.connector.Error as err:
            flash(mensaje_error(err), 'danger')
            registro = request.form

    return render_template('form.html', e=e, entidad=entidad, registro=registro)


@app.route('/<entidad>/<int:id>/eliminar', methods=['POST'])
@login_required
def eliminar(entidad, id):
    e = obtener(entidad)
    if entidad == 'usuarios' and id == session['id_usuario']:
        flash('No puedes eliminar tu propio usuario.', 'warning')
        return redirect(url_for('listar', entidad=entidad))
    try:
        ejecutar(f"DELETE FROM {e['tabla']} WHERE {e['pk']} = %s", (id,))
        flash('Registro eliminado.', 'success')
    except mysql.connector.Error as err:
        flash(mensaje_error(err), 'danger')
    return redirect(url_for('listar', entidad=entidad))


# ---------- Reporte de clientes por nacionalidad ----------
@app.route('/clientes/reporte')
@login_required
def reporte_clientes():
    filas = consultar("""SELECT id_cliente, nombre, email, telefono, ciudad, pais, fecha_registro
                         FROM cliente ORDER BY pais, nombre""")
    return render_template('reporte_clientes.html', filas=filas, fecha=datetime.now())


# ---------- Ventas y facturas ----------
@app.route('/ventas/nueva', methods=['GET', 'POST'])
@login_required
def nueva_venta():
    clientes = consultar("SELECT id_cliente, nombre FROM cliente ORDER BY nombre")
    productos = consultar("SELECT * FROM producto WHERE stock > 0 ORDER BY nombre_producto")

    if request.method == 'POST':
        con = conectar()
        cur = con.cursor()
        try:
            items = []
            total = 0
            for p in productos:
                cantidad = int(request.form.get(f"cant_{p['id_producto']}") or 0)
                if cantidad > 0:
                    subtotal = p['precio'] * cantidad
                    items.append((p, cantidad, subtotal))
                    total += subtotal
            if not items:
                raise ValueError('Selecciona al menos un producto.')

            for p, cantidad, subtotal in items:
                cur.execute("SELECT stock FROM producto WHERE id_producto = %s FOR UPDATE", (p['id_producto'],))
                if cur.fetchone()[0] < cantidad:
                    raise ValueError(f"Stock insuficiente para {p['nombre_producto']}.")

            cur.execute("INSERT INTO venta (id_cliente, id_usuario, total) VALUES (%s, %s, %s)",
                        (request.form['id_cliente'], session['id_usuario'], total))
            id_venta = cur.lastrowid

            for p, cantidad, subtotal in items:
                # el stock lo descuenta el trigger de MySQL al insertar el detalle
                cur.execute("""INSERT INTO detalle_venta (id_venta, id_producto, cantidad, precio_unitario, subtotal)
                               VALUES (%s, %s, %s, %s, %s)""",
                            (id_venta, p['id_producto'], cantidad, p['precio'], subtotal))

            cur.execute("""INSERT INTO historial_facturas (numero_factura, id_venta, id_cliente, monto_total, metodo_pago)
                           VALUES (%s, %s, %s, %s, %s)""",
                        (f"F-{id_venta:06d}", id_venta, request.form['id_cliente'], total, request.form['metodo_pago']))
            con.commit()
            flash('Venta registrada.', 'success')
            return redirect(url_for('factura', id_venta=id_venta))
        except (ValueError, mysql.connector.Error) as err:
            con.rollback()
            flash(str(err), 'danger')
        finally:
            cur.close()
            con.close()

    return render_template('nueva_venta.html', clientes=clientes, productos=productos)


@app.route('/facturas')
@login_required
def facturas():
    filas = consultar("""SELECT f.id_venta, f.numero_factura, f.fecha_emision, c.nombre AS cliente,
                                u.nombre_usuario AS vendedor, f.metodo_pago, f.monto_total
                         FROM historial_facturas f
                         JOIN cliente c ON c.id_cliente = f.id_cliente
                         JOIN venta v ON v.id_venta = f.id_venta
                         JOIN usuarios u ON u.id_usuario = v.id_usuario
                         ORDER BY f.id_factura DESC""")
    return render_template('facturas.html', filas=filas)


@app.route('/facturas/<int:id_venta>')
@login_required
def factura(id_venta):
    f = consultar("""SELECT f.*, c.nombre, c.email, c.direccion, c.ciudad, u.nombre_usuario AS vendedor
                     FROM historial_facturas f
                     JOIN cliente c ON c.id_cliente = f.id_cliente
                     JOIN venta v ON v.id_venta = f.id_venta
                     JOIN usuarios u ON u.id_usuario = v.id_usuario
                     WHERE f.id_venta = %s""", (id_venta,), uno=True)
    if not f:
        abort(404)
    detalle = consultar("""SELECT p.nombre_producto, d.cantidad, d.precio_unitario, d.subtotal
                           FROM detalle_venta d JOIN producto p ON p.id_producto = d.id_producto
                           WHERE d.id_venta = %s""", (id_venta,))
    return render_template('factura.html', f=f, detalle=detalle)


if __name__ == '__main__':
    app.run(debug=True)
