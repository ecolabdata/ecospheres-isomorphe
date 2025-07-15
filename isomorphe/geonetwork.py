import logging
import re
from abc import abstractmethod
from dataclasses import dataclass
from enum import IntEnum, StrEnum, auto
from textwrap import shorten
from typing import Any, Callable, override

import requests
from lxml import etree

log = logging.getLogger(__name__)


class MetadataType(StrEnum):
    METADATA = "n"
    TEMPLATE = "y"
    SUB_TEMPLATE = "s"
    TEMPLATE_OF_SUB_TEMPLATE = "t"

    def label(self) -> str:
        match self:
            case self.METADATA:
                return "métadonnées"
            case self.TEMPLATE:
                return "modèle"
            case self.SUB_TEMPLATE:
                return "sous-modèle"
            case self.TEMPLATE_OF_SUB_TEMPLATE:
                return "modèle de sous-modèle"


class WorkflowStatus(IntEnum):
    UNKNOWN = 0
    DRAFT = 1
    APPROVED = 2
    RETIRED = 3
    SUBMITTED = 4
    REJECTED = 5


class WorkflowStage(StrEnum):
    NEVER_APPROVED = auto()
    APPROVED = auto()
    WORKING_COPY = auto()


@dataclass
class WorkflowState:
    # [Stage]  NEVER_APPROVED ------> APPROVED <-> WORKING_COPY (WC)
    # [Status] DRAFT -> SUBMITTED? -> APPROVED  -> DRAFT -> SUBMITTED? -\
    #                -> REJECTED -\                      -> REJECTED -\  |
    #                <------------/                      <------------/  |
    #                                           <--- WC applied --------/|
    #                                           <--- WC dropped --------/
    #
    # Each of those stages require a different treatment:
    # - NEVER_APPROVED:
    #   - Status is reported in `medatadata.mdStatus`.
    #   - Updating a never-approved record updates the record itself.
    # - APPROVED:
    #   - Status is reported in `metadata.mdStatus` (= APPROVED).
    #   - Updating an approved record creates a working copy containing the update.
    # - WORKING_COPY:
    #   - Working copy status must be queried from `/records/{uuid}/status`, since
    #     `metadata.mdStatus` always reports the record status.
    #   - Updating a record with a working copy MUST update the working copy.
    stage: WorkflowStage
    status: WorkflowStatus  # working copy status in WORKING_COPY stage, otherwise record status


@dataclass
class Record:
    uuid: str
    title: str
    md_type: MetadataType
    state: WorkflowState | None
    published: bool
    writable: bool


class GeonetworkConnectionError(Exception):
    pass


