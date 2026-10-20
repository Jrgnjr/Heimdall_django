# Heimdall — pack de refonte graphique

Référence visuelle pour appliquer la refonte au code de l'appli.

- `captures/` : chaque écran en sombre et en clair (PNG, 1440 px de large). C'est la cible.
- `maquettes/` : les mêmes écrans en HTML vivant (navigation, filtres, recherche, sélection de casier).
  Pour les ouvrir : `cd maquettes && python3 -m http.server 8000`, puis
  http://localhost:8000/Main.dc.html (ajouter `?theme=Clair` pour le mode clair).
  `support.js` est un petit lecteur autonome du format des maquettes ; il ne fait pas partie de l'appli.
  Dans chaque fichier, seul le markup et les styles comptent : le bloc
  `<script type="text/x-dc">` ne contient que les données d'exemple de la maquette.
- `tokens.css` : couleurs (thèmes `.t-dark` / `.t-light`), typo, rayons, espacements et règles d'usage.
- `icones/inline/` : les 12 icônes à coller en SVG inline (trait `currentColor`, accent `var(--gold)`).
  `icones/sombre/` et `icones/clair/` : les mêmes en couleurs figées, pour un usage en `<img>`.

Le logo est un emplacement vide dans les maquettes : garder le logo actuel de l'appli.
Le seuil « stock bas » (5 u. ou moins) est une hypothèse de maquette.
