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


class GeonetworkClient:

    def __init__(
            self, url,
            username: str | None = None, password: str | None = None
    ):
        self.url = url
        self.api = f"{self.url}/api"
        self.session = requests.Session()
        self.authenticate()

    def authenticate(self):
        # TODO: add authentication
        r = self.session.post(f"{self.api}/info?_content_type=json&type=me")
        # don't abort on error here, it's expected
        xsrf_token = r.cookies.get('XSRF-TOKEN')
        self.session.headers.update({'X-XSRF-TOKEN': xsrf_token})
        log.debug("XSRF token:", xsrf_token)

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
            recs = [Record(uuid=m['geonet:info']['uuid'], title=m.get('defaultTitle'))
                    for m in rsp.get('metadata', [])]
            if not recs:
                break
            records += recs
            to = int(rsp.get('@to'))

        return records

    def get_record(self, uuid: str) -> etree.ElementTree:
        # log.debug("Processing record:", record)
        r = self.session.get(
            f"{self.api}/records/{uuid}/formatters/xml",
            headers = {'Accept': 'application/xml'},
            params = {
                'addSchemaLocation': 'true',
                'increasePopularity': 'false',
                'withInfo': 'true',
                'attachment': 'false',
                'approved': 'true'  # FIXME: true or false?
            }
        )
        r.raise_for_status()
        return etree.fromstring(r.content)

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

    def add(self, uuid: str, record: etree.ElementTree, info: etree.ElementTree):
        """
        Add a record to the MEF archive.

        :param uuid: Record UUID.
        :param record: Record metadata.
        :param info: Record info in MEF `info.xml` format.
        """
        kwargs = {
            'encoding': 'utf-8',
            'pretty_print': True,
            'xml_declaration': True
        }
        self.zipf.writestr(f"{uuid}/info.xml", etree.tostring(info, **kwargs))
        self.zipf.writestr(f"{uuid}/metadata/metadata.xml", etree.tostring(record, **kwargs))

    def finalize(self):
        """
        Finalize and return bytes of the full MEF archive.
        """
        self.zipf.close()
        return self.zipb.getvalue()


def extract_record_info(record: etree.ElementTree, sources: dict) -> etree.ElementTree:
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