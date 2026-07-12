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

`app.py` est organisée autour de la communauté Ivry Soleil Partagé : un
en-tête affiche deux "piles" (jauges) avec la production annuelle et la
consommation échangée via l'autoconsommation collective (ACC) de la
communauté, puis trois onglets séparent les usages : **Producteur**
(simuler ou décrire une installation photovoltaïque — le contenu détaillé
ci-dessous), **Consommateur** (estimer ses économies à partir de sa
facture EDF), et **Administration** (réservé à l'association, pour valider
les soumissions avant qu'elles comptent dans les totaux de la communauté).

### En-tête : les piles de la communauté

Les deux jauges ("Production annuelle" et "Consommation échangée via
l'ACC") affichent les totaux **approuvés uniquement** (voir onglet
Administration), avec un pourcentage de remplissage par rapport à un
objectif annuel réglable par l'association. Version annuelle uniquement
pour l'instant ; une vue plus détaillée (mensuelle, par membre...) est
prévue dans une prochaine itération.

### Onglet Producteur

Le contenu de cet onglet reprend le simulateur solaire complet (chaque
section a son encadré "ℹ️ Pourquoi ces informations ?") : choix du profil,
localisation, modules PV, pans de toiture, consommation du foyer, batterie
optionnelle, financement, tarifs — puis affiche les résultats (production,
autoconsommation, temps de retour, VAN) avec des graphiques interactifs. La
batterie est simulée heure par heure (charge sur le surplus, décharge sur
le manque, rendement aller-retour) et augmente mécaniquement le taux
d'autoconsommation. Une fois les résultats calculés, un expander "📤
Contribuer à la pile de production de la communauté" permet de soumettre
sa production annuelle (nom, email, consentement) — la soumission reste en
attente de validation par un-e administrateur-ice avant de compter dans la
pile affichée en en-tête.

#### Deux profils

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

### Onglet Consommateur

Permet à un-e non-producteur-ice d'estimer ses économies potentielles en
rejoignant l'autoconsommation collective. On y dépose sa facture EDF (PDF,
JPG ou PNG) ; le bouton "Analyser la facture" envoie le document à l'API
Claude d'Anthropic (modèle Sonnet), qui en extrait automatiquement adresse,
point de livraison (PDL), titulaire, consommation annuelle, prix moyen du
kWh, etc. (voir `src/invoice_extraction.py`). Ces valeurs sont ensuite
affichées dans un formulaire éditable — à vérifier/corriger avant de
continuer, l'IA pouvant se tromper. Le calcul d'économies applique un taux
de couverture ACC et un prix ACC réglables (par défaut 30 % et 0,20 €/kWh)
faute de clé de répartition réelle pour l'instant — à affiner une fois la
convention de l'association et les données d'allocation réelles connues.
Un expander "📤 Contribuer à la pile de consommation de la communauté"
permet ensuite de soumettre ces données (en attente de validation).

Important : la facture n'est envoyée qu'à l'API Anthropic pour cette
analyse ponctuelle (elle n'est pas stockée par Ivry Soleil Partagé) ; seuls
les champs extraits, vérifiés par l'utilisateur-ice puis explicitement
soumis, sont conservés localement.

### Onglet Administration

Réservé à l'association : protégé par un mot de passe (`ADMIN_PASSWORD`,
voir configuration des clés ci-dessous — l'onglet reste inaccessible tant
qu'il n'est pas défini). Permet de régler les objectifs annuels des deux
piles, de consulter les soumissions producteur/consommateur en attente
(avec boutons Approuver/Rejeter), et de voir l'historique complet des
soumissions déjà traitées. Seules les soumissions **approuvées** comptent
dans les totaux affichés en en-tête (voir `src/community_db.py`).

### Configuration des clés et mots de passe

Trois secrets optionnels, à définir dans `.streamlit/secrets.toml` (jamais
dans le dépôt) :

```
GOOGLE_SOLAR_API_KEY = "..."   # detection automatique du toit (onglet Producteur)
ANTHROPIC_API_KEY = "..."      # extraction de facture (onglet Consommateur)
ADMIN_PASSWORD = "..."         # acces a l'onglet Administration
```

```
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

puis remplacer les valeurs par les vraies clés dans ce fichier local
(`.streamlit/secrets.toml` est déjà exclu par `.gitignore`). Sur Streamlit
Community Cloud, ces valeurs se configurent plutôt dans les "Secrets" de
l'app, depuis le tableau de bord — jamais dans le dépôt. Sans clé
configurée, chaque fonctionnalité correspondante affiche un champ de test
local (à ne jamais utiliser sur une app publique, la valeur saisie restant
visible/inspectable par les visiteurs) ou reste inaccessible (cas du mot
de passe administrateur).

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

Les soumissions de production/consommation (onglets Producteur/Consommateur,
section "📤 Contribuer à la pile...") suivent la même logique de stockage
local, mais dans une base séparée : `data/community.db` (voir
`src/community_db.py`), elle aussi exclue du dépôt par `.gitignore`. Chaque
soumission reste au statut "en attente" jusqu'à validation explicite par
un-e administrateur-ice dans l'onglet Administration ; seules les
soumissions approuvées comptent dans les totaux affichés en en-tête.

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
- Le calcul d'économies de l'onglet Consommateur repose sur un taux de
  couverture ACC et un prix ACC **saisis manuellement** (par défaut 30 % et
  0,20 €/kWh) : il n'existe pas encore de vraie clé de répartition de
  l'énergie partagée entre les membres de la communauté. La "pile"
  d'énergie échangée via l'ACC en en-tête additionne, pour l'instant, les
  valeurs déclarées/estimées à chaque soumission approuvée — à remplacer
  par un calcul réel dès que les données d'allocation (Enedis, PMO...)
  seront disponibles.
- L'extraction de facture via l'API Anthropic peut se tromper (mise en
  page inhabituelle, facture de mauvaise qualité/scan...) : les champs
  extraits sont affichés dans un formulaire éditable à vérifier avant
  toute soumission, jamais enregistrés tels quels sans relecture.
- Le mot de passe administrateur protège l'onglet Administration au niveau
  de l'application (comparaison côté serveur), mais reste un mécanisme
  simple : suffisant pour une petite association, pas un contrôle d'accès
  de niveau production. Ne pas y stocker de secret plus sensible que la
  validation de soumissions.
