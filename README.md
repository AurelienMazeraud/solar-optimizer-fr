# solar-optimizer-fr

Simulation de production photovoltaïque, autoconsommation et retour sur
investissement — pensé pour évaluer sa situation avant de rejoindre ou
constituer une communauté d'autoconsommation collective.

## Installation

```
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

## Utilisation en ligne de commande

`main.py` lit `config/maison.yaml` et affiche un résumé (production,
consommation, autoconsommation, économies) dans le terminal, avec un
graphique de production mensuelle.

```
python main.py
```

## Interface web (Streamlit)

`app.py` propose un formulaire (localisation, toiture(s), modules PV,
consommation du foyer, batterie optionnelle, financement, tarifs) et
affiche les résultats (production, autoconsommation, temps de retour, VAN)
avec des graphiques interactifs. La batterie est simulée heure par heure
(charge sur le surplus, décharge sur le manque, rendement aller-retour) et
augmente mécaniquement le taux d'autoconsommation.

```
streamlit run app.py
```

Cela ouvre l'application dans le navigateur, à l'adresse
`http://localhost:8501`.

### Repérage automatique du toit (Google Solar API, optionnel)

Dans l'expander "🔎 Repérage automatique du toit", coller une clé Google
Solar API pré-remplit l'inclinaison, l'azimut et la surface des pans de
toiture détectés à l'adresse renseignée (10 000 requêtes gratuites/mois).

Pour ne jamais committer la clé par erreur :

```
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

puis remplacer la valeur par la vraie clé dans ce fichier local
(`.streamlit/secrets.toml` est déjà exclu par `.gitignore`). Sur Streamlit
Community Cloud, la clé se configure plutôt dans les "Secrets" de l'app,
depuis le tableau de bord — jamais dans le dépôt.

### Intégrer l'app dans une page internet

Quelques options, du plus simple au plus autonome :

- **Streamlit Community Cloud** (gratuit) : héberger le dépôt sur GitHub
  et le déployer sur [share.streamlit.io](https://share.streamlit.io).
  Cela donne une URL publique (`https://<app>.streamlit.app`) que l'on
  peut intégrer dans une page existante via une balise `<iframe>`.
- **Auto-hébergement** : lancer `streamlit run app.py` sur un serveur
  (VPS, Raspberry Pi...) et exposer le port via un reverse proxy
  (Nginx/Caddy) sur un sous-domaine, par exemple
  `simulateur.mondomaine.fr`.
- **Intégration directe** : si la page internet est elle-même construite
  avec un framework Python (Flask/Django), l'app Streamlit reste un
  processus séparé — l'intégration se fait via iframe ou lien, pas par
  import direct du code.

### Limites connues

- Le profil de consommation est un modèle simplifié (charge de base +
  chauffe-eau + pompe à chaleur + véhicule électrique), pas une mesure
  réelle. Utiliser le champ « consommation annuelle connue » pour recaler
  sur un relevé Linky réel améliore la précision globale, sans changer la
  forme horaire du profil.
- Les tarifs de revente proposés (obligation d'achat, autoconsommation
  collective) sont des valeurs indicatives à vérifier/ajuster selon le
  contrat réel — ces tarifs réglementés évoluent régulièrement.
- La simulation traite un foyer à la fois ; il n'y a pas (encore)
  d'agrégation multi-participants façon autoconsommation collective
  réelle (clé de répartition, plusieurs points de production/consommation
  dans un même périmètre).
- Les données météo viennent de l'API PVGIS (Commission européenne) : une
  connexion internet est nécessaire au premier calcul pour chaque
  localisation (les résultats sont ensuite mis en cache).
