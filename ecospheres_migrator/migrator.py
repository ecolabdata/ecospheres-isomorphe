import io
import logging
import time
import zipfile

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)


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

    def select(self, **kwargs):
        """
        Select data to migrate based on given params
        """
        log.debug(f"Selecting with {kwargs}")
        return [
            {
                "id": "1d0077f3-b62b-4863-821e-46a06ab38456",
                "title": "une fiche",
            },
            {
                "id": "6265cc1d-b4b3-4067-afb9-61c186e7a2cc",
                "title": "une autre fiche",
            }
        ]

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
