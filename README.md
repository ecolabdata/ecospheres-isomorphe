# ecospheres-isomorphe

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
- [RQ](https://python-rq.org) pour une gestion de jobs/queue simple, basé sur Redis,
    - NB: ce composant est jugé nécessaire car certains traitements peuvent prendre du temps, notamment les opérations sur le catalogue distant. L'architecture permet également de stocker des éléments volumineux (fichier de sortie) entre les requêtes. Si la notion de job/queue n'est plus jugée nécessaire, le Redis pourra être utilisé pour stocker des données de sessions volumineuses.
- un frontend HTML Flask classique.

## Configuration

Les variables d'environnement suivantes sont nécessaires :

```shell
export FLASK_APP=isomorphe.app
export FLASK_DEBUG=1
export FLASK_SECRET_KEY=s3cr3t
export REDIS_URL=redis://localhost:6379
export TRANSFORMATIONS_PATH=/path/to/xslt/repository
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
rq worker --url $REDIS_URL
```

### Lancement des tests

Lancer les services de test :

```shell
docker compose -f docker-compose.tests.yml up
```

Lancer les tests :

```shell
pytest
```

### MacOS caveat

Sur MacOS, il peut être nécessaire d'utiliser la variable d'environnement suivante pour éviter un crash du worker RQ :

```shell
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
```

Référence : https://github.com/rq/rq/issues/2058

## Linting

Linting, formatting and import sorting are done automatically by [Ruff](https://docs.astral.sh/ruff/) launched by a pre-commit hook. So, before contributing to the repository, it is necessary to initialize the pre-commit hooks:

```bash
pre-commit install
```
Once this is done, code formatting and linting, as well as import sorting, will be automatically checked before each commit.

If you cannot use pre-commit, it is necessary to format, lint, and sort imports with [Ruff](https://docs.astral.sh/ruff/) before committing:

```bash
ruff check --fix .
ruff format .
```

> WARNING: running `ruff` on the codebase will lint and format all of it, whereas using `pre-commit` will only be done on the staged files.