class GeonetworkClient:
    @staticmethod
    def connect(url: str, username: str | None = None, password: str | None = None):
        version = GeonetworkClient._server_version(url)
        client = GeonetworkClient._create(version, url)
        client.authenticate(username, password)
        return client

    @staticmethod
    def _server_version(url: str):
        r = requests.get(f"{url}/api/site", headers={"Accept": "application/json"})
        r.raise_for_status()
        try:
            version = int(r.json()["system/platform/version"].split(".")[0])
        except KeyError:
            raise GeonetworkConnectionError("Version Geonetwork manquante.")
        except requests.exceptions.JSONDecodeError:
            err = GeonetworkConnectionError(
                "Format de réponse serveur invalide. Avez-vous la bonne URL ?"
            )
            err.add_note(f"Response: {shorten(r.text, 200)}")
            raise err
        log.info(f"Geonetwork version: {version}")
        return version

    @staticmethod
    def _create(version: int, url: str):
        if version == 3:
            return GeonetworkClientV3(url)
        elif version == 4:
            return GeonetworkClientV4(url)
        else:
            raise GeonetworkConnectionError(f"Version Geonetwork non prise en charge: {version}")

    def __init__(self, url: str):
        self.url = url
        self.api = f"{url}/api"
        self.session = requests.Session()

    def authenticate(self, username: str | None, password: str | None):
        auth_url = f"{self.api}/info?_content_type=json&type=me"
        auth_headers = {"Accept": "application/json"}

        # First POST request to Geonetwork should return an error and the XSRF token (no need for credentials)
        # See https://docs.geonetwork-opensource.org/4.4/customizing-application/misc/
        r = self.session.post(auth_url, headers=auth_headers, allow_redirects=False)

        if r.is_redirect:
            raise GeonetworkConnectionError(
                f"Redirection détectée vers {r.headers['Location']}. Merci d'utiliser l'URL canonique du serveur."
            )

        xsrf_token = r.cookies.get("XSRF-TOKEN")
        log.debug(f"XSRF token found: {xsrf_token is not None}")
        if xsrf_token:
            self.session.headers.update({"X-XSRF-TOKEN": xsrf_token})
        elif not r.ok:
            raise GeonetworkConnectionError("Impossible de récupérer le token XSRF.")

        if username and password:
            log.debug(f"Authenticating as: {username}")
            self.session.auth = (username, password)
            # Retry the initial request but with credentials to make sure they're valid
            r = self.session.post(auth_url, headers=auth_headers)
            r.raise_for_status()
            try:
                me = r.json().get("me")
            except requests.exceptions.JSONDecodeError:
                err = GeonetworkConnectionError(
                    "Format de réponse serveur invalide. Avez-vous la bonne URL ?"
                )
                err.add_note(f"Response: {shorten(r.text, 200)}")
                raise err
            if not me:
                raise GeonetworkConnectionError("Réponse serveur vide.")
            if me.get("@authenticated") != "true":
                raise GeonetworkConnectionError("Non authentifié.")

    def get_records(self, query: dict[str, Any] | None = None) -> list[Record]:
        if query and (extra := query.pop("__extra__", None)):
            query |= {k.strip(): v.strip() for k, v in [p.split("=") for p in extra.split(",")]}
        params = self._search_params(query)
        log.debug(f"Search params: {params}")
        records = []
        from_pos = 0
        while True:
            hits = self._search_hits(params, from_pos=from_pos)
            if not hits:
                break
            recs = []
            for hit in hits:
                try:
                    rec = self._as_record(hit)
                except Exception as e:
                    raise RuntimeError(f"Failed to process record: {hit}") from e
                if rec:
                    if rec.writable:
                        log.debug(f"Record: {rec}")
                        recs.append(rec)
                    else:
                        log.debug(f"Skipping non-writable record: {rec}")
                else:
                    log.debug(f"Skipping empty record: {hit}")
            records += recs
            from_pos += len(hits)
        return records

    @abstractmethod
    def _search_params(self, query: dict[str, Any] | None) -> dict[str, Any]:
        pass

    @abstractmethod
    def _search_hits(self, params: dict[str, Any], from_pos: int) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    def _as_record(self, hit: dict[str, Any]) -> Record | None:
        pass

    @staticmethod
    def _get_metadata_type(md: dict) -> MetadataType:
        return MetadataType(md.get("isTemplate", MetadataType.METADATA))

    @staticmethod
    def _get_workflow_state(md: dict) -> WorkflowState | None:
        if "mdStatus" not in md:  # workflow disabled
            return None

        if not md.get("draft") == "e":
            status = WorkflowStatus(int(md["mdStatus"]))
            stage = (
                WorkflowStage.APPROVED
                if status == WorkflowStatus.APPROVED
                else WorkflowStage.NEVER_APPROVED
            )
        else:
            # Not supported in migration().
            # We don't bother setting the status (requires an API call), but
            # still include it in `records` so we can report on it.
            stage = WorkflowStage.WORKING_COPY
            status = WorkflowStatus.UNKNOWN

        return WorkflowState(stage=stage, status=status)

    @staticmethod
    @abstractmethod
    def uuid_filter(uuids: list[str]) -> dict[str, str]:
        """
        Return list of uuids as a filter parameter
        """
        pass

    def get_record(self, uuid: str, query: dict[str, Any] | None = None) -> etree._ElementTree:
        log.debug(f"Processing record: {uuid}")
        params = {
            "addSchemaLocation": "true",  # FIXME: needed?
            "increasePopularity": "false",
            "withInfo": "false",
            "attachment": "false",
            "approved": "false",  # only relevant when workflow is enabled
        }
        if query:
            params |= dict(
                m(v) if (m := self.QUERY_MAPPINGS.get(k)) else (k, v) for k, v in query.items()
            )
        r = self.session.get(
            f"{self.api}/records/{uuid}/formatters/xml",
            headers={"Accept": "application/xml"},
            params=params,
        )
        r.raise_for_status()
        return etree.fromstring(r.content, parser=None)

    def _extract_uuid_from_put_response(self, payload: dict) -> str | None:
        """
        Create record UUID is not in the `uuid` but in `metadatasInfos`:
        ```
        "metadataInfos":{
            "259":[
                {
                    "message":"Metadata imported from XML with UUID '7d447744-1be5-4be0-8b46-6be0d36ec90f'",
                    "date":"2024-09-12T15:39:41"
                }
            ]
        },
        ```
        """
        metadata_infos = payload.get("metadataInfos")
        if not metadata_infos:
            return None

        for md_info in metadata_infos.values():
            for info in md_info:
                message = info.get("message")
                uuid_match = re.search(
                    r"'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})'", message
                )
                if uuid_match:
                    return uuid_match.group(1)

    def put_record(
        self,
        uuid: str,
        metadata: bytes,
        md_type: MetadataType,
        group: int | None,
        uuid_processing: str = "GENERATEUUID",
    ) -> dict:
        log.debug(f"Duplicating record {uuid}: md_type={md_type.name}, group={group}")
        r = self.session.put(
            f"{self.api}/records",
            headers={"Accept": "application/json", "Content-type": "application/xml"},
            params={
                "uuidProcessing": uuid_processing,
                "group": group,
                "metadataType": md_type.name,
            },
            data=metadata,
        )
        r.raise_for_status()
        data = r.json()
        data["new_record_uuid"] = self._extract_uuid_from_put_response(data)
        return data

    def update_record(
        self,
        uuid: str,
        metadata: bytes,
        md_type: MetadataType,
        update_date_stamp: bool,
        state: WorkflowState | None = None,
    ):
        # PUT /records doesn't work as expected: it delete/recreates the record instead
        # of updating in place, hence losing Geonetwork-specific record metadata like
        # workflow state or access rights.
        # So instead we pretend to be the Geonetwork UI and "edit" the XML view of the
        # record, ignoring the returned editor view and immediately saving our new
        # metadata as the "edit" outcome.
        log.debug(f"Updating record {uuid}: md_type={md_type.value}, state={state}")

        r = self.session.get(
            f"{self.api}/records/{uuid}/editor",
            headers={"Accept": "application/xml"},
            params={
                "currTab": "xml",
                "withAttributes": "false",  # FIXME: needed? true/false?
            },
        )
        r.raise_for_status()

        # API expects x-www-form-urlencoded here
        data: dict[str, Any] = {
            "tab": "xml",
            "minor": str(not update_date_stamp).lower(),
            "withAttributes": "false",
            "withValidationErrors": "false",
            "commit": "true",
            "terminate": "true",
            "template": md_type.value,
            "data": metadata,
        }
        if state:
            if state.stage == WorkflowStage.WORKING_COPY:
                raise NotImplementedError("Migrating working copies is not supported")
            if state.status == WorkflowStatus.APPROVED:
                # The /editor API endpoint rejects requests setting the record status
                # directly to APPROVED (since it can't be done through the editor UI).
                # This means updates of records in WorkflowStage.APPROVED have to go
                # through creating a working copy.
                # We create that working copy as SUBMITTED so the update will have more
                # chances to get noticed (requiring action from a reviewer) in case the
                # follow-up request to re-approve the record fails.
                data["status"] = WorkflowStatus.SUBMITTED
            else:
                data["status"] = state.status
        r = self.session.post(f"{self.api}/records/{uuid}/editor", data=data)
        r.raise_for_status()

        if state and state.stage == WorkflowStage.APPROVED:
            # If the record was already approved, transparently approve the working copy
            # we created above when updating the record.
            r = self.session.put(
                f"{self.api}/records/{uuid}/status",
                headers={"Content-Type": "application/json"},
                json={
                    "changeMessage": "Approved by ISOmorphe",
                    "status": WorkflowStatus.APPROVED,
                },
            )
            r.raise_for_status()

    def delete_record(self, uuid: str) -> None:
        log.debug(f"Deleting record: {uuid}")
        r = self.session.delete(
            f"{self.api}/records/{uuid}",
            params={
                "withBackup": False,
            },
        )
        r.raise_for_status()

    def add_group(self, name: str, description: str = ""):
        log.info(f"Adding group: {name}")
        r = self.session.put(
            f"{self.api}/groups",
            headers={"Accept": "application/json"},
            json={
                "name": name,
                "description": description,
                "id": -99,
                "label": {},
                "email": "",
                "enableAllowedCategories": False,
                "allowedCategories": [],
                "defaultCategory": None,
                "logo": None,
                "referrer": None,
                "website": None,
            },
        )
        r.raise_for_status()
        return r.json()

    def get_groups(self) -> dict:
        r = self.session.get(
            f"{self.api}/groups",
            headers={"Accept": "application/json"},
        )
        r.raise_for_status()
        return r.json()


