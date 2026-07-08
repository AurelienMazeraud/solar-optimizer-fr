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
"ℹ️ Pourquoi ces informations ?") : choix du profil, localisation, modules PV,
répartition des panneaux sur la toiture, consommation du foyer, batterie
optionnelle, financement, tarifs — puis affiche les résultats (production,
autoconsommation, temps de retour, VAN) avec des graphiques interactifs. La
batterie est simulée heure par heure (charge sur le surplus, décharge sur
le manque, rendement aller-retour) et augmente mécaniquement le taux
d'autoconsommation.

### Deux profils

En haut de page, un sélecteur "Quel est ton profil ?" propose deux
parcours :

- **Je simule un nouveau projet** : parcours complet (détection du toit,
  modules PV, répartition des panneaux) qui simule la production heure par
  heure à partir de données météo PVGIS.
- **J'ai déjà une installation — j'entre mes données réelles** : masque les
  sections de simulation physique (détection du toit, modules PV,
  répartition des panneaux, batterie) et affiche à la place un bloc
  "Vos données réelles" où l'on saisit directement la consommation
  annuelle, la production annuelle et — si connue — l'énergie
  injectée/revendue (sinon estimée par `max(production − consommation, 0)`).
  Ces chiffres viennent typiquement d'une facture EDF annuelle, de l'appli
  de monitoring de l'onduleur, ou d'un relevé Linky. Les sections
  Investissement/financement et Tarifs restent communes aux deux profils,
  ce qui permet d'estimer le retour sur investissement réel d'une
  installation déjà posée.

```
streamlit run app.py
```

Cela ouvre l'application dans le navigateur, à l'adresse
`http://localhost:8501`.

### Localisation sur carte

La section "📍 Localisation" propose une recherche d'adresse (géocodage
gratuit via OpenStreetMap/Nominatim, sans clé) et une carte interactive
(clic pour placer le point exact, bascule vue satellite/plan via l'icône
en haut à droite) — les champs latitude/longitude se mettent à jour
automatiquement et restent modifiables à la main. Le marqueur se
repositionne immédiatement après un clic (un rerun forcé évite le
décalage d'un cycle qui donnait l'impression que la carte mettait du
temps à réagir). Un vrai glisser-déposer (drag-and-drop) de la punaise
n'est pas fiable avec les cartes interactives utilisées ici
(streamlit-folium ne capture pas les événements de fin de glissement de
façon robuste) : cliquer directement au bon endroit fait la même chose en
un seul geste.

### Repérage automatique du toit (Google Solar API, optionnel)

Dans l'expander "🔎 Repérage automatique du toit", coller une clé Google
Solar API déclenche **automatiquement** (dès qu'une position est choisie,
sans bouton à cliquer) la récupération de l'inclinaison, l'azimut et la
surface des pans de toiture détectés (10 000 requêtes gratuites/mois). Les
pans détectés s'affichent directement sur la carte sous forme de
rectangles colorés avec info-bulle (inclinaison/azimut/surface), ainsi que
le contour du bâtiment identifié par Google — à comparer visuellement à
la vue satellite pour vérifier que le bon bâtiment/toit a été détecté.
L'algorithme de Google (imagerie/LIDAR) peut se tromper, notamment sur les
toits plats, complexes ou de petite taille (ex : inclinaison non nulle
affichée sur un toit plat) : les valeurs restent éditables manuellement
dans la section "Toiture(s)" ci-dessous, qui est ce qui alimente réellement
le calcul. Un bouton "🔄 Relancer la détection" reste disponible pour
forcer une nouvelle tentative (ex : après avoir collé la clé après coup).
Google ne fournissant que la surface de chaque pan (pas sa forme exacte),
la largeur/hauteur sont approximées par un carré équivalent — à ajuster
manuellement si les dimensions réelles sont connues.

### Répartition des panneaux sur le toit

La section "🏠 Toiture(s) & répartition des panneaux" permet, pour chaque
pan : de saisir sa largeur/hauteur et l'orientation des panneaux
(portrait/paysage), ce qui détermine combien de panneaux tiennent
physiquement dessus. Un champ "Nombre de panneaux souhaité (total)" +
bouton "Répartir automatiquement" répartit ce total au prorata des places
disponibles sur chaque pan ; on peut ensuite affiner avec un simple
curseur par pan (0 jusqu'à la capacité maximale calculée). Le nombre de
panneaux réellement réglé sur chaque curseur (pas une estimation de
surface) est ce qui alimente le calcul de production.

Pour ne jamais committer la clé par erreur :

```
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

puis remplacer la valeur par la vraie clé dans ce fichier local
(`.streamlit/secrets.toml` est déjà exclu par `.gitignore`). Sur Streamlit
Community Cloud, la clé se configure plutôt dans les "Secrets" de l'app,
depuis le tableau de bord — jamais dans le dépôt.

### Formulaire de contact (Ivry Soleil Partagé)

En bas de page, un formulaire facultatif permet de laisser ses coordonnées
(prénom, nom, email, téléphone, adresse — pré-remplie depuis la recherche
d'adresse faite en haut de page) pour être recontacté·e au sujet du projet
de communauté d'autoconsommation collective. Les mentions RGPD (finalité,
base légale, durée de conservation, droits, contact CNIL) sont détaillées
dans l'expander juste au-dessus du formulaire.

Fonctionnement technique :

- Les données sont stockées **uniquement en local**, dans une base SQLite
  (`data/contacts.db`, créée automatiquement au premier envoi). Aucun appel
  réseau, aucun service tiers.
- Le fichier `data/contacts.db` est exclu du dépôt par `.gitignore` — des
  données personnelles ne doivent jamais être commitées dans Git.
- Une case de consentement est **obligatoire** pour l'enregistrement (base
  légale du traitement) ; une seconde case, **facultative et décochée par
  défaut**, autorise en plus le partage avec des partenaires du projet —
  sans elle, les coordonnées ne doivent jamais être transmises à un tiers.
- **Important pour le déploiement** : sur un hébergement à disque éphémère
  (typiquement Streamlit Community Cloud), `data/contacts.db` ne survit pas
  à un redémarrage/redéploiement de l'app. Pour une conservation fiable des
  contacts dans la durée, préférer un auto-hébergement (NAS Synology, VPS...)
  où le disque persiste réellement entre les redémarrages.
- Avant toute collecte réelle de données personnelles, faire relire les
  mentions RGPD par un professionnel du droit (durée de conservation, nom
  légal exact du responsable de traitement, éventuelles obligations
  déclaratives selon l'ampleur de la collecte) — le texte fourni est un
  point de départ, pas un avis juridique.

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
- Les valeurs (inclinaison, azimut, surface) fournies par Google Solar API
  sont une estimation automatique et peuvent contenir des erreurs,
  notamment sur les toits plats ou complexes — toujours vérifier
  visuellement via la vue satellite et corriger manuellement si besoin.
- La base de contacts locale (`data/contacts.db`) n'est pas fiable sur un
  hébergement à disque éphémère (voir "Formulaire de contact" ci-dessus) :
  prévoir un auto-hébergement pour une conservation réelle dans la durée.
