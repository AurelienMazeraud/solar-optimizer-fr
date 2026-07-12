import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# Base de donnees locale uniquement : jamais transmise a un service tiers,
# jamais commitee dans le depot (voir .gitignore, meme repertoire data/ que
# contacts.db). Sur un hebergement a disque ephemere (ex: Streamlit
# Community Cloud), ce fichier ne survit pas a un redeploiement - prevoir
# un auto-hebergement (NAS, VPS...) pour une conservation fiable.
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "community.db"

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"


def _get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS producer_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            name TEXT,
            email TEXT,
            phone TEXT,
            address TEXT,
            latitude REAL,
            longitude REAL,
            annual_production_kwh REAL NOT NULL,
            installed_kw REAL,
            status TEXT NOT NULL DEFAULT 'pending',
            admin_note TEXT,
            decided_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS consumer_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            name TEXT,
            email TEXT,
            phone TEXT,
            address TEXT,
            pdl TEXT,
            identity TEXT,
            annual_consumption_kwh REAL NOT NULL,
            annual_acc_kwh REAL,
            estimated_savings_eur REAL,
            invoice_extract_json TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            admin_note TEXT,
            decided_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS community_targets (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            production_target_kwh REAL NOT NULL DEFAULT 10000,
            consumption_target_kwh REAL NOT NULL DEFAULT 5000
        )
        """
    )
    conn.execute(
        "INSERT OR IGNORE INTO community_targets (id, production_target_kwh, consumption_target_kwh) "
        "VALUES (1, 10000, 5000)"
    )
    conn.commit()
    return conn


def _now():
    return datetime.now(timezone.utc).isoformat()


def submit_producer(name, email, phone, address, latitude, longitude,
                     annual_production_kwh, installed_kw=None):
    """Enregistre une soumission de production annuelle, en attente de
    validation par un-e administrateur-ice (statut 'pending'). Ne compte
    dans les totaux de la communaute qu'une fois approuvee."""
    if annual_production_kwh is None or annual_production_kwh <= 0:
        raise ValueError("La production annuelle doit etre superieure a 0.")

    conn = _get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO producer_submissions (
                created_at, name, email, phone, address, latitude, longitude,
                annual_production_kwh, installed_kw, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _now(), (name or "").strip(), (email or "").strip(),
                (phone or "").strip(), (address or "").strip(),
                latitude, longitude, float(annual_production_kwh),
                float(installed_kw) if installed_kw else None,
                STATUS_PENDING,
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def submit_consumer(name, email, phone, address, pdl, identity,
                     annual_consumption_kwh, annual_acc_kwh=None,
                     estimated_savings_eur=None, invoice_extract=None):
    """Enregistre une soumission de consommation annuelle (typiquement
    issue d'une facture EDF analysee), en attente de validation par un-e
    administrateur-ice. invoice_extract (dict) est stocke tel quel en JSON
    pour tracabilite/verification manuelle."""
    if annual_consumption_kwh is None or annual_consumption_kwh <= 0:
        raise ValueError("La consommation annuelle doit etre superieure a 0.")

    conn = _get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO consumer_submissions (
                created_at, name, email, phone, address, pdl, identity,
                annual_consumption_kwh, annual_acc_kwh, estimated_savings_eur,
                invoice_extract_json, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _now(), (name or "").strip(), (email or "").strip(),
                (phone or "").strip(), (address or "").strip(),
                (pdl or "").strip(), (identity or "").strip(),
                float(annual_consumption_kwh),
                float(annual_acc_kwh) if annual_acc_kwh is not None else None,
                float(estimated_savings_eur) if estimated_savings_eur is not None else None,
                json.dumps(invoice_extract, ensure_ascii=False) if invoice_extract else None,
                STATUS_PENDING,
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _rows_to_dicts(rows):
    return [dict(row) for row in rows]


def list_producers(status=None):
    conn = _get_connection()
    try:
        if status:
            cur = conn.execute(
                "SELECT * FROM producer_submissions WHERE status = ? ORDER BY created_at DESC",
                (status,),
            )
        else:
            cur = conn.execute("SELECT * FROM producer_submissions ORDER BY created_at DESC")
        return _rows_to_dicts(cur.fetchall())
    finally:
        conn.close()


def list_consumers(status=None):
    conn = _get_connection()
    try:
        if status:
            cur = conn.execute(
                "SELECT * FROM consumer_submissions WHERE status = ? ORDER BY created_at DESC",
                (status,),
            )
        else:
            cur = conn.execute("SELECT * FROM consumer_submissions ORDER BY created_at DESC")
        return _rows_to_dicts(cur.fetchall())
    finally:
        conn.close()


def set_producer_status(submission_id, status, admin_note=None):
    if status not in (STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED):
        raise ValueError(f"Statut invalide : {status}")
    conn = _get_connection()
    try:
        conn.execute(
            "UPDATE producer_submissions SET status = ?, admin_note = ?, decided_at = ? WHERE id = ?",
            (status, admin_note, _now(), submission_id),
        )
        conn.commit()
    finally:
        conn.close()


def set_consumer_status(submission_id, status, admin_note=None):
    if status not in (STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED):
        raise ValueError(f"Statut invalide : {status}")
    conn = _get_connection()
    try:
        conn.execute(
            "UPDATE consumer_submissions SET status = ?, admin_note = ?, decided_at = ? WHERE id = ?",
            (status, admin_note, _now(), submission_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_approved_totals():
    """Renvoie (production_totale_kwh, energie_acc_totale_kwh), calcules
    uniquement a partir des soumissions approuvees par un-e administrateur-ice.
    energie_acc_totale_kwh represente l'energie consommee par les membres qui
    a ete echangee au travers de l'autoconsommation collective (approximee,
    dans cette premiere version, par la valeur declaree/estimee a la
    soumission -- a affiner avec de vraies donnees d'allocation ACC)."""
    conn = _get_connection()
    try:
        prod = conn.execute(
            "SELECT COALESCE(SUM(annual_production_kwh), 0) FROM producer_submissions WHERE status = ?",
            (STATUS_APPROVED,),
        ).fetchone()[0]
        acc = conn.execute(
            "SELECT COALESCE(SUM(COALESCE(annual_acc_kwh, annual_consumption_kwh)), 0) "
            "FROM consumer_submissions WHERE status = ?",
            (STATUS_APPROVED,),
        ).fetchone()[0]
        return float(prod), float(acc)
    finally:
        conn.close()


def get_targets():
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT production_target_kwh, consumption_target_kwh FROM community_targets WHERE id = 1"
        ).fetchone()
        return float(row["production_target_kwh"]), float(row["consumption_target_kwh"])
    finally:
        conn.close()


def set_targets(production_target_kwh, consumption_target_kwh):
    conn = _get_connection()
    try:
        conn.execute(
            "UPDATE community_targets SET production_target_kwh = ?, consumption_target_kwh = ? WHERE id = 1",
            (float(production_target_kwh), float(consumption_target_kwh)),
        )
        conn.commit()
    finally:
        conn.close()
