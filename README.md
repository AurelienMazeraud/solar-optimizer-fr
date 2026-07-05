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
consommation du foyer, financement, tarifs) et affiche les résultats
(production, autoconsommation, temps de retour, VAN) avec des graphiques
interactifs.

```
streamlit run app.py
```

Cela ouvre l'application dans le navigateur, à l'adresse
`http://localhost:8501`.

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
