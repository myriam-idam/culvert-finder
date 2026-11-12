"""Paramètres de l'analyse (toutes les distances sont en mètres)."""

from dataclasses import dataclass


@dataclass
class Parametres:
    # Profil en long extrait le long du cours d'eau, de part et d'autre du franchissement
    demi_longueur_profil: float = 40.0
    # Demi-largeur de la zone « remblai » centrée sur le franchissement
    demi_largeur_remblai: float = 12.0
    # Rayon de recherche du point bas autour du tracé (le tracé BD TOPO n'est pas
    # exactement sur le thalweg du MNT)
    rayon_thalweg: float = 3.0
    # Rayon de recherche de la cuvette créée par le remblai
    rayon_cuvette: float = 30.0
    # Distance maximale pour associer un ouvrage OpenStreetMap à un franchissement
    distance_osm: float = 20.0
    # Distance minimale entre deux franchissements (dédoublonnage)
    espacement_min: float = 10.0
    # Valeurs de référence pour le score (au-delà, la composante vaut 1)
    hauteur_remblai_ref: float = 1.0
    profondeur_cuvette_ref: float = 0.5
    # Score à partir duquel un franchissement est corrigé dans le MNT
    seuil_correction: float = 0.6
    # Score à partir duquel un franchissement est signalé « à vérifier »
    seuil_verification: float = 0.3
    # Demi-largeur (en cellules) du chenal creusé dans le MNT
    demi_largeur_chenal: int = 1
