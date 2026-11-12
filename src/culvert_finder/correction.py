"""Correction du MNT : creusement d'un chenal à travers les remblais détectés (« burning »)."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString

from culvert_finder.config import Parametres
from culvert_finder.mnt import lignes_colonnes, profil_en_long


def creuser(
    mnt: np.ndarray,
    mnt_thalweg: np.ndarray,
    franch: gpd.GeoDataFrame,
    lignes: list[LineString],
    transform,
    params: Parametres,
) -> tuple[np.ndarray, np.ndarray]:
    """Creuse le MNT au droit des franchissements dont le score dépasse le seuil.

    Entre le point bas amont et le point bas aval, l'altitude le long du cours d'eau est
    abaissée sur une droite reliant ces deux points : l'eau franchit le remblai comme
    par une buse. Aux deux extrémités, le chenal est élargi au rayon de recherche du
    thalweg pour rejoindre le vrai point bas (le tracé BD TOPO peut en être décalé de
    quelques mètres) : sans cela, l'extrémité du chenal formerait un trou.
    Renvoie (MNT corrigé, masque booléen des franchissements corrigés).
    """
    corrige = mnt.copy()
    corriges = np.zeros(len(franch), dtype=bool)
    w = params.demi_largeur_chenal
    w_ext = max(w, int(round(params.rayon_thalweg / abs(transform.a))))
    c = params.demi_largeur_remblai
    for n, (p, j, score) in enumerate(zip(franch.geometry, franch["indice_cours_eau"], franch["score"])):
        if score < params.seuil_correction:
            continue
        off, xs, ys, z = profil_en_long(lignes[int(j)], p, mnt_thalweg, transform, params.demi_longueur_profil)
        gauche = np.where((off < -c) & np.isfinite(z))[0]
        droite = np.where((off > c) & np.isfinite(z))[0]
        if not len(gauche) or not len(droite):
            continue
        ig = gauche[np.argmin(z[gauche])]
        id_ = droite[np.argmin(z[droite])]
        segment = slice(ig, id_ + 1)
        cible = np.interp(off[segment], [off[ig], off[id_]], [z[ig], z[id_]])
        rows, cols = lignes_colonnes(transform, xs[segment], ys[segment])
        dernier = len(cible) - 1
        for k, (r, col, t) in enumerate(zip(rows, cols, cible)):
            if not (0 <= r < corrige.shape[0] and 0 <= col < corrige.shape[1]):
                continue
            # Aux extrémités, la cible est le minimum de la fenêtre du thalweg : abaisser
            # toute la fenêtre à cette valeur la relie au vrai point bas, sans creux.
            ww = w_ext if k in (0, dernier) else w
            bloc = corrige[max(r - ww, 0) : r + ww + 1, max(col - ww, 0) : col + ww + 1]
            np.fmin(bloc, t, out=bloc, where=np.isfinite(bloc))
        corriges[n] = True
    return corrige, corriges