class GeonetworkClientV3(GeonetworkClient):
    version = 3

    QUERY_MAPPINGS: dict[str, Callable[[Any], tuple[str, Any]]] = {
        "group": lambda v: ("_groupOwner", v),
        "harvested": lambda v: ("_isHarvested", "y" if v else "n"),
        "source": lambda v: ("_source", v),
        "template": lambda v: ("_isTemplate", v),
        "uuid": lambda v: ("_uuid", v),
    }

    def _search_params(self, query: dict[str, Any] | None) -> dict[str, Any]:
        params = {
            "_content_type": "json",
            "buildSummary": "false",
            "fast": "index",  # needed to get info such as title
            "sortBy": "changeDate",
            "_isTemplate": "y or n",  # force default to "both" to match GN4 default
        }
        if query:
            params |= dict(
                m(v) if (m := self.QUERY_MAPPINGS.get(k)) else (k, v) for k, v in query.items()
            )
        return params

    def _search_hits(self, params: dict[str, Any], from_pos: int) -> list[dict[str, Any]]:
        r = self.session.get(
            f"{self.api}/q",
            headers={"Accept": "application/json"},
            params=params | {"from": from_pos + 1},  # v3 'from' param starts at 1
        )
        r.raise_for_status()
        rsp = r.json()
        hits = rsp.get("metadata")
        if hits and "geonet:info" in hits:
            # When returning a single record, metadata isn't a list :/
            hits = [hits]
        return hits

    def _as_record(self, hit: dict[str, Any]) -> Record | None:
        info = hit["geonet:info"]
        try:
            uuid = info["uuid"]
        except KeyError:
            return None
        return Record(
            uuid=uuid,
            title=hit.get("defaultTitle", ""),
            md_type=self._get_metadata_type(hit),
            state=self._get_workflow_state(hit),
            published=info.get("isPublishedToAll") == "true",
            writable=info.get("edit") == "true",
        )

    @staticmethod
    @override
    def uuid_filter(uuids: list[str]) -> dict[str, str]:
        return {"_uuid": " or ".join(uuids)} if uuids else {}


