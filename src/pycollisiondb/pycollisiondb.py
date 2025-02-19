import os
from pathlib import Path
import json
import requests
import zipfile
import logging
from collections import defaultdict
import tempfile
from pyqn.units import Units

from .pycoll_ds import PyCollDataSet

logger = logging.getLogger(__name__)


class PyCollisionDBConnectionError(Exception):
    pass


class PyCollisionDBKeywordError(Exception):
    pass


class PyCollisionDBPlotError(Exception):
    pass


class PyCollision:

    VALID_QUERY_KEYWORDS = (
        "pk",
        "pks",
        "reaction_text",
        "reaction_texts",
        "reactant1",
        "reactant2",
        "product1",
        "product2",
        "process_types",
        "method",
        "data_type",
        "reactants",
        "products",
        "doi",
    )

    def __init__(
        self,
        archive_uuid=None,
        DB_URL="https://db-amdis.org/collisiondb/",
        DATA_DIR=None,
    ):

        self.archive_uuid = archive_uuid
        self.API_URL = os.path.join(DB_URL, "api/")
        self.REFS_API_URL = os.path.join(DB_URL, "refs/api/")

        self.DATA_DIR = DATA_DIR
        if self.DATA_DIR is None:
            self.DATA_DIR = Path(tempfile.mkdtemp())
            logger.debug(f"Created temporary DATA_DIR {self.DATA_DIR}")
        else:
            self.DATA_DIR = Path(self.DATA_DIR)

        self.dataset_dir = None
        if self.archive_uuid is not None:
            self.dataset_dir = self.DATA_DIR / self.archive_uuid

        self.archive_url = None
        self.archive_name = None
        self.archive_path = None
        self.manifest = None

        self.use_latex = False

        self.datasets = {}

    def __str__(self):
        if not self.datasets:
            return "<PyCollision object (no data)>"
        return f"<PyCollision object ({len(self.datasets)} datasets)>"

    def make_query(self, query_data):
        logger.debug("getting CSRF token ...")
        csrftoken = requests.get(self.API_URL).cookies["csrftoken"]
        header = {"X-CSRFToken": csrftoken, "referer": self.API_URL}
        cookies = {"csrftoken": csrftoken}

        data = {"query": json.dumps(query_data)}
        r = requests.post(self.API_URL, data=data, headers=header, cookies=cookies)
        if r.status_code != 200:
            raise PyCollisionDBConnectionError(
                f"Could not retrieve data: HTTP"
                f" {r.status_code} ({r.reason}) returned from {self.API_URL}"
            )
        json_response = json.loads(r.text)
        self.archive_url = json_response["archive_url"]
        logger.debug(f"Success! archive_url is {self.archive_url}")
        return self.archive_url

    def validate_query_keywords(self, keywords):
        keywords_set = set(keywords)

        if not keywords_set.issubset(self.VALID_QUERY_KEYWORDS):
            raise PyCollisionDBKeywordError(f"Invalid query keyword in {keywords}")

        if "pk" in keywords and "pks" in keywords:
            raise PyCollisionDBKeywordError(f"pk and pks not allowed {keywords}")

        if "reaction_text" in keywords and "reaction_texts" in keywords:
            raise PyCollisionDBKeywordError(
                f"reaction_text and reaction_texts not allowed {keywords}"
            )

        if "reactants" in keywords and (
            "reactant1" in keywords
            or "reactant2" in keywords
            or "reaction_text" in keywords
        ):
            raise PyCollisionDBKeywordError(
                f"Cannot specify reactant1, reactant2 or reaction_text if reactants is given"
            )

        if "products" in keywords and (
            "product1" in keywords
            or "product2" in keywords
            or "reaction_text" in keywords
        ):
            raise PyCollisionDBKeywordError(
                f"Cannot specify product1, product2 or reaction_text if products is given"
            )

    def query(self, **kwargs):
        self.validate_query_keywords(kwargs.keys())

        pk = kwargs.get("pk")
        if pk:
            del kwargs["pk"]
            kwargs["pks"] = [pk]

        reaction_text = kwargs.get("reaction_text")
        if reaction_text:
            del kwargs["reaction_text"]
            kwargs["reaction_texts"] = [reaction_text]

        if reactants := kwargs.get("reactants"):
            if len(reactants) > 2:
                raise PyCollisionDBKeywordError(
                    f"A maximum of two species can be specified in reactants"
                )
            del kwargs["reactants"]
            kwargs["reactant1"] = reactants[0]
            try:
                kwargs["reactant2"] = reactants[1]
            except IndexError:
                kwargs["reactant2"] = ""

        if products := kwargs.get("products"):
            if len(products) > 2:
                raise PyCollisionDBKeywordError(
                    f"A maximum of two species can be specified in products"
                )
            del kwargs["products"]
            kwargs["product1"] = products[0]
            try:
                kwargs["product2"] = products[1]
            except IndexError:
                kwargs["product2"] = ""
        return self.make_query(kwargs)

    def query_database_by_pk(self, pks):
        """

        Query the database for a list of CDataSet ids and return the URL
        at which the archive of filtered datasets can be obtained. This URL
        is stored as self.archive_url.

        """

        if type(pks) is int:
            pks = [pks]

        logger.debug(f"querying for pks = {pks} ...")
        query_data = {"pk": pks}

        return self.make_query(query_data)

    def query_database_by_reaction_text(self, reaction_texts):
        """

        Query the database for a list of CDataSet ids and return the URL
        at which the archive of filtered datasets can be obtained. This URL
        is stored as self.archive_url.

        """

        if type(reaction_texts) is str:
            reaction_texts = [reaction_texts]

        logger.debug(f"querying for reaction_texts = {reaction_texts} ...")
        data = {"reaction_text": reaction_texts}

        return self.make_query(data)

    def query_database_by_reactants(self, reactants):
        """

        Query the database for a list of reactants.

        """

        if type(reactants) is str:
            reactants = [reactants]

        logger.debug(f"querying for reactants = {reactants} ...")
        data = {"reactants": reactants}

        return self.make_query(data)

    def download_datasets_archive_from_url(self):
        logger.debug(f"Downloading compressed dataset archive from {self.archive_url}")
        r = requests.get(self.archive_url)
        self.archive_name = os.path.basename(self.archive_url)
        self.archive_path = self.DATA_DIR / self.archive_name
        logger.debug(f"Writing compressed dataset archive to {self.archive_path}")
        with open(self.archive_path, "wb") as fo:
            fo.write(r.content)
        return self.archive_path

    def unzip_dataset_archive(self):
        self.dataset_dir = self.DATA_DIR / os.path.splitext(self.archive_name)[0]
        logger.debug(f"Unzipping compressed dataset archive to {self.dataset_dir}...")
        with zipfile.ZipFile(self.archive_path, "r") as zip_ref:
            zip_ref.extractall(self.dataset_dir)
        return self.dataset_dir

    def get_manifest(self):
        manifest_path = self.dataset_dir / "manifest.json"
        logger.debug(f"Retrieving dataset manifest from {manifest_path}...")
        with open(manifest_path, "r") as fi:
            self.manifest = json.loads(fi.read())
        logger.debug(f'The manifest indicates {self.manifest["ndatasets"]} datasets...')
        return self.manifest

    def get_dataset_pks_by_reaction(self):
        # Invert the manifest['datasets'] directory to produce a list of dataset pks
        # for each distinct reaction.
        logger.debug(f"Retrieving dataset pks for each reaction from the manifest...")
        self.pks = defaultdict(list)
        self.all_pks = []
        for qid, reaction_text in self.manifest["datasets"].items():
            pk = int(qid[1:])
            self.all_pks.append(pk)
            self.pks[reaction_text].append(pk)
        return self.pks

    def summarize_datasets(self):
        for reaction_text, pks in self.pks.items():
            print(reaction_text)
            print("=" * 72)
            for pk in pks:
                print(f"   qid: D{pk}")
                if self.datasets:
                    metadata = self.datasets[pk].metadata
                    print("   process_types:", list(metadata["process_types"].keys()))
                    print("   data_type:", metadata["data_type"])
                    print("   refs:", metadata["refs"])
            print()

    def get_distinct_rps(self):
        self.reactant_rps, self.product_rps = set(), set()
        self.reactant_species, self.product_species = defaultdict(set), defaultdict(set)
        for ds in self.datasets.values():
            reactants = ds.reaction.reactants
            reactant_rps = set(r[1] for r in reactants)
            self.reactant_rps |= reactant_rps
            for reactant_rp in reactant_rps:
                formula = reactant_rp.formula
                self.reactant_species[formula].add(tuple(reactant_rp.states))

            products = ds.reaction.products
            product_rps = set(p[1] for p in products)
            self.product_rps |= product_rps
            for product_rp in product_rps:
                formula = product_rp.formula
                self.product_species[formula].add(tuple(product_rp.states))

    def read_all_datasets(self):
        logger.info("Reading in all dataset data...")
        self.datasets = {}
        for pk in self.all_pks:
            filepath = self.dataset_dir / f"{pk}.txt"
            self.datasets[pk] = PyCollDataSet(filepath)

    def plot_all_datasets(self, ax, **kwargs):
        self.plot_datasets(ax, self.all_pks, **kwargs)

    def plot_datasets(self, ax, pks=None, reaction_texts=None, **kwargs):
        if pks is None:
            pks = [
                pk for reaction_text in reaction_texts for pk in self.pks[reaction_text]
            ]

        data_type, columns = self._get_plot_metadata(pks)

        for pk in pks:
            self.datasets[pk].plot_dataset(ax, use_latex=self.use_latex, **kwargs)

        first_dataset = next(iter(self.datasets.values()))
        first_dataset.label_axes(ax, self.use_latex)

    def _get_plot_metadata(self, pks):
        data_type = self.datasets[pks[0]].metadata["data_type"]
        frame = self.datasets[pks[0]].metadata.get("frame", "target")
        columns = self.datasets[pks[0]].metadata["json_data"]["columns"]
        for pk in pks[1:]:
            if self.datasets[pk].metadata["data_type"] != data_type:
                raise PyCollisionDBPlotError(
                    "Data types not all the same in requested plot."
                )
            if self.datasets[pk].metadata.get("frame", "target") != frame:
                raise PyCollisionDBPlotError(
                    "Energy frames not all the same in requested plot."
                )
            if self.datasets[pk].metadata["json_data"]["columns"] != columns:
                raise PyCollisionDBPlotError(
                    "Column metadata not all the same in requested plot."
                )

        return data_type, columns

    @classmethod
    def get_datasets(cls, archive_uuid=None, query=None, **kwargs):
        if archive_uuid is None:
            assert query is not None
            pycoll = cls(**kwargs)
            pycoll.query(**query)
            pycoll.download_datasets_archive_from_url()
            pycoll.unzip_dataset_archive()
        else:
            pycoll = cls(archive_uuid, **kwargs)

        pycoll.get_manifest()
        pycoll.get_dataset_pks_by_reaction()
        pycoll.read_all_datasets()

        return pycoll

    def resolve_refs(self):
        qids = set(
            qid for ds in self.datasets.values() for qid in ds.metadata["refs"].keys()
        )

        if not qids:
            self.refs = {}

        data = {"qid": list(qids)}
        r = requests.get(self.REFS_API_URL, params=data)
        if r.status_code != 200:
            raise PyCollisionDBConnectionError(
                f"Could not retrieve data: HTTP"
                f" {r.status_code} ({r.reason}) returned from {self.REFS_API_URL}"
            )
        refs_list = json.loads(r.text)
        self.refs = {
            qid: ref_dict for ref in refs_list for qid, ref_dict in ref.items()
        }

    def convert_units(self, column_units):
        """Convert the units in all datasets.

        column_units should be a dictionary of column_name: to_units items,
        where column_name identifies the dataset column to convert (e.g. 'E',
        'sigma', and to_units is a Units object or string representing the
        units to convert to. Dimensions have to match.

        """
        for dataset in self.datasets.values():
            for column_name, to_units in column_units.items():
                dataset.convert_units(column_name, to_units)

    def validate(self, raise_exception=False):
        self.all_valid = True
        for ds in self.datasets.values():
            self.all_valid &= ds.validate(raise_exception)
        return self.all_valid
