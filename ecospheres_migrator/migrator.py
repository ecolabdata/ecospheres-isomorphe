import io
import logging
import requests
import time
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

class Migrator:

    TRANSFORMATIONS = [
        {
            "id": "all",
            "label": "Toutes les transformations",
            "xslt": None
        },
        {
            "id": "license",
            "label": "Champ licence",
            "xslt": "licence.xslt",
        },
        {
            "id": "error",
            "label": "Retournera une erreur",
            "xslt": "error.xslt",
        },
    ]

    def __init__(
        self, *, url: str, username: str | None = None, password: str | None = None
    ) -> None:
        self.url = url
        self.password = password
        self.username = username
        self.api = f"{self.url}/api"
        self.session = requests.Session()

        # TODO: add authentication

        r = self.session.post(f"{self.api}/info?_content_type=json&type=me")
        # don't abort on error here, it's expected
        self.xsrf_token = r.cookies.get('XSRF-TOKEN')
        log.debug("XSRF token:", self.xsrf_token)

    def select(self, **kwargs) -> list[Record]:
        """
        Select data to migrate based on given params
        """
        log.debug(f"Selecting with {kwargs}")

        params = {
            '_content_type': 'json',
            'buildSummary': 'false',
            'fast': 'index',    # needed to get info such as title
            'sortBy': 'title',  # FIXME: or changeDate?
            'sortOrder': 'reverse',
            '_isHarvested': 'n'
        }
        query = kwargs.get('query')
        if query:
            params |= dict(p.split('=') for p in query.split(','))

        selection = []
        to = 0
        while True:
            r = self.session.get(
                f"{self.api}/q",
                params=params|{'from': to+1},
                headers={
                    'Accept': 'application/json',
                    'X-XSRF-TOKEN': self.xsrf_token
                }
            )
            # TODO: abort_on_error logic
            r.raise_for_status()
            rsp = r.json()
            records = Migrator.list_records(rsp.get('metadata', []))
            if not records:
                break
            selection += records
            to = int(rsp.get('@to'))

        log.debug(f"Selection contains {len(selection)} items")
        return selection

    def transform(self, transformation: dict, selection: list[Record]) -> bytes:
        """
        Transform data from a selection
        """
        log.debug(f"Transforming {selection} via {transformation}")
        if transformation["id"] == "error":
            raise Exception("You asked for an error, here you are!")

        sources = self.get_sources()

        # TODO: load transformation xsl

        zipb = io.BytesIO()
        with zipfile.ZipFile(zipb, 'w', compression=zipfile.ZIP_DEFLATED) as zipf:
            for s in selection:
                record = self.get_record(s.uuid)
                info = Migrator.extract_info(record, sources)
                # TODO: apply transformation
                Migrator.add_to_zip(zipf, s.uuid, record, info)

        log.debug("Transformation done.")
        return zipb.getvalue()

    def migrate(self, output_file: bytes):
        log.debug(f"Migrating for {self.url}")
        time.sleep(10)
        log.debug("Migration done.")

    def get_sources(self) -> dict:
        r = self.session.get(
            f"{self.api}/sources",
            headers={
                'Accept': 'application/json',
                'X-XSRF-TOKEN': self.xsrf_token
            }
        )
        r.raise_for_status()
        return {s['uuid']: s['name'] for s in r.json()}

    def get_record(self, uuid: str) -> etree.ElementTree:
        # log.debug("Processing record:", record)
        r = self.session.get(
            f"{self.api}/records/{uuid}/formatters/xml",
            params={
                'addSchemaLocation': 'true',
                'increasePopularity': 'false',
                'withInfo': 'true',
                'attachment': 'false',
                'approved': 'true'  # FIXME: true or false?
            },
            headers={
                'Accept': 'application/xml',
                'X-XSRF-TOKEN': self.xsrf_token
            }
        )
        r.raise_for_status()
        return etree.fromstring(r.content)

    @staticmethod
    def list_records(metadata: list) -> list[Record]:
        records = []
        for m in metadata:
            records.append(Record(uuid=m['geonet:info']['uuid'],
                                  title=m.get('defaultTitle')))
        return records

    @staticmethod
    def extract_info(record: etree.ElementTree, sources: dict) -> etree.ElementTree:
        e = record.xpath('/gmd:MD_Metadata/geonet:info', namespaces=record.nsmap)[0]
        e.getparent().remove(e)
        source_id = e.find('source').text
        info = E.info(
            E.general(
                E.createDate(e.find('createDate').text),
                E.changeDate(e.find('changeDate').text),
                E.schema(e.find('schema').text),
                E.isTemplate(e.find('isTemplate').text),
                E.localId(e.find('id').text),
                E.format("simple"),
                E.rating(e.find('rating').text),
                E.popularity(e.find('popularity').text),
                E.uuid(e.find('uuid').text),
                E.siteId(source_id),
                E.siteName(sources[source_id])
            ),
            E.categories(),
            E.privileges(),
            E.public(),
            E.private(),
            version='1.1'
        ).getroottree()
        return info

    @staticmethod
    def add_to_zip(zip_file: zipfile.ZipFile,
                   uuid: str,
                   record: etree.ElementTree,
                   info: etree.ElementTree):
        kwargs = {
            'pretty_print': True,
            'xml_declaration': True,
            'encoding': 'utf-8'
        }
        zip_file.writestr(f"{uuid}/info.xml", etree.tostring(info, **kwargs))
        zip_file.writestr(f"{uuid}/metadata/metadata.xml", etree.tostring(record, **kwargs))
