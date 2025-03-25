import io
import logging
import re
import zipfile
from abc import abstractmethod
from dataclasses import dataclass
from enum import IntEnum, StrEnum, auto
from typing import Any, Callable, override

import requests
from lxml import etree
from lxml.builder import E

log = logging.getLogger(__name__)


class MetadataType(StrEnum):
    METADATA = "n"
    TEMPLATE = "y"
    SUB_TEMPLATE = "s"
    TEMPLATE_OF_SUB_TEMPLATE = "t"


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


class GeonetworkConnectionError(Exception):
    pass


class GeonetworkClient:
    @staticmethod
    def connect(url: str, username: str | None = None, password: str | None = None):
        session = requests.Session()
        GeonetworkClient._authenticate_session(url, session, username, password)
        version = GeonetworkClient._server_version(url, session)
        if version == 3:
            return GeonetworkClientV3(url, session)
        elif version == 4:
            return GeonetworkClientV4(url, session)
        else:
            raise GeonetworkConnectionError(f"Version Geonetwork non prise en charge: {version}")

    @staticmethod
    def _authenticate_session(
        url: str, session: requests.Session, username: str | None, password: str | None
    ):
        if username and password:
            session.auth = (username, password)
            log.info(f"Authenticating as: {username}")

        r = session.post(f"{url}/api/info?_content_type=json&type=me", allow_redirects=False)
        if r.is_redirect:
            raise GeonetworkConnectionError(
                f"Redirection détectée vers {r.headers['Location']}. Merci d'utiliser l'URL canonique du serveur."
            )
        # if the POST above failed, we need the XSFR-TOKEN to proceed further
        # if it did not, (username, password) basic auth should be enough
        if not r.ok:
            xsrf_token = r.cookies.get("XSRF-TOKEN")
            if xsrf_token:
                session.headers.update({"X-XSRF-TOKEN": xsrf_token})
                log.debug("XSRF token found")
            else:
                raise GeonetworkConnectionError("Impossible de récupérer le token XSRF")

    @staticmethod
    def _server_version(url: str, session: requests.Session):
        r = session.get(f"{url}/api/site", headers={"Accept": "application/json"})
        r.raise_for_status()
        try:
            version = int(r.json()["system/platform/version"].split(".")[0])
        except KeyError:
            raise GeonetworkConnectionError("Version Geonetwork manquante")
        log.info(f"Geonetwork version: {version}")
        return version

    def __init__(self, url: str, session: requests.Session | None = None):
        self.url = url
        self.api = f"{url}/api"
        self.session = session if session else requests.Session()

    def info(self):
        r = self.session.get(f"{self.api}/info?_content_type=json&type=me")
        r.raise_for_status()
        return r.json()

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
                    log.debug(f"Record: {rec}")
                    recs.append(rec)
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

    def get_record(self, uuid: str) -> etree._ElementTree:
        log.debug(f"Processing record: {uuid}")
        r = self.session.get(
            f"{self.api}/records/{uuid}/formatters/xml",
            headers={"Accept": "application/xml"},
            params={
                "addSchemaLocation": "true",  # FIXME: needed?
                "increasePopularity": "false",
                "withInfo": "true",
                "attachment": "false",
                "approved": "false",  # only relevant when workflow is enabled
            },
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
            "minor": "false" if update_date_stamp else "true",
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

    def get_sources(self) -> dict:
        r = self.session.get(f"{self.api}/sources", headers={"Accept": "application/json"})
        r.raise_for_status()
        sources = {s["uuid"]: s["name"] for s in r.json()}
        return sources

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
        # FIXME: can't do template+metadata in a single request
        "template": lambda v: ("_isTemplate", v),
        "uuid": lambda v: ("_uuid", v),
    }

    def _search_params(self, query: dict[str, Any] | None) -> dict[str, Any]:
        params = {
            "_content_type": "json",
            "buildSummary": "false",
            "fast": "index",  # needed to get info such as title
            "sortBy": "changeDate",
            "sortOrder": "reverse",
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
        try:
            uuid = hit["geonet:info"]["uuid"]
        except KeyError:
            return None
        return Record(
            uuid=uuid,
            title=hit.get("defaultTitle", ""),
            md_type=self._get_metadata_type(hit),
            state=self._get_workflow_state(hit),
        )

    @staticmethod
    @override
    def uuid_filter(uuids: list[str]) -> dict[str, str]:
        return {"_uuid": " or ".join(uuids)}


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
            "sort": [{"changeDate": "asc"}],
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
        )

    @staticmethod
    @override
    def uuid_filter(uuids: list[str]) -> dict[str, str]:
        return {"uuid": "[" + ",".join([f'"{u}"' for u in uuids]) + "]"}


class MefArchive:
    def __init__(self, compression=zipfile.ZIP_DEFLATED):
        self.zipb = io.BytesIO()
        self.zipf = zipfile.ZipFile(self.zipb, "w", compression=compression)

    def add(self, uuid: str, record: bytes, info: str):
        """
        Add a record to the MEF archive.

        :param uuid: Record UUID.
        :param record: Record metadata.
        :param info: Record info in MEF `info.xml` format.
        """
        self.zipf.writestr(f"{uuid}/info.xml", info)
        self.zipf.writestr(f"{uuid}/metadata/metadata.xml", record)

    def finalize(self):
        """
        Finalize and return bytes of the full MEF archive.
        """
        self.zipf.close()
        return self.zipb.getvalue()


def extract_record_info(record: etree._ElementTree, sources: dict) -> etree._ElementTree:
    """
    Extract (remove and return) the `geonet:info` structure from the given record.

    :param record: Record to process.
    :param sources: List of existing sources, as returned by `GeonetworkClient.get_sources`.
    :returns: Record info in MEF `info.xml` format.
    """
    ri = record.xpath("/gmd:MD_Metadata/geonet:info", namespaces=record.nsmap)[0]
    ri.getparent().remove(ri)
    source_id = ri.find("source").text
    info = E.info(
        E.general(
            E.createDate(ri.find("createDate").text),
            E.changeDate(ri.find("changeDate").text),
            E.schema(ri.find("schema").text),
            E.isTemplate(ri.find("isTemplate").text),
            E.localId(ri.find("id").text),
            E.format("simple"),
            E.rating(ri.find("rating").text),
            E.popularity(ri.find("popularity").text),
            E.uuid(ri.find("uuid").text),
            E.siteId(source_id),
            E.siteName(sources[source_id]),
        ),
        E.categories(),
        E.privileges(),
        E.public(),
        E.private(),
        version="1.1",
    )
    return info.getroottree()
