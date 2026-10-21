# -*- coding: utf-8 -*-
"""Invariants de l'interface, vérifiés sur le gabarit lui-même.

`index.html` est du JavaScript qui réécrit toute la page à chaque redessin. Ce
parti pris a une contrainte, et elle ne se voit pas à la lecture : un champ de
saisie doit porter un `data-k`, sinon le moteur ne sait pas où remettre le
curseur après le redessin, et celui-ci **sort du champ à chaque caractère
tapé**.

C'est arrivé au champ « détail » du sac de dotation, et quatre autres champs
avaient le même défaut sans que personne ne l'ait encore remarqué. D'où ce
test, qui vérifie la règle plutôt que le cas.

Il lit le gabarit comme du texte, pas comme du HTML : le fichier est un
programme qui *produit* du HTML, et ses balises contiennent des expressions
JavaScript — un analyseur syntaxique HTML s'y perdrait.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

GABARIT = Path(settings.RACINE) / "templates" / "stock" / "index.html"

# Les éléments de saisie au clavier. `<select>` en est exclu : il réagit au
# changement, pas à la frappe, et l'interaction est terminée quand il se
# redessine.
OUVERTURES = ("<input", "<textarea")


def _contexte(source, position, longueur=90):
    """De quoi reconnaître le champ fautif dans le message d'échec."""
    debut = max(0, position - longueur)
    return source[debut:position + longueur].replace("\n", " ")


class ChampsDeSaisie(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = GABARIT.read_text(encoding="utf-8")

    def test_le_gabarit_est_lisible(self):
        self.assertGreater(len(self.source), 100_000,
                           "le gabarit de l'interface est introuvable ou tronqué")

    def test_tout_champ_de_saisie_porte_un_data_k(self):
        """Sans `data-k`, le curseur saute hors du champ à chaque frappe.

        Le redessin peut venir du champ lui-même, ou de la boucle de
        synchronisation qui interroge le serveur toutes les 2,5 secondes : même
        un champ qui ne redessine pas lui-même en a besoin.
        """
        fautifs = []
        for correspondance in re.finditer(r"\$\{oni\(", self.source):
            position = correspondance.start()
            # L'élément englobant est la dernière ouverture avant ce gestionnaire.
            debut = max(self.source.rfind(o, 0, position) for o in OUVERTURES)
            self.assertGreater(
                debut, -1,
                "gestionnaire de saisie hors de tout champ : %s"
                % _contexte(self.source, position))
            if "data-k=" not in self.source[debut:position]:
                fautifs.append(_contexte(self.source, debut))

        self.assertEqual(
            fautifs, [],
            "%d champ(s) de saisie sans data-k — le curseur en sortira à "
            "chaque caractère :\n  - %s"
            % (len(fautifs), "\n  - ".join(fautifs)))

    def test_les_cles_du_sac_distinguent_les_exemplaires(self):
        """Deux exemplaires du même article ont deux champs distincts.

        Une clé partagée ferait rendre le curseur au mauvais champ — plus
        déroutant encore que de le perdre.
        """
        for cle in ('data-k="dot-det-${esc(k)}"', 'data-k="dot-qte-${esc(k)}"'):
            self.assertIn(cle, self.source,
                          "la clé du champ de sac ne dépend plus de l'exemplaire")

    def test_le_moteur_restaure_bien_le_curseur(self):
        """La contre-partie : le mécanisme que ces `data-k` alimentent.

        S'il disparaissait, tous les `data-k` du fichier deviendraient
        décoratifs et le défaut reviendrait partout à la fois.
        """
        self.assertIn("ae.dataset ? ae.dataset.k : null", self.source)
        self.assertIn("app.querySelector('[data-k=\"'+CSS.escape(focusKey)+'\"]')",
                      self.source)
        self.assertIn("setSelectionRange(focusPos,focusPos)", self.source)

    def test_les_listes_de_stock_admin_gardent_les_commandes_et_defilent(self):
        for onglet, rubrique in (("phones", "Téléphones"), ("material", "Matériel")):
            with self.subTest(rubrique=rubrique):
                self.assertIn(
                    '<section class="card admin-stock-card" aria-label="%s" '
                    'style="overflow:hidden;display:${S.adminTab==="%s"?"flex":"none"};'
                    % (rubrique, onglet),
                    self.source,
                )
                section = self.source.split(
                    'aria-label="%s"' % rubrique, 1
                )[1].split("</section>", 1)[0]
                self.assertIn(
                    'display:${S.adminTab==="%s"?"flex":"none"};'
                    "flex-direction:column;flex:1;min-height:0" % onglet,
                    section,
                )
                self.assertIn('class="admin-stock-list"', section)
        self.assertIn(
            ".admin-stock-list{flex:1;min-height:0;overflow:auto}",
            self.source,
        )

    def test_le_formulaire_de_creation_template_a_un_espace_sous_les_boutons(self):
        editeur = self.source.split("function editeurTemplate(f){", 1)[1]
        self.assertIn(
            ".template-editor-card{flex:1;min-height:0;overflow-y:auto;"
            "overscroll-behavior:contain}",
            self.source,
        )
        self.assertIn(
            '<div class="card template-editor-card" '
            'style="display:${S.adminTab==="templates"?"block":"none"}">',
            editeur,
        )
        self.assertIn(
            'overflow:${S.adminTab==="templates"&&S.templateEdit?"hidden":"auto"}',
            self.source,
        )
        pied = editeur.split('class="template-editor-actions"', 1)[1].split(
            "</div>", 1
        )[0]
        self.assertIn(
            'padding:14px 16px ${f.origine?"14px":"10px"}', pied
        )
        self.assertIn(">Annuler</button>", pied)
        self.assertIn(
            '>${f.origine?"Enregistrer":"Créer le template"}</button>',
            pied,
        )
