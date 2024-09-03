import io
import logging
import requests
import zipfile

from dataclasses import dataclass
from lxml import etree
from lxml.builder import E

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)


@dataclass
class Record:
    uuid: str
    title: str
    template: bool


class GeonetworkClient:

    def __init__(
            self, url,
            username: str | None = None, password: str | None = None
    ):
        self.url = url
        self.api = f"{self.url}/api"
        self.session = requests.Session()
        if username and password:
            self.session.auth = (username, password)
            log.debug(f"Authenticating as: {username}")
        self.authenticate()

    def authenticate(self):
        r = self.session.post(f"{self.api}/info?_content_type=json&type=me")
        # don't abort on error here, it's expected
        xsrf_token = r.cookies.get('XSRF-TOKEN')
        if xsrf_token:
            self.session.headers.update({'X-XSRF-TOKEN': xsrf_token})
        log.debug(f"XSRF token: {xsrf_token}")

    def get_records(self, query=None) -> list[Record]:
        params = {
            '_content_type': 'json',
            'buildSummary': 'false',
            'fast': 'index',    # needed to get info such as title
            'sortBy': 'title',  # FIXME: or changeDate?
            'sortOrder': 'reverse'
        }
        if query:
            params |= query

        # TODO: if _isTemplate is missing, it only returns records (not both like I'd expect)
        # => make template param explicit to force a choice?

        records = []
        to = 0
        while True:
            r = self.session.get(
                f"{self.api}/q",
                headers = {'Accept': 'application/json'},
                params = params | {'from': to+1}
            )
            r.raise_for_status()
            rsp = r.json()
            mds = rsp.get('metadata')
            if not mds:
                break
            if 'geonet:info' in mds:
                # When returning a single record, metadata isn't a list :/
                mds = [mds]
            recs = []
            for md in mds:
                log.debug("Record:", md)
                uuid = md['geonet:info']['uuid']
                title = md.get('defaultTitle')
                template = md.get('isTemplate') == 'y'
                recs.append(Record(uuid=uuid, title=title, template=template))
            records += recs
            to = int(rsp.get('@to'))

        return records

    def get_record(self, uuid: str) -> etree._ElementTree:
        # log.debug(f"Processing record: {record}")
        r = self.session.get(
            f"{self.api}/records/{uuid}/formatters/xml",
            headers = {'Accept': 'application/xml'},
            params = {
                'addSchemaLocation': 'true',  # FIXME: needed?
                'increasePopularity': 'false',
                'withInfo': 'true',
                'attachment': 'false',
                'approved': 'true'  # FIXME: true or false?
            }
        )
        r.raise_for_status()
        return etree.fromstring(r.content, parser=None)


    def duplicate_record(self, uuid: str, metadata: str, template: bool, group: int):
        log.debug(f"Duplicating record {uuid}: template={template}, group={group}")
        r = self.session.put(
            f"{self.api}/records",
            headers = {
                'Accept': 'application/json',
                'Content-type': 'application/xml'
            },
            params = {
                'uuidProcessing': 'GENERATEUUID',
                'group': group,
                'metadataType': 'TEMPLATE' if template else 'METADATA',  # FIXME: other metadataType ?
                # TODO: 'category' ?
                # TODO: 'rejectIfInvalid' ?
            },
            data = metadata
        )
        r.raise_for_status()

    def update_record(self, uuid: str, metadata: str, template: bool):
        # PUT /records doesn't work as expected: it delete/recreates the record instead
        # of updating in place, hence losing Geonetwork-specific record metadata like
        # workflow status or access rights.
        # So instead we pretend to be the Geonetwork UI and "edit" the XML view of the
        # record, ignoring the returned editor view and immediately saving our new
        # metadata as the "edit" outcome.
        log.debug(f"Updating record {uuid}: template={template}")

        r = self.session.get(
            f"{self.api}/records/{uuid}/editor",
            headers = {'Accept': 'application/xml'},
            params = {
                'currTab': 'xml',
                'withAttributes': 'false'  # FIXME: needed? true/false?
            }
        )
        r.raise_for_status()

        # API expects x-www-form-urlencoded here
        data = {
            'tab': 'xml',
            'withAttributes': 'false',
            'withValidationErrors': 'false',
            'commit': 'true',
            'terminate': 'true',
            'template': 'y' if template else 'n',
            'data': metadata
        }
        r = self.session.post(
            f"{self.api}/records/{uuid}/editor",
            data = data
        )
        r.raise_for_status()

    def get_sources(self) -> dict:
        r = self.session.get(
            f"{self.api}/sources",
            headers = {'Accept': 'application/json'}
        )
        r.raise_for_status()
        sources = {s['uuid']: s['name'] for s in r.json()}
        return sources


class MefArchive:

    def __init__(self, compression=zipfile.ZIP_DEFLATED):
        self.zipb = io.BytesIO()
        self.zipf = zipfile.ZipFile(self.zipb, 'w', compression=compression)

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
    ri = record.xpath('/gmd:MD_Metadata/geonet:info', namespaces=record.nsmap)[0]
    ri.getparent().remove(ri)
    source_id = ri.find('source').text
    info = E.info(
        E.general(
            E.createDate(ri.find('createDate').text),
            E.changeDate(ri.find('changeDate').text),
            E.schema(ri.find('schema').text),
            E.isTemplate(ri.find('isTemplate').text),
            E.localId(ri.find('id').text),
            E.format("simple"),
            E.rating(ri.find('rating').text),
            E.popularity(ri.find('popularity').text),
            E.uuid(ri.find('uuid').text),
            E.siteId(source_id),
            E.siteName(sources[source_id])
        ),
        E.categories(),
        E.privileges(),
        E.public(),
        E.private(),
        version='1.1'
    )
    return info.getroottree()
