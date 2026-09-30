# -*- coding: utf-8 -*-
"""Hasher scrypt au format de Heimdall.

Le portage vers Django aurait normalement coûté tous les mots de passe : une
empreinte ne se reconvertit pas, c'est précisément ce qui fait sa valeur, et
c'est ce qui était arrivé en sens inverse au passage de Django vers Heimdall.

Sauf que Heimdall hachait déjà en scrypt, que Django sait faire du scrypt, et
que seul l'encodage diffère :

    Heimdall : scrypt$<n>$<r>$<p>$<sel>$<hex>
    Django   : scrypt$<n>$<sel>$<r>$<p>$<base64>

Ce hasher lit et écrit la première forme. Les comptes repris continuent donc de
fonctionner avec leur mot de passe actuel, et personne n'a à en changer.

Il reste le hasher d'écriture par défaut pour que le trajet soit réversible :
une base produite ici se relit par l'application Qt d'origine, ce qui laisse la
possibilité de revenir en arrière tant que le déploiement n'est pas acquis.
"""

import hashlib
import hmac

from django.contrib.auth.hashers import BasePasswordHasher
from django.utils.crypto import constant_time_compare, get_random_string
from django.utils.translation import gettext_noop as _

# Paramètres d'origine, reproduits à l'identique : les changer casserait la
# relecture par l'application Qt, et le coût actuel est déjà correct.
SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
LONGUEUR_EMPREINTE = 32
MAXMEM = 64 * 1024 * 1024


class ScryptHeimdall(BasePasswordHasher):
    """scrypt, encodé comme l'application Qt l'encodait."""

    algorithm = "scrypt"
    n = SCRYPT_N
    r = SCRYPT_R
    p = SCRYPT_P

    def salt(self):
        # Hexadécimal, comme à l'origine : le sel est concaténé dans une chaîne
        # découpée sur « $ », et un sel base64 pourrait en contenir un.
        return get_random_string(32, allowed_chars="0123456789abcdef")

    def encode(self, password, salt=None, n=None, r=None, p=None):
        salt = salt or self.salt()
        assert "$" not in salt, "le sel ne doit pas contenir de séparateur"
        n, r, p = n or self.n, r or self.r, p or self.p
        brut = hashlib.scrypt(
            password.encode("utf-8"), salt=salt.encode("ascii"),
            n=n, r=r, p=p, dklen=LONGUEUR_EMPREINTE, maxmem=MAXMEM,
        )
        return "%s$%d$%d$%d$%s$%s" % (self.algorithm, n, r, p, salt, brut.hex())

    def decode(self, encoded):
        algorithme, n, r, p, salt, empreinte = encoded.split("$", 5)
        assert algorithme == self.algorithm
        return {"algorithm": algorithme, "n": int(n), "r": int(r),
                "p": int(p), "salt": salt, "hash": empreinte}

    def verify(self, password, encoded):
        try:
            lu = self.decode(encoded)
        except (ValueError, AssertionError):
            return False
        try:
            calcule = hashlib.scrypt(
                password.encode("utf-8"), salt=lu["salt"].encode("ascii"),
                n=lu["n"], r=lu["r"], p=lu["p"],
                dklen=len(lu["hash"]) // 2, maxmem=MAXMEM,
            )
        except (ValueError, TypeError):
            return False
        # `hmac.compare_digest` plutôt que `==` : la durée d'une comparaison
        # ordinaire renseigne sur le nombre de caractères justes.
        return hmac.compare_digest(calcule.hex(), lu["hash"])

    def safe_summary(self, encoded):
        lu = self.decode(encoded)
        return {
            _("algorithm"): lu["algorithm"],
            _("work factor"): lu["n"],
            _("block size"): lu["r"],
            _("parallelism"): lu["p"],
            _("salt"): self.mask_hash(lu["salt"]),
            _("hash"): self.mask_hash(lu["hash"]),
        }

    def must_update(self, encoded):
        lu = self.decode(encoded)
        return (lu["n"], lu["r"], lu["p"]) != (self.n, self.r, self.p)

    def harden_runtime(self, password, encoded):
        # Le coût de scrypt ne dépend pas du mot de passe : il n'y a rien à
        # égaliser après un échec, contrairement à PBKDF2 dont le nombre
        # d'itérations stocké peut différer.
        pass
