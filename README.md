# ecospheres-migrator

Une application pour appliquer des transformations XML aux catalogues Geonetwork du MTECT.

## Processus

1. Sélection du catalogue, des fiches à migrer et des traitements à appliquer
2. Traitement des données (application des transformations)
3. Migration des données sur le catalogue distant (optionnel)

Le parti-pris pour les étapes 2. et 3. est d'utiliser (actuellement simulé) un fichier binaire d'échange qui peut être téléchargé par l'usager à l'issue de l'étape et/ou appliqué par l'application à l'étape 3.

## Architecture

L'application [Flask](https://flask.palletsprojects.com/en/3.0.x/) intègre :
- le [DSFR](https://www.systeme-de-design.gouv.fr) pour une charte graphique cohérente,
- [htmx](https://htmx.org) pour dynamiser certains comportements (prévisualisation de la sélection, polling du statut des jobs)
- (RQ)[https://python-rq.org] pour une gestion de jobs/queue simple, basé sur Redis,
    - NB: ce composant est jugé nécessaire car certains traitements peuvent prendre du temps, notamment les opérations sur le catalogue distant. L'architecture permet également de stocker des éléments volumineux (fichier de sortie) entre les requêtes. Si la notion de job/queue n'est plus jugée nécessaire, le Redis pourra être utilisé pour stocker des données de sessions volumineuses.
- un frontend HTML Flask classique.

## Configuration

Les variables d'environnement suivantes sont nécessaires :

```shell
export FLASK_APP=ecospheres_migrator.app
export FLASK_DEBUG=1
export FLASK_SECRET_KEY=s3cr3t
export REDIS_URL=redis://localhost:6379
```

## Installation

Lancement du service Redis éphémère :

```shell
docker compose up
```

Installation des dépendances :

```shell
pip install -r requirements.txt
```

Lancement de l'application principale :

```shell
flask run
```

Lancement du worker RQ (traitement des jobs en asynchrone) :

```shell
rq worker
```
