import io
import logging
import re
import zipfile
from dataclasses import dataclass
from enum import IntEnum, StrEnum, auto
from typing import Any

import requests
from lxml import etree
from lxml.builder import E

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)


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
    template: bool
    state: WorkflowState | None


class GeonetworkClient:
    def __init__(self, url, username: str | None = None, password: str | None = None):
        self.url = url
        self.api = f"{self.url}/api"
        self.session = requests.Session()
        if username and password:
            self.session.auth = (username, password)
            log.debug(f"Authenticating as: {username}")
        self.authenticate()

    def info(self):
        r = self.session.get(f"{self.api}/info?_content_type=json&type=me")
        r.raise_for_status()
        return r.json()

    def authenticate(self):
        r = self.session.post(f"{self.api}/info?_content_type=json&type=me")
        # don't abort on error here, it's expected
        xsrf_token = r.cookies.get("XSRF-TOKEN")
        if xsrf_token:
            self.session.headers.update({"X-XSRF-TOKEN": xsrf_token})
        log.debug(f"XSRF token: {xsrf_token}")

    def get_records(self, query=None) -> list[Record]:
        params = {
            "_content_type": "json",
            "buildSummary": "false",
            "fast": "index",  # needed to get info such as title
            "sortBy": "title",  # FIXME: or changeDate?
            "sortOrder": "reverse",
        }
        if query:
            params |= query

        records = []
        to = 0
        while True:
            r = self.session.get(
                f"{self.api}/q",
                headers={"Accept": "application/json"},
                params=params | {"from": to + 1},
            )
            r.raise_for_status()
            rsp = r.json()
            mds = rsp.get("metadata")
            if not mds:
                break
            if "geonet:info" in mds:
                # When returning a single record, metadata isn't a list :/
                mds = [mds]
            recs = []
            for md in mds:
                uuid = md["geonet:info"]["uuid"]
                title = md.get("defaultTitle")
                template = md.get("isTemplate") == "y"
                state = None
                if "mdStatus" in md:  # workflow enabled
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
                    state = WorkflowState(stage=stage, status=status)
                    log.debug(f"Workflow state: {state}")
                rec = Record(uuid=uuid, title=title, template=template, state=state)
                log.debug(f"Record: {rec}")
                recs.append(rec)
            records += recs
            to = int(rsp.get("@to"))

        return records

    def get_record(self, uuid: str) -> etree._ElementTree:
        # log.debug(f"Processing record: {record}")
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

    def _extract_uuid_from_put_response(self, payload: dict):
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
        """
        metadata_infos = payload.get("metadataInfos")
        if not metadata_infos:
            return None

        uuid_match = None
        for md_info in metadata_infos.values():
            for info in md_info:
                message = info.get("message")
                uuid_match = re.search(
                    r"'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})'", message
                )
                if uuid_match:
                    uuid_match = uuid_match.group(1)
                    break

        return uuid_match

    def put_record(
        self,
        uuid: str,
        metadata: str,
        template: bool,
        group: int | None,
        uuid_processing: str = "GENERATEUUID",
    ) -> dict:
        log.debug(f"Duplicating record {uuid}: template={template}, group={group}")
        r = self.session.put(
            f"{self.api}/records",
            headers={"Accept": "application/json", "Content-type": "application/xml"},
            params={
                "uuidProcessing": uuid_processing,
                "group": group,
                "metadataType": "TEMPLATE"
                if template
                else "METADATA",  # FIXME: other metadataType ?
            },
            data=metadata,
        )
        r.raise_for_status()
        data = r.json()
        data["new_record_uuid"] = self._extract_uuid_from_put_response(data)
        return data

    def update_record(
        self, uuid: str, metadata: str, template: bool, state: WorkflowState | None = None
    ):
        # PUT /records doesn't work as expected: it delete/recreates the record instead
        # of updating in place, hence losing Geonetwork-specific record metadata like
        # workflow state or access rights.
        # So instead we pretend to be the Geonetwork UI and "edit" the XML view of the
        # record, ignoring the returned editor view and immediately saving our new
        # metadata as the "edit" outcome.
        log.debug(f"Updating record {uuid}: template={template}, state={state}")

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
            "withAttributes": "false",
            "withValidationErrors": "false",
            "commit": "true",
            "terminate": "true",
            "template": "y" if template else "n",
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
                    "changeMessage": "Approved by Migrator",
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
        log.debug(f"Adding group: {name}")
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


class MefArchive:
    def __init__(self, compression=zipfile.ZIP_DEFLATED):
        self.zipb = io.BytesIO()
        self.zipf = zipfile.ZipFile(self.zipb, "w", compression=compression)

    def add(self, uuid: str, record: str, info: str):
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
