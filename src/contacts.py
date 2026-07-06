import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# Base de donnees locale uniquement : jamais transmise a un service tiers,
# jamais commitee dans le depot (voir .gitignore). Sur un hebergement a
# disque ephemere (ex: Streamlit Community Cloud), ce fichier ne survit
# pas a un redeploiement — prevoir un auto-hebergement (NAS, VPS...) pour
# une conservation fiable dans la duree.
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "contacts.db"


def _get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT,
            address TEXT,
            latitude REAL,
            longitude REAL,
            storage_consent INTEGER NOT NULL,
            partner_sharing_consent INTEGER NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def save_contact(first_name, last_name, email, phone, address,
                  latitude, longitude, storage_consent, partner_sharing_consent):
    """Enregistre un contact dans la base locale. storage_consent DOIT etre
    vrai (verifie a l'appel comme dans le formulaire) : c'est la base
    legale (consentement) du traitement. partner_sharing_consent est une
    autorisation distincte et facultative, decochee par defaut, pour un
    eventuel partage ulterieur avec des partenaires du projet — sans elle,
    les coordonnees ne doivent jamais etre transmises a des tiers."""
    if not storage_consent:
        raise ValueError("Le consentement au stockage est obligatoire.")

    conn = _get_connection()
    try:
        conn.execute(
            """
            INSERT INTO contacts (
                created_at, first_name, last_name, email, phone, address,
                latitude, longitude, storage_consent, partner_sharing_consent
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                first_name.strip(),
                last_name.strip(),
                email.strip(),
                (phone or "").strip(),
                (address or "").strip(),
                latitude,
                longitude,
                1 if storage_consent else 0,
                1 if partner_sharing_consent else 0,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def count_contacts():
    """Utilitaire simple pour verifier/tester le contenu de la base."""
    conn = _get_connection()
    try:
        cur = conn.execute("SELECT COUNT(*) FROM contacts")
        return cur.fetchone()[0]
    finally:
        conn.close()