class GeonetworkClientV4(GeonetworkClient):
    version = 4

    QUERY_MAPPINGS: dict[str, Callable[[Any], tuple[str, Any]]] = {
        "group": lambda v: ("groupOwner", v),
        "harvested": lambda v: ("isHarvested", str(v).lower()),
        "source": lambda v: ("sourceCatalogue", v),
        "template": lambda v: ("isTemplate", v),
        "type": lambda v: ("resourceType", v),
    }

    def _search_params(self, query: dict[str, Any] | None) -> dict[str, Any]:
        params = {
            "size": 20,
            "sort": [{"changeDate": "desc"}],
            "_source": [
                "uuid",
                "resourceTitleObject.default",
                "resourceType",
                "draft",
                "isTemplate",
                "mdStatus",
            ],
        }
        if query:
            mapped_query = dict(
                m(v) if (m := self.QUERY_MAPPINGS.get(k)) else (k, v) for k, v in query.items()
            )
            params |= {
                "query": {
                    "bool": {
                        "filter": [
                            {
                                "query_string": {
                                    "query": " ".join(f"+{k}:{v}" for k, v in mapped_query.items())
                                }
                            }
                        ]
                    }
                }
            }
        return params

    def _search_hits(self, params: dict[str, Any], from_pos: int) -> list[dict[str, Any]]:
        r = self.session.post(
            f"{self.api}/search/records/_search",
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            params={"bucket": "metadata"},
            json=params | {"from": from_pos},
        )
        r.raise_for_status()
        hits = r.json().get("hits") or {}
        return hits.get("hits") or []  # nested "hits"

    def _as_record(self, hit: dict[str, Any]) -> Record | None:
        try:
            md = hit["_source"]
            uuid = md["uuid"]
        except KeyError:
            return None
        title = md.get("resourceTitleObject") or {}
        if isinstance(title, list):  # seen in the wild...
            title = title[0]
        return Record(
            uuid=uuid,
            title=title.get("default", ""),
            md_type=self._get_metadata_type(md),
            state=self._get_workflow_state(md),
            published=hit.get("isPublishedToAll", False),
            writable=hit.get("edit", False),
        )

    @staticmethod
    @override
    def uuid_filter(uuids: list[str]) -> dict[str, str]:
        return {"uuid": "[" + ",".join([f'"{u}"' for u in uuids]) + "]"} if uuids else {}
