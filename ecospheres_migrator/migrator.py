import io
import logging
import requests
import time
import zipfile

from dataclasses import dataclass
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
        xsrf_token = r.cookies.get('XSRF-TOKEN')

        self.headers = {
            'Accept': 'application/json',
            'X-XSRF-TOKEN': xsrf_token
        }
        log.debug(f"Headers: {self.headers}")

    def select(self, **kwargs) -> list[Record]:
        """
        Select data to migrate based on given params
        """
        log.debug(f"Selecting with {kwargs}")

        q_params = {
            '_content_type': 'json',
            'buildSummary': 'false',
            'fast': 'index',    # needed to get info such as title
            'sortBy': 'title',  # FIXME: or changeDate?
            'sortOrder': 'reverse'
        }

        query = kwargs.get('query')
        if query:
            q_params |= dict(p.split('=') for p in query.split(','))

        selection = []
        to = 0
        while True:
            r = self.session.get(f"{self.api}/q", headers=self.headers, params=q_params|{'from': to+1})
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

    def create_dummy_output_file(self) -> bytes:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zipf:
            zipf.writestr("dummy_file1.xml", "<xml></xml>")
        zip_content = zip_buffer.getvalue()
        return zip_content


    def transform(self, transformation: dict, selection: list[dict]) -> bytes:
        """
        Transform data from a selection
        """
        log.debug(f"Transforming {selection} via {transformation}")
        if transformation["id"] == "error":
            raise Exception("You asked for an error, here you are!")
        time.sleep(10)
        output = self.create_dummy_output_file()
        log.debug("Transformation done.")
        return output

    def migrate(self, output_file: bytes):
        log.debug(f"Migrating for {self.url}")
        time.sleep(10)
        log.debug("Migration done.")

    @staticmethod
    def list_records(metadata: list) -> list[Record]:
        records = []
        for m in metadata:
            records.append(Record(uuid=m['geonet:info']['uuid'],
                                  title=m.get('defaultTitle')))
        return records
