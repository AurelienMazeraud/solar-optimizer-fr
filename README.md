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

`app.py` propose un parcours pédagogique (chaque section a son encadré
"ℹ️ Pourquoi ces informations ?") : localisation, modules PV, placement des
panneaux sur la toiture, consommation du foyer, batterie optionnelle,
financement, tarifs — puis affiche les résultats (production,
autoconsommation, temps de retour, VAN) avec des graphiques interactifs. La
batterie est simulée heure par heure (charge sur le surplus, décharge sur
le manque, rendement aller-retour) et augmente mécaniquement le taux
d'autoconsommation.

```
streamlit run app.py
```

Cela ouvre l'application dans le navigateur, à l'adresse
`http://localhost:8501`.

### Localisation sur carte

La section "📍 Localisation" propose une recherche d'adresse (géocodage
gratuit via OpenStreetMap/Nominatim, sans clé) et une carte interactive
(clic pour placer le point exact) — les champs latitude/longitude se
mettent à jour automatiquement et restent modifiables à la main. Un vrai
glisser-déposer (drag-and-drop) de la punaise n'est pas fiable avec les
cartes interactives utilisées ici (streamlit-folium ne capture pas les
événements de fin de glissement de façon robuste) : cliquer directement au
bon endroit fait la même chose en un seul geste.

### Repérage automatique du toit (Google Solar API, optionnel)

Dans l'expander "🔎 Repérage automatique du toit", coller une clé Google
Solar API déclenche **automatiquement** (dès qu'une position est choisie,
sans bouton à cliquer) la récupération de l'inclinaison, l'azimut et la
surface des pans de toiture détectés (10 000 requêtes gratuites/mois). Un
bouton "🔄 Relancer la détection" reste disponible pour forcer une nouvelle
tentative (ex : après avoir collé la clé après coup). Google ne fournissant
que la surface de chaque pan (pas sa forme exacte), la largeur/hauteur sont
approximées par un carré équivalent — à ajuster manuellement si les
dimensions réelles sont connues.

### Placement des panneaux sur le toit

La section "🏠 Toiture(s) & placement des panneaux" permet, pour chaque
pan : de saisir sa largeur/hauteur et l'orientation des panneaux
(portrait/paysage), ce qui détermine combien de panneaux tiennent
physiquement dessus (grille colonnes × lignes, limitée à 10×12 cases à
l'écran pour rester lisible sur les très grands toits). Un champ "Nombre
de panneaux souhaité (total)" + bouton "Répartir automatiquement" répartit
ce total au prorata des places disponibles sur chaque pan ; on peut ensuite
affiner en cliquant directement sur les cases de la grille (🟦 = panneau
posé, ⬜ = case vide), ou utiliser "Tout remplir"/"Tout vider" par pan. Le
nombre de panneaux réellement sélectionné (pas une estimation de surface)
est ce qui alimente le calcul de production.

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
- La grille de placement des panneaux affiche au maximum 10×12 cases par
  pan pour rester réactive : au-delà, le nombre réel de places possibles
  est indiqué en texte mais l'affichage est tronqué (le calcul de
  production utilise bien le nombre de panneaux réellement sélectionnés
  dans la grille affichée).
